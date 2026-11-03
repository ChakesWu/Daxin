"""Pre-effective regression: when a new clause version is frozen with a future effective date, list what must be
re-tested and preview how the answers on record would fare on that date.

The preview is a MACHINE dry run against the upcoming standard. It is never stored as a judgment and never counts in
any rate (only human-reviewed verdicts do); its purpose is to show, before the change, which topics will break.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

from .classify import classify
from .models import Clause, Observation
from .observe import Store
from .policy import Policy


def upcoming(policy: Policy, today: date) -> list[Clause]:
    """Frozen clause versions that take effect after `today`."""
    return [c for c in policy.clauses(("frozen",)) if c.effective_from > today]


def _questions(clause: Clause, store: Store) -> list[Observation]:
    """One representative observation per distinct question asked in a situation the clause covers."""
    keys = {f.key for f in clause.facts}
    seen, out = set(), []
    for o in store.observations():
        if o.fact_key not in keys or not clause.scope.covers(o.scope()):
            continue
        k = (o.question_id, o.region, o.product, o.channel, o.language)
        if k not in seen:
            seen.add(k); out.append(o)
    return out


def plan(policy: Policy, store: Store, today: date) -> list[dict]:
    """For every upcoming clause: the questions to re-test, the deadline (the day before it takes effect) and a preview."""
    out = []
    for c in upcoming(policy, today):
        qs = _questions(c, store)
        keys = {f.key for f in c.facts}
        recorded = [o for o in store.observations() if o.fact_key in keys and c.scope.covers(o.scope())]
        preview = [_dry_run(o, policy, c.effective_from) for o in recorded]
        out.append({"clause": c.ref, "topic": c.topic, "effective_from": c.effective_from.isoformat(),
                    "deadline": (c.effective_from - timedelta(days=1)).isoformat(), "days_left": (c.effective_from - today).days,
                    "facts": [f"{f.key}={f.value:g}{f.unit}" if isinstance(f.value, float) else f"{f.key}={f.value}{f.unit}" for f in c.facts],
                    "questions": [{"question_id": o.question_id, "question": o.question, "region": o.region, "product": o.product,
                                   "channel": o.channel, "language": o.language} for o in qs],
                    "recorded_answers": len(recorded),
                    "preview": preview, "preview_summary": dict(Counter(p["verdict"] for p in preview))})
    return out


def _dry_run(o: Observation, policy: Policy, on: date) -> dict:
    j = classify(o.model_copy(update={"ts": f"{on.isoformat()} 00:00"}), policy)
    return {"obs_id": o.obs_id, "question_id": o.question_id, "region": o.region, "channel": o.channel, "language": o.language,
            "answer": o.answer, "verdict": j.verdict, "reason": j.reason, "clause": j.clause_ref}


def text(plans: list[dict]) -> str:
    if not plans:
        return "没有待生效的已冻结条款。"
    L = []
    for p in plans:
        L.append(f"{p['clause']}（{p['topic']}）{p['effective_from']} 生效，须在 {p['deadline']} 前复测（剩 {p['days_left']} 天）")
        L.append(f"   须复测的问题：{len(p['questions'])} 个；按新标准预演已记录的 {p['recorded_answers']} 条回答：" +
                 ("，".join(f"{k} {v}" for k, v in sorted(p["preview_summary"].items())) or "无记录"))
        for q in p["preview"][:5]:
            L.append(f"   - {q['obs_id']} {q['region']} {q['channel']}：{q['answer']} → {q['verdict']}（{q['reason']}）")
    return "\n".join(L)
