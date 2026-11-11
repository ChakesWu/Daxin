"""Module 2: auto-generate exam questions from the FROZEN policy. Deterministic, no model.

Three kinds, each carrying the expected value and the clause it comes from:
  basic      one per (fact x scope in force)
  boundary   confusable situations: another scope has a different value (aims at C3), or an older version had a different value (aims at C2)
  paraphrase same fact, different wording (stability check)
Question ids are stable hashes of their content, so regenerating never renumbers.
"""
from __future__ import annotations

import hashlib
from datetime import date

from pydantic import BaseModel

from .models import Scope
from .policy import Policy

KINDS = ("basic", "boundary", "paraphrase")


class Question(BaseModel):
    qid: str
    kind: str
    target: str = ""            # for boundary: 'C3' (other scope) or 'C2' (older version)
    fact_key: str
    topic: str
    scope: Scope
    text: str
    expected: float | str
    unit: str = ""
    clause_ref: str


def _who(s: Scope) -> str:
    return "".join(v for v in (s.region, s.product, s.channel and f"（{s.channel}）") if v) or "本行"


def _what(topic: str, cond: str, unit: str) -> str:
    return f"{topic}{('（' + cond + '）') if cond else ''}"


def _fmt(v) -> str:
    try:
        return f"{float(v):g}"
    except (TypeError, ValueError):
        return str(v)


def _qid(*parts) -> str:
    return "G-" + hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:8]


PARAPHRASE = (
    "请问{who}的{what}，具体标准是多少{unit}？",
    "我想确认一下：{who}{what}，数字是多少？",
    "{who}的{what}怎么规定的？直接告诉我数值。",
)


def generate(policy: Policy, day: date | None = None, paraphrases: int = 2) -> list[Question]:
    day = day or date.today()
    qs: list[Question] = []

    def add(**kw):
        qs.append(Question(qid=_qid(kw["kind"], kw["fact_key"], kw["scope"].model_dump_json(), kw["text"]), **kw))

    for c in policy.clauses(("frozen",)):
        if not policy._active(c, day):
            continue
        for f in c.facts:
            hit = policy.resolve(f.key, c.scope, day)
            if not hit or hit[1].ref != c.ref:      # only the version that is the standard today
                continue
            who, what = _who(c.scope), _what(c.topic, f.condition, f.unit)
            base = dict(fact_key=f.key, topic=c.topic, scope=c.scope, expected=f.value, unit=f.unit, clause_ref=c.ref)
            if f.elements:                       # eligibility / documents: ask what is required; no 'which number' boundary questions
                add(kind="basic", text=f"{who}的{what}有哪些要求？", **base)
                for t in ("请问{who}的{what}，需要满足什么条件、准备什么？", "我想办{what}，{who}要准备什么？")[:paraphrases]:
                    add(kind="paraphrase", text=t.format(who=who, what=what), **base)
                continue
            add(kind="basic", text=f"{who}的{what}是多少{f.unit}？", **base)
            for t in PARAPHRASE[:paraphrases]:
                add(kind="paraphrase", text=t.format(who=who, what=what, unit=f.unit), **base)
            for of, oc in policy.other_scope_values(f.key, c.scope, day):
                if (of.value, of.op) != (f.value, f.op):
                    add(kind="boundary", target="C3", text=f"我知道{_who(oc.scope)}的{what}是{_fmt(of.value)}{of.unit}，那{who}呢？", **base)
            old = [(of, oc) for of, oc in policy.older_values(f.key, c.scope, day) if (of.value, of.op) != (f.value, f.op)]
            if old:
                of, oc = max(old, key=lambda p: p[1].effective_from)
                add(kind="boundary", target="C2", text=f"我之前听说{who}的{what}是{_fmt(of.value)}{of.unit}，现在还是这样吗？", **base)
    return qs


def summary(qs: list[Question]) -> dict:
    return {k: sum(q.kind == k for q in qs) for k in KINDS} | {"total": len(qs)}
