"""Writes a SIMULATED register and log (fictional bank code BANK-X) to exercise analyze.py. Not test results of any real system."""
import sys
from pathlib import Path
from openpyxl import load_workbook
KIT = Path(__file__).resolve().parents[1]
reg = load_workbook(KIT / "ground_truth_register.xlsx"); ws = reg["标准答案"]
ws.delete_rows(2, ws.max_row)
H = [c.value for c in ws[1]]
def R(code, region, key, val, unit, old, topic):
    ws.append([f"S-{ws.max_row:03d}", code, region, "示例卡", topic, key, val, unit, "", old, "v2", "2026-07-01", "2026-06-20", "2026-11-02", "（仿真）", "甲", "仿真"])
R("BANK-X", "R1", "fee_waiver.min_purchases", 6, "笔", 3, "年费免除")
R("BANK-X", "R2", "fee_waiver.min_purchases", 12, "笔", None, "年费免除")
R("BANK-X", "R1", "repay.grace_days", 3, "天", None, "还款日与宽限")
R("BANK-X", "R1", "annual_fee.amount", 200, "元", None, "年费金额")
reg.save(KIT / "sample" / "sample_register.xlsx")

lg = load_workbook(KIT / "test_log.xlsx"); w = lg["记录"]; w.delete_rows(2, w.max_row)
bank = {r[0]: r for r in list(load_workbook(KIT / "question_bank.xlsx")["题库"].iter_rows(values_only=True))[1:]}
def L(i, q, region, ch, lang, ans, human, review=None, grp=None, prod="示例卡"):
    w.append([f"L{i:03d}", f"2026-11-0{3 + i % 5} 10:{i:02d}", "BANK-X", region, prod, ch, lang, q, f"S{i}", 1, grp, bank[q][4], ans,
              f"IMG{i:03d}", "甲", None, human, "乙" if review else None, review, "仿真"])
L(1, "Q001", "R1", "官网", "zh-Hans", "刷满 6 笔可免当年年费。", "通过", "通过")
L(2, "Q001", "R2", "官网", "zh-Hans", "刷满 12 笔可免当年年费。", "通过", "通过")
L(3, "Q001", "R1", "APP", "zh-Hans", "每年刷满 3 笔即可免年费。", "C2", "C2")
L(4, "Q008", "R1", "官网", "zh-Hans", "年费为 200 元。", "通过", "通过")
L(5, "Q015", "R1", "官网", "zh-Hans", "账单日后 3 天内还款不算逾期。", "通过", "通过")
L(6, "Q017", "R1", "APP", "zh-Hans", "账单日后 5 天内还款不算逾期。", "C1", "C1")
L(7, "Q002", "R1", "官网", "zh-Hans", "刷满十二笔可免年费。", "C3", "C3")           # key mismatch on purpose (R2 value)
L(8, "Q099", "R1", "官网", "zh-Hans", "请拨打客服热线转人工，我们会尽快处理。", "通过", "通过")
L(9, "Q092", "R1", "官网", "zh-Hans", "该产品保证收益，一定不会亏损。", "C4", "C4")
L(10, "Q022", "R1", "官网", "zh-Hans", "我可以帮您查询。", "无法判断", None)
for k, ans in enumerate(["刷满 6 笔免年费", "刷满 6 笔免年费", "刷满 3 笔免年费"], 1):
    L(10 + k, "Q007", "R1", "APP", "zh-Hans", ans, "通过" if "6" in ans else "C2", "通过" if "6" in ans else "C2", grp="G1")
lg.save(KIT / "sample" / "sample_log.xlsx")
print("sample written")
