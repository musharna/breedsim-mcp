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

import functools
import statistics

from .engine import r_eval
from .limits import check_all, check_seed_range
from .program import run_replicate
from .session import SessionStore


def _engine_provenance() -> dict[str, str | None]:
    """Versions of the stack that produced a result, for the result to carry.

    Cheap enough to call per run: `check_environment` only reads
    `R.version.string` and package metadata, and R is already up by the time any
    run finishes. Never raises — provenance that can break a simulation would be
    worse than provenance that is absent, so a failure degrades to nulls.
    """
    from . import engine

    try:
        env = engine.check_environment()
    except Exception:  # noqa: BLE001 - see docstring: never break a run over this
        return {"r_version": None, "alphasimr_version": None, "rpy2_version": None}
    return {
        "r_version": env.r_version,
        "alphasimr_version": env.alphasimr_version,
        "rpy2_version": env.rpy2_version,
    }


# Below this, the standard deviation is not estimable in any meaningful way.
MIN_REPLICATES = 5
DEFAULT_REPLICATES = 10


class TooFewReplicatesError(Exception):
    """Raised when fewer replicates are requested than can support an interval."""


@functools.cache
def _t_critical(df: int) -> float:
    """The exact two-sided 95% t critical value, R's `qt(0.975, df)`.

    This replaced a 19-entry table that, for any df it did not list, used the
    NEXT LISTED df up — and past 29 the normal 1.96. A higher df has a SMALLER
    critical value, so every rounding went the same way: intervals too narrow,
    which is the one direction an interval here must not be wrong in. That held
    for 177 of the 196 replicate counts allowed (5..200); at n=31 it used 1.96
    against a true 2.042. R is already loaded, so the exact quantile costs one
    call per distinct df.
    """
    if df < 1:
        raise ValueError(f"a t interval needs df >= 1, got {df}")
    return float(r_eval(f"qt(0.975, df={int(df)})")[0])


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
    index_weights: list[float] | None = None,
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
            "This server does not return single-run results: in one five-seed measurement, "
            "run-to-run spread on genetic gain was sd 0.247, the same order as the effects "
            "being compared, so one run is a draw from a distribution rather than "
            "an answer. Ask for at least "
            f"{MIN_REPLICATES} replicates."
        )

    check_seed_range("base_seed", base_seed, replicates)

    session = store.get(session_id)
    crosses = n_cross if n_cross is not None else session.spec["n_ind"]

    # Each replicate gets its own seed; the founders are shared and fixed.
    per_replicate = [
        run_replicate(
            session,
            cycles,
            n_select,
            crosses,
            base_seed + i,
            selection_method,
            index_weights=index_weights,
        )
        for i in range(replicates)
    ]

    n_traits = int(session.spec.get("n_traits", 1) or 1)
    cycle_records = []
    for c in range(cycles):
        record: dict = {"cycle": c + 1}
        if n_traits == 1:
            record["genetic_gain"] = summarise(
                [r[c].genetic_gain[0] for r in per_replicate]
            )
            record["genetic_variance"] = summarise(
                [r[c].genetic_variance[0] for r in per_replicate]
            )
        else:
            # No bare `genetic_gain` on a multi-trait programme, deliberately.
            # Emitting one would have to mean trait 1, and a caller reading the
            # familiar key would take a single trait for the whole objective.
            # Make them read per-trait, the way the summary is only ever
            # reachable as a distribution.
            record["traits"] = [
                {
                    "trait": t + 1,
                    "genetic_gain": summarise(
                        [r[c].genetic_gain[t] for r in per_replicate]
                    ),
                    "genetic_variance": summarise(
                        [r[c].genetic_variance[t] for r in per_replicate]
                    ),
                }
                for t in range(n_traits)
            ]
        # Absent rather than null under phenotypic selection: no model was fitted,
        # so there is no accuracy that could be reported as zero without implying
        # a model that predicted nothing. Per trait on a multi-trait programme,
        # inside each `traits` entry, for the same reason there is no bare
        # genetic_gain there: a single accuracy would have to be trait 1's.
        accuracies = [
            r[c].prediction_accuracy
            for r in per_replicate
            if r[c].prediction_accuracy is not None
        ]
        if accuracies:
            if n_traits == 1:
                record["prediction_accuracy"] = summarise([a[0] for a in accuracies])
            else:
                for t, trait_record in enumerate(record["traits"]):
                    trait_record["prediction_accuracy"] = summarise(
                        [a[t] for a in accuracies]
                    )
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
            "n_traits": n_traits,
            "index_weights": list(index_weights) if index_weights else None,
            # Provenance travels WITH the result. The versions were already
            # available, but only from list_methods — so a stored or forwarded
            # result could not say which engine produced it, and two results
            # could not be told apart. A number you cannot attribute is not a
            # citable measurement.
            "engine": _engine_provenance(),
            # What the gain is measured IN. Deliberately a description of the
            # scale rather than a unit string: single-trait sessions use
            # AlphaSimR's addTraitA defaults (genetic mean 0, variance 1) so
            # gain is in founder additive genetic SD, while a multi-trait
            # session sets its own variances and the scale is whatever the
            # caller chose. One hard-coded label would be wrong for one of them.
            "gain_scale": (
                "founder additive genetic SD (trait variance set to 1 at founding)"
                if n_traits == 1
                else "trait units on the caller-supplied variances from found_population"
            ),
        },
    }
