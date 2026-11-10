"""Overlapping tool calls on one real stdio server give the answers they give alone.

MCPServer runs every synchronous tool on a worker thread, and it starts each
request as its own task, so two calls in flight at once run at the same time
against the ONE embedded R. A replicate is many R evaluations in a row: it seeds
R's single global RNG, then keeps drawing from it, and keeps its scratch
population under a name derived from the session. Before tool calls were
serialised, two overlapping `run_program` calls drew from each other's RNG
stream and returned different numbers with `reproducible: true` and no warning,
and two on the same session freed each other's scratch population, so one died
with R's "object '.bs_..._pop' not found".

This test drives the real server process over stdio, the way a client does. It
records each call's answer alone, checks that a sequential repeat is identical
(the positive control: if that fails, the comparison below means nothing), then
issues the calls in overlapping pairs and requires the identical answer.
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Large enough that each run lasts long enough for two to overlap many times,
# small enough to keep the test to tens of seconds.
FOUND = {"n_ind": 150, "n_chr": 4, "seg_sites": 100, "n_qtl_per_chr": 10}
RUN = {"cycles": 4, "replicates": 8, "base_seed": 1}
# Wall-clock ceiling for the whole conversation. A hang must fail, not block CI.
TIMEOUT_S = 600


def _answer(result) -> dict:
    """The comparable part of a tool result; a tool error is a test failure."""
    assert not result.is_error, result.content[0].text
    out = dict(result.structured_content)
    # found_population mints a fresh id each time; everything else must match.
    out.pop("session_id", None)
    return out


async def _conversation() -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-c", "from breedsim_mcp.server import main; main()"],
        # conftest has already put the AlphaSimR library on R_LIBS_USER.
        env=dict(os.environ),
    )
    async with (
        stdio_client(params) as (read, write),
        ClientSession(read, write) as s,
    ):
        await s.initialize()

        async def call(tool: str, args: dict) -> dict:
            return _answer(await s.call_tool(tool, args))

        s1 = await s.call_tool("found_population", {**FOUND, "seed": 7})
        s2 = await s.call_tool("found_population", {**FOUND, "seed": 8})
        sid1 = s1.structured_content["session_id"]
        sid2 = s2.structured_content["session_id"]

        a = {**RUN, "session_id": sid1, "n_select": 20}
        b = {**RUN, "session_id": sid1, "n_select": 60}  # same session as a
        c = {**RUN, "session_id": sid2, "n_select": 60}  # other session
        cmp_args = {**RUN, "session_id": sid2, "a_n_select": 10, "b_n_select": 40}
        found9 = {**FOUND, "seed": 9}

        alone = {
            "a": await call("run_program", a),
            "b": await call("run_program", b),
            "c": await call("run_program", c),
            "cmp": await call("compare_programs", cmp_args),
            "found9": await call("found_population", found9),
        }

        # Positive control: the same call again, in sequence, is identical.
        # Without it a server that is merely nondeterministic would make
        # every comparison below fail for a reason unrelated to overlap.
        assert await call("run_program", a) == alone["a"]
        assert await call("compare_programs", cmp_args) == alone["cmp"]

        pairs = [
            ("same session", ("run_program", a, "a"), ("run_program", b, "b")),
            ("two sessions", ("run_program", a, "a"), ("run_program", c, "c")),
            (
                "run beside compare",
                ("run_program", a, "a"),
                ("compare_programs", cmp_args, "cmp"),
            ),
            (
                "run beside founding",
                ("run_program", c, "c"),
                ("found_population", found9, "found9"),
            ),
        ]
        mismatches = []
        for label, (t1, args1, k1), (t2, args2, k2) in pairs:
            got1, got2 = await asyncio.gather(
                s.call_tool(t1, args1), s.call_tool(t2, args2)
            )
            for key, got in ((k1, got1), (k2, got2)):
                if got.is_error:
                    mismatches.append(f"{label}: {key} errored: {got.content[0].text}")
                elif _answer(got) != alone[key]:
                    mismatches.append(
                        f"{label}: {key} differs from its solo answer\n"
                        f"  alone:      {alone[key].get('cycles')}\n"
                        f"  overlapped: {got.structured_content.get('cycles')}"
                    )
        assert not mismatches, "\n".join(mismatches)


@pytest.mark.filterwarnings("ignore::ResourceWarning")
def test_overlapping_calls_over_stdio_give_their_solo_answers():
    asyncio.run(asyncio.wait_for(_conversation(), TIMEOUT_S))


def test_every_registered_tool_holds_the_r_lock():
    """The stdio test exercises three tools; this pins the class, so a sixth tool
    registered without the lock fails here rather than in production."""
    from breedsim_mcp import server

    lock_code = server._one_call_in_r_at_a_time(lambda: None).__code__

    def holds_lock(fn) -> bool:
        while fn is not None:
            if getattr(fn, "__code__", None) is lock_code:
                return True
            fn = getattr(fn, "__wrapped__", None)
        return False

    tools = server.build_server()._tool_manager.list_tools()
    assert len(tools) == 5, [t.name for t in tools]
    # Control: the walk can see the wrapper at all.
    assert holds_lock(server._one_call_in_r_at_a_time(lambda: None))
    unlocked = sorted(t.name for t in tools if not holds_lock(t.fn))
    assert not unlocked, f"{unlocked} run without engine.R_LOCK"
