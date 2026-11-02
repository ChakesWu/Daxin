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
        c.execute("UPDATE audit_events SET actor='someone-else' WHERE seq=3")
    assert a.verify() == (False, 3)


def test_deleting_an_event_breaks_the_chain(tmp_path):
    db = DB(tmp_path / "a.db"); a = Audit(db)
    for i in range(4):
        a.append("u", "act", "obj", str(i))
    with db.conn() as c:
        c.execute("DELETE FROM audit_events WHERE seq=2")
    assert a.verify()[0] is False


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
