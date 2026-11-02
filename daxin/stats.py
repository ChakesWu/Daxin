"""Honest statistics: every rate comes with its sample size and an interval."""
from __future__ import annotations

import math


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for k successes in n trials (95% by default)."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def rule_of_three(n: int) -> float:
    """Upper 95% bound of an error rate after n trials with zero errors (about 3/n)."""
    return 1.0 if n == 0 else min(1.0, 3.0 / n)


def min_n_for_lower_bound(target: float, z: float = 1.96) -> int:
    """Smallest n with zero errors whose Wilson lower bound of the pass rate reaches `target`."""
    n = 1
    while wilson(n, n, z)[0] < target:
        n += 1
        if n > 100000:
            raise ValueError("target unreachable")
    return n


def cohen_kappa(pairs: list[tuple[str, str]]) -> float | None:
    if not pairs:
        return None
    labels = sorted({x for p in pairs for x in p})
    n = len(pairs)
    po = sum(a == b for a, b in pairs) / n
    pe = sum((sum(a == l for a, _ in pairs) / n) * (sum(b == l for _, b in pairs) / n) for l in labels)
    return None if pe == 1 else (po - pe) / (1 - pe)
