# Reference

Detail behind the [README](../README.md): tool signatures, species and size limits,
example outputs, the paired comparison, genomic selection and its LD guard, the
warnings, and reproducibility.

## Tool signatures

Defaults as in `src/breedsim_mcp/server.py`; `replicates` defaults to 10 and may not
go below 5.

```python
list_methods()
found_population(
    generator="quickHaplo", seed=1, n_ind=100, n_chr=10, seg_sites=100,
    n_qtl_per_chr=10, h2=0.4, species="MAIZE", n_snp_per_chr=0,
    trait_correlation=0.0,
)  # h2 may be a list, one value per trait
run_program(
    session_id, cycles=3, replicates=10, n_select=10, n_cross=None,
    base_seed=1000, selection_method="phenotypic", index_weights=None,
    final_only=False,
)
compare_programs(
    session_id, a_n_select=10, b_n_select=25, cycles=3, replicates=10,
    a_n_cross=None, b_n_cross=None, base_seed=1000, a_label="A", b_label="B",
    a_selection_method="phenotypic", b_selection_method="phenotypic",
    final_only=False,
)
describe_session(session_id)
```

`final_only=True` returns only the last cycle; the warnings still read every cycle.
Every float in a response is rounded to 4 significant figures, far inside the Monte
Carlo error of these estimates (the library itself returns full precision).

## Species

`species` applies only to `runMacs`, which carries demographic histories for exactly
four: **`GENERIC`, `CATTLE`, `WHEAT`, `MAIZE`** (read out of `body(runMacs)`, not the
docs). Anything else is refused here rather than failing inside R. Casing does not
matter — AlphaSimR upper-cases it, so this does too.

Note the scope that implies: **two plants and an animal.** Despite the default of
`MAIZE`, this is not a plant-only simulator.

## Limits

Every size parameter has a ceiling, reported by `list_methods()` under `limits` so a
caller can size a request rather than discover the bound by being refused. R runs as a
single interpreter here and tool calls are serialized, so one oversized call blocks every
other call until it finishes — there is no second worker. The caps are set where a call
stops being slow and starts being an outage. For genuinely large jobs, drive AlphaSimR
directly rather than through this server.

## What `run_program` returns

Example output (AlphaSimR 2.1.0) from `found_population(generator="quickHaplo",
seed=1)` with every other argument at its default, then `run_program(session_id,
cycles=2, replicates=10, n_select=10, n_cross=60, base_seed=1000)`. Abridged to cycle 2;
the session id is elided. Regenerate it with `uv run python scripts/readme_examples.py`.

```json
{
  "session_id": "bs-...",
  "replicates": 10,
  "cycles": [
    {
      "cycle": 2,
      "genetic_gain": {
        "mean": 2.011,
        "sd": 0.3861,
        "ci_low": 1.734,
        "ci_high": 2.287,
        "n": 10
      },
      "genetic_variance": {
        "mean": 0.6598,
        "sd": 0.1739,
        "ci_low": 0.5355,
        "ci_high": 0.7842,
        "n": 10
      }
    }
  ],
  "reproducible": true,
  "recipe": {
    "generator": "quickHaplo",
    "seed": 1,
    "n_select": 10,
    "n_cross": 60,
    "base_seed": 1000,
    "selection_method": "phenotypic",
    "n_traits": 1,
    "index_weights": null,
    "engine": {
      "r_version": "R version 4.3.3 (2024-02-29)",
      "alphasimr_version": "2.1.0",
      "rpy2_version": "3.5.17"
    },
    "gain_scale": "founder additive genetic SD (trait variance set to 1 at founding)"
  },
  "warnings": []
}
```

There is no `value` field anywhere. Intervals use **t** critical values rather than a normal
1.96, because at n = 5–10 the normal understates the interval — the wrong direction to be
wrong in when the interval exists to be honest.

## Comparing two programs

Do **not** call `run_program` twice and compare the means. Use `compare_programs`, which
pairs the two arms on the same seeds — replicate _i_ of A and replicate _i_ of B start from
identical founders under an identical seed — and differences them **within** each pair, so
the shared luck of that seed cancels instead of being counted twice.

Read `difference` and `favours`. `favours` is `null` when the interval contains zero, which
means the two programs are not distinguishable at that replicate count; the larger mean is
then not the better program.

Here is why the pairing earns its keep. Example output (AlphaSimR 2.1.0) from
`found_population(generator="quickHaplo", seed=1)` with every other argument at its default
(100 individuals), then `compare_programs(session_id, a_n_select=12, b_n_select=18,
a_n_cross=100, b_n_cross=100, cycles=2, replicates=10)`: selecting 12 of 100 against 18 of
100. Abridged to the final cycle, with the `sd` fields, `session_id` and the warning text
elided; `scripts/readme_examples.py` prints it in full.

```json
{
  "replicates": 10,
  "paired": true,
  "programs": {
    "a": { "label": "A", "n_select": 12, "n_cross": 100, "selection_method": "phenotypic" },
    "b": { "label": "B", "n_select": 18, "n_cross": 100, "selection_method": "phenotypic" }
  },
  "cycles": [
    {
      "cycle": 2,
      "a_genetic_gain": {
        "mean": 2.03,
        "ci_low": 1.839,
        "ci_high": 2.221,
        "n": 10
      },
      "b_genetic_gain": {
        "mean": 1.717,
        "ci_low": 1.572,
        "ci_high": 1.861,
        "n": 10
      },
      "difference": {
        "mean": 0.3135,
        "ci_low": 0.1475,
        "ci_high": 0.4795,
        "n": 10
      }
    }
  ],
  "difference_is": "a_minus_b_final_cycle_genetic_gain",
  "favours": "a",
  "intervals_overlap": true,
  "reproducible": true,
  "recipe": { "generator": "quickHaplo", "seed": 1, "base_seed": 1000, "cycles": 2 },
  "warnings": [{ "code": "overlap_but_different", "message": "..." }]
}
```

**The two per-program intervals overlap** — A spans 1.839–2.221, B spans 1.572–1.861 — so
reading them side by side says "no difference". The paired difference says otherwise:
`[+0.148, +0.480]`, entirely above zero. Pairing cancels the seed-to-seed variation that
made both individual intervals wide, so it resolves a contrast that eyeballing the overlap
cannot. That is what `overlap_but_different` is for.

**Two overlapping confidence intervals do not imply no difference.** This is the single
easiest way to get a breeding comparison wrong, and it is why the tool reports a difference
rather than two numbers.

## Genomic selection — and the trap under it

`selection_method="genomic"` fits RRBLUP to the marker genotypes each cycle and
selects on the estimated breeding value instead of the phenotype. It needs a SNP
chip, which is a **founding** decision:

```python
found_population(generator="runMacs", n_snp_per_chr=50)  # note the generator
run_program(session_id, selection_method="genomic")
```

Note the generator, because this is where genomic selection goes quietly wrong.
Markers predict a trait only through **linkage disequilibrium** with the causal
loci — that is the whole mechanism. And `quickHaplo`, the default generator and
the only reproducible one, **has none**. Measured once while building v0.2.0
(2026-07-29, AlphaSimR 2.1.0; 10 chromosomes × 100 segregating sites, 50 SNPs per
chromosome, accuracy at 500 founders) and not re-run since:

| Generator    | Mean \|r\| adjacent SNP | Mean \|r\| distant pairs | Ratio    | Out-of-sample accuracy |
| ------------ | ----------------------- | ------------------------ | -------- | ---------------------- |
| `quickHaplo` | 0.0444                  | 0.0462                   | **0.96** | 0.097                  |
| `runMacs`    | 0.1979                  | 0.0495                   | **4.00** | 0.351                  |

Adjacent markers in `quickHaplo` are no more correlated than randomly chosen
distant ones — it samples haplotypes with no coalescent history, so there is no
linkage to learn from. Every `found_population` call with a chip therefore returns
a measured `linkage_disequilibrium` block, and a `no_linkage_disequilibrium`
warning when the ratio says the markers are uninformative.

**So on this engine, reproducibility and genomic realism cannot be had at the same
time.** `quickHaplo` reproduces and cannot support genomic selection; `runMacs`
supports it and does not reproduce in a long-lived process. That is a real
constraint of the underlying simulator, and the server states it rather than
letting you find it as a wrong answer.

### Why the guard measures LD instead of accuracy

The obvious alternative — fit the model, warn if accuracy is poor — cannot do the
job. Measured once while building v0.2.0 (2026-07-29, AlphaSimR 2.1.0) at 20
replicates, 200 individuals, three cycles, and not re-run since:

| Selection | `quickHaplo` (LD ratio 1.00) | `runMacs` (LD ratio 3.7)  |
| --------- | ---------------------------- | ------------------------- |
| 10% kept  | 0.104 → 0.159 → **0.208**    | 0.105 → 0.130 → 0.167     |
| 50% kept  | 0.162 → 0.207 → 0.226        | 0.217 → 0.257 → **0.253** |

A population with **no linkage disequilibrium at all reaches 0.208**, and at 10%
selection it beats the population that has real LD. Accuracy also climbs every
cycle in both. Neither is a paradox: out-of-sample accuracy in a closed population
conflates LD with the causal loci and plain **relatedness** between training and
target individuals. As descendants of a few selected parents fill the population,
markers predict by tracking pedigree — and `quickHaplo`'s mutually uncorrelated
markers tag pedigree _more_ efficiently than `runMacs`' markers, which are partly
redundant with each other precisely because they are in LD.

An accuracy threshold would therefore wave through the exact population it claimed
to catch. Only the LD measurement discriminates, so that is what gates the warning.
Accuracy is still reported on every genomic cycle, measured **out-of-sample** on
progeny the model never saw. In the same v0.2.0 measurement, the in-sample fit read
0.448 where the out-of-sample accuracy was 0.097. Read it as a property of the model in front of
you, not as proof that genomic selection is working for the reason you assume.

## Warnings

| Code                           | Meaning                                                                  |
| ------------------------------ | ------------------------------------------------------------------------ |
| `nondeterministic_founders`    | founders came from `runMacs`; a repeat call will differ                  |
| `no_linkage_disequilibrium`    | founder markers carry no linkage; genomic prediction cannot work here    |
| `prediction_accuracy_low`      | the marker model is not predicting — gain came from drift, not selection |
| `difference_indistinguishable` | the paired difference interval contains zero — no winner at this n       |
| `overlap_but_different`        | the per-arm intervals overlap but the paired difference resolves         |
| `threads_not_pinned`           | `OMP_NUM_THREADS != 1`, so the same seed will not reproduce              |
| `replicates_too_few`           | the CI is wide relative to the effect — too wide to support a comparison |
| `variance_exhausted`           | genetic variance is ≤20% of the founders'; a rising mean is a plateau    |

None of these withhold results. Outputs are always distributions, so you can already see when
an answer is too noisy to use — they explain rather than refuse.

## Reproducibility

Two independent things break it. Both were measured once while building v0.1.0
(2026-07-29, AlphaSimR 2.1.0); the numbers below are from that run:

| Source                | Symptom                                         | Fix                                          |
| --------------------- | ----------------------------------------------- | -------------------------------------------- |
| `runMacs` founder RNG | a **repeat** seeded call in one session differs | use `quickHaplo`                             |
| OpenMP in selection   | same seed, fixed founders → 2.397 vs 2.125      | `OMP_NUM_THREADS=1` **before R initializes** |

The `runMacs` case is subtler than "it ignores the seed". Its MaCS RNG is seeded **once per R
session** and advances across calls, so the same call _sequence_ reproduces in a fresh process
while a repeat call inside one session does not. Since this server is a long-lived process,
the repeat case is the one you hit — hence `reproducible: false`.

The server pins threads at import, before rpy2 loads, and reports whether it succeeded. With
founders fixed and threads pinned, seed 7 reproduces exactly: `meanG=2.01451853`, twice.
