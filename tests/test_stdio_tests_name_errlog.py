"""A test that starts the server over stdio says where the server's stderr goes.

`mcp.client.stdio.stdio_client(server, errlog=sys.stderr)` takes that default
once, when `mcp.client.stdio` is first imported. Under pytest, `sys.stderr` at
that moment is the capture file of the session doing the import, and pytest
closes it when the session ends. A second pytest session in the same process
then hands the closed file to `subprocess.Popen`, which raises "ValueError: I/O
operation on closed file" before the server starts. mutmut runs the suite twice
in one process (once to collect stats, once as its clean run), so one bare call
stopped the nightly mutation job before it checked a single mutant.

Passing `errlog=sys.stderr` at the call reads `sys.stderr` when the test runs,
which is the live session's file. This scan keeps every call doing so.
"""

from __future__ import annotations

import ast
from pathlib import Path

TESTS = Path(__file__).parent


def _stdio_client_calls(source: str) -> tuple[int, list[int]]:
    """(number of stdio_client calls, lines of those that leave errlog out)."""
    calls = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", getattr(node.func, "attr", None)) == "stdio_client"
    ]
    bare = [c.lineno for c in calls if not any(kw.arg == "errlog" for kw in c.keywords)]
    return len(calls), bare


def test_every_stdio_client_call_in_the_tests_names_errlog():
    # Controls: the scan flags a bare call, by name or by attribute, and
    # accepts one that names errlog.
    assert _stdio_client_calls("stdio_client(p)") == (1, [1])
    assert _stdio_client_calls("x = 1\nmcp.client.stdio.stdio_client(p)") == (1, [2])
    assert _stdio_client_calls("stdio_client(p, errlog=sys.stderr)") == (1, [])

    total = 0
    bare = []
    for path in sorted(TESTS.rglob("*.py")):
        n, lines = _stdio_client_calls(path.read_text())
        total += n
        bare += [f"{path.relative_to(TESTS)}:{line}" for line in lines]
    # The suite drives a real stdio server in two places; a scan that finds
    # fewer is not looking at the tests.
    assert total >= 2, total
    assert not bare, f"stdio_client called without errlog=: {bare}"
