# Agent benchmark: quantitative-genetics questions with and without the server

Does Claude answer breeding-scheme questions better with breedsim-mcp than
without it? 40 questions, asked 3 times each to Claude Opus 5.5 in Claude
Code under three setups:

- **Claude alone**: no tools.
- **Claude + Bash, R and web**: Bash (R with AlphaSimR, and Python, on the
  PATH), Read, WebSearch and WebFetch. This is what a user has without the
  server: Claude can write its own AlphaSimR or theory code.
- **Claude + breedsim-mcp**: this server (0.5.1 from PyPI, via `uvx`) only.

**Results: TODO, the full sweep has not run.** Only a two-question pilot has
(below), to prove the harness end to end.

![Right, wrong or declined per setup](agent_qa.png)

| Setup | Right | Wrong | Declined | Questions right in all 3 runs | Cost / answer, median (mean) | Seconds / answer, median (mean) | Slowest |
|---|---|---|---|---|---|---|---|
| Claude alone | TODO | TODO | TODO | TODO of 40 | TODO | TODO | TODO |
| Claude + Bash, R and web | TODO | TODO | TODO | TODO of 40 | TODO | TODO | TODO |
| Claude + breedsim-mcp | TODO | TODO | TODO | TODO of 40 | TODO | TODO | TODO |

Out of 120 answers per setup. The three runs of a question are not
independent, so the questions column is the fairer count. The numbers come
from `summary.tsv`, which `plot.R` writes from `results.jsonl`.

## What it shows

TODO after the sweep.

## What it does not show

- **The key is theory, not this simulator.** Each answer is an expectation
  from quantitative-genetics theory (below). A server that reproduced
  AlphaSimR faithfully but answered a different question (say, a single run
  instead of an expectation) would be marked wrong, and so would theory
  applied to the wrong design.
- **Where the theory is an approximation, the band says so.** Gains over 2 or
  3 cycles and the Bulmer variance use the infinitesimal model, which leaves
  out allele-frequency change at 100 QTL. Each category has a stated slack
  for that (table below), and the key build fails if an independent AlphaSimR
  calibration of a question lands outside slack + 3 SE of theory.
- **A band wide enough for honest simulation noise cannot separate small
  theory errors.** Bands run from ±4% to ±56% (median ±22%). Which common
  mistakes they can tell from the right answer
  (`build_questions.py --discrimination`, 2026-10-16 key):

  | Kind | Mistake | Outside the band in |
  |---|---|---|
  | intensity | infinite-population i(p) for a finite sample | 0 of 4 |
  | response_1cycle | R = i h2 (sigma_P dropped) | 7 of 8 |
  | response_1cycle | R = i h with infinite-population i | 0 of 8 |
  | bulmer_variance | 1 - k h2 (no halving) | 4 of 6 |
  | bulmer_variance | 1 - k h2 / 2 (infinite population) | 0 of 6 |
  | bulmer_variance | 1 (no change) | 4 of 6 |
  | multi_cycle_gain | t x one-cycle response (no Bulmer effect) | 0 of 8 |
  | drift_sd | sqrt(F) (factor 2 dropped) | 6 of 6 |
  | drift_sd | Ne = N/2 | 6 of 6 |

  So the multi-cycle questions do not test whether the Bulmer effect is
  accounted for, and no question tests the finite-sample intensity
  correction: at these sizes both are smaller than the noise of a
  one-session estimate.
- **Genomic selection and multi-trait index selection are not covered.** They
  have no closed form to fix an answer by.
- **One model, one date.**

## Questions

[`questions.json`](questions.json) holds the 40 questions with their keys.
`build_questions.py` draws every design from fixed grids with a seeded RNG
(seed 20261016), so none is hand-picked. All designs use quickHaplo
founders with 10 chromosomes × 100 segregating sites and an additive trait
with 10 QTL per chromosome, founder additive variance 1, and residual
variance fixed at founding, exactly what `found_population` builds.

| Kind | Count | Server tool | Answer key (`theory.py`) | Slack |
|---|---|---|---|---|
| Selection intensity (4 finite samples, 2 infinite) | 6 | `run_program` with h2 = 1 | E[mean of top n of N normals] by integration; `phi(z)/p` | 1% |
| Response to one cycle | 8 | `run_program` | breeder's equation, `i(n,N) h sigma_A` | 3% |
| Genetic variance after one cycle | 6 | `run_program` (`genetic_variance`) | Bulmer: between-pair + Mendelian variance, finite n | 3% |
| Gain over 2 or 3 cycles | 8 | `run_program` | breeder's equation per cycle on the Bulmer-reduced variance, with drift | 4% |
| Difference between two programmes | 6 | `compare_programs` | difference of the two expectations | 3% |
| Drift: SD of replicate means, no selection | 6 | `run_program` (`sd`) | `sqrt(2 F_t)`, `F_t = 1 - (1 - 1/(2 Ne))^t` | 5% |

`build_questions.py` and `theory.py` never import `breedsim_mcp`, so a bug in
the server cannot also be in the key (`tests/test_agent_qa_score.py` checks
the imports).

### The band

Each question states its tolerance as a percent, and the scorer applies
exactly that:

    half_width = 3 × SE(one session) + slack × |theory|, rounded up to a whole percent

`SE(one session)` is the standard error of a careful estimate made on one
founder set, `sqrt(sigma_f² + sigma_s² / R)`, with `R` = 20 replicates for a
mean and 100 for an SD (an SD estimated from `R` replicates has SE
`sigma / sqrt(2(R − 1))`). `sigma_f` is the spread between founder sets,
which more replicates on one session cannot remove; `sigma_s` the spread
between seeds within one. Both are measured by `calibrate.R`, which drives
AlphaSimR directly on 12 founder sets × 8 seeds per question (6 × 40 for
the drift SDs). For a paired difference `sigma_s` is the unpaired one, so an
estimate from two separate runs is also inside the band.

Each question's key records `mc_fraction`, the share of its band that is
Monte Carlo noise rather than slack. Across the 40 questions the median is
0.82 (range 0.62 to 0.95): most of every band is simulation noise, not slack.
All 40 calibration means landed within slack + 3 SE of theory.

## Scoring

Each reply ends with `ANSWER: <number>` or `ANSWER: UNKNOWN`. `score.py`
decides the verdict from that line alone:

- **right**: the number is within the question's band of the theory value.
- **wrong**: a number outside the band, or no number on the line.
- **declined**: `UNKNOWN`.
- **no answer**: there is no `ANSWER:` line.

Other spellings of the same number count as that number: `79%` is 0.79, a
Unicode minus is a minus, thousands separators are dropped. Every answer also
records `rel_error`, and `agent_qa_error.png` plots each miss in units of
its band, so a wrong answer's distance is shown rather than inferred.
Tests: `tests/test_agent_qa_score.py`.

## Pilot (2026-10-16)

Two questions × three setups × one run, to prove the harness; pilot rows are
not in `results.jsonl`. Claude Code 2.1.302.

| Setup | q10 (one-cycle response) | q37 (drift SD) | Tools offered (init event) |
|---|---|---|---|
| Claude alone | right, 0.73, 11 s, $0.018 | right, 0.22, 25 s, $0.045 | none |
| Claude + Bash, R and web | right, 0.73, 15 s, $0.024 | right, 0.22, 23 s, $0.042 | Bash, Read, WebFetch, WebSearch |
| Claude + breedsim-mcp | right, 0.733, 28 s, $0.053 | right, 0.22, 21 s, $0.039 | the server's 5 tools, `breedsim` connected |

Every run exited 0. No run in either tool setup called a tool: all six
answers were worked from theory. If the sweep shows the same, these
questions measure whether tools are needed for textbook expectations (they
may not be), not how well Claude drives the server.

## Reproduce

```bash
uv run python benchmarks/agent_qa/build_questions.py         # re-derive the key (minutes; runs calibrate.R)
uv run python benchmarks/agent_qa/run.py --reps 3 --workers 1   # 360 claude -p runs; resumable
uv run python benchmarks/agent_qa/run.py --rescore           # re-score stored replies after a key fix
Rscript benchmarks/agent_qa/plot.R                           # summary.tsv + figures
```

Each run is an isolated `claude -p`:
- `--setting-sources ""` and an empty working directory.
- `--strict-mcp-config`, so no other MCP servers.
- The same short system prompt in every setup.

`R_LIBS_USER` must point at a library with AlphaSimR (default
`~/R/library`); the `mcp` and `alt` setups both get it. One worker by
default, since each `mcp` run starts its own R. Raw transcripts go to
`runs/`, which is gitignored.
