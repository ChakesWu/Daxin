"""Export the release matrix as a routing policy that a customer-service agent's router can read.

Daxin never enters answer generation: it publishes a signed-off decision per scope (topic x region x channel x language),
and the bank's own intent router decides where to send a question. The file fails closed:
- anything not listed falls back to `default` (L4, humans only);
- a route past `valid_until` must be treated no better than `on_expiry` (L3);
- `sha256` covers every other field, so a router can reject an edited file.
Levels are EXAMPLE thresholds (see release.py); the mapping to automation modes is the bank's to confirm.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone

from . import RULE_VERSION, __version__
from .release import NAME, Row

SCHEMA = "daxin.routing/1"
MODE = {"L1": "auto", "L2": "ai_draft_human_confirm", "L3": "ai_answer_offer_handoff", "L4": "human_only"}


def _digest(doc: dict) -> str:
    body = {k: v for k, v in doc.items() if k != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def build(rows: list[Row], inst: str, standard: list[str], audit_head: str, max_age_days: int = 30,
          generated_at: str | None = None) -> dict:
    routes = []
    for r in rows:
        valid_until = (date.fromisoformat(r.last_tested) + timedelta(days=max_age_days)).isoformat() if r.last_tested else ""
        routes.append({"topic": r.topic, "region": r.region, "channel": r.channel, "language": r.language,
                       "level": r.level, "mode": MODE[r.level], "label": NAME[r.level],
                       "n": r.n, "errors": r.k, "wilson_lower": round(r.lower_bound, 4),
                       "last_tested": r.last_tested, "valid_until": valid_until, "reasons": list(r.reasons)})
    doc = {"schema": SCHEMA, "inst": inst, "daxin_version": __version__, "rule_version": RULE_VERSION,
           "generated_at": generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "standard": sorted(standard), "audit_head": audit_head,
           "default": {"level": "L4", "mode": MODE["L4"]}, "on_expiry": {"level": "L3", "mode": MODE["L3"]},
           "modes": MODE, "routes": routes}
    doc["sha256"] = _digest(doc)
    return doc


def verify(doc: dict) -> bool:
    return doc.get("schema") == SCHEMA and doc.get("sha256") == _digest(doc)


def _matches(route_val: str, q: str) -> bool:
    return route_val in ("", q)


def decide(doc: dict, topic: str, region: str = "", channel: str = "", language: str = "", today: date | None = None) -> dict:
    """Reference lookup for a router: the level/mode to use for one question. Unknown, tampered or expired → conservative."""
    if not verify(doc):
        return {**doc.get("default", {"level": "L4", "mode": MODE["L4"]}), "why": "路由文件校验失败，按默认处理"}
    hits = [r for r in doc["routes"] if r["topic"] == topic and _matches(r["region"], region)
            and _matches(r["channel"], channel) and _matches(r["language"], language)]
    if not hits:
        return {**doc["default"], "why": "未经验收的范围，按默认处理"}
    # the most specific route wins; ties resolve to the more conservative level
    best = max(hits, key=lambda r: (sum(bool(r[k]) for k in ("region", "channel", "language")), r["level"]))
    out = {"level": best["level"], "mode": best["mode"], "why": "；".join(best["reasons"]) or NAME[best["level"]]}
    if today and best["valid_until"] and today > date.fromisoformat(best["valid_until"]):
        lv = max(best["level"], doc["on_expiry"]["level"])
        out = {"level": lv, "mode": MODE[lv], "why": f"放行已于 {best['valid_until']} 过期，封顶 {doc['on_expiry']['level']}"}
    return out
