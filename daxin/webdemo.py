"""Export the simulated end-to-end run as a single offline HTML page with two views:

- external (what a customer of the fictional BANK-X sees): answers with verified citations, or a hand-off;
- internal (what consumer protection, compliance and audit see): verdicts, evidence, reviews, the release matrix through a
  policy change, the pre-effective regression, the routing policy and the evidence chain.

Every number on the page comes from this run; nothing is typed in by hand. Black-box only: the page never shows the system
under test's prompts, retrieval or model.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from importlib import resources
from pathlib import Path

from . import RULE_VERSION, __version__
from .cite import cite
from .demo import _clauses, run
from .grade import grade
from .release import NAME
from .routing import build as routing_build

TURN_PICK = [("Q001", "通过"), ("S0117", None), ("Q008", "通过"), ("S0193", None), ("Q015", "通过"), ("S0156", None), ("S0205", None)]


def _canon(card: dict) -> str:
    return json.dumps({k: v for k, v in card.items() if k != "hash"}, sort_keys=True, ensure_ascii=False)


def collect(workdir: Path) -> dict:
    import contextlib, io
    with contextlib.redirect_stdout(io.StringIO()):
        r = run(workdir, log=lambda *a, **k: None)
    policy, store, audit = r["policy"], r["store"], r["audit"]
    obs = store.observations()
    final, revs, judg = store.final_verdicts(), store.reviews(), store.judgments(RULE_VERSION)
    by_id = {o.obs_id: o for o in obs}
    level_of = {(x.topic, x.region): x.level for x in r["before"]}
    preview = {p["obs_id"]: p for pl in r["plans"] for p in pl["preview"]}
    cards = {c["id"]: c for c in r["cards"]}

    def turn(o):
        j = judg.get(o.obs_id)
        v = final.get(o.obs_id, j.verdict if j else "")
        clause = next((c for c in policy.clauses() if j and c.ref == j.clause_ref), None)
        ext = cite(o, policy, level_of.get((o.topic, o.region), ""))
        pv = preview.get(o.obs_id)
        return {"obs_id": o.obs_id, "ts": o.ts, "region": o.region, "channel": o.channel, "language": o.language, "topic": o.topic,
                "question_id": o.question_id, "question": o.question, "answer": o.answer, "verdict": v,
                "machine": j.verdict if j else "", "reason": j.reason if j else "", "clause": j.clause_ref if j else "",
                "clause_text": clause.text if clause else "", "source_ref": clause.source_ref if clause else "",
                "expected": j.expected if j else None, "claims": j.claims if j else [],
                "grade": grade(v, j.flags if j else [], o.fact_key) if v else None,
                "reviewers": [f"{who}：{vv}" for who, vv in revs.get(o.obs_id, [])], "sha": o.answer_sha256,
                "card": o.obs_id if o.obs_id in cards else "", "external": ext,
                "upcoming": ({"on": "2026-12-01", "verdict": pv["verdict"], "reason": pv["reason"]} if pv else None)}

    turns = []
    for key, want in TURN_PICK:
        if key in by_id:
            turns.append(turn(by_id[key]))
        else:
            o = next(o for o in obs if o.question_id == key and final.get(o.obs_id) == want and o.region == "R1")
            turns.append(turn(o))

    def rows(m):
        return [{**asdict(x), "label": NAME[x.level]} for x in m]

    frozen = [c.ref for c in policy.clauses(("frozen",))]
    later = {c.ref for c in _clauses("clause_annual_fee_v3.json")}
    frozen_before = [x for x in frozen if x not in later]
    stages = []
    for key, label, note, m, gen in (("before", "① 现状（2026-11-20）", "按现行标准测试并经双人复核后的放行等级。", r["before"], "2026-11-20T00:00:00Z"),
                                ("change", "② 发布新标准：年费 2026-12-01 起调为 220 元",
                                 "新版本一冻结，旧测试结果就不再覆盖它：相关主题封顶 L3，并触发生效前回归。", r["after_change"], "2026-11-20T00:00:00Z"),
                                ("retest", "③ 复测后（2026-12-08）", "按新标准复测并复核后，等级按新数据重新计算。", r["after_retest"], "2026-12-08T00:00:00Z")):
        stages.append({"key": key, "label": label, "note": note, "rows": rows(m),
                       "routing": routing_build(m, "BANK-X", frozen if key != "before" else frozen_before, audit.head(), generated_at="2026-12-08T00:00:00Z")})
    chain = [{**c, "canon": _canon(c)} for c in r["cards"]]
    ok, _ = audit.verify()
    return {
        "meta": {"inst": "BANK-X", "version": __version__, "rule_version": RULE_VERSION, "audit_ok": ok,
                 "audit_events": len(audit.events()), "audit_head": audit.head(), "frozen": frozen, "dist": r["dist"],
                 "observations": len(obs), "frozen_error": r["frozen_error"]},
        "clauses": [{"ref": c.ref, "topic": c.topic, "text": c.text, "effective_from": c.effective_from.isoformat(),
                     "source_ref": c.source_ref, "status": c.status,
                     "facts": [f"{f.value:g}{f.unit}" if isinstance(f.value, float) else f"{f.value}{f.unit}" for f in c.facts]}
                    for c in policy.clauses()],
        "turns": turns,
        "observations": [{"obs_id": o.obs_id, "ts": o.ts, "region": o.region, "channel": o.channel, "topic": o.topic,
                          "answer": o.answer, "machine": judg[o.obs_id].verdict if o.obs_id in judg else "",
                          "final": final.get(o.obs_id, "未复核"), "reviewers": len(revs.get(o.obs_id, []))} for o in obs],
        "stages": stages, "plans": r["plans"], "chain": chain,
    }


def export(workdir: Path, out: Path) -> Path:
    data = collect(Path(workdir))
    tpl = (Path(__file__).parent / "web" / "template.html").read_text(encoding="utf-8")
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    out = Path(out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(tpl.replace("/*__DAXIN_DATA__*/null", blob), encoding="utf-8")
    return out
