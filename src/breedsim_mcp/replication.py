"""Replication and aggregation — the load-bearing rule of this server.

**A single stochastic run is not a result, and this module will not return one.**

Measured on AlphaSimR 2.1.0: five seeds of an identical three-cycle programme gave
mean genetic gain [1.151, 1.841, 1.424, 1.429, 1.473] — sd 0.247, range 0.690, on
the very quantity being reported. Quoting one run to three decimal places reports
noise with the authority of a measurement.

There is deliberately NO parameter that collapses the output to a point estimate:
no `replicates=1`, no `raw=True`. A caller is free to average the interval
themselves; what they cannot do is get the server to present a lone run as the
answer. This mirrors `plantcv-mcp`, where traits are unreachable without the
segmentation overlay — make the honest answer the only reachable one.
"""

import statistics

from .limits import check_all
from .program import run_replicate
from .session import SessionStore

# Below this, the standard deviation is not estimable in any meaningful way.
MIN_REPLICATES = 5
DEFAULT_REPLICATES = 10

# Two-sided 95% t critical values by degrees of freedom (n-1). A normal 1.96
# would understate the interval at these sample sizes, which is the wrong
# direction to be wrong in when the point of the interval is honesty.
_T95 = {
    4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262,
    10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131,
    16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086, 24: 2.064,
    29: 2.045,
}  # fmt: skip


class TooFewReplicatesError(Exception):
    """Raised when fewer replicates are requested than can support an interval."""


def _t_critical(df: int) -> float:
    if df in _T95:
        return _T95[df]
    if df < 4:
        return _T95[4]
    known = sorted(_T95)
    nearest = min((k for k in known if k >= df), default=known[-1])
    return _T95[nearest] if df <= known[-1] else 1.96


def summarise(values: list[float]) -> dict:
    """mean / sd / 95% CI. Never returns an individual value."""
    n = len(values)
    mean = statistics.fmean(values)
    sd = statistics.stdev(values) if n > 1 else 0.0
    half = _t_critical(n - 1) * (sd / (n**0.5)) if n > 1 else 0.0
    return {
        "mean": mean,
        "sd": sd,
        "ci_low": mean - half,
        "ci_high": mean + half,
        "n": n,
    }


def run_program(
    store: SessionStore,
    session_id: str,
    cycles: int = 3,
    replicates: int = DEFAULT_REPLICATES,
    n_select: int = 10,
    n_cross: int | None = None,
    base_seed: int = 1000,
    selection_method: str = "phenotypic",
) -> dict:
    """Run a selection programme `replicates` times; return per-cycle distributions.

    Raises TooFewReplicatesError below MIN_REPLICATES. That is the point of the
    module, not a limitation of it.

    Under `selection_method="genomic"` each cycle also carries a
    `prediction_accuracy` distribution — the out-of-sample correlation between
    predicted and true breeding value. It is summarised across replicates like
    everything else here, because a single replicate's accuracy is as much a draw
    from a distribution as a single replicate's gain.
    """
    check_all(replicates=replicates, cycles=cycles)
    if replicates < MIN_REPLICATES:
        raise TooFewReplicatesError(
            f"replicates={replicates} is below the minimum of {MIN_REPLICATES}. "
            "This server does not return single-run results: measured run-to-run "
            "spread on genetic gain was sd 0.247, the same order as the effects "
            "being compared, so one run is a draw from a distribution rather than "
            "an answer. Ask for at least "
            f"{MIN_REPLICATES} replicates."
        )

    session = store.get(session_id)
    crosses = n_cross if n_cross is not None else session.spec["n_ind"]

    # Each replicate gets its own seed; the founders are shared and fixed.
    per_replicate = [
        run_replicate(
            session, cycles, n_select, crosses, base_seed + i, selection_method
        )
        for i in range(replicates)
    ]

    cycle_records = []
    for c in range(cycles):
        record = {
            "cycle": c + 1,
            "genetic_gain": summarise([r[c].genetic_gain for r in per_replicate]),
            "genetic_variance": summarise(
                [r[c].genetic_variance for r in per_replicate]
            ),
        }
        # Absent rather than null under phenotypic selection: no model was fitted,
        # so there is no accuracy that could be reported as zero without implying
        # a model that predicted nothing.
        accuracies: list[float] = [
            acc
            for acc in (r[c].prediction_accuracy for r in per_replicate)
            if acc is not None
        ]
        if accuracies:
            record["prediction_accuracy"] = summarise(accuracies)
        cycle_records.append(record)

    session.cycles_run = cycles
    return {
        "session_id": session_id,
        "replicates": replicates,
        "cycles": cycle_records,
        "reproducible": session.reproducible,
        "recipe": {
            "generator": session.generator,
            "seed": session.seed,
            "n_select": n_select,
            "n_cross": crosses,
            "base_seed": base_seed,
            "selection_method": selection_method,
        },
    }
