"""Create a workspace holding the range's frozen standard (SIMULATED, institution code BANK-X) and its generated questions.
Usage: python setup_workspace.py WS_DIR"""
import json
import sys
from datetime import date
from pathlib import Path

from daxin.audit import Audit
from daxin.db import DB
from daxin.models import Clause, Fact, Scope
from daxin.observe import Store
from daxin.policy import Policy
from daxin.questions import generate

here, ws = Path(__file__).parent, Path(sys.argv[1])
db = DB(ws / "daxin.db"); audit = Audit(db); pol = Policy(db, audit)
for r in json.loads((here / "standard.json").read_text(encoding="utf-8")):
    if any(c.id == r["id"] and c.version == r["version"] for c in pol.clauses()):
        continue
    c = Clause(id=r["id"], version=r["version"], topic=r["topic"], text="仿真靶场标准", scope=Scope(product=r["product"], region=r["region"], channel=r["channel"]),
               facts=[Fact(key=r["key"], value=r["value"], unit=r["unit"])], effective_from=date.fromisoformat(r["effective_from"]), source_ref="仿真靶场｜testkit/range/standard.json")
    pol.add(c, "range-setup"); pol.confirm(c.id, c.version, "range-setup"); pol.freeze(c.id, c.version, "range-setup-2")
qs = generate(pol, date(2026, 11, 10), paraphrases=2)
(ws / "questions.json").write_text(json.dumps([q.model_dump(mode="json") for q in qs], ensure_ascii=False, indent=1), encoding="utf-8")
print(f"标准已冻结；出题 {len(qs)} 道：", {k: sum(q.kind == k for q in qs) for k in ("basic", "boundary", "paraphrase")})
