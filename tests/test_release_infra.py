"""Routing export, pre-effective regression, customer citations, the report template and the web demo."""
import json
from datetime import date

from typer.testing import CliRunner

from daxin.cite import cite
from daxin.cli import app
from daxin.regress import plan, upcoming
from daxin.release import matrix
from daxin.report import ALIGN, build as report
from daxin.routing import MODE, build as route, decide, verify

from .conftest import clause, obs
from .test_release import fill


def _route(env, **kw):
    clause(pol=env[2]); fill(env, 80)
    rows = matrix(env[2], env[3], group=("topic", "region"))
    return route(rows, "BANK-X", ["FEE@v1"], env[1].head(), generated_at="2026-11-04T00:00:00Z", **kw)


def test_routing_lists_each_scope_with_its_mode(env):
    doc = _route(env)
    (r,) = doc["routes"]
    assert verify(doc) and r["level"] == "L1" and r["mode"] == MODE["L1"] and r["valid_until"] == "2026-12-03"
    assert decide(doc, "年费免除", "R1")["level"] == "L1"


def test_routing_fails_closed(env):
    doc = _route(env)
    assert decide(doc, "没验收过的主题", "R1")["level"] == "L4"                       # unknown scope → humans
    assert decide(doc, "年费免除", "R1", today=date(2026, 12, 4))["level"] == "L3"     # expired → no better than L3
    doc["routes"][0]["level"] = "L1"; doc["routes"][0]["n"] = 999                    # edited file → rejected
    assert not verify(doc) and decide(doc, "年费免除", "R1")["level"] == "L4"


def test_regression_lists_upcoming_changes_and_previews_them(env):
    _, _, pol, st = env
    clause(pol=pol, value=6); fill(env, 10)
    assert plan(pol, st, date(2026, 11, 20)) == []
    clause(pol=pol, version="v2", value=8, frm="2026-12-01")
    assert [c.ref for c in upcoming(pol, date(2026, 11, 20))] == ["FEE@v2"]
    (p,) = plan(pol, st, date(2026, 11, 20))
    assert p["deadline"] == "2026-11-30" and p["days_left"] == 11 and len(p["questions"]) == 1
    assert p["recorded_answers"] == 10 and p["preview_summary"] == {"C2": 10}      # 6 becomes the superseded value on 12-01
    assert all(j.verdict == "通过" for j in st.judgments().values())                 # the preview is never stored


def test_citations_only_for_verified_claims(env):
    _, _, pol, _ = env
    clause(pol=pol, source_ref="仿真制度 第 3.1 条")
    ok = cite(obs(answer="每年刷满 6 笔可免年费"), pol)
    assert ok["action"] == "show" and ok["citations"][0]["document"] == "仿真制度 第 3.1 条" and ok["spans"] == [[5, 8]]
    assert cite(obs(answer="每年刷满 8 笔可免年费"), pol)["action"] == "handoff"
    assert cite(obs(answer="请咨询网点"), pol)["action"] == "show_unverified"
    assert cite(obs(answer="每年刷满 6 笔可免年费"), pol, level="L4")["action"] == "handoff"
    assert cite(obs(answer="Spend six times a year", language="en"), pol)["text"] == "Spend six times a year"
    assert "Transferring" in cite(obs(answer="Spend eight times a year", language="en"), pol)["text"]


def test_report_template_uses_workspace_numbers_and_marks_what_to_align(env):
    _, a, pol, st = env
    clause(pol=pol); fill(env, 40, errors=2)
    text = report(pol, st, a, matrix(pol, st, group=("topic", "region")), "BANK-X", "2026-11", date(2026, 11, 20))
    assert "| C1 | 2 |" in text and "| 通过 | 38 |" in text and "金发〔2026〕8号" in text and "第十五条" in text and "BANK-X" in text
    assert "## 9 条款对应总表" in text and "| 第二十五条 |" in text and "不覆盖" in text


def test_cli_route_regress_report(tmp_path):
    from daxin.audit import Audit; from daxin.db import DB; from daxin.observe import Store; from daxin.policy import Policy
    ws = tmp_path / "ws"; ws.mkdir(); db = DB(ws / "daxin.db"); a = Audit(db); e = (db, a, Policy(db, a), Store(db, a))
    clause(pol=e[2]); fill(e, 80)
    r = CliRunner()
    out = tmp_path / "routing.json"
    assert r.invoke(app, ["route-export", str(out), "--ws", str(ws), "--today", "2026-11-05"]).exit_code == 0
    assert verify(json.loads(out.read_text(encoding="utf-8")))
    res = r.invoke(app, ["route-check", str(out), "年费免除", "--region", "R1", "--channel", "官网", "--language", "zh-Hans"])
    assert res.exit_code == 0 and res.output.startswith("L1 auto")
    assert "没有待生效" in r.invoke(app, ["regress", "--ws", str(ws), "--today", "2026-11-05"]).output
    assert r.invoke(app, ["report", str(tmp_path / "r.md"), "--ws", str(ws), "--today", "2026-11-05"]).exit_code == 0
    assert (tmp_path / "r.md").read_text(encoding="utf-8").startswith("# 智能客服回答测评报告（范本）")


def test_web_demo_is_built_from_the_run(tmp_path):
    from daxin.webdemo import collect, export
    d = collect(tmp_path / "w")
    assert d["meta"]["dist"] == {"C1": 1, "C2": 1, "C3": 1, "C4": 1, "通过": 201} and d["meta"]["audit_ok"]
    assert "immutable" in d["meta"]["frozen_error"]
    assert {t["verdict"] for t in d["turns"]} == {"通过", "C1", "C2", "C3", "C4"}
    assert all((t["external"]["action"] == "show") == (t["verdict"] == "通过") for t in d["turns"])
    assert [s["key"] for s in d["stages"]] == ["before", "change", "retest"] and d["plans"][0]["preview_summary"] == {"C2": 37}
    page = export(tmp_path / "w2", tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    assert "/*__DAXIN_DATA__*/" not in page and "BANK-X" in page and "</script>" in page
