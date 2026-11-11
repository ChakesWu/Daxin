import json
from datetime import date

from daxin.claims import LLMTagger
from daxin.classify import classify
from daxin.llm import LLMClient, LLMError

from .conftest import clause, obs


class Fake(LLMClient):
    def __init__(self, reply):
        super().__init__(); self.reply, self.calls = reply, 0

    def chat(self, messages, json_mode=True):
        self.calls += 1
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


ANS = "每日取现限额 50000 元，手续费每笔最低 10 元。"


def setup(env):
    _, _, pol, _ = env
    clause(pol=pol, cid="L", key="withdrawal.daily_limit", value=50000, unit="元", topic="取现限额", region="R1")
    clause(pol=pol, cid="F", key="withdrawal.min_fee", value=10, unit="元", topic="取现手续费", region="R1")
    return pol


def tags(*items):
    return json.dumps({"tags": [dict(index=0, about="other_fact", fact_key="withdrawal.min_fee", quote="手续费每笔最低 10 元") | i for i in (items or ({},))]})


def test_without_a_tagger_the_second_number_forces_pending_human(env):
    pol = setup(env)
    assert classify(obs(answer=ANS, key="withdrawal.daily_limit"), pol).verdict == "待人工"


def test_a_verified_tag_removes_the_needless_abstention(env):
    pol = setup(env)
    j = classify(obs(answer=ANS, key="withdrawal.daily_limit"), pol, LLMTagger(Fake(tags()), pol))
    assert j.verdict == "通过" and j.rule_version.endswith("+llm")


def test_the_model_cannot_excuse_a_number_that_is_not_that_facts_value(env):
    pol = setup(env)
    wrong = "每日取现限额 50000 元，手续费每笔最低 12 元。"                  # 12 is not the value of withdrawal.min_fee
    j = classify(obs(answer=wrong, key="withdrawal.daily_limit"), pol, LLMTagger(Fake(tags(dict(quote="手续费每笔最低 12 元"))), pol))
    assert j.verdict == "待人工"


def test_quote_must_be_verbatim_and_cover_the_number(env):
    pol = setup(env)
    for bad in (dict(quote="手续费是十元"), dict(quote="每日取现限额 50000 元"), dict(quote="")):
        assert classify(obs(answer=ANS, key="withdrawal.daily_limit"), pol, LLMTagger(Fake(tags(bad)), pol)).verdict == "待人工", bad


def test_the_model_can_never_excuse_the_standard_value_or_invent_a_pass(env):
    pol = setup(env)
    wrong_only = "每日取现限额 30000 元，手续费每笔最低 10 元。"
    j = classify(obs(answer=wrong_only, key="withdrawal.daily_limit"), pol,
                 LLMTagger(Fake(json.dumps({"tags": [dict(index=0, about="none", quote="每日取现限额 30000 元")]})), pol))
    assert j.verdict != "通过"                                                # 30000 is no value of any fact, but the real claim is still wrong


def test_tagger_failure_falls_back_to_rules(env):
    pol = setup(env)
    t = LLMTagger(Fake(LLMError("down")), pol)
    assert classify(obs(answer=ANS, key="withdrawal.daily_limit"), pol, t).verdict == "待人工" and t.notes


def test_tagger_is_not_called_when_nothing_is_unexplained(env):
    pol = setup(env)
    f = Fake(tags())
    classify(obs(answer="每日取现限额 50000 元。", key="withdrawal.daily_limit"), pol, LLMTagger(f, pol))
    assert f.calls == 0
