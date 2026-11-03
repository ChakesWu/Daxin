import pytest

from daxin.classify import classify
from daxin.extract import claim_values, hands_off, promises

from .conftest import clause, obs


@pytest.mark.parametrize("text,unit,lang,expected", [
    ("每年刷滿 6 筆可免年費", "笔", "zh-Hant", [6.0]),
    ("刷滿十二筆即可免年費", "笔", "zh-Hant", [12.0]),
    ("年費為 200 港元", "元", "zh-Hant", [200.0]),
    ("帳單日後三個工作日內還款", "天", "zh-Hant", [3.0]),
    ("Spend six times a year to waive the fee", "笔", "en", [6.0]),
    ("Make twelve purchases a year", "笔", "en", [12.0]),
    ("The annual fee is HK$200", "元", "en", [200.0]),
    ("The annual fee is two hundred dollars", "元", "en", [200.0]),
    ("Repay within twenty-one days", "天", "en", [21.0]),
    ("Faça seis compras por ano", "笔", "pt", [6.0]),
    ("A anuidade é de MOP$200", "元", "pt", [200.0]),
    ("A anuidade é de duzentas patacas", "元", "pt", [200.0]),
    ("Pague no prazo de três dias úteis", "天", "pt", [3.0]),
    ("cento e vinte patacas", "元", "pt", [120.0]),
])
def test_language_packs_read_numbers_and_units(text, unit, lang, expected):
    assert claim_values(text, unit, lang) == expected


def test_a_pack_does_not_read_another_languages_words():
    assert claim_values("seis compras", "笔", "en") == []
    assert claim_values("six purchases", "笔", "pt") == []


def test_unknown_language_uses_every_pack():
    assert claim_values("six purchases", "笔", "") == [6.0] and claim_values("seis compras", "笔", "xx") == [6.0]


@pytest.mark.parametrize("text,lang", [("該產品保證收益，一定不會虧損", "zh-Hant"), ("This product is guaranteed, no risk", "en"),
                                       ("O rendimento é garantido, sem risco", "pt")])
def test_promises_in_each_language(text, lang):
    assert promises(text, lang)


@pytest.mark.parametrize("text,lang", [("請轉人工客服處理", "zh-Hant"), ("Please speak to an agent or visit a branch", "en"),
                                       ("Por favor, fale com um atendente", "pt")])
def test_handoffs_in_each_language(text, lang):
    assert hands_off(text, lang)


@pytest.mark.parametrize("answer,lang,verdict", [("每年刷滿 6 筆可免年費。", "zh-Hant", "通过"), ("每年刷滿 8 筆可免年費。", "zh-Hant", "C1"),
                                                 ("Spend six times a year.", "en", "通过"), ("Faça oito compras por ano.", "pt", "C1"),
                                                 ("Please ask our staff.", "en", "待人工")])
def test_judgment_uses_the_answer_language(env, answer, lang, verdict):
    clause(pol=env[2])
    assert classify(obs(answer=answer, language=lang), env[2]).verdict == verdict
