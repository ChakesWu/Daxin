import sqlite3

import pytest
import pytest

from daxin.anonymity import AnonymityError, assert_clean, load_names, mask_text
from daxin.audit import Audit
from daxin.db import DB


def test_chain_detects_tampering(tmp_path):
    db = DB(tmp_path / "a.db"); a = Audit(db)
    for i in range(5):
        a.append("u", "act", "obj", str(i), {"i": i})
    assert a.verify() == (True, None)
    with db.conn() as c:
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("UPDATE audit_events SET actor='someone-else' WHERE seq=3")      # the database itself refuses
    with db.conn() as c:                                                                # a privileged attacker drops the trigger first
        c.execute("DROP TRIGGER audit_no_update")
        c.execute("UPDATE audit_events SET actor='someone-else' WHERE seq=3")
    assert a.verify() == (False, 3)


def test_deleting_an_event_breaks_the_chain(tmp_path):
    db = DB(tmp_path / "a.db"); a = Audit(db)
    for i in range(4):
        a.append("u", "act", "obj", str(i))
    with db.conn() as c:
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("DELETE FROM audit_events WHERE seq=2")
    with db.conn() as c:
        c.execute("DROP TRIGGER audit_no_delete")
        c.execute("DELETE FROM audit_events WHERE seq=2")
    assert a.verify()[0] is False


def test_anchor_catches_tail_truncation_that_the_chain_cannot(tmp_path):
    db = DB(tmp_path / "a.db"); a = Audit(db)
    for i in range(4):
        a.append("u", "act", "obj", str(i))
    seq, h = a.anchor()
    with db.conn() as c:
        c.execute("DROP TRIGGER audit_no_delete")
        c.execute("DELETE FROM audit_events WHERE seq=4")          # cut the newest event: the chain still verifies
    assert a.verify() == (True, None)
    assert a.verify_anchor(seq, h) is False and a.verify_anchor(3, a.events()[-1]["hash"]) is True


def test_hmac_needs_the_key(tmp_path, monkeypatch):
    monkeypatch.setenv("DAXIN_AUDIT_KEY", "k1")
    db = DB(tmp_path / "a.db"); a = Audit(db); a.append("u", "act", "o", "1")
    assert a.verify()[0]
    monkeypatch.setenv("DAXIN_AUDIT_KEY", "k2")
    assert Audit(db).verify() == (False, 1)


def test_mask():
    assert "13800000000" not in mask_text("电话 13800000000") and "a***@x.com" in mask_text("a.b@x.com")
    assert mask_text("刷满 6 笔") == "刷满 6 笔"


def test_anonymity_guard(tmp_path):
    m = tmp_path / "institution_map.csv"; m.write_text("code,name\nBANK-X,某某测试银行\n", encoding="utf-8")
    names = load_names(m)
    assert names == ["某某测试银行"]
    assert_clean({"a": "BANK-X 的回答"}, names)
    with pytest.raises(AnonymityError, match="拒绝"):
        assert_clean({"a": "某某测试银行的回答"}, names)
    with pytest.raises(AnonymityError):
        assert_clean({"a": "anything"}, [])                  # no list means nothing can be guaranteed
    assert load_names(tmp_path / "missing.csv") == []


def test_state_change_and_audit_event_commit_together(tmp_path, monkeypatch):
    from datetime import date
    from daxin.models import Clause, Fact, Scope
    from daxin.observe import Store
    from daxin.policy import Policy
    from .conftest import obs
    db = DB(tmp_path / "t.db"); a = Audit(db); pol = Policy(db, a); st = Store(db, a)
    c = Clause(id="X", version="v1", topic="t", scope=Scope(), facts=[Fact(key="k", value=1)], effective_from=date(2026, 1, 1))

    def boom(*args, **kw):
        raise RuntimeError("audit write failed")
    monkeypatch.setattr(a, "_append", boom)
    with pytest.raises(RuntimeError):
        pol.add(c, "u")
    with pytest.raises(RuntimeError):
        st.add(obs(1), "u")
    assert pol.clauses() == [] and st.observations() == []          # neither the clause nor the observation survived the failed audit write
    monkeypatch.undo()
    pol.add(c, "u"); pol.confirm("X", "v1", "u")
    monkeypatch.setattr(a, "_append", boom)
    with pytest.raises(RuntimeError):
        pol.freeze("X", "v1", "u")
    assert pol.clauses()[0].status == "confirmed"                    # the status change was rolled back too
    monkeypatch.undo()
    assert a.verify() == (True, None) and len(a.events()) == 2


def test_two_writers_never_share_a_sequence_number(tmp_path):
    import threading
    db = DB(tmp_path / "c.db"); a = Audit(db)
    errs = []

    def work(n):
        try:
            for i in range(15):
                a.append(f"w{n}", "act", "o", str(i))
        except Exception as e:
            errs.append(e)
    ts = [threading.Thread(target=work, args=(n,)) for n in range(4)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert not errs and len(a.events()) == 60 and a.verify() == (True, None)
