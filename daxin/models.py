"""Data model of the policy kernel (see docs/ARCHITECTURE.md, section 4.1)."""
from __future__ import annotations

from datetime import date
from typing import Literal, Optional, Union

from pydantic import BaseModel, Field

DIMS = ("product", "channel", "region", "language")
Status = Literal["draft", "confirmed", "frozen"]


class Scope(BaseModel):
    """Where a clause applies. None on a dimension means 'any value'."""
    product: Optional[str] = None
    channel: Optional[str] = None
    region: Optional[str] = None
    language: Optional[str] = None

    def specificity(self) -> int:
        return sum(getattr(self, d) is not None for d in DIMS)

    def covers(self, q: "Scope") -> bool:
        """True if a question asked in scope q falls under this clause scope."""
        return all(getattr(self, d) is None or getattr(self, d) == getattr(q, d) for d in DIMS)

    def overlaps(self, o: "Scope") -> bool:
        """True if some situation could fall under both scopes."""
        return all(getattr(self, d) is None or getattr(o, d) is None or getattr(self, d) == getattr(o, d) for d in DIMS)


class Fact(BaseModel):
    key: str
    value: Union[float, str]
    op: Literal["=", "<=", ">="] = "="
    unit: str = ""
    condition: str = ""


class Clause(BaseModel):
    id: str
    version: str
    topic: str
    text: str = ""
    scope: Scope = Field(default_factory=Scope)
    facts: list[Fact]
    effective_from: date
    effective_to: Optional[date] = None
    status: Status = "draft"
    source_ref: str = ""            # document, page, paragraph; never an institution name in public output

    @property
    def ref(self) -> str:
        return f"{self.id}@{self.version}"


class Observation(BaseModel):
    """One answer given by the system under test. Append-only."""
    obs_id: str
    ts: str                         # 'YYYY-MM-DD HH:MM'
    inst: str                       # institution CODE, never a name
    region: str = ""
    product: str = ""
    channel: str = ""
    language: str = ""
    question_id: str = ""
    session: str = ""
    turn: int = 1
    retest_group: str = ""
    question: str = ""
    answer: str = ""
    answer_sha256: str = ""
    fact_key: str = ""
    topic: str = ""
    must_handoff: bool = False
    recorder: str = ""
    system_fp: str = ""             # fingerprint of the system under test (model, knowledge base, config); '' = unknown. KEEP LAST: DB column order

    @property
    def day(self) -> date:
        return date.fromisoformat(self.ts[:10])

    def scope(self) -> Scope:
        return Scope(product=self.product or None, channel=self.channel or None,
                     region=self.region or None, language=self.language or None)


VERDICTS = ("通过", "C1", "C2", "C3", "C4", "C5", "待人工", "无回答", "无法判断", "不适用")
ERRORS = ("C1", "C2", "C3", "C4")           # confirmed wrong answers
SCORED = ("通过",) + ERRORS                  # the denominator of every rate


class Judgment(BaseModel):
    obs_id: str
    rule_version: str
    verdict: str
    flags: list[str] = Field(default_factory=list)       # e.g. ['C4'] when a promise overlays another verdict
    claims: list[float] = Field(default_factory=list)
    expected: Optional[Union[float, str]] = None
    clause_ref: str = ""
    reason: str = ""
