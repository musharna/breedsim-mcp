"""Paired comparison of two programmes.

The behaviour under test is mostly a refusal: `favours` must stay null whenever
the difference interval contains zero, however tempting the larger mean looks.
Every assertion here is paired with its opposite case in the same test, so a
function that ALWAYS refuses reads as broken rather than as cautious.
"""

import pytest

from breedsim_mcp.comparison import compare_programs
from breedsim_mcp.diagnostics import (
    indistinguishable_warning,
    overlap_but_different_warning,
)
from breedsim_mcp.founding import found_population
from breedsim_mcp.replication import MIN_REPLICATES, TooFewReplicatesError
from breedsim_mcp.session import SessionStore

SMALL = {"n_ind": 60, "n_chr": 4, "seg_sites": 40, "n_qtl_per_chr": 5, "h2": 0.4}


@pytest.fixture(scope="module")
def session():
    store = SessionStore()
    s = found_population(store, generator="quickHaplo", seed=11, **SMALL)
    return store, s.session_id


def test_a_comparison_needs_at_least_the_replicate_floor(session):
    """One run per arm is exactly the case that looks decisive and is not."""
    store, sid = session
    with pytest.raises(TooFewReplicatesError, match="below the minimum"):
        compare_programs(store, sid, cycles=1, replicates=1)

    # Positive control in the same test: the floor itself is allowed.
    out = compare_programs(store, sid, cycles=1, replicates=MIN_REPLICATES)
    assert out["replicates"] == MIN_REPLICATES


def test_identical_programmes_are_reported_as_indistinguishable(session):
    """Two arms with the SAME parameters must not produce a winner.

    This is the sharpest available check on the whole design: because the arms
    are paired on shared seeds and configured identically, every paired
    difference is exactly zero, so no amount of replication can manufacture a
    preference. If `favours` is ever non-null here, the verdict logic is reading
    noise as signal.
    """
    store, sid = session
    out = compare_programs(
        store, sid, a_n_select=10, b_n_select=10, cycles=1, replicates=MIN_REPLICATES
    )
    diff = out["cycles"][-1]["difference"]

    assert diff["mean"] == pytest.approx(0.0, abs=1e-12)
    assert out["favours"] is None
    assert indistinguishable_warning(out) is not None


def test_a_real_difference_is_resolved_and_names_the_winner(session):
    """Selecting 2 of 60 vs 50 of 60 is a large, directional difference.

    Harsher truncation means higher selection intensity, so arm A should gain
    more per cycle. The point of the assertion is not the biology but that the
    verdict machinery CAN return a winner — without this, the previous test
    would pass against a function that always returns None.
    """
    store, sid = session
    out = compare_programs(
        store, sid, a_n_select=2, b_n_select=50, cycles=1, replicates=MIN_REPLICATES
    )
    diff = out["cycles"][-1]["difference"]

    assert out["favours"] == "a", f"expected A to win, got {out['favours']} ({diff})"
    assert diff["ci_low"] > 0
    assert indistinguishable_warning(out) is None


def test_pairing_uses_the_same_seed_for_both_arms(session):
    """Identical arms must give a difference of EXACTLY zero, not merely a small one.

    That is the observable signature of common random numbers. If the arms were
    seeded independently, identical configurations would still differ by the
    seed-to-seed noise measured at sd 0.247 — nowhere near exact zero.
    """
    store, sid = session
    out = compare_programs(
        store, sid, a_n_select=8, b_n_select=8, cycles=2, replicates=MIN_REPLICATES
    )
    for cycle in out["cycles"]:
        assert cycle["difference"]["mean"] == pytest.approx(0.0, abs=1e-12)
        assert cycle["difference"]["sd"] == pytest.approx(0.0, abs=1e-12)


def test_overlap_warning_fires_only_when_overlap_hides_a_real_difference():
    """The warning must distinguish its two ingredients, not fire on either alone.

    Built from literals rather than a simulation, because the case being tested
    is a specific combination — intervals overlapping WHILE the paired
    difference excludes zero — that is awkward to obtain on demand from a real
    run and would make the test depend on luck.
    """
    overlapping_arms = {
        "a_genetic_gain": {"ci_low": 1.0, "ci_high": 3.0},
        "b_genetic_gain": {"ci_low": 2.0, "ci_high": 4.0},
    }
    resolved = {
        "favours": "b",
        "intervals_overlap": True,
        "programs": {"a": {"label": "A"}, "b": {"label": "B"}},
        "cycles": [
            {"difference": {"mean": -1.0, "ci_low": -1.5, "ci_high": -0.5, "n": 10}}
        ],
        **overlapping_arms,
    }
    fired = overlap_but_different_warning(resolved)
    assert fired is not None
    assert "B" in fired.message

    # Control 1: overlapping intervals, but the difference does NOT resolve.
    unresolved = {**resolved, "favours": None}
    assert overlap_but_different_warning(unresolved) is None

    # Control 2: difference resolves, but the intervals never overlapped, so
    # there is no misleading overlap to warn about.
    disjoint = {**resolved, "intervals_overlap": False}
    assert overlap_but_different_warning(disjoint) is None


def test_verdict_reads_the_interval_not_the_mean():
    """A positive mean whose interval straddles zero must NOT name a winner.

    Tested on literals because the realistic case — a difference that is
    non-zero but unresolved — is stochastic, and a test that has to get lucky to
    fail is not a test. The identical-arms case above cannot cover this: its
    difference is exactly zero, so a verdict that simply returned the sign of
    the mean would pass it and still be wrong here.
    """
    from breedsim_mcp.comparison import _verdict

    # Mean clearly favours A, interval does not exclude zero.
    assert _verdict({"mean": 0.42, "ci_low": -0.10, "ci_high": 0.94}) is None
    assert _verdict({"mean": -0.42, "ci_low": -0.94, "ci_high": 0.10}) is None

    # Positive controls: intervals that DO exclude zero, both directions.
    assert _verdict({"mean": 0.42, "ci_low": 0.10, "ci_high": 0.74}) == "a"
    assert _verdict({"mean": -0.42, "ci_low": -0.74, "ci_high": -0.10}) == "b"
