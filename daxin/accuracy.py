"""Accuracy of the machine judgments against human-reviewed verdicts (the gold set). Only real counts, always with an interval.

Machine verdicts are suggestions (I2/I3). This module answers: when the rules decide, how often are they right, and when they
say 'pass', how often is that a miss? Abstentions ('待人工', '无法判断') are not errors: they are reported as the abstain rate.
Human side: only observations whose reviewers agree count; a dispute is not a gold label.
"""
from __future__ import annotations

from collections import Counter

from .models import ERRORS, SCORED
from .observe import Store
from .stats import cohen_kappa, wilson

ABSTAIN = ("待人工", "无法判断")
LABELS = ("通过",) + ERRORS + ("C5", "无回答")


def _rate(k: int, n: int) -> dict:
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "rate": round(k / n, 4) if n else None, "wilson95": [round(lo, 4), round(hi, 4)]}


def compare(pairs: list[tuple[str, str]]) -> dict:
    """pairs = (human verdict, machine verdict). Returns confusion matrix, per-class precision/recall, agreement, kappa, false-pass rate."""
    conf: Counter = Counter(pairs)
    decided = [(h, m) for h, m in pairs if m not in ABSTAIN]
    labels = sorted({x for p in pairs for x in p} - set(ABSTAIN)) or []
    per = {}
    for c in labels:
        tp = sum(1 for h, m in decided if h == c and m == c)
        per[c] = {"precision": _rate(tp, sum(1 for _, m in decided if m == c)), "recall_among_decided": _rate(tp, sum(1 for h, _ in decided if h == c))}
    pass_said = [(h, m) for h, m in decided if m == "通过"]
    false_pass = sum(1 for h, _ in pass_said if h in ERRORS)
    err_human = [(h, m) for h, m in pairs if h in ERRORS]
    missed_err = sum(1 for _, m in err_human if m == "通过")
    return {
        "n": len(pairs),
        "abstain": _rate(len(pairs) - len(decided), len(pairs)),
        "agreement_on_decided": _rate(sum(1 for h, m in decided if h == m), len(decided)),
        "kappa_on_decided": None if not decided else (None if (k := cohen_kappa(decided)) is None else round(k, 4)),
        "false_pass": _rate(false_pass, len(pass_said)),                  # machine says pass, human says wrong: the dangerous cell
        "errors_passed": _rate(missed_err, len(err_human)),               # of human-confirmed wrong answers, share the machine passed
        "per_class": per,
        "confusion": {f"{h}→{m}": v for (h, m), v in sorted(conf.items())},
    }


def from_store(store: Store, rule_version: str | None = None) -> dict:
    final, machine = store.final_verdicts(), store.judgments(rule_version)
    pairs = [(final[o], machine[o].verdict) for o in final if o in machine and final[o] in SCORED + ("C5", "无回答")]
    out = compare(pairs)
    out["n_gold"] = len(pairs)
    out["n_reviewed_not_in_gold"] = len(final) - len(pairs)      # disputes ('待人工'), or no machine judgment yet
    # reviewer agreement: first two reviewers of each observation
    rev = [(r[0][1], r[1][1]) for r in store.reviews().values() if len(r) >= 2]
    out["reviewer_agreement"] = _rate(sum(a == b for a, b in rev), len(rev))
    out["reviewer_kappa"] = None if (k := cohen_kappa(rev)) is None else round(k, 4)
    return out


def markdown(r: dict) -> str:
    def f(x):
        return "—" if x["rate"] is None else f"{x['k']}/{x['n']} = {x['rate']:.1%}（95% 区间 {x['wilson95'][0]:.1%}–{x['wilson95'][1]:.1%}）"
    lines = [f"黄金集样本 {r['n']} 条（仅人工复核一致者）",
             f"- 机器弃权（待人工/无法判断）：{f(r['abstain'])}",
             f"- 机器已判定者与人工一致：{f(r['agreement_on_decided'])}；kappa = {r['kappa_on_decided']}",
             f"- 机器判“通过”而人工认为有错（误放行）：{f(r['false_pass'])}",
             f"- 人工确认有错的回答中，被机器判“通过”的：{f(r['errors_passed'])}"]
    if "reviewer_agreement" in r:
        lines.append(f"- 复核人之间一致率：{f(r['reviewer_agreement'])}；kappa = {r['reviewer_kappa']}")
    lines += ["", "| 类别 | 精确率 | 已判定中的召回 |", "|---|---|---|"]
    for c, v in r["per_class"].items():
        lines.append(f"| {c} | {f(v['precision'])} | {f(v['recall_among_decided'])} |")
    lines += ["", "混淆（人工→机器）：" + "，".join(f"{k}:{v}" for k, v in r["confusion"].items())]
    return "\n".join(lines)
