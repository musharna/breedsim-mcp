"""MCP server. Five tools over a session store.

`engine` is imported FIRST and deliberately: it pins OMP_NUM_THREADS before rpy2
loads, and R reads that variable when OpenMP initialises. Import order here is
load-bearing, not incidental.

Tools are synchronous. R is a single interpreter with global state; serialising
calls on the event loop is what keeps concurrent tool invocations from
interleaving inside it.
"""

# isort: off  -- engine MUST come before anything that could pull in rpy2.
from . import engine  # noqa: I001

# isort: on
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from typing_extensions import TypedDict

from .comparison import compare_programs
from .diagnostics import (
    indistinguishable_warning,
    nondeterministic_founders_warning,
    overlap_but_different_warning,
    replicates_too_few_warning,
    threads_not_pinned_warning,
    variance_exhausted_warning,
)
from .founding import GENERATORS, RUNMACS_RNG_NOTE, found_population
from .replication import (
    DEFAULT_REPLICATES,
    MIN_REPLICATES,
    run_program,
)
from .session import SessionStore

_store = SessionStore()

INSTRUCTIONS = f"""\
Breeding-scheme simulation, driving AlphaSimR.

Work in this order: found_population -> run_program, or found_population ->
compare_programs when the question is "which of these two is better".

TO COMPARE TWO PROGRAMMES, USE compare_programs — do not run run_program twice and
compare the means. compare_programs pairs the two arms on the same seeds so the
shared luck cancels, and returns the DIFFERENCE with its own confidence interval.
Read `difference` and `favours`. When `favours` is null the interval contains zero
and the programmes are not distinguishable at that replicate count, so the larger
mean is not the better programme. Two overlapping per-programme intervals do NOT
imply no difference — that is what `overlap_but_different` is telling you.

THIS SERVER DOES NOT RETURN SINGLE RUNS. run_program executes many replicates and
returns, per cycle, the mean, standard deviation and 95% confidence interval of
genetic gain and genetic variance. Measured on this engine, five seeds of one
identical programme gave gains spanning 1.151 to 1.841 — sd 0.247, the same order
as the differences people try to compare. One run is a draw from a distribution,
not an answer, so there is no option to request one.

Read `reproducible` on every response. Two independent things break reproducibility:
founders generated with runMacs ({RUNMACS_RNG_NOTE}), and OpenMP running
multi-threaded. Use generator="quickHaplo" and keep threads pinned if you need a
result someone else can repeat.

Read the `warnings` array. `replicates_too_few` means the interval is too wide to
support the comparison being made. `variance_exhausted` means selection has used up
the usable variation, so a still-rising mean is a plateau rather than progress.\
"""


class SummaryDict(TypedDict):
    mean: float
    sd: float
    ci_low: float
    ci_high: float
    n: int


class CycleDict(TypedDict):
    cycle: int
    genetic_gain: SummaryDict
    genetic_variance: SummaryDict


class WarningDict(TypedDict):
    code: str
    message: str


class FoundResult(TypedDict):
    session_id: str
    generator: str
    seed: int
    founder_hash: str
    reproducible: bool
    reason: str | None
    spec: dict[str, Any]
    warnings: list[WarningDict]


class RunResult(TypedDict):
    session_id: str
    replicates: int
    cycles: list[CycleDict]
    reproducible: bool
    recipe: dict[str, Any]
    warnings: list[WarningDict]


class CompareCycleDict(TypedDict):
    cycle: int
    a_genetic_gain: SummaryDict
    b_genetic_gain: SummaryDict
    difference: SummaryDict


class CompareResult(TypedDict):
    session_id: str
    replicates: int
    paired: bool
    programs: dict[str, Any]
    cycles: list[CompareCycleDict]
    difference_is: str
    # None when the difference interval contains zero. Not a missing value —
    # it is the answer "these are not distinguishable at this replicate count".
    favours: str | None
    intervals_overlap: bool
    reproducible: bool
    recipe: dict[str, Any]
    warnings: list[WarningDict]


class SessionInfo(TypedDict):
    session_id: str
    generator: str
    seed: int
    founder_hash: str
    reproducible: bool
    reason: str | None
    spec: dict[str, Any]
    cycles_run: int


class MethodsInfo(TypedDict):
    r_version: str
    alphasimr_version: str | None
    rpy2_version: str
    generators: list[str]
    min_replicates: int
    default_replicates: int
    threads_pinned: bool
    reproducible: bool
    notes: list[str]
    guidance: str


def _warn_dicts(advisories) -> list[WarningDict]:
    return [{"code": a.code, "message": a.message} for a in advisories if a]


def build_server() -> FastMCP:
    mcp = FastMCP("breedsim-mcp", instructions=INSTRUCTIONS)

    READ_ONLY = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=False,  # each call advances RNG state
        openWorldHint=False,
    )

    @mcp.tool(
        title="List engine capabilities and determinism status", annotations=READ_ONLY
    )
    def list_methods() -> MethodsInfo:
        """Engine versions, available founder generators, replicate floor, and
        whether THIS process is currently able to produce reproducible results."""
        env = engine.check_environment()
        return {
            "r_version": env.r_version,
            "alphasimr_version": env.alphasimr_version,
            "rpy2_version": env.rpy2_version,
            "generators": list(GENERATORS),
            "min_replicates": MIN_REPLICATES,
            "default_replicates": DEFAULT_REPLICATES,
            "threads_pinned": env.threads_pinned,
            "reproducible": env.reproducible,
            "notes": env.notes,
            "guidance": (
                "quickHaplo is reproducible from a seed; runMacs gives realistic "
                f"coalescent linkage disequilibrium but {RUNMACS_RNG_NOTE}. "
                "Results are always distributions across replicates — there is "
                "no single-run mode."
            ),
        }

    @mcp.tool(
        name="found_population",
        title="Create a founder population",
        annotations=READ_ONLY,
    )
    def found_population_tool(
        generator: str = "quickHaplo",
        seed: int = 1,
        n_ind: int = 100,
        n_chr: int = 10,
        seg_sites: int = 100,
        n_qtl_per_chr: int = 10,
        h2: float = 0.4,
        species: str = "MAIZE",
    ) -> FoundResult:
        """Found a population and its trait architecture, and keep it for later runs.

        generator="quickHaplo" is reproducible; "runMacs" is not, and says so in
        `reproducible` and `reason`.

        species only affects "runMacs", which has demographic histories for
        GENERIC, CATTLE, WHEAT and MAIZE — animal breeding as well as plant.
        """
        s = found_population(
            _store,
            generator=generator,
            seed=seed,
            n_ind=n_ind,
            n_chr=n_chr,
            seg_sites=seg_sites,
            n_qtl_per_chr=n_qtl_per_chr,
            h2=h2,
            species=species,
        )
        return {
            "session_id": s.session_id,
            "generator": s.generator,
            "seed": s.seed,
            "founder_hash": s.founder_hash,
            "reproducible": s.reproducible,
            "reason": s.reason,
            "spec": s.spec,
            "warnings": _warn_dicts(
                [
                    nondeterministic_founders_warning(s),
                    threads_not_pinned_warning(engine.threads_are_pinned()),
                ]
            ),
        }

    @mcp.tool(
        name="run_program",
        title="Run a selection programme (returns distributions)",
        annotations=READ_ONLY,
    )
    def run_program_tool(
        session_id: str,
        cycles: int = 3,
        replicates: int = DEFAULT_REPLICATES,
        n_select: int = 10,
        n_cross: int | None = None,
        base_seed: int = 1000,
    ) -> RunResult:
        """Run the programme `replicates` times; return per-cycle mean, sd and 95% CI.

        There is no way to request a single run. Measured spread across seeds was
        sd 0.247 on genetic gain, so one replicate is noise rather than a result.
        """
        out = run_program(
            _store,
            session_id,
            cycles=cycles,
            replicates=replicates,
            n_select=n_select,
            n_cross=n_cross,
            base_seed=base_seed,
        )
        session = _store.get(session_id)
        last_gain = out["cycles"][-1]["genetic_gain"]
        variances = [c["genetic_variance"] for c in out["cycles"]]
        out["warnings"] = _warn_dicts(
            [
                nondeterministic_founders_warning(session),
                threads_not_pinned_warning(engine.threads_are_pinned()),
                replicates_too_few_warning(last_gain),
                variance_exhausted_warning(variances),
            ]
        )
        return out

    @mcp.tool(
        name="compare_programs",
        title="Compare two programmes (paired, returns the difference)",
        annotations=READ_ONLY,
    )
    def compare_programs_tool(
        session_id: str,
        a_n_select: int = 10,
        b_n_select: int = 25,
        cycles: int = 3,
        replicates: int = DEFAULT_REPLICATES,
        a_n_cross: int | None = None,
        b_n_cross: int | None = None,
        base_seed: int = 1000,
        a_label: str = "A",
        b_label: str = "B",
    ) -> CompareResult:
        """Compare two programmes on shared founders using paired seeds.

        Read `difference` and `favours`, NOT the two per-programme means. The
        arms are paired replicate-by-replicate on the same seed, so the shared
        luck cancels and the difference carries its own confidence interval.

        `favours` is null when that interval contains zero — meaning the two
        programmes are not distinguishable at this replicate count. When it is
        null, do not report the larger mean as the better programme.

        Note that two overlapping per-programme intervals do NOT imply no
        difference; `overlap_but_different` fires when the paired difference
        resolves a contrast that the overlap hides.
        """
        out = compare_programs(
            _store,
            session_id,
            a_n_select=a_n_select,
            b_n_select=b_n_select,
            cycles=cycles,
            replicates=replicates,
            a_n_cross=a_n_cross,
            b_n_cross=b_n_cross,
            base_seed=base_seed,
            a_label=a_label,
            b_label=b_label,
        )
        session = _store.get(session_id)
        out["warnings"] = _warn_dicts(
            [
                nondeterministic_founders_warning(session),
                threads_not_pinned_warning(engine.threads_are_pinned()),
                indistinguishable_warning(out),
                overlap_but_different_warning(out),
            ]
        )
        return out

    @mcp.tool(title="Describe a session", annotations=READ_ONLY)
    def describe_session(session_id: str) -> SessionInfo:
        """Founder provenance, trait architecture, cycles run, reproducibility."""
        s = _store.get(session_id)
        return {
            "session_id": s.session_id,
            "generator": s.generator,
            "seed": s.seed,
            "founder_hash": s.founder_hash,
            "reproducible": s.reproducible,
            "reason": s.reason,
            "spec": s.spec,
            "cycles_run": s.cycles_run,
        }

    return mcp


def main() -> None:
    build_server().run()
