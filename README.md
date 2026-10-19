# breedsim-mcp

breedsim-mcp is an MCP server that lets AI agents run [AlphaSimR](https://github.com/gaynorr/AlphaSimR)
breeding-program simulations. It returns the spread over replicates, never a single stochastic
run, so an agent can say what a selection scheme would gain and how sure that is.

[![CI](https://img.shields.io/github/actions/workflow/status/musharna/breedsim-mcp/ci.yml?branch=master&label=CI)](https://github.com/musharna/breedsim-mcp/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/breedsim-mcp)](https://pypi.org/project/breedsim-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/breedsim-mcp)](https://pypi.org/project/breedsim-mcp/)
[![License](https://img.shields.io/pypi/l/breedsim-mcp)](LICENSE)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21713210.svg)](https://doi.org/10.5281/zenodo.21713210)
[![Glama](https://glama.ai/mcp/servers/musharna/breedsim-mcp/badges/score.svg)](https://glama.ai/mcp/servers/musharna/breedsim-mcp)

<!-- mcp-name: io.github.musharna/breedsim-mcp -->

## Does it help?

Yes, compared with Claude alone. Compared with Claude writing its own AlphaSimR scripts, it
is not measurably more accurate and costs more.

<p align="center">
  <img src="https://raw.githubusercontent.com/musharna/breedsim-mcp/master/benchmarks/agent_qa/agent_qa.png" width="780"
       alt="Stacked bar chart of right and wrong answers to 34 breeding-simulation questions, 3 runs each. Claude alone: 51 right, 51 wrong. Claude with Bash, R and web: 99 right, 3 wrong. Claude with breedsim-mcp: 102 right, 0 wrong. No-LLM baselines, one answer per question: one constant per kind of question, 12 right and 22 wrong; best closed form per question, 15 right and 19 wrong.">
</p>

Claude Opus 5.5 answered 34 breeding-simulation questions three times each, keyed by
AlphaSimR run directly; the best named formula lands in only 15 of 34. With this server
Claude got 102 of 102 right, with its own R and AlphaSimR 99 of 102 (not separated, exact
McNemar p = 1.0), and alone 51 of 102 (both tool setups beat it, p < 1e-6). It still costs
more than Claude's own scripts. A pre-registered re-run on 2026-10-18, with an unreleased
commit that cut the server's instructions and rounded its outputs, got 102 of 102 right in
both setups and lowered the server's median cost per answer from $0.051 to $0.033, but Claude's
own scripts cost $0.027, cheaper on all 34 questions (p = 1e-10). Time is not separated.

Each question spells out the AlphaSimR calls, so this tests running a stated simulation, not
designing one unaided; method, controls, other limitations, and six probability questions
reported separately are in [benchmarks/agent_qa](benchmarks/agent_qa/README.md).

## Why replicates

A single simulation run is not a result, and this API will not return one. Five seeds of an
identical three-cycle program gave mean genetic gain `[1.151, 1.841, 1.424, 1.429, 1.473]`,
sd 0.247, on the very number being reported (measured once on AlphaSimR 2.1.0 while
building v0.1.0, 2026-07-29). So `run_program` enforces a replicate floor and returns a
per-cycle mean, sd and confidence interval. No flag collapses it to a point estimate.

## Install

This needs more than `uv pip install`:

- **R ≥ 4.3** with a shared library (`libR.so`)
- **AlphaSimR**, an Rcpp/RcppArmadillo compile that takes minutes
- **`libtirpc-dev`**, or rpy2 fails to link (`cannot find -ltirpc`)
- **rpy2 `<3.6`**, because 3.6 binds `R_getVar`, which needs R ≥ 4.4

```bash
sudo apt-get install -y r-base r-base-dev libtirpc-dev
R -e 'install.packages("AlphaSimR", repos="https://cloud.r-project.org")'
uv add breedsim-mcp
```

Do not use a **conda** Python: rpy2 then fails to load `libR.so` with
`GLIBCXX_3.4.30 not found`, because conda ships an older `libstdc++` than the system
`libicuuc` requires. Use a system or uv-managed interpreter. Requires `mcp` 2.x.

## Configure your MCP client

The server speaks stdio through the `breedsim-mcp` console script.

**Claude Code**

```bash
claude mcp add breedsim -- breedsim-mcp
```

**Claude Desktop** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "breedsim": {
      "command": "breedsim-mcp"
    }
  }
}
```

If the executable is not on your `PATH`, or AlphaSimR lives in a user library, run it
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

Check it with `list_methods()`, which reports the engine versions **and whether this process
can currently produce reproducible results**.

## Tools

| Tool               | Returns                                                           |
| ------------------ | ----------------------------------------------------------------- |
| `list_methods`     | engine versions, generators, selection methods, replicate floor   |
| `found_population` | `session_id`, founder provenance, `reproducible`, measured **LD** |
| `run_program`      | per-cycle **distributions**: mean, sd, 95% CI                     |
| `compare_programs` | the **paired difference** between two programs, with a CI         |
| `describe_session` | provenance, trait architecture, cycles run                        |

Typical loop: `found_population` → `run_program` → read the CI and the warnings. To compare
two schemes: `found_population` → `compare_programs` → read `difference`. `run_program`
takes `selection_method="phenotypic"` or `"genomic"`; `compare_programs` takes one per arm.

[docs/REFERENCE.md](docs/REFERENCE.md) has the full tool signatures, example outputs, the
warnings table, and the measurements behind the points below.

- **Compare with `compare_programs`, not two `run_program` calls.** It runs both arms on
  the same seeds and differences them within each pair, so shared luck cancels. Two
  overlapping per-program intervals do not imply no difference; the paired interval can
  still exclude zero (warning `overlap_but_different`). `favours` is `null` when the paired
  interval contains zero.
- **Genomic selection needs linkage disequilibrium.** `selection_method="genomic"` fits
  RRBLUP to a SNP chip set at founding (`n_snp_per_chr`). `quickHaplo`, the default and the
  only reproducible generator, has no LD, so use `runMacs`, which does not reproduce in a
  long-lived process. On this engine you cannot have both. `found_population` measures LD
  and warns (`no_linkage_disequilibrium`) when the markers are uninformative.
- **Reproducibility.** The server pins `OMP_NUM_THREADS=1` at import, before R starts;
  without it the same seed gives different results. The `runMacs` RNG is seeded once per R
  session and advances across calls, so a repeat call in this long-lived process differs
  (`reproducible: false`).
- **Warnings explain; none of them withhold results.**
- **Multi-trait selection.** Pass `h2` as a list and `index_weights` to select on a
  weighted index. `trait_correlation` must be a real correlation matrix (for n equally
  correlated traits, not below −1/(n−1)); an invalid one is refused, not replaced by the
  nearest valid matrix. Genomic selection fits one RRBLUP model per trait, applies the index
  to the estimated breeding values, and reports `prediction_accuracy` in each `traits`
  entry.
- **Species.** `species` applies only to `runMacs`, which has demographic histories for
  `GENERIC`, `CATTLE`, `WHEAT` and `MAIZE`; anything else is refused. The default is
  `MAIZE`, but this is not a plant-only simulator.
- **Limits.** Every size parameter has a ceiling, listed by `list_methods()` under
  `limits`. R is a single interpreter and calls are serialized, so one oversized call would
  block every other. For large jobs, drive AlphaSimR directly.

## Testing

CI installs R and compiles AlphaSimR, so the suite runs against the real engine on Python
3.11, 3.12 and 3.13. One test checks the R engine layer against the breeder's equation
`R = h²S` ([docs/EVAL.md](docs/EVAL.md)); it does not test this server's founding or
selection code against an outside reference. [docs/MUTATION-CHECKS.md](docs/MUTATION-CHECKS.md)
records 25 deliberate mutants: 24 turned a test red, and one survives because it is
equivalent. `tests/test_perf_ratchet.py` gates each tool on exact counts of package-function
calls and R evaluations, not on time.

## Limitations

- `compare_programs` is single-trait: one paired verdict needs one criterion, and with
  several traits that is the index, for which AlphaSimR reports no gain.
- No G×E, optimal contribution selection, crossing-block optimization or genotype-matrix
  export.
- Genomic selection is RRBLUP only. `RRBLUP_D`, `_GCA` and `_SCA` estimate dominance and
  combining-ability effects that the additive-only `addTraitA` architecture does not have.
- Sessions are in memory, capped at 8 (LRU), and do not survive a restart.

## License

**GPL-3.0-or-later**, because this imports rpy2, which is GPLv2+. AlphaSimR itself is MIT.
Unofficial: not affiliated with, endorsed by, or sponsored by the AlphaSimR authors, the
University of Edinburgh, or the R Foundation. See [NOTICE](NOTICE).

[CHANGELOG.md](CHANGELOG.md) records what changed and why.
