"""The bridge between the HTTP adapter and a self-hosted Dify app, tested against a local stand-in for the platform's API."""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy"))
import bridge  # noqa: E402

from daxin.adapters.http import HttpAdapter  # noqa: E402


class FakeDify(BaseHTTPRequestHandler):
    seen: list = []
    fail = False

    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        self._send(200, {"name": "客服", "mode": "chat"} if self.path.endswith("/info") else {"user_input_form": []})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeDify.seen.append((self.path, self.headers.get("Authorization"), body))
        if FakeDify.fail:
            return self._send(500, {"code": "internal_server_error"})
        self._send(200, {"answer": " 每年消费满 12 笔可免年费。 ", "conversation_id": "c1",
                         "metadata": {"retriever_resources": [{"document_name": "P01.txt", "score": 0.9, "position": 1, "content": "原文"}]}})


def start(server):
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.fixture
def stack(tmp_path, monkeypatch):
    FakeDify.seen, FakeDify.fail = [], False
    up = start(HTTPServer(("127.0.0.1", 0), FakeDify))
    kb = tmp_path / "kb"; kb.mkdir(); (kb / "a.txt").write_text("甲", encoding="utf-8")
    log = tmp_path / "log.jsonl"
    br = start(bridge.serve(0, base=f"http://127.0.0.1:{up.server_port}/v1", key="app-test", kb_dir=str(kb), label="v1", log=str(log)))
    monkeypatch.setenv("DAXIN_HTTP_ENABLED", "1")
    yield f"http://127.0.0.1:{br.server_port}/", kb, log, up
    br.shutdown(); up.shutdown()


def test_adapter_gets_the_answer_and_a_stable_fingerprint(stack):
    url, _, log, _ = stack
    ad = HttpAdapter(url, interval_s=0.5)
    a1, m1 = ad.ask("R1 年费怎么免？"); a2, m2 = ad.ask("再问一次")
    assert a1 == "每年消费满 12 笔可免年费。"
    assert m1["system"] == m2["system"] and m1["system"]["app"] == "客服" and m1["system"]["kb_files"] == 1
    path, auth, body = FakeDify.seen[0]
    assert path == "/v1/chat-messages" and auth == "Bearer app-test"
    assert body["query"] == "R1 年费怎么免？" and body["response_mode"] == "blocking" and "conversation_id" not in body
    assert FakeDify.seen[0][2]["user"] != FakeDify.seen[1][2]["user"]          # no memory carried between questions
    rec = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert rec["sources"][0]["document"] == "P01.txt" and "app-test" not in log.read_text(encoding="utf-8")


def test_upstream_failure_is_no_answer_never_a_pass(stack):
    url, *_ = stack
    FakeDify.fail = True
    ans, meta = HttpAdapter(url, interval_s=0.5).ask("问题")
    assert ans == ""


def test_a_changed_document_changes_the_fingerprint(stack, tmp_path):
    _, kb, _, up = stack
    d = bridge.Dify(f"http://127.0.0.1:{up.server_port}/v1", "k")
    before = bridge.fingerprint(d, str(kb), "v1")
    (kb / "a.txt").write_text("乙", encoding="utf-8")
    after = bridge.fingerprint(d, str(kb), "v1")
    assert before["kb_sha"] != after["kb_sha"] and bridge.fingerprint(d, str(kb), "v2") != after


def test_refuses_an_upstream_that_is_not_ours(monkeypatch):
    monkeypatch.delenv("DAXIN_BRIDGE_UPSTREAM_OK", raising=False)
    with pytest.raises(bridge.BridgeRefused):
        bridge.serve(0, base="https://api.example.com/v1", key="k")
    with pytest.raises(bridge.BridgeRefused):
        bridge.serve(0, base="http://127.0.0.1:1/v1", key="")
