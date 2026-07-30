"""Genomic selection, and the measurement that says whether it can work at all.

Genomic selection predicts a breeding value from marker genotypes instead of
reading a phenotype. It only works when the markers are in **linkage
disequilibrium** with the causal loci — that is the entire mechanism. A marker
uncorrelated with any QTL carries no information about the trait, so a model
fitted on such markers returns numbers that look like breeding values and are
noise.

That is not a hypothetical here. Measured 2026-07-29 on AlphaSimR 2.1.0, 10
chromosomes x 100 segregating sites, 50 SNPs per chromosome:

    generator     mean |r| adjacent SNP   mean |r| distant pairs   ratio
    quickHaplo    0.0444                  0.0462                   0.96
    runMacs       0.1979                  0.0495                   4.00

In `quickHaplo`, adjacent markers are **no more correlated than randomly chosen
distant ones**. That is what no linkage structure means: `quickHaplo` samples
haplotypes independently with no coalescent history, so there is no LD to learn
from. Out-of-sample prediction accuracy on progeny confirms it — 0.097 for
`quickHaplo` against 0.351 for `runMacs` at 500 founders.

The trap is that `quickHaplo` does not look broken. At 100 founders it reports an
apparently healthy 0.468, because a small parent set is closely related to its own
progeny and relatedness alone predicts. Grow the population to 500 and it collapses
to 0.097 — the fingerprint of family structure rather than marker-QTL LD.

**So this server measures LD rather than assuming it.** The guard keys on the
measured ratio, not on the generator's name: a name-based check could not
discriminate a `runMacs` configuration whose LD had been destroyed by parameters,
which is precisely the case a guard is for.

The uncomfortable consequence, stated plainly because the alternative is letting a
caller discover it as a wrong answer: **the only generator here with real LD is
`runMacs`, and `runMacs` is the one that is not reproducible.** Genomic selection
on this engine trades reproducibility for validity. Neither option is silently
better, so both are reported.

**Why the guard measures LD and not accuracy.** The obvious alternative — fit the
model and warn when its accuracy is poor — cannot do this job. Measured at 20
replicates, 200 individuals, three cycles:

    selection   quickHaplo (LD ratio 1.00)   runMacs (LD ratio 3.7)
    10% kept    0.104 -> 0.159 -> 0.208      0.105 -> 0.130 -> 0.167
    50% kept    0.162 -> 0.207 -> 0.226      0.217 -> 0.257 -> 0.253

A population with **no linkage disequilibrium at all** reaches accuracy 0.208, and
at 10% selection it beats the population that has real LD. Accuracy also rises
every cycle in both. Neither result is a paradox: out-of-sample accuracy in a
closed population conflates two sources — LD with the causal loci, and
**relatedness** between the training and target individuals. As the population
fills with descendants of a few selected parents, markers predict by tracking
pedigree; and quickHaplo's mutually uncorrelated markers tag pedigree MORE
efficiently than runMacs' markers, which are partly redundant with each other
precisely because they are in LD.

So an accuracy threshold would wave through a zero-LD population at 0.208 while
claiming to detect exactly that case. Only the LD measurement discriminates, which
is why it — not the accuracy — is what gates the advisory. Accuracy is still
reported, because it is what a caller needs to know about the model in front of
them. It is simply not evidence that genomic selection is working for the reason a
breeder would assume, and only the LD component generalises to unrelated material.
"""

from .engine import r_eval
from .session import Session

SELECTION_METHODS: tuple[str, ...] = ("phenotypic", "genomic")

# Ratio of adjacent-marker correlation to distant-marker correlation. At 1.0 there
# is no linkage structure whatever; measured 0.96 for quickHaplo and 4.00 for
# runMacs, so the floor sits between the two regimes rather than at a round number
# chosen for looking principled.
LD_RATIO_FLOOR = 1.5

# Below this out-of-sample correlation, the model is not predicting. Measured
# quickHaplo out-of-sample accuracy was 0.097 at 500 founders; runMacs held
# 0.33-0.45 across the same range.
MIN_USEFUL_ACCURACY = 0.15

# The LD measurement is capped so it cannot become the expensive part of founding.
# A correlation over every marker pair is O(m^2) in memory, which at the ceilings
# in limits.py would be tens of gigabytes; neither estimate needs that much data.
_LD_MAX_IND = 300
_LD_MAX_MARKERS = 2_000


class NoSnpChipError(Exception):
    """Genomic selection was requested on a session founded without a SNP chip."""


def measure_ld(session: Session) -> dict:
    """Measure linkage disequilibrium on the founder SNP chip.

    Two statistics, both mean absolute marker-marker correlation:

    - **adjacent** — each marker against its neighbour in map order. Under real
      linkage this is elevated, because neighbouring loci are inherited together.
    - **background** — each marker against the one half a chromosome-set away in
      index order. Deliberately deterministic rather than a random sample, so the
      measurement does not consume RNG state and disturb the reproducibility this
      server reports on.

    Their **ratio** is the discriminator. Under linkage, adjacent >> background.
    With no linkage structure the two are equal and the ratio sits at 1.

    Two approximations, named because they slightly dilute the adjacent figure and
    both push the ratio DOWN — that is, toward declaring no LD, which is the safe
    direction for a guard: pairs spanning a chromosome boundary are counted as
    adjacent (9 of 499 pairs at the default sizes), and the calculation is capped
    at the first `_LD_MAX_IND` individuals and `_LD_MAX_MARKERS` markers.
    """
    p = session.r_prefix
    sp = session.sim_param
    r_eval(f"""
    {p}_ldg <- pullSnpGeno({p}_p0, simParam={sp})
    if (nrow({p}_ldg) > {_LD_MAX_IND}) {{
        {p}_ldg <- {p}_ldg[1:{_LD_MAX_IND}, , drop=FALSE]
    }}
    if (ncol({p}_ldg) > {_LD_MAX_MARKERS}) {{
        {p}_ldg <- {p}_ldg[, 1:{_LD_MAX_MARKERS}, drop=FALSE]
    }}
    {p}_ldg <- {p}_ldg[, apply({p}_ldg, 2, sd) > 0, drop=FALSE]
    {p}_ldn <- ncol({p}_ldg)
    """)
    n_markers = int(r_eval(f"{p}_ldn")[0])

    # Fewer than four polymorphic markers cannot support either estimate. This is
    # a degenerate founding, not a measurement, so it reports as no LD found.
    if n_markers < 4:
        return {
            "adjacent": 0.0,
            "background": 0.0,
            "ratio": 1.0,
            "n_markers": n_markers,
            "has_linkage_disequilibrium": False,
        }

    vals = list(
        r_eval(f"""
    {p}_ldi <- 1:({p}_ldn - 1)
    {p}_ldadj <- mean(abs(suppressWarnings(vapply({p}_ldi, function(k)
        cor({p}_ldg[, k], {p}_ldg[, k + 1]), numeric(1)))), na.rm=TRUE)
    {p}_ldoff <- ((0:({p}_ldn - 1)) + floor({p}_ldn / 2)) %% {p}_ldn + 1
    {p}_ldbg <- mean(abs(suppressWarnings(vapply(1:{p}_ldn, function(k)
        cor({p}_ldg[, k], {p}_ldg[, {p}_ldoff[k]]), numeric(1)))), na.rm=TRUE)
    c({p}_ldadj, {p}_ldbg)
    """)
    )
    adjacent, background = float(vals[0]), float(vals[1])

    # A zero background would make the ratio infinite rather than informative.
    ratio = adjacent / background if background > 1e-12 else 1.0
    return {
        "adjacent": adjacent,
        "background": background,
        "ratio": ratio,
        "n_markers": n_markers,
        "has_linkage_disequilibrium": ratio >= LD_RATIO_FLOOR,
    }


def require_snp_chip(session: Session) -> None:
    """Refuse genomic selection on founders that carry no markers.

    Raised at the start of a run rather than inside R, because AlphaSimR's own
    failure here is `subscript out of bounds` — measured — which says nothing
    about what the caller did wrong.
    """
    if session.n_snp_per_chr > 0:
        return
    raise NoSnpChipError(
        "This session has no SNP chip, so genomic selection has no markers to "
        "predict from. Genotyping is decided when the population is founded, not "
        "when it is selected: call found_population(n_snp_per_chr=50, "
        'generator="runMacs") and use the session_id it returns. Note the '
        "generator — measured on this engine, quickHaplo founders carry no "
        "linkage disequilibrium at all, so genomic prediction on them is noise."
    )


def validate_method(method: str) -> str:
    if method not in SELECTION_METHODS:
        raise ValueError(
            f"Unknown selection_method {method!r}. Valid: {list(SELECTION_METHODS)}. "
            "'phenotypic' selects on the observed phenotype; 'genomic' fits RRBLUP "
            "to the marker genotypes and selects on the resulting estimated "
            "breeding value."
        )
    return method
