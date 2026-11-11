"""Measure draft extraction against the hand-made answer key. Replays recorded raw outputs by default (offline, no key).
Usage: python testkit/draft_eval/run_eval.py [--live]   (--live calls the model and records new raw outputs)"""
import json
import sys
from pathlib import Path

from daxin.draft import draft_facts, evaluate
from daxin.llm import LLMClient, ReplayClient

here = Path(__file__).parent
client = LLMClient(record_dir=here / "raw") if "--live" in sys.argv else ReplayClient(here / "raw")
res = draft_facts((here / "policy_doc_仿真.txt").read_text(encoding="utf-8"), client)
key = json.loads((here / "answer_key.json").read_text(encoding="utf-8"))["facts"]
ev = evaluate(res.accepted, key)
len_ = evaluate(res.accepted, key, lenient=True)
ev["strict"] = {k: ev[k] for k in ("true_positive", "precision", "recall")}
ev["lenient"] = {k: len_[k] for k in ("true_positive", "precision", "recall")}
ev["lenient_missed"] = len_["missed"]
ev["lenient_extra"] = len_["extra"]
ev.update(rejected=[{"reason": r.reason, "key": r.raw.get("key"), "value": r.raw.get("value")} for r in res.rejected], errors=res.errors)
print(json.dumps(ev, ensure_ascii=False, indent=1))
