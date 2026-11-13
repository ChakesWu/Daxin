"""Bridge between the 答信 HTTP adapter and a SELF-HOSTED Dify chat app. Standard library only.

  adapter  --POST {"question": ...}-->  bridge (127.0.0.1)  --POST /v1/chat-messages-->  your own Dify
  adapter  <--{"answer": ..., "system": {...}}--

Why a bridge: the adapter speaks one small protocol and only talks to localhost; the platform's API (bearer key, its own
payload) stays out of the core. The bridge refuses to forward anywhere but a local Dify unless the host is named in
DAXIN_BRIDGE_UPSTREAM_OK (your own statement that the upstream is yours). It is not a client for anyone else's system.

Reasoning text a model returns inline (<think>...</think>) is removed from the answer before it is recorded; the raw reply is kept
in the log. Every question is a new conversation (no memory carried between questions). The retrieved passages Dify reports are written
to a JSONL log, so a wrong answer can later be traced to retrieval or to generation. The log stays on this machine.

Environment:
  DIFY_APP_KEY               the chat app's API key (app-...). Required. Never written to disk by this program.
  DIFY_BASE                  default http://127.0.0.1:8080/v1
  DAXIN_KB_DIR               folder holding the documents you uploaded to the knowledge base; their hashes go into the fingerprint
  DAXIN_SYSTEM_LABEL         free text describing the build (e.g. "kb-2026-11-11 默认配置"); part of the fingerprint
  DAXIN_BRIDGE_LOG           JSONL log path (default: deploy/data/bridge_log.jsonl)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

LOCAL = ("127.0.0.1", "localhost", "::1")
HERE = Path(__file__).parent


class BridgeRefused(RuntimeError):
    pass


def check_upstream(base: str) -> str:
    host = urllib.parse.urlparse(base).hostname or ""
    ok = {h.strip() for h in os.environ.get("DAXIN_BRIDGE_UPSTREAM_OK", "").split(",") if h.strip()}
    if host not in LOCAL and host not in ok:
        raise BridgeRefused(f"上游 {host} 不是本机：只有你自己架设的平台才可以接入，确认后把主机名写入 DAXIN_BRIDGE_UPSTREAM_OK。")
    return base.rstrip("/")


_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)


def split_reasoning(raw: str) -> tuple[str, bool, str]:
    """(answer, had_reasoning, problem). Some models return their chain of thought inline in <think>...</think>. That is not
    what a customer is meant to read: judged as part of the answer it adds every number the model considered, and a
    reviewer would be shown the knowledge base contents. The answer is the text outside the tags; the raw text stays in the log.
    A <think> that never closes means the reply was cut off before any answer: recorded as 'no answer', never as a pass."""
    had = bool(re.search(r"<think>", raw, re.I))
    text = _THINK.sub("", raw)
    if re.search(r"<think>", text, re.I):
        return "", True, "unclosed_think"
    return text.replace("</think>", "").strip(), had, ""


def kb_manifest(folder: str) -> dict:
    """sha256 of every file under the knowledge-base folder: a changed, added or removed document changes the fingerprint."""
    p = Path(folder) if folder else None
    if not p or not p.is_dir():
        return {}
    return {str(f.relative_to(p)).replace("\\", "/"): hashlib.sha256(f.read_bytes()).hexdigest()[:16]
            for f in sorted(p.rglob("*")) if f.is_file() and not f.name.startswith(".")}


class Dify:
    def __init__(self, base: str, key: str, timeout: float = 55.0):
        self.base, self.key, self.timeout = check_upstream(base), key, timeout

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        req = urllib.request.Request(self.base + path, json.dumps(body, ensure_ascii=False).encode() if body is not None else None,
                                     {"Authorization": "Bearer " + self.key, "Content-Type": "application/json"}, method=method)
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read())

    def describe(self) -> dict:
        """What the platform will say about the app without admin rights: name, mode, and its public parameters."""
        out = {}
        for name, path in (("info", "/info"), ("parameters", "/parameters")):
            try:
                out[name] = self._call("GET", path)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
                out[name] = {"error": type(e).__name__}
        return out

    def chat(self, question: str) -> dict:
        return self._call("POST", "/chat-messages", {"inputs": {}, "query": question, "response_mode": "blocking",
                                                     "user": "daxin-" + uuid.uuid4().hex[:8], "auto_generate_name": False})


def fingerprint(dify: Dify, kb_dir: str, label: str) -> dict:
    """Stable description of the system under test. It must not contain anything that changes between two questions.
    Limit: the app's prompt and model are not readable with an app key, so a change made in the Dify console is only
    caught if you also change DAXIN_SYSTEM_LABEL. The README says so."""
    d = dify.describe()
    info = d.get("info", {})
    return {"platform": "dify(self-hosted)", "app": info.get("name", ""), "mode": info.get("mode", ""),
            "parameters_sha": hashlib.sha256(json.dumps(d.get("parameters", {}), sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16],
            "kb_files": len(kb_manifest(kb_dir)),
            "kb_sha": hashlib.sha256(json.dumps(kb_manifest(kb_dir), sort_keys=True).encode()).hexdigest()[:16],
            "label": label}


def make_handler(dify: Dify, system: dict, log_path: Path | None):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):          # keep the console quiet; questions and answers go to the JSONL log only
            pass

        def _send(self, code: int, obj: dict):
            b = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code); self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

        def do_GET(self):
            self._send(200, {"ok": True, "system": system})

        def do_POST(self):
            try:
                q = str(json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0))).get("question") or "").strip()
            except (json.JSONDecodeError, ValueError):
                return self._send(400, {"answer": "", "error": "bad_request"})
            if not q:
                return self._send(400, {"answer": "", "error": "empty_question"})
            t0, ans, err, sources, raw, had = time.monotonic(), "", "", [], "", False
            try:
                r = dify.chat(q)
                raw = str(r.get("answer") or "").strip()
                ans, had, problem = split_reasoning(raw)
                err = problem
                for s in ((r.get("metadata") or {}).get("retriever_resources") or []):
                    sources.append({"document": s.get("document_name", ""), "score": s.get("score"), "position": s.get("position"),
                                    "content_sha": hashlib.sha256(str(s.get("content", "")).encode()).hexdigest()[:16]})
            except urllib.error.HTTPError as e:
                err = f"http_{e.code}"
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
                err = type(e).__name__
            if log_path:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "question": q, "answer": ans, "error": err,
                                        **({"raw_answer": raw} if had else {}), "latency_s": round(time.monotonic() - t0, 2), "sources": sources}, ensure_ascii=False) + "\n")
            # an upstream failure is an empty answer: the adapter records 'no answer', never a pass
            self._send(200, {"answer": ans, "system": system, **({"error": err} if err else {})})
    return H


def serve(port: int = 8810, base: str | None = None, key: str | None = None, kb_dir: str | None = None,
          label: str | None = None, log: str | None = None) -> HTTPServer:
    key = key or os.environ.get("DIFY_APP_KEY", "")
    if not key:
        raise BridgeRefused("缺少 DIFY_APP_KEY：在 Dify 的应用「访问 API」页生成密钥，写入 deploy/.env（不要提交）。")
    dify = Dify(base or os.environ.get("DIFY_BASE", "http://127.0.0.1:8080/v1"), key)
    system = fingerprint(dify, kb_dir if kb_dir is not None else os.environ.get("DAXIN_KB_DIR", ""),
                         label if label is not None else os.environ.get("DAXIN_SYSTEM_LABEL", ""))
    log_path = Path(log or os.environ.get("DAXIN_BRIDGE_LOG") or HERE / "data" / "bridge_log.jsonl")
    return HTTPServer(("127.0.0.1", port), make_handler(dify, system, log_path))     # loopback only, by construction


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=8810)
    a = ap.parse_args()
    try:
        srv = serve(a.port)
    except BridgeRefused as e:
        raise SystemExit(str(e))
    print(f"bridge up on http://127.0.0.1:{a.port}/", flush=True)
    srv.serve_forever()
