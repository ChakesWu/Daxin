"""Reading the words AROUND a number. The same digits can be right or wrong depending on negation, period, direction, history and scope.

Everything here is a guard: it can only turn a would-be pass into 'pending human' (or excuse a clearly labelled old/other-scope number);
it never creates a pass out of nothing. Lexicons are examples for Chinese; other languages fall through to 'pending human'.
"""
from __future__ import annotations

import re

SEG = re.compile(r"[，,；;。！!？?\n]")          # clause boundaries
SENT = re.compile(r"[。；;！!？?\n]")            # sentence boundaries

NEG = ("不需要", "无需", "無需", "不用", "不必", "不要", "没有", "沒有", "并非", "並非", "不是", "无须", "無須", "免于", "不再", "不会", "不能", "不可")
UP = ("不超过", "不超過", "最多", "至多", "以内", "以內", "不高于", "不高於", "不得超过", "上限")        # "<="
DOWN = ("至少", "不少于", "不少於", "以上", "不低于", "不低於", "起码", "起碼")                                   # ">="
HIST_PRE = ("以前", "此前", "之前", "原为", "原為", "原先", "原来", "原來", "旧规则", "旧版", "舊版", "曾经", "曾經")
HIST_POST = ("已被取代", "已取代", "已作废", "已失效", "不再适用", "已被替代", "已调整", "已被取代")
# period words and the concepts (in the fact key, topic or condition) that make them legitimate
PERIOD = {"每月": ("monthly", "month", "月"), "每个月": ("monthly", "month", "月"), "每日": ("daily", "day", "日", "天"), "每天": ("daily", "day", "日", "天"),
          "每周": ("weekly", "week", "周"), "每季": ("quarter", "季"), "每半年": ("半年", "half"), "每次": ("per_", "每次")}


def _seg_bounds(text: str, pos: int) -> tuple[int, int]:
    a = max((m.end() for m in SEG.finditer(text, 0, pos)), default=0)
    m = SEG.search(text, pos)
    return a, (m.start() if m else len(text))


def _sent_bounds(text: str, pos: int) -> tuple[int, int]:
    a = max((m.end() for m in SENT.finditer(text, 0, pos)), default=0)
    m = SENT.search(text, pos)
    return a, (m.start() if m else len(text))


def is_historical(text: str, start: int, end: int) -> bool:
    """The number is presented as an old value: a history word before it in its clause, or 'has been superseded' right after it
    with no other number in between (so the marker belongs to THIS number, not to the one before it)."""
    a, b = _seg_bounds(text, start)
    if any(w in text[a:start] for w in HIST_PRE):
        return True
    tail = text[end:min(len(text), b + 12)]
    for w in HIST_POST:
        i = tail.find(w)
        if i >= 0 and not re.search(r"\d", tail[:i]):
            return True
    return False


def is_negated(text: str, start: int) -> bool:
    """A negation word comes before the number within its clause (the number is being denied, not claimed)."""
    a, _ = _seg_bounds(text, start)
    return any(w in text[a:start] for w in NEG)


def labelled_for_other_scope(text: str, start: int, own: list[str], others: list[str]) -> bool:
    """The nearest scope word before the number (in its sentence) belongs to another scope, e.g. 'R2 ... 10'.
    A sentence that names the question's own scope last (or names none) does not excuse the number."""
    a, _ = _sent_bounds(text, start)
    before = text[a:start]
    last_own = max((before.rfind(w) for w in own if w), default=-1)
    last_other = max((before.rfind(w) for w in others if w), default=-1)
    return last_other >= 0 and last_other > last_own


def qualifier_problem(text: str, start: int, end: int, op: str, context_words: str) -> str | None:
    """Why a number equal to the standard should still NOT be passed automatically (None = nothing found).
    `context_words` = the fact's key, topic, condition: they make a period word legitimate (a 'daily limit' may say '每日')."""
    a, b = _seg_bounds(text, start)
    pre, post = text[a:start], text[end:b]
    if any(w in pre for w in NEG):
        return "该数字前有否定措辞"
    near_pre, near_post = pre[-6:], post[:4]
    for w in UP:
        if (w in near_pre or w in near_post) and op != "<=":
            return f"数字带有“{w}”的方向，与标准的比较方式不符"
    for w in DOWN:
        if (w in near_pre or w in near_post) and op != ">=":
            return f"数字带有“{w}”的方向，与标准的比较方式不符"
    for w, concepts in PERIOD.items():
        if w in pre and not any(c in context_words.lower() for c in concepts):
            return f"数字前有周期词“{w}”，标准没有这个周期"
    return None
