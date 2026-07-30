# breedsim-mcp

**Breeding-scheme simulation over MCP — returns distributions, never a single stochastic run.**

Drives [AlphaSimR](https://github.com/gaynorr/AlphaSimR) so an agent can ask what a selection
programme would actually gain, with one structural rule: **a single simulation run is not a
result, and this API will not return one.**

Measured on AlphaSimR 2.1.0 — five seeds of an identical three-cycle programme gave mean
genetic gain `[1.151, 1.841, 1.424, 1.429, 1.473]`: **sd 0.247** on the very number being
reported. Quoting one run to three decimals reports noise with the authority of a measurement.
So `run_program` enforces a replicate floor and returns per-cycle mean, sd and confidence
interval. There is no flag that collapses it to a point estimate.

> Unofficial. Not affiliated with, endorsed by, or sponsored by the AlphaSimR authors, the
> University of Edinburgh, or the R Foundation. See [NOTICE](NOTICE).

## Status

[![ci](https://github.com/musharna/breedsim-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/musharna/breedsim-mcp/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/breedsim-mcp)](https://pypi.org/project/breedsim-mcp/)

On PyPI — the badge above is the released version, so it cannot go stale the way
a number typed here would. Genomic selection included. 5 tools, 57 tests against
real AlphaSimR, and 20 mutation checks all confirmed red
([docs/MUTATION-CHECKS.md](docs/MUTATION-CHECKS.md)). CI installs R and compiles
AlphaSimR, so the suite runs against the real engine on Python 3.11, 3.12 and 3.13 —
not against a mock.

Requires `mcp` 2.x.

## Install tax — read this first

Heavier than `uv pip install`, and the reasons are not negotiable:

- **R ≥ 4.3** with a shared library (`libR.so`)
- **AlphaSimR** — an Rcpp/RcppArmadillo compile, minutes not seconds
- **`libtirpc-dev`** — rpy2 fails to link without it (`cannot find -ltirpc`)
- **rpy2 pinned `<3.6`** — 3.6 binds `R_getVar`, which needs R ≥ 4.4

```bash
sudo apt-get install -y r-base r-base-dev libtirpc-dev
R -e 'install.packages("AlphaSimR", repos="https://cloud.r-project.org")'
uv add breedsim-mcp
```

If you build against a **conda** Python, rpy2 will fail to load `libR.so` with
`GLIBCXX_3.4.30 not found` — conda ships an older `libstdc++` than system `libicuuc`
requires. Use a system or uv-managed interpreter.

## Configure your MCP client

The server speaks stdio; the installed console script is `breedsim-mcp`.

**Claude Code**

```bash
claude mcp add breedsim -- breedsim-mcp
```

**Claude Desktop** — add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "breedsim": {
      "command": "breedsim-mcp"
    }
  }
}
```

If the executable is not on your `PATH`, or AlphaSimR lives in a user library, invoke it
through uv and pass the library path:

```json
{
  "mcpServers": {
    "breedsim": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/breedsim-mcp", "breedsim-mcp"],
      "env": { "R_LIBS_USER": "/home/you/R/library" }
    }
  }
}
```

Verify with `list_methods()`, which reports the engine versions **and whether this process
can currently produce reproducible results**.

## Tools

| tool                                                           | returns                                                           |
| -------------------------------------------------------------- | ----------------------------------------------------------------- |
| `list_methods()`                                               | engine versions, generators, selection methods, replicate floor   |
| `found_population(generator, seed, n_ind, n_snp_per_chr, ...)` | `session_id`, founder provenance, `reproducible`, measured **LD** |
| `run_program(session_id, cycles, replicates, ...)`             | per-cycle **distributions** — mean, sd, 95% CI                    |
| `compare_programs(session_id, a_n_select, b_n_select, ...)`    | the **paired difference** between two programmes, with a CI       |
| `describe_session(session_id)`                                 | provenance, trait architecture, cycles run                        |

Typical loop: `found_population` → `run_program` → read the CI and the warnings.
Comparing two schemes: `found_population` → `compare_programs` → read `difference`.
Both run tools take `selection_method="phenotypic"` or `"genomic"`.

### Species

`species` applies only to `runMacs`, which carries demographic histories for exactly
four: **`GENERIC`, `CATTLE`, `WHEAT`, `MAIZE`** (read out of `body(runMacs)`, not the
docs). Anything else is refused here rather than failing inside R. Casing does not
matter — AlphaSimR upper-cases it, so this does too.

Note the scope that implies: **two plants and an animal.** Despite the default of
`MAIZE`, this is not a plant-only simulator.

### Limits

Every size parameter has a ceiling, reported by `list_methods()` under `limits` so a
caller can size a request rather than discover the bound by being refused. R runs as a
single interpreter here and tool calls are serialised, so one oversized call blocks every
other call until it finishes — there is no second worker. The caps are set where a call
stops being slow and starts being an outage. For genuinely large jobs, drive AlphaSimR
directly rather than through this server.

### What `run_program` returns

Verbatim, for `cycles=2, replicates=10`, abridged to one cycle:

```json
{
  "session_id": "bs-...",
  "replicates": 10,
  "cycles": [
    {
      "cycle": 2,
      "genetic_gain": {
        "mean": 1.5941703785773211,
        "sd": 0.1414620049281876,
        "ci_low": 1.4929815869737013,
        "ci_high": 1.695359170180941,
        "n": 10
      },
      "genetic_variance": {
        "mean": 0.5149269761002959,
        "sd": 0.15228915685789685,
        "ci_low": 0.4059934446929936,
        "ci_high": 0.6238605075075982,
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
    "base_seed": 1000
  },
  "warnings": []
}
```

There is no `value` field anywhere. Intervals use **t** critical values rather than a normal
1.96, because at n = 5–10 the normal understates the interval — the wrong direction to be
wrong in when the interval exists to be honest.

### Comparing two programmes

Do **not** call `run_program` twice and compare the means. Use `compare_programs`, which
pairs the two arms on the same seeds — replicate _i_ of A and replicate _i_ of B start from
identical founders under an identical seed — and differences them **within** each pair, so
the shared luck of that seed cancels instead of being counted twice.

Read `difference` and `favours`. `favours` is `null` when the interval contains zero, which
means the two programmes are not distinguishable at that replicate count; the larger mean is
then not the better programme.

Here is why the pairing earns its keep. Verbatim, selecting 12 of 100 against 18 of 100,
final cycle of two, ten replicates:

```json
{
  "programs": {
    "a": { "label": "A", "n_select": 12, "n_cross": 100 },
    "b": { "label": "B", "n_select": 18, "n_cross": 100 }
  },
  "cycles": [
    {
      "cycle": 2,
      "a_genetic_gain": {
        "mean": 2.046227841067686,
        "ci_low": 1.9001469542399823,
        "ci_high": 2.1923087278953903,
        "n": 10
      },
      "b_genetic_gain": {
        "mean": 1.730473406465538,
        "ci_low": 1.5520780571733739,
        "ci_high": 1.9088687557577022,
        "n": 10
      },
      "difference": {
        "mean": 0.31575443460214814,
        "ci_low": 0.10028439648886733,
        "ci_high": 0.5312244727154289,
        "n": 10
      }
    }
  ],
  "favours": "a",
  "intervals_overlap": true,
  "warnings": [{ "code": "overlap_but_different", "message": "..." }]
}
```

**The two per-programme intervals overlap** — A spans 1.900–2.192, B spans 1.552–1.909 — so
reading them side by side says "no difference". The paired difference says otherwise:
`[+0.100, +0.531]`, entirely above zero. Pairing cancels the seed-to-seed variation that
made both individual intervals wide, so it resolves a contrast that eyeballing the overlap
cannot. That is what `overlap_but_different` is for.

**Two overlapping confidence intervals do not imply no difference.** This is the single
easiest way to get a breeding comparison wrong, and it is why the tool reports a difference
rather than two numbers.

### Genomic selection — and the trap under it

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
the only reproducible one, **has none**:

| generator    | mean \|r\| adjacent SNP | mean \|r\| distant pairs | ratio    | out-of-sample accuracy |
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

#### Why the guard measures LD instead of accuracy

The obvious alternative — fit the model, warn if accuracy is poor — cannot do the
job. Measured at 20 replicates, 200 individuals, three cycles:

| selection | `quickHaplo` (LD ratio 1.00) | `runMacs` (LD ratio 3.7)  |
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
progeny the model never saw — reporting its in-sample fit instead would have read
0.448 where the truth was 0.097. Read it as a property of the model in front of
you, not as proof that genomic selection is working for the reason you assume.

### Warnings

| code                           | meaning                                                                  |
| ------------------------------ | ------------------------------------------------------------------------ |
| `nondeterministic_founders`    | founders came from `runMacs`; a repeat call will differ                  |
| `no_linkage_disequilibrium`    | founder markers carry no linkage; genomic prediction cannot work here    |
| `prediction_accuracy_low`      | the marker model is not predicting — gain came from drift, not selection |
| `difference_indistinguishable` | the paired difference interval contains zero — no winner at this n       |
| `overlap_but_different`        | the per-arm intervals overlap but the paired difference resolves         |
| `threads_not_pinned`           | `OMP_NUM_THREADS != 1`, so the same seed will not reproduce              |
| `replicates_too_few`           | the CI is wide relative to the effect — too wide to support a comparison |
| `variance_exhausted`           | genetic variance has collapsed; a still-rising mean is a plateau         |

None of these withhold results. Outputs are always distributions, so you can already see when
an answer is too noisy to use — they explain rather than refuse.

## Reproducibility

Two independent things break it, and both were measured:

| source                | symptom                                         | fix                                          |
| --------------------- | ----------------------------------------------- | -------------------------------------------- |
| `runMacs` founder RNG | a **repeat** seeded call in one session differs | use `quickHaplo`                             |
| OpenMP in selection   | same seed, fixed founders → 2.397 vs 2.125      | `OMP_NUM_THREADS=1` **before R initialises** |

The `runMacs` case is subtler than "it ignores the seed". Its MaCS RNG is seeded **once per R
session** and advances across calls, so the same call _sequence_ reproduces in a fresh process
while a repeat call inside one session does not. Since this server is a long-lived process,
the repeat case is the one you hit — hence `reproducible: false`.

The server pins threads at import, before rpy2 loads, and reports whether it succeeded. With
founders fixed and threads pinned, seed 7 reproduces exactly: `meanG=2.01451853`, twice.

## Limitations

No multi-trait or G×E, no optimal contribution selection, no crossing-block optimisation, no
genotype-matrix export. Genomic selection is RRBLUP only — the `RRBLUP_D`, `_GCA` and `_SCA`
variants AlphaSimR provides for dominance and combining ability are not exposed. Selection is
truncation on a single trait, by phenotype or by estimated breeding value.

The `prediction_accuracy_low` and `no_linkage_disequilibrium` warnings are advisory: like every
other warning here, they explain rather than refuse.

Sessions are in-memory and capped (8, LRU); they do not survive a restart.

## Licence

**GPL-3.0-or-later** — because this imports rpy2, which is GPLv2+. AlphaSimR itself is MIT;
the licence here is about rpy2, not about AlphaSimR. See [NOTICE](NOTICE).

## More

- [CHANGELOG.md](CHANGELOG.md) — what changed, and why
- [docs/MUTATION-CHECKS.md](docs/MUTATION-CHECKS.md) — every guard disabled on purpose, and
  the test that went red for it
