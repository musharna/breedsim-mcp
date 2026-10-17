"""Quantitative-genetics expectations for the agent benchmark's answer key.

Everything here is closed-form or numerical integration over the normal
distribution, plus one seeded numpy Monte Carlo over standard normal order
statistics (a known generator). It never imports breedsim_mcp and never runs
AlphaSimR: the key is fixed by theory, and the simulator is only used later,
by ``calibrate.R``, to measure how wide the band around it must be.

Units throughout: founder additive genetic variance 1 and founder genetic mean
0, which is what ``addTraitA`` builds; residual variance is fixed at founding,
``VE = (1 - h2) / h2``, which is what ``setVarE(h2=)`` does.

The model for a selection cycle is the infinitesimal model with the Bulmer
effect and finite-population corrections:

- the best ``n`` of ``N`` are kept on phenotype. Their expected mean, in
  phenotypic SD, is the finite-sample intensity ``i(n, N)``: the expected mean
  of the top ``n`` of ``N`` standard normal draws (integration, exact).
- the parents' breeding values regress on phenotype with slope ``h2_t``, so
  response is ``i * h2_t * sigma_P(t)`` (breeder's equation, R = h2 S).
- the variance among the selected is reduced by the expected within-selected
  variance of the top ``n`` order statistics (Monte Carlo, seeded).
- progeny variance is half the parents' between-pair variance plus half the
  Mendelian (within-family) variance of the base, ``(1 - F) / 2``, with ``F``
  the parents' inbreeding, advanced by ``1 / (2 Ne)`` a generation.
"""

from __future__ import annotations

import math
from functools import cache

import numpy as np

MC_SEED = 20261016


def phi(x: np.ndarray | float) -> np.ndarray | float:
    return np.exp(-0.5 * np.square(x)) / math.sqrt(2 * math.pi)


def upper_tail(x: float) -> float:
    return 0.5 * math.erfc(x / math.sqrt(2))


def truncation_point(p: float) -> float:
    """z with P(Z > z) = p, by bisection on erfc (no scipy needed)."""
    lo, hi = -10.0, 10.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if upper_tail(mid) > p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def intensity_infinite(p: float) -> float:
    """i = phi(z) / p: selection intensity for the top fraction p of an
    infinitely large normal population."""
    return float(phi(truncation_point(p)) / p)


def variance_reduction_infinite(p: float) -> float:
    """k = i (i - z): fractional reduction in phenotypic variance among the
    selected, infinite population."""
    i = intensity_infinite(p)
    return i * (i - truncation_point(p))


@cache
def intensity_finite(n: int, N: int) -> float:
    """E[mean of the top n of N iid standard normals], by integration.

    E[sum of top n] = N * integral x phi(x) P(at most n-1 of the other N-1
    exceed x) dx: each draw contributes when fewer than n others beat it.
    """
    x = np.linspace(-9, 9, 36001)
    q = np.array([upper_tail(v) for v in x])  # P(other > x)
    # P(Bin(N-1, q) <= n-1), summed in log space to stay finite at N = 5000.
    lq = np.log(np.clip(q, 1e-300, 1))
    l1q = np.log(np.clip(1 - q, 1e-300, 1))
    cdf = np.zeros_like(x)
    for j in range(n):
        logc = math.lgamma(N) - math.lgamma(j + 1) - math.lgamma(N - j)
        cdf += np.exp(logc + j * lq + (N - 1 - j) * l1q)
    integrand = x * phi(x) * cdf
    return float(N / n * np.trapezoid(integrand, x))


@cache
def within_selected_variance(n: int, N: int) -> float:
    """E[variance (divisor n) among the top n of N standard normals].

    Seeded Monte Carlo over order statistics; the draw count keeps its
    standard error under 0.1% of the value for every (n, N) the key uses.
    """
    rng = np.random.default_rng(MC_SEED + 7919 * n + N)
    reps = max(4000, int(4e7 // N))
    total = 0.0
    done = 0
    while done < reps:
        b = min(reps - done, max(1, int(4e6 // N)))
        z = rng.standard_normal((b, N))
        top = -np.partition(-z, n - 1, axis=1)[:, :n]
        total += float(top.var(axis=1).sum())
        done += b
    return total / reps


def contribution_variance(n: int, m: int) -> float:
    """Variance of the number of crosses each parent enters, for AlphaSimR's
    randCross plan on n parents and m crosses (sampHalfDialComb: every one of
    the M = n(n-1)/2 pairs once per full round, the remainder drawn without
    replacement). A parent's count in the remainder is hypergeometric."""
    M = n * (n - 1) // 2
    r = m % M
    if r == 0 or M == 1:
        return 0.0
    succ = n - 1
    return r * (succ / M) * (1 - succ / M) * (M - r) / (M - 1)


def effective_size(n: int, m: int) -> float:
    """Ne for n monoecious parents, each cross giving one progeny, so a
    parent's gamete count is its cross count: mean k_bar = 2m/n, variance Vk.
    Ne = (n k_bar - 2) / (k_bar - 1 + Vk / k_bar), the inbreeding effective
    number for a monoecious population whose size changes."""
    k_bar = 2 * m / n
    vk = contribution_variance(n, m)
    return (n * k_bar - 2) / (k_bar - 1 + vk / k_bar)


def programme(
    N: int, n: int, h2: float, cycles: int, n_cross: int | None = None
) -> list[dict[str, float]]:
    """Expected genetic mean and variance after each cycle of truncation
    selection on phenotype (best n of N), random mating of the selected into
    n_cross progeny (default N). Variances are population variances (divisor
    = population size), which is what AlphaSimR's varG reports."""
    m = N if n_cross is None else n_cross
    ve = (1 - h2) / h2
    i = intensity_finite(n, N)
    vz = within_selected_variance(n, N)
    ne = effective_size(n, m)
    mean, var, inbreeding = 0.0, 1.0, 0.0
    out = []
    pop = N
    for t in range(1, cycles + 1):
        # The intensity and order-statistic variance depend on the current
        # population size; after cycle 1 it is m.
        if pop != N:
            i = intensity_finite(n, pop)
            vz = within_selected_variance(n, pop)
        sp = math.sqrt(var + ve)
        h2t = var / (var + ve)
        mean += i * h2t * sp
        v_sel = var * (h2t * vz + (1 - h2t) * (n - 1) / n)
        # Midparent of a random distinct pair from a finite set (divisor n):
        # Var((X+Y)/2) = v/2 * (1 - 1/(n-1)).
        between = 0.5 * v_sel * (1 - 1 / (n - 1)) if n > 2 else 0.0
        within = 0.5 * (1 - inbreeding)
        inbreeding = 1 / (2 * ne) + (1 - 1 / (2 * ne)) * inbreeding
        var = (between + within) * (1 - 1 / m)
        pop = m
        out.append({"cycle": t, "mean": mean, "var": var, "ne": ne})
    return out


def drift_variance_textbook(N: int, t: int) -> float:
    """V_A(t) = V_A(0) (1 - 1/(2 Ne))^t with Ne = N: the answer most
    textbooks give for pure drift."""
    return (1 - 1 / (2 * N)) ** t
