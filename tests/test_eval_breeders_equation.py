"""EVAL: does the simulation obey the breeder's equation?

Every other test here checks that the code does what the code intends. This one
checks the code against something OUTSIDE it: the closed-form prediction of
quantitative genetics.

    R = h^2 * S

Response to selection equals narrow-sense heritability times the selection
differential. `addTraitA` builds a purely additive trait, so the h2 handed to
`setVarE` IS the narrow-sense heritability, and the identity should hold in
expectation.

Recovering h2 as R/S is the eval: the simulator is asked a question whose answer
was fixed before it ran, by theory rather than by a previous version of this
code. A regression test can only tell you the number stopped changing. This can
tell you the number is WRONG.

**The tolerance is measured, not guessed.** At 20 replicates of 500 founders the
recovered h2 came out at 0.1987 / 0.4875 / 0.7950 against true 0.2 / 0.5 / 0.8 —
relative errors of 0.6%, 2.5% and 0.6%, with a replicate-to-replicate sd of
about 0.03.

## What this eval does NOT cover

It writes its own R and calls `r_eval` directly, so the subject is **AlphaSimR
plus the theory** — not this server's selection path. It never imports
`program`, `founding` or `replication`.

Measured, so the boundary is not a guess: flipping the server's own selection
from `use="pheno"` to `use="rand"` — which destroys response to selection
entirely — leaves this file GREEN. Four other tests catch it, chiefly
`test_simulation.py::test_gain_rises_and_variance_falls_under_selection`, so the
behaviour IS covered; it is covered there, not here.

Stated because the file's name invites the opposite reading. An eval whose scope
is assumed wider than it is licenses more confidence than it earns.
"""

import statistics

import pytest

from breedsim_mcp.engine import r_eval, require_alphasimr

# Smaller than the calibration run so CI stays affordable; the tolerance below
# is widened to match rather than the population being quietly shrunk under a
# tolerance calibrated at a different size.
N_IND = 300
N_SELECT = 30
REPLICATES = 12
TRUE_H2 = (0.2, 0.5, 0.8)

# Absolute tolerance on recovered h2. Wide enough to absorb drift at this
# replicate count, tight enough that a systematically wrong response — a factor
# of two, a variance mix-up, selection acting on the wrong value — cannot pass.
TOLERANCE = 0.08


def _recover_h2(h2: float) -> tuple[float, float]:
    """Return (mean, sd) of R/S over independent replicates."""
    require_alphasimr()
    ratios: list[float] = []
    for seed in range(1, REPLICATES + 1):
        r_eval(f"""
        set.seed({seed})
        .ev_f <- quickHaplo(nInd={N_IND}, nChr=10, segSites=100)
        .ev_SP <- SimParam$new(.ev_f)
        .ev_SP$addTraitA(nQtlPerChr=10)
        .ev_SP$setVarE(h2={h2})
        .ev_p <- newPop(.ev_f, simParam=.ev_SP)
        .ev_g0 <- meanG(.ev_p)
        .ev_pbar <- meanP(.ev_p)
        .ev_sel <- selectInd(.ev_p, nInd={N_SELECT}, use="pheno", simParam=.ev_SP)
        .ev_S <- meanP(.ev_sel) - .ev_pbar
        .ev_prog <- randCross(.ev_sel, nCrosses={N_IND}, simParam=.ev_SP)
        .ev_R <- meanG(.ev_prog) - .ev_g0
        """)
        s = float(r_eval(".ev_S")[0])
        r = float(r_eval(".ev_R")[0])
        if abs(s) > 1e-9:
            ratios.append(r / s)
    return statistics.fmean(ratios), statistics.stdev(ratios)


@pytest.mark.parametrize("true_h2", TRUE_H2)
def test_response_to_selection_recovers_the_heritability(true_h2):
    """R/S must estimate h2, the value the trait was BUILT with."""
    recovered, sd = _recover_h2(true_h2)
    assert abs(recovered - true_h2) < TOLERANCE, (
        f"breeder's equation violated: h2={true_h2} was built into the trait, "
        f"but response/differential recovered {recovered:.4f} "
        f"(sd {sd:.4f} over {REPLICATES} replicates). Either selection is not "
        "acting on the value it claims to, or the response is being measured "
        "against the wrong baseline."
    )


def test_recovered_heritability_tracks_the_true_value():
    """The DISCRIMINATING half, and the reason the test above is not enough.

    A simulator that ignored h2 entirely and returned some fixed ratio could sit
    inside the tolerance at one setting by luck. Requiring the recovered value to
    RISE with the true one cannot be satisfied by any constant, so it separates
    "the identity holds" from "one number happened to land close".
    """
    recovered = {h2: _recover_h2(h2)[0] for h2 in TRUE_H2}
    ordered = [recovered[h2] for h2 in sorted(TRUE_H2)]
    assert ordered == sorted(ordered), (
        f"recovered h2 does not increase with true h2: {recovered}. The response "
        "is not scaling with heritability, so any single-point agreement above "
        "is a coincidence rather than the equation holding."
    )
    # And the spread must be real, not three values sitting on top of each other.
    assert ordered[-1] - ordered[0] > 0.3, (
        f"recovered h2 spans only {ordered[-1] - ordered[0]:.3f} across true h2 "
        f"{sorted(TRUE_H2)} — the simulation is barely responding to heritability"
    )
