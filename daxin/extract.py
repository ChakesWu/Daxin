"""Claim extraction (layers L1 and L2 of the architecture): deterministic rules and lexicons. No model is involved.

Limits (see docs): digits, Chinese numerals up to 999, English and Portuguese number words up to 999 (language packs in
lang.py: zh-Hans, zh-Hant, en, pt), common units, percentages; ordinals, fractions and multi-condition
sentences are not understood. When nothing can be extracted the caller must treat the answer as 'pending human', never as a pass.
"""
from __future__ import annotations

import re

_D = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "兩": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
NUM = r"(?:\d+(?:\.\d+)?|[零〇一二两兩三四五六七八九十百]+)"
from . import lang as L


def _word_number(tok: str, words: dict[str, int]) -> float | None:
    """'twelve' -> 12, 'twenty one' / 'twenty-one' -> 21, 'two hundred' -> 200, 'cento e vinte' -> 120, 'doze' -> 12."""
    parts = [p for p in re.split(r"[\s-]+", tok.lower()) if p and p not in ("e", "and")]
    if not parts:
        return None
    cur = 0
    for p in parts:
        if p == "hundred":
            cur = (cur or 1) * 100
        elif p in words:
            cur += words[p]
        else:
            return None
    return float(cur)


def _word_num_re(words: dict[str, int]) -> str:
    w = "|".join(sorted(map(re.escape, list(words) + ["hundred"]), key=len, reverse=True))
    return rf"(?:(?:{w})(?:(?:\s+(?:e|and)\s+|[\s-]+)(?:{w}))*)"


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


def _num(tok: str, words: dict[str, int] | None = None) -> float | None:
    if tok[0].isdigit():
        return float(tok)
    v = cn_to_number(tok)
    return v if v is not None or not words else _word_number(tok, words)


def claim_spans(text: str, unit: str = "", lang: str = "") -> list[tuple[int, int, float]]:
    """(start, end, value) of each number the answer states with `unit`, read with the answer's language pack."""
    text = text or ""
    words = L.number_words(lang)
    num = rf"(?:{NUM}|\b{_word_num_re(words)}\b)" if words else NUM
    if unit:
        u = L.unit_re(unit, lang)
        if not u:
            return []
        m_ = L.measure_re(lang)
        pats = [rf"({num})\s*(?:(?:{m_})\s*)?(?:{u})" if m_ else rf"({num})\s*(?:{u})"]
        lead = L.lead_re(unit, lang)
        if lead:
            pats.append(rf"(?:{lead})\s*({num})")
    else:
        pats = [rf"({NUM})"]
    hits = []
    for p in pats:
        for m in re.finditer(p, text, re.I):
            v = _num(m.group(1), words)
            if v is not None:
                hits.append((m.start(), m.end(), v))
    hits.sort()
    out: list[tuple[int, int, float]] = []
    for h in hits:
        if not out or h[0] >= out[-1][1]:
            out.append(h)
    return out


def claim_values(text: str, unit: str = "", lang: str = "") -> list[float]:
    """Numbers the answer states, tied to `unit` when the unit is known (so '3 days' is not read as a count of purchases)."""
    out: list[float] = []
    for _, _, v in claim_spans(text, unit, lang):
        if v not in out:
            out.append(v)
    return out


def promises(text: str, lang: str = "") -> bool:
    return bool(L.lexicon("promise", lang).search(text or ""))


def hands_off(text: str, lang: str = "") -> bool:
    return bool(L.lexicon("handoff", lang).search(text or ""))
