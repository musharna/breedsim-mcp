"""The server must survive more than one tool call.

This file exists because the whole 27-test suite passed while the server was
broken for every real client after its first request.

rpy2 publishes its conversion rules into a `contextvars.ContextVar` at IMPORT
time, so whichever context performs the import owns them. `engine._rpy2()` used
to import lazily, on first use — which, in a real server, is inside a request.
The rules landed in that request's context and were discarded when it returned,
so the second tool call raised "Conversion rules for `rpy2.robjects` appear to be
missing".

Why nothing caught it: the existing tests call the library directly, which imports
rpy2 in the pytest process's root context before any tool call. That masks the bug
completely. A test in this process therefore proves nothing — it has to be a fresh
process that touches R ONLY through the MCP tool layer, which is the layer the bug
lived in and the only layer a client uses.
"""

import os
import subprocess
import sys

# Drive every tool in order, through call_tool and nothing else. Any direct
# library call here would re-mask the bug this script exists to expose.
DRIVER = """
import asyncio, sys
from breedsim_mcp.server import build_server

srv = build_server()

def call(name, args):
    out = asyncio.run(srv.call_tool(name, args))
    return out[1] if isinstance(out, tuple) else out

call("list_methods", {})
s = call("found_population", {"generator": "quickHaplo", "seed": 1, "n_ind": 20,
                              "n_chr": 2, "seg_sites": 20, "n_qtl_per_chr": 3,
                              "h2": 0.4})
r = call("run_program", {"session_id": s["session_id"], "cycles": 1, "replicates": 5})
call("describe_session", {"session_id": s["session_id"]})

assert r["cycles"][0]["genetic_gain"]["n"] == 5
print("SEQUENCE_OK")
"""


def _run(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,  # a non-zero exit is the failure mode under test, not an error
        env={**os.environ},
    )


def test_four_tool_calls_in_one_fresh_process():
    """Four sequential tool calls must all succeed in a process that has never
    touched R outside the tool layer.

    Before the fix this reached call 2 and stopped."""
    proc = _run(DRIVER)
    assert "SEQUENCE_OK" in proc.stdout, (
        "the tool layer could not complete four sequential calls.\n"
        f"stdout:\n{proc.stdout}\n\nstderr:\n{proc.stderr[-3000:]}"
    )


def test_the_driver_can_actually_fail():
    """Positive control for the harness above.

    `_run` asserting on stdout is only meaningful if a broken server actually
    withholds SEQUENCE_OK. A subprocess that dies for an unrelated reason —
    missing R, a bad path, an import error — would otherwise read identically to
    a passing one, and this file would be decoration.
    """
    proc = _run(DRIVER.replace('call("list_methods", {})', 'raise SystemExit("boom")'))
    assert "SEQUENCE_OK" not in proc.stdout
    assert proc.returncode != 0
