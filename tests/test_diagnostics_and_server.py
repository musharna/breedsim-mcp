"""Warnings and the MCP surface.

Every warning test pairs the firing case with a non-firing positive control in the
same function, so an always-fires bug cannot masquerade as detection.
"""

import asyncio

import pytest

from breedsim_mcp.diagnostics import (
    nondeterministic_founders_warning,
    replicates_too_few_warning,
    threads_not_pinned_warning,
    variance_exhausted_warning,
)
from breedsim_mcp.founding import found_population
from breedsim_mcp.replication import MIN_REPLICATES, run_program
from breedsim_mcp.server import build_server
from breedsim_mcp.session import SessionStore

SMALL = {"n_ind": 40, "n_chr": 4, "seg_sites": 40, "n_qtl_per_chr": 5, "h2": 0.4}


# --------------------------------------------------------------------------
# warnings
# --------------------------------------------------------------------------


def test_nondeterministic_founders_fires_for_runmacs_only():
    store = SessionStore()
    macs = found_population(store, generator="runMacs", seed=1, **SMALL)
    quick = found_population(store, generator="quickHaplo", seed=1, **SMALL)

    assert nondeterministic_founders_warning(macs) is not None
    assert nondeterministic_founders_warning(quick) is None


def test_threads_not_pinned_fires_only_when_unpinned():
    assert threads_not_pinned_warning(pinned=False) is not None
    assert threads_not_pinned_warning(pinned=True) is None
    w = threads_not_pinned_warning(pinned=False)
    assert "OMP_NUM_THREADS" in w.message, "the warning must name the fix"


def test_replicates_too_few_compares_ci_width_to_the_effect():
    """Wide relative to the effect fires; narrow does not."""
    wide = {"mean": 1.0, "ci_low": 0.2, "ci_high": 1.8, "sd": 0.5, "n": 5}
    narrow = {"mean": 1.0, "ci_low": 0.95, "ci_high": 1.05, "sd": 0.05, "n": 30}
    assert replicates_too_few_warning(wide) is not None
    assert replicates_too_few_warning(narrow) is None


def test_variance_exhausted_fires_on_collapse_only():
    collapsed = [{"mean": 0.80}, {"mean": 0.30}, {"mean": 0.03}]
    healthy = [{"mean": 0.80}, {"mean": 0.75}, {"mean": 0.70}]
    assert variance_exhausted_warning(collapsed) is not None
    assert variance_exhausted_warning(healthy) is None


# --------------------------------------------------------------------------
# MCP surface
# --------------------------------------------------------------------------


def test_server_registers_exactly_the_expected_tools():
    tools = asyncio.run(build_server().list_tools())
    assert {t.name for t in tools} == {
        "list_methods",
        "found_population",
        "run_program",
        "describe_session",
    }


def test_every_tool_has_title_and_readonly_annotations():
    for t in asyncio.run(build_server().list_tools()):
        assert t.title, f"{t.name} has no title"
        assert t.annotations is not None, f"{t.name} has no annotations"
        assert t.annotations.readOnlyHint is True, f"{t.name} not read-only"
        assert t.annotations.openWorldHint is False, f"{t.name} not closed-world"


def test_every_tool_publishes_an_output_schema():
    """Asserts the RULE for every tool, not a named list — a new tool added with a
    bare `-> dict` must fail this without anyone remembering to update it."""
    for t in asyncio.run(build_server().list_tools()):
        assert t.outputSchema is not None, (
            f"{t.name} publishes no outputSchema — annotate its return with a "
            "TypedDict from typing_extensions"
        )


def test_server_instructions_state_the_rule():
    s = build_server()
    assert s.instructions
    text = s.instructions.lower()
    assert "distribution" in text or "replicate" in text
    assert "reproducib" in text


def test_run_program_over_the_real_mcp_layer_returns_a_distribution():
    server = build_server()
    found = asyncio.run(
        server.call_tool(
            "found_population",
            {
                "generator": "quickHaplo",
                "seed": 1,
                "n_ind": 40,
                "n_chr": 4,
                "seg_sites": 40,
                "n_qtl_per_chr": 5,
                "h2": 0.4,
            },
        )
    )
    payload = found[1] if isinstance(found, tuple) else found
    assert payload["reproducible"] is True
    sid = payload["session_id"]

    out = asyncio.run(
        server.call_tool(
            "run_program",
            {"session_id": sid, "cycles": 2, "replicates": MIN_REPLICATES},
        )
    )
    res = out[1] if isinstance(out, tuple) else out
    assert res["replicates"] == MIN_REPLICATES
    gain = res["cycles"][0]["genetic_gain"]
    assert {"mean", "sd", "ci_low", "ci_high"} <= set(gain)


def test_single_replicate_is_refused_through_the_tool_layer():
    """The structural rule must hold at the SERVER boundary, not just in the
    library — that is the layer a caller actually touches."""
    server = build_server()
    found = asyncio.run(
        server.call_tool(
            "found_population",
            {
                "generator": "quickHaplo",
                "seed": 2,
                "n_ind": 40,
                "n_chr": 4,
                "seg_sites": 40,
                "n_qtl_per_chr": 5,
                "h2": 0.4,
            },
        )
    )
    payload = found[1] if isinstance(found, tuple) else found
    with pytest.raises(Exception, match="replicates"):
        asyncio.run(
            server.call_tool(
                "run_program",
                {"session_id": payload["session_id"], "cycles": 1, "replicates": 1},
            )
        )


def test_store_is_shared_between_tools():
    """found_population and run_program must see the same store, or every session
    would be unknown to the tool that needs it."""
    store = SessionStore()
    s = found_population(store, generator="quickHaplo", seed=9, **SMALL)
    out = run_program(store, s.session_id, cycles=1, replicates=MIN_REPLICATES)
    assert out["session_id"] == s.session_id
