# Agent benchmark: breeding-simulation questions with and without the server

Does Claude answer breeding-programme questions better with breedsim-mcp than
without it? 40 questions, asked 3 times each to Claude Opus 5.5 in Claude
Code under three setups:

- **Claude alone**: no tools.
- **Claude + Bash, R and web**: Bash (R with AlphaSimR, and Python, on the
  PATH), Read, WebSearch and WebFetch. This is what a user has without the
  server: Claude can write and run its own AlphaSimR code.
- **Claude + breedsim-mcp**: this server (0.5.1 from PyPI, via `uvx`) only.

Sweep run 2026-10-16/17 (EDT): 40 questions × 3 runs × 3 setups = 360 runs,
all exited 0, all valid, no leaks. The headline leaves out the 6
probability-of-beating questions, where one constant lands in 5 of 6 bands
(below); they are reported separately.

![Right, wrong or declined per setup and per no-LLM baseline](agent_qa.png)

Headline, 34 questions × 3 runs (102 answers per setup; baselines answer
each question once). Intervals are bootstrap 95% over questions.

| Setup | Right | Wrong | Questions right in all 3 runs | Accuracy, 95% CI | Cost / answer, median [CI] | Seconds / answer, median [CI] | Tool calls, median |
|---|---|---|---|---|---|---|---|
| Claude alone | 51 | 51 | 12 of 34 | 0.50 [0.35, 0.65] | $0.036 [0.034, 0.040] | 18.0 [16.2, 19.7] | 0 |
| Claude + Bash, R and web | 99 | 3 | 33 of 34 | 0.97 [0.91, 1.00] | $0.028 [0.026, 0.030] | 15.2 [13.9, 16.9] | 2 |
| Claude + breedsim-mcp | 102 | 0 | 34 of 34 | 1.00 [1.00, 1.00] | $0.051 [0.047, 0.054] | 16.9 [15.5, 18.5] | 2 |
| No LLM: one constant per kind (the key's category median) | 12 | 22 | 12 of 34 | 0.35 | - | - | - |
| No LLM: best named closed form per question | 15 | 19 | 15 of 34 | 0.44 | - | - | - |

Not in the headline, 6 probability questions × 3 runs: Claude alone 15 of
18 right, Bash + R 18 of 18, breedsim-mcp 18 of 18; the category-median
constant 5 of 6. Over all 40 questions: 66, 117 and 120 of 120. No setup
declined a question. `summary.tsv` (written by `plot.R`) and
`analysis.json` (written by `analyse.py`) hold every number here.

## What it shows

- **Both tool setups beat Claude alone, decisively.** Per question (right
  in all 3 runs), breedsim-mcp beats Claude alone on 22 questions and loses
  on none (exact McNemar p = 5e-7); Bash + R beats it on 21 and loses on
  none (p = 1e-6). Claude alone got the one-cycle control right every time
  and lost most where the answer needs simulation: 0 of 15 genomic
  accuracy answers, 9 of 24 gains after 5-10 cycles.
- **breedsim-mcp and Bash + R are not separated on accuracy.** They agree
  on 33 of 34 questions; the one difference (q09) is p = 1.0, and the
  bootstrap interval of the accuracy difference, [0.00, 0.09], includes 0.
  Bash + R's only misses are q09, where it ran exactly the stated
  simulation with seeds 1-50 in all three runs and got 3.86 against a key
  of 3.65 ± 0.21: a 3.05-SE draw of honest Monte Carlo noise, not a setup
  error. Re-running the same script on seeds 1001-1050 and 2001-2050 gives
  3.63 and 3.68, both inside the band.
- **What does separate them is cost: Bash + R is cheaper.** Median
  $0.028 [0.026, 0.030] per answer against $0.051 [0.047, 0.054] for
  breedsim-mcp; the intervals do not overlap. Time is not separated (15.2 s
  [13.9, 16.9] against 16.9 s [15.5, 18.5]). Both made a median of 2 tool
  calls. One breedsim-mcp run (q24, rep 3) took 1,360 s for the same two
  calls its sibling runs made in about 15 s; the cause was not found, and it
  moves the mean, not the median.

So on questions that spell out the AlphaSimR calls, this server makes Claude
as accurate as Claude writing its own AlphaSimR script, at about 1.8 times
the cost per answer, and both are far better than answering from theory.

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
  and 4 of 7 scheme differences. The baselines row "best named closed form
  per question" counts that: 15 of 34 headline questions.
- **Some bands admit a constant.** One number per kind of question (the
  median of the key over that kind, which no setup can know) lands inside
  12 of the 34 headline bands: 2 of 6 controls, 0 of 8 gains, 3 of 8
  variances, 4 of 7 scheme differences, 3 of 5 genomic accuracies, and 5 of
  6 probabilities. The probability questions are therefore out of the
  headline; scheme differences and genomic accuracy are kept but are close
  behind, so a right answer there is weaker evidence than in the gain
  questions.
- **The server does not return per-replicate values**, so for the
  probability-of-beating questions an agent using it must either assume the
  paired difference is normal (P = Phi(mean / sd)) or make 100
  single-replicate calls. The alt setup can count wins directly.
- **The questions spell out the R calls.** They test running a stated
  simulation, not designing one from a breeder's description. That favours
  the Bash setup, which can paste the calls.
- **One model, one date.**

## Controls

All in [`analyse.py`](analyse.py), run on the stored results with no new
Claude runs, and tested in `tests/test_agent_qa_controls.py` (each check is
paired with a case it must reject, and each was seen to fail under a
planted mutation).

- **Oracle.** The frozen key's own values, written as replies, score 40 of 40
  right through `score.py`; the same values moved 1.5 band-widths score 0 of
  40. `run.py` repeats the oracle check before every sweep.
- **Baselines** (negative controls, scored through `score.py`): the
  category-median constant, and every named closed form on the questions it
  applies to. Per-question rows are in `baselines.tsv`, totals in
  `summary.tsv` (`level = baseline`). Apart from the control's textbook
  answer (6 of 6, as designed) and the infinitesimal recursion (9 of 23),
  every named closed form scored 0.
- **Validity, one rule for every setup.** A run counts only if it exited 0,
  its setup's tools were offered (none for Claude alone, Bash for Bash + R,
  a connected breedsim server for breedsim-mcp; read from the init event),
  and, outside the control category, a tool setup made at least one tool
  call. Invalid runs would be shown as "invalid" and counted as not right.
  Result: 360 of 360 valid. No run was retried except one: the sweep was
  interrupted once after 157 rows, and the run in flight then (Bash + R,
  q13, rep 2) was run again on resume, as any setup's would have been.
- **Leak scan.** Every transcript's tool inputs and outputs (not the prompt)
  were searched for the key's file names, the benchmark directory (locally
  or on GitHub), the key cache and the pilot directory (`LEAK_PATTERNS`).
  360 transcripts scanned, 0 hits. The Bash setup's scripts wrote to fixed
  paths such as `/tmp/sim/s.R` that later runs could also see; each run now
  gets its own `TMPDIR`, but a literal `/tmp` path is still shared, and the
  scan does not look for one run reading another's script.

## Versions

| What | Version | How fixed |
|---|---|---|
| Model / harness | claude-opus-5-5, Claude Code 2.1.302 | recorded per run (init event) |
| Server (breedsim-mcp arm) | breedsim-mcp 0.5.1 from PyPI via `uvx`; it resolved mcp 2.3.0, rpy2 3.5.17, numpy 2.5.4 on CPython 3.14.3 | server pinned in `run.py`; its dependencies were not |
| AlphaSimR (key, server and Bash setup) | 2.1.0 on R 4.3.3, from `~/R/library` | `run.py` refuses to start on any other version; CI installs exactly 2.1.0 (`scripts/install-r-deps.R`) and a test checks key = pin = installed |

## History

Earlier versions, and why each changed:

1. **v1, theory key (commit 183f2c2).** 40 questions whose answers came
   from closed-form theory (intensity, one-cycle response, Bulmer variance,
   gain over 2-3 cycles, drift). In its pilot (q10, q37 × 3 setups × 1 run)
   all six answers were right and no setup called a tool, and its bands
   could not separate the textbook answer from its common shortcuts
   (infinite-population intensity 0 of 12 outside, no Bulmer effect 0 of 8).
   It measured textbook recall, so it was replaced before any sweep.
2. **v2, simulation key (this one).** The design above. While building it,
   genomic accuracy moved from 1 cycle to 4-6: at 1 cycle the accuracy was
   about 0, so the answer "zero" landed in 4 of 5 bands. The probability
   pool grew from 14 to 40 candidates because only 4 of 14 passed. Pilot
   (q07, q36 × 3 × 1): Claude alone wrong on both, both tool setups right.
3. **Controls added after the sweep** (validity, leak scan, baselines,
   oracle, paired statistics, the probability questions out of the
   headline). Re-scoring the stored replies with `run.py --rescore`
   changed no verdict.

Pilot rows, the v1 key and the v1 pilot transcripts are not in git; they
are archived locally under `~/breedsim-mcp-artifacts/agent_qa/history/`.

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

## Reproduce

```bash
uv run python benchmarks/agent_qa/build_questions.py            # re-derive the key (~20 min, 4 R processes)
uv run python benchmarks/agent_qa/run.py --reps 3 --workers 1 \
    --results ~/breedsim-mcp-artifacts/agent_qa/results.jsonl \
    --runs ~/breedsim-mcp-artifacts/agent_qa/runs                # 360 claude -p runs; resumable
uv run python benchmarks/agent_qa/run.py --rescore              # re-score stored replies after a key fix
uv run python benchmarks/agent_qa/analyse.py                    # validity, leaks, baselines, statistics
Rscript benchmarks/agent_qa/plot.R                              # summary.tsv + figures
```

This sweep wrote its results and transcripts inside the repository
(`results.jsonl`, `runs/`); new sweeps should keep both outside it, as
above, so a Bash-armed agent cannot list them. `analyse.py` and `plot.R`
take the results path and the runs directory as arguments.

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
worker by default, since each `mcp` run starts its own R. Raw transcripts are
not committed (`runs/` is gitignored).
