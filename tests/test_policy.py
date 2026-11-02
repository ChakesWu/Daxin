from datetime import date

import pytest

from daxin.models import Clause, Scope
from daxin.policy import PolicyConflict, PolicyError

from .conftest import clause

D = date.fromisoformat


def test_scope_cover_and_specificity():
    wide, narrow = Scope(product="A"), Scope(product="A", region="R1")
    assert wide.covers(narrow) and not narrow.covers(wide)
    assert narrow.specificity() == 2 and Scope().specificity() == 0
    assert Scope(region="R1").overlaps(Scope(region=None, channel="web")) and not Scope(region="R1").overlaps(Scope(region="R2"))


def test_resolve_only_uses_frozen_clauses(env):
    _, _, pol, _ = env
    clause(pol=pol, frozen=False)
    assert pol.resolve("fee_waiver.min_purchases", Scope(region="R1", product="示例卡"), D("2026-11-03")) is None
    pol.confirm("FEE", "v1", "x"); pol.freeze("FEE", "v1", "y")
    f, c = pol.resolve("fee_waiver.min_purchases", Scope(region="R1", product="示例卡"), D("2026-11-03"))
    assert f.value == 6 and c.ref == "FEE@v1"


def test_a_new_version_ends_the_old_one_and_old_values_are_listed(env):
    _, _, pol, _ = env
    clause(version="v1", value=3, frm="2025-01-01", pol=pol)
    clause(version="v2", value=6, frm="2026-07-01", pol=pol)
    s = Scope(region="R1", product="示例卡")
    assert pol.resolve("fee_waiver.min_purchases", s, D("2026-06-30"))[0].value == 3
    assert pol.resolve("fee_waiver.min_purchases", s, D("2026-07-01"))[0].value == 6
    assert [f.value for f, _ in pol.older_values("fee_waiver.min_purchases", s, D("2026-08-01"))] == [3]
    assert pol.older_values("fee_waiver.min_purchases", s, D("2026-06-30")) == []        # not yet superseded that day


def test_more_specific_scope_wins_then_latest(env):
    _, _, pol, _ = env
    pol.add(Clause(id="G", version="v1", topic="t", scope=Scope(product="示例卡"), effective_from=D("2025-01-01"),
                   facts=[{"key": "k", "value": 1}]), "t"); pol.confirm("G", "v1", "t"); pol.freeze("G", "v1", "u")
    pol.add(Clause(id="S", version="v1", topic="t", scope=Scope(product="示例卡", region="R1"), effective_from=D("2024-01-01"),
                   facts=[{"key": "k", "value": 2}]), "t"); pol.confirm("S", "v1", "t"); pol.freeze("S", "v1", "u")
    assert pol.resolve("k", Scope(product="示例卡", region="R1"), D("2026-01-01"))[0].value == 2       # specific beats recent
    assert pol.resolve("k", Scope(product="示例卡", region="R9"), D("2026-01-01"))[0].value == 1


def test_equally_specific_disagreement_is_a_conflict(env):
    _, _, pol, _ = env
    clause("A", value=6, region="R1", pol=pol); clause("B", value=7, region="R1", pol=pol)
    with pytest.raises(PolicyConflict):
        pol.resolve("fee_waiver.min_purchases", Scope(region="R1", product="示例卡"), D("2026-11-03"))
    cs = pol.conflicts()
    assert len(cs) == 1 and cs[0][2] == "fee_waiver.min_purchases"


def test_other_scope_values(env):
    _, _, pol, _ = env
    clause("A", value=6, region="R1", pol=pol); clause("B", value=12, region="R2", pol=pol)
    vals = [f.value for f, _ in pol.other_scope_values("fee_waiver.min_purchases", Scope(region="R1", product="示例卡"), D("2026-11-03"))]
    assert vals == [12]


def test_lifecycle_rules(env):
    db, _, pol, _ = env
    clause(pol=pol, frozen=False)
    with pytest.raises(PolicyError):
        pol.freeze("FEE", "v1", "x")                       # must be confirmed first
    pol.confirm("FEE", "v1", "x"); pol.freeze("FEE", "v1", "y")
    with pytest.raises(PolicyError):
        pol.confirm("FEE", "v1", "x")                      # a frozen clause never goes back
    with pytest.raises(PolicyError):
        pol.add(clause(), "x")                             # same version again: a new fact needs a new version
    with pytest.raises(Exception, match="immutable"):
        with db.conn() as c:
            c.execute("UPDATE clauses SET text='x' WHERE id='FEE'")
    with pytest.raises(Exception, match="cannot be deleted"):
        with db.conn() as c:
            c.execute("DELETE FROM clauses WHERE id='FEE'")


def test_change_detection(env):
    _, _, pol, _ = env
    clause(version="v1", frm="2026-07-01", pol=pol); clause(version="v2", value=7, frm="2026-12-01", pol=pol)
    assert pol.changed_after({"fee_waiver.min_purchases"}, D("2026-11-20"))
    assert not pol.changed_after({"fee_waiver.min_purchases"}, D("2026-12-05"))
    assert not pol.changed_after({"other"}, D("2026-11-20"))
