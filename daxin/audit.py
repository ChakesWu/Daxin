"""Hash-chained audit log with optional HMAC (set DAXIN_AUDIT_KEY). Every state change is appended here."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timezone

from .db import DB

GENESIS = "0" * 64


def sha256_json(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


class Audit:
    def __init__(self, db: DB):
        self.db = db
        self.key = (os.environ.get("DAXIN_AUDIT_KEY") or "").encode() or None

    def _mac(self, h: str) -> str | None:
        return hmac.new(self.key, h.encode(), hashlib.sha256).hexdigest() if self.key else None

    def append(self, actor: str, action: str, object_type: str, object_id: str, payload=None) -> int:
        with self.db.conn() as c:
            last = c.execute("SELECT seq, hash FROM audit_events ORDER BY seq DESC LIMIT 1").fetchone()
            seq, prev = (last["seq"] + 1, last["hash"]) if last else (1, GENESIS)
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            psha = sha256_json(payload if payload is not None else {})
            h = hashlib.sha256("|".join([str(seq), ts, actor, action, object_type, object_id, psha, prev]).encode()).hexdigest()
            c.execute("INSERT INTO audit_events VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (seq, ts, actor, action, object_type, object_id, psha, prev, h, self._mac(h)))
            return seq

    def events(self) -> list[dict]:
        with self.db.conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM audit_events ORDER BY seq")]

    def verify(self) -> tuple[bool, int | None]:
        """(True, None) if the chain is intact, else (False, seq of the first broken event)."""
        prev = GENESIS
        for e in self.events():
            h = hashlib.sha256("|".join([str(e["seq"]), e["ts"], e["actor"], e["action"], e["object_type"], e["object_id"],
                                         e["payload_sha256"], prev]).encode()).hexdigest()
            if e["prev_hash"] != prev or e["hash"] != h:
                return False, e["seq"]
            if self.key and e["mac"] != self._mac(h):
                return False, e["seq"]
            prev = h
        return True, None

    def head(self) -> str:
        ev = self.events()
        return ev[-1]["hash"] if ev else GENESIS
