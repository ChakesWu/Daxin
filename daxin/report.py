"""Assessment report TEMPLATE for regulators and internal audit, generated from a workspace.

Sections are mapped to the articles of the regulator's guidance on AI in banking and insurance (金发〔2026〕8号, issued
2026-06-18) checked article by article against the full text of the guidance. The mapping says which article a section serves;
it is not a legal opinion that the requirement is met. Check against the official text before relying on it.
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


CROSSWALK = [
    ("四", "完善测评体系：测试工具链、测评指标、测试用例集", "覆盖：第 3、4 节"),
    ("五", "生成式模型准入管理，评估效能及安全合规性；外部引入需网信部门备案", "部分：第 4、5 节可作准入评估材料；备案不覆盖"),
    ("六", "定期开展模型效能测评分析", "覆盖：第 5 节放行过期即降级、须复测"),
    ("十一", "知识创建、审核、发布、更新到归档的全流程管理", "部分：第 2 节以冻结版本为标准；不审查机构知识库本身"),
    ("十四", "防范模型生成结果不可靠风险", "覆盖：第 4、6 节"),
    ("十五", "风险分类分级管理，制定应用清单，实施分级管控", "覆盖：第 5 节（等级阈值须机构确认）"),
    ("十六", "高风险应用须经本机构风险管理委员会批准", "不覆盖：是否属高风险及审批由机构认定"),
    ("十七", "高风险环节人工监督和干预，紧急停用条件，人工替代流程", "部分：第 5 节给出转人工建议；不检查机构流程"),
    ("十八", "外包合作名单制，对引入的外部模型建立内部评估框架", "部分：第 7 节独立测评可作评估输入；合同与名单管理不覆盖"),
    ("二十", "稳健性：对抗样本检测、压力测试、部署后持续监测", "部分：持续监测见第 5 节；不做对抗样本与压力测试"),
    ("二十一", "透明度；生成内容显著标识并主动说明；开发与训练日志留存", "不覆盖"),
    ("二十二", "高风险场景人工最终决策；保留原始数据与阈值触发记录；算法审计", "部分：第 7 节测评记录可追溯；不审计被测算法"),
    ("二十三", "伦理审查与公平性，避免算法歧视", "不覆盖"),
    ("二十四", "数据安全与个人信息保护，个人信息不得用于生成式模型训练", "不覆盖（测评回答先脱敏再存）"),
    ("二十五", "对抗攻击测试，防范提示词注入等", "不覆盖：本工具不做越狱或提示注入"),
    ("二十六", "业务连续性：故障时人工流程及时介入", "部分：第 5 节 L4 转人工；不检查容灾"),
    ("二十九", "面向公众服务使用生成式人工智能须向监管报告", "不覆盖：由机构履行"),
]


def art(*ns: str) -> str:
    return f"《指导意见》第{'、'.join(ns)}条"


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
         "> 本工具是制度一致性检查与风险提示工具，不构成法律意见。各节标注其服务的监管条款，仅表示对应关系，不表示该要求已经满足；使用前请对照正式文本。",
         f"> 下文《指导意见》指{GUIDE}。", "",
         "## 1 测评对象与范围", "",
         f"- 机构代号：{inst}（报告不含机构名称）", f"- 测评期间：{period}", f"- 渠道：{'、'.join(chans) or '—'}　语言：{'、'.join(langs) or '—'}",
         f"- 主题数：{len({r.topic for r in rows})}　观察记录：{len(obs)} 条", f"- 对应：{art('十五')}（按业务场景重要性、应用规模、对客影响度等分类分级）；与客户利益直接相关的生成式人工智能场景应用视为高风险应用（第十六条），是否属于高风险由机构认定",
         "- 面向公众服务使用生成式人工智能的报告义务（第二十九条）由机构履行；本报告只提供测评事实，不替代该报告", "",
         "## 2 测评标准", "",
         f"以经机构确认并冻结的制度版本为唯一标准，共 {len(frozen)} 个条款版本。冻结后不可修改，只能新增版本（数据库触发器强制）。", "",
         f"对应：{art('十一')}（知识创建、审核、发布、更新到归档的全流程管理）；用于检查{art('十四')}所称“模型生成结果不可靠”风险。", "",
         "| 条款版本 | 主题 | 生效日 | 出处 |", "|---|---|---|---|"]
    L += [f"| {c.ref} | {c.topic} | {c.effective_from} | {c.source_ref} |" for c in frozen]
    L += ["", "## 3 测评方法", "",
          "- 黑盒观察：只记录问题与回答，不接触被测系统的模型、提示词或知识库。",
          "- 机器判定为建议；只有两名复核人一致的人工判定计入统计，分歧记为待人工。",
          "- 判定顺序：C1 与现行制度矛盾、C2 引用旧版、C3 混用其他范围、C4 越权承诺、C5 需合规复核；抽不到主张不判通过。",
          f"- 比率附 Wilson 95% 区间下界；样本不足、未关闭高危发现、标准变更未复测、结果过期只会降级。", f"- 对应：{art('四')}（测试工具链、测评指标、测试用例集，评估金融业务支持能力与安全可靠性）；{art('六')}（定期测评模型效能）；{art('五')}所称生成式模型准入评估中的“效能及安全合规性”可引用本节结果", 
          "- 机器判定只作建议、由人工最终确认，与第二十二条“由人工进行最终决策”的原则一致；这是测评方自身的做法，不表示被测机构已设置人工复核节点", "",
          "## 4 判定结果", "", "| 结果 | 条数 |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in sorted(dist.items())]
    L += ["", "## 5 分类分级放行结果", "", f"对应：{art('十五')}（制定应用清单、实施分级管控措施）；L4 转人工、L2 人工确认对应{art('十七')}（高风险应用关键环节的人工监督和干预、人工替代流程）及第二十六条（人工流程及时介入）；放行过期即降级对应{art('二十')}（部署后持续监测性能表现）。等级阈值为示例值，须经本机构确认。", "",
          "| 主题 | 地区 | 渠道 | 语言 | n | 错 | 正确率下界 | 等级 | 说明 |", "|---|---|---|---|---|---|---|---|---|"]
    L += [f"| {r.topic} | {r.region or '全部'} | {r.channel or '全部'} | {r.language or '全部'} | {r.n} | {r.k} | {r.lower_bound:.1%} | "
          f"{r.level} {NAME[r.level]} | {'；'.join(r.reasons) or '—'} |" for r in rows]
    L += ["", "## 6 发现与证据", "", f"经人工确认的差异 {len(cards)} 项，证据卡链式校验{'通过' if verify_cards(cards) else '失败'}。对应：{art('十四')}（防范模型生成结果不可靠风险）、{art('十七')}（及时发现和管控模型风险）。", "",
          "| 编号 | 类别 | 风险 | 依据 | 判定理由 |", "|---|---|---|---|---|"]
    L += [f"| {c['id']} | {c['verdict']} | {c['grade'] or '—'} | {c['clause']} | {c['reason']} |" for c in cards]
    L += ["", "## 7 可追溯性与独立性", "",
          f"- 审计链：{'校验通过' if ok_chain else f'第 {bad} 条异常'}，共 {len(audit.events())} 条事件；链头 `{audit.head()[:16]}…`",
          "- 每项结论可追溯到（条款版本、回答原文哈希、规则版本）。", "- 测评方与被测系统的建设方、服务商相互独立。",
          f"- 对应：{art('二十二')}（完整保留原始数据及阈值触发记录，确保责任可追溯）；独立测评可作为{art('十八')}所称对引入外部模型的内部评估的输入之一",
          "- 本链只记录测评过程，不是第二十一条所称被测系统的模型开发、变更与训练过程日志", "",
          "## 8 局限与待改进", "",
          "- 抽取规则只覆盖有限句式，漏判落入待人工；阈值为示例值，须用试点数据校准。",
          "- 样本量不足的主题只能给出保守等级。", "- 不在本测评范围：见第 9 节“不覆盖”各行。", "",
          "## 9 条款对应总表", "",
          "条款序号依《指导意见》正文（一）至（三十二）。“覆盖”指本报告提供与该条相关的测评事实，不表示该条要求已经满足。", "",
          "| 条款 | 要求（摘要） | 本报告 |", "|---|---|---|"]
    L += [f"| 第{n}条 | {req} | {cov} |" for n, req, cov in CROSSWALK]
    L += [""]
    return "\n".join(L)
