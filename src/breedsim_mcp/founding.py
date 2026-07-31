"""Founder populations, and honest reporting of whether they can be reproduced.

Measured 2026-07-28 on AlphaSimR 2.1.0. `quickHaplo` reproduces from a seed.
`runMacs` is subtler than "ignores the seed": its MaCS RNG is seeded once per R
SESSION and advances across calls, so two seeded calls in one session differ while
the same call SEQUENCE in a fresh process reproduces exactly. Since this server is
a long-lived process, the practical consequence is that a repeat found_population
with the same seed gives different founders — hence reproducible=False.

Both generators are offered, because `runMacs` gives realistic coalescent LD that
`quickHaplo` does not. What is NOT offered is silence about the difference.
"""

import hashlib

from .engine import r_eval, require_alphasimr
from .genomic import measure_ld
from .limits import check_all
from .session import Session, SessionStore

GENERATORS: tuple[str, ...] = ("quickHaplo", "runMacs")

# The species runMacs actually has demographic histories for. Read out of
# `body(runMacs)` in AlphaSimR 2.1.0, not from documentation: the function
# branches on these four and ends in `stop("No rules for species ...")`.
#
# Note what this list says about scope. Two of the four are plants and one is an
# animal, so this server is NOT plant-only, whatever its `plant-breeding` topic
# suggests. The value used to be interpolated into R with no check at all.
SPECIES: tuple[str, ...] = ("GENERIC", "CATTLE", "WHEAT", "MAIZE")

# The single canonical statement of runMacs' RNG behaviour.
#
# This exists because the fact was hand-restated in four places, and when the
# original overstatement ("runMacs ignores set.seed") was corrected here, the
# copies in server.py — including the INSTRUCTIONS an agent reads to decide how
# to drive the engine — kept asserting the false version. Paraphrase is the
# mechanism; a shared constant removes it. Every agent-facing surface
# interpolates THIS string rather than restating it.
RUNMACS_RNG_NOTE = (
    "its MaCS coalescent RNG is seeded ONCE PER R SESSION and advances across "
    "calls, so set.seed does not reset it and repeating a seeded call inside "
    "this long-lived process yields different founders"
)


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


MAX_TRAITS = 10


def _cor_matrix_r(n_traits: int, correlation: float) -> str:
    """R literal for an equicorrelation matrix: 1 on the diagonal, rho elsewhere.

    One scalar rather than a full matrix, and said plainly rather than implied:
    with three or more traits this makes EVERY pair equally correlated, which is
    a simplification. An arbitrary correlation structure would need the caller to
    supply a whole matrix and would need checking for positive-definiteness —
    AlphaSimR fails inside R otherwise, with a message naming neither the matrix
    nor the traits.
    """
    rows = []
    for i in range(n_traits):
        rows.append(
            ", ".join("1" if i == j else str(correlation) for j in range(n_traits))
        )
    return f"matrix(c({', '.join(rows)}), nrow={n_traits})"


def found_population(
    store: SessionStore,
    generator: str = "quickHaplo",
    seed: int = 1,
    n_ind: int = 100,
    n_chr: int = 10,
    seg_sites: int = 100,
    n_qtl_per_chr: int = 10,
    h2: float | list[float] = 0.4,
    species: str = "MAIZE",
    n_snp_per_chr: int = 0,
    trait_correlation: float = 0.0,
) -> Session:
    """Create a founder population and its trait architecture, and persist both.

    `n_snp_per_chr` > 0 adds a SNP chip, which is what genomic selection predicts
    from. Genotyping is a founding decision because the markers have to exist
    before any breeding value can be estimated from them; a session founded
    without a chip cannot run genomic selection at all.
    """
    if generator not in GENERATORS:
        raise ValueError(
            f"Unknown generator {generator!r}. Valid: {list(GENERATORS)}. "
            "'quickHaplo' is reproducible from a seed; 'runMacs' gives realistic "
            "coalescent linkage disequilibrium but is NOT reproducible."
        )
    # AlphaSimR upper-cases this itself, so accept any casing and normalise —
    # then check it, which the old passthrough never did. Validated even for
    # quickHaplo, which ignores the value: silently accepting a species that
    # will not be used is how a typo survives long enough to look deliberate.
    species = species.upper()
    if species not in SPECIES:
        raise ValueError(
            f"Unknown species {species!r}. Valid: {list(SPECIES)}. These are the "
            "only four runMacs has a demographic history for; anything else "
            'fails inside R with "No rules for species". Note that CATTLE is '
            "supported: this server simulates animal breeding as well as plant."
        )
    check_all(
        n_ind=n_ind,
        n_chr=n_chr,
        seg_sites=seg_sites,
        n_qtl_per_chr=n_qtl_per_chr,
        n_snp_per_chr=n_snp_per_chr,
    )
    for name, value in (("n_ind", n_ind), ("n_chr", n_chr), ("seg_sites", seg_sites)):
        if value < 1:
            raise ValueError(f"{name} must be >= 1, got {value}")
    # h2 as a LIST is what declares a multi-trait architecture: one heritability
    # per trait. A separate n_traits argument could disagree with the length of
    # h2, and then one of the two would silently win.
    h2_list = [float(h2)] if isinstance(h2, int | float) else [float(v) for v in h2]
    n_traits = len(h2_list)
    if n_traits < 1:
        raise ValueError("h2 must give at least one heritability.")
    if n_traits > MAX_TRAITS:
        raise ValueError(
            f"{n_traits} traits exceeds the {MAX_TRAITS} cap. Each trait adds a "
            "QTL set per chromosome and a column to every phenotype."
        )
    for value in h2_list:
        if not 0 < value <= 1:
            raise ValueError(f"every h2 must be in (0, 1], got {h2}")
    if not -1 <= trait_correlation <= 1:
        raise ValueError(
            f"trait_correlation must be in [-1, 1], got {trait_correlation}"
        )
    if n_traits == 1 and trait_correlation:
        raise ValueError(
            "trait_correlation was given but h2 declares a single trait, so there "
            "is nothing for it to correlate. Pass a list of heritabilities — one "
            "per trait — to build a multi-trait architecture."
        )
    if n_snp_per_chr < 0:
        raise ValueError(f"n_snp_per_chr must be >= 0, got {n_snp_per_chr}")
    # QTL and SNP markers are drawn from the same pool of segregating sites, so
    # asking for more of both than exist fails inside R with "Not enough eligible
    # sites" — measured. Caught here so the message names the three numbers that
    # have to add up.
    if n_snp_per_chr and n_snp_per_chr + n_qtl_per_chr > seg_sites:
        raise ValueError(
            f"n_snp_per_chr={n_snp_per_chr} plus n_qtl_per_chr={n_qtl_per_chr} "
            f"exceeds seg_sites={seg_sites}. QTL and SNP markers are both drawn "
            "from the segregating sites on each chromosome, so their total cannot "
            "exceed what is there. Raise seg_sites, or lower either count."
        )

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
    # Only emitted when a chip is asked for, so a session founded without one
    # consumes exactly the RNG draws it did before this parameter existed.
    snp_chip = (
        f"\n    {prefix}_SP$addSnpChip(nSnpPerChr={n_snp_per_chr})"
        if n_snp_per_chr
        else ""
    )
    # The single-trait call is emitted EXACTLY as it was before multi-trait
    # existed — same arguments, same order, same number of RNG draws — so a
    # session founded with a scalar h2 still reproduces the founders it did
    # under earlier versions. The multi-trait branch is additive, not a rewrite
    # of the single-trait path with new defaults threaded through it.
    if n_traits == 1:
        trait_call = f"{prefix}_SP$addTraitA(nQtlPerChr={n_qtl_per_chr})"
        var_e = f"{prefix}_SP$setVarE(h2={h2_list[0]})"
    else:
        cor_a = _cor_matrix_r(n_traits, trait_correlation)
        means = ", ".join("0" for _ in range(n_traits))
        variances = ", ".join("1" for _ in range(n_traits))
        trait_call = (
            f"{prefix}_SP$addTraitA(nQtlPerChr={n_qtl_per_chr}, "
            f"mean=c({means}), var=c({variances}), corA={cor_a})"
        )
        var_e = f"{prefix}_SP$setVarE(h2=c({', '.join(str(v) for v in h2_list)}))"

    r_eval(f"""
    set.seed({seed})
    {prefix}_founders <- {founder_call}
    {prefix}_SP <- SimParam$new({prefix}_founders)
    {trait_call}{snp_chip}
    {var_e}
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
                f"Founders were generated with runMacs: {RUNMACS_RNG_NOTE}. "
                "(Measured: within one session, two seeded runMacs calls differ; "
                "across fresh processes the same call sequence does reproduce.) Use "
                "generator='quickHaplo' if you need repeatable founders here."
            )
        ),
        spec={
            "n_ind": n_ind,
            "n_chr": n_chr,
            "seg_sites": seg_sites,
            "n_qtl_per_chr": n_qtl_per_chr,
            "h2": h2_list[0] if n_traits == 1 else h2_list,
            "n_traits": n_traits,
            "trait_correlation": trait_correlation if n_traits > 1 else None,
            "species": species if generator == "runMacs" else None,
            "n_snp_per_chr": n_snp_per_chr,
        },
        n_snp_per_chr=n_snp_per_chr,
    )
    session.founder_hash = _founder_hash(session)
    # Measured at founding, not at selection time: a caller who is about to spend
    # replicates on genomic selection should learn here that the markers carry no
    # information, rather than after paying for the run.
    if n_snp_per_chr:
        session.ld = measure_ld(session)
    return store.add(session)
