# Changelog

All notable changes to `breedsim-mcp` are recorded here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Phase 1. Breeding-scheme simulation over MCP, driving AlphaSimR 2.1.0 through rpy2.

### Added

- Four MCP tools — `list_methods`, `found_population`, `run_program`,
  `describe_session` — each publishing a title, read-only annotations and an
  `outputSchema` derived from a typed return.
- **The structural rule: `run_program` will not return a single run.** It enforces a
  replicate floor and returns per-cycle mean, sd and 95% confidence interval. There is
  no `replicates=1` and no `raw=True`. The floor is not arbitrary — five seeds of an
  identical three-cycle programme gave genetic gains of
  `[1.151, 1.841, 1.424, 1.429, 1.473]`: **sd 0.247**, the same order as the effects
  people compare. One run is a draw, not an answer.
- Confidence intervals use t critical values rather than a normal 1.96, because at
  n = 5–10 the normal understates the interval — the wrong direction to be wrong in
  when the interval exists to be honest.
- **Reproducibility reporting.** Every response carries `reproducible`, and when false,
  why. Two independent sources were measured:
  - `runMacs` founders — MaCS's RNG is seeded once per R **session** and advances across
    calls, so `set.seed` does not reset it. A repeat call with the same seed in a
    long-lived server process yields different founders. (Across fresh processes the
    same call _sequence_ does reproduce — the claim is narrower than "ignores the seed".)
  - **OpenMP** — with founders fixed, pinned threads give `meanG=2.01451853` twice while
    unpinned gives 2.397 then 2.125. `engine` pins `OMP_NUM_THREADS=1` at import, before
    rpy2 loads, because R reads it when OpenMP initialises.
- Four advisories: `nondeterministic_founders`, `threads_not_pinned`,
  `replicates_too_few` (relative CI width, since ±0.4 is fine around 10 and useless
  around 0.5), and `variance_exhausted` (a still-rising mean past variance collapse is a
  plateau, not progress).
- Precise install errors naming the missing piece and the command that fixes it. The
  server never installs R packages for you.
- 27 tests against real AlphaSimR — no mocked R — plus `docs/MUTATION-CHECKS.md`
  recording ten mutants, all confirmed red.
- CI across Python 3.11/3.12/3.13, installing R and caching the AlphaSimR compile.

### Notes

- **Licensed GPL-3.0-or-later**, because this imports rpy2 (GPLv2+). AlphaSimR itself is
  MIT; the licence is about rpy2, not AlphaSimR.
- `BLOCKING_CODES` is deliberately empty. `plantcv-mcp` withholds traits when a guard
  fires because a bad mask yields a confidently wrong number; here results are always
  distributions, so a caller can already see when an answer is too noisy. These
  advisories explain rather than withhold.
- Tool functions are synchronous. R is one interpreter with global state, and
  serialising calls is what stops concurrent invocations interleaving inside it.
- `uv` is pinned to a managed CPython: conda ships a `libstdc++` older than system
  `libicuuc` needs, so rpy2's `dlopen` of `libR.so` fails with `GLIBCXX_3.4.30 not found`.

### Not included (phase 2)

Genomic selection models (GBLUP/RR-BLUP), multi-trait and G×E, optimal contribution
selection, crossing-block optimisation, genotype-matrix export, and `compare_programs`
for a paired A/B of two schemes.
