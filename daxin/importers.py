"""Bridges from the manual test kit (xlsx) into the workspace."""
from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

from openpyxl import load_workbook

from .models import Clause, Fact, Observation, Scope
from .observe import Store
from .policy import Policy

LONG_AGO = date(2000, 1, 1)


def _rows(path: Path | str, sheet: str) -> list[dict]:
    ws = load_workbook(path, data_only=True)[sheet]
    it = ws.iter_rows(values_only=True)
    head = [str(h) for h in next(it)]
    return [dict(zip(head, r)) for r in it if any(v not in (None, "") for v in r)]


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _day(v) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def _slug(*parts) -> str:
    return re.sub(r"[^0-9A-Za-z一-鿿]+", "-", "-".join(str(p or "") for p in parts)).strip("-")


def import_register(path: Path | str, policy: Policy, actor: str = "register-import", freeze: bool = False) -> int:
    """Rows of ground_truth_register.xlsx -> clauses. A stated old value becomes an earlier version of the same clause.
    One workspace holds one institution; the institution code is not part of the scope. The source file name never enters the workspace."""
    n = 0
    for r in _rows(path, "标准答案"):
        if "请删除" in str(r.get("备注") or ""):
            continue
        val = _num(r["标准取值"])
        fact = Fact(key=r["事实键"], value=val if val is not None else str(r["标准取值"]), unit=str(r.get("单位") or ""), condition=str(r.get("条件") or ""))
        cid = _slug(r.get("产品"), r.get("地区"), r["事实键"])
        scope = Scope(product=r.get("产品") or None, region=r.get("地区") or None)
        ver = str(r.get("版本") or "v1")
        ref = f"{r.get('条款号')}｜来源日期 {r.get('来源日期')}｜抓取日期 {r.get('抓取日期')}"
        made = []
        old = _num(r.get("旧版取值"))
        if old is not None:
            made.append(Clause(id=cid, version=f"pre-{ver}", topic=str(r.get("主题") or ""), scope=scope, effective_from=LONG_AGO,
                               facts=[fact.model_copy(update={"value": old})], source_ref=ref + "｜旧版取值，依据见备注"))
        made.append(Clause(id=cid, version=ver, topic=str(r.get("主题") or ""), scope=scope, effective_from=_day(r["生效日期"]), facts=[fact], source_ref=ref))
        for c in made:
            policy.add(c, actor)
            if freeze:
                policy.confirm(c.id, c.version, actor)
                policy.freeze(c.id, c.version, actor)
            n += 1
    return n


def import_log(path: Path | str, bank_path: Path | str, store: Store, actor: str = "log-import") -> dict:
    """Rows of test_log.xlsx -> observations plus the human verdicts written next to them."""
    bank = {r["题号"]: r for r in _rows(bank_path, "题库")}
    added = skipped = reviews = 0
    for r in _rows(path, "记录"):
        q = bank.get(r.get("题号"), {})
        ts = r["日期时间"].strftime("%Y-%m-%d %H:%M") if isinstance(r["日期时间"], datetime) else str(r["日期时间"])
        o = Observation(obs_id=str(r["记录号"]), ts=ts, inst=str(r.get("机构代号") or ""), region=str(r.get("地区") or ""),
                        product=str(r.get("产品") or ""), channel=str(r.get("渠道") or ""), language=str(r.get("语言") or ""),
                        question_id=str(r.get("题号") or ""), session=str(r.get("会话号") or ""), turn=int(r.get("轮次") or 1),
                        retest_group=str(r.get("重测组号") or ""), question=str(r.get("提问原文") or q.get("问题（模板）") or ""),
                        answer=str(r.get("回答原文") or ""), fact_key=str(q.get("事实键") or ""), topic=str(q.get("主题") or ""),
                        must_handoff=q.get("须转人工") == "是", recorder=str(r.get("记录人") or ""))
        if store.add(o, actor):
            added += 1
        else:
            skipped += 1
        for who, verdict in ((r.get("记录人"), r.get("人工判定")), (r.get("复核人"), r.get("复核判定"))):
            if who and verdict and store.add_review(o.obs_id, str(who), str(verdict)):
                reviews += 1
    return {"added": added, "skipped": skipped, "reviews": reviews}
