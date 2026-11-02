import pytest

from daxin.stats import cohen_kappa, min_n_for_lower_bound, rule_of_three, wilson


def test_the_sample_sizes_quoted_in_the_documents():
    assert min_n_for_lower_bound(0.95) == 73 and min_n_for_lower_bound(0.90) == 35


def test_wilson_basics():
    assert wilson(0, 0) == (0.0, 1.0)
    lo, hi = wilson(50, 100)
    assert 0.40 < lo < 0.5 < hi < 0.60
    assert wilson(100, 100)[1] == pytest.approx(1.0) and wilson(0, 100)[0] == 0.0
    assert wilson(73, 73)[0] >= 0.95 > wilson(72, 72)[0]


def test_rule_of_three():
    assert rule_of_three(100) == 0.03 and rule_of_three(0) == 1.0 and rule_of_three(1) == 1.0


def test_kappa():
    assert cohen_kappa([]) is None
    assert cohen_kappa([("a", "a"), ("b", "b")]) == 1.0
    assert cohen_kappa([("a", "b"), ("b", "a")]) == -1.0
