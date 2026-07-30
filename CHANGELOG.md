# Changelog

All notable changes to `breedsim-mcp` are recorded here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- **Migrated to `mcp` 2.x.** `FastMCP` was renamed, not removed: it is now
  `mcp.server.mcpserver.MCPServer`, same class and same kwargs. The dependency
  **moves** to `mcp>=2,<3` rather than widening to `<3` — this package imports
  `mcp.server.mcpserver`, absent in 1.x, so a range spanning both majors could
  resolve to a version that cannot import the server. mcp 2.x requires Python

  > =3.10, below this package's >=3.11 floor, so the support matrix is unchanged.

- **`call_tool` now returns a `CallToolResult` instead of a
  `(content, structured)` tuple.** This is a genuine API change rather than a
  rename, and it is the part of the 2.x move that actually required work here.
  Tests read `.structured_content` directly; the old
  `out[1] if isinstance(out, tuple) else out` shim is gone rather than extended,
  since a shape sniff would silently hand back the result object if the field
  were renamed again, surfacing the failure far from its cause.

- **`mcp.types` fields are snake_case** (`outputSchema` → `output_schema`,
  `readOnlyHint` → `read_only_hint`). The camelCase spellings survive as pydantic
  aliases, so _constructing_ `ToolAnnotations` still works either way — but that
  rescue does not extend to attribute access, which is what the tests do. Both
  the construction and the reads now use one spelling.

### Fixed

- **`test_single_replicate_is_refused_through_the_tool_layer` used
  `pytest.raises(Exception)`.** During this migration it caught an unrelated
  `TypeError` from a break three lines above it, and only the `match="replicates"`
  kept it from passing for the wrong reason. It now expects `ToolError`, so it can
  distinguish the refusal under test from any other failure on the way to it.

## [0.2.0] - 2026-07-29

### Added

- **Genomic selection.** `run_program` and `compare_programs` take
  `selection_method="genomic"`, which fits RRBLUP to marker genotypes each cycle
  and selects on the estimated breeding value rather than the phenotype.
  `found_population` gains `n_snp_per_chr` to add the SNP chip it needs — a
  founding decision, since the markers must exist before anything can be predicted
  from them. Setting the two arms of `compare_programs` to different methods makes
  "is genotyping worth it on these founders" a single paired call, which that
  contrast needs more than most: the gap between methods is routinely smaller than
  the sd 0.247 of seed-to-seed noise.

- **Measured founder linkage disequilibrium**, reported by `found_population` and
  `describe_session` as `linkage_disequilibrium`, with a
  `no_linkage_disequilibrium` advisory.

  This exists because genomic prediction on this engine has a trap with no warning
  label. LD with the causal loci is the entire mechanism by which a marker says
  anything about a trait, and **`quickHaplo` founders have none**: measured,
  adjacent markers correlate 0.0444 against a background of 0.0462 between distant
  markers, a ratio of 0.96. Adjacent is not merely low — it is indistinguishable
  from unlinked, because `quickHaplo` samples haplotypes with no coalescent
  history. `runMacs` gives 0.1979 against 0.0495, a ratio of 4.0. Out-of-sample
  accuracy on progeny follows: 0.097 versus 0.351 at 500 founders.

  Since `quickHaplo` is the default generator and the only reproducible one, the
  consequence is stated rather than buried: **on this engine, reproducibility and
  genomic realism cannot currently be had at the same time.**

- **Out-of-sample prediction accuracy** on every genomic cycle, summarised across
  replicates like everything else here. It is measured on progeny the fitted model
  never saw. Scoring it on its own training generation was the easy alternative and
  would have overstated it badly — measured 0.448 in-sample against 0.097
  out-of-sample on the same population.

### Changed

- `list_methods` reports `selection_methods`, and `limits` gains `n_snp_per_chr`.
- `found_population` refuses `n_snp_per_chr + n_qtl_per_chr > seg_sites`. Both are
  drawn from the same segregating sites, and R's own failure is
  `Not enough eligible sites`, which names none of the three numbers involved.

### Notes

The LD advisory keys on the **measurement**, never on the generator's name, and an
accuracy threshold is deliberately not used in its place. Measured at 20
replicates, a population with an LD ratio of 1.00 reached accuracy **0.208** by
cycle three — beating a genuinely linked population at the same selection
intensity — because in a closed population markers predict by tracking relatedness
as well as by linkage. An accuracy gate would therefore pass precisely the case it
claimed to detect. Accuracy is still reported; it is simply not evidence that
genomic selection is working for the reason a breeder assumes.

## [0.1.1] - 2026-07-29

### Fixed

- **Session eviction freed nothing.** `_free_r_state` intersected its target names
  against a bare `ls(envir=.GlobalEnv)`, which omits dot-prefixed names unless
  `all.names=TRUE` — and the session prefix starts with a dot by design. The
  intersection was therefore always empty and the `rm()` a permanent no-op. Measured:
  after eviction, all five of the session's R objects survived. Since the server is
  deliberately long-lived, every founded-then-evicted session leaked a whole
  population for the life of the process.

  The replacement removes by **prefix** rather than by enumerated name, which also
  fixes a second defect hiding underneath: the old two-name list would still have
  missed `_p0`, `_pop` and `_pop_sel` — the populations, i.e. the large objects —
  even once `all.names=TRUE` was added.

  Eviction had **no test at all**, which is why this shipped. It has one now, and it
  asserts against `ls(all.names=TRUE)` deliberately: a test written with the same
  bare `ls()` as the code would have seen zero survivors and passed against the
  broken version.

### Added

- **Upper bounds on every size parameter** (`limits.py`). 0.1.0 validated floors only.
  R is a single interpreter and the tools are synchronous, so one oversized call
  blocks every other call until it finishes — and the caller is a language model,
  which will ask for `replicates=10000` because the number sounds thorough. The caps
  are published through `list_methods` so a caller can size a request rather than
  discover the ceiling by being refused.

### Changed

- `session.py`'s "the genotype matrix never crosses the boundary" was imprecise. No
  matrix is ever returned to the caller, but `_founder_hash` does pull the whole
  haplotype matrix into Python once per `found_population` — 200,000 values at the
  default sizes. Reworded to say what is actually true.

## [0.1.0] - 2026-07-29

Phase 1. Breeding-scheme simulation over MCP, driving AlphaSimR 2.1.0 through rpy2.

### Fixed

- **P0: the server failed on every tool call after the first.** rpy2 publishes its
  conversion rules into a `contextvars.ContextVar` at import time, and `engine._rpy2()`
  imported lazily — i.e. inside whichever request first touched R. Those rules lived in
  that request's context and were discarded when it returned, so the next call raised
  `Conversion rules for rpy2.robjects appear to be missing`. Measured in a fresh process
  driven only through the MCP layer: `list_methods` succeeded, `found_population` died.
  rpy2 is now bound at module scope, in the root context that every task inherits. The
  import still lives inside a function so an import sorter cannot hoist it above the
  `OMP_NUM_THREADS` pin, which is a separate guarantee this module exists to provide.

  The 27-test suite passed against the broken code. Every test called the library
  directly, which imports rpy2 into the pytest process's root context and masks the bug
  entirely; the regression test therefore runs a **subprocess** that touches R only
  through `call_tool`, and it ships with a positive control proving it can fail.

- The `runMacs` explanation is now interpolated from a single `RUNMACS_RNG_NOTE`
  constant. It had been hand-restated in four places, and when the overstated version
  ("runMacs ignores `set.seed`") was corrected in `founding.py`, the copies in
  `server.py` — including the `INSTRUCTIONS` an agent reads to decide how to drive the
  engine — kept asserting the false claim.

### Added

- **`compare_programs` — paired A/B comparison.** Runs two programmes on shared founders
  with **common random numbers**: replicate _i_ of each arm starts from identical founders
  under the same seed, and the difference is taken WITHIN the pair, so the shared luck of
  that seed cancels rather than being counted twice. Returns the difference as a
  distribution with its own confidence interval.
  - `favours` is `null` whenever that interval contains zero — the two programmes are not
    distinguishable at that replicate count, and the larger mean is not the winner.
  - `overlap_but_different` fires when the per-arm intervals overlap but the paired
    difference excludes zero. Measured live at 12-of-100 vs 18-of-100: the arms span
    1.900–2.192 and 1.552–1.909 (overlapping), while the paired difference is
    `[+0.100, +0.531]`. **Two overlapping intervals do not imply no difference**, and that
    is the easiest way to get a breeding comparison wrong.
  - The replicate floor applies here too, with a blunter message: a comparison needs more
    replication than a single programme, not less.
  - Breaking the pairing in a mutation check made two identical programmes differ by 0.169
    and 0.271 — the same order as the sd 0.247 the floor exists for.

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
- 38 tests against real AlphaSimR — no mocked R — plus `docs/MUTATION-CHECKS.md`
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

### Not included

Genomic selection models (GBLUP/RR-BLUP), multi-trait and G×E, optimal contribution
selection, crossing-block optimisation, and genotype-matrix export. `compare_programs`
was originally listed here and shipped in this release instead.

[0.2.0]: https://github.com/musharna/breedsim-mcp/releases/tag/v0.2.0
[0.1.1]: https://github.com/musharna/breedsim-mcp/releases/tag/v0.1.1
[0.1.0]: https://github.com/musharna/breedsim-mcp/releases/tag/v0.1.0
