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

Phase 1 complete: 4 tools, 30 tests against real AlphaSimR, 12 mutation checks all confirmed
red ([docs/MUTATION-CHECKS.md](docs/MUTATION-CHECKS.md)). CI installs R and compiles
AlphaSimR, so the suite runs against the real engine on Python 3.11, 3.12 and 3.13 — not
against a mock.

Not on PyPI; install from git (below).

## Install tax — read this first

Heavier than `uv pip install`, and the reasons are not negotiable:

- **R ≥ 4.3** with a shared library (`libR.so`)
- **AlphaSimR** — an Rcpp/RcppArmadillo compile, minutes not seconds
- **`libtirpc-dev`** — rpy2 fails to link without it (`cannot find -ltirpc`)
- **rpy2 pinned `<3.6`** — 3.6 binds `R_getVar`, which needs R ≥ 4.4

```bash
sudo apt-get install -y r-base r-base-dev libtirpc-dev
R -e 'install.packages("AlphaSimR", repos="https://cloud.r-project.org")'
uv add git+https://github.com/musharna/breedsim-mcp
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

| tool                                                   | returns                                                          |
| ------------------------------------------------------ | ---------------------------------------------------------------- |
| `list_methods()`                                       | engine versions, generators, replicate floor, determinism status |
| `found_population(generator, seed, n_ind, n_chr, ...)` | `session_id` + founder provenance + `reproducible`               |
| `run_program(session_id, cycles, replicates, ...)`     | per-cycle **distributions** — mean, sd, 95% CI                   |
| `describe_session(session_id)`                         | provenance, trait architecture, cycles run                       |

Typical loop: `found_population` → `run_program` → read the CI and the warnings.

### Species

`species` applies only to `runMacs`, which carries demographic histories for exactly
four: **`GENERIC`, `CATTLE`, `WHEAT`, `MAIZE`** (read out of `body(runMacs)`, not the
docs). Anything else is refused here rather than failing inside R. Casing does not
matter — AlphaSimR upper-cases it, so this does too.

Note the scope that implies: **two plants and an animal.** Despite the default of
`MAIZE`, this is not a plant-only simulator.

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

### Warnings

| code                        | meaning                                                                  |
| --------------------------- | ------------------------------------------------------------------------ |
| `nondeterministic_founders` | founders came from `runMacs`; a repeat call will differ                  |
| `threads_not_pinned`        | `OMP_NUM_THREADS != 1`, so the same seed will not reproduce              |
| `replicates_too_few`        | the CI is wide relative to the effect — too wide to support a comparison |
| `variance_exhausted`        | genetic variance has collapsed; a still-rising mean is a plateau         |

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

## Limitations (phase 1)

No genomic selection models (GBLUP/RR-BLUP), no multi-trait or G×E, no optimal contribution
selection, no crossing-block optimisation, no genotype-matrix export. Truncation selection on
phenotype only. Phase 2 adds genomic selection and `compare_programs` for a paired A/B.

Sessions are in-memory and capped (8, LRU); they do not survive a restart.

## Licence

**GPL-3.0-or-later** — because this imports rpy2, which is GPLv2+. AlphaSimR itself is MIT;
the licence here is about rpy2, not about AlphaSimR. See [NOTICE](NOTICE).

## More

- [CHANGELOG.md](CHANGELOG.md) — what changed, and why
- [docs/MUTATION-CHECKS.md](docs/MUTATION-CHECKS.md) — every guard disabled on purpose, and
  the test that went red for it
