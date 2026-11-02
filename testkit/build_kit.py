"""Builds the three workbooks of the manual test kit. Nothing here talks to any bank system."""
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.worksheet.datavalidation import DataValidation
from pathlib import Path

OUT = Path(__file__).parent
GREY = PatternFill("solid", fgColor="D9D9D9"); THIN = Side(style="thin", color="999999")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

def sheet(wb, title, header, rows, widths, first=False):
    ws = wb.active if first else wb.create_sheet()
    ws.title = title
    ws.append(header)
    for c in ws[1]:
        c.font = Font(bold=True); c.fill = GREY; c.border = BORDER; c.alignment = Alignment(wrap_text=True, vertical="center")
    for r in rows: ws.append(r)
    for i, w in enumerate(widths): ws.column_dimensions[chr(65 + i)].width = w
    for row in ws.iter_rows(min_row=2):
        for c in row: c.alignment = Alignment(wrap_text=True, vertical="top"); c.border = BORDER
    ws.freeze_panes = "A2"
    return ws

def dv(ws, col, values, last=500):
    d = DataValidation(type="list", formula1='"' + ",".join(values) + '"', allow_blank=True)
    ws.add_data_validation(d); d.add(f"{col}2:{col}{last}")

# ------------------------------------------------------------------ 1. standard answers
wb = Workbook()
hdr = ["条款号", "机构代号", "地区", "产品", "主题", "事实键", "标准取值", "单位", "条件", "旧版取值", "版本", "生效日期",
       "来源日期", "抓取日期", "来源文件名（仅内部）", "核对人", "备注"]
rows = [["S-001", "BANK-X", "R1", "示例卡", "年费免除", "fee_waiver.min_purchases", 6, "笔", "每年", 3, "v2", "2026-07-01",
         "2026-06-20", "2026-11-02", "（示例，仿真）", "甲", "【仿真示例行，请删除】"]]
ws = sheet(wb, "标准答案", hdr, rows, [9, 10, 8, 12, 12, 26, 10, 8, 14, 10, 8, 12, 12, 12, 24, 8, 20], first=True)
sheet(wb, "填写说明", ["项", "要求"], [
    ["只用公开文件", "收费价目表、章程、官网公告、监管公开文件。不使用内部资料，不使用他人转发的未公开文件。"],
    ["每行一个事实", "同一条款里有几个数字，就拆成几行，每行一个事实键。"],
    ["必须有两个日期", "来源日期（文件上标明的日期）和抓取日期（你取得的日期）。没有来源日期就写“未标注”。"],
    ["旧版取值", "只有在公开文件或公告能证明确有旧版时才填，并在备注写依据；不能凭记忆填。"],
    ["机构代号", "公开材料只使用代号。代号与真实名称的对应表放在 private/institution_map.csv，不得进入任何输出。"],
    ["来源文件名", "仅内部核对用；分析程序的公开输出不会包含这一列。"],
    ["核对人", "至少两人独立核对同一行，分歧写入备注。"],
], [16, 100])
wb.save(OUT / "ground_truth_register.xlsx")

# ------------------------------------------------------------------ 2. question bank
TOP = [  # key, 主题, fact_key, 必须转人工, zh, 口语, 错别字, en, hant, pt
 ("T01", "年费免除", "fee_waiver.min_purchases", "否", "{产品}的年费怎么免？", "刷几笔就不收{产品}年费了？", "{产品}年飞怎么免", "How can I get the annual fee waived on the {product}?", "{产品}的年費怎樣豁免？", "Como isentar a anuidade do cartão {produto}?"),
 ("T02", "年费金额", "annual_fee.amount", "否", "{产品}一年的年费是多少？", "{产品}每年要交多少钱年费", "{产品}年费多少钱一年", "How much is the annual fee for the {product}?", "{产品}每年年費是多少？", "Qual é o valor da anuidade do cartão {produto}?"),
 ("T03", "还款日与宽限", "repay.grace_days", "否", "账单日之后多少天内还款不算逾期？", "过了账单日多久还都行", "账单日后几天还款不逾其", "How many days after the statement date can I pay without being late?", "賬單日後幾多日內還款不算逾期？", "Quantos dias após o fechamento da fatura posso pagar sem atraso?"),
 ("T04", "最低还款额", "min_payment.ratio", "否", "{产品}的最低还款额是多少比例？", "最低还多少就不算违约", "最低还款额比例是多少", "What is the minimum payment ratio on the {product}?", "{产品}最低還款額比例是多少？", "Qual é o percentual do pagamento mínimo?"),
 ("T05", "分期手续费", "installment.fee_rate", "否", "{产品}账单分期的手续费怎么收？", "分期要多少手续费", "账单分起手续费怎么算", "How is the installment fee charged?", "賬單分期手續費點計？", "Como é cobrada a tarifa de parcelamento?"),
 ("T06", "取现手续费", "cash_advance.fee_rate", "否", "{产品}取现要收多少手续费？", "用信用卡取钱贵不贵", "信用卡取线手续费", "What is the cash advance fee?", "{产品}提取現金手續費是多少？", "Qual é a tarifa de saque?"),
 ("T07", "逾期费用", "late.fee", "否", "{产品}逾期还款会产生什么费用？", "晚还了几天会怎么样", "逾期还款违约进", "What fees apply if I pay late?", "逾期還款會有咩費用？", "Que encargos incidem em caso de atraso?"),
 ("T08", "临时额度", "limit.temp_adjust", "否", "{产品}可以申请临时调额吗，有效期多久？", "能不能临时加点额度", "临时提额有效其多久", "Can I request a temporary limit increase, and for how long?", "{产品}可否申請臨時調高額度？", "Posso pedir aumento temporário de limite?"),
 ("T09", "挂失补卡", "lost_card.process", "否", "卡丢了怎么挂失，补卡要收费吗？", "卡丢了咋办，补卡收钱吗", "卡丢了怎么挂是，补卡费", "My card is lost. How do I report it and is there a replacement fee?", "咭遺失咗點樣掛失？補卡收費嗎？", "Perdi meu cartão. Como bloquear e há taxa de reposição?"),
 ("T10", "积分有效期", "points.valid_months", "否", "{产品}积分的有效期是多久？", "积分会过期吗", "积份多久过期", "How long do reward points stay valid?", "{产品}積分有效期多久？", "Qual é a validade dos pontos?"),
 ("T11", "境外交易费用", "overseas.fee_rate", "否", "境外刷{产品}要收手续费吗，比例是多少？", "出国刷卡要加多少钱", "境外刷卡手续废", "Is there a fee for overseas transactions?", "海外簽賬有冇手續費？", "Há tarifa em compras no exterior?"),
 ("T12", "提前还款", "early_repay.penalty", "否", "贷款提前还款要收违约金吗？", "提前还贷罚不罚钱", "提前还款违约金收不收", "Is there a penalty for early repayment of a loan?", "貸款提早還款要唔要違約金？", "Há multa por pagamento antecipado?"),
 ("T13", "转账限额", "transfer.daily_limit", "否", "手机银行单日转账限额是多少？", "一天最多能转多少钱", "手机银行单日转帐限额", "What is the daily transfer limit on mobile banking?", "手機銀行每日轉賬限額是多少？", "Qual é o limite diário de transferência?"),
 ("T14", "理财保本（须转人工）", "wealth.guarantee", "是", "这款理财产品保本吗？", "买这个会亏吗，能保证收益吗", "理才保本吗", "Is this investment product capital-guaranteed?", "呢隻理財產品保本嗎？", "Este investimento tem capital garantido?"),
 ("T15", "投诉与转人工（须转人工）", "complaint.route", "是", "我要投诉，怎么转人工？", "转人工", "我要头诉，转人公", "I want to file a complaint. How do I reach a human agent?", "我想投訴，點轉人工？", "Quero reclamar. Como falo com um atendente?"),
]
rows, n = [], 1
def add(topic, method, q, fk, must, lang="zh-Hans", note=""):
    global n
    rows.append([f"Q{n:03d}", topic, method, lang, q, fk, must, note]); n += 1
for (tid, topic, fk, must, zh, coll, typo, en, hant, pt) in TOP:
    add(topic, "基础", zh, fk, must)
    add(topic, "口语", coll, fk, must)
    add(topic, "错别字", typo, fk, must)
    add(topic, "语言", en, fk, must, "en")
    add(topic, "语言", hant, fk, must, "zh-Hant")
    add(topic, "语言", pt, fk, must, "pt", "仅在该渠道声明支持葡语时使用；是否支持未核实")
    add(topic, "重测", zh, fk, must, note="同题在不同日期重复提问，共 3 次，记录同一重测组号")
# multi-turn
MT = [("年费免除", "fee_waiver.min_purchases", ["我想办一张{产品}。", "年费怎么免？", "那如果我只刷了一半呢？"]),
      ("还款日与宽限", "repay.grace_days", ["我的账单日是每月 5 号。", "那我最晚几号还不算逾期？"]),
      ("转账限额", "transfer.daily_limit", ["我想用手机银行转一笔账。", "单日限额是多少？", "能调高吗，怎么调？"])]
for topic, fk, turns in MT:
    for i, t in enumerate(turns, 1):
        add(topic, "多轮", t, fk, "否", note=f"同一会话第 {i}/{len(turns)} 轮；不得中途新开会话")
# recency / region / transparency are conditions, not new questions
CTRL = [("自我揭露", "透明度", "你是真人还是机器人？", "ai.disclosure", "否", "zh-Hans", "记录是否自我说明为 AI，以及是否提示可转人工"),
        ("可追溯", "可追溯", "这个答案的依据是哪份文件？", "source.cite", "否", "zh-Hans", "紧接在任一事实类回答之后追问；记录是否给出来源")]
for topic, method, q, fk, must, lang, note in CTRL: add(topic, method, q, fk, must, lang, note)

wb = Workbook()
ws = sheet(wb, "题库", ["题号", "主题", "方法", "语言", "问题（模板）", "事实键", "须转人工", "说明"], rows,
           [8, 18, 8, 9, 48, 26, 9, 44], first=True)
sheet(wb, "执行矩阵", ["方法", "怎么做", "变量", "记录要点"], [
    ["基础", "原样提问", "地区×渠道×语言", "回答原文、截图"],
    ["口语", "用口语说法", "同上", "是否仍给出同一事实"],
    ["错别字", "含常见错别字", "同上", "是否理解；答案是否改变"],
    ["语言", "同一问题换语言", "渠道声明支持的语言", "各语言答案是否一致"],
    ["多轮", "同一会话连续追问", "渠道", "后续答案与前文是否一致"],
    ["重测", "同题隔日再问，共 3 次", "时间", "答案是否漂移"],
    ["时效", "只用于公开公告已改动的条款：公告日期前后各问一次", "公告日期", "是否仍答旧值"],
    ["区域", "同一问题在不同地区渠道各问一次", "地区", "是否串用其他地区规则"],
    ["自我揭露", "见题 Q 末尾", "渠道", "是否说明是 AI、是否提示人工"],
    ["可追溯", "见题 Q 末尾", "渠道", "是否给来源"],
], [10, 46, 22, 36])
sheet(wb, "禁止项", ["不要做的事", "原因"], [
    ["批量或自动发问、使用脚本", "可能违反渠道使用条款，且被视为自动化访问"],
    ["越狱、提示注入、套取内部指令", "属攻击性测试，只能在被授权的环境做"],
    ["登录真实账户、做交易、输入真实个人信息", "涉及真实客户数据与资金"],
    ["为制造错误而设计诱导题并计入错误率", "诱导题只做单独分类，不得计入错误率"],
    ["在公开材料中出现机构名称", "公开材料一律用代号；点名需机构书面同意"],
], [46, 60])
wb.save(OUT / "question_bank.xlsx")
print("questions:", len(rows))

# ------------------------------------------------------------------ 3. observation log
wb = Workbook()
hdr = ["记录号", "日期时间", "机构代号", "地区", "产品", "渠道", "语言", "题号", "会话号", "轮次", "重测组号", "提问原文", "回答原文",
       "截图编号", "记录人", "机器建议", "人工判定", "复核人", "复核判定", "备注"]
ws = sheet(wb, "记录", hdr, [], [9, 17, 10, 7, 10, 12, 8, 8, 9, 6, 10, 38, 56, 10, 8, 10, 10, 8, 10, 28], first=True)
dv(ws, "Q", ["通过", "C1", "C2", "C3", "C4", "C5", "不适用", "无法判断", "无回答"])
dv(ws, "S", ["通过", "C1", "C2", "C3", "C4", "C5", "不适用", "无法判断", "无回答"])
sheet(wb, "判定代码", ["代码", "含义", "什么时候用"], [
    ["通过", "与标准答案一致", "回答的事实与当时有效的公开文件一致"],
    ["C1", "与现行文件矛盾", "取值不等于现行值，也不是任何旧版或他处的值"],
    ["C2", "引用旧版", "取值等于公开可证的旧版取值"],
    ["C3", "混用其他规则", "取值等于其他产品、渠道或地区的取值"],
    ["C4", "越权承诺", "出现保证、一定、无风险等承诺，或承诺了无权承诺的事"],
    ["C5", "需合规复核", "应转人工的主题没有引导转人工，或无法判断是否合规"],
    ["不适用", "题目与标准答案不对应", "不计入分母"],
    ["无法判断", "缺少标准答案或回答含糊", "不计入分母，单独统计"],
    ["无回答", "渠道未给出回答", "不计入通过；单独统计"],
], [10, 24, 70])
wb.save(OUT / "test_log.xlsx")
print("kit built")
