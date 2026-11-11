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

    def append(self, actor: str, action: str, object_type: str, object_id: str, payload=None, conn=None) -> int:
        """Append one event. Pass `conn` (the connection that holds the state change) to commit both in ONE transaction:
        if either fails, neither is kept. Without `conn` the event gets its own transaction."""
        if conn is not None:
            return self._append(conn, actor, action, object_type, object_id, payload)
        with self.db.conn() as c:
            c.execute("BEGIN IMMEDIATE")          # take the write lock before reading the chain head, so two writers cannot pick the same seq
            return self._append(c, actor, action, object_type, object_id, payload)

    def _append(self, c, actor: str, action: str, object_type: str, object_id: str, payload=None) -> int:
        last = c.execute("SELECT seq, hash FROM audit_events ORDER BY seq DESC LIMIT 1").fetchone()
        seq, prev = (last["seq"] + 1, last["hash"]) if last else (1, GENESIS)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        psha = sha256_json(payload if payload is not None else {})
        h = hashlib.sha256("|".join([str(seq), ts, actor, action, object_type, object_id, psha, prev]).encode()).hexdigest()
        c.execute("INSERT INTO audit_events VALUES (?,?,?,?,?,?,?,?,?,?)", (seq, ts, actor, action, object_type, object_id, psha, prev, h, self._mac(h)))
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

    def anchor(self) -> tuple[int, str]:
        """(seq, hash) of the newest event. Store it OUTSIDE the database (another disk or system): truncating the log's tail
        is invisible to the chain itself, but not to an anchor taken earlier."""
        ev = self.events()
        return (ev[-1]["seq"], ev[-1]["hash"]) if ev else (0, GENESIS)

    def verify_anchor(self, seq: int, h: str) -> bool:
        """True if the event `seq` still exists with hash `h` (and so everything before it was not cut or changed)."""
        if seq == 0:
            return True
        return any(e["seq"] == seq and e["hash"] == h for e in self.events())
