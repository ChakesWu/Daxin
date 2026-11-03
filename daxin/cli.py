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


def _inst(st: Store) -> str:
    insts = sorted({o.inst for o in st.observations() if o.inst})
    return insts[0] if len(insts) == 1 else ",".join(insts)


@app.command("route-export")
def route_export(out: Path, ws: Path = WS, today: str = typer.Option("", help="YYYY-MM-DD"),
                 by: str = typer.Option("topic,region,channel,language", help="分组维度，逗号分隔"),
                 max_age: int = typer.Option(30, help="放行有效天数，过期后路由须按 L3 处理")):
    """把放行矩阵导出为路由策略 JSON，供智能客服的意图路由读取（未列出的范围默认 L4 人工）。"""
    from .routing import build as route_build
    _, a, pol, st = _ctx(ws)
    rows = matrix(pol, st, today=date.fromisoformat(today) if today else None, max_age_days=max_age,
                  group=tuple(x.strip() for x in by.split(",") if x.strip()))
    doc = route_build(rows, _inst(st), [c.ref for c in pol.clauses(("frozen",))], a.head(), max_age)
    a.append(actor(), "routing.export", "routing", doc["sha256"], {"routes": len(doc["routes"]), "out": str(out)})
    Path(out).parent.mkdir(parents=True, exist_ok=True); Path(out).write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    typer.echo(f"路由策略 {len(doc['routes'])} 条范围 → {out}（sha256 {doc['sha256'][:12]}…）")


@app.command("route-check")
def route_check(file: Path, topic: str, region: str = "", channel: str = "", language: str = "",
                today: str = typer.Option("", help="YYYY-MM-DD，用于判断是否过期")):
    """按路由策略文件查询一个问题应走哪种模式（参考实现，供路由方对照）。"""
    from .routing import decide
    d = decide(json.loads(Path(file).read_text(encoding="utf-8")), topic, region, channel, language,
               date.fromisoformat(today) if today else None)
    typer.echo(f"{d['level']} {d['mode']}：{d['why']}")


@app.command()
def regress(ws: Path = WS, today: str = typer.Option("", help="YYYY-MM-DD，默认今天"), out: Path = typer.Option(None, help="另存 JSON")):
    """制度生效前回归：列出待生效条款须复测的问题，并按新标准预演已记录的回答（机器预演，不计入统计）。"""
    from .regress import plan, text
    _, _, pol, st = _ctx(ws); ps = plan(pol, st, date.fromisoformat(today) if today else date.today())
    typer.echo(text(ps))
    if out:
        Path(out).write_text(json.dumps(ps, ensure_ascii=False, indent=1), encoding="utf-8")


@app.command()
def report(out: Path, ws: Path = WS, today: str = typer.Option("", help="YYYY-MM-DD"), period: str = typer.Option("", help="测评期间"),
           by: str = typer.Option("topic,region,channel,language", help="分组维度")):
    """生成测评报告范本（Markdown），各节标注对应的金发〔2026〕8号条款。"""
    from .report import build as report_build
    _, a, pol, st = _ctx(ws); d = date.fromisoformat(today) if today else date.today()
    rows = matrix(pol, st, today=d, group=tuple(x.strip() for x in by.split(",") if x.strip()))
    days = sorted(o.day for o in st.observations())
    text = report_build(pol, st, a, rows, _inst(st), period or (f"{days[0]} 至 {days[-1]}" if days else "—"), d)
    Path(out).parent.mkdir(parents=True, exist_ok=True); Path(out).write_text(text, encoding="utf-8")
    typer.echo(f"报告范本 → {out}")


@app.command("export-demo")
def export_demo(out: Path = typer.Option(Path("site/index.html"), help="输出的单文件网页"),
                dir: Path = typer.Option(Path(".daxin-demo"), help="演示工作区（会被清空）")):
    """运行仿真演示，并把结果导出为可离线打开的网页（外部客户视角 + 内部验收视角）。"""
    import shutil
    from .webdemo import export
    shutil.rmtree(dir, ignore_errors=True)
    path = export(dir, out); typer.echo(f"网页 → {path}")


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
