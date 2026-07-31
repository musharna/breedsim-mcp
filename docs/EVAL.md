# Eval — checking the simulation against theory, not against itself

Every other test in this repo checks that the code does what the code intends.
A regression test can tell you a number stopped changing; it cannot tell you the
number is wrong. This file records the checks that compare the simulator to
something outside it.

## The breeder's equation

    R = h² · S

Response to selection equals narrow-sense heritability times the selection
differential. `addTraitA` builds a purely additive trait, so the `h2` handed to
`setVarE` **is** the narrow-sense heritability and the identity should hold in
expectation.

The eval recovers h² as `R / S` and compares it to the value the trait was built
with. The answer was fixed before the simulator ran — by theory, not by a
previous version of this code.

### Measured

Calibration run, 20 replicates, 500 founders, 50 selected, 10 chromosomes ×
100 segregating sites, 10 QTL per chromosome:

| true h² | recovered R/S | sd     | relative error |
| ------- | ------------- | ------ | -------------- |
| 0.2     | 0.1987        | 0.0333 | 0.64%          |
| 0.5     | 0.4875        | 0.0280 | 2.50%          |
| 0.8     | 0.7950        | 0.0324 | 0.62%          |

The committed eval (`tests/test_eval_breeders_equation.py`) runs a cheaper
configuration — 12 replicates of 300 founders — with the tolerance widened to
match, rather than the population being quietly shrunk under a tolerance
calibrated at a different size.

### Why there are two assertions

Agreement at one setting is weak evidence: a simulator that ignored h² entirely
and returned some fixed ratio could sit inside the tolerance by luck. The second
assertion requires the recovered value to **rise with** the true one, which no
constant can satisfy. That is what separates "the identity holds" from "one
number happened to land close".

### Seen to fail

An eval nobody has watched fail is decoration. Three mutants, each a plausible
way to get this wrong, all confirmed RED:

| mutant                                                                  | result |
| ----------------------------------------------------------------------- | ------ |
| selection is random rather than on phenotype                            | RED    |
| response measured against the selected parents, not the base population | RED    |
| selection differential taken on genetic value instead of phenotype      | RED    |

The third is the subtle one. Using genetic values for `S` looks more "correct" —
it removes environmental noise — and yields a ratio near 1 regardless of h².
That is precisely the number the equation says should be h², so the mistake
produces a confident, wrong, stable answer. The tracking assertion is what
catches it.

## Not covered

Genomic selection has no closed-form reference of this kind: prediction accuracy
depends on marker–QTL linkage disequilibrium, effective population size and
training design, with no single identity to check against. What the server does
instead is report accuracy **out-of-sample**, on progeny the fitted model never
saw, and measure founder LD directly rather than assuming it.

Multi-trait index selection is checked behaviourally — the weights must change
which trait gains — rather than against a closed form.
