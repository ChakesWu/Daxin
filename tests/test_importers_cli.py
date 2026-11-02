import json
from pathlib import Path

from openpyxl import Workbook, load_workbook
from typer.testing import CliRunner

from daxin.cli import app
from daxin.importers import import_log, import_register

KIT = Path(__file__).resolve().parents[1] / "testkit"
runner = CliRunner()


def test_template_example_row_is_not_imported(env):
    _, _, pol, _ = env
    assert import_register(KIT / "ground_truth_register.xlsx", pol) == 0


def make_register(path, rows):
    wb = load_workbook(KIT / "ground_truth_register.xlsx"); ws = wb["标准答案"]; ws.delete_rows(2, ws.max_row)
    for r in rows:
        ws.append(r)
    wb.save(path)


ROW = ["S-1", "BANK-X", "R1", "示例卡", "年费免除", "fee_waiver.min_purchases", 6, "笔", "每年", 3, "v2", "2026-07-01", "2026-06-20", "2026-11-02", "内部文件名.pdf", "甲", ""]


def test_register_rows_become_versioned_clauses_and_never_carry_the_file_name(env, tmp_path):
    db, _, pol, _ = env
    make_register(tmp_path / "r.xlsx", [ROW])
    assert import_register(tmp_path / "r.xlsx", pol, "甲", freeze=True) == 2          # the old value becomes an earlier version
    cs = pol.clauses()
    assert [c.version for c in cs] == ["pre-v2", "v2"] and all(c.status == "frozen" for c in cs)
    assert "内部文件名" not in json.dumps([c.model_dump(mode="json") for c in cs], ensure_ascii=False)
    from datetime import date
    from daxin.models import Scope
    s = Scope(region="R1", product="示例卡")
    assert pol.resolve("fee_waiver.min_purchases", s, date(2026, 8, 1))[0].value == 6
    assert [f.value for f, _ in pol.older_values("fee_waiver.min_purchases", s, date(2026, 8, 1))] == [3.0]


def test_log_import_brings_in_human_verdicts(env, tmp_path):
    _, _, pol, st = env
    make_register(tmp_path / "r.xlsx", [ROW]); import_register(tmp_path / "r.xlsx", pol, "甲", freeze=True)
    wb = load_workbook(KIT / "test_log.xlsx"); ws = wb["记录"]
    hdr = [c.value for c in ws[1]]
    def row(**kv): return [kv.get(h) for h in hdr]
    ws.append(row(记录号="L1", 日期时间="2026-11-03 10:00", 机构代号="BANK-X", 地区="R1", 产品="示例卡", 渠道="官网", 语言="zh-Hans", 题号="Q001",
                  回答原文="每年刷满 3 笔免年费", 记录人="甲", 人工判定="C2", 复核人="乙", 复核判定="C2"))
    ws.append(row(记录号="L2", 日期时间="2026-11-03 10:05", 机构代号="BANK-X", 地区="R1", 产品="示例卡", 渠道="官网", 语言="zh-Hans", 题号="Q001", 回答原文="刷满 6 笔", 记录人="甲"))
    wb.save(tmp_path / "l.xlsx")
    r = import_log(tmp_path / "l.xlsx", KIT / "question_bank.xlsx", st)
    assert r == {"added": 2, "skipped": 0, "reviews": 2}
    assert import_log(tmp_path / "l.xlsx", KIT / "question_bank.xlsx", st)["skipped"] == 2        # importing twice adds nothing
    assert st.final_verdicts() == {"L1": "C2"} and st.observations()[0].fact_key == "fee_waiver.min_purchases"


def test_cli_demo_and_commands(tmp_path):
    ws = tmp_path / "w"
    r = runner.invoke(app, ["demo", "--dir", str(ws)])
    assert r.exit_code == 0, r.output
    assert "被数据库拒绝" in r.output and "L1" in r.output and "证据卡 4 张" in r.output and "仿真" in r.output
    assert runner.invoke(app, ["audit-verify", "--ws", str(ws)]).exit_code == 0
    out = runner.invoke(app, ["policy", "list", "--ws", str(ws)]).output
    assert "FEE-WAIVER-R1@v2" in out and "frozen" in out
    assert "冲突 0 处" in runner.invoke(app, ["policy", "conflicts", "--ws", str(ws)]).output
    rel = runner.invoke(app, ["release", "--ws", str(ws), "--by", "topic,region"]).output
    assert "年费免除" in rel and "L1" in rel
    assert "daxin" in runner.invoke(app, ["--version"]).output


def test_cli_public_export_refuses_without_a_name_list(tmp_path):
    ws = tmp_path / "w"; runner.invoke(app, ["demo", "--dir", str(ws)])
    r = runner.invoke(app, ["evidence", str(tmp_path / "out.md"), "--ws", str(ws), "--public"])
    assert r.exit_code == 1 and "拒绝输出" in r.output and not (tmp_path / "out.md").exists()
    (tmp_path / "private").mkdir(); (tmp_path / "private" / "institution_map.csv").write_text("code,name\nBANK-X,不会出现的名字\n", encoding="utf-8")
    r = runner.invoke(app, ["evidence", str(tmp_path / "out.md"), "--ws", str(ws), "--public"])
    assert r.exit_code == 0 and (tmp_path / "out.md").exists()


def test_cli_review_validates_and_freezes_are_enforced(tmp_path):
    ws = tmp_path / "w"; runner.invoke(app, ["init", "--ws", str(ws)])
    assert runner.invoke(app, ["review", "X", "胡说", "--by", "甲", "--ws", str(ws)]).exit_code == 1
    clauses = Path(__file__).resolve().parents[1] / "daxin" / "examples" / "bank_x" / "clauses.json"
    assert runner.invoke(app, ["policy", "add", str(clauses), "--ws", str(ws)]).exit_code == 0
    r = runner.invoke(app, ["policy", "freeze", "GRACE-R1", "v1", "--ws", str(ws)])
    assert r.exit_code == 1 and "失败" in r.output                       # still a draft: it has to be confirmed first
