"""One replicate of a selection programme.

Deliberately private to `replication`: nothing outside this package should be able
to run a single replicate and read its numbers, because a single stochastic run is
not a result. See `replication.run_program`.
"""

from dataclasses import dataclass

from .engine import r_eval
from .session import Session


@dataclass(frozen=True)
class CycleRecord:
    cycle: int
    genetic_gain: float
    genetic_variance: float


def run_replicate(
    session: Session,
    cycles: int,
    n_select: int,
    n_cross: int,
    seed: int,
) -> list[CycleRecord]:
    """Run `cycles` of truncation selection from the session's founders.

    Each replicate restarts from the SAME founders with a DIFFERENT seed, so the
    spread across replicates measures the stochasticity of the breeding process
    rather than of the founder sample.
    """
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
        r_eval(f"""
        {p}_sel <- selectInd({p}, nInd={n_select}, use="pheno", simParam={sp})
        {p} <- randCross({p}_sel, nCrosses={n_cross}, simParam={sp})
        """)
        records.append(
            CycleRecord(
                cycle=i,
                genetic_gain=float(r_eval(f"meanG({p})")[0]),
                genetic_variance=float(r_eval(f"varG({p})")[0]),
            )
        )
    return records
