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
from breedsim_mcp.founding import RUNMACS_RNG_NOTE, found_population
from breedsim_mcp.replication import MIN_REPLICATES, run_program
from breedsim_mcp.server import INSTRUCTIONS, build_server
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


def test_agent_facing_text_derives_from_one_source():
    """Every surface that explains runMacs must interpolate RUNMACS_RNG_NOTE.

    This is not a style rule. The fact was hand-restated in four places; when the
    original overstatement ("runMacs ignores set.seed") was corrected in
    founding.py, server.py kept shipping the false version -- including in
    INSTRUCTIONS, which is the text an agent reads to decide how to drive the
    engine. A grep for the bad string would only ever catch that one wording, so
    this asserts the invariant instead: the surfaces derive, they do not paraphrase.

    It also catches the opposite failure. Interpolation is easy to break silently:
    ruff strips an `f` prefix from a string that has no placeholder yet, so adding
    the prefix before the placeholder leaves a literal "{RUNMACS_RNG_NOTE}" in the
    prompt. Both directions are checked.
    """
    guidance = asyncio.run(build_server().call_tool("list_methods", {}))
    guidance = guidance[1] if isinstance(guidance, tuple) else guidance
    store = SessionStore()
    reason = found_population(store, generator="runMacs", seed=3, **SMALL).reason

    surfaces = {
        "INSTRUCTIONS": INSTRUCTIONS,
        "list_methods.guidance": guidance["guidance"],
        "session.reason": reason,
    }
    for name, text in surfaces.items():
        assert RUNMACS_RNG_NOTE in text, f"{name} paraphrases instead of deriving"
        assert "{RUNMACS" not in text, f"{name} leaked an uninterpolated placeholder"

    # Positive control: the assertion can fail. A surface that never mentions
    # runMacs must NOT contain the note, or the check above would pass on anything.
    assert RUNMACS_RNG_NOTE not in build_server().name


def test_species_is_validated_not_passed_through():
    """An unknown species must be refused here, not interpolated into R.

    It used to reach AlphaSimR unchecked. Both halves are asserted in one test:
    the bad value raises, and a legitimate one still works — otherwise a
    validator that rejected everything would look identical to a working one.
    """
    store = SessionStore()

    with pytest.raises(ValueError, match="Unknown species"):
        found_population(store, generator="quickHaplo", seed=1, species="MAZE", **SMALL)

    # Positive control, same test: the valid path is untouched.
    s = found_population(
        store, generator="quickHaplo", seed=1, species="WHEAT", **SMALL
    )
    assert s.session_id

    # AlphaSimR upper-cases species itself, so casing must not decide validity.
    lower = found_population(
        store, generator="quickHaplo", seed=1, species="wheat", **SMALL
    )
    assert lower.session_id


def test_cattle_is_accepted_because_this_is_not_plant_only():
    """CATTLE is one of runMacs' four histories, so it must be allowed.

    Pinned deliberately: the repo's metadata reads plant-first, and a future
    tightening to plants-only should have to delete this test on purpose rather
    than discover the restriction by accident.
    """
    store = SessionStore()
    s = found_population(
        store, generator="quickHaplo", seed=1, species="CATTLE", **SMALL
    )
    assert s.session_id
