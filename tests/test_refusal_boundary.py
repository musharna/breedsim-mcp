"""Every tool must reach the model through the refusal boundary.

Since mcp 2.1 (python-sdk #3314) MCPServer masks any exception other than
`ToolError`: the caller gets `Error executing tool <name>` and the reason stays
in the server log. `server._surfaces_refusals` converts this server's
anticipated refusals at that boundary so their text survives.

`test_diagnostics_and_server` asserts the text of ONE refusal from ONE tool.
That pins the instance -- it passes unchanged on the day a sixth tool is
registered without the wrapper, or a seventh exception class is raised that
`_REFUSALS` does not name. Both are the original bug returning with nothing red.
These pin the class.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil

import pytest
from mcp.server.mcpserver.exceptions import ToolError

import breedsim_mcp
from breedsim_mcp import server


def _boundary_code():
    """The code object of the wrapper `_surfaces_refusals` returns.

    Every wrapper it builds shares one code object, so identity against it tests
    exactly "this callable came out of that boundary". `hasattr(fn, "__wrapped__")`
    would also be satisfied by any unrelated functools.wraps decorator, and
    matching on `__name__` by nothing at all -- functools.wraps copies the
    wrapped function's name onto the wrapper.
    """
    return server._surfaces_refusals(lambda: None).__code__


def _registered_tools():
    tools = server.build_server()._tool_manager.list_tools()
    assert tools, "no tools registered -- this guard would otherwise pass vacuously"
    return tools


def _package_exception_classes():
    """Every exception class this package defines, by walking its modules.

    Enumerated rather than listed, because a hand-kept list is exactly the thing
    that goes stale when the seventh class is added.
    """
    found = {}
    for mod in pkgutil.walk_packages(
        breedsim_mcp.__path__, prefix=f"{breedsim_mcp.__name__}."
    ):
        module = importlib.import_module(mod.name)
        for name, obj in vars(module).items():
            if (
                inspect.isclass(obj)
                and issubclass(obj, BaseException)
                and obj.__module__ == mod.name
            ):
                found[obj] = f"{mod.name}.{name}"
    assert found, "found no exception classes -- the walk is broken, not the package"
    return found


def test_every_registered_tool_passes_through_the_refusal_boundary():
    expected = _boundary_code()
    unguarded = sorted(
        t.name
        for t in _registered_tools()
        if getattr(t.fn, "__code__", None) is not expected
    )
    assert not unguarded, (
        f"{unguarded} are registered without @_surfaces_refusals, so a refusal "
        "from them reaches the model as `Error executing tool <name>` with the "
        "reason dropped. Add the decorator under @mcp.tool in build_server()."
    )


def test_every_exception_this_package_raises_is_one_the_boundary_recognises():
    """A class outside `_REFUSALS` is masked, however deliberate the message.

    Names starting with an underscore are exempt: those are internal control
    flow, caught inside the module that defines them, and never intended to
    reach a caller.
    """
    unrecognised = sorted(
        where
        for cls, where in _package_exception_classes().items()
        if not cls.__name__.startswith("_") and not issubclass(cls, server._REFUSALS)
    )
    assert not unrecognised, (
        f"{unrecognised} are not covered by server._REFUSALS, so raising one "
        "from a tool reaches the model as `Error executing tool <name>` with "
        "its message dropped. Add it to _REFUSALS, or make it private and "
        "catch it in the module that defines it."
    )


def test_the_boundary_converts_a_refusal_and_leaves_a_real_bug_masked():
    """The negative assertion needs the positive one beside it.

    A boundary that converted every exception would satisfy the refusal half
    while destroying the SDK's crash signal, so both directions are asserted in
    one test rather than trusting a broken harness to look like a pass.
    """

    @server._surfaces_refusals
    def refuses():
        raise ValueError("at least 10 replicates are needed")

    @server._surfaces_refusals
    def crashes():
        raise TypeError("this is a bug, not a refusal")

    with pytest.raises(ToolError, match="10 replicates"):
        refuses()

    with pytest.raises(TypeError):
        crashes()
