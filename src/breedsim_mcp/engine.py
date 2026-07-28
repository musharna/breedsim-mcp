"""R engine bootstrap: thread pinning, dependency detection, R evaluation.

**Import this module before anything imports rpy2.** R reads OMP_NUM_THREADS when
OpenMP initialises, so setting it afterwards is a silent no-op. Measured: with
founders held fixed, a pinned process reproduces `meanG=2.01451853` from seed 7
twice, while an unpinned one gives 2.397 then 2.125.

rpy2 is deliberately NOT imported at module level. If it were, ruff's import
sorter would hoist it above the environment assignment below and quietly destroy
the guarantee this module exists to provide. It is imported lazily instead, so the
ordering cannot be refactored away by a formatter.
"""

import os
import sys
from dataclasses import dataclass

# Recorded BEFORE we touch anything: if rpy2 is already loaded then R may already
# have initialised OpenMP, and our pin below arrived too late to matter.
RPY2_PREIMPORTED: bool = "rpy2" in sys.modules

# setdefault, not assignment: a caller who deliberately sets OMP_NUM_THREADS=8 to
# trade reproducibility for speed is making a legitimate choice. We record that
# they did (threads_are_pinned() -> False) rather than overriding them.
os.environ.setdefault("OMP_NUM_THREADS", "1")


class EngineError(Exception):
    """Base for engine problems."""


class MissingDependencyError(EngineError):
    """A required piece of the R stack is absent, named explicitly."""

    @classmethod
    def for_r_package(cls, package: str) -> "MissingDependencyError":
        return cls(
            f"The R package {package!r} is required but was not found on R's "
            f"library path. Install it with:\n\n"
            f'    R -e \'install.packages("{package}", repos="https://cloud.r-project.org")\'\n\n'
            "This server never installs R packages for you: doing so mutates your "
            "system as a side effect, takes minutes, and can fail halfway."
        )

    @classmethod
    def for_r(cls) -> "MissingDependencyError":
        return cls(
            "R could not be initialised. breedsim-mcp needs R >= 4.3 with a shared "
            "library (libR.so). On Debian/Ubuntu:\n\n"
            "    sudo apt-get install -y r-base libtirpc-dev\n\n"
            "libtirpc-dev is required to build rpy2; without it linking fails with "
            "'cannot find -ltirpc'."
        )


@dataclass(frozen=True)
class EnvironmentReport:
    r_version: str
    alphasimr_version: str | None
    rpy2_version: str
    threads_pinned: bool
    rpy2_preimported: bool
    reproducible: bool
    notes: list[str]


def threads_are_pinned() -> bool:
    """True when OpenMP is limited to one thread.

    This is not cosmetic. With more than one thread the selection path's reduction
    order varies between runs, so the same seed produces different genetic gain.
    """
    return os.environ.get("OMP_NUM_THREADS") == "1"


def _rpy2():
    """Import rpy2 lazily, translating failure into an actionable error."""
    try:
        import rpy2.robjects as ro
    except Exception as exc:  # deliberately blind: any failure here means R is unusable
        raise MissingDependencyError.for_r() from exc
    return ro


def r_eval(code: str):
    """Evaluate R code in the shared session."""
    return _rpy2().r(code)


def require_alphasimr() -> str:
    """Load AlphaSimR, or raise naming it. Returns its version."""
    ro = _rpy2()
    # requireNamespace returns INVISIBLY, and rpy2 3.5 surfaces an invisible
    # result as None. Assigning first forces a visible value we can read.
    ok = ro.r('.bs_ok <- requireNamespace("AlphaSimR", quietly=TRUE); .bs_ok')[0]
    if not ok:
        raise MissingDependencyError.for_r_package("AlphaSimR")
    ro.r("suppressMessages(library(AlphaSimR))")
    return str(ro.r('as.character(packageVersion("AlphaSimR"))')[0])


def check_environment() -> EnvironmentReport:
    """Describe the stack we are actually running on. Never installs anything."""
    import importlib.metadata as md

    ro = _rpy2()
    r_version = str(ro.r("R.version.string")[0])
    try:
        alphasimr = require_alphasimr()
    except MissingDependencyError:
        alphasimr = None

    pinned = threads_are_pinned()
    notes: list[str] = []
    if not pinned:
        notes.append(
            f"OMP_NUM_THREADS is {os.environ.get('OMP_NUM_THREADS')!r}, not '1'. "
            "Selection runs will not reproduce from a seed."
        )
    if RPY2_PREIMPORTED:
        notes.append(
            "rpy2 was imported before breedsim_mcp.engine, so the thread pin may "
            "have arrived after OpenMP initialised. Import breedsim_mcp first."
        )
    if alphasimr is None:
        notes.append("AlphaSimR is not installed; simulation is unavailable.")

    return EnvironmentReport(
        r_version=r_version,
        alphasimr_version=alphasimr,
        rpy2_version=md.version("rpy2"),
        threads_pinned=pinned,
        rpy2_preimported=RPY2_PREIMPORTED,
        reproducible=pinned and not RPY2_PREIMPORTED,
        notes=notes,
    )
