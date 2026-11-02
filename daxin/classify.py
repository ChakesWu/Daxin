"""Judgment kernel: the fixed decision order of the five risk classes (docs/ARCHITECTURE.md, section 4.4).

C1 contradicts the current rule · C2 states a superseded version · C3 states another scope's rule · C4 over-promises ·
C5 needs compliance review. Anything that cannot be decided becomes '待人工' (pending human): never a pass (invariant I3).
"""
from __future__ import annotations

from . import RULE_VERSION
from .extract import claim_values, hands_off, promises
from .models import Judgment, Observation
from .policy import Policy, PolicyConflict

EPS = 1e-9


def _eq(a: float, b: float) -> bool:
    return abs(a - b) < EPS


def classify(obs: Observation, policy: Policy) -> Judgment:
    j = Judgment(obs_id=obs.obs_id, rule_version=RULE_VERSION, verdict="")
    ans = (obs.answer or "").strip()
    if not ans:
        return j.model_copy(update={"verdict": "无回答", "reason": "渠道未给出回答"})
    promised = promises(ans)

    if obs.must_handoff:                                   # topics that must go to a human (investment guarantees, complaints...)
        if promised:
            return j.model_copy(update={"verdict": "C4", "reason": "须转人工的主题出现承诺类措辞"})
        ok = hands_off(ans)
        return j.model_copy(update={"verdict": "通过" if ok else "C5", "reason": "已引导转人工" if ok else "须转人工的主题未引导转人工"})

    verdict, reason, expected, ref, claims = _fact_verdict(obs, ans, policy)
    flags: list[str] = []
    if promised:
        if verdict in ("通过", "待人工", "无法判断"):
            verdict, reason = "C4", "出现承诺类措辞"
        else:
            flags.append("C4")
    return j.model_copy(update={"verdict": verdict, "flags": flags, "claims": claims, "expected": expected,
                                "clause_ref": ref, "reason": reason})


def _fact_verdict(obs: Observation, ans: str, policy: Policy):
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
    try:
        exp = float(fact.value)
    except (TypeError, ValueError):
        return "无法判断", "标准取值不是数字，需人工判断", fact.value, clause.ref, []
    vals = claim_values(ans, fact.unit)
    if not vals:
        return "待人工", "回答中抽不到可比对的主张（不判通过）", exp, clause.ref, []
    has_exp = any(_eq(v, exp) for v in vals)
    others = [v for v in vals if not _eq(v, exp)]
    if has_exp and not others:
        return "通过", f"与 {clause.ref} 一致（{exp:g}）", exp, clause.ref, vals
    if has_exp:
        return "待人工", f"回答同时出现现行值 {exp:g} 与其他数字 {others}，无法确定哪个被当作现行规则", exp, clause.ref, vals
    olds = [(float(f.value), c) for f, c in policy.older_values(obs.fact_key, scope, day) if _num_ok(f.value)]
    for v in vals:
        for ov, oc in olds:
            if _eq(v, ov):
                return "C2", f"回答 {v:g} 等于已被取代的旧版 {oc.ref}；现行为 {exp:g}（{clause.ref}）", exp, clause.ref, vals
    others_scope = [(float(f.value), c) for f, c in policy.other_scope_values(obs.fact_key, scope, day) if _num_ok(f.value)]
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
