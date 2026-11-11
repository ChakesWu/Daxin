from daxin.accuracy import compare, from_store, markdown
from daxin.classify import classify

from .conftest import clause, obs


def test_compare_counts_the_dangerous_cell_and_abstentions():
    pairs = [("通过", "通过")] * 8 + [("C1", "通过")] * 2 + [("C1", "C1")] * 4 + [("C2", "C1")] + [("C3", "待人工")] * 5
    r = compare(pairs)
    assert r["n"] == 20 and r["abstain"]["k"] == 5
    assert (r["false_pass"]["k"], r["false_pass"]["n"]) == (2, 10)            # machine said pass 10 times, 2 were wrong
    assert (r["errors_passed"]["k"], r["errors_passed"]["n"]) == (2, 12)       # 12 human-confirmed errors, 2 passed
    assert r["agreement_on_decided"]["k"] == 12 and r["agreement_on_decided"]["n"] == 15
    assert r["per_class"]["C1"]["precision"]["k"] == 4 and r["per_class"]["C1"]["precision"]["n"] == 5
    lo, hi = r["false_pass"]["wilson95"]
    assert 0 < lo < 0.2 < hi < 1                                               # an interval, never a bare point estimate


def test_empty_gold_set_does_not_crash_or_invent_numbers():
    r = compare([])
    assert r["n"] == 0 and r["agreement_on_decided"]["rate"] is None and r["kappa_on_decided"] is None
    assert "黄金集样本 0 条" in markdown(r)


def test_from_store_uses_only_agreed_human_verdicts(env):
    _, _, pol, st = env
    clause(pol=pol)
    cases = [("刷满 6 笔免年费", "通过", "通过"), ("刷满 8 笔免年费", "C1", "C1"), ("刷满 6 笔免年费", "C1", "C1"),   # last: machine says pass, humans say C1
             ("多少都行", "C1", "C1")]
    for i, (ans, a, b) in enumerate(cases, 1):
        o = obs(i, answer=ans); st.add(o); st.save_judgment(classify(o, pol))
        st.add_review(o.obs_id, "甲", a); st.add_review(o.obs_id, "乙", b)
    o = obs(9, answer="刷满 6 笔免年费"); st.add(o); st.save_judgment(classify(o, pol))
    st.add_review(o.obs_id, "甲", "通过"); st.add_review(o.obs_id, "乙", "C1")      # disputed: not gold
    r = from_store(st)
    assert r["n_gold"] == 4 and r["n_reviewed_not_in_gold"] == 1
    assert r["false_pass"]["k"] == 1 and r["false_pass"]["n"] == 2 and r["abstain"]["k"] == 1
    assert r["reviewer_agreement"]["n"] == 5 and r["reviewer_agreement"]["k"] == 4
