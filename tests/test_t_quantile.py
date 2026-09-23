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
