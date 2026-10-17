# Agent benchmark: breeding-simulation questions with and without the server

Does Claude answer breeding-programme questions better with breedsim-mcp than
without it? 40 questions, asked 3 times each to Claude Opus 5.5 in Claude
Code under three setups:

- **Claude alone**: no tools.
- **Claude + Bash, R and web**: Bash (R with AlphaSimR, and Python, on the
  PATH), Read, WebSearch and WebFetch. This is what a user has without the
  server: Claude can write and run its own AlphaSimR code.
- **Claude + breedsim-mcp**: this server (0.5.1 from PyPI, via `uvx`) only.

**Results: TODO, the full sweep has not run.** Only a two-question pilot has
(below).

![Right, wrong or declined per setup](agent_qa.png)

| Setup | Right | Wrong | Declined | Questions right in all 3 runs | Cost / answer, median (mean) | Seconds / answer, median (mean) | Slowest |
|---|---|---|---|---|---|---|---|
| Claude alone | TODO | TODO | TODO | TODO of 40 | TODO | TODO | TODO |
| Claude + Bash, R and web | TODO | TODO | TODO | TODO of 40 | TODO | TODO | TODO |
| Claude + breedsim-mcp | TODO | TODO | TODO | TODO of 40 | TODO | TODO | TODO |

Out of 120 answers per setup. The three runs of a question are not
independent, so the questions column is the fairer count. The numbers come
from `summary.tsv`, which `plot.R` writes from `results.jsonl`.

## What it measures

Most questions sit where a closed form does not give the answer: many cycles
of selection in a small population (where drift, the Bulmer effect and loss
of variance at a few QTL interact), two schemes compared over 5-15 cycles,
the chance that one beats the other, and genomic prediction accuracy built up
over several cycles. One category, the one-cycle response in a large
population, is a control where the textbook answer is right.

**The key and the server share AlphaSimR.** The key is not theory: it is
AlphaSimR driven directly by [`simulate_key.R`](simulate_key.R), which shares
no code with breedsim_mcp, on the founders each question pins with a seed.
That is the same relation plant-genomics-mcp's key has with Ensembl. So the
benchmark measures whether an agent sets up and runs the stated simulation
correctly (founders, trait, selection, crossing, enough replicates, the right
statistic), not whether AlphaSimR is right.
[`tests/test_agent_qa_key_matches_server.py`](../../tests/test_agent_qa_key_matches_server.py)
checks the premise on the real engine: on the same founder and replicate
seeds the server's means equal the key script's to 1e-9, for phenotypic
selection, genomic selection (gain and accuracy) and a paired comparison,
with a different selection intensity as the control that must not match.
Mutating the key script (accuracy scored on the selected parents instead of
the progeny, or replicate seeds shifted by one) fails it.

## What it does not show

- **A theory-literate answer can still land in some bands.** The bands are
  built to reject the named shortcuts (below), not every closed form. The
  full infinitesimal recursion (Bulmer effect plus drift, `theory.programme`)
  lands inside the band in 3 of 8 gain questions, 2 of 8 variance questions
  and 4 of 7 scheme differences. It is reported, not used to reject.
- **The server does not return per-replicate values**, so for the
  probability-of-beating questions an agent using it must either assume the
  paired difference is normal (P = Phi(mean / sd)) or make 100
  single-replicate calls. The alt setup can count wins directly.
- **The questions spell out the R calls.** They test running a stated
  simulation, not designing one from a breeder's description.
- **One model, one date.**

## Questions

[`questions.json`](questions.json) holds the 40 questions with their keys,
built 2026-10-17 (UTC; the evening of 2026-10-16 EDT) on AlphaSimR 2.1.0
with seed 20261016. `build_questions.py` draws every design from fixed grids
with a seeded RNG, so none is hand-picked. All use quickHaplo founders with
10 chromosomes × 100 segregating sites and an additive trait with 10 QTL per
chromosome, founder genetic variance 1, h2 fixed at founding: exactly what
`found_population` builds. Each question gives the founding calls, the
per-generation calls, the statistic, the number of replicates to base the
answer on, and the band.

| Kind | Count | Design grid | Statistic | Key replicates | Answer replicates | Candidates rejected |
|---|---|---|---|---|---|---|
| Control: one-cycle response | 6 | N 500 or 1000, 5-30% selected | `meanG` after 1 generation | 400 | 50 | 3 of 18 |
| Gain after 5-10 cycles | 8 | N 20-100, 10-30% selected, h2 0.2-0.8 | `meanG` after the last generation | 400 | 50 | 0 of 16 |
| Genetic variance left after 5-10 cycles | 8 | as above | `varG` after the last generation | 400 | 50 | 1 of 16 |
| Difference between two schemes | 7 | N 30-100, 5-10% vs 30-50% selected, 5-15 cycles | paired `meanG(A) - meanG(B)` | 400 | 50 | 0 of 14 |
| Probability scheme A beats B | 6 | as above | fraction of paired replicates where A ends higher | 400 | 100 | 14 of 40 |
| Genomic prediction accuracy | 5 | N 100-300, 10-20% selected, 100-400 SNPs, 4-6 cycles | `cor(ebv, gv)` on the progeny in the last generation | 300 | 50 | 0 of 12 |

`build_questions.py`, `simulate_key.R` and `theory.py` never import
`breedsim_mcp` (`tests/test_agent_qa_score.py` checks the imports). Two
questions where the ranking flips: in q34 the stronger scheme (2 of 50
selected) ends ahead of the weaker one (15 of 50) in only 5.5% of replicates
after 15 cycles, and in q26 the expected difference is -0.02 where R = h2 S
per cycle predicts +3.5 (the infinitesimal recursion with drift gets close,
-0.29).

### The band

    half_width = 3 × sd × sqrt(1 / R_answer + 1 / R_key), rounded up to 2 significant figures

`sd` is the per-replicate standard deviation of the statistic in the key's
own replicates (for a proportion, `sqrt(p (1 - p))`); `R_answer` is the
replicate count the question asks for and `R_key` the key's. There is no
theory slack. The answer's own Monte Carlo noise is 80-89% of the band's
variance (`answer_noise_share` in each key), and the key's standard error is
at most 15% of any half-width. A careful answer from the stated replicates
lands inside about 99.7% of the time; one from far fewer replicates often
does not, which is intended.

### Which shortcuts the bands catch

A candidate design becomes a question only if every shortcut named for its
category lands outside its band (and, in the control, the textbook answer
lands inside). `uv run python benchmarks/agent_qa/build_questions.py --discrimination`
on this key:

| Kind | Shortcut | Must | Outside the band in |
|---|---|---|---|
| control_response | breeder's equation, R = i(n,N) h | hit | 0 of 6 |
| control_response | R = i h2 (sigma_P dropped) | (reported) | 6 of 6 |
| long_term_gain | R = h2 S every cycle, infinite-population i | miss | 8 of 8 |
| long_term_gain | R = h2 S every cycle, finite i(n,N) | miss | 8 of 8 |
| long_term_gain | Bulmer effect, no drift | miss | 8 of 8 |
| long_term_gain | Bulmer + drift, infinitesimal | (reported) | 5 of 8 |
| remaining_variance | unchanged (1) | miss | 8 of 8 |
| remaining_variance | drift only, (1 - 1/(2n))^t over the n parents | miss | 8 of 8 |
| remaining_variance | Bulmer effect, no drift | miss | 8 of 8 |
| remaining_variance | Bulmer + drift, infinitesimal | (reported) | 6 of 8 |
| scheme_difference | R = h2 S every cycle, infinite-population i | miss | 7 of 7 |
| scheme_difference | R = h2 S every cycle, finite i(n,N) | miss | 7 of 7 |
| scheme_difference | Bulmer effect, no drift | miss | 7 of 7 |
| scheme_difference | Bulmer + drift, infinitesimal | (reported) | 3 of 7 |
| prob_beats | certain: 1 or 0 by the sign of the breeder's-equation difference | miss | 6 of 6 |
| prob_beats | coin flip (0.5) | miss | 6 of 6 |
| genomic_accuracy | accuracy of phenotypic selection, h | miss | 5 of 5 |
| genomic_accuracy | Daetwyler, Me = number of markers | miss | 5 of 5 |
| genomic_accuracy | zero (no LD in quickHaplo founders) | miss | 5 of 5 |

Every required shortcut misses in every question it applies to. The test
`test_every_named_shortcut_misses_its_band...` recomputes them from
`theory.py` rather than trusting the stored flags; promoting the reported
infinitesimal recursion to "must miss" makes it fail (on q08).

## Scoring

Each reply ends with `ANSWER: <number>` or `ANSWER: UNKNOWN`. `score.py`
decides the verdict from that line alone:

- **right**: the number is within the question's band of the key.
- **wrong**: a number outside the band, or no number on the line.
- **declined**: `UNKNOWN`.
- **no answer**: there is no `ANSWER:` line.

Other spellings of the same number count as that number: `79%` is 0.79, a
Unicode minus is a minus, thousands separators are dropped. Every answer also
records `rel_error`, and `agent_qa_error.png` plots each miss in units of
its band. Tests: `tests/test_agent_qa_score.py`.

## Pilot (2026-10-16)

Two questions × three setups × one run; pilot rows are not in
`results.jsonl`. Claude Code 2.1.302, every run exited 0.

| Setup | q07 (gain after 8 cycles, N = 30; key 5.87 ± 0.32) | q36 (genomic accuracy, generation 6; key 0.229 ± 0.043) | Tool calls |
|---|---|---|---|
| Claude alone | wrong, 5.2, 21 s, $0.050 | wrong, 0.5, 22 s, $0.047 | none offered |
| Claude + Bash, R and web | right, 5.98, 13 s, $0.055 | right, 0.210, 21 s, $0.034 | 2 Bash each: check AlphaSimR, then a 50-replicate script |
| Claude + breedsim-mcp | right, 5.68, 13 s, $0.075 | right, 0.210, 25 s, $0.070 | `found_population` then `run_program` (50 replicates; `selection_method="genomic"` for q36) |

Claude alone answered from theory both times (the infinitesimal recursion
for q07, adjusted down by hand; a guess of 0.45-0.6 for q36) and did not
decline. Both tool setups ran the simulation with the stated founders and 50
replicates. On these two questions the server and Claude's own AlphaSimR
script did equally well; the sweep will say whether that holds.

## Reproduce

```bash
uv run python benchmarks/agent_qa/build_questions.py            # re-derive the key (~20 min, 4 R processes)
uv run python benchmarks/agent_qa/run.py --reps 3 --workers 1   # 360 claude -p runs; resumable
uv run python benchmarks/agent_qa/run.py --rescore              # re-score stored replies after a key fix
Rscript benchmarks/agent_qa/plot.R                              # summary.tsv + figures
```

The key build caches each design's simulation under a hash of the design and
`simulate_key.R` (`AGENT_QA_KEY_CACHE`, default
`~/.cache/breedsim-agent-qa-key`); a rebuild from the cache reproduced
`questions.json` byte for byte.

Each run is an isolated `claude -p`:
- `--setting-sources ""` and an empty working directory.
- `--strict-mcp-config`, so no other MCP servers.
- The same short system prompt in every setup.

`R_LIBS_USER` must point at a library with AlphaSimR (default
`~/R/library`); the `mcp` and `alt` setups both get it. Tool and Bash
timeouts are raised to 15 minutes so a 50-replicate run is not cut off. One
worker by default, since each `mcp` run starts its own R. Raw transcripts go
to `runs/`, which is gitignored.
