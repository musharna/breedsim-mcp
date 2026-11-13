"""The per-axis ceilings do not bound a founding; the memory budget does.

Each of n_ind, n_chr and seg_sites has its own ceiling, but a founding's memory
grows with their PRODUCT: `_founder_hash` pulls every haplotype value into
Python. Measured at 29-38 bytes per value, the largest founding the ceilings
allowed (5000 x 40 x 5000) extrapolated to 55-71 GiB. These tests pin the
product bound, the message that names the numbers, and the environment knob.
"""

from __future__ import annotations

import pytest

from breedsim_mcp import engine, limits
from breedsim_mcp.founding import found_population
from breedsim_mcp.limits import (
    DEFAULT_FOUNDING_MEMORY_MIB,
    FOUNDING_MEMORY_ENV,
    LIMITS,
    LimitExceededError,
    check_founding_memory,
    founding_memory_budget_mib,
    founding_memory_mib,
)
from breedsim_mcp.session import SessionStore


def _bs_objects() -> set[str]:
    return set(
        engine.r_eval('ls(envir=.GlobalEnv, all.names=TRUE, pattern="^\\\\.bs_")')
    )


def test_a_founding_over_the_budget_is_refused_before_r_and_one_under_it_runs(
    monkeypatch,
):
    """Through found_population itself, with the budget lowered so both sides of
    it are cheap: 200 x 10 x 300 is 1.2 million values, about 46 MiB at 40 B;
    100 x 10 x 100 is 0.2 million, about 8 MiB."""
    monkeypatch.setattr(limits, "FOUNDING_MEMORY_MIB", 16)
    store = SessionStore()
    before = _bs_objects()
    with pytest.raises(LimitExceededError) as refused:
        found_population(store, n_ind=200, n_chr=10, seg_sites=300, n_qtl_per_chr=5)
    message = str(refused.value)
    for named in ("n_ind=200", "n_chr=10", "seg_sites=300", "1,200,000", "16 MiB"):
        assert named in message, (named, message)
    assert FOUNDING_MEMORY_ENV in message
    # Refused before R ran: nothing was assigned under a session prefix.
    assert _bs_objects() == before
    assert len(store) == 0

    # Positive control: under the same lowered budget a smaller founding runs.
    s = found_population(store, n_ind=100, n_chr=10, seg_sites=100, n_qtl_per_chr=5)
    assert s.founder_hash and len(store) == 1


def test_the_default_budget_refuses_the_ceilings_product_and_admits_measured_sizes():
    """Pure arithmetic, no R: the default budget must refuse the combination the
    per-axis ceilings allowed, and must still admit the server's defaults and
    the largest size that was measured to run (1000 x 10 x 1000, 142 s)."""
    with pytest.raises(LimitExceededError, match="haplotype values"):
        check_founding_memory(
            LIMITS["n_ind"],
            LIMITS["n_chr"],
            LIMITS["seg_sites"],
            budget_mib=DEFAULT_FOUNDING_MEMORY_MIB,
        )
    # Hand-computed: 100 x 10 x 100 sites x 2 copies = 200,000 values at 40 B.
    assert founding_memory_mib(100, 10, 100) == pytest.approx(8_000_000 / 1_048_576)
    check_founding_memory(100, 10, 100, budget_mib=DEFAULT_FOUNDING_MEMORY_MIB)
    check_founding_memory(1000, 10, 1000, budget_mib=DEFAULT_FOUNDING_MEMORY_MIB)
    # Each axis at its own ceiling with the others at the defaults also fits:
    # the budget bounds the product, not any one size.
    check_founding_memory(LIMITS["n_ind"], 10, 100, budget_mib=1024)
    check_founding_memory(100, LIMITS["n_chr"], 100, budget_mib=1024)
    check_founding_memory(100, 10, LIMITS["seg_sites"], budget_mib=1024)


def test_the_budget_is_read_from_the_environment_and_a_bad_value_is_refused():
    assert founding_memory_budget_mib({}) == DEFAULT_FOUNDING_MEMORY_MIB
    assert founding_memory_budget_mib({FOUNDING_MEMORY_ENV: ""}) == 1024
    assert founding_memory_budget_mib({FOUNDING_MEMORY_ENV: " 4096 "}) == 4096
    for bad in ("abc", "0", "-5", "1.5"):
        with pytest.raises(ValueError, match="not a positive whole number"):
            founding_memory_budget_mib({FOUNDING_MEMORY_ENV: bad})


def test_the_budget_set_in_a_clients_env_block_reaches_the_server_over_stdio():
    """Real execution: the knob is an environment variable an MCP client sets, so
    drive a real server process with it and read the result back."""
    import asyncio
    import os
    import sys

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def conversation():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-c", "from breedsim_mcp.server import main; main()"],
            env={**os.environ, FOUNDING_MEMORY_ENV: "16"},
        )
        async with (
            # errlog named at call time; see test_stdio_tests_name_errlog.py.
            stdio_client(params, errlog=sys.stderr) as (read, write),
            ClientSession(read, write) as s,
        ):
            await s.initialize()
            methods = await s.call_tool("list_methods", {})
            assert methods.structured_content["limits"]["founding_memory_mib"] == 16
            big = {"n_ind": 200, "n_chr": 10, "seg_sites": 300, "n_qtl_per_chr": 5}
            refused = await s.call_tool("found_population", big)
            assert refused.is_error
            assert "founding budget of 16 MiB" in refused.content[0].text
            small = {**big, "seg_sites": 100}
            ok = await s.call_tool("found_population", small)
            assert not ok.is_error, ok.content[0].text
            assert ok.structured_content["founder_hash"]

    asyncio.run(asyncio.wait_for(conversation(), 300))
