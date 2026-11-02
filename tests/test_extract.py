import pytest

from daxin.extract import claim_values, cn_to_number, hands_off, promises


@pytest.mark.parametrize("s,v", [("六", 6), ("十", 10), ("十二", 12), ("二十", 20), ("二十五", 25), ("一百", 100), ("一百二十", 120), ("两", 2)])
def test_chinese_numerals(s, v):
    assert cn_to_number(s) == v


def test_not_numerals():
    assert cn_to_number("你好") is None and cn_to_number("") is None


@pytest.mark.parametrize("text,unit,expected", [
    ("每年刷满 6 笔可免年费", "笔", [6.0]), ("刷满十二笔", "笔", [12.0]), ("年费 200 元，宽限 3 天", "元", [200.0]),
    ("年费 200 元，宽限 3 天", "天", [3.0]), ("利率百分之五", "%", [5.0]), ("rate is 5%", "%", [5.0]), ("费用为 ¥120", "元", [120.0]),
    ("6 purchases per year", "笔", [6.0]), ("3 days", "天", [3.0]), ("刷3笔，6天内", "笔", [3.0]), ("没有数字", "笔", []),
    ("原来 3 笔，现在 6 笔", "笔", [3.0, 6.0]),
])
def test_claims_are_tied_to_their_unit(text, unit, expected):
    assert claim_values(text, unit) == expected


def test_without_a_unit_every_number_counts():
    assert claim_values("第 3 条，共 7 款", "") == [3.0, 7.0]


def test_lexicons():
    assert promises("该产品保证收益") and promises("It is risk-free") and not promises("请咨询客服")
    assert hands_off("请转人工处理") and hands_off("Please speak to a human agent") and not hands_off("这是答案")
