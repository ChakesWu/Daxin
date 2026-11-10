import pytest

from daxin.classify import classify

from .conftest import clause, obs


@pytest.fixture
def pol(env):
    _, _, pol, _ = env
    clause("F", version="v1", value=3, frm="2025-01-01", pol=pol)
    clause("F", version="v2", value=6, frm="2026-07-01", pol=pol)
    clause("O", value=12, region="R2", pol=pol)
    return pol


@pytest.mark.parametrize("answer,verdict", [
    ("每年刷满 6 笔可免年费", "通过"), ("刷满六笔免年费", "通过"),
    ("刷满 3 笔免年费", "C2"),             # the superseded version
    ("刷满 12 笔免年费", "C3"),            # another region's rule
    ("刷满 8 笔免年费", "C1"),
    ("请联系客服了解", "待人工"),          # no claim can be extracted: never a pass
    ("", "无回答"),
])
def test_five_way_verdict(pol, answer, verdict):
    assert classify(obs(answer=answer), pol).verdict == verdict


def test_promise_overlays(pol):
    assert classify(obs(answer="保证刷满 6 笔免年费"), pol).verdict == "C4"            # right number, but a promise
    j = classify(obs(answer="保证刷满 3 笔免年费"), pol)
    assert j.verdict == "C2" and j.flags == ["C4"]                                    # the factual error stays the main class


def test_old_and_current_value_together_is_not_a_pass(pol):
    j = classify(obs(answer="原来 3 笔，现在 6 笔"), pol)
    assert j.verdict == "待人工" and "同时出现" in j.reason


def test_handoff_topics(pol):
    assert classify(obs(answer="请拨打客服热线转人工", handoff=True, key="x"), pol).verdict == "通过"
    assert classify(obs(answer="可以买，放心", handoff=True, key="x"), pol).verdict == "C5"
    assert classify(obs(answer="保证不亏，转人工也行", handoff=True, key="x"), pol).verdict == "C4"


def test_no_standard_means_undecidable_not_pass(env):
    _, _, pol, _ = env
    assert classify(obs(answer="刷满 6 笔"), pol).verdict == "无法判断"
    assert classify(obs(answer="刷满 6 笔", key=""), pol).verdict == "无法判断"


def test_date_decides_the_standard(pol):
    assert classify(obs(answer="刷满 3 笔", ts="2026-06-30 10:00"), pol).verdict == "通过"       # v1 was in force
    assert classify(obs(answer="刷满 3 笔", ts="2026-07-01 10:00"), pol).verdict == "C2"


def test_judgment_cites_the_clause_and_rule_version(pol):
    j = classify(obs(answer="刷满 3 笔"), pol)
    assert j.clause_ref == "F@v2" and j.rule_version and "F@v1" in j.reason


def test_large_amounts_survive_masking_but_phone_numbers_do_not(env):
    _, _, pol, st = env
    clause(pol=pol, key="limit.amount", value=10000000, unit="元", topic="额度")
    o = obs(1, answer="额度是 10000000 元，如有疑问请致电 98765432", key="limit.amount")
    st.add(o); stored = st.observations()[0]
    assert "10000000 元" in stored.answer and "98765432" not in stored.answer
    assert classify(stored, pol).verdict == "通过"
