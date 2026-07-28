"""Engine bootstrap: thread pinning and dependency detection.

Thread pinning is tested through SUBPROCESSES rather than in-process, because the
thing under test is import ORDER. R reads OMP_NUM_THREADS when OpenMP initialises;
setting it after rpy2 has loaded is a no-op that would still pass a naive
in-process assertion.
"""

import subprocess
import sys

from breedsim_mcp.engine import (
    MissingDependencyError,
    check_environment,
    threads_are_pinned,
)


def _run(code: str, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    import os

    env = dict(os.environ)
    env.pop("OMP_NUM_THREADS", None)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        timeout=300,
        check=False,  # the tests assert on returncode themselves
    )


def test_importing_engine_pins_threads_before_rpy2_loads():
    """The load-bearing ordering assertion: our module must set OMP_NUM_THREADS
    while rpy2 is still unimported."""
    r = _run(
        "import sys, os\n"
        "import breedsim_mcp.engine as e\n"
        "print('PINNED', os.environ.get('OMP_NUM_THREADS'))\n"
        "print('RPY2_WAS_PREIMPORTED', e.RPY2_PREIMPORTED)\n"
    )
    assert r.returncode == 0, r.stderr
    assert "PINNED 1" in r.stdout, r.stdout
    assert "RPY2_WAS_PREIMPORTED False" in r.stdout, r.stdout


def test_engine_detects_when_rpy2_was_imported_first():
    """Positive control for the guard above: if the pin came too late we must be
    able to SAY so. A guard that cannot detect the bad case is not a guard."""
    r = _run(
        "import rpy2\n"  # rpy2 first — the pin is now too late to affect OpenMP
        "import breedsim_mcp.engine as e\n"
        "print('RPY2_WAS_PREIMPORTED', e.RPY2_PREIMPORTED)\n"
    )
    assert r.returncode == 0, r.stderr
    assert "RPY2_WAS_PREIMPORTED True" in r.stdout, r.stdout


def test_threads_are_pinned_reflects_the_environment():
    assert threads_are_pinned() is True  # our own import pinned it
    import os

    old = os.environ.get("OMP_NUM_THREADS")
    try:
        os.environ["OMP_NUM_THREADS"] = "4"
        assert threads_are_pinned() is False
    finally:
        if old is None:
            os.environ.pop("OMP_NUM_THREADS", None)
        else:
            os.environ["OMP_NUM_THREADS"] = old


def test_check_environment_reports_the_real_stack():
    env = check_environment()
    # r_version is R.version.string verbatim, e.g. "R version 4.3.3 (2024-02-29)".
    assert env.r_version.startswith("R version 4."), env.r_version
    assert env.alphasimr_version is not None
    assert env.rpy2_version.startswith("3.5"), "plan pins rpy2 <3.6 for R 4.3"
    assert env.threads_pinned is True
    assert env.reproducible is True


def test_missing_dependency_error_names_the_missing_piece():
    """A raw RRuntimeError tells a user nothing actionable."""
    err = MissingDependencyError.for_r_package("AlphaSimR")
    assert "AlphaSimR" in str(err)
    assert "install.packages" in str(err), "the error must carry the fix"
