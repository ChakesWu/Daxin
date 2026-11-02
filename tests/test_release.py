from datetime import date

from daxin.classify import classify
from daxin.release import matrix

from .conftest import clause, obs


def fill(env, n, errors=0, start=1, day="2026-11-03", **kw):
    _, _, pol, st = env
    for i in range(n):
        wrong = i < errors
        o = obs(start + i, answer="刷满 8 笔免年费" if wrong else "刷满 6 笔免年费", ts=f"{day} 10:{i % 60:02d}", **kw)
        st.add(o); st.save_judgment(classify(o, pol))
        for who in ("甲", "乙"):
            st.add_review(o.obs_id, who, "C1" if wrong else "通过")
    return start + n


def setup(env):
    clause(pol=env[2])


def level(env, **kw):
    (row,) = matrix(env[2], env[3], **kw)
    return row


def test_sample_size_is_a_hard_requirement(env):
    setup(env); fill(env, 73)
    assert level(env).level == "L1" and level(env).n == 73


def test_72_clean_answers_are_not_enough_for_l1(tmp_path):
    from daxin.audit import Audit; from daxin.db import DB; from daxin.observe import Store; from daxin.policy import Policy
    db = DB(tmp_path / "x.db"); a = Audit(db); e = (db, a, Policy(db, a), Store(db, a))
    setup(e); fill(e, 72)
    assert level(e).level == "L2"


def test_small_samples_can_only_lower(env):
    setup(env); fill(env, 34)
    assert level(env).level == "L3" and "样本不足" in "；".join(level(env).reasons)


def test_a_few_answers_mean_human_only(env):
    setup(env); fill(env, 3)
    assert level(env).level == "L4"


def test_errors_lower_the_bound(env):
    setup(env); fill(env, 80, errors=4)
    r = level(env)
    assert r.k == 4 and r.level in ("L3", "L4")


def test_handoff_topics_are_always_l4(env):
    clause(pol=env[2], key="wealth.guarantee")
    _, _, pol, st = env
    for i in range(100):
        o = obs(i + 1, answer="请联系人工客服", key="wealth.guarantee", handoff=True); st.add(o)
        for who in ("甲", "乙"): st.add_review(o.obs_id, who, "通过")
    assert level(env).level == "L4"


def test_unreviewed_machine_verdicts_do_not_count(env):
    setup(env); _, _, pol, st = env
    for i in range(100):
        o = obs(i + 1); st.add(o); st.save_judgment(classify(o, pol))      # judged by the machine, never reviewed
    r = level(env)
    assert r.n == 0 and r.level == "L4" and r.unreviewed == 100


def test_an_open_high_risk_finding_caps_the_level_until_a_retest_passes(env):
    clause(pol=env[2], key="annual_fee.amount", unit="元", value=200)
    _, _, pol, st = env
    def add(i, answer, ts):
        o = obs(i, answer=answer, key="annual_fee.amount", ts=ts); st.add(o); st.save_judgment(classify(o, pol))
        for who in ("甲", "乙"): st.add_review(o.obs_id, who, classify(o, pol).verdict)
    for i in range(1, 100):
        add(i, "年费 200 元", f"2026-11-03 10:{i % 60:02d}")
    add(200, "年费 150 元", "2026-11-04 10:00")                     # wrong: a money error is R3
    r = level(env)
    assert r.open_high == 1 and r.level == "L3" and "未关闭" in "；".join(r.reasons)
    add(201, "年费 200 元", "2026-11-05 10:00")                     # the same question passes later: closed
    r = level(env)
    assert r.open_high == 0 and r.level == "L2"


def test_a_new_standard_blocks_old_results_until_retested(env):
    _, _, pol, st = env
    setup(env); fill(env, 80)
    assert level(env).level == "L1"
    clause("FEE", version="v2", value=7, frm="2026-12-01", pol=pol)
    r = level(env)
    assert r.level == "L3" and "新版本" in "；".join(r.reasons)


def test_results_expire(env):
    setup(env); fill(env, 80)
    assert level(env, today=date(2026, 11, 10)).level == "L1"
    r = level(env, today=date(2026, 12, 20))
    assert r.level == "L3" and "过期" in "；".join(r.reasons)


def test_groups_are_never_pooled(env):
    clause(pol=env[2]); clause("O", value=12, region="R2", pol=env[2])
    fill(env, 80, region="R1")
    _, _, pol, st = env
    for i in range(5):
        o = obs(500 + i, region="R2", answer="刷满 12 笔免年费"); st.add(o)
        for who in ("甲", "乙"): st.add_review(o.obs_id, who, "通过")
    rows = {r.region: r for r in matrix(pol, st)}
    assert rows["R1"].level == "L1" and rows["R2"].level in ("L3", "L4")
