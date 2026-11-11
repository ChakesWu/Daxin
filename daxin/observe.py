"""Observation, judgment and review storage. Observations and reviews are append-only (enforced by triggers)."""
from __future__ import annotations

import hashlib
import json
from collections import Counter

from . import RULE_VERSION
from .anonymity import mask_text
from .audit import Audit
from .db import DB
from .models import Judgment, Observation


MIN_REVIEWERS = 2        # a verdict counts only when at least this many reviewers have judged the answer and they agree


class Store:
    def __init__(self, db: DB, audit: Audit | None = None):
        self.db, self.audit = db, audit or Audit(db)

    # ---- observations
    def add(self, o: Observation, actor: str = "system") -> bool:
        """Append one observation. The answer is stored masked; its SHA-256 is of the original text. False if it already exists."""
        o = o.model_copy(update={"answer_sha256": o.answer_sha256 or hashlib.sha256(o.answer.encode()).hexdigest(),
                                 "answer": mask_text(o.answer), "question": mask_text(o.question)})
        with self.db.conn() as c:
            if c.execute("SELECT 1 FROM observations WHERE obs_id=?", (o.obs_id,)).fetchone():
                return False
            d = o.model_dump()
            d["must_handoff"] = int(d["must_handoff"])
            c.execute(f"INSERT INTO observations VALUES ({','.join('?' * len(d))})", tuple(d.values()))
            self.audit.append(actor, "observation_recorded", "observation", o.obs_id,
                              {k: v for k, v in o.model_dump().items() if k not in ("answer", "question")}, conn=c)
        return True

    def observations(self, **where) -> list[Observation]:
        q, args = "SELECT * FROM observations", []
        if where:
            q += " WHERE " + " AND ".join(f"{k}=?" for k in where)
            args = list(where.values())
        with self.db.conn() as c:
            rows = c.execute(q + " ORDER BY ts, obs_id", args).fetchall()
        return [Observation(**{**dict(r), "must_handoff": bool(r["must_handoff"])}) for r in rows]

    # ---- judgments (machine suggestions; recomputable, keyed by rule version)
    def save_judgment(self, j: Judgment, actor: str = "system") -> None:
        with self.db.conn() as c:
            c.execute("INSERT OR REPLACE INTO judgments VALUES (?,?,?,?,?,?,?,?)",
                      (j.obs_id, j.rule_version, j.verdict, json.dumps(j.flags), json.dumps(j.claims),
                       json.dumps(j.expected, ensure_ascii=False), j.clause_ref, j.reason))

    def judgments(self, rule_version: str = RULE_VERSION) -> dict[str, Judgment]:
        """Machine judgments of ONE rule version (default: the current one). Versions are never mixed: an old rule's verdict is history."""
        with self.db.conn() as c:
            rows = c.execute("SELECT * FROM judgments WHERE rule_version=?", (rule_version,)).fetchall()
        return {r["obs_id"]: Judgment(obs_id=r["obs_id"], rule_version=r["rule_version"], verdict=r["verdict"],
                                      flags=json.loads(r["flags"]), claims=json.loads(r["claims"]),
                                      expected=json.loads(r["expected"]), clause_ref=r["clause_ref"], reason=r["reason"]) for r in rows}

    # ---- human reviews (only these count in statistics: invariant I1/I6)
    def add_review(self, obs_id: str, reviewer: str, verdict: str, note: str = "", ts: str = "") -> bool:
        with self.db.conn() as c:
            if not c.execute("SELECT 1 FROM observations WHERE obs_id=?", (obs_id,)).fetchone():
                raise KeyError(f"unknown observation {obs_id}")
            if c.execute("SELECT 1 FROM reviews WHERE obs_id=? AND reviewer=?", (obs_id, reviewer)).fetchone():
                return False
            c.execute("INSERT INTO reviews VALUES (?,?,?,?,?)", (obs_id, reviewer, verdict, ts, note))
            self.audit.append(reviewer, "review_added", "observation", obs_id, {"verdict": verdict}, conn=c)
        return True

    def reviews(self) -> dict[str, list[tuple[str, str]]]:
        with self.db.conn() as c:
            rows = c.execute("SELECT obs_id, reviewer, verdict FROM reviews ORDER BY rowid").fetchall()
        out: dict[str, list[tuple[str, str]]] = {}
        for r in rows:
            out.setdefault(r["obs_id"], []).append((r["reviewer"], r["verdict"]))
        return out

    def final_verdicts(self, min_reviewers: int = MIN_REVIEWERS) -> dict[str, str]:
        """The verdict that counts: at least `min_reviewers` reviewers, all agreeing -> that verdict; they disagree -> '待人工'
        (a dispute is not a result). One reviewer alone is not a gold label: the answer stays 'not yet reviewed'."""
        out = {}
        for oid, rs in self.reviews().items():
            if len(rs) < min_reviewers:
                continue
            vs = Counter(v for _, v in rs)
            out[oid] = next(iter(vs)) if len(vs) == 1 else "待人工"
        return out
