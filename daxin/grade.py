"""Risk grade R1-R4. The mapping is an EXAMPLE to be calibrated with pilot data and the bank's own views."""
from __future__ import annotations

IMPACT = {"money": 3, "condition": 2, "info": 1}
_MONEY = ("fee", "rate", "limit", "penalty", "amount", "interest")
_COND = ("days", "min_", "valid", "months", "grace")


def impact_of(fact_key: str) -> str:
    k = fact_key.lower()
    if any(t in k for t in _MONEY):
        return "money"
    if any(t in k for t in _COND):
        return "condition"
    return "info"


def grade(verdict: str, flags: list[str], fact_key: str, exposure: str = "mid") -> str | None:
    """R4 severe ... R1 low. Only confirmed wrong answers (C1-C4) and C5 are graded; exposure is 'low', 'mid' or 'high'
    (a PROXY: the topic's share of the test set or the sample, not real traffic)."""
    if verdict not in ("C1", "C2", "C3", "C4", "C5"):
        return None
    n = IMPACT[impact_of(fact_key)]
    n += {"low": -1, "mid": 0, "high": 1}.get(exposure, 0)
    if verdict == "C4" or "C4" in flags:
        n += 1
    if verdict == "C5":
        n = max(n, 3)
    return f"R{max(1, min(4, n))}"
