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
    # One value PER TRAIT. A single-trait programme carries a one-element tuple
    # rather than a scalar, so aggregation has ONE shape to handle instead of
    # two — a scalar-or-list union is how the wrong element ends up being read
    # as "the" gain.
    genetic_gain: tuple[float, ...]
    genetic_variance: tuple[float, ...]
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
    index_weights: list[float] | None = None,
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

    n_traits = int(session.spec.get("n_traits", 1) or 1)
    index_clause = _index_clause(index_weights, n_traits)

    p = f"{session.r_prefix}_pop"
    sp = session.sim_param
    r_eval(f"set.seed({seed}); {p} <- newPop({session.founders}, simParam={sp})")

    records: list[CycleRecord] = []
    for i in range(1, cycles + 1):
        accuracy: float | None = None
        if selection_method == "phenotypic":
            r_eval(f"""
        {p}_sel <- selectInd({p}, nInd={n_select}, use="pheno"{index_clause}, simParam={sp})
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
        {p}_sel <- selectInd({p}, nInd={n_select}, use="ebv"{index_clause}, simParam={sp})
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
        # meanG/varG return one value PER TRAIT. Reading [0] would silently
        # report trait 1 as the whole answer on a multi-trait programme.
        gains = tuple(float(v) for v in r_eval(f"meanG({p})"))
        variances = tuple(float(v) for v in _diag_or_vector(f"varG({p})"))
        records.append(
            CycleRecord(
                cycle=i,
                genetic_gain=gains,
                genetic_variance=variances,
                prediction_accuracy=accuracy,
            )
        )
    return records


def _diag_or_vector(expr: str) -> list[float]:
    """varG returns a scalar for one trait and a COVARIANCE MATRIX for several.

    Taking the whole matrix would report covariances as if they were variances;
    taking element [0] would report trait 1's variance as the programme's. The
    diagonal is the per-trait variance, which is what the summary means.
    """
    values = [float(v) for v in r_eval(expr)]
    n = len(values)
    root = round(n**0.5)
    if root > 1 and root * root == n:
        return [values[j * root + j] for j in range(root)]
    return values


def _index_clause(index_weights: list[float] | None, n_traits: int) -> str:
    """The `trait=selIndex, b=..., scale=TRUE` fragment, or nothing.

    Selection on several traits needs an explicit economic weighting: there is
    no defensible default, because the weights ARE the breeding objective.
    Without them AlphaSimR silently selects on trait 1 alone, which looks like a
    multi-trait programme and is not one — so a multi-trait session without
    weights is refused rather than quietly reduced to its first trait.
    """
    if index_weights is None:
        if n_traits > 1:
            raise ValueError(
                f"This session has {n_traits} traits, so run_program needs "
                "index_weights — one economic weight per trait. Without them "
                "selection would fall back to trait 1 alone and the other "
                f"{n_traits - 1} would be along for the ride while appearing to "
                "be selected on."
            )
        return ""
    if n_traits == 1:
        raise ValueError(
            "index_weights was given but this session has a single trait. Found "
            "the population with a LIST of heritabilities to build a multi-trait "
            "architecture."
        )
    if len(index_weights) != n_traits:
        raise ValueError(
            f"index_weights has {len(index_weights)} weights but the session has "
            f"{n_traits} traits. One weight per trait, in trait order."
        )
    if not any(index_weights):
        raise ValueError(
            "index_weights are all zero, so the index cannot rank anything."
        )
    weights = ", ".join(str(float(w)) for w in index_weights)
    # scale=TRUE puts the traits on a common scale before weighting. Without it
    # the weights would be applied to raw units, so a trait measured in tonnes
    # and one in percent would be weighted by their units as much as by intent.
    return f", trait=selIndex, b=c({weights}), scale=TRUE"
