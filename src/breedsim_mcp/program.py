"""One replicate of a selection programme.

Deliberately private to `replication`: nothing outside this package should be able
to run a single replicate and read its numbers, because a single stochastic run is
not a result. See `replication.run_program`.
"""

import math
from dataclasses import dataclass

from .engine import r_eval
from .genomic import require_snp_chip, validate_method
from .limits import check_all
from .session import Session


@dataclass(frozen=True)
class CycleRecord:
    cycle: int
    genetic_gain: float
    genetic_variance: float
    # None under phenotypic selection, where no model is fitted and there is
    # therefore no prediction whose accuracy could be reported.
    prediction_accuracy: float | None = None


def run_replicate(
    session: Session,
    cycles: int,
    n_select: int,
    n_cross: int,
    seed: int,
    selection_method: str = "phenotypic",
) -> list[CycleRecord]:
    """Run `cycles` of truncation selection from the session's founders.

    Each replicate restarts from the SAME founders with a DIFFERENT seed, so the
    spread across replicates measures the stochasticity of the breeding process
    rather than of the founder sample.

    Under `selection_method="genomic"`, each cycle fits RRBLUP to the current
    generation's markers and phenotypes and selects on the resulting estimated
    breeding value instead of the phenotype.

    **`prediction_accuracy` is measured out-of-sample, on the progeny.** The model
    is scored against individuals created after it was fitted, which it has never
    seen. Scoring it on its own training generation instead would be easy and
    would overstate it badly: measured on quickHaplo founders at 500 individuals,
    in-sample accuracy read 0.448 while true out-of-sample accuracy was 0.097. A
    server that refuses to report a single run cannot then report an in-sample fit
    as though it were predictive ability.
    """
    validate_method(selection_method)
    if selection_method == "genomic":
        require_snp_chip(session)
    check_all(cycles=cycles, n_select=n_select, n_cross=n_cross)
    if cycles < 1:
        raise ValueError(f"cycles must be >= 1, got {cycles}")
    if n_select < 1 or n_cross < 1:
        raise ValueError(
            f"n_select and n_cross must be >= 1, got {n_select}, {n_cross}"
        )
    if n_select > session.spec["n_ind"]:
        raise ValueError(
            f"n_select={n_select} exceeds the population size "
            f"({session.spec['n_ind']}); nothing would be selected against."
        )

    p = f"{session.r_prefix}_pop"
    sp = session.sim_param
    r_eval(f"set.seed({seed}); {p} <- newPop({session.founders}, simParam={sp})")

    records: list[CycleRecord] = []
    for i in range(1, cycles + 1):
        accuracy: float | None = None
        if selection_method == "phenotypic":
            r_eval(f"""
        {p}_sel <- selectInd({p}, nInd={n_select}, use="pheno", simParam={sp})
        {p} <- randCross({p}_sel, nCrosses={n_cross}, simParam={sp})
        """)
        else:
            # Fit on this generation, select on the fitted EBVs, then re-score the
            # SAME model on the progeny — individuals that did not exist when it
            # was fitted. That second setEBV is what makes the reported accuracy
            # out-of-sample rather than a measure of its own fit.
            r_eval(f"""
        {p}_sol <- RRBLUP({p}, simParam={sp})
        {p} <- setEBV({p}, {p}_sol, simParam={sp})
        {p}_sel <- selectInd({p}, nInd={n_select}, use="ebv", simParam={sp})
        {p} <- randCross({p}_sel, nCrosses={n_cross}, simParam={sp})
        {p} <- setEBV({p}, {p}_sol, simParam={sp})
        {p}_acc <- suppressWarnings(cor(as.numeric(ebv({p})[, 1]),
                                        as.numeric(gv({p})[, 1])))
        """)
            raw = float(r_eval(f"{p}_acc")[0])
            # A correlation is undefined when either side has no variance — which
            # happens once selection has fixed the population. Undefined is
            # reported as no predictive ability rather than dropped, so that the
            # low-accuracy advisory still sees it.
            accuracy = 0.0 if math.isnan(raw) else raw
        records.append(
            CycleRecord(
                cycle=i,
                genetic_gain=float(r_eval(f"meanG({p})")[0]),
                genetic_variance=float(r_eval(f"varG({p})")[0]),
                prediction_accuracy=accuracy,
            )
        )
    return records
