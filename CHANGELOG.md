# Changelog

All notable changes to `breedsim-mcp` are recorded here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- **Refusals reach the calling agent again under mcp >= 2.1.** mcp 2.1.0
  (python-sdk #3314) treats any exception other than `ToolError` as a crash:
  the model sees only `Error executing tool <name>` and the reason stays in the
  server log. Every refusal this server raises — the replicate floor, a missing
  SNP chip, an unknown session, a generator that does not exist — is the product,
  and under 2.0 its text went through regardless, so nothing in the server said
  so. Each tool is now wrapped at the MCP boundary to re-raise those anticipated
  errors as `ToolError`; the library keeps its own exception types, and a genuine
  crash stays masked as the SDK intends. Caught by
  `test_single_replicate_is_refused_through_the_tool_layer`, which matches the
  refusal TEXT at the tool layer and is unchanged — it is the guard.

- **Corrected the stated reason for the `rpy2<3.6` bound.** The comment at the pin
  claimed rpy2 >=3.6 "requires R >= 4.4" and that R 4.3 is "what Debian/Ubuntu
  ship". The first understates it — upstream's own 3.6.x documentation states
  **R >= 4.5** — and the second is unverified, since CRAN publishes R 4.5
  packages for current Ubuntu, so which R you get depends on which archive you
  use. Both claims were repeated into `.github/dependabot.yml`, PR #28 and the
  v0.4.1 release notes; all are corrected.

  **The bound itself is unchanged and was never in doubt.** The mechanism is now
  recorded as observed rather than inferred: dependabot's widening proposal (#25)
  died in all three test jobs inside `openrlib.rlib.R_getVar(...)` with "The
  embedded R is not initialized." against R 4.3. That is the evidence; the R
  version number was the part that was wrong.


## [0.4.1] — 2026-08-02

### Added

- **Community-health and repo-hygiene files, matching the standard set by
  `data-aggregator-mcp` and `plant-genomics-mcp`.** An earlier parity audit
  compared this repo only against `ldraw-mcp`, which is itself thin on these, so
  the whole tier went unnoticed: `CONTRIBUTING.md`, `SECURITY.md`, issue forms
  (bug report + feature request + a config pointing security reports at private
  advisories), a pull-request template, `.editorconfig`, `.mcp.json`, `glama.json`,
  a CodeQL workflow, and a Dependabot config.

  **Dependabot uses the `uv` ecosystem, not `pip`.** This is a uv-locked project;
  the pip ecosystem would update `pyproject.toml` and leave `uv.lock` stale, which
  CI installs with `--frozen` and would fail on. Dependabot's native uv support
  reads both together.

  `CONTRIBUTING.md` and `SECURITY.md` were added to the sdist allow-list.
  hatchling's allow-list drops anything unlisted **silently** — verified with
  `tar tzf` on a real build rather than assumed, the same way a `NOTICE` was
  previously found missing.

  `SECURITY.md` documents this server's actual trust boundary — verified against the
  source, not asserted: R statements are built only from pydantic-validated numeric
  parameters and server-generated `.bs_<uuid4>` identifiers, and a caller's
  `session_id` is used solely as a dictionary key, so no caller string reaches R.

- **README gained `python`, `licence` and Glama badges**, closing the one badge gap
  the earlier parity audit recorded and never actioned. All badge endpoints were
  checked for HTTP 200, with a deliberately bogus name as a negative control to
  confirm the check could fail.

- **`project.urls` gained `Changelog`.**

### Fixed

- **`server.json`'s description is back under the registry's 100-character cap.**
  The 0.4.0 audit fix moved the whole install-tax explanation into that field —
  315 characters — and the MCP registry rejected the submission with a 422. PyPI
  0.4.0 and the `v0.4.0` tag had already been published by then, because the
  registry is the last step and the only thing that checks this. The description
  now names the requirement in one line and leaves the explanation in the README,
  which is where it always was.

  `test_registry_metadata` gained the length assertion it was missing. That file
  exists specifically to catch registry constraints locally rather than in a
  workflow log after a version is burned, and this constraint had simply never
  been written down — the same failure mode the file's own docstring describes.

- **`server.json` is now validated against the registry's own schema, not against
  one hand-copied constant.** The length assertion above covers the constraint
  that happened to bite. It says nothing about the four other length caps, the
  required-field list, or any of the patterns and enums the registry also
  enforces — so the next unmeasured constraint would fail exactly the way this
  one did, at tag-push, in a workflow log.

  `server.json` already declared a dated `$schema`. That document _is_ the
  registry's statement of what it accepts, so the check is now to validate
  against it. The schema is vendored at `tests/server.schema.json` rather than
  fetched, keeping the suite offline and deterministic, and a test asserts the
  vendored copy's `$id` still matches the declared `$schema` so the pin cannot
  drift silently. `DESCRIPTION_MAX` is read out of the schema instead of being
  restated, leaving one source of truth and making it the registry's.

  Verified by mutation rather than assumed: the 371-character description was
  written back into `server.json` and the suite watched to fail on it, with a
  non-length failure (a missing required field) and an in-test positive control
  so a validator that raised on everything could not read as a working guard.

## [0.4.0] - 2026-08-01

### Added

- **Multi-trait architecture and index selection.** `found_population` takes `h2`
  as a LIST — one heritability per trait — plus `trait_correlation` for the
  genetic correlation between them. `run_program` then takes `index_weights`, one
  economic weight per trait, and selects on the weighted index via AlphaSimR's
  `selIndex` with `scale=TRUE`.

  **A multi-trait session without `index_weights` is refused.** AlphaSimR's
  `selectInd` defaults to `trait=1`, so omitting the index would select on the
  first trait alone while the response still looked multi-trait — a plausible
  result in which every other trait was merely along for the ride. The weights
  are the breeding objective; there is no defensible default for them.

  **A multi-trait cycle publishes `traits[]` and NO bare `genetic_gain`.** That
  key could only mean trait 1, and a caller reading the familiar name would take
  one trait for the whole objective. Same principle as refusing to return a
  single replicate: make the honest answer the only reachable one.

  `varG` returns a covariance MATRIX for several traits, not a vector. Its
  diagonal is taken; handing it back whole would report trait 2's "variance" as
  the trait1-trait2 covariance, a different quantity that can be negative.

- **The simulation is now checked against the breeder's equation.** A test drives
  a single cycle at a known heritability and asserts the realised response lands
  where R = h²S predicts. Until now every test compared this server against
  itself: a change that broke the genetics consistently would have kept the whole
  suite green. This is an external oracle — theory, not our own output.

  Its SCOPE is narrower than its name suggests, and that is recorded rather than
  papered over: it writes its own R and never imports `program` or `founding`, so
  mutating the server's selection criterion leaves it passing. The wider suite
  catches that. The eval validates AlphaSimR-plus-theory, not this package's
  wiring.

- **Every result states the engine that produced it and the scale it is in.**
  `recipe.engine` carries the R, AlphaSimR and rpy2 versions, and
  `recipe.gain_scale` names the units gain is reported in. Both were previously
  reachable only through a separate introspection call, so a saved result was not
  self-describing — a number in a notebook six months later could not be traced
  to the stack that made it, and gain had no stated scale at all.

  `gain_scale` DESCRIBES the scale rather than naming a fixed unit, deliberately:
  a single-trait session uses AlphaSimR's variance-1 default while a multi-trait
  session sets its own variances, so one hard-coded label would be false for one
  of them.

### Changed

- `compare_programs` refuses multi-trait sessions. It returns one paired verdict,
  which needs ONE criterion; with several traits that criterion is the index, and
  AlphaSimR does not report gain in index units. Any verdict would be this server
  choosing which trait counts. Use `run_program` per programme instead.

- **Selecting everyone is now named as such, and stops asking for replicates.**
  `n_select == n_ind` was permitted — legally, since a no-selection arm is a real
  drift-only control — but nothing said the selection differential was nil, so a
  gain of zero read as a finding rather than as arithmetic. Worse, the advisory
  that DID fire was `replicates_too_few`, telling the caller to re-run with more
  replicates against an effect that is zero BY CONSTRUCTION and that no number of
  replicates can move. A new `no_selection` warning fires instead, and
  `replicates_too_few` is withheld for that run.

  The run itself is unchanged and still permitted. What changed is that a guard
  which could not tell "underpowered" from "there is no effect to power against"
  no longer answers as if it could.

- **`server.json` leads with the install tax.** All three of our servers declare
  `runtimeHint: "uvx"`, which tells an MCP client to install on demand — but rpy2
  publishes no Linux wheels, so every Linux install compiles from source against R
  headers and `libtirpc-dev`. The client surfaced a raw `cannot find -ltirpc`
  linker error and never showed the README that explains it. The requirement is
  now in the description the client actually displays.

### Not included

The `RRBLUP_D`, `_GCA` and `_SCA` variants are still not exposed. They estimate
dominance and combining-ability effects, which requires a trait built with
`addTraitAD` rather than the additive-only `addTraitA` used here — fitting them
against an additive trait would estimate dominance that does not exist. Dominance
founding comes first.

## [0.3.2] - 2026-07-31

### Added

- **Zenodo archival.** This release exists to be archived: the Zenodo↔GitHub
  integration mints a DOI from the tag's tarball, and the previous tag predated
  `.zenodo.json` and `CITATION.cff` entirely — those files were added after it was
  cut. Zenodo archives the tag, not the default branch, so a release was the only
  way to get the metadata into an archived snapshot.

### Changed

- **`.zenodo.json` now uses Zenodo's lowercase licence identifier**
  (`gpl-3.0-or-later` rather than `GPL-3.0-or-later`). That is the canonical spelling —
  `zenodo.org/api/vocabularies/licenses/<id>` returns 200 for the lowercase form
  and 404 for the SPDX-cased one. See the correction below: it fixed nothing.

### Correction — added after this release was published

This release was originally described here as **fixing** a defect in which the
SPDX casing "silently dropped the licence from the published record". **That was
wrong, and the entry is corrected rather than quietly deleted.**

Zenodo normalises the licence identifier on ingest. The sibling `ldraw-mcp`
archived with `"MIT"` still in place and its record reads `license: mit-license`;
this project's record reads `license: gpl-3.0-or-later`. The licence was never dropped.

The apparent evidence was two of my own measurement errors, both the same
mistake — probing a proxy instead of the artifact:

1. Querying the licence **vocabulary endpoint** and treating a 404 there as what
   the ingest accepts. It is not; the ingest normalises casing.
2. Reading the **RDM-era field names** (`rights`, `subjects`,
   `creators[].person_or_org`) against an API endpoint that returns the **legacy**
   shape (`metadata.license`, `metadata.keywords`, `creators[].orcid`). Every
   field reported as absent was present throughout.

What remains true is the reason this release exists: the previous tag predated
`.zenodo.json` and `CITATION.cff`, and Zenodo archives the **tag**, not the
default branch. DOI: [10.5281/zenodo.21713868](https://doi.org/10.5281/zenodo.21713868).

### Notes

No functional change. Tools, guards and dependency pins are identical to 0.3.1.

## [0.3.1] - 2026-07-31

### Added

- **Published to the official MCP registry** (`io.github.musharna/breedsim-mcp`)
  via `server.json` and an OIDC workflow, so the server is discoverable from MCP
  clients and directories rather than only from PyPI.

  This needed a release rather than a docs commit. The registry proves PyPI
  ownership by finding an `mcp-name` marker in the package README **as published
  to PyPI**, and PyPI captures `long_description` at release time — so a marker
  sitting on `master` verifies nothing. It is the same mechanism that kept
  `plantcv-mcp`'s "Not published to PyPI" line live on its project page after the
  fix had merged.

- **`tests/test_registry_metadata.py`.** `server.json` states the version in three
  places, and nothing else makes them agree with `pyproject.toml`; a stale one is
  rejected by the registry during a release, after the version is spent. The
  README marker is checked against the name `server.json` declares for the same
  reason — that string is exactly what the registry greps for. All three
  assertions were confirmed red against mutants (drifted version, wrong marker
  name, transport declared `http`) before being kept.

### Notes

No functional change. The simulation, the tools, the replicate floor and the
dependency pins are identical to 0.3.0.

## [0.3.0] - 2026-07-30

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

[0.3.2]: https://github.com/musharna/breedsim-mcp/releases/tag/v0.3.2
[0.3.1]: https://github.com/musharna/breedsim-mcp/releases/tag/v0.3.1
[0.3.0]: https://github.com/musharna/breedsim-mcp/releases/tag/v0.3.0
[0.2.0]: https://github.com/musharna/breedsim-mcp/releases/tag/v0.2.0
[0.1.1]: https://github.com/musharna/breedsim-mcp/releases/tag/v0.1.1
[0.1.0]: https://github.com/musharna/breedsim-mcp/releases/tag/v0.1.0
