"""Decision kernel: topic-level release matrix L1-L4 (docs/ARCHITECTURE.md, section 4.6).

Only human-reviewed verdicts count. Rates carry a Wilson lower bound; too small a sample can only lower a level (I8).
Thresholds are EXAMPLES to be calibrated with pilot data and the bank's own judgment.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from .grade import grade
from .models import ERRORS, SCORED
from .observe import Store
from .policy import Policy
from .stats import wilson

LEVELS = ["L1", "L2", "L3", "L4"]          # L1 most automated ... L4 humans only
NAME = {"L1": "全自动", "L2": "辅助（AI 起草，人工确认）", "L3": "AI 回答并提示可转人工", "L4": "必须人工"}
THRESHOLDS = {"L1": (0.95, 73), "L2": (0.90, 35), "L3": (0.80, 1)}   # (Wilson lower bound, minimum n)


def lower(a: str, b: str) -> str:
    """The more conservative (less automated) of two levels."""
    return LEVELS[max(LEVELS.index(a), LEVELS.index(b))]


@dataclass
class Row:
    topic: str
    region: str
    channel: str
    language: str
    n: int = 0
    k: int = 0
    lower_bound: float = 0.0
    open_high: int = 0
    unreviewed: int = 0
    level: str = "L4"
    reasons: list[str] = field(default_factory=list)


def matrix(policy: Policy, store: Store, today: date | None = None, max_age_days: int = 30,
           group: tuple[str, ...] = ("topic", "region", "channel", "language")) -> list[Row]:
    obs, final = store.observations(), store.final_verdicts()
    groups: dict[tuple, list] = defaultdict(list)
    for o in obs:
        groups[tuple(getattr(o, g) for g in group)].append(o)
    total_scored = sum(1 for o in obs if final.get(o.obs_id) in SCORED) or 1
    judg = store.judgments()
    rows = []
    for key, os_ in sorted(groups.items()):
        r = Row(**dict(zip(group, key)), **{g: "" for g in ("topic", "region", "channel", "language") if g not in group})
        scored = [o for o in os_ if final.get(o.obs_id) in SCORED]
        r.n = len(scored)
        r.k = sum(final[o.obs_id] in ERRORS for o in scored)
        r.unreviewed = sum(1 for o in os_ if o.obs_id not in final)
        r.lower_bound = wilson(r.n - r.k, r.n)[0] if r.n else 0.0
        share = r.n / total_scored
        exposure = "high" if share >= 0.2 else "mid"
        # an R3/R4 error stays open until a later reviewed pass of the same question in the same situation
        for o in scored:
            if final[o.obs_id] not in ERRORS:
                continue
            j = judg.get(o.obs_id)
            g = grade(final[o.obs_id], j.flags if j else [], o.fact_key, exposure)
            if g in ("R3", "R4"):
                later_pass = any(p.question_id == o.question_id and (p.region, p.channel, p.product, p.language) == (o.region, o.channel, o.product, o.language)
                                 and p.ts > o.ts and final.get(p.obs_id) == "通过" for p in os_)
                r.open_high += 0 if later_pass else 1

        if any(o.must_handoff for o in os_):
            r.level, r.reasons = "L4", ["该主题必须转人工"]
            rows.append(r)
            continue
        if r.n == 0:
            r.level, r.reasons = "L4", ["没有经人工判定的样本"]
            rows.append(r)
            continue
        level = "L4"
        for lv in ("L1", "L2", "L3"):
            lb, nmin = THRESHOLDS[lv]
            if r.lower_bound >= lb and r.n >= nmin:
                level = lv
                break
        if level != "L1" and r.n < THRESHOLDS["L2"][1]:
            r.reasons.append(f"样本不足（n={r.n}，达到 L2 至少需要 {THRESHOLDS['L2'][1]} 条）")
        ceiling = "L1"
        if r.open_high:
            ceiling = lower(ceiling, "L3"); r.reasons.append(f"有 {r.open_high} 个未关闭的 R3/R4 发现，封顶 L3")
        last = max(o.day for o in os_)
        keys = {o.fact_key for o in os_ if o.fact_key}
        if policy.changed_after(keys, last):
            ceiling = lower(ceiling, "L3"); r.reasons.append("标准在最近一次测试之后有新版本生效，尚未复测，封顶 L3")
        if today and (today - last).days > max_age_days:
            ceiling = lower(ceiling, "L3"); r.reasons.append(f"最近一次测试已超过 {max_age_days} 天，放行已过期，封顶 L3")
        r.level = lower(level, ceiling)
        if r.unreviewed:
            r.reasons.append(f"另有 {r.unreviewed} 条尚未经人工判定，不计入")
        rows.append(r)
    return rows
