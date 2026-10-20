"""The token cost of the MCP surface: short instructions, rounded floats, final_only.

The 2026-10-17 agent benchmark found the server arm cost 1.8x the Bash arm per
answer, and 86% of that gap was cache writes: about 1,100 tokens of server
instructions written again every conversation (Claude Code places them after
the question, outside the cached prefix) and tool results that printed every
float as a 17-digit double. Each test here pairs the property with a positive
control on the same call, so a check that passed on anything would fail.
"""

from __future__ import annotations

import asyncio
import json
import math

from breedsim_mcp.founding import found_population
from breedsim_mcp.replication import MIN_REPLICATES, run_program
from breedsim_mcp.server import INSTRUCTIONS, SIG_FIGS, build_server
from breedsim_mcp.session import SessionStore

FOUND = {"generator": "quickHaplo", "seed": 7, "n_ind": 40, "n_chr": 4,
         "seg_sites": 40, "n_qtl_per_chr": 5, "h2": 0.4}  # fmt: skip
RUN = {"cycles": 3, "replicates": MIN_REPLICATES, "n_select": 8, "base_seed": 50}


def _call(srv, name: str, args: dict):
    res = asyncio.run(srv.call_tool(name, args))
    assert not res.is_error, res.content
    return res


def _floats(obj):
    if isinstance(obj, float):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _floats(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _floats(v)


def _sig_figs(x: float) -> int:
    """Significant figures in the shortest repr of x."""
    digits = repr(abs(x)).split("e")[0].replace(".", "").lstrip("0")
    return len(digits.rstrip("0")) or 1


def test_instructions_stay_short_and_still_name_the_workflow():
    """The 0.5.1 instructions were 3,106 characters, about 1,100 tokens written
    to the cache on every conversation. The workflow must survive the cut."""
    assert len(INSTRUCTIONS) <= 400, len(INSTRUCTIONS)
    for tool in ("found_population", "run_program", "compare_programs"):
        assert tool in INSTRUCTIONS, tool
    # The model copies tool names from this text, and Claude Code refuses a
    # call by the bare name (plantcv-mcp's 10-18 sweep: 23 of 138 runs). So the
    # prefix note must come before the first tool the text names.
    first_tool = min(
        INSTRUCTIONS.index(t)
        for t in ("found_population", "run_program", "compare_programs")
        if t in INSTRUCTIONS
    )
    assert 0 <= INSTRUCTIONS.find("mcp__breedsim__") < first_tool
    # Positive control: the guidance that left the instructions now lives in
    # the tool descriptions, which sit in the cached prefix.
    tools = {t.name: t.description for t in asyncio.run(build_server().list_tools())}
    assert "compare_programs, not run_program twice" in tools["run_program"]
    assert "has_linkage_disequilibrium" in tools["found_population"]
    assert "favours" in tools["compare_programs"]


def test_every_float_a_tool_returns_has_at_most_four_significant_figures():
    srv = build_server()
    sid = _call(srv, "found_population", FOUND).structured_content["session_id"]
    res = _call(srv, "run_program", {"session_id": sid, **RUN})
    out = res.structured_content
    floats = list(_floats(out))
    assert len(floats) >= 3 * 2 * 4, "expected mean/sd/ci floats for every cycle"
    assert max(_sig_figs(x) for x in floats) <= SIG_FIGS
    # What the model reads is the text block; it must be the same rounded JSON.
    assert json.loads(res.content[0].text) == out

    # Positive control: the library, which does not round, returns more
    # figures, and the tool's mean is that value rounded, not a different one.
    store = SessionStore()
    s = found_population(store, **FOUND)
    lib = run_program(store, s.session_id, **RUN)
    lib_floats = list(_floats(lib))
    assert max(_sig_figs(x) for x in lib_floats) > SIG_FIGS
    for c in range(RUN["cycles"]):
        full = lib["cycles"][c]["genetic_gain"]["mean"]
        got = out["cycles"][c]["genetic_gain"]["mean"]
        assert got == float(f"{full:.{SIG_FIGS}g}")
        assert math.isclose(got, full, rel_tol=5e-4)


def test_final_only_returns_the_last_cycle_with_the_same_numbers_and_warnings():
    srv = build_server()
    sid = _call(srv, "found_population", FOUND).structured_content["session_id"]
    full = _call(srv, "run_program", {"session_id": sid, **RUN}).structured_content
    last = _call(
        srv, "run_program", {"session_id": sid, **RUN, "final_only": True}
    ).structured_content
    # Positive control: the default still reports every cycle.
    assert len(full["cycles"]) == RUN["cycles"]
    assert last["cycles"] == full["cycles"][-1:]
    assert last["warnings"] == full["warnings"]

    cmp = {"session_id": sid, "cycles": 3, "replicates": MIN_REPLICATES,
           "a_n_select": 4, "b_n_select": 20, "base_seed": 50}  # fmt: skip
    c_full = _call(srv, "compare_programs", cmp).structured_content
    c_last = _call(
        srv, "compare_programs", {**cmp, "final_only": True}
    ).structured_content
    assert len(c_full["cycles"]) == 3
    assert c_last["cycles"] == c_full["cycles"][-1:]
    for k in ("favours", "difference_is", "intervals_overlap", "warnings"):
        assert c_last[k] == c_full[k], k
