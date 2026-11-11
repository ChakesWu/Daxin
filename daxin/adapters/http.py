"""HTTP adapter for an AUTHORISED test environment. Safety rules, none of which can be switched off:
  * disabled unless DAXIN_HTTP_ENABLED=1;
  * only hosts on the allow-list: localhost by default; any other host must be named with --authorized-host AND confirmed in the
    environment variable DAXIN_HTTP_AUTHORIZED (the person's own statement that they are authorised to test it);
  * a minimum interval between requests (MIN_INTERVAL_S) that a caller may raise but never lower;
  * a hard timeout; a timeout, an error or an empty reply is recorded as 'no answer', never retried in a loop, never as a pass.
It asks the questions it is given, one at a time. No jailbreaks, no prompt injection, no bulk crawling.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

MIN_INTERVAL_S = 0.5
MAX_TIMEOUT_S = 60.0
LOCAL = ("127.0.0.1", "localhost", "::1")


class AdapterRefused(RuntimeError):
    pass


class HttpAdapter:
    def __init__(self, url: str, interval_s: float = 1.0, timeout_s: float = 30.0, authorized_host: str = ""):
        if os.environ.get("DAXIN_HTTP_ENABLED") != "1":
            raise AdapterRefused("HTTP 适配器默认关闭：确认已获授权后设置环境变量 DAXIN_HTTP_ENABLED=1。")
        host = urllib.parse.urlparse(url).hostname or ""
        if host not in LOCAL:
            allowed = {h.strip() for h in os.environ.get("DAXIN_HTTP_AUTHORIZED", "").split(",") if h.strip()}
            if authorized_host != host or host not in allowed:
                raise AdapterRefused(f"主机 {host} 不在授权名单：需同时给出 --authorized-host {host} 并把它写入环境变量 DAXIN_HTTP_AUTHORIZED。")
        self.url = url
        self.interval_s = max(MIN_INTERVAL_S, float(interval_s))       # the floor cannot be lowered
        self.timeout_s = min(MAX_TIMEOUT_S, float(timeout_s))
        self._last = 0.0

    def ask(self, question: str, **context) -> tuple[str, dict]:
        """(answer, meta). answer is '' when there was none (timeout, error, empty): the caller records 'no answer'."""
        wait = self._last + self.interval_s - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        req = urllib.request.Request(self.url, json.dumps({"question": question, **context}, ensure_ascii=False).encode(),
                                     {"Content-Type": "application/json"}, method="POST")
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as r:
                data = json.loads(r.read())
            ans = str(data.get("answer") or "").strip()
            return ans, {"latency_s": round(time.monotonic() - t0, 2), "system": data.get("system", {})}
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
            return "", {"latency_s": round(time.monotonic() - t0, 2), "error": type(e).__name__}
