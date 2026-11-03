"""Customer-facing citations: what the customer sees after an answer has been checked against the frozen standard.

Only a claim that matches the standard in force gets a citation. A wrong claim gets none and the answer is replaced by a
hand-off; an answer with no extractable claim gets none either (I3: no claim, no pass, no citation). The citation names
the published document, version and effective date, never an internal clause id or reviewer.
"""
from __future__ import annotations

from .classify import classify
from .extract import claim_spans
from .models import Observation
from .policy import Policy

HANDOFF_TEXT = {"zh-Hans": "这个问题需要由人工客服为您确认，正在为您转接。", "zh-Hant": "這個問題需要由人工客服為您確認，正在為您轉接。",
                "en": "A member of staff needs to confirm this for you. Transferring you now.",
                "pt": "Esta questão tem de ser confirmada por um atendente. Vamos transferi-lo."}


def cite(o: Observation, policy: Policy, level: str = "") -> dict:
    """{'action': 'show'|'handoff'|'show_unverified', 'text': ..., 'citations': [...], 'spans': [...]}.

    `level` is the topic's release level; L4 always hands off, whatever the answer says."""
    j = classify(o, policy)
    lang = o.language or "zh-Hans"
    handoff = HANDOFF_TEXT.get(lang, HANDOFF_TEXT["zh-Hans"])
    if level == "L4" or o.must_handoff:
        return {"action": "handoff", "text": handoff, "citations": [], "spans": [], "verdict": j.verdict, "why": "该主题须由人工处理"}
    if j.verdict in ("C1", "C2", "C3", "C4"):
        return {"action": "handoff", "text": handoff, "citations": [], "spans": [], "verdict": j.verdict, "why": "回答与现行标准不一致，不向客户展示"}
    if j.verdict != "通过":
        return {"action": "show_unverified", "text": o.answer, "citations": [], "spans": [], "verdict": j.verdict,
                "why": "未能核对（不附出处）"}
    found = policy.resolve(o.fact_key, o.scope(), o.day)
    fact, clause = found
    spans = [(s, e) for s, e, v in claim_spans(o.answer, fact.unit, o.language or "") if abs(v - float(fact.value)) < 1e-9]
    c = {"document": clause.source_ref or clause.topic, "version": clause.version, "effective_from": clause.effective_from.isoformat(),
         "statement": clause.text, "checked_by": "答信第三方核对：与现行版本一致"}
    return {"action": "show", "text": o.answer, "citations": [c], "spans": [list(s) for s in spans], "verdict": j.verdict, "why": ""}
