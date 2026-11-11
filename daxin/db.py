"""SQLite storage. Immutability is enforced by the database, not by convention (invariants I2, I4)."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS clauses(
  id TEXT NOT NULL, version TEXT NOT NULL, topic TEXT, text TEXT, scope TEXT, facts TEXT,
  effective_from TEXT, effective_to TEXT, status TEXT, source_ref TEXT, PRIMARY KEY(id, version));
CREATE TRIGGER IF NOT EXISTS clauses_frozen_update BEFORE UPDATE ON clauses WHEN OLD.status = 'frozen'
  BEGIN SELECT RAISE(ABORT, 'a frozen clause is immutable: create a new version'); END;
CREATE TRIGGER IF NOT EXISTS clauses_frozen_delete BEFORE DELETE ON clauses WHEN OLD.status = 'frozen'
  BEGIN SELECT RAISE(ABORT, 'a frozen clause cannot be deleted'); END;

CREATE TABLE IF NOT EXISTS observations(
  obs_id TEXT PRIMARY KEY, ts TEXT, inst TEXT, region TEXT, product TEXT, channel TEXT, language TEXT,
  question_id TEXT, session TEXT, turn INTEGER, retest_group TEXT, question TEXT, answer TEXT, answer_sha256 TEXT,
  fact_key TEXT, topic TEXT, must_handoff INTEGER, recorder TEXT, system_fp TEXT DEFAULT '');
CREATE TRIGGER IF NOT EXISTS obs_no_update BEFORE UPDATE ON observations
  BEGIN SELECT RAISE(ABORT, 'observations are append-only'); END;
CREATE TRIGGER IF NOT EXISTS obs_no_delete BEFORE DELETE ON observations
  BEGIN SELECT RAISE(ABORT, 'observations are append-only'); END;

CREATE TABLE IF NOT EXISTS judgments(
  obs_id TEXT NOT NULL, rule_version TEXT NOT NULL, verdict TEXT, flags TEXT, claims TEXT, expected TEXT,
  clause_ref TEXT, reason TEXT, PRIMARY KEY(obs_id, rule_version));

CREATE TABLE IF NOT EXISTS reviews(
  obs_id TEXT NOT NULL, reviewer TEXT NOT NULL, verdict TEXT NOT NULL, ts TEXT, note TEXT, PRIMARY KEY(obs_id, reviewer));
CREATE TRIGGER IF NOT EXISTS reviews_no_update BEFORE UPDATE ON reviews
  BEGIN SELECT RAISE(ABORT, 'reviews are append-only'); END;
CREATE TRIGGER IF NOT EXISTS reviews_no_delete BEFORE DELETE ON reviews
  BEGIN SELECT RAISE(ABORT, 'reviews are append-only'); END;

CREATE TABLE IF NOT EXISTS audit_events(
  seq INTEGER PRIMARY KEY, ts TEXT, actor TEXT, action TEXT, object_type TEXT, object_id TEXT,
  payload_sha256 TEXT, prev_hash TEXT, hash TEXT, mac TEXT);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_events
  BEGIN SELECT RAISE(ABORT, 'the audit log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_events
  BEGIN SELECT RAISE(ABORT, 'the audit log is append-only'); END;
"""


class DB:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.conn() as c:
            c.executescript(SCHEMA)
            cols = {r["name"] for r in c.execute("PRAGMA table_info(observations)")}
            if "system_fp" not in cols:                       # workspaces made before fingerprints existed
                c.execute("ALTER TABLE observations ADD COLUMN system_fp TEXT DEFAULT ''")

    @contextmanager
    def conn(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()
