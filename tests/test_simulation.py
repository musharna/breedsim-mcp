"""Founding, sessions, replicates, and the no-point-estimate rule.

Everything here runs against real AlphaSimR. Nothing is mocked, because the facts
being asserted — that `runMacs` is irreproducible and `quickHaplo` is not, that
run-to-run spread is large — are facts about the engine, and a mock would just
restate my assumptions back to me.
"""

import pytest

from breedsim_mcp.founding import found_population
from breedsim_mcp.replication import MIN_REPLICATES, TooFewReplicatesError, run_program
from breedsim_mcp.session import SessionStore, UnknownSessionError

# Small but not degenerate: enough segregating sites for selection to bite,
# small enough that the suite stays fast.
SMALL = {"n_ind": 40, "n_chr": 4, "seg_sites": 40, "n_qtl_per_chr": 5, "h2": 0.4}


# --------------------------------------------------------------------------
# founding
# --------------------------------------------------------------------------


def test_quickhaplo_reproduces_and_runmacs_does_not():
    """The measured asymmetry the whole determinism story rests on. Both halves
    live in one test so neither can drift into being asserted alone."""
    store = SessionStore()

    a = found_population(store, generator="quickHaplo", seed=1, **SMALL)
    b = found_population(store, generator="quickHaplo", seed=1, **SMALL)
    assert a.founder_hash == b.founder_hash, "quickHaplo must reproduce from a seed"
    assert a.reproducible is True

    c = found_population(store, generator="runMacs", seed=1, **SMALL)
    d = found_population(store, generator="runMacs", seed=1, **SMALL)
    assert c.founder_hash != d.founder_hash, (
        "runMacs is expected to IGNORE set.seed; if this ever passes, re-measure "
        "before trusting it — the whole reproducible flag depends on it"
    )
    assert c.reproducible is False
    assert "runMacs" in (c.reason or "")


def test_unknown_generator_is_refused():
    store = SessionStore()
    with pytest.raises(ValueError, match="generator"):
        found_population(store, generator="nonsense", seed=1, **SMALL)
    # Positive control: a valid generator still works.
    assert found_population(store, generator="quickHaplo", seed=1, **SMALL)


# --------------------------------------------------------------------------
# sessions
# --------------------------------------------------------------------------


def test_sessions_do_not_collide():
    store = SessionStore()
    one = found_population(store, generator="quickHaplo", seed=1, **SMALL)
    two = found_population(store, generator="quickHaplo", seed=2, **SMALL)
    assert one.session_id != two.session_id
    assert store.get(one.session_id).r_prefix != store.get(two.session_id).r_prefix
    # The first session's R state must survive creation of the second.
    assert store.get(one.session_id).founder_hash == one.founder_hash


def test_unknown_session_raises_naming_what_was_passed():
    store = SessionStore()
    with pytest.raises(UnknownSessionError, match="no-such-session"):
        store.get("no-such-session")


# --------------------------------------------------------------------------
# THE structural rule
# --------------------------------------------------------------------------


def test_a_single_run_cannot_be_requested():
    """The load-bearing decision. There must be no path to a point estimate."""
    store = SessionStore()
    s = found_population(store, generator="quickHaplo", seed=1, **SMALL)
    for bad in (1, 2, 0, -1):
        with pytest.raises(TooFewReplicatesError):
            run_program(store, s.session_id, cycles=2, replicates=bad)
    # Positive control in the same test: the floor itself is accepted.
    ok = run_program(store, s.session_id, cycles=2, replicates=MIN_REPLICATES)
    assert ok["replicates"] == MIN_REPLICATES


def test_results_are_distributions_not_point_estimates():
    store = SessionStore()
    s = found_population(store, generator="quickHaplo", seed=1, **SMALL)
    out = run_program(store, s.session_id, cycles=3, replicates=MIN_REPLICATES)

    assert len(out["cycles"]) == 3
    for rec in out["cycles"]:
        for field in ("mean", "sd", "ci_low", "ci_high"):
            assert field in rec["genetic_gain"], f"{field} missing"
        assert rec["genetic_gain"]["ci_low"] <= rec["genetic_gain"]["mean"]
        assert rec["genetic_gain"]["mean"] <= rec["genetic_gain"]["ci_high"]
    # No field anywhere may carry a lone run's value.
    assert "value" not in out["cycles"][0]["genetic_gain"]


def test_gain_rises_and_variance_falls_under_selection():
    """The Bulmer effect. If varG does not fall under truncation selection the
    programme is wired wrong — this is a correctness check on the wiring, not on
    AlphaSimR."""
    store = SessionStore()
    s = found_population(store, generator="quickHaplo", seed=3, **SMALL)
    out = run_program(store, s.session_id, cycles=3, replicates=MIN_REPLICATES)

    gains = [c["genetic_gain"]["mean"] for c in out["cycles"]]
    varg = [c["genetic_variance"]["mean"] for c in out["cycles"]]
    assert gains[-1] > gains[0], f"genetic gain must rise under selection: {gains}"
    assert varg[-1] < varg[0], f"genetic variance must fall under selection: {varg}"


def test_replicates_produce_real_spread():
    """Guards against a bug where every replicate silently runs the same seed and
    the CI collapses to zero — which would look like beautiful precision."""
    store = SessionStore()
    s = found_population(store, generator="quickHaplo", seed=5, **SMALL)
    out = run_program(store, s.session_id, cycles=2, replicates=MIN_REPLICATES)
    sds = [c["genetic_gain"]["sd"] for c in out["cycles"]]
    assert all(sd > 0 for sd in sds), f"replicates must actually differ, got sd={sds}"
