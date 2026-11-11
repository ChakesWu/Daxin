"""LLM-assisted tagging of the numbers in an answer. The model PROPOSES which fact each number belongs to; code DISPOSES.

Purpose: cut needless 'pending human' when an answer mixes facts (e.g. a daily limit of 50000 yuan and a fee of 10 yuan in one sentence).
What the model can NOT do (I3, I5): it cannot create a pass, cannot change a number, cannot excuse a number that equals this fact's standard.
A tag is accepted only if code verifies it:
  * the quote is found verbatim in the answer and covers the number;
  * 'other_fact': the named fact exists in the frozen standard and its value equals the number;
  * 'old' / 'other_scope': the number equals a superseded value / another scope's value of THIS fact;
  * 'none': the number equals no value of this fact at all.
Raw model outputs are saved (LLMClient.record_dir) so a run can be replayed offline. Judgments made with a tagger carry their own
rule-version label (RULE_VERSION + '+llm') and are never mixed with rule-only judgments.
"""
from __future__ import annotations

import json
import re
from datetime import date

from .draft import parse_json
from .llm import LLMClient, LLMError
from .policy import Policy

SYSTEM = ("你是银行客服回答的标注助手。给你一段客服回答、被检查的事实，以及回答中出现的数字列表。请判断每个数字在回答里说的是什么，只输出 JSON。"
          "about 取值：this（说的就是被检查的事实）、old（被检查事实的旧版取值）、other_scope（被检查事实在其他地区或渠道的取值）、"
          "other_fact（候选事实列表里另一个事实，须给出 fact_key）、none（与任何政策事实无关，如电话、年限）。"
          "每项必须附 quote：逐字摘自回答、包含该数字的一小段。不确定就答 this。")
FORMAT = '输出：{"tags":[{"index":0,"about":"this|old|other_scope|other_fact|none","fact_key":"","quote":"逐字摘自回答的片段"}]}'


def _norm(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class LLMTagger:
    def __init__(self, client: LLMClient, policy: Policy, max_candidates: int = 40):
        self.client, self.policy, self.max_candidates = client, policy, max_candidates
        self.notes: list[str] = []

    def candidates(self, day: date, key: str) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for c in self.policy.clauses(("frozen",)):
            if not self.policy._active(c, day):
                continue
            for f in c.facts:
                v = _norm(f.value)
                if f.key != key and v is not None and not f.elements and f.key not in out:
                    out[f.key] = {"topic": c.topic, "value": v, "unit": f.unit}
        return dict(list(out.items())[: self.max_candidates])

    def __call__(self, answer: str, spans, fact_key: str, fact_desc: str, day: date, olds: list[float], others: list[float], expected: float) -> set[int]:
        """Indices (into `spans`) of numbers that the model tagged AND code verified as not being a claim about this fact's current value."""
        cands = self.candidates(day, fact_key)
        nums = [{"index": i, "number": v, "text": answer[max(0, st - 12):en + 8]} for i, (v, st, en) in enumerate(spans)]
        user = (f"被检查的事实：{fact_desc}\n候选的其他事实：{json.dumps(cands, ensure_ascii=False)}\n回答：{answer}\n数字：{json.dumps(nums, ensure_ascii=False)}\n" + FORMAT)
        try:
            data = parse_json(self.client.chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}], json_mode=True))
            tags = data.get("tags", []) if isinstance(data, dict) else []
        except (LLMError, json.JSONDecodeError) as e:
            self.notes.append(f"tagger failed: {type(e).__name__}")
            return set()
        excused: set[int] = set()
        for t in tags:
            try:
                i, about, quote = int(t["index"]), t["about"], str(t.get("quote") or "").strip()
            except (KeyError, TypeError, ValueError):
                continue
            if not (0 <= i < len(spans)) or not quote:
                continue
            v, st, en = spans[i]
            at = answer.find(quote)
            if at < 0 or not (at <= st and en <= at + len(quote)):                 # the quote must be verbatim and must contain this very number
                continue
            if abs(v - expected) < 1e-9:                                          # the model may never excuse a number equal to the standard
                continue
            ok = False
            if about == "other_fact":
                c = cands.get(str(t.get("fact_key") or ""))
                ok = bool(c) and abs(c["value"] - v) < 1e-9
            elif about == "old":
                ok = any(abs(v - o) < 1e-9 for o in olds)
            elif about == "other_scope":
                ok = any(abs(v - o) < 1e-9 for o in others)
            elif about == "none":
                ok = not any(abs(v - o) < 1e-9 for o in [expected, *olds, *others])
            if ok:
                excused.add(i)
        return excused
