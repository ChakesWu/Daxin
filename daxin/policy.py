"""Policy kernel: versioned, scoped facts; frozen standards; scope resolution; conflict detection."""
from __future__ import annotations

import json
from datetime import date, timedelta

from .audit import Audit
from .db import DB
from .models import Clause, Fact, Scope

FAR = date(9999, 12, 31)


class PolicyError(ValueError):
    pass


class PolicyConflict(PolicyError):
    """Two equally specific, equally recent clauses give different values for the same key."""


def _row(r) -> Clause:
    return Clause(id=r["id"], version=r["version"], topic=r["topic"] or "", text=r["text"] or "",
                  scope=Scope(**json.loads(r["scope"])), facts=[Fact(**f) for f in json.loads(r["facts"])],
                  effective_from=date.fromisoformat(r["effective_from"]),
                  effective_to=date.fromisoformat(r["effective_to"]) if r["effective_to"] else None,
                  status=r["status"], source_ref=r["source_ref"] or "")


class Policy:
    def __init__(self, db: DB, audit: Audit | None = None):
        self.db, self.audit = db, audit or Audit(db)

    # ---- lifecycle: draft -> confirmed -> frozen (a frozen clause never changes; new facts mean a new version)
    def add(self, c: Clause, actor: str = "system") -> None:
        if c.status != "draft":
            c = c.model_copy(update={"status": "draft"})
        with self.db.conn() as conn:
            if conn.execute("SELECT 1 FROM clauses WHERE id=? AND version=?", (c.id, c.version)).fetchone():
                raise PolicyError(f"{c.ref} already exists: a new fact needs a new version")
            conn.execute("INSERT INTO clauses VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (c.id, c.version, c.topic, c.text, c.scope.model_dump_json(), json.dumps([f.model_dump() for f in c.facts], ensure_ascii=False),
                          c.effective_from.isoformat(), c.effective_to.isoformat() if c.effective_to else None, "draft", c.source_ref))
            self.audit.append(actor, "clause_added", "clause", c.ref, c.model_dump(mode="json"), conn=conn)     # one transaction with the insert

    def _set_status(self, cid: str, version: str, frm: tuple[str, ...], to: str, actor: str) -> None:
        with self.db.conn() as conn:
            r = conn.execute("SELECT status FROM clauses WHERE id=? AND version=?", (cid, version)).fetchone()
            if not r:
                raise PolicyError(f"unknown clause {cid}@{version}")
            if r["status"] not in frm:
                raise PolicyError(f"{cid}@{version} is {r['status']}, cannot become {to}")
            conn.execute("UPDATE clauses SET status=? WHERE id=? AND version=?", (to, cid, version))
            self.audit.append(actor, f"clause_{to}", "clause", f"{cid}@{version}", conn=conn)

    def confirm(self, cid: str, version: str, actor: str) -> None:
        self._set_status(cid, version, ("draft",), "confirmed", actor)

    def freeze(self, cid: str, version: str, actor: str) -> None:
        self._set_status(cid, version, ("confirmed",), "frozen", actor)

    # ---- queries
    def clauses(self, status: tuple[str, ...] | None = None) -> list[Clause]:
        with self.db.conn() as conn:
            rows = conn.execute("SELECT * FROM clauses ORDER BY id, effective_from").fetchall()
        out = [_row(r) for r in rows]
        return [c for c in out if status is None or c.status in status]

    def versions(self, cid: str) -> list[Clause]:
        return sorted((c for c in self.clauses() if c.id == cid), key=lambda c: c.effective_from)

    def end(self, c: Clause) -> date:
        """Exclusive end of a clause version: its own effective_to, or the start of the next version of the same clause."""
        later = [v.effective_from for v in self.versions(c.id) if v.effective_from > c.effective_from]
        ends = [e for e in ([c.effective_to + timedelta(days=1)] if c.effective_to else []) + later]
        return min(ends) if ends else FAR

    def _active(self, c: Clause, day: date) -> bool:
        return c.effective_from <= day < self.end(c)

    # ---- resolution (the standard an answer is judged against)
    def resolve(self, key: str, scope: Scope, day: date, status: tuple[str, ...] = ("frozen",)):
        """The (fact, clause) in force on `day` for `scope`: most specific scope wins, then the latest effective date.

        Only frozen clauses count as the standard by default. Raises PolicyConflict when the top candidates disagree."""
        cands = [(c, f) for c in self.clauses(status) if c.scope.covers(scope) and self._active(c, day) for f in c.facts if f.key == key]
        if not cands:
            return None
        best = max((c.scope.specificity(), c.effective_from) for c, _ in cands)
        top = [(c, f) for c, f in cands if (c.scope.specificity(), c.effective_from) == best]
        if len({(f.value, f.op) for _, f in top}) > 1:
            raise PolicyConflict(f"{key}: " + " vs ".join(f"{c.ref}={f.value}" for c, f in top))
        c, f = top[0]
        return f, c

    def older_values(self, key: str, scope: Scope, day: date, status: tuple[str, ...] = ("frozen",)) -> list[tuple[Fact, Clause]]:
        """Values of versions that covered this scope but ended on or before `day` (candidates for C2: stale answers)."""
        return [(f, c) for c in self.clauses(status) if c.scope.covers(scope) and self.end(c) <= day for f in c.facts if f.key == key]

    def other_scope_values(self, key: str, scope: Scope, day: date, status: tuple[str, ...] = ("frozen",)) -> list[tuple[Fact, Clause]]:
        """Values in force on `day` in other scopes (candidates for C3: another product, channel or region's rule)."""
        return [(f, c) for c in self.clauses(status) if not c.scope.covers(scope) and self._active(c, day) for f in c.facts if f.key == key]

    def conflicts(self, status: tuple[str, ...] = ("confirmed", "frozen")) -> list[tuple[Clause, Clause, str]]:
        """Pairs of clauses that could both apply, are equally specific and overlap in time, but disagree (a problem of the policy itself)."""
        cs, out = self.clauses(status), []
        for i, a in enumerate(cs):
            for b in cs[i + 1:]:
                if a.id == b.id or a.scope.specificity() != b.scope.specificity() or not a.scope.overlaps(b.scope):
                    continue
                if not (a.effective_from < self.end(b) and b.effective_from < self.end(a)):
                    continue
                for fa in a.facts:
                    for fb in b.facts:
                        if fa.key == fb.key and (fa.value, fa.op) != (fb.value, fb.op):
                            out.append((a, b, fa.key))
        return out

    def changed_after(self, keys: set[str], day: date, status: tuple[str, ...] = ("frozen",)) -> bool:
        """True if any frozen clause touching `keys` takes effect after `day` (a change not yet re-tested)."""
        return any(c.effective_from > day for c in self.clauses(status) if any(f.key in keys for f in c.facts))
