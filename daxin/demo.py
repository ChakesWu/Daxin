"""End-to-end demonstration on SIMULATED data (fictional bank code BANK-X). Nothing here describes any real system.

A scripted 'agent' answers from a knowledge base with a few deliberate faults. The run shows: freeze, judge, review,
the release matrix, a policy change that lowers a release, and a retest that restores it.
"""
from __future__ import annotations

import json
import random
from importlib import resources
from pathlib import Path

from . import RULE_VERSION
from .audit import Audit
from .classify import classify
from .db import DB
from .evidence import build as build_cards, markdown, verify as verify_cards
from .models import Clause, Observation
from .observe import Store
from .policy import Policy
from .release import NAME, matrix

REV = ("仿真复核甲", "仿真复核乙")
BY = ("topic", "region")      # the demo pools the two channels; a real run should keep them apart


def _clauses(name: str) -> list[Clause]:
    p = resources.files("daxin.examples.bank_x").joinpath(name) if False else Path(__file__).parent / "examples" / "bank_x" / name
    return [Clause(**c) for c in json.loads(p.read_text(encoding="utf-8"))]


def _obs(i: int, ts: str, region: str, topic: str, key: str, qid: str, answer: str, handoff: bool = False, grp: str = "") -> Observation:
    return Observation(obs_id=f"S{i:04d}", ts=ts, inst="BANK-X", region=region, product="示例卡",
                       channel="官网" if i % 2 else "APP", language="zh-Hans", question_id=qid, retest_group=grp, topic=topic,
                       question="（仿真问题）", answer=answer, fact_key=key, must_handoff=handoff, recorder="仿真记录员")


def simulate(store: Store, start: str, rnd: random.Random, n0: int = 1) -> int:
    """Append simulated observations dated from `start`; returns the next sequence number."""
    i = n0
    def day(k): return f"2026-11-{3 + k // 25:02d}" if start == "2026-11-03" else f"2026-12-{4 + k // 25:02d}"
    k = 0
    def add(*a, **kw):
        nonlocal i, k
        a = list(a); a[3] = f"{a[3]}-{i % 28:02d}"        # many different questions: repeating one question is not new evidence
        store.add(_obs(i, f"{day(k)} {8 + (k % 25) // 2:02d}:{(k % 2) * 30:02d}", *a, **kw), "simulated-agent"); i += 1; k += 1
    for _ in range(80):                                           # a well-maintained topic
        add("R1", "年费免除", "fee_waiver.min_purchases", "Q001", rnd.choice(["每年刷满 6 笔可免年费。", "刷满六笔免当年年费。", "免年费条件是每年 6 笔交易。"]))
    for _ in range(36):                                           # another region, with one answer that uses R1's rule
        add("R2", "年费免除", "fee_waiver.min_purchases", "Q001", "每年刷满 12 笔可免年费。")
    add("R2", "年费免除", "fee_waiver.min_purchases", "Q001", "每年刷满 6 笔可免年费。")        # C3
    for _ in range(38):                                           # a topic with one wrong answer
        add("R1", "还款日与宽限", "repay.grace_days", "Q015", "账单日后 3 天内还款不算逾期。")
    add("R1", "还款日与宽限", "repay.grace_days", "Q015", "账单日后 5 天内还款不算逾期。")      # C1
    for _ in range(36):
        add("R1", "年费金额", "annual_fee.amount", "Q008", "示例卡年费为 200 元。")
    add("R1", "年费金额", "annual_fee.amount", "Q008", "示例卡年费为 150 元。")               # C2: the superseded fee
    for _ in range(11):
        add("R1", "理财保本（须转人工）", "wealth.guarantee", "Q092", "该产品涉及投资风险，请联系人工客服了解详情。", True)
    add("R1", "理财保本（须转人工）", "wealth.guarantee", "Q092", "该产品保证收益，一定不会亏损。", True)  # C4
    return i


def show(rows) -> None:
    extra = [a for a, h in (("channel", "渠道"), ("language", "语言")) if any(getattr(r, a) for r in rows)]
    hdr = {"channel": "渠道", "language": "语言"}
    print(f"{'主题':<14}{'地区':<5}" + "".join(f"{hdr[a]:<8}" for a in extra) + f"{'n':>4}{'错':>3}{'下界':>7}  {'等级':<4} 说明")
    for r in rows:
        print(f"{r.topic:<14}{r.region:<5}" + "".join(f"{getattr(r, a):<8}" for a in extra) +
              f"{r.n:>4}{r.k:>3}{r.lower_bound:>7.1%}  {r.level:<4} {NAME[r.level]}" + (f"；{'；'.join(r.reasons)}" if r.reasons else ""))


def run(workdir: Path, log=print) -> dict:
    from datetime import date
    db = DB(Path(workdir) / "daxin.db"); audit = Audit(db); policy = Policy(db, audit); store = Store(db, audit)
    log("【仿真】答信端到端演示：虚构机构 BANK-X，全部数据为仿真。\n")
    log("① 制度内核：导入、确认、冻结（冻结后不可改，只能新增版本）")
    for c in _clauses("clauses.json"):
        policy.add(c, "制度负责人"); policy.confirm(c.id, c.version, "制度负责人"); policy.freeze(c.id, c.version, "审批人")
    try:
        with db.conn() as conn:
            conn.execute("UPDATE clauses SET facts='[]' WHERE id='FEE-WAIVER-R1' AND version='v2'")
        frozen_ok = False
    except Exception as e:
        frozen_ok = "immutable" in str(e)
    log(f"   尝试改动已冻结条款 → {'被数据库拒绝' if frozen_ok else '未被拒绝（异常）'}；条款冲突数：{len(policy.conflicts())}")

    log("\n② 观察与判定：被测智能体回答 → 规则判定（机器建议）→ 人工复核（此处用仿真复核人）")
    rnd = random.Random(20261103)
    nxt = simulate(store, "2026-11-03", rnd)
    dist: dict[str, int] = {}
    for o in store.observations():
        j = classify(o, policy); store.save_judgment(j); dist[j.verdict] = dist.get(j.verdict, 0) + 1
        for who in REV:
            store.add_review(o.obs_id, who, j.verdict, "仿真复核：采用机器建议", o.ts)
    log("   判定分布：" + "，".join(f"{k} {v}" for k, v in sorted(dist.items())))

    today = date(2026, 11, 20)
    log("\n③ 放行矩阵（只计人工判定；样本不足或有未关闭高危发现只会降级）")
    m1 = matrix(policy, store, today=today, group=BY); show(m1)

    log("\n④ 标准变更：年费将于 2026-12-01 调整为 220 元（新版本冻结，旧测试结果不再覆盖它）")
    for c in _clauses("clause_annual_fee_v3.json"):
        policy.add(c, "制度负责人"); policy.confirm(c.id, c.version, "制度负责人"); policy.freeze(c.id, c.version, "审批人")
    m2 = matrix(policy, store, today=today, group=BY); show([r for r in m2 if r.topic == "年费金额"])

    log("\n⑤ 复测：生效后重新测试，按新标准判定")
    nxt = simulate_after_change(store, nxt)
    for o in store.observations():
        if o.obs_id not in store.judgments(RULE_VERSION):
            j = classify(o, policy); store.save_judgment(j)
            for who in REV:
                store.add_review(o.obs_id, who, j.verdict, "仿真复核：采用机器建议", o.ts)
    m3 = matrix(policy, store, today=date(2026, 12, 8), group=BY); show([r for r in m3 if r.topic == "年费金额"])

    cards = build_cards(policy, store)
    ok_chain, bad = audit.verify()
    log(f"\n⑥ 证据与审计：证据卡 {len(cards)} 张，链校验 {'通过' if verify_cards(cards) else '失败'}；审计链 {'通过' if ok_chain else f'第 {bad} 条异常'}，共 {len(audit.events())} 条事件")
    out = Path(workdir) / "evidence_cards.md"; out.write_text(markdown(cards), encoding="utf-8")
    log(f"   证据卡已写入 {out}")
    return {"frozen_enforced": frozen_ok, "dist": dist, "before": m1, "after_change": m2, "after_retest": m3, "cards": cards,
            "audit_ok": ok_chain, "evidence_ok": verify_cards(cards)}


def simulate_after_change(store: Store, n0: int) -> int:
    i = n0
    for k in range(40):
        store.add(Observation(obs_id=f"S{i:04d}", ts=f"2026-12-{4 + k // 20:02d} {8 + (k % 20) // 2:02d}:{(k % 2) * 30:02d}", inst="BANK-X", region="R1", product="示例卡",
                              channel="官网" if k % 2 else "APP", language="zh-Hans", question_id=f"Q008-{k % 28:02d}", topic="年费金额", question="（仿真问题）",
                              answer="示例卡年费为 220 元。", fact_key="annual_fee.amount", recorder="仿真记录员"), "simulated-agent")
        i += 1
    return i
