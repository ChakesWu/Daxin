"""daxin command line."""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

import typer

from . import RULE_VERSION, __version__
from .anonymity import AnonymityError, assert_clean, load_names
from .audit import Audit
from .classify import classify
from .db import DB
from .evidence import build as build_cards, markdown, verify as verify_cards
from .importers import import_log, import_register
from .models import VERDICTS, Clause
from .observe import Store
from .policy import Policy, PolicyError
from .release import NAME, matrix

app = typer.Typer(help="答信 daxin：智能客服回答的第三方验收与分级放行（演示数据均为仿真）", no_args_is_help=True)
policy_app = typer.Typer(help="制度内核", no_args_is_help=True)
app.add_typer(policy_app, name="policy")
WS = typer.Option(".daxin", "--ws", help="工作区目录（一个工作区对应一个机构代号）")


def _ctx(ws: Path):
    db = DB(Path(ws) / "daxin.db"); a = Audit(db)
    return db, a, Policy(db, a), Store(db, a)


def actor() -> str:
    return os.environ.get("DAXIN_USER") or os.environ.get("USER") or "unknown"


def _version(value: bool):
    if value:
        typer.echo(f"daxin {__version__} ({RULE_VERSION})")
        raise typer.Exit()


@app.callback()
def _main(version: bool = typer.Option(False, "--version", callback=_version, is_eager=True, help="显示版本")):
    pass


@app.command()
def init(ws: Path = WS):
    """创建工作区。"""
    _ctx(ws); typer.echo(f"已初始化 {ws}")


@policy_app.command("import-register")
def p_import_register(file: Path, ws: Path = WS, freeze: bool = typer.Option(False, help="导入后直接确认并冻结"), by: str = typer.Option("")):
    """从 ground_truth_register.xlsx 导入标准答案。"""
    _, _, pol, _ = _ctx(ws); n = import_register(file, pol, by or actor(), freeze); typer.echo(f"导入 {n} 个条款版本" + ("，已冻结" if freeze else "（草稿）"))


@policy_app.command("add")
def p_add(file: Path, ws: Path = WS, freeze: bool = False, by: str = typer.Option("")):
    """从 JSON 导入条款。"""
    _, _, pol, _ = _ctx(ws); who = by or actor()
    for c in json.loads(Path(file).read_text(encoding="utf-8")):
        c = Clause(**c); pol.add(c, who)
        if freeze:
            pol.confirm(c.id, c.version, who); pol.freeze(c.id, c.version, who)
    typer.echo("完成")


@policy_app.command("confirm")
def p_confirm(clause: str, version: str, ws: Path = WS, by: str = typer.Option("")):
    _, _, pol, _ = _ctx(ws); pol.confirm(clause, version, by or actor()); typer.echo("已确认")


@policy_app.command("freeze")
def p_freeze(clause: str, version: str, ws: Path = WS, by: str = typer.Option("")):
    _, _, pol, _ = _ctx(ws)
    try:
        pol.freeze(clause, version, by or actor())
    except PolicyError as e:
        typer.echo(f"失败：{e}"); raise typer.Exit(1)
    typer.echo("已冻结")


@policy_app.command("list")
def p_list(ws: Path = WS):
    _, _, pol, _ = _ctx(ws)
    for c in pol.clauses():
        typer.echo(f"{c.ref:<28}{c.status:<10}{c.effective_from}  {c.topic}  " + "; ".join(f"{f.key}={f.value}{f.unit}" for f in c.facts))


@policy_app.command("conflicts")
def p_conflicts(ws: Path = WS):
    """列出制度自身互相冲突的条款（不是 AI 的错）。"""
    _, _, pol, _ = _ctx(ws); cs = pol.conflicts()
    for a, b, k in cs:
        typer.echo(f"{k}: {a.ref} 与 {b.ref} 取值不同")
    typer.echo(f"冲突 {len(cs)} 处")


@app.command("observe-import")
def observe_import(log: Path, bank: Path, ws: Path = WS):
    """从 test_log.xlsx 导入观察记录与人工判定。"""
    _, _, _, st = _ctx(ws); typer.echo(str(import_log(log, bank, st, actor())))


@app.command()
def judge(ws: Path = WS):
    """对所有观察运行判定（机器建议；不参与统计）。"""
    _, _, pol, st = _ctx(ws); dist: dict[str, int] = {}
    for o in st.observations():
        j = classify(o, pol); st.save_judgment(j); dist[j.verdict] = dist.get(j.verdict, 0) + 1
    typer.echo("判定分布：" + "，".join(f"{k} {v}" for k, v in sorted(dist.items())))


@app.command()
def review(obs_id: str, verdict: str, by: str = typer.Option(...), note: str = "", ws: Path = WS):
    """人工复核。只有人工判定参与统计。"""
    if verdict not in VERDICTS:
        typer.echo(f"判定须为 {VERDICTS}"); raise typer.Exit(1)
    _, _, _, st = _ctx(ws); typer.echo("已记录" if st.add_review(obs_id, by, verdict, note) else "该复核人已复核过")


@app.command()
def release(ws: Path = WS, today: str = typer.Option("", help="YYYY-MM-DD，用于判断放行是否过期"),
            by: str = typer.Option("topic,region,channel,language", help="分组维度，逗号分隔；不同分组不要加总")):
    """主题级放行矩阵。"""
    from .demo import show
    _, _, pol, st = _ctx(ws); show(matrix(pol, st, today=date.fromisoformat(today) if today else None, group=tuple(x.strip() for x in by.split(",") if x.strip())))


@app.command()
def evidence(out: Path, ws: Path = WS, public: bool = typer.Option(False, help="对外输出：检查是否含机构名称")):
    """导出证据卡。--public 需要 private/institution_map.csv。"""
    _, _, pol, st = _ctx(ws); cards = build_cards(pol, st); text = markdown(cards)
    if public:
        try:
            assert_clean({"evidence": text}, load_names(Path(ws).parent / "private" / "institution_map.csv"))
        except AnonymityError as e:
            typer.echo(f"拒绝输出：{e}"); raise typer.Exit(1)
    Path(out).parent.mkdir(parents=True, exist_ok=True); Path(out).write_text(text, encoding="utf-8")
    typer.echo(f"证据卡 {len(cards)} 张（链校验{'通过' if verify_cards(cards) else '失败'}）→ {out}")


@app.command("audit-verify")
def audit_verify(ws: Path = WS):
    ok, bad = _ctx(ws)[1].verify(); typer.echo("审计链通过" if ok else f"审计链第 {bad} 条异常"); raise typer.Exit(0 if ok else 1)


@app.command()
def demo(dir: Path = typer.Option(Path(".daxin-demo"), help="演示工作区（会被清空）")):
    """端到端演示（仿真数据）。"""
    import shutil
    from .demo import run
    shutil.rmtree(dir, ignore_errors=True); r = run(dir)
    raise typer.Exit(0 if r["frozen_enforced"] and r["audit_ok"] and r["evidence_ok"] else 1)
