"""Presentation layer: one offline, read-only HTML page that shows each answer with its numbers marked against the frozen standard.

Nothing here changes any state. It reads the store and renders: the answer with each stated number coloured, an evidence panel
(frozen clause, version, effective date, expected vs stated, rule version, reviewers, hash), the machine suggestion beside the
human verdict, the release lights, and the audit-chain check. `blind=True` hides every machine verdict and human verdict (for reviewers).
"""
from __future__ import annotations

import hashlib
import json
from datetime import date

from . import RULE_VERSION
from .anonymity import mask_text
from .extract import claim_spans
from .models import ERRORS
from .release import NAME, matrix


def _spans(answer: str, unit: str, expected) -> list[dict]:
    out = []
    for v, st, en in claim_spans(answer, unit):
        same = isinstance(expected, (int, float)) and abs(v - float(expected)) < 1e-9
        out.append({"s": st, "e": en, "v": v, "same": bool(same)})
    return out


def build(policy, store, audit, today: date | None = None, blind: bool = False, rule_version: str | None = None, limit: int = 300) -> dict:
    today = today or date.today()
    rule_version = rule_version or RULE_VERSION
    final, judg, revs = store.final_verdicts(), store.judgments(rule_version), store.reviews()
    clauses = {c.ref: c for c in policy.clauses(("frozen",))}
    items = []
    for o in store.observations()[:limit]:
        j = judg.get(o.obs_id)
        c = clauses.get(j.clause_ref) if j else None
        fact = next((f for f in c.facts if f.key == o.fact_key), None) if c else None
        ans = mask_text(o.answer)
        spans = _spans(o.answer, fact.unit, j.expected) if (fact and j and len(ans) == len(o.answer)) else []
        item = {"id": o.obs_id, "ts": o.ts, "region": o.region, "product": o.product, "channel": o.channel, "topic": o.topic,
                "question": mask_text(o.question), "answer": ans, "answer_sha256": o.answer_sha256, "fact_key": o.fact_key,
                "spans": spans, "reviewers": [r for r, _ in revs.get(o.obs_id, [])]}
        if not blind:
            item |= {"machine": j.verdict if j else "未判定", "flags": j.flags if j else [], "reason": j.reason if j else "",
                     "expected": j.expected if j else None, "unit": fact.unit if fact else "", "rule_version": j.rule_version if j else "",
                     "human": final.get(o.obs_id, ""), "clause": {"ref": c.ref, "topic": c.topic, "text": c.text, "scope": c.scope.model_dump(exclude_none=True),
                                                                   "effective_from": str(c.effective_from), "source": c.source_ref} if c else None}
        items.append(item)
    ok, bad = audit.verify()
    n = sum(1 for _ in audit.events())
    lights = [] if blind else [{"topic": r.topic, "region": r.region, "channel": r.channel, "language": r.language, "level": r.level, "name": NAME[r.level],
                                "n": r.n, "k": r.k, "lb": round(r.lower_bound, 3), "reasons": r.reasons}
                               for r in matrix(policy, store, today=today, rule_version=rule_version if rule_version != RULE_VERSION else None)]
    return {"generated": str(today), "rule_version": rule_version, "blind": blind, "audit_ok": ok, "audit_bad": bad, "audit_events": n,
            "min_reviewers": 2, "items": items, "lights": lights}


def render(data: dict) -> str:
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return TEMPLATE.replace("/*DATA*/null", blob).replace("{{FP}}", hashlib.sha256(blob.encode()).hexdigest()[:12])


TEMPLATE = r"""<!doctype html>
<html lang="zh-Hans"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>答信 · 证据台（仿真）</title>
<style>
:root{--bg:#f6f5f1;--pane:#fff;--ink:#1d2433;--mute:#6b7385;--line:#e2dfd6;--ok:#1b7f4b;--okbg:#dff3e7;--bad:#b3261e;--badbg:#fbe1de;--warn:#9a6200;--warnbg:#fdf0d2;--acc:#2a4d9b}
@media(prefers-color-scheme:dark){:root{--bg:#14171d;--pane:#1c2029;--ink:#e6e8ee;--mute:#98a0b2;--line:#2c3240;--ok:#5fd394;--okbg:#17352a;--bad:#ff8f86;--badbg:#42201d;--warn:#f0b954;--warnbg:#3a2d12;--acc:#8fb0ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.65 -apple-system,"PingFang SC","Noto Sans CJK SC","Microsoft YaHei",sans-serif}
header{display:flex;flex-wrap:wrap;gap:8px 20px;align-items:center;padding:14px 24px;background:var(--pane);border-bottom:1px solid var(--line)}
header h1{font-size:18px;margin:0;letter-spacing:.08em}.tag{font-size:12px;padding:2px 8px;border:1px solid var(--line);border-radius:99px;color:var(--mute)}
.tag.sim{color:var(--warn);border-color:var(--warn)}.tag.ok{color:var(--ok);border-color:var(--ok)}.tag.bad{color:var(--bad);border-color:var(--bad)}
main{display:grid;grid-template-columns:320px 1fr;min-height:calc(100vh - 62px)}
aside{border-right:1px solid var(--line);background:var(--pane);overflow:auto;max-height:calc(100vh - 62px)}
.filters{padding:12px 16px;display:flex;flex-wrap:wrap;gap:6px;border-bottom:1px solid var(--line);position:sticky;top:0;background:var(--pane)}
.filters button{border:1px solid var(--line);background:none;color:var(--ink);border-radius:99px;padding:2px 10px;font-size:12px;cursor:pointer}.filters button.on{background:var(--acc);color:#fff;border-color:var(--acc)}
.row{padding:12px 16px;border-bottom:1px solid var(--line);cursor:pointer}.row:hover,.row.on{background:var(--bg)}
.row .q{font-size:13px;color:var(--ink);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.row .m{font-size:12px;color:var(--mute);margin-top:4px;display:flex;gap:8px;flex-wrap:wrap}
.pill{font-size:12px;padding:1px 8px;border-radius:99px;background:var(--warnbg);color:var(--warn)}.pill.通过{background:var(--okbg);color:var(--ok)}.pill.err{background:var(--badbg);color:var(--bad)}
section{padding:24px 32px;max-width:980px}h2{font-size:13px;color:var(--mute);letter-spacing:.12em;margin:0 0 8px;font-weight:600}
.note{background:var(--warnbg);color:var(--warn);padding:8px 12px;border-radius:6px;font-size:13px;margin:0 0 20px}
.card{background:var(--pane);border:1px solid var(--line);border-radius:10px;padding:16px 20px;margin-bottom:20px;white-space:pre-wrap}
mark{padding:1px 3px;border-radius:4px;cursor:pointer;border-bottom:2px solid;background:var(--warnbg);color:var(--ink);border-color:var(--warn)}
mark.same{background:var(--okbg);border-color:var(--ok)}mark.diff{background:var(--badbg);border-color:var(--bad)}mark.sel{outline:2px solid var(--acc)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px}.box{background:var(--pane);border:1px solid var(--line);border-radius:10px;padding:12px 16px}
.box b{display:block;font-size:12px;color:var(--mute);letter-spacing:.1em;margin-bottom:4px}.box .v{font-size:16px}.box small{color:var(--mute);display:block;margin-top:4px;word-break:break-all}
table{width:100%;border-collapse:collapse;background:var(--pane);border:1px solid var(--line);border-radius:10px;overflow:hidden;font-size:13px}th,td{padding:8px 12px;border-bottom:1px solid var(--line);text-align:left}th{color:var(--mute);font-weight:600}
.lv{display:inline-block;min-width:32px;text-align:center;border-radius:6px;padding:1px 6px;font-weight:700;color:#fff}.L1{background:#1b7f4b}.L2{background:#4f8f2f}.L3{background:#c28a00}.L4{background:#b3261e}
@media(max-width:760px){main{grid-template-columns:1fr}aside{max-height:260px;border-right:0;border-bottom:1px solid var(--line)}section{padding:16px}}
</style></head><body>
<header><h1>答信 · 证据台</h1><span class="tag sim">仿真数据</span><span class="tag" id="rv"></span><span class="tag" id="audit"></span><span class="tag" id="blind"></span><span class="tag">页面指纹 {{FP}}</span></header>
<main><aside><div class="filters" id="filters"></div><div id="list"></div></aside>
<section><div class="note">机器判定只是建议；只有至少两名复核人一致的人工判定才参与统计。抽不到主张的回答显示“待人工”，不会判通过。本页只读，不能修改任何条款或判定。</div>
<h2>被测系统的回答（点数字看依据）</h2><div class="card" id="ans"></div>
<h2>证据</h2><div class="grid" id="ev"></div>
<h2 style="margin-top:28px" id="lh">主题放行灯</h2><div style="overflow:auto"><table id="lights"></table></div></section></main>
<script>
const D=/*DATA*/null;const $=id=>document.getElementById(id);const esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const ERR=["C1","C2","C3","C4"];const cls=v=>v==="通过"?"通过":(ERR.includes(v)?"err":"");
$("rv").textContent="规则版本 "+D.rule_version;$("audit").textContent=D.audit_ok?("审计链校验通过 · "+D.audit_events+" 条"):("审计链第 "+D.audit_bad+" 条异常");$("audit").className="tag "+(D.audit_ok?"ok":"bad");
$("blind").textContent=D.blind?"盲测视图：已隐藏机器与人工判定":"完整视图";
let cur=null,flt="全部";const FS=D.blind?["全部"]:["全部","通过","错误","待人工"];
function pass(it){if(flt==="全部")return true;const v=it.human||it.machine;return flt==="错误"?ERR.includes(v):flt==="通过"?v==="通过":!["通过",...ERR].includes(v)}
function renderList(){$("filters").innerHTML=FS.map(f=>`<button class="${f===flt?"on":""}" data-f="${f}">${f}</button>`).join("");
 $("filters").querySelectorAll("button").forEach(b=>b.onclick=()=>{flt=b.dataset.f;renderList()});
 $("list").innerHTML=D.items.filter(pass).map(it=>`<div class="row ${cur&&cur.id===it.id?"on":""}" data-id="${esc(it.id)}"><div class="q">${esc(it.question)}</div><div class="m"><span>${esc(it.region||"—")}</span>${D.blind?"":`<span class="pill ${cls(it.machine)}">机器 ${esc(it.machine)}</span>`+(it.human?`<span class="pill ${cls(it.human)}">人工 ${esc(it.human)}</span>`:"")}</div></div>`).join("")||'<div class="row">没有符合的回答</div>';
 $("list").querySelectorAll(".row[data-id]").forEach(r=>r.onclick=()=>show(D.items.find(i=>i.id===r.dataset.id)))}
function show(it,span){cur=it;renderList();let h="",p=0;const a=it.answer;
 it.spans.forEach((s,i)=>{h+=esc(a.slice(p,s.s));const k=s.same?"same":(it.machine&&ERR.includes(it.machine)?"diff":"");h+=`<mark class="${k} ${span===i?"sel":""}" data-i="${i}">${esc(a.slice(s.s,s.e))}</mark>`;p=s.e});h+=esc(a.slice(p));
 $("ans").innerHTML=h||"（无回答）";$("ans").querySelectorAll("mark").forEach(m=>m.onclick=()=>show(it,+m.dataset.i));
 const b=(t,v,s)=>`<div class="box"><b>${t}</b><div class="v">${v}</div>${s?`<small>${s}</small>`:""}</div>`;let e="";
 e+=b("问题",esc(it.question),esc([it.region,it.product,it.channel].filter(Boolean).join(" · ")+" · "+it.ts));
 if(span!==undefined){const s=it.spans[span];e+=b("你点的数字",esc(s.v)+esc(it.unit||""),s.same?"与标准值相同":"与标准值不同（标准值 "+esc(it.expected)+esc(it.unit||"")+"）")}
 if(!D.blind){const c=it.clause;
  e+=b("机器建议",`<span class="pill ${cls(it.machine)}">${esc(it.machine)}</span> ${it.flags.map(f=>`<span class="pill err">${esc(f)}</span>`).join(" ")}`,esc(it.reason)+(it.rule_version?"（"+esc(it.rule_version)+"）":""));
  e+=b("人工复核",it.human?`<span class="pill ${cls(it.human)}">${esc(it.human)}</span>`:"尚无一致的人工判定",`复核人 ${it.reviewers.length} 人（至少 ${D.min_reviewers} 人一致才计入）`);
  e+=b("依据：冻结条款",c?esc(c.ref):"未匹配到条款",c?esc(c.topic)+"｜生效 "+esc(c.effective_from)+"｜范围 "+esc(JSON.stringify(c.scope))+"<br>"+esc(c.text):"");
  e+=b("标准值",it.expected==null?"—":esc(it.expected)+esc(it.unit||""),"")}
 e+=b("回答原文指纹（SHA-256）","",esc(it.answer_sha256));$("ev").innerHTML=e}
if(D.blind){$("lights").style.display="none";$("lh").style.display="none"}else{
 $("lights").innerHTML="<tr><th>主题</th><th>地区</th><th>渠道</th><th>放行</th><th>样本 n</th><th>错误数 k</th><th>Wilson 下界</th><th>说明</th></tr>"+D.lights.map(r=>`<tr><td>${esc(r.topic)}</td><td>${esc(r.region)}</td><td>${esc(r.channel)}</td><td><span class="lv ${r.level}">${r.level}</span> ${esc(r.name)}</td><td>${r.n}</td><td>${r.k}</td><td>${r.lb}</td><td>${esc(r.reasons.join("；"))}</td></tr>`).join("")}
renderList();if(D.items.length)show(D.items.find(i=>!D.blind&&ERR.includes(i.human||i.machine))||D.items[0]);
</script></body></html>
"""
