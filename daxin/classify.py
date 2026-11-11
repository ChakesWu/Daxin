"""Judgment kernel: the fixed decision order of the five risk classes (docs/ARCHITECTURE.md, section 4.4).

C1 contradicts the current rule · C2 states a superseded version · C3 states another scope's rule · C4 over-promises ·
C5 needs compliance review. Anything that cannot be decided becomes '待人工' (pending human): never a pass (invariant I3).
"""
from __future__ import annotations

from . import RULE_VERSION
from . import context as ctx
from .extract import claim_spans, hands_off, promises
import re

from .models import Fact, Judgment, Observation
from .policy import Policy, PolicyConflict

EPS = 1e-9


def _eq(a: float, b: float) -> bool:
    return abs(a - b) < EPS


def classify(obs: Observation, policy: Policy, tagger=None) -> Judgment:
    """`tagger` (claims.LLMTagger) may excuse numbers that belong to other facts; its judgments carry their own rule-version label."""
    j = Judgment(obs_id=obs.obs_id, rule_version=RULE_VERSION + ("+llm" if tagger else ""), verdict="")
    ans = (obs.answer or "").strip()
    if not ans:
        return j.model_copy(update={"verdict": "无回答", "reason": "渠道未给出回答"})
    promised = promises(ans)

    if obs.must_handoff:                                   # topics that must go to a human (investment guarantees, complaints...)
        if promised:
            return j.model_copy(update={"verdict": "C4", "reason": "须转人工的主题出现承诺类措辞"})
        ok = hands_off(ans)
        return j.model_copy(update={"verdict": "通过" if ok else "C5", "reason": "已引导转人工" if ok else "须转人工的主题未引导转人工"})

    verdict, reason, expected, ref, claims = _fact_verdict(obs, ans, policy, tagger)
    flags: list[str] = []
    if promised:
        if verdict in ("通过", "待人工", "无法判断"):
            verdict, reason = "C4", "出现承诺类措辞"
        else:
            flags.append("C4")
    return j.model_copy(update={"verdict": verdict, "flags": flags, "claims": claims, "expected": expected,
                                "clause_ref": ref, "reason": reason})


def _fact_verdict(obs: Observation, ans: str, policy: Policy, tagger=None):
    if not obs.fact_key:
        return "无法判断", "题目没有对应的事实键", None, "", []
    scope, day = obs.scope(), obs.day
    try:
        found = policy.resolve(obs.fact_key, scope, day)
    except PolicyConflict as e:
        return "无法判断", f"标准自身冲突：{e}", None, "", []
    if found is None:
        return "无法判断", f"没有已冻结的标准（{obs.fact_key}，{day}）", None, "", []
    fact, clause = found
    if fact.elements:
        v, why = _element_verdict(ans, fact)
        return v, why, fact.value, clause.ref, []
    try:
        exp = float(fact.value)
    except (TypeError, ValueError):
        return "无法判断", "标准取值不是数字，需人工判断", fact.value, clause.ref, []
    spans = claim_spans(ans, fact.unit)
    vals = list(dict.fromkeys(v for v, _, _ in spans))
    if not vals:
        return "待人工", "回答中抽不到可比对的主张（不判通过）", exp, clause.ref, []
    olds = [(float(f.value), c) for f, c in policy.older_values(obs.fact_key, scope, day) if _num_ok(f.value)]
    others_scope = [(float(f.value), c) for f, c in policy.other_scope_values(obs.fact_key, scope, day) if _num_ok(f.value)]
    own = [x for x in (obs.region, obs.channel) if x]
    other_labels = sorted({x for _, c in others_scope for x in (c.scope.region, c.scope.channel) if x} - set(own))
    words = f"{obs.fact_key} {clause.topic} {fact.condition}"

    cur, rest = [], []                       # numbers equal to the standard that are stated as current / everything else
    for v, st, en in spans:
        (cur if _eq(v, exp) and not ctx.is_historical(ans, st, en) else rest).append((v, st, en))
    hist_exp = [sp for sp in rest if _eq(sp[0], exp)]
    rest = [sp for sp in rest if not _eq(sp[0], exp)]

    def excused(sp) -> bool:                  # clearly labelled as an old version or as another scope's rule
        v, st, en = sp
        if ctx.is_negated(ans, st):
            return True
        if ctx.is_historical(ans, st, en) and any(_eq(v, ov) for ov, _ in olds):
            return True
        return any(_eq(v, ov) for ov, _ in others_scope) and ctx.labelled_for_other_scope(ans, st, own, other_labels)

    unexplained = [sp for sp in rest if not excused(sp)]
    if unexplained and tagger is not None:
        idx = tagger(ans, unexplained, obs.fact_key, f"{clause.topic}（{obs.fact_key}）现行取值 {exp:g}{fact.unit}", day,
                     [ov for ov, _ in olds], [ov for ov, _ in others_scope], exp)
        unexplained = [sp for i, sp in enumerate(unexplained) if i not in idx]
    if cur and not unexplained:
        for v, st, en in cur:
            why = ctx.qualifier_problem(ans, st, en, fact.op, words)
            if why:
                return "待人工", f"回答含 {exp:g}，但{why}，数字相同不足以判通过", exp, clause.ref, vals
        if all(ctx.labelled_for_other_scope(ans, st, own, other_labels) for _, st, _ in cur) and other_labels:
            return "待人工", f"{exp:g} 出现在针对其他范围（{other_labels}）的说明里，不能确认适用于本范围", exp, clause.ref, vals
        return "通过", f"与 {clause.ref} 一致（{exp:g}）", exp, clause.ref, vals
    if cur:
        left = [v for v, _, _ in unexplained]
        return "待人工", f"回答同时出现现行值 {exp:g} 与其他数字 {left}，无法确定哪个被当作现行规则", exp, clause.ref, vals
    if hist_exp and not unexplained:
        return "待人工", f"现行值 {exp:g} 只作为旧版说明出现，回答没有把它说成现行规则", exp, clause.ref, vals
    if rest and all(ctx.is_historical(ans, st, en) for _, st, en in rest):
        return "待人工", "回答只提到旧版数字并说明已被取代，没有给出现行值", exp, clause.ref, vals
    for v in vals:
        for ov, oc in olds:
            if _eq(v, ov):
                return "C2", f"回答 {v:g} 等于已被取代的旧版 {oc.ref}；现行为 {exp:g}（{clause.ref}）", exp, clause.ref, vals
    for v in vals:
        for ov, oc in others_scope:
            if _eq(v, ov):
                return "C3", f"回答 {v:g} 等于其他范围的规则 {oc.ref}；本范围现行为 {exp:g}（{clause.ref}）", exp, clause.ref, vals
    return "C1", f"回答 {vals} 与现行 {exp:g}（{clause.ref}）不符", exp, clause.ref, vals


def _num_ok(v) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def _element_verdict(ans: str, fact: Fact) -> tuple[str, str]:
    """Eligibility / required-document facts: every required element must be stated and none denied.
    A missing element is 'pending human' (an incomplete answer is not necessarily a wrong one); a denied one is never a pass."""
    missing, denied = [], []
    for el in fact.elements:
        spots = [m.start() for a in el.anchors if a for m in re.finditer(re.escape(a), ans)]
        if not spots:
            missing.append(el.name)
        elif all(ctx.is_negated(ans, p) for p in spots):
            denied.append(el.name)
    if denied:
        return "待人工", f"要素 {denied} 前有否定措辞（如“不需要”），不能判通过"
    if missing:
        return "待人工", f"回答遗漏要素 {missing}（遗漏不等于错误，须人工判断）"
    return "通过", f"已说明全部 {len(fact.elements)} 项要素：{'、'.join(e.name for e in fact.elements)}"
