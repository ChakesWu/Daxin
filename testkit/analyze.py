#!/usr/bin/env python3
"""Offline analysis of a manual test log. It reads two workbooks you filled in by hand and never contacts any system.

  python analyze.py --log test_log.xlsx --register ground_truth_register.xlsx --bank question_bank.xlsx --out out [--public]

Outputs (in --out): report.md, stats.csv, evidence_cards.md (one card per confirmed discrepancy, hash-chained).
With --public the program refuses to write anything that contains an institution name listed in private/institution_map.csv.
"""
from __future__ import annotations
import argparse, csv, hashlib, math, re, sys
from collections import defaultdict
from pathlib import Path
from openpyxl import load_workbook

ERR = {"C1", "C2", "C3", "C4"}           # confirmed wrong answers
SCORED = {"通过"} | ERR                   # the denominator
CN = {"零": 0, "一": 1, "二": 2, "两": 3 - 1, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
PROMISE = re.compile(r"保证|一定(能|会|可以)|绝对|肯定(能|会)|无风险|稳赚|已为您(批准|通过)|保本保收益")
HANDOFF = re.compile(r"转人工|人工(客服|服务|坐席)|客服热线|拨打|联系(客户经理|网点)|柜台|客服电话|human agent|contact (a|an) (agent|representative)", re.I)
NUM = re.compile(r"\d+(?:\.\d+)?%?|[零一二两三四五六七八九十]{1,3}")

def cn_to_int(t: str):
    if t == "十": return 10
    if t.startswith("十") and len(t) == 2: return 10 + CN.get(t[1], 0)
    if t.endswith("十") and len(t) == 2: return CN.get(t[0], 0) * 10
    if "十" in t and len(t) == 3: return CN.get(t[0], 0) * 10 + CN.get(t[2], 0)
    return CN.get(t) if len(t) == 1 else None

def numbers(text: str) -> list[float]:
    """Numbers as written: 5% is read as 5 (write ratios in the register in percent units too)."""
    out = []
    for m in NUM.findall(text or ""):
        if m[0].isdigit():
            out.append(float(m.rstrip("%")))
        else:
            v = cn_to_int(m)
            if v is not None: out.append(float(v))
    return out

def wilson(k: int, n: int, z: float = 1.96):
    if n == 0: return (0.0, 1.0)
    p = k / n; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d; h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))

def mask(t: str) -> str:
    t = re.sub(r"\d[\d ]{6,}\d", lambda m: m.group(0)[:2] + "*" * (len(m.group(0)) - 4) + m.group(0)[-2:], t or "")
    return re.sub(r"([\w.+-])[\w.+-]*@([\w-]+(?:\.[\w-]+)+)", r"\1***@\2", t)

def read(path, sheet):
    ws = load_workbook(path, data_only=True)[sheet]
    rows = list(ws.iter_rows(values_only=True))
    head = [str(h) for h in rows[0]]
    return [dict(zip(head, r)) for r in rows[1:] if any(v not in (None, "") for v in r)]

def fnum(v):
    try: return float(v)
    except (TypeError, ValueError): return None

def suggest(rec, bank, reg_rows):
    """Machine suggestion; a human always has the last word."""
    q = bank.get(rec["题号"])
    ans = rec.get("回答原文") or ""
    if not ans.strip(): return "无回答"
    if q is None: return "不适用"
    if PROMISE.search(ans): return "C4"
    if q["须转人工"] == "是":
        return "通过" if HANDOFF.search(ans) else "C5"
    key = (rec["机构代号"], rec["地区"], rec.get("产品") or "", q["事实键"])
    std = next((r for r in reg_rows if (r["机构代号"], r["地区"], r.get("产品") or "", r["事实键"]) == key), None)
    if std is None: return "无法判断"
    got = numbers(ans)
    if not got: return "无法判断"
    sv, ov = fnum(std["标准取值"]), fnum(std.get("旧版取值"))
    if sv is not None and sv in got: return "通过"
    if ov is not None and ov in got: return "C2"
    others = {fnum(r["标准取值"]) for r in reg_rows if r["事实键"] == q["事实键"] and r is not std}
    if any(g in others for g in got): return "C3"
    return "C1"

def kappa(pairs):
    if not pairs: return None
    labels = sorted({x for p in pairs for x in p}); n = len(pairs)
    po = sum(a == b for a, b in pairs) / n
    pe = sum((sum(a == l for a, _ in pairs) / n) * (sum(b == l for _, b in pairs) / n) for l in labels)
    return None if pe == 1 else (po - pe) / (1 - pe)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", required=True); ap.add_argument("--register", required=True); ap.add_argument("--bank", required=True)
    ap.add_argument("--out", required=True); ap.add_argument("--public", action="store_true")
    a = ap.parse_args()
    log = read(a.log, "记录"); reg = read(a.register, "标准答案")
    bank = {r["题号"]: r for r in read(a.bank, "题库")}
    for r in log:
        r["机器建议"] = suggest(r, bank, reg)
        r["最终"] = r.get("复核判定") or r.get("人工判定") or ""
        r["方法"] = bank.get(r["题号"], {}).get("方法", "?")
    scored = [r for r in log if r["最终"] in SCORED]
    L = ["# 测试结果摘要", "", f"- 记录总数：{len(log)}；已有最终判定：{sum(1 for r in log if r['最终'])}；计入分母：{len(scored)}",
         f"- 其中确认差异（C1–C4）：{sum(r['最终'] in ERR for r in scored)}；需合规复核（C5）：{sum(r['最终'] == 'C5' for r in log)}",
         f"- 不计入分母：不适用 {sum(r['最终']=='不适用' for r in log)}，无法判断 {sum(r['最终']=='无法判断' for r in log)}，无回答 {sum(r['最终']=='无回答' for r in log)}",
         "- 未填最终判定的记录不参与统计；机器建议不参与统计。", ""]
    n = len(scored); k = sum(r["最终"] in ERR for r in scored)
    lo, hi = wilson(k, n)
    L += ["## 总体", "", f"- 样本 {n}，确认差异 {k}，差异率 {k/n:.1%}（95% 置信区间 {lo:.1%}–{hi:.1%}）" if n else "- 暂无计入分母的记录"]
    if n and k == 0: L.append(f"- 零差异：在 95% 置信下，差异率上限约 {3/n:.1%}（三分法，3/n）。这不表示没有错误。")
    L += ["", "## 分组（不要把不同分组加总成一个数字）", ""]
    stats = [["维度", "组", "n", "差异数", "差异率", "区间下限", "区间上限"]]
    for dim in ("机构代号", "地区", "渠道", "语言", "方法"):
        g = defaultdict(list)
        for r in scored: g[r.get(dim) or "?"].append(r)
        for name, rs in sorted(g.items(), key=lambda x: str(x[0])):
            kk = sum(x["最终"] in ERR for x in rs); lo_, hi_ = wilson(kk, len(rs))
            stats.append([dim, name, len(rs), kk, f"{kk/len(rs):.1%}", f"{lo_:.1%}", f"{hi_:.1%}"])
    L += ["| " + " | ".join(stats[0]) + " |", "|" + "---|" * len(stats[0])] + ["| " + " | ".join(map(str, s)) + " |" for s in stats[1:]]
    # classes
    cls = defaultdict(int)
    for r in log:
        if r["最终"]: cls[r["最终"]] += 1
    L += ["", "## 判定分布", "", "| 判定 | 数量 |", "|---|---|"] + [f"| {c} | {cls[c]} |" for c in sorted(cls)]
    # repeat consistency
    rep = defaultdict(list)
    for r in log:
        if r.get("重测组号"): rep[r["重测组号"]].append(tuple(numbers(r.get("回答原文") or "")))
    bad = [g for g, v in rep.items() if len(v) > 1 and len(set(v)) > 1]
    L += ["", "## 重测一致性", "", f"- 重测组 {len(rep)} 个，其中答案中的数字不一致 {len(bad)} 个" + (f"（{', '.join(sorted(bad))}）" if bad else "")]
    # agreement
    h = [(r["机器建议"], r["最终"]) for r in log if r["最终"] and r["机器建议"] not in ("无法判断",)]
    ag = sum(a_ == b_ for a_, b_ in h) / len(h) if h else None
    two = [(r["人工判定"], r["复核判定"]) for r in log if r.get("人工判定") and r.get("复核判定")]
    kp = kappa(two)
    L += ["", "## 判定质量", "", f"- 机器建议与最终判定一致率：{ag:.0%}（{len(h)} 条）" if ag is not None else "- 机器建议：无可比较记录",
          f"- 双人判定一致率：{sum(a_==b_ for a_,b_ in two)/len(two):.0%}（{len(two)} 条）；Cohen kappa={kp:.2f}" if two and kp is not None else "- 双人判定：样本不足，无法计算 kappa"]
    L += ["", "## 解读限制", "", "- 样本由人工记录，规模小，不代表整体错误率；渠道版本、回答随机性、标准答案是否完整都会影响结果。",
          "- 确认差异必须经第二人复核并核对文件版本后才可对外说明；对外不得点名机构，除非机构书面同意。"]
    # evidence cards
    prev, cards = "0" * 64, ["# 证据卡（仅含确认差异）", ""]
    for r in log:
        if r["最终"] not in ERR: continue
        q = bank.get(r["题号"], {}); key = (r["机构代号"], r["地区"], r.get("产品") or "", q.get("事实键"))
        std = next((x for x in reg if (x["机构代号"], x["地区"], x.get("产品") or "", x["事实键"]) == key), {})
        body = "\n".join(f"{k}={r.get(k)}" for k in ("记录号", "日期时间", "机构代号", "地区", "渠道", "语言", "题号", "回答原文", "最终")) + f"\n标准={std.get('标准取值')}|{std.get('版本')}|{std.get('来源日期')}"
        h_ = hashlib.sha256((prev + body).encode()).hexdigest(); prev = h_
        cards += [f"## 证据卡 {r['记录号']}（{r['最终']}）", "",
                  f"- 机构：{r['机构代号']}　地区：{r['地区']}　渠道：{r['渠道']}　语言：{r['语言']}　时间：{r['日期时间']}",
                  f"- 问：{mask(r.get('提问原文') or '')}", f"- 答：{mask(r.get('回答原文') or '')}",
                  f"- 标准：{std.get('标准取值')}{std.get('单位') or ''}（版本 {std.get('版本')}，来源日期 {std.get('来源日期')}，抓取日期 {std.get('抓取日期')}）",
                  f"- 截图编号：{r.get('截图编号')}　记录人：{r.get('记录人')}　复核人：{r.get('复核人')}", f"- 校验值（链式）：`{h_}`", ""]
    texts = {"report.md": "\n".join(L) + "\n", "evidence_cards.md": "\n".join(cards) + "\n"}
    # anonymity guard
    if a.public:
        mp = Path(__file__).parent / "private" / "institution_map.csv"
        names = []
        if mp.exists():
            with open(mp, encoding="utf-8") as f: names = [row[1].strip() for row in csv.reader(f) if len(row) > 1 and row[1].strip() and row[0] != "code"]
        if not names: sys.exit("--public 需要 private/institution_map.csv（代号,名称），否则无法保证不含机构名称。")
        hits = [(fn, nm) for fn, t in texts.items() for nm in names if nm.lower() in t.lower()]
        if hits: sys.exit(f"拒绝输出：发现机构名称 {hits}。请在记录中改用代号后重试。")
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    for fn, t in texts.items(): (out / fn).write_text(t, encoding="utf-8")
    with open(out / "stats.csv", "w", encoding="utf-8", newline="") as f: csv.writer(f).writerows(stats)
    print(f"ok: {len(log)} 条记录，计入 {n}，确认差异 {k}；输出在 {out}")

if __name__ == "__main__":
    main()
