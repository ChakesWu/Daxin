"""Invariant I7: the core sees institution CODES only; public output must never contain a real name."""
from __future__ import annotations

import csv
import re
from pathlib import Path

# Long digit runs (phone, card, id numbers) are masked, but NOT amounts: a run followed by a unit or currency word,
# or preceded by a currency symbol, is a claim the judge must still be able to read (e.g. "额度 10000000 元").
_UNIT = r"(?:元|块|圆|港元|人民币|HKD|RMB|CNY|yuan|dollars?|%|％|笔|筆|次|天|日|个|個|月|年|days?|months?|years?)"
_LONG_NUM = re.compile(rf"(?<![\d¥￥$])\d[\d ]{{6,}}\d(?!\d)(?!\s*{_UNIT})", re.I)
_EMAIL = re.compile(r"([\w.+-])[\w.+-]*@([\w-]+(?:\.[\w-]+)+)")


class AnonymityError(RuntimeError):
    pass


def mask_text(t: str) -> str:
    """Mask long digit runs (phone, card, id numbers) and e-mail addresses."""
    t = _LONG_NUM.sub(lambda m: m.group(0)[:2] + "*" * (len(m.group(0)) - 4) + m.group(0)[-2:], t or "")
    return _EMAIL.sub(lambda m: f"{m.group(1)}***@{m.group(2)}", t)


def load_names(path: Path | str) -> list[str]:
    p = Path(path)
    if not p.exists():
        return []
    with open(p, encoding="utf-8", newline="") as f:
        return [r[1].strip() for r in csv.reader(f) if len(r) > 1 and r[0].strip().lower() != "code" and r[1].strip()]


def assert_clean(texts: dict[str, str], names: list[str]) -> None:
    """Refuse to release output that contains any listed name. An empty name list is itself an error: nothing can be guaranteed."""
    if not names:
        raise AnonymityError("没有机构名称对照表（private/institution_map.csv），无法保证输出不含机构名称。")
    hits = sorted({(fn, nm) for fn, t in texts.items() for nm in names if nm.lower() in t.lower()})
    if hits:
        raise AnonymityError(f"输出含机构名称，已拒绝：{hits}")
