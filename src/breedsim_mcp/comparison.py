"""Comparing two breeding programmes honestly.

The whole reason this server refuses single runs is that people compare
programmes. Measured spread on genetic gain was sd 0.247 across seeds of one
IDENTICAL programme — larger than many differences worth acting on. So a
comparison built from two independent point estimates is not a weak result, it
is a coin flip wearing three decimal places.

Two things this module does that a naive comparison does not:

**It pairs.** Replicate i of programme A and replicate i of programme B start
from the same founders under the same seed (common random numbers). The
difference is then taken WITHIN a pair, so the shared luck of that seed cancels
instead of being counted twice. The streams do diverge as soon as the programmes
select different numbers of individuals — this is variance reduction, not perfect
synchronisation — but the starting state is identical by construction.

**It reports the difference as a distribution.** The comparison lives in the
`difference` field with its own confidence interval. If that interval contains
zero, the two programmes are indistinguishable at this replicate count and the
tool says so rather than letting a bigger mean look like a better programme.

The trap this exists to remove: **two overlapping confidence intervals do NOT
imply no difference.** Paired differences routinely resolve a contrast whose
individual intervals overlap heavily, because the pairing removes the
seed-to-seed variation that made both intervals wide. A caller reading only the
two per-programme CIs would call that pair "the same". `overlap_but_different`
fires exactly there.
"""

from dataclasses import dataclass

from .limits import check_all
from .program import run_replicate
from .replication import MIN_REPLICATES, TooFewReplicatesError, summarise
from .session import SessionStore


@dataclass(frozen=True)
class ProgramSpec:
    """One arm of the comparison."""

    label: str
    n_select: int
    n_cross: int
    selection_method: str = "phenotypic"


def _verdict(diff: dict) -> str | None:
    """Which arm wins, or None when the interval does not exclude zero.

    Deliberately returns None rather than the larger mean. Naming a winner on a
    mean whose interval straddles zero is the exact failure this module exists
    to prevent.
    """
    if diff["ci_low"] > 0:
        return "a"
    if diff["ci_high"] < 0:
        return "b"
    return None


def _intervals_overlap(x: dict, y: dict) -> bool:
    return x["ci_low"] <= y["ci_high"] and y["ci_low"] <= x["ci_high"]


def compare_programs(
    store: SessionStore,
    session_id: str,
    a_n_select: int = 10,
    b_n_select: int = 25,
    cycles: int = 3,
    replicates: int = 10,
    a_n_cross: int | None = None,
    b_n_cross: int | None = None,
    base_seed: int = 1000,
    a_label: str = "A",
    b_label: str = "B",
    a_selection_method: str = "phenotypic",
    b_selection_method: str = "phenotypic",
) -> dict:
    """Run two programmes on shared founders with paired seeds; return the difference.

    `difference` is A minus B on final-cycle genetic gain, so a positive interval
    means A gained more.

    The arms may differ in selection METHOD as well as in intensity, which is what
    makes "is genomic selection worth it on these founders?" a single paired call
    rather than two runs eyeballed against each other. That contrast needs pairing
    more than most: the gap between genomic and phenotypic selection is frequently
    smaller than the sd 0.247 of seed-to-seed noise, so two independent runs cannot
    resolve it in either direction.
    """
    # Doubled work: this runs each replicate through BOTH arms.
    check_all(replicates=replicates, cycles=cycles)
    if replicates < MIN_REPLICATES:
        raise TooFewReplicatesError(
            f"replicates={replicates} is below the minimum of {MIN_REPLICATES}. "
            "A comparison needs MORE replication than a single programme, not "
            "less: the quantity being estimated is a difference, and it is "
            "exactly the case where one run per arm looks decisive and is not."
        )

    session = store.get(session_id)
    n_traits = session.spec.get("n_traits") or 1
    if n_traits > 1:
        raise ValueError(
            f"This session has {n_traits} traits, and compare_programs returns a "
            "single paired verdict — which needs ONE criterion. With several "
            "traits the criterion is the selection index, and AlphaSimR does not "
            "report gain in index units, so any verdict here would be a choice "
            "this server made on your behalf about which trait counts. Use "
            "run_program on each programme and compare the per-trait "
            "distributions yourself."
        )
    default_cross = session.spec["n_ind"]
    a = ProgramSpec(
        a_label,
        a_n_select,
        a_n_cross if a_n_cross is not None else default_cross,
        a_selection_method,
    )
    b = ProgramSpec(
        b_label,
        b_n_select,
        b_n_cross if b_n_cross is not None else default_cross,
        b_selection_method,
    )

    per_cycle_a: list[list[float]] = [[] for _ in range(cycles)]
    per_cycle_b: list[list[float]] = [[] for _ in range(cycles)]
    per_cycle_diff: list[list[float]] = [[] for _ in range(cycles)]

    for i in range(replicates):
        # The SAME seed for both arms. This is the pairing.
        seed = base_seed + i
        ra = run_replicate(
            session, cycles, a.n_select, a.n_cross, seed, a.selection_method
        )
        rb = run_replicate(
            session, cycles, b.n_select, b.n_cross, seed, b.selection_method
        )
        for c in range(cycles):
            # [0] is safe and not a silent truncation: a multi-trait session is
            # refused above, so this arm only ever runs with exactly one trait.
            per_cycle_a[c].append(ra[c].genetic_gain[0])
            per_cycle_b[c].append(rb[c].genetic_gain[0])
            # Differenced WITHIN the pair, before any averaging.
            per_cycle_diff[c].append(ra[c].genetic_gain[0] - rb[c].genetic_gain[0])

    cycle_records = [
        {
            "cycle": c + 1,
            "a_genetic_gain": summarise(per_cycle_a[c]),
            "b_genetic_gain": summarise(per_cycle_b[c]),
            "difference": summarise(per_cycle_diff[c]),
        }
        for c in range(cycles)
    ]

    final = cycle_records[-1]
    session.cycles_run = cycles
    return {
        "session_id": session_id,
        "replicates": replicates,
        "paired": True,
        "programs": {
            "a": {
                "label": a.label,
                "n_select": a.n_select,
                "n_cross": a.n_cross,
                "selection_method": a.selection_method,
            },
            "b": {
                "label": b.label,
                "n_select": b.n_select,
                "n_cross": b.n_cross,
                "selection_method": b.selection_method,
            },
        },
        "cycles": cycle_records,
        "difference_is": "a_minus_b_final_cycle_genetic_gain",
        "favours": _verdict(final["difference"]),
        "intervals_overlap": _intervals_overlap(
            final["a_genetic_gain"], final["b_genetic_gain"]
        ),
        "reproducible": session.reproducible,
        "recipe": {
            "generator": session.generator,
            "seed": session.seed,
            "base_seed": base_seed,
            "cycles": cycles,
        },
    }
