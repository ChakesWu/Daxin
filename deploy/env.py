"""One command for the self-hosted test environment (自建实测环境). Works on macOS, Linux and Windows; needs git, Docker
(Compose v2.35+) and this repository installed (`pip install -e .`).

  python deploy/env.py up            fetch the pinned Dify release, write its .env, start it on 127.0.0.1 only
  python deploy/env.py status        what is running, what is still missing
  python deploy/env.py smoke-kb DIR  write the SIMULATED range knowledge base as text files you can upload for a first run
  python deploy/env.py exam          bridge -> ask every generated question -> judge -> blind review sheet -> audit anchor
  python deploy/env.py backup        consistent copy of the workspace + audit-chain check
  python deploy/env.py down          stop Dify (data volumes are kept)

Settings come from deploy/.env (see deploy/.env.example). Nothing here talks to any system but the Dify you run yourself.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = HERE / "data"                    # gitignored: Dify checkout, workspace, logs, backups
DIFY_TAG = "1.19.0"                     # pinned; change deliberately, and expect the fingerprint label to change with it
DIFY_REPO = "https://github.com/langgenius/dify.git"


def load_env() -> dict:
    f = HERE / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return os.environ


def sh(*cmd: str, cwd: Path | None = None, check: bool = True, env: dict | None = None) -> int:
    print("$", " ".join(cmd), flush=True)
    r = subprocess.run(cmd, cwd=cwd, env=env)
    if check and r.returncode:
        raise SystemExit(r.returncode)
    return r.returncode


def daxin(*args: str, check: bool = True) -> int:
    return sh(sys.executable, "-c", "from daxin.cli import app; app()", *args, check=check, env={**os.environ, "PYTHONUTF8": "1"})


def port() -> str:
    return os.environ.get("DIFY_PORT", "8080")


def ws() -> Path:
    return Path(os.environ.get("DAXIN_WS") or DATA / "ws")


def set_env_line(path: Path, key: str, value: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    out, done = [], False
    for ln in lines:
        if ln.startswith(key + "="):
            out.append(f"{key}={value}"); done = True
        else:
            out.append(ln)
    if not done:
        out.append(f"{key}={value}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def get_env_line(path: Path, key: str) -> str:
    for ln in path.read_text(encoding="utf-8").splitlines() if path.exists() else []:
        if ln.startswith(key + "="):
            return ln.split("=", 1)[1].strip()
    return ""


def cmd_up(_):
    DATA.mkdir(exist_ok=True)
    src = DATA / "dify"
    if not src.exists():
        sh("git", "clone", "--depth", "1", "--branch", DIFY_TAG, DIFY_REPO, str(src))
    dk = src / "docker"
    env = dk / ".env"
    if not env.exists():
        env.write_text((dk / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")
    if not get_env_line(env, "DIFY_AGENT_LOCAL_SANDBOX_AUTH_TOKEN"):        # the one value the platform requires
        set_env_line(env, "DIFY_AGENT_LOCAL_SANDBOX_AUTH_TOKEN", secrets.token_hex(32))
    # publish on loopback only: nobody else on the network can reach the platform
    set_env_line(env, "EXPOSE_NGINX_PORT", f"127.0.0.1:{port()}")
    set_env_line(env, "EXPOSE_NGINX_SSL_PORT", f"127.0.0.1:{int(port()) + 363}")
    sh("docker", "compose", "up", "-d", cwd=dk)
    print(f"\n平台启动中（首次需下载镜像，可能要十几分钟）。就绪后打开 http://127.0.0.1:{port()}/install 完成初始设置，"
          f"然后按 deploy/README.md 第 2 步操作。")


def cmd_down(_):
    sh("docker", "compose", "down", cwd=DATA / "dify" / "docker")


def _get(url: str, timeout: float = 5) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read(300).decode("utf-8", "replace")
    except Exception as e:                                  # noqa: BLE001 - status report only
        return 0, type(e).__name__


def cmd_status(_):
    code, _b = _get(f"http://127.0.0.1:{port()}/")
    print(f"平台 http://127.0.0.1:{port()}/ ：{'可访问' if code else '未启动或仍在启动'}")
    print(f"应用密钥 DIFY_APP_KEY：{'已设置' if os.environ.get('DIFY_APP_KEY') else '未设置（deploy/.env）'}")
    kb = os.environ.get("DAXIN_KB_DIR", "")
    print(f"知识库目录 DAXIN_KB_DIR：{kb or '未设置'}{'' if not kb or Path(kb).is_dir() else '（目录不存在）'}")
    db = ws() / "daxin.db"
    print(f"工作区 {ws()} ：{'已建立' if db.exists() else '尚未建立（先冻结标准，见 README 第 3 步）'}")


def cmd_smoke_kb(a):
    """The simulated range passages as plain text files, one per passage, for a first end-to-end run before real documents exist."""
    out = Path(a.dir); out.mkdir(parents=True, exist_ok=True)
    kb = json.loads((ROOT / "testkit" / "range" / "kb.json").read_text(encoding="utf-8"))
    for p in kb:
        (out / f"{p['id']}.txt").write_text(p["text"] + "\n", encoding="utf-8")
    print(f"已写出 {len(kb)} 段仿真知识库到 {out}；把这些文件上传到 Dify 知识库，并把 DAXIN_KB_DIR 指向该目录。")
    print(f"对应的仿真标准：python testkit/range/setup_workspace.py {ws()}")


def cmd_exam(a):
    from bridge import BridgeRefused, serve                # noqa: PLC0415 - same folder
    w = ws()
    if not (w / "daxin.db").exists():
        raise SystemExit(f"工作区 {w} 不存在：先冻结标准（README 第 3 步）。")
    run = a.run or "N" + date.today().strftime("%y%m%d")   # opaque: a date, never the configuration under test
    out = DATA / "runs" / run; out.mkdir(parents=True, exist_ok=True)
    daxin("questions", "--out", str(out / "questions.json"), "--ws", str(w))
    try:
        srv = serve(a.port)
    except BridgeRefused as e:
        raise SystemExit(str(e))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    os.environ["DAXIN_HTTP_ENABLED"] = "1"                  # the target is the bridge on this machine, i.e. our own system
    try:
        args = ["ask", str(out / "questions.json"), f"http://127.0.0.1:{a.port}/", "--run", run, "--ws", str(w),
                "--interval", str(a.interval), "--meta-out", str(out / "meta_do_not_share_with_reviewers.json")]
        if a.limit:
            args += ["--limit", str(a.limit)]
        daxin(*args)
    finally:
        srv.shutdown()
    daxin("judge", "--ws", str(w))
    daxin("review-export", str(out / "blind_sheet.csv"), "--run", run, "--ws", str(w))
    daxin("audit-anchor", str(DATA / "audit_anchor.txt"), "--ws", str(w))
    print(f"\n本轮 {run} 完成。把 {out / 'blind_sheet.csv'} 复制两份，分别交给两位复核人；"
          f"不要把同目录的 meta 文件或机器判定给他们。机器判定未经人工复核前不算准确率。")


def cmd_backup(_):
    w = ws(); db = w / "daxin.db"
    if not db.exists():
        raise SystemExit("没有工作区可备份。")
    dst = DATA / "backups"; dst.mkdir(parents=True, exist_ok=True)
    target = dst / f"daxin-{time.strftime('%Y%m%d-%H%M%S')}.db"
    src = sqlite3.connect(db); bak = sqlite3.connect(target)
    with bak:
        src.backup(bak)                                    # consistent even if the workspace is being written
    src.close(); bak.close()
    print(f"已备份到 {target}")
    anchor = DATA / "audit_anchor.txt"
    daxin("audit-verify", "--ws", str(w), *(["--anchor", str(anchor)] if anchor.exists() else []))


def main(argv=None):
    load_env()
    sys.path.insert(0, str(HERE))
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("up", cmd_up), ("down", cmd_down), ("status", cmd_status), ("backup", cmd_backup)):
        sub.add_parser(name).set_defaults(fn=fn)
    p = sub.add_parser("smoke-kb"); p.add_argument("dir"); p.set_defaults(fn=cmd_smoke_kb)
    p = sub.add_parser("exam"); p.set_defaults(fn=cmd_exam)
    p.add_argument("--run", default="", help="本轮代号，默认 N+日期；同一天再跑请另给代号（如 N261111b）")
    p.add_argument("--limit", type=int, default=0, help="只问前 N 题（试跑用）")
    p.add_argument("--interval", type=float, default=1.0, help="两次提问的间隔秒数，下限 0.5")
    p.add_argument("--port", type=int, default=8810)
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
