import json
import re

from typer.testing import CliRunner

from daxin.cli import app
from daxin.demo import run

runner = CliRunner()


def _data(html):
    return json.loads(re.search(r"const D=(.*?);const \$=", html, re.S).group(1).replace("<\\/", "</"))


def test_console_full_and_blind_views(tmp_path):
    run(tmp_path / "w", log=lambda *a, **k: None)
    full, blind = tmp_path / "full.html", tmp_path / "blind.html"
    assert runner.invoke(app, ["console", str(full), "--ws", str(tmp_path / "w")]).exit_code == 0
    assert runner.invoke(app, ["console", str(blind), "--ws", str(tmp_path / "w"), "--blind"]).exit_code == 0
    f, b = _data(full.read_text("utf-8")), _data(blind.read_text("utf-8"))
    assert f["audit_ok"] and f["items"] and f["lights"] and "仿真" in full.read_text("utf-8")
    assert any(i["spans"] for i in f["items"])                      # numbers are located in the answers
    for i in b["items"]:                                            # reviewers must not see any verdict, reason or clause
        assert not ({"machine", "human", "reason", "clause", "expected", "flags"} & set(i))
    assert b["lights"] == []
