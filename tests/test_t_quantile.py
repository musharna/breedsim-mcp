"""The 95% interval uses the exact t quantile at every replicate count allowed.

The reference here is computed independently of R -- Simpson integration of the
t density -- so the test cannot agree with the implementation merely by sharing
its source. It checks the quantile the interval ACTUALLY used, recovered from
`summarise`'s output, rather than calling the helper, so a table, a rounding or
a normal approximation anywhere on the path shows up.
"""

import math

import pytest

from breedsim_mcp.limits import LIMITS
from breedsim_mcp.replication import MIN_REPLICATES, summarise


def _t_cdf(x: float, df: int, steps: int = 4000) -> float:
    """P(T <= x) for x >= 0, by composite Simpson over the density on [0, x]."""
    log_c = (
        math.lgamma((df + 1) / 2) - math.lgamma(df / 2) - 0.5 * math.log(df * math.pi)
    )

    def pdf(t: float) -> float:
        return math.exp(log_c - (df + 1) / 2 * math.log1p(t * t / df))

    h = x / steps
    total = pdf(0.0) + pdf(x)
    for i in range(1, steps):
        total += (4 if i % 2 else 2) * pdf(i * h)
    return 0.5 + total * h / 3


def _quantile_used(n: int) -> float:
    values = [float(i) for i in range(n)]
    s = summarise(values)
    return (s["ci_high"] - s["mean"]) / (s["sd"] / math.sqrt(n))


def test_interval_quantile_is_exact_for_every_allowed_replicate_count():
    wrong = []
    for n in range(MIN_REPLICATES, LIMITS["replicates"] + 1):
        q = _quantile_used(n)
        coverage = _t_cdf(q, n - 1)
        if abs(coverage - 0.975) > 1e-6:
            wrong.append((n, round(q, 4), round(coverage, 5)))
    assert not wrong, (
        f"{len(wrong)} replicate counts use a quantile whose one-sided coverage "
        f"is not 0.975 (n, quantile used, coverage): {wrong[:5]} ..."
    )


def test_the_reference_can_tell_a_rounded_quantile_from_the_exact_one():
    """Positive control for the reference itself: it must accept the known
    df=4 value and REJECT the two errors the old table made -- the next listed
    df's value (n=22 used df=24's 2.064) and the normal 1.96 past df=29."""
    assert _t_cdf(2.7764451, 4) == pytest.approx(0.975, abs=1e-6)
    assert abs(_t_cdf(2.064, 21) - 0.975) > 1e-4
    assert abs(_t_cdf(1.96, 30) - 0.975) > 1e-4


def test_sd_and_interval_match_a_hand_computed_sample():
    """The test above recovers the quantile by dividing by the sd `summarise`
    reported, so it agrees with itself whichever sd that is: a population sd
    (divide by n) in place of the sample sd (divide by n - 1) passed it and every
    other test. This one is computed by hand.

    Values 1, 2, 3, 4: mean 2.5, squared deviations 2.25 + 0.25 + 0.25 + 2.25 = 5,
    so the sample sd is sqrt(5 / 3) = 1.2910 (the population sd would be
    sqrt(5 / 4) = 1.1180). With df = 3, t(0.975) = 3.18245 (printed tables give
    3.182), so the half-width is 3.18245 * 1.2910 / sqrt(4) = 2.0543.
    """
    s = summarise([1.0, 2.0, 3.0, 4.0])
    assert s["n"] == 4
    assert s["mean"] == 2.5
    assert s["sd"] == pytest.approx(math.sqrt(5 / 3), rel=1e-12)
    assert s["ci_low"] == pytest.approx(2.5 - 2.054260, abs=1e-5)
    assert s["ci_high"] == pytest.approx(2.5 + 2.054260, abs=1e-5)
