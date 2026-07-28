# breedsim-mcp — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL — use `superpowers:subagent-driven-development`
> to implement this plan task by task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> Design: `docs/superpowers/specs/2026-07-28-breedsim-mcp-design.md` (APPROVED).
> Every API call below was **executed** during the 2026-07-28 spike, not read from docs.

## Ground truth every task must respect

These were measured. Do not re-derive them, and do not contradict them without re-measuring.

| fact                                                                      | value                                                       |
| ------------------------------------------------------------------------- | ----------------------------------------------------------- |
| Engine                                                                    | AlphaSimR **2.1.0** (MIT) via rpy2 **3.5.17** (GPLv2+)      |
| rpy2 ≥3.6 needs R ≥4.4 (`R_getVar`); local R is 4.3.3                     | pin `rpy2<3.6`                                              |
| `runMacs` ignores `set.seed` — even at `nThreads=1` + `OMP_NUM_THREADS=1` | non-reproducible founders                                   |
| `quickHaplo` under a fixed seed                                           | **reproducible** (identical haplotype hashes)               |
| OpenMP in the selection path                                              | pinned → `meanG=2.01451853` twice; unpinned → 2.397 / 2.125 |
| Run-to-run spread, 5 seeds, 3 cycles                                      | mean 1.463, **sd 0.247**, range 0.690                       |
| 3-cycle gain on persisted state                                           | meanG 0.8420 → 1.5776 → 2.1971; varG 0.7997 → 0.6351        |

**Verified R call signatures** (all executed): `runMacs(nInd, nChr, segSites, inbred, species,
split, ploidy, manualCommand, manualGenLen, nThreads)` · `quickHaplo(nInd, nChr, segSites)` ·
`SimParam$new(founderPop)` · `SP$addTraitA(nQtlPerChr)` · `SP$setVarE(h2)` ·
`newPop(founderPop, simParam=SP)` · `selectInd(pop, nInd, use="pheno", simParam=SP)` ·
`randCross(pop, nCrosses, simParam=SP)` · `meanG(pop)` · `varG(pop)` ·
`pullSegSiteHaplo(pop, simParam=SP)`.

⚠️ **`pullSegSiteHaplo` defaults to a GLOBAL named `SP` in `.GlobalEnv`** — it errors with
`object 'SP' not found` if your simulation-parameter object has any other name. Pass
`simParam=` explicitly everywhere.

⚠️ **`getNThreads` / `setNThreads` DO NOT EXIST in AlphaSimR 2.1.0.** A `try(setNThreads(1),
silent=TRUE)` silently no-ops and will fake a passing determinism test. Thread control is via
the `OMP_NUM_THREADS` environment variable only, set before R initialises.

---

## Task 1 — Project skeleton

- [ ] `pyproject.toml`: name `breedsim-mcp`, version `0.1.0`, `license = "GPL-3.0-or-later"`,
      `requires-python = ">=3.11"`, deps `mcp>=1.28.1,<2`, `rpy2>=3.5,<3.6`, `numpy>=1.26`,
      `typing-extensions>=4.12`. Dev group: `pytest>=8.0`, `ruff>=0.6`.
- [ ] `LICENSE` = GPL-3.0. `NOTICE` crediting AlphaSimR (MIT, Chris Gaynor) + rpy2 (GPLv2+) +
      an explicit "unofficial, not affiliated with the AlphaSimR authors" statement.
- [ ] sdist allow-list (`src/**`, `tests/**`, README, CHANGELOG, LICENSE, NOTICE, pyproject).
      **Check with `tar tzf`, not `git ls-files`** — hatchling's `packages` covers the wheel only.
- [ ] `[tool.ruff] extend-exclude = ["docs"]` — ruff formats Python inside Markdown and would
      rewrite this plan's code blocks.
- [ ] CI: matrix 3.11/3.12/3.13. **The R side must be installed in CI** (`r-base`,
      `libtirpc-dev`, then AlphaSimR). Expect a multi-minute Rcpp compile — cache it.
- [ ] **Verify:** `uv build` succeeds; `tar tzf dist/*.tar.gz` shows no `.claude`/`docs`.

## Task 2 — `engine.py`: thread pinning before R starts

- [ ] **Test first:** importing `breedsim_mcp.engine` sets `os.environ["OMP_NUM_THREADS"]=="1"`,
      and does so **before** rpy2 is imported (assert `"rpy2" not in sys.modules` at the point
      the variable is set — use a subprocess so import order is real, not simulated).
- [ ] Implement: set the variable at module top, above the rpy2 import, with a comment
      explaining that R reads it at OpenMP init and setting it later is a no-op.
- [ ] **Positive control in the same test:** a subprocess that imports rpy2 FIRST and only then
      our module must be detectable as unpinned — otherwise the guard cannot discriminate.

## Task 3 — `engine.py`: dependency detection with precise errors

- [ ] **Test first:** with a bogus `R_HOME`, the error names R specifically and is NOT a raw
      `RRuntimeError`; with R present but AlphaSimR absent, the error names AlphaSimR and gives
      the `install.packages` command.
- [ ] Implement `check_environment() -> EnvironmentReport` (r_version, alphasimr_version,
      rpy2_version, threads_pinned, reproducible). Never bootstrap-install anything.
- [ ] **Verify:** against the real environment — R 4.3.3, AlphaSimR 2.1.0.

## Task 4 — `founding.py`: founder populations and their provenance

- [ ] **Test first:** `found(generator="quickHaplo", seed=1)` twice gives **identical**
      haplotype hashes and `reproducible is True`; `generator="runMacs"` gives **different**
      hashes and `reproducible is False`. Both assertions in one test — the runMacs case is the
      failing case, the quickHaplo case is its positive control.
- [ ] Implement: `quickHaplo` and `runMacs` paths; return founder provenance (generator, seed,
      nInd, nChr, segSites) plus the `reproducible` flag and, when false, the reason.
- [ ] ⚠️ Name the sim-param object `SP` in the R global env AND pass `simParam=` explicitly.

## Task 5 — `session.py`: sessions over persisted R state

- [ ] **Test first:** two sessions do not collide (distinct R object names); an unknown
      `session_id` raises naming what was passed; eviction frees the R-side objects.
- [ ] Implement an LRU store (default 8). Each session owns uniquely-named R globals; the
      Python side holds founder spec, seed, trait architecture and provenance — never a copy of
      the genotype matrix.
- [ ] **Verify:** `nInd` of a session's population is unchanged after another session is created.

## Task 6 — `program.py`: one replicate of a selection programme

- [ ] **Test first:** running 3 cycles from fixed founders with pinned threads reproduces
      `meanG` **exactly** across two calls; a different seed differs (positive control in the
      same test). Use the measured recipe — `quickHaplo` founders, `OMP_NUM_THREADS=1`.
- [ ] Implement `run_replicate(session, cycles, n_select, n_cross, seed) -> per-cycle records`
      of `meanG`, `varG`, and inbreeding.
- [ ] **Verify:** genetic gain rises and `varG` falls across cycles — the Bulmer effect. A run
      where `varG` does not fall under truncation selection indicates the programme is wired
      wrong, not that biology changed.

## Task 7 — `replication.py`: THE structural rule

- [ ] **Test first:** `run_program` with `replicates=1` **raises** — there is no way to obtain a
      single-run point estimate. `replicates=10` returns per-cycle `mean`, `sd`, `ci_low`,
      `ci_high`, `n_replicates`. Assert the returned object has **no** field carrying a lone
      run's value.
- [ ] Implement aggregation across replicates. `MIN_REPLICATES = 5` (floor), default 10.
- [ ] ⚠️ This is the load-bearing decision of the whole server. It must not be reachable to
      bypass — no `replicates=1`, no `raw=True`, no flag that collapses the distribution.
- [ ] **Verify against measured reality:** with 5 seeds the sd was 0.247 on meanG; the returned
      CI must be wide enough to contain that spread, not a spuriously tight interval.

## Task 8 — `diagnostics.py`: the four warnings

- [ ] **Test first,** each paired with a positive control in the same test:
      `nondeterministic_founders` (runMacs vs quickHaplo) · `threads_not_pinned` (unpinned vs
      pinned subprocess) · `replicates_too_few` (wide CI vs narrow) · `variance_exhausted`
      (collapsed `varG` vs healthy).
- [ ] Implement as pure functions over a summary object — no R, no I/O, so they are testable in
      isolation.
- [ ] Define `BLOCKING_CODES` and keep it **empty for now**, with a comment: unlike
      `plantcv-mcp`, no warning here withholds results, because the structural protection is
      the no-point-estimate rule rather than a refusal.

## Task 9 — `server.py`: the MCP surface

- [ ] **Test first:** exactly four tools register — `list_methods`, `found_population`,
      `run_program`, `describe_session`. Every tool has a `title` and `ToolAnnotations`
      (`readOnlyHint=True`, `openWorldHint=False`). Every tool returning structured data
      publishes an `outputSchema`; assert the RULE for all tools, not a named list.
- [ ] ⚠️ `TypedDict` **must** come from `typing_extensions`, not `typing` — pydantic raises
      `PydanticUserError` on stdlib TypedDict under Python <3.12 and CI will go red on 3.11
      only, which a 3.13 dev box will not reproduce.
- [ ] Server `instructions=` must state: results are distributions not point estimates; what
      each warning code means; that `runMacs` founders are not reproducible.
- [ ] **Verify:** drive `found_population` → `run_program` over the real MCP layer.

## Task 10 — Integration test on the real engine

- [ ] End-to-end through the MCP tools against real AlphaSimR: found → run 3 cycles × 10
      replicates → assert gain rises, `varG` falls, CI present, `reproducible` reported.
- [ ] No mocked R anywhere in this test.

## Task 11 — Determinism suite

- [ ] Assert the full recipe: `quickHaplo` + pinned threads + fixed seed reproduces exactly.
- [ ] Assert each half FAILS to reproduce on its own — `runMacs` + pinned, and `quickHaplo` +
      unpinned (subprocess). ⚠️ This is why the earlier OpenMP rule-out was wrong twice: with
      two independent noise sources live, a test for one is invalid while the other is active.
      **Isolate to a single variable per assertion.**

## Task 12 — Docs

- [ ] README: what it is, the install tax stated up front (R ≥4.3 + compiled AlphaSimR +
      `libtirpc-dev` + rpy2 `<3.6`), MCP client config, the no-point-estimate rule and why,
      the determinism recipe, GPL notice. Absolute image/link URLs if any are added.
- [ ] `docs/MUTATION-CHECKS.md` — every guard, its mutation, and the test that went red.

## Task 13 — Mutation pass

- [ ] Disable each guard in turn and confirm the paired test goes red: the `replicates=1`
      refusal, each of the four warnings, the thread-pin, the `reproducible` flag, and each
      tool's `outputSchema`.
- [ ] ⚠️ **Pair every mutant with a test that exercises the layer the mutation is in.** A
      library-level test does not protect a server-level passthrough; that exact mistake
      survived two rounds on `plantcv-mcp`.
- [ ] Record results. A surviving mutant is a coverage report — fix the coverage, then re-run.
