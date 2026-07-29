"""Advisories. Pure functions over summary objects — no R, no I/O.

Note what is NOT here: a BLOCKING_CODES set. `plantcv-mcp` withholds traits when a
guard fires, because there the wrong mask yields a confidently wrong number. Here
the structural protection is different — results are always distributions, so a
caller can already see when the answer is too noisy to use. These advisories
explain; they do not withhold.
"""

from dataclasses import dataclass

# A caller who deliberately runs multi-threaded for speed is making a legitimate
# trade. Doing it without being told is not.
BLOCKING_CODES: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Advisory:
    code: str
    message: str


def nondeterministic_founders_warning(session) -> "Advisory | None":
    """Fires when founders came from runMacs, whose coalescent RNG is seeded once
    per R session — so a repeat seeded call in this process gives different
    founders. The detail lives in `session.reason`; this only routes it."""
    if session.reproducible:
        return None
    return Advisory(
        code="nondeterministic_founders",
        message=(
            session.reason
            or "Founders are not reproducible; re-running will not give this result."
        ),
    )


def threads_not_pinned_warning(pinned: bool) -> "Advisory | None":
    """Fires when OpenMP is free to use more than one thread.

    Measured: with founders fixed and threads pinned, seed 7 gives
    meanG=2.01451853 twice; unpinned it gives 2.397 then 2.125.
    """
    if pinned:
        return None
    return Advisory(
        code="threads_not_pinned",
        message=(
            "OMP_NUM_THREADS is not '1', so the selection path's reduction order "
            "varies between runs and the same seed will NOT reproduce. Set "
            "OMP_NUM_THREADS=1 before the process starts — setting it afterwards "
            "is a no-op, because R reads it when OpenMP initialises."
        ),
    )


def replicates_too_few_warning(
    gain_summary: dict, max_relative_width: float = 0.5
) -> "Advisory | None":
    """Fires when the CI is wide relative to the effect it is meant to support.

    Relative width, not absolute: an interval of ±0.4 is fine around a mean of 10
    and useless around a mean of 0.5.
    """
    mean = abs(gain_summary.get("mean", 0.0))
    width = gain_summary.get("ci_high", 0.0) - gain_summary.get("ci_low", 0.0)
    if mean == 0:
        return None
    if width / mean <= max_relative_width:
        return None
    return Advisory(
        code="replicates_too_few",
        message=(
            f"The 95% confidence interval spans {width:.3f} around a mean of "
            f"{gain_summary.get('mean'):.3f} ({width / mean:.0%} of the effect). "
            f"That is too wide to support a comparison. Re-run with more "
            f"replicates (currently {gain_summary.get('n')})."
        ),
    )


def variance_exhausted_warning(
    variance_cycles: list[dict], collapse_fraction: float = 0.2
) -> "Advisory | None":
    """Fires when genetic variance has collapsed toward zero.

    Once variance is gone, further cycles cannot deliver gain. A meanG still
    drifting upward at that point is a plateau being misread as progress.
    """
    if len(variance_cycles) < 2:
        return None
    first = variance_cycles[0].get("mean", 0.0)
    last = variance_cycles[-1].get("mean", 0.0)
    if first <= 0 or last > first * collapse_fraction:
        return None
    return Advisory(
        code="variance_exhausted",
        message=(
            f"Genetic variance fell from {first:.3f} to {last:.3f} "
            f"({last / first:.0%} of its starting value). Selection has nearly "
            "exhausted the usable variation, so additional cycles will add little "
            "gain — a still-rising mean is a plateau, not progress."
        ),
    )


def indistinguishable_warning(comparison: dict) -> "Advisory | None":
    """Fires when the paired difference interval contains zero.

    The point is to stop a larger mean being read as a better programme. With
    the interval straddling zero, the ordering of the two means is not
    established by this run — more replicates, or a real difference, would be
    needed to establish it.
    """
    if comparison.get("favours") is not None:
        return None
    diff = comparison["cycles"][-1]["difference"]
    return Advisory(
        code="difference_indistinguishable",
        message=(
            f"The paired difference is {diff['mean']:.3f} with a 95% interval of "
            f"[{diff['ci_low']:.3f}, {diff['ci_high']:.3f}], which contains zero. "
            f"These two programmes are NOT distinguishable at {diff['n']} "
            "replicates. Do not report the larger mean as the better programme; "
            "either raise replicates or accept that the difference is too small "
            "to resolve."
        ),
    )


def overlap_but_different_warning(comparison: dict) -> "Advisory | None":
    """Fires when the per-arm intervals overlap but the PAIRED difference does not.

    This is the case a naive reading gets backwards. Two overlapping confidence
    intervals do not imply no difference: pairing removes the seed-to-seed
    variation that made both intervals wide, so a contrast can be firmly
    resolved while the individual intervals still overlap heavily.
    """
    if comparison.get("favours") is None:
        return None
    if not comparison.get("intervals_overlap"):
        return None
    winner = comparison["programs"][comparison["favours"]]["label"]
    return Advisory(
        code="overlap_but_different",
        message=(
            "The two programmes' individual confidence intervals OVERLAP, but the "
            f"paired difference excludes zero and favours {winner}. Read the "
            "difference, not the overlap — pairing cancels the shared seed noise "
            "that widens both individual intervals, which is why it can resolve a "
            "contrast that eyeballing the two intervals cannot."
        ),
    )
