import json
from datetime import date

import pytest

from daxin.draft import DraftFact, draft_facts, evaluate, numbers_in, to_clauses, validate
from daxin.llm import LLMClient, LLMError, ReplayClient

SRC = """第1条 R1 地区示例卡持卡人，自 2026 年 7 月 1 日起，每年消费满 6 笔即可免次年年费。
第2条 示例卡年费为每年 三百 元。
第3条 活动礼品价值不作保证。"""


def raw(**kw):
    d = {"key": "fee_waiver.min_purchases", "topic": "年费免除", "value": 6, "op": "=", "unit": "笔", "condition": "", "product": "示例卡",
         "region": "R1", "channel": None, "effective_from": "2026-07-01", "quote": "每年消费满 6 笔即可免次年年费"}
    d.update(kw)
    return d


def test_valid_draft_is_accepted_with_position():
    f, why = validate(raw(), SRC)
    assert why == "" and f.value == 6 and SRC[f.quote_at:].startswith("每年消费满")
    assert any("示例卡" in w for w in f.warnings)          # product not in the quote: flagged for the human


def test_quote_must_be_verbatim():
    assert validate(raw(quote="每年消费满六笔即可免年费"), SRC)[1] == "quote_not_verbatim"
    assert validate(raw(quote="每年消费满 6 笔，即可免次年年费"), SRC)[1] == "quote_not_verbatim"


def test_whitespace_differences_are_tolerated():
    assert validate(raw(quote="每年消费满6笔即可免次年年费"), SRC)[1] == ""


def test_number_must_be_in_the_quote():
    assert validate(raw(value=8), SRC)[1] == "number_not_in_quote"


def test_chinese_numeral_in_quote_counts():
    f, why = validate(raw(key="fee.annual", value=300, unit="元", quote="示例卡年费为每年 三百 元"), SRC)
    assert numbers_in("三百") == [300.0] and why == ""


@pytest.mark.parametrize("patch,why", [({"quote": ""}, "no_quote"), ({"quote": "年费"}, "quote_too_short"), ({"key": "Fee Waiver"}, "bad_key"),
                                       ({"op": "~"}, "bad_op"), ({"value": "六"}, "bad_value"), ({"value": True}, "bad_value"),
                                       ({"effective_from": "soon"}, "bad_date")])
def test_other_rejections(patch, why):
    assert validate(raw(**patch), SRC)[1] == why


class Fake(LLMClient):
    def __init__(self, replies):
        super().__init__(); self.replies = list(replies); self.calls = 0

    def chat(self, messages, json_mode=True):
        self.calls += 1
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def test_draft_facts_filters_and_dedups():
    reply = "```json\n" + json.dumps({"facts": [raw(), raw(), raw(value=8), raw(quote="编造的句子不在原文里")]}) + "\n```"
    res = draft_facts(SRC, Fake([reply]))
    assert len(res.accepted) == 1 and [r.reason for r in res.rejected] == ["number_not_in_quote", "quote_not_verbatim"]


def test_bad_json_and_llm_error_are_recorded_not_swallowed_as_success():
    res = draft_facts(SRC, Fake(["not json at all"]))
    assert res.accepted == [] and res.errors
    res = draft_facts(SRC, Fake([LLMError("boom")]))
    assert res.accepted == [] and "boom" in res.errors[0]


def test_drafts_are_unconfirmed_and_need_a_date():
    res = draft_facts(SRC, Fake([json.dumps({"facts": [raw(), raw(key="fee.annual", value=300, unit="元", effective_from=None,
                                                                 quote="示例卡年费为每年 三百 元")]})]))
    cs = to_clauses(res, "DOC-1")
    assert len(cs) == 1 and cs[0].status == "draft" and cs[0].text.startswith("每年消费满")      # the dateless one is skipped
    cs = to_clauses(res, "DOC-1", default_effective_from=date(2026, 1, 1))
    assert len(cs) == 2 and all(c.status == "draft" for c in cs)


def test_drafts_enter_the_policy_as_drafts_only(env):
    res = draft_facts(SRC, Fake([json.dumps({"facts": [raw()]})]))
    for c in to_clauses(res, "DOC-1"):
        env[2].add(c, "llm")
    assert [c.status for c in env[2].clauses()] == ["draft"] and env[2].clauses(("frozen",)) == []


def test_replay_roundtrip(tmp_path, monkeypatch):
    c = LLMClient(record_dir=tmp_path)
    monkeypatch.setattr(c, "_post", lambda body: {"choices": [{"message": {"content": json.dumps({"facts": [raw()]})}}]})
    assert len(draft_facts(SRC, c).accepted) == 1
    assert len(draft_facts(SRC, ReplayClient(tmp_path)).accepted) == 1
    with pytest.raises(LLMError):
        ReplayClient(tmp_path).chat([{"role": "user", "content": "never recorded"}])


def test_evaluate_counts_real_hits_misses_and_extras():
    got = [DraftFact(key="a", value=6, unit="笔", quote="q" * 8), DraftFact(key="b", value=99, unit="元", quote="q" * 8)]
    key = [{"value": 6, "unit": "笔"}, {"value": 12, "unit": "笔"}, {"value": 8, "unit": "笔", "optional": True}]
    r = evaluate(got, key)
    assert (r["true_positive"], r["n_key"], r["precision"], r["recall"]) == (1, 2, 0.5, 0.5) and len(r["extra"]) == 1 and len(r["missed"]) == 1


def test_lenient_matching_ignores_unit_period_and_scope_suffix():
    got = [DraftFact(key="a", value=20000, unit="元/天", scope={"region": "R2 地区"}, quote="q" * 8)]
    key = [{"value": 20000, "unit": "元", "region": "R2"}]
    assert evaluate(got, key)["true_positive"] == 0 and evaluate(got, key, lenient=True)["true_positive"] == 1


def test_recorded_run_replays_offline_and_matches_the_reported_numbers():
    from pathlib import Path
    here = Path(__file__).parent.parent / "testkit" / "draft_eval"
    res = draft_facts((here / "policy_doc_仿真.txt").read_text(encoding="utf-8"), ReplayClient(here / "raw"))
    key = json.loads((here / "answer_key.json").read_text(encoding="utf-8"))["facts"]
    assert len(res.accepted) == 12 and not res.rejected and not res.errors
    assert (evaluate(res.accepted, key)["true_positive"], evaluate(res.accepted, key, lenient=True)["true_positive"]) == (3, 11)
