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


def test_old_value_clearly_labelled_as_old_does_not_block_a_correct_answer(pol):
    assert classify(obs(answer="原来 3 笔，现在 6 笔"), pol).verdict == "通过"
    assert classify(obs(answer="现行刷满 6 笔免年费；此前的规则（满 3 笔）已被取代。"), pol).verdict == "通过"


def test_superseded_marker_belongs_to_the_nearest_number(pol):
    assert classify(obs(answer="自 7 月起改为满 6 笔免年费（此前满 3 笔的规则已被取代）"), pol).verdict == "通过"
    assert classify(obs(answer="满 6 笔的规则已被取代，现在满 3 笔"), pol).verdict != "通过"


def test_old_value_stated_as_current_is_never_a_pass(pol):
    for a in ("原来 6 笔，现在 3 笔", "现在 3 笔，原来 6 笔"):
        assert classify(obs(answer=a), pol).verdict != "通过", a
    j = classify(obs(answer="刷满 6 笔和 5 笔免年费"), pol)
    assert j.verdict == "待人工" and "同时出现" in j.reason


@pytest.mark.parametrize("answer,why", [
    ("不需要刷满 6 笔，开卡即永久免年费", "否定"),
    ("每月刷满 6 笔免年费", "周期"),
    ("不超过 6 笔即可免年费", "方向"),
    ("至少 6 笔免年费", "方向"),
    ("不是 6 笔", "否定"),
])
def test_same_number_with_negation_period_or_direction_is_not_a_pass(pol, answer, why):
    j = classify(obs(answer=answer), pol)
    assert j.verdict == "待人工" and why in j.reason, (j.verdict, j.reason)


def test_number_after_a_negation_clause_is_still_read_in_its_own_clause(pol):
    assert classify(obs(answer="不是 3 笔，而是 6 笔"), pol).verdict == "通过"


def test_thousands_separator_is_not_read_as_a_smaller_number(env):
    _, _, pol, _ = env
    clause(pol=pol, key="limit.amount", value=1200, unit="元", topic="额度")
    assert classify(obs(answer="额度 1,200 元", key="limit.amount"), pol).verdict == "通过"
    assert classify(obs(answer="额度 200 元", key="limit.amount"), pol).verdict == "C1"


def test_other_regions_number_is_ignored_only_when_labelled_for_that_region(pol):
    assert classify(obs(answer="R1 是 6 笔，R2 是 12 笔"), pol).verdict == "通过"
    assert classify(obs(answer="R2 是 12 笔"), pol).verdict != "通过"


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


@pytest.fixture
def docs(env):
    from datetime import date
    from daxin.models import Clause, Element, Fact, Scope
    _, _, pol, _ = env
    c = Clause(id="REISSUE-DOCS", version="v1", topic="挂失补发材料", scope=Scope(region="R1", product="示例卡"), effective_from=date(2026, 1, 1),
               facts=[Fact(key="card_reissue.docs", value="身份证明、申请表",
                           elements=[Element(name="身份证明", anchors=["身份证", "护照"]), Element(name="申请表", anchors=["申请表", "填写表格"])])])
    pol.add(c, "t"); pol.confirm("REISSUE-DOCS", "v1", "t"); pol.freeze("REISSUE-DOCS", "v1", "t2")
    return pol


def test_required_elements_all_stated_is_a_pass(docs):
    j = classify(obs(answer="需要带身份证和填写申请表。", key="card_reissue.docs"), docs)
    assert j.verdict == "通过" and "全部 2 项" in j.reason
    assert classify(obs(answer="请携带护照并填一张表", key="card_reissue.docs"), docs).verdict == "待人工"      # the form is described by a word that is not an anchor


def test_missing_element_is_pending_human_not_an_error(docs):
    j = classify(obs(answer="带上身份证就可以办理", key="card_reissue.docs"), docs)
    assert j.verdict == "待人工" and "申请表" in j.reason


def test_a_denied_element_is_never_a_pass(docs):
    j = classify(obs(answer="不需要身份证，只要填写申请表", key="card_reissue.docs"), docs)
    assert j.verdict == "待人工" and "否定" in j.reason
    assert classify(obs(answer="需要身份证，无需申请表", key="card_reissue.docs"), docs).verdict == "待人工"


def test_a_promise_still_overrides_an_element_pass(docs):
    assert classify(obs(answer="身份证加申请表，保证当天办好", key="card_reissue.docs"), docs).verdict == "C4"


def test_element_facts_get_requirement_questions(docs):
    from datetime import date
    from daxin.questions import generate
    qs = generate(docs, date(2026, 11, 10))
    assert {q.kind for q in qs} == {"basic", "paraphrase"} and "有哪些要求" in qs[0].text and qs[0].expected == "身份证明、申请表"
