from datetime import date

from daxin.classify import classify
from daxin.coverage import report
from daxin.questions import generate, summary
from daxin.release import matrix

from .conftest import clause, obs


def policy_with_boundaries(pol):
    clause(pol=pol, cid="FEE-R1-old", version="v1", value=8, frm="2026-01-01", region="R1")
    clause(pol=pol, cid="FEE-R1-old", version="v2", value=6, frm="2026-07-01", region="R1")
    clause(pol=pol, cid="FEE-R2", version="v1", value=12, frm="2026-01-01", region="R2")


def test_generation_covers_basic_boundary_and_paraphrase(env):
    policy_with_boundaries(env[2])
    qs = generate(env[2], day=date(2026, 11, 3))
    s = summary(qs)
    assert s["basic"] == 2 and s["paraphrase"] == 4          # one basic + two paraphrases per in-force fact
    b = [q for q in qs if q.kind == "boundary"]
    assert {q.target for q in b} == {"C2", "C3"}
    c2 = next(q for q in b if q.target == "C2")
    assert c2.expected == 6 and "8" in c2.text and c2.clause_ref == "FEE-R1-old@v2"
    c3 = next(q for q in b if q.target == "C3" and q.scope.region == "R1")
    assert c3.expected == 6 and "12" in c3.text


def test_generation_is_deterministic_and_ids_unique(env):
    policy_with_boundaries(env[2])
    a, b = generate(env[2], day=date(2026, 11, 3)), generate(env[2], day=date(2026, 11, 3))
    assert [q.qid for q in a] == [q.qid for q in b] and len({q.qid for q in a}) == len(a)


def test_drafts_and_unfrozen_clauses_get_no_questions(env):
    clause(pol=env[2], frozen=False)
    assert generate(env[2], day=date(2026, 11, 3)) == []


def test_future_version_is_not_asked_yet(env):
    clause(pol=env[2], cid="F", version="v1", value=6, frm="2026-07-01")
    clause(pol=env[2], cid="F", version="v2", value=5, frm="2027-01-01")
    qs = generate(env[2], day=date(2026, 11, 3))
    assert {q.expected for q in qs} == {6}


def _pass_n(env, n, key, region="R1", start=1):
    _, _, pol, st = env
    for i in range(n):
        o = obs(start + i, answer="刷满 6 笔免年费", ts=f"2026-11-03 10:{i % 60:02d}", key=key, region=region)
        st.add(o); st.save_judgment(classify(o, pol))
        for who in ("甲", "乙"):
            st.add_review(o.obs_id, who, "通过")


def test_coverage_untested_fact_caps_topic_at_l3(env):
    _, _, pol, st = env
    clause(pol=pol, cid="A", key="fee_waiver.min_purchases")
    clause(pol=pol, cid="B", key="fee.annual", value=300, unit="元")        # same topic, never tested
    _pass_n(env, 80, "fee_waiver.min_purchases")
    cov = report(pol, st)
    assert cov["年费免除"].ceiling == "L3" and len(cov["年费免除"].untested) == 1
    (row,) = matrix(pol, st)
    assert row.level == "L3" and "覆盖不足" in "；".join(row.reasons)


def test_fully_tested_topic_is_not_capped(env):
    _, _, pol, st = env
    clause(pol=pol)
    _pass_n(env, 80, "fee_waiver.min_purchases")
    assert report(pol, st)["年费免除"].ceiling is None
    assert matrix(pol, st)[0].level == "L1"


def test_topic_with_no_observations_is_l4(env):
    _, _, pol, st = env
    clause(pol=pol, cid="A", topic="挂失")
    clause(pol=pol, cid="B", key="fee_waiver.min_purchases", topic="年费免除")
    _pass_n(env, 80, "fee_waiver.min_purchases")
    rows = {r.topic: r for r in matrix(pol, st)}
    assert rows["挂失"].level == "L4" and "没有经人工判定" in rows["挂失"].reasons[0]


def test_superseded_versions_do_not_count_as_untested(env):
    _, _, pol, st = env
    clause(pol=pol, cid="F", version="v1", value=8, frm="2026-01-01")
    clause(pol=pol, cid="F", version="v2", value=6, frm="2026-07-01")
    _pass_n(env, 5, "fee_waiver.min_purchases")
    assert report(pol, st)["年费免除"].untested == []
