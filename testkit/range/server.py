"""A SIMULATED customer-service RAG (the "range"): retrieval over a small simulated knowledge base + a GLM answer.
It listens on 127.0.0.1 only. It is not any institution's system. Faults can be injected to know the ground truth of each error.

  python server.py --preset default      natural setup: old versions stay in the index, no region filtering
  python server.py --preset scoped       region filter + current versions only (the healthy setup)
  python server.py --preset stale        the current fee-waiver passages were never re-indexed (only the old version remains)
Flags override presets: --top-k N  --include-old / --no-old  --region-filter / --no-region-filter  --drop-current KEY,KEY

Embeddings: GLM embedding-3 (256 dims); results cached in emb_cache.json. The key is injected by the network proxy or DAXIN_LLM_KEY.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HERE = Path(__file__).parent
BASE = os.environ.get("DAXIN_LLM_BASE", "https://open.bigmodel.cn/api/paas/v4")
GEN_MODEL = os.environ.get("DAXIN_LLM_MODEL", "glm-5.3-flashx")
PRESETS = {
    "default": dict(top_k=3, include_old=True, region_filter=False, drop_current=[]),
    "scoped": dict(top_k=3, include_old=False, region_filter=True, drop_current=[]),
    "stale": dict(top_k=3, include_old=True, region_filter=False, drop_current=["fee_waiver.min_purchases"]),
}
CACHE_F = HERE / "emb_cache.json"
CACHE: dict = json.loads(CACHE_F.read_text()) if CACHE_F.exists() else {}


def _post(path: str, body: dict, timeout: float = 120) -> dict:
    h = {"Content-Type": "application/json"}
    if os.environ.get("DAXIN_LLM_KEY"):
        h["Authorization"] = "Bearer " + os.environ["DAXIN_LLM_KEY"]
    req = urllib.request.Request(BASE + path, json.dumps(body, ensure_ascii=False).encode(), h, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def embed(text: str) -> list[float]:
    k = hashlib.sha256(text.encode()).hexdigest()[:24]
    if k not in CACHE:
        CACHE[k] = _post("/embeddings", {"model": "embedding-3", "input": [text], "dimensions": 256})["data"][0]["embedding"]
        CACHE_F.write_text(json.dumps(CACHE))
    return CACHE[k]


def cos(a, b) -> float:
    return sum(x * y for x, y in zip(a, b)) / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)) or 1)


class Rag:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        kb = json.loads((HERE / "kb.json").read_text(encoding="utf-8"))
        if not cfg["include_old"]:
            kb = [p for p in kb if p["current"]]
        kb = [p for p in kb if not (p["current"] and p["key"] in cfg["drop_current"])]
        self.kb = kb
        for p in kb:
            p["vec"] = embed(p["text"])
        self.fingerprint = {"gen_model": GEN_MODEL, "embed_model": "embedding-3", "config": cfg,
                            "kb_sha": hashlib.sha256(json.dumps([p["id"] for p in kb]).encode()).hexdigest()[:12]}

    def retrieve(self, q: str) -> list[dict]:
        pool = self.kb
        if self.cfg["region_filter"]:
            m = re.search(r"R\d", q)
            if m:
                pool = [p for p in pool if p["region"] in ("", m.group(0))]
        qv = embed(q)
        return sorted(pool, key=lambda p: -cos(qv, p["vec"]))[: self.cfg["top_k"]]

    def answer(self, q: str) -> tuple[str, list[str]]:
        ctx = self.retrieve(q)
        prompt = ("你是 BANK-X 的在线客服。只根据下面的资料用一两句话回答客户的问题；资料里没有的内容，请回答“请转人工客服”。\n\n资料：\n"
                  + "\n".join(f"- {p['text']}" for p in ctx) + f"\n\n客户问题：{q}")
        r = _post("/chat/completions", {"model": GEN_MODEL, "messages": [{"role": "user", "content": prompt}], "max_tokens": 1500,
                                        "reasoning_effort": "low", "temperature": 0})
        return (r["choices"][0]["message"]["content"] or "").strip(), [p["id"] for p in ctx]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", default="default", choices=PRESETS)
    ap.add_argument("--port", type=int, default=8801)
    ap.add_argument("--top-k", type=int)
    ap.add_argument("--include-old", dest="include_old", action="store_true", default=None)
    ap.add_argument("--no-old", dest="include_old", action="store_false")
    ap.add_argument("--region-filter", dest="region_filter", action="store_true", default=None)
    ap.add_argument("--no-region-filter", dest="region_filter", action="store_false")
    ap.add_argument("--drop-current", default=None)
    a = ap.parse_args()
    cfg = dict(PRESETS[a.preset])
    for k in ("top_k", "include_old", "region_filter"):
        if getattr(a, k) is not None:
            cfg[k] = getattr(a, k)
    if a.drop_current is not None:
        cfg["drop_current"] = [x for x in a.drop_current.split(",") if x]
    rag = Rag(cfg)

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            try:
                ans, used = rag.answer(str(body.get("question", "")))
                out = {"answer": ans, "system": rag.fingerprint, "retrieved": used}
            except Exception as e:     # a failing system returns no answer; the adapter records that as 无回答
                out = {"answer": "", "error": type(e).__name__}
            data = json.dumps(out, ensure_ascii=False).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(data))); self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    print(f"range up on 127.0.0.1:{a.port} cfg={cfg}", flush=True)
    HTTPServer(("127.0.0.1", a.port), H).serve_forever()


if __name__ == "__main__":
    sys.exit(main())
