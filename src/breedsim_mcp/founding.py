"""Founder populations, and honest reporting of whether they can be reproduced.

Measured 2026-07-28 on AlphaSimR 2.1.0: under a fixed `set.seed`, `quickHaplo`
produces identical founder haplotypes while `runMacs` does not — and `runMacs`
stays irreproducible even at `nThreads=1` with `OMP_NUM_THREADS=1`, so this is not
a threading artefact. The MaCS coalescent simply does not draw from R's RNG.

Both generators are offered, because `runMacs` gives realistic coalescent LD that
`quickHaplo` does not. What is NOT offered is silence about the difference.
"""

import hashlib

from .engine import r_eval, require_alphasimr
from .session import Session, SessionStore

GENERATORS: tuple[str, ...] = ("quickHaplo", "runMacs")


def _founder_hash(session: Session) -> str:
    """Hash the actual haplotype matrix.

    Deliberately not a derived statistic: mean genetic value of a founder
    population is ~0 by construction, so comparing it would compare signed zeros
    and report determinism that is not there.
    """
    r_eval(
        f"{session.r_prefix}_p0 <- newPop({session.founders}, simParam={session.sim_param})"
    )
    vals = list(
        r_eval(
            f"as.vector(pullSegSiteHaplo({session.r_prefix}_p0, simParam={session.sim_param}))"
        )
    )
    return hashlib.sha256(",".join(f"{v:g}" for v in vals).encode()).hexdigest()[:16]


def found_population(
    store: SessionStore,
    generator: str = "quickHaplo",
    seed: int = 1,
    n_ind: int = 100,
    n_chr: int = 10,
    seg_sites: int = 100,
    n_qtl_per_chr: int = 10,
    h2: float = 0.4,
    species: str = "MAIZE",
) -> Session:
    """Create a founder population and its trait architecture, and persist both."""
    if generator not in GENERATORS:
        raise ValueError(
            f"Unknown generator {generator!r}. Valid: {list(GENERATORS)}. "
            "'quickHaplo' is reproducible from a seed; 'runMacs' gives realistic "
            "coalescent linkage disequilibrium but is NOT reproducible."
        )
    for name, value in (("n_ind", n_ind), ("n_chr", n_chr), ("seg_sites", seg_sites)):
        if value < 1:
            raise ValueError(f"{name} must be >= 1, got {value}")
    if not 0 < h2 <= 1:
        raise ValueError(f"h2 must be in (0, 1], got {h2}")

    require_alphasimr()
    prefix = store.new_prefix()

    if generator == "quickHaplo":
        founder_call = f"quickHaplo(nInd={n_ind}, nChr={n_chr}, segSites={seg_sites})"
    else:
        founder_call = (
            f"runMacs(nInd={n_ind}, nChr={n_chr}, segSites={seg_sites}, "
            f'species="{species}")'
        )

    # simParam is passed explicitly everywhere: several AlphaSimR helpers default
    # to a GLOBAL named `SP` and error with "object 'SP' not found" otherwise.
    r_eval(f"""
    set.seed({seed})
    {prefix}_founders <- {founder_call}
    {prefix}_SP <- SimParam$new({prefix}_founders)
    {prefix}_SP$addTraitA(nQtlPerChr={n_qtl_per_chr})
    {prefix}_SP$setVarE(h2={h2})
    """)

    reproducible = generator == "quickHaplo"
    session = Session(
        session_id=f"bs-{prefix[4:]}",
        r_prefix=prefix,
        generator=generator,
        seed=seed,
        founder_hash="",
        reproducible=reproducible,
        reason=(
            None
            if reproducible
            else (
                "Founders were generated with runMacs, whose coalescent RNG is not "
                "governed by R's set.seed. Measured: identical seeds give different "
                "founder haplotypes, even at nThreads=1 with OMP_NUM_THREADS=1. Use "
                "generator='quickHaplo' if you need this session to be reproducible."
            )
        ),
        spec={
            "n_ind": n_ind,
            "n_chr": n_chr,
            "seg_sites": seg_sites,
            "n_qtl_per_chr": n_qtl_per_chr,
            "h2": h2,
            "species": species if generator == "runMacs" else None,
        },
    )
    session.founder_hash = _founder_hash(session)
    return store.add(session)
