"""Inputs R cannot run, refused through the MCP layer with a reason.

Each of these used to reach R, die there, and come back to the caller as the
SDK's masked `Error executing tool <name>` — or, worse, succeed and leave a
session that could not do anything, or one whose spec said something the
founders did not have. Every test drives the real server with `call_tool`, and
every refusal is matched on its TEXT: `UnexpectedToolError` (the masked crash)
is itself a ToolError, so asserting only the type would pass on the bug.

Each refusal is paired with the nearest legitimate call succeeding in the same
test, so a harness that refused everything could not read as a pass.
"""

import asyncio

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from breedsim_mcp import engine, server
from breedsim_mcp.founding import found_population
from breedsim_mcp.session import SessionStore

SMALL = {"n_ind": 50, "n_chr": 2, "seg_sites": 50, "n_qtl_per_chr": 5}


def _call(srv, tool, args):
    return asyncio.run(srv.call_tool(tool, args)).structured_content


def _bs_objects() -> set[str]:
    return set(
        engine.r_eval('ls(envir=.GlobalEnv, all.names=TRUE, pattern="^\\\\.bs_")')
    )


# --------------------------------------------------------------------------
# M1: a correlation matrix no set of traits can have
# --------------------------------------------------------------------------


def test_impossible_trait_correlation_is_refused_and_the_boundary_is_accepted():
    """-0.9 between each of three traits cannot exist: AlphaSimR substituted the
    nearest valid matrix, the spec echoed -0.9, and the founders' realised
    correlations were -0.40 to -0.58."""
    srv = server.build_server()
    with pytest.raises(ToolError, match=r"-1/\(n-1\) = -0\.5000"):
        _call(
            srv,
            "found_population",
            {**SMALL, "h2": [0.4, 0.4, 0.4], "trait_correlation": -0.9},
        )
    # Just past the bound is still impossible ...
    with pytest.raises(ToolError, match="not positive semi-definite"):
        _call(
            srv,
            "found_population",
            {**SMALL, "h2": [0.4, 0.4, 0.4], "trait_correlation": -0.51},
        )
    # ... while the bound itself (singular, still valid) and -0.9 with TWO traits
    # (bound -1) are real correlation matrices and must be accepted.
    at_bound = _call(
        srv,
        "found_population",
        {**SMALL, "h2": [0.4, 0.4, 0.4], "trait_correlation": -0.5},
    )
    assert at_bound["spec"]["trait_correlation"] == -0.5
    two = _call(
        srv, "found_population", {**SMALL, "h2": [0.4, 0.4], "trait_correlation": -0.9}
    )
    assert two["spec"]["trait_correlation"] == -0.9
    # +1 is the other singular boundary: two traits with identical genetics.
    # Valid, and measured to realise exactly 1.000 in the founders.
    identical = _call(
        srv, "found_population", {**SMALL, "h2": [0.4, 0.4], "trait_correlation": 1.0}
    )
    assert identical["spec"]["trait_correlation"] == 1.0


# --------------------------------------------------------------------------
# M3 / M4: sizes and seeds R cannot use
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("args", "reason"),
    [
        ({"n_qtl_per_chr": 0}, r"n_qtl_per_chr must be >= 1, got 0"),
        ({"n_qtl_per_chr": -3}, r"n_qtl_per_chr must be >= 1, got -3"),
        # No SNP chip: this was only checked when one was asked for.
        ({"n_qtl_per_chr": 80}, r"n_qtl_per_chr=80 exceeds seg_sites=50"),
        ({"seed": 2**40}, r"seed=1,099,511,627,776 is outside the range R accepts"),
        ({"seed": -(2**31)}, r"outside the range R accepts"),
    ],
)
def test_founding_inputs_r_cannot_run_are_refused_with_a_reason(args, reason):
    srv = server.build_server()
    with pytest.raises(ToolError, match=reason):
        _call(srv, "found_population", {**SMALL, **args})
    # Positive control: the extremes that ARE valid go through.
    ok = _call(
        srv,
        "found_population",
        {**SMALL, "n_qtl_per_chr": SMALL["seg_sites"], "seed": 2**31 - 1},
    )
    assert ok["spec"]["n_qtl_per_chr"] == SMALL["seg_sites"]


def test_zero_qtl_no_longer_founds_a_session_that_cannot_run():
    """n_qtl_per_chr=0 used to SUCCEED, and every run_program on the session then
    died in R with "selection trait has missing values"."""
    srv = server.build_server()
    with pytest.raises(ToolError, match="n_qtl_per_chr must be >= 1"):
        _call(srv, "found_population", {**SMALL, "n_qtl_per_chr": 0})
    sid = _call(srv, "found_population", {**SMALL, "n_qtl_per_chr": 1})["session_id"]
    out = _call(srv, "run_program", {"session_id": sid, "cycles": 1, "replicates": 5})
    assert out["cycles"][0]["genetic_gain"]["n"] == 5


@pytest.mark.parametrize(
    ("args", "reason"),
    [
        ({"n_select": 1}, r"n_select must be >= 2, got 1"),
        ({"base_seed": 2**31}, r"base_seed=2,147,483,648 with 5 replicates"),
        # The FIRST seed fits; the fifth replicate's (base_seed + 4) does not.
        ({"base_seed": 2**31 - 3}, r"seeds 2,147,483,645\.\.2,147,483,649"),
    ],
)
def test_run_inputs_r_cannot_run_are_refused_with_a_reason(args, reason):
    srv = server.build_server()
    sid = _call(srv, "found_population", SMALL)["session_id"]
    base = {"session_id": sid, "cycles": 1, "replicates": 5}
    with pytest.raises(ToolError, match=reason):
        _call(srv, "run_program", {**base, **args})
    with pytest.raises(ToolError, match=reason):
        _call(
            srv,
            "compare_programs",
            {
                "session_id": sid,
                "cycles": 1,
                "replicates": 5,
                **{("a_" + k if k == "n_select" else k): v for k, v in args.items()},
            },
        )
    # Positive control: the smallest valid n_select, and the largest base_seed
    # whose whole run of replicate seeds fits.
    ok = _call(srv, "run_program", {**base, "n_select": 2, "base_seed": 2**31 - 1 - 4})
    assert ok["cycles"][0]["genetic_gain"]["n"] == 5


# --------------------------------------------------------------------------
# The class: any R error nobody wrote a check for
# --------------------------------------------------------------------------


def test_an_unanticipated_r_error_reaches_the_caller_with_rs_message():
    """The input checks above cover the known cases; this covers the class. An R
    stop() used to escape `_REFUSALS` as rpy2's RRuntimeError and be masked."""

    @server._surfaces_refusals
    def r_stops():
        return engine.r_eval('stop("sentinel-4f1c: not enough eligible sites")')

    @server._surfaces_refusals
    def r_runs():
        return engine.r_eval("1 + 1")

    with pytest.raises(ToolError, match="sentinel-4f1c: not enough eligible sites"):
        r_stops()
    assert r_runs()[0] == 2
    # A genuine Python bug is still masked: the boundary did not become a
    # catch-all on the way.
    with pytest.raises(TypeError):
        server._surfaces_refusals(lambda: None + 1)()


# --------------------------------------------------------------------------
# L5: failed calls must not leave R objects behind
# --------------------------------------------------------------------------


def _stop_before(real, marker):
    """An r_eval that makes R stop() on the line containing `marker`.

    Every input known to fail in R is now refused before R sees it, so a
    mid-call R failure has to be provoked. The lines BEFORE the marker still
    run, which is the point: they are the assignments a failure used to strand.
    """

    def r_eval(code):
        if marker not in code:
            return real(code)
        lines = code.split("\n")
        at = next(i for i, line in enumerate(lines) if marker in line)
        lines.insert(at, 'stop("sentinel-leak: provoked failure")')
        return real("\n".join(lines))

    return r_eval


def test_failed_calls_leave_no_r_objects_behind(monkeypatch):
    # Imported here, NOT at module top: a module-level `import rpy2` sorts above
    # `breedsim_mcp`, so if this file is collected first rpy2 loads before
    # engine pins OMP_NUM_THREADS and every seeded run in the session stops
    # reproducing (seen: the golden-value test in test_multi_trait failed).
    from rpy2.rinterface_lib.embedded import RRuntimeError

    from breedsim_mcp import founding, program
    from breedsim_mcp.replication import run_program

    # Caught by what either version of the package raises for an R stop(), so
    # that on the old code this fails on the LEAK assertion it exists for, not
    # on the type of the exception.
    r_failure = (engine.EngineError, RRuntimeError)

    store = SessionStore()
    s = found_population(store, **SMALL)
    # Positive control first: a successful run leaves nothing new behind, and
    # the session's own objects are still there to run again.
    run_program(store, s.session_id, cycles=1, replicates=5)
    before = _bs_objects()
    run_program(store, s.session_id, cycles=1, replicates=5)
    assert _bs_objects() == before, sorted(_bs_objects() - before)

    # Founding that fails after the founders and SimParam were assigned. Before,
    # they survived under a prefix no session owned, so nothing could free them.
    monkeypatch.setattr(founding, "r_eval", _stop_before(engine.r_eval, "addTraitA"))
    with pytest.raises(r_failure, match="sentinel-leak"):
        found_population(store, **SMALL)
    monkeypatch.undo()
    assert _bs_objects() == before, sorted(_bs_objects() - before)

    # A replicate that fails after selecting, before crossing.
    monkeypatch.setattr(program, "r_eval", _stop_before(engine.r_eval, "randCross"))
    with pytest.raises(r_failure, match="sentinel-leak"):
        run_program(store, s.session_id, cycles=1, replicates=5)
    monkeypatch.undo()
    assert _bs_objects() == before, sorted(_bs_objects() - before)

    # And the session is intact after both failures.
    out = run_program(store, s.session_id, cycles=1, replicates=5)
    assert out["cycles"][0]["genetic_gain"]["n"] == 5
