# Pre-registration: model-tier re-run, 2026-10-20

Committed and pushed before either confirmatory sweep. Anything run after the
sweeps is exploratory and is labeled so.

**Why.** On Opus 5.5 the server and Claude's own scripts were both at ceiling
(10-18: 34 and 34 of 34 headline questions right in all 3 runs), so accuracy
could not separate them. The question now is whether the server lifts a
weaker model's accuracy.

**Tiers.** Two confirmatory tiers, same design: Claude Haiku 5.5
(`claude-haiku-5-5`), then Claude Sonnet 5.5 (`claude-sonnet-5-5`), both in
this session, Sonnet right after Haiku. No Opus rows are reused for the
primary endpoint.

**Server under test.** breedsim-mcp 0.6.1, the current PyPI release, run as
`git+https://github.com/musharna/breedsim-mcp@6c095adc1df0c7634642edcccdfaa4823ed2f004`
(tag v0.6.1, the release merge) with `--exclude-newer 2026-10-17`: the 10-18
re-run's pinning. Its `src/` is identical to the 10-18 commit 7038ec0; only the
version number changed. Resolved on 2026-10-20: breedsim-mcp 0.6.1, mcp 2.3.0,
rpy2 3.5.17, numpy 2.5.4 on CPython 3.14.3, the 10-18 environment. AlphaSimR
2.1.0 on R 4.3.3 for the key, the server and the alt arm (`run.py` refuses any
other). Claude Code 2.1.305.

**Arms.** As before, with the same prompt, system prompt, isolation and tools:
`bare` (no tools), `alt` (Bash with R + AlphaSimR and Python, Read,
WebSearch, WebFetch) and `mcp` (this server only). All three are re-run on
each tier, interleaved: for each rep, each question runs bare, alt, then mcp.
`--workers 1`.

**Questions, reps, scorer, key.** The 40 questions in `questions.json`,
unchanged (sha256 `b2413a36…`), 3 reps per arm: 360 runs per tier. Scorer
`score.py` and the validity rule `analyse.py invalid_reason` unchanged; the
leak scan as fixed on 10-18 (a run's own cwd is ignored). The key is
AlphaSimR 2.1.0 on seeded founders and depends on no live state. Oracle,
2026-10-20: the key's values score 40 of 40 right and moved 1.5 band-widths 0
of 40; `run.py` repeats it before each sweep. No rebuild.

**Primary endpoint, per tier.** Accuracy on the 34 headline questions (the
probability category stays out, as on 10-17 and 10-18): a question counts
right if all 3 runs were right (an invalid run is not right). mcp vs alt by
the exact two-sided McNemar test over questions, with the 95% bootstrap CI
(10,000 resamples of questions, seed 1) of the mcp − alt accuracy, as
`analyse.py` computes them (`headline.mcp_vs_alt`,
`headline.bootstrap_95["mcp - alt accuracy"]`).

**Win rule.** Holm across the 2 tiers on the McNemar p-values.

- A tier shows a **lift** if its Holm-adjusted p < 0.05 and more questions are
  right only under mcp; a **loss** if adjusted p < 0.05 and more are right
  only under alt.
- **Win**: a lift at ≥ 1 tier and no loss at the other.
- **Loss**: a loss at ≥ 1 tier and no lift. **Mixed**: a lift at one tier and
  a loss at the other (not a win). **Tie**: neither.

All of it is `tiers.py`.

**Secondary, descriptive (no rule).**
- The bare floor per tier, and mcp vs bare, alt vs bare (McNemar).
- **Substitute claim**: each tier's mcp arm against the 10-18 Opus alt rows
  (`rerun_2026-10-18`), McNemar on headline questions right in all 3 runs.
  Non-concurrent (a different day and sweep), labelled so.
- **Mechanism**: server tool calls per mcp run, mcp runs with 0 server calls
  (outside the control these are invalid under the validity rule, so they
  count as not right), calls by a bare tool name, runs using `final_only`.
  A server arm that never calls its tools is reported as "mechanism did not
  fire".
- Cost and time per answer (median, bootstrap CI), and the 10-18 cost test
  (`cost_mcp_vs_alt`) per tier. All 40 questions as a second view.

**Controls.** The oracle in `run.py` before each sweep; the no-LLM baselines
(`baselines.tsv`, unchanged); the validity rule; the leak scan over every
transcript; the served model read from every run's init event
(`results.jsonl` `model`, `versions.json` `models_served`). A tier whose runs
were served by a model other than the one requested is reported as such.

**Usage gate and re-run rule.** Before each sweep a one-word probe on the
tier's model reads the usage windows; a sweep starts only when five-hour
< 0.50 and seven-day < 0.90 (the 0.90 stop is the coordinator's 10-20
amendment; it was 0.80). `run.py` sleeps until the window resets whenever a
run shows five-hour ≥ 0.85 or a rejected request (each pause in
`pauses.jsonl`), and stops (exit 3) when a run shows seven-day ≥ 0.90; the
rows so far are kept and reported, and the stop is reported. A row the API
ended before any model answer (`api_failure`: a rejected request and no
assistant message, read from the transcript) is a harness failure: after the
sweep, `run.py --drop-api-failures` moves those rows aside and a resume runs
each once more; a triple that fails that way twice stays and counts as
invalid. No other retries; an interrupted sweep is resumed, not restarted,
and not stopped early on interim results.

**Reporting.** Every result is reported, whatever it shows, in a dated README
section; the headline and "Does it help?" change only from this confirmatory
result, after both tiers are in. The Opus results stay published.

**Sweep commands.** Per tier (`M=claude-haiku-5-5`, then
`M=claude-sonnet-5-5`), under the shared sweep lock:

```bash
flock ~/.claude/jobs/9cc8114d/tmp/sweep.lock env HEAVY_RUN_MEM=6G heavy-run \
  ~/breedsim-mcp-artifacts/tiers_1020/both_tiers.sh   # gated_sweep.sh haiku, then sonnet
```

For each tier `gated_sweep.sh $M` probes the usage windows (gate above),
checks `df -h /` (stops under 5 GB free), runs the pilot and its check, then
runs, with `A=~/breedsim-mcp-artifacts/tiers_1020/$M`:

```bash
python3 benchmarks/agent_qa/run.py --model $M --arms bare,alt,mcp --reps 3 --workers 1 \
  --results $A/results.jsonl --runs $A/runs --work $A/work \
  --server-spec git+https://github.com/musharna/breedsim-mcp@6c095adc1df0c7634642edcccdfaa4823ed2f004 \
  --exclude-newer 2026-10-17
# transcripts land in $A/runs-$M/
```

and then `--drop-api-failures` and the one resume.

**Analysis.**

```bash
D=benchmarks/agent_qa/tiers_2026-10-20/<haiku|sonnet>
mkdir -p $D && cp $A/results.jsonl $A/versions.json $D/
uv run python benchmarks/agent_qa/analyse.py $D/results.jsonl $A/runs-$M
uv run python benchmarks/agent_qa/tiers.py haiku=benchmarks/agent_qa/tiers_2026-10-20/haiku \
  sonnet=benchmarks/agent_qa/tiers_2026-10-20/sonnet --opus benchmarks/agent_qa/rerun_2026-10-18 \
  --out benchmarks/agent_qa/tiers_2026-10-20/verdict.json
```

**Pilot, per tier, immediately before its sweep** (inside the same hold of
the lock; the lock queue was hours long, so it did not run before this
file). q12 and q36, bare, alt and mcp, 1 rep, into `$A/pilot/`, never
merged into the results. Feasibility only: `pilot_check.py` (beside the
wrapper) stops the tier, before any confirmatory run, if a pilot run did
not exit 0, was served another model, lacked its arm's tools, or made no
tool call. The pilot's verdicts are not read and change nothing in this
design. Haiku and Sonnet run in one hold of the lock
(`~/breedsim-mcp-artifacts/tiers_1020/both_tiers.sh`); a stop in the Haiku
tier means Sonnet does not start.

## Amendment, 2026-10-23 ~19:20 EDT: API billing (before any further run)

- **Billing.** The user's decision: every remaining run in this design (both
  tiers) bills an Anthropic API key, not the Claude subscription. Same model
  IDs, prompts, arms, reps, harness and controls. Claude Code is 2.1.309 now
  (recorded per row).
- **How.** A benchmark-only `claude` wrapper, first on `PATH` for the sweep,
  loads the key and then `exec`s the real CLI (so the harness's timeout still
  kills Claude itself). It records each run's cost (Claude Code's
  `total_cost_usd`; for a killed run, estimated from its token counts) and
  refuses to start a run once the total reaches $171 of the user's $175 cap
  (exit 75, no transcript). A run whose `init` event does not show
  `apiKeySource: ANTHROPIC_API_KEY` stops every later launch.
- **Gate.** API calls report no subscription windows, so the seven-day stop
  and the five-hour pause no longer fire. `run.py` instead asks the spend gate
  (`BENCH_SPEND_GATE`) before every run and, on a refusal, stops cleanly as
  at the seven-day stop: finished rows stay, nothing new starts. Test added,
  seen to fail with the check disabled (`mutate-run`).
- **Set aside by exit code, not outcome.** A run the wrapper refuses (exit
  75) is a harness failure, not a result: it is set aside and re-run once.
- **Concurrency.** Up to 4 servers' sweeps run at once (2 before). The
  workers per sweep are unchanged.
- **Harness fault, 20:38-20:52 EDT, and set-aside (recorded before any analysis).**
  The first API-billed launch hid the key from the agent's tools with
  `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1`. That setting also forces Claude
  Code's permission mode to `default` (checked live: with it, a run asking for
  `bypassPermissions` starts in `default`; without it, on either billing
  source, it starts in `bypassPermissions`). The data-aggregator arms ask for
  `bypassPermissions`, so their tools were denied (91 of 91 Haiku runs had
  denials; median 7 turns against 21.5 before). The coordinator stopped every
  sweep at 20:52. Rule, by time window and not by outcome: **every run
  started under that wrapper, on every server and tier, is set aside and
  re-run** (`*.scrub_2026-10-23*`, `_scrub/` for data-aggregator), including
  servers whose arms ask for `default` mode and showed no change. The key now
  reaches Claude Code through an `apiKeyHelper` flag setting (`--settings`),
  never the environment; the run's `init` must show `apiKeySource:
  apiKeyHelper` and the permission mode the harness asked for, or every later
  launch stops.
- **Where the billing check lives (clarification, 2026-10-24, after the
  sweeps; changes no rule).** The two "stops every later launch" checks above
  are not in `run.py`. They are in the benchmark-only wrapper, which is
  outside this repo (`~/.claude/state/mcp-bench-api/`). After each run its
  recorder (`bench_spend.py record`) reads the `init` event and writes a
  `BILLING_VIOLATION` flag if `apiKeySource` is wrong or the permission mode is
  not the one the harness asked for. From then on `bench_spend.py check` exits 5,
  so the wrapper refuses every launch (exit 75) and `run.py`'s spend gate
  stops the sweep. The wrapper's own test (`test_wrapper.py`, cases 4 and 7)
  raises both flags and checks that launches are blocked, then that they
  start again once the flag is cleared. The recorder runs after a run ends,
  so a run already started on another worker can still finish. The ledger
  logged 769 breedsim runs: 37 with `ANTHROPIC_API_KEY` (all inside the
  20:38-20:52 set-aside window) and 732 with `apiKeyHelper`, each in the
  asked-for mode. No flag was ever raised, and no run was refused with exit
  75. `run.py` now marks an exit-75 refusal with no transcript as
  `api_failure`, so `--drop-api-failures` sets it aside as the rule above says.
