"""Evidence cards for confirmed wrong answers, chained by SHA-256 (invariant I1)."""
from __future__ import annotations

import hashlib
import json

from . import RULE_VERSION
from .anonymity import mask_text
from .grade import grade
from .models import ERRORS
from .observe import Store
from .policy import Policy


def build(policy: Policy, store: Store) -> list[dict]:
    final, judg, revs = store.final_verdicts(), store.judgments(RULE_VERSION), store.reviews()
    prev, cards = "0" * 64, []
    for o in store.observations():
        v = final.get(o.obs_id)
        if v not in ERRORS:
            continue
        j = judg.get(o.obs_id)
        card = {"id": o.obs_id, "verdict": v, "grade": grade(v, j.flags if j else [], o.fact_key),
                "inst": o.inst, "region": o.region, "product": o.product, "channel": o.channel, "language": o.language, "ts": o.ts,
                "question": mask_text(o.question), "answer": mask_text(o.answer), "answer_sha256": o.answer_sha256,
                "expected": j.expected if j else None, "clause": j.clause_ref if j else "", "reason": j.reason if j else "",
                "rule_version": RULE_VERSION, "reviewers": [r for r, _ in revs.get(o.obs_id, [])]}
        card["hash"] = prev = hashlib.sha256((prev + json.dumps(card, sort_keys=True, ensure_ascii=False)).encode()).hexdigest()
        cards.append(card)
    return cards


def verify(cards: list[dict]) -> bool:
    prev = "0" * 64
    for c in cards:
        body = {k: v for k, v in c.items() if k != "hash"}
        h = hashlib.sha256((prev + json.dumps(body, sort_keys=True, ensure_ascii=False)).encode()).hexdigest()
        if h != c["hash"]:
            return False
        prev = h
    return True


def markdown(cards: list[dict]) -> str:
    L = ["# 证据卡（仅含经人工确认的差异）", "", "每张卡的校验值链接上一张；任何改动都会使其后各卡校验失败。", ""]
    for c in cards:
        L += [f"## {c['id']}　{c['verdict']}　{c['grade'] or ''}", "",
              f"- 机构代号：{c['inst']}　地区：{c['region']}　产品：{c['product']}　渠道：{c['channel']}　语言：{c['language']}　时间：{c['ts']}",
              f"- 问：{c['question']}", f"- 答：{c['answer']}",
              f"- 依据：{c['clause']}；判定理由：{c['reason']}", f"- 规则版本：{c['rule_version']}　复核人：{', '.join(c['reviewers'])}",
              f"- 回答原文 SHA-256：`{c['answer_sha256']}`", f"- 校验值（链式）：`{c['hash']}`", ""]
    return "\n".join(L)
