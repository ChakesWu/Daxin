"""Module 3: coverage of the frozen standard. A fact that no human-reviewed observation has tested limits the topic's release.

A (clause, fact) counts as tested when at least one observation for that fact key, asked within the clause's scope,
has a human-reviewed scored verdict. Topic ceiling: no fact tested -> L4; some tested, some not -> L3; all tested -> no cap.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .models import SCORED
from .observe import Store
from .policy import Policy


@dataclass
class Coverage:
    topic: str
    tested: list[str] = field(default_factory=list)       # "clause_ref:fact_key"
    untested: list[str] = field(default_factory=list)

    @property
    def ceiling(self) -> str | None:
        if not self.untested:
            return None
        return "L4" if not self.tested else "L3"


def report(policy: Policy, store: Store) -> dict[str, Coverage]:
    final = store.final_verdicts()
    scored = [o for o in store.observations() if final.get(o.obs_id) in SCORED]
    out: dict[str, Coverage] = {}
    for c in policy.clauses(("frozen",)):
        if any(v.effective_from > c.effective_from for v in policy.versions(c.id)):
            continue            # superseded versions are history, not part of today's standard
        cov = out.setdefault(c.topic, Coverage(c.topic))
        for f in c.facts:
            ok = any(o.fact_key == f.key and c.scope.covers(o.scope()) for o in scored)
            (cov.tested if ok else cov.untested).append(f"{c.ref}:{f.key}")
    return out


def markdown(cov: dict[str, Coverage]) -> str:
    lines = ["| 主题 | 已测事实 | 未测事实 | 放行上限 |", "|---|---|---|---|"]
    for t, c in sorted(cov.items()):
        lines.append(f"| {t} | {len(c.tested)} | {len(c.untested)}{'：' + '、'.join(c.untested) if c.untested else ''} | {c.ceiling or '无'} |")
    return "\n".join(lines)
