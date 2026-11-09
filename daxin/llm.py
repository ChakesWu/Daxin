"""Thin LLM client (OpenAI-compatible chat completions) used only to DRAFT facts; it never judges (I5).

Every raw response is saved to `record_dir` keyed by a hash of the request, so a run can be replayed offline (ReplayClient).
The key is never written anywhere: it comes from the environment (DAXIN_LLM_KEY) or from a network proxy that injects it.
Default is the BigModel GLM endpoint; override with DAXIN_LLM_URL / DAXIN_LLM_MODEL.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
DEFAULT_MODEL = "glm-5.3-flashx"


class LLMError(RuntimeError):
    pass


def request_key(model: str, messages: list[dict], params: dict) -> str:
    blob = json.dumps({"model": model, "messages": messages, "params": params}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:24]


class LLMClient:
    def __init__(self, model: str | None = None, url: str | None = None, record_dir: Path | str | None = None,
                 effort: str = "high", max_tokens: int = 8000, timeout: float = 180, retries: int = 2):
        self.model = model or os.environ.get("DAXIN_LLM_MODEL") or DEFAULT_MODEL
        self.url = url or os.environ.get("DAXIN_LLM_URL") or DEFAULT_URL
        self.record_dir = Path(record_dir) if record_dir else None
        self.effort, self.max_tokens, self.timeout, self.retries = effort, max_tokens, timeout, retries

    def _params(self, json_mode: bool) -> dict:
        p = {"max_tokens": self.max_tokens, "reasoning_effort": self.effort, "temperature": 0}
        if json_mode:
            p["response_format"] = {"type": "json_object"}
        return p

    def _post(self, body: dict) -> dict:
        headers = {"Content-Type": "application/json"}
        if os.environ.get("DAXIN_LLM_KEY"):
            headers["Authorization"] = "Bearer " + os.environ["DAXIN_LLM_KEY"]
        req = urllib.request.Request(self.url, json.dumps(body).encode(), headers, method="POST")
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return json.loads(r.read())
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
                last = e
                time.sleep(2 ** attempt)
        raise LLMError(f"LLM request failed: {type(last).__name__}")

    def chat(self, messages: list[dict], json_mode: bool = True) -> str:
        params = self._params(json_mode)
        key = request_key(self.model, messages, params)
        t0 = time.time()
        raw = self._post({"model": self.model, "messages": messages, **params})
        raw["_daxin"] = {"key": key, "model": self.model, "params": params, "messages": messages,
                         "latency_s": round(time.time() - t0, 2)}
        if self.record_dir:
            self.record_dir.mkdir(parents=True, exist_ok=True)
            (self.record_dir / f"{key}.json").write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
        try:
            return raw["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            raise LLMError("unexpected response shape")


class ReplayClient(LLMClient):
    """Offline: answers only from previously recorded raw outputs; a request never seen before is an error."""

    def __init__(self, record_dir: Path | str, model: str = DEFAULT_MODEL, effort: str = "high", max_tokens: int = 8000):
        super().__init__(model=model, record_dir=record_dir, effort=effort, max_tokens=max_tokens)

    def chat(self, messages: list[dict], json_mode: bool = True) -> str:
        key = request_key(self.model, messages, self._params(json_mode))
        f = self.record_dir / f"{key}.json"
        if not f.exists():
            raise LLMError(f"no recorded output for request {key}")
        return json.loads(f.read_text(encoding="utf-8"))["choices"][0]["message"]["content"] or ""
