"""Claim extraction (layers L1 and L2 of the architecture): deterministic rules and lexicons. No model is involved.

Limits (see docs): digits and Chinese numerals up to 999, common units, percentages; ordinals, fractions and multi-condition
sentences are not understood. When nothing can be extracted the caller must treat the answer as 'pending human', never as a pass.
"""
from __future__ import annotations

import re

_D = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "兩": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
NUM = r"(?:\d+(?:\.\d+)?|[零〇一二两兩三四五六七八九十百]+)"
_UNITS = {
    "笔": r"(?:笔|筆|次|宗|purchases?|transactions?|times|compras?)",
    "天": r"(?:天|日|个工作日|個工作日|工作日|days?|dias?)",
    "元": r"(?:元|块|圆|港元|人民币|HKD|RMB|CNY|yuan|dollars?)",
    "%": r"(?:%|％|个百分点|percent)",
    "月": r"(?:个月|個月|月|months?|meses)",
    "年": r"(?:年|years?|anos?)",
}
_LEAD = {"元": r"(?:¥|￥|HK\$|HKD|RMB|CNY|R\$)\s*", "%": r"百分之\s*"}

PROMISE = re.compile(r"保证|一定(?:能|会|可以|不会)|绝对|絕對|肯定(?:能|会)|无风险|零风险|稳赚|保本保收益|已为您(?:批准|通过)|"
                     r"guarantee[ds]?|risk[- ]free|definitely will|garanti[ad]", re.I)
HANDOFF = re.compile(r"转人工|轉人工|人工(?:客服|服务|坐席|座席)|客服(?:热线|熱線|电话)|联系(?:客户经理|网点)|柜台|櫃檯|拨打|撥打|"
                     r"human agent|speak (?:to|with) (?:a|an) (?:agent|representative)|customer service (?:hotline|line)|atendente|falar com", re.I)


def cn_to_number(s: str) -> float | None:
    """'十二' -> 12, '二十五' -> 25, '一百二十' -> 120, '六' -> 6. None if it is not a numeral."""
    if not s or any(ch not in _D and ch not in "十百" for ch in s):
        return None
    total, cur, seen_unit = 0, 0, False
    for ch in s:
        if ch in _D:
            cur = _D[ch]
        elif ch == "十":
            total += (cur or 1) * 10; cur = 0; seen_unit = True
        elif ch == "百":
            total += (cur or 1) * 100; cur = 0; seen_unit = True
    return float(total + cur) if (seen_unit or len(s) == 1) else None


def _num(tok: str) -> float | None:
    return float(tok) if tok[0].isdigit() else cn_to_number(tok)


def claim_values(text: str, unit: str = "") -> list[float]:
    """Numbers the answer states, tied to `unit` when the unit is known (so '3 days' is not read as a count of purchases)."""
    text = text or ""
    if unit in _UNITS:
        pats = [rf"({NUM})\s*(?:个|個)?\s*{_UNITS[unit]}"]
        if unit in _LEAD:
            pats.append(rf"{_LEAD[unit]}({NUM})")
        hits = [(m.start(), m.group(1)) for p in pats for m in re.finditer(p, text, re.I)]
    else:
        hits = [(m.start(), m.group(0)) for m in re.finditer(NUM, text)]
    out: list[float] = []
    for _, tok in sorted(hits):
        v = _num(tok)
        if v is not None and v not in out:
            out.append(v)
    return out


def promises(text: str) -> bool:
    return bool(PROMISE.search(text or ""))


def hands_off(text: str) -> bool:
    return bool(HANDOFF.search(text or ""))
