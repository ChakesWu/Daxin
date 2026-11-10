from datetime import date

import pytest

from daxin.audit import Audit
from daxin.db import DB
from daxin.models import Clause, Fact, Observation, Scope
from daxin.observe import Store
from daxin.policy import Policy


@pytest.fixture
def env(tmp_path):
    db = DB(tmp_path / "daxin.db"); a = Audit(db)
    return db, a, Policy(db, a), Store(db, a)


def clause(cid="FEE", version="v1", value=6, frm="2026-07-01", key="fee_waiver.min_purchases", unit="笔", region="R1", product="示例卡", topic="年费免除", frozen=True, pol=None, **kw):
    c = Clause(id=cid, version=version, topic=topic, scope=Scope(region=region, product=product), effective_from=date.fromisoformat(frm),
               facts=[Fact(key=key, value=value, unit=unit)], **kw)
    if pol is not None:
        pol.add(c, "t")
        if frozen:
            pol.confirm(cid, version, "t"); pol.freeze(cid, version, "t2")
    return c


def obs(i=1, answer="每年刷满 6 笔可免年费", ts="2026-11-03 10:00", region="R1", key="fee_waiver.min_purchases", handoff=False, **kw):
    d = dict(obs_id=f"O{i:03d}", ts=ts, inst="BANK-X", region=region, product="示例卡", channel="官网", language="zh-Hans", question_id=f"Q{i:03d}",
             topic="年费免除", question="年费怎么免？", answer=answer, fact_key=key, must_handoff=handoff)
    d.update(kw)
    return Observation(**d)
