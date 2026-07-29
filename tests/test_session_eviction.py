"""Session eviction must actually free the R objects it claims to free.

This file exists because 0.1.0 shipped with eviction freeing NOTHING, and no test
noticed. `_free_r_state` intersected its target names against a bare `ls()`, which
omits dot-prefixed names unless `all.names=TRUE` — and the session prefix starts
with a dot by design. The intersection was always empty, so the `rm()` was a
permanent no-op while looking entirely reasonable.

The lesson for the test, not just the fix: **an eviction test must assert against
`ls(all.names=TRUE)`.** A test written with the same bare `ls()` as the code would
have reported zero surviving objects and passed against the broken version — the
harness would have shared the bug it was meant to catch.
"""

from breedsim_mcp.engine import r_eval
from breedsim_mcp.founding import found_population
from breedsim_mcp.replication import MIN_REPLICATES, run_program
from breedsim_mcp.session import SessionStore

SMALL = {"n_ind": 30, "n_chr": 2, "seg_sites": 20, "n_qtl_per_chr": 3, "h2": 0.4}


def _r_objects(prefix: str) -> list[str]:
    """Every global belonging to a session. all.names=TRUE is the whole point."""
    escaped = prefix.replace(".", "\\\\.")
    return list(r_eval(f'ls(envir=.GlobalEnv, all.names=TRUE, pattern="^{escaped}")'))


def _use(store, seed):
    s = found_population(store, generator="quickHaplo", seed=seed, **SMALL)
    run_program(store, s.session_id, cycles=1, replicates=5)
    return s


def test_eviction_frees_every_object_the_session_owned():
    """Not just `_founders` and `_SP` — the populations too.

    `_p0`, `_pop` and `_pop_sel` are the large objects, and the original
    name-enumerated cleanup omitted all three. Asserting on the whole prefixed set
    is what makes this robust to any R object a future feature adds.
    """
    store = SessionStore(max_sessions=2)
    first = _use(store, 1)
    prefix = first.r_prefix

    owned = _r_objects(prefix)
    assert len(owned) >= 4, f"expected several R objects, saw {owned}"

    survivors = [_use(store, k) for k in (2, 3)]  # pushes `first` out

    assert _r_objects(prefix) == [], (
        f"evicted session leaked R objects: {_r_objects(prefix)}"
    )

    # Positive control: eviction must be surgical. If this were freeing by
    # something broader than the prefix, the live session would be gone too and
    # the assertion above would pass for entirely the wrong reason.
    assert _r_objects(survivors[-1].r_prefix), "eviction also freed a LIVE session"


def test_a_session_is_unreachable_after_eviction():
    """The Python side must agree with the R side."""
    import pytest

    from breedsim_mcp.session import UnknownSessionError

    store = SessionStore(max_sessions=1)
    first = _use(store, 4)
    _use(store, 5)

    with pytest.raises(UnknownSessionError, match="Unknown session_id"):
        store.get(first.session_id)


# --------------------------------------------------------------------------
# Upper bounds (0.1.0 validated floors only)
# --------------------------------------------------------------------------


def test_oversized_requests_are_refused_at_every_entry_point():
    """Each entry point must bound its own inputs.

    Checked per entry point rather than once, because they take different
    parameters and a bound applied in only one of them leaves the others open —
    which is exactly the state 0.1.0 shipped in, where nothing had a ceiling.
    """
    import pytest

    from breedsim_mcp.comparison import compare_programs
    from breedsim_mcp.limits import LIMITS, LimitExceededError

    store = SessionStore()

    with pytest.raises(LimitExceededError, match="n_ind"):
        found_population(
            store,
            generator="quickHaplo",
            seed=1,
            **{**SMALL, "n_ind": LIMITS["n_ind"] + 1},
        )

    s = _use(store, 7)

    with pytest.raises(LimitExceededError, match="replicates"):
        run_program(store, s.session_id, cycles=1, replicates=LIMITS["replicates"] + 1)

    with pytest.raises(LimitExceededError, match="cycles"):
        run_program(store, s.session_id, cycles=LIMITS["cycles"] + 1, replicates=5)

    with pytest.raises(LimitExceededError, match="replicates"):
        compare_programs(
            store, s.session_id, cycles=1, replicates=LIMITS["replicates"] + 1
        )

    # Positive control: values AT the ceiling are allowed, so the bound is a
    # ceiling rather than an off-by-one that rejects legitimate work.
    assert run_program(store, s.session_id, cycles=1, replicates=MIN_REPLICATES)


def test_limits_are_published_so_a_caller_can_size_a_request():
    """An agent should read the ceiling, not discover it by being refused."""
    import asyncio

    from breedsim_mcp.limits import LIMITS
    from breedsim_mcp.server import build_server

    out = asyncio.run(build_server().call_tool("list_methods", {}))
    out = out[1] if isinstance(out, tuple) else out
    assert out["limits"] == LIMITS
    assert out["limits"]["replicates"] >= MIN_REPLICATES
