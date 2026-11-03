"""Assessment report TEMPLATE for regulators and internal audit, generated from a workspace.

Sections are mapped to the articles of the regulator's guidance on AI in banking and insurance (金发〔2026〕8号, issued
2026-06-18) as read from a government reprint of the full text. The mapping says which article a section serves; it is
not a legal opinion that the requirement is met. Check against the official text before relying on it.
"""
from __future__ import annotations

from collections import Counter
from datetime import date

from . import RULE_VERSION, __version__
from .audit import Audit
from .evidence import build as build_cards, verify as verify_cards
from .observe import Store
from .policy import Policy
from .release import NAME, Row

GUIDE = "《关于银行业保险业人工智能安全开发应用的指导意见》（金发〔2026〕8号）"
ALIGN = GUIDE  # kept for callers of the template; every section now names its article


def art(*ns: str) -> str:
    return f"{GUIDE}第{'、'.join(ns)}条"


def build(policy: Policy, store: Store, audit: Audit, rows: list[Row], inst: str, period: str, today: date) -> str:
    obs, final = store.observations(), store.final_verdicts()
    dist = Counter(final.get(o.obs_id, "未复核") for o in obs)
    cards = build_cards(policy, store)
    ok_chain, bad = audit.verify()
    frozen = policy.clauses(("frozen",))
    langs = sorted({o.language for o in obs if o.language})
    chans = sorted({o.channel for o in obs if o.channel})
    L = [f"# 智能客服回答测评报告（范本）", "",
         f"> 本报告由答信 {__version__}（规则 {RULE_VERSION}）于 {today.isoformat()} 生成。所有数字来自工作区实际数据。",
         "> 本工具是制度一致性检查与风险提示工具，不构成法律意见。各节标注其服务的监管条款，仅表示对应关系，不表示该要求已经满足；使用前请对照正式文本。", "",
         "## 1 测评对象与范围", "",
         f"- 机构代号：{inst}（报告不含机构名称）", f"- 测评期间：{period}", f"- 渠道：{'、'.join(chans) or '—'}　语言：{'、'.join(langs) or '—'}",
         f"- 主题数：{len({r.topic for r in rows})}　观察记录：{len(obs)} 条", f"- 对应：{art('十五', '十六')}（风险分类分级、对客生成式应用属高风险）；报告用途参见第二十九条", "",
         "## 2 测评标准", "",
         f"以经机构确认并冻结的制度版本为唯一标准，共 {len(frozen)} 个条款版本。冻结后不可修改，只能新增版本（数据库触发器强制）。", "",
         "| 条款版本 | 主题 | 生效日 | 出处 |", "|---|---|---|---|"]
    L += [f"| {c.ref} | {c.topic} | {c.effective_from} | {c.source_ref} |" for c in frozen]
    L += ["", "## 3 测评方法", "",
          "- 黑盒观察：只记录问题与回答，不接触被测系统的模型、提示词或知识库。",
          "- 机器判定为建议；只有两名复核人一致的人工判定计入统计，分歧记为待人工。",
          "- 判定顺序：C1 与现行制度矛盾、C2 引用旧版、C3 混用其他范围、C4 越权承诺、C5 需合规复核；抽不到主张不判通过。",
          f"- 比率附 Wilson 95% 区间下界；样本不足、未关闭高危发现、标准变更未复测、结果过期只会降级。", f"- 对应：{art('四')}（测评体系、测评指标、测试用例集）；人工复核对应{art('十七', '二十二')}（人工监督与干预、最终决策由人作出）", "",
          "## 4 判定结果", "", "| 结果 | 条数 |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in sorted(dist.items())]
    L += ["", "## 5 分类分级放行结果", "", f"对应：{art('十五')}（按场景重要性、对客影响度等分级管控）。等级阈值为示例值，须经本机构确认。", "",
          "| 主题 | 地区 | 渠道 | 语言 | n | 错 | 正确率下界 | 等级 | 说明 |", "|---|---|---|---|---|---|---|---|---|"]
    L += [f"| {r.topic} | {r.region or '全部'} | {r.channel or '全部'} | {r.language or '全部'} | {r.n} | {r.k} | {r.lower_bound:.1%} | "
          f"{r.level} {NAME[r.level]} | {'；'.join(r.reasons) or '—'} |" for r in rows]
    L += ["", "## 6 发现与证据", "", f"经人工确认的差异 {len(cards)} 项，证据卡链式校验{'通过' if verify_cards(cards) else '失败'}。", "",
          "| 编号 | 类别 | 风险 | 依据 | 判定理由 |", "|---|---|---|---|---|"]
    L += [f"| {c['id']} | {c['verdict']} | {c['grade'] or '—'} | {c['clause']} | {c['reason']} |" for c in cards]
    L += ["", "## 7 可追溯性与独立性", "",
          f"- 审计链：{'校验通过' if ok_chain else f'第 {bad} 条异常'}，共 {len(audit.events())} 条事件；链头 `{audit.head()[:16]}…`",
          "- 每项结论可追溯到（条款版本、回答原文哈希、规则版本）。", "- 测评方与被测系统的建设方、服务商相互独立。",
          f"- 对应：{art('二十一', '二十二')}（日志留存、完整保留记录、责任可追溯）", "",
          "## 8 局限与待改进", "",
          "- 抽取规则只覆盖有限句式，漏判落入待人工；阈值为示例值，须用试点数据校准。",
          "- 样本量不足的主题只能给出保守等级。", f"- 不在本测评范围：生成内容的显著标识（第二十一条）、算法歧视（第二十三条）、个人信息用于训练（第二十四条）、外部模型备案与评估（第五、十八条）。", ""]
    return "\n".join(L)
