# breedsim-mcp — design

> Status: **APPROVED 2026-07-28.** Section 8's open questions are now DECIDED (see §9).
> Name `breedsim-mcp` — verified free on PyPI and GitHub (control: `plantcv-mcp` returns 200
> and is found, so the probe discriminates). Deliberately **not** `alphasimr-mcp`: borrowing
> the upstream name is what forced an affiliation disclaimer onto `plantcv-mcp`.

## 1. Motivation and seam

An MCP server for **breeding-scheme simulation** — run a selection programme in silico and
find out what it would gain — built around one structural rule:

> **A single stochastic run is not a result, and the API will not return one.**

**Grounding (verified 2026-07-28, shape-matched positive controls).** `alphasimr mcp`,
`pybrops mcp` and `breeding mcp` are null on GitHub while `napari mcp` (37★), `pymol mcp`
(65★) and `galaxy mcp` (36★) return hits, and domain-shaped controls fire too
(`breeding simulation` → 30★, `genomic selection` → 29★) — so the harness discriminates on
both query shapes. The MCP registry returns 0 for breeding/simulation/alphasimr while
`genomic` returns 5 as an in-registry control. **No breeding-simulation MCP server exists.**

**Gate 2 — compute tier.** Simulation is compute by definition. The field is open.

**Gate 1 — shell-out — passes on its strongest condition, and this was PROVEN by execution
rather than argued.** A breeding programme is inherently multi-generation stateful: found a
population, then run selection cycles each depending on the last. Measured across three
_separate_ Python→R calls against one persisted population:

| cycle | meanG  | varG   |
| ----- | ------ | ------ |
| 1     | 0.8420 | 0.7997 |
| 2     | 1.5776 | 0.7857 |
| 3     | 2.1971 | 0.6351 |

Genetic gain rises while genetic variance falls under selection — the Bulmer effect. A
one-shot script cannot model that loop; a session can.

## 2. Empirical basis — why "no single run" is load-bearing

Measured on AlphaSimR 2.1.0 via rpy2 3.5.17.

**Run-to-run noise is the same order as the effect being measured.** Five seeds of an
identical three-cycle programme gave meanG `[1.151, 1.841, 1.424, 1.429, 1.473]` — mean
1.463, **sd 0.247, range 0.690**. Reporting one run's genetic gain to three decimals would be
reporting noise with the authority of a measurement. This is the direct analogue of
`plantcv-mcp`'s seventeen plausible traits from an empty mask.

**Reproducibility is achievable, but needs two separate fixes — both found the hard way:**

| source                   | symptom                                        | remedy                                       |
| ------------------------ | ---------------------------------------------- | -------------------------------------------- |
| `runMacs` founder RNG    | same `set.seed` → different founder haplotypes | use `quickHaplo`, or persist founders once   |
| OpenMP in selection path | same seed, fixed founders → 2.397 vs 2.125     | `OMP_NUM_THREADS=1` **before R initialises** |

`runMacs` stays non-deterministic even with `nThreads=1` **and** `OMP_NUM_THREADS=1`, so its
coalescent RNG is simply not governed by R's. With founders fixed and threads pinned, seed 7
reproduces exactly: `meanG=2.01451853` twice.

## 3. Tool surface (phase 1)

### `list_methods()`

Selection protocols, founder generators, engine versions, **and the determinism status of the
running process** — whether threads are actually pinned right now.

### `found_population(...) -> session_id`

Creates and persists a founder population and its trait architecture. Returns the
`session_id`, the generator used, and an explicit **`reproducible: true|false`** — false
whenever `runMacs` was used, with the reason attached.

### `run_program(session_id, cycles, replicates=10, ...) -> distribution`

Runs the selection programme `replicates` times and returns, **per cycle**, the mean, sd and
confidence interval of genetic gain, genetic variance and inbreeding.

**It cannot return a single run.** `replicates` has a floor, and there is no parameter that
collapses the output to a point estimate. A caller may compute one; the server will not
present one as the answer.

### `describe_session(session_id)`

Founder provenance, trait architecture, cycles run so far, seed, reproducibility status.

### The load-bearing decision

**`plantcv-mcp` splits `segment` from `measure` so a number cannot be obtained without the
picture. `breedsim-mcp` refuses point estimates so a number cannot be obtained without its
uncertainty.** The same move in a different domain: make the honest answer the only reachable
one, rather than documenting a caveat the caller is free to skip.

## 4. Automatic warnings

Each derived from something measured, not imagined:

1. **`nondeterministic_founders`** — `runMacs` was used; this session cannot be reproduced.
2. **`threads_not_pinned`** — `OMP_NUM_THREADS != 1`; results will vary run to run.
3. **`replicates_too_few`** — the CI is wide relative to the difference being claimed.
4. **`variance_exhausted`** — `varG` has collapsed, so further cycles will add little; a still
   rising meanG is then a plateau rather than progress.

## 5. Error handling — fail loud

- Refuse to return a point estimate. There is no flag to disable it.
- R, AlphaSimR or rpy2 missing → a precise install error naming the missing piece, not a raw
  `RRuntimeError` traceback.
- Unknown `session_id` → explicit error naming what was passed.
- Any fallback that would silently make results irreproducible must raise instead.

## 6. Testing strategy

1. **Real execution** against AlphaSimR 2.1.0. No mocked R.
2. **Determinism tests that assert the recipe** — same seed + `quickHaplo` + pinned threads
   reproduces exactly, paired in the same test with a positive control that a _different_
   seed differs, so an always-equal bug cannot masquerade as determinism.
3. **Never trust a test that has not been seen fail** — every guard mutated off and confirmed
   red, recorded in `docs/MUTATION-CHECKS.md`.
4. Golden values pinned with tolerance, since AlphaSimR releases may shift them.

## 7. Non-goals (phase 1)

No genomic selection models (GBLUP/RR-BLUP), no multi-trait or G×E, no optimal contribution
selection, no crossing-block optimisation, no genotype-matrix export. Phase 2 adds genomic
selection and `compare_programs` for a paired A/B of two schemes.

## 8. Open questions — RESOLVED (kept for the reasoning; decisions in §9)

1. **Install tax.** Needs R ≥4.3, a compiled AlphaSimR (Rcpp, minutes), `libtirpc-dev`, and
   rpy2 pinned `<3.6` (3.6 requires R ≥4.4). Far heavier than `uv pip install`. Should the
   server detect and explain, or try to bootstrap the R side itself?
2. **Where do threads get pinned?** `OMP_NUM_THREADS=1` must be set before R initialises,
   which in-process means at import — before rpy2 loads. That is invisible to anyone who
   imports modules in a different order, so it needs a guard that detects the unpinned case
   and refuses rather than silently returning irreproducible numbers.
3. **Replicate cost.** 10 replicates × N cycles is 10× the runtime. Fixed default, or adaptive
   until the CI is narrow enough to support the claim being made?

## 9. Decisions (2026-07-28)

### Licence — GPL-3.0-or-later

**Verified:** AlphaSimR 2.1.0 is **MIT** (installed `DESCRIPTION`, confirmed on CRAN), but
**rpy2 3.5.17 is GPLv2+**, and R itself is GPL.

`plantcv-mcp` is MIT because PlantCV's MPL-2.0 is a *file-level* copyleft that an ordinary
runtime dependency does not spread. **That reasoning does not carry over.** GPL is a strong
copyleft, and a distributed package that IMPORTS rpy2 is normally a derivative work, so the
combined distribution must be GPL-compatible.

So this package is **GPL-3.0-or-later**. It keeps the rpy2 architecture already verified
working, and GPL is the ecosystem norm here — R is GPL and every AlphaSimR user is already in
that world. `NOTICE` will credit AlphaSimR (MIT, Chris Gaynor) and state that this project is
unofficial and unaffiliated.

### The three open questions

1. **Install tax → detect and explain, never bootstrap.** Auto-installing R packages mutates
   the user's system as a side effect, takes minutes and can fail halfway. Instead a
   doctor-style check, surfaced through `list_methods()` and raised on first use, names
   exactly what is missing and the command that fixes it.
2. **Thread pinning → pin at import AND guard at runtime.** `OMP_NUM_THREADS=1` is set before
   rpy2 loads. Because import order is not ours to control, a runtime check also detects the
   case where R came up unpinned and marks those results `reproducible: false` with a loud
   warning. It WARNS rather than blocks, consistent with `implausible_coverage`: trading
   reproducibility for speed is a legitimate choice, silently doing so is not.
3. **Replicate cost → fixed floor of 10 for phase 1; adaptive deferred.** The response
   reports the CI width and fires `replicates_too_few` when the interval is wide relative to
   the difference being claimed. Adaptive replication until a target precision is reached is
   phase 2.

**Note the asymmetry, which is deliberate:** the no-point-estimate rule is STRUCTURAL and has
no override, while `threads_not_pinned` only warns. The first prevents a class of wrong
answer; the second describes a tradeoff the caller is entitled to make.
