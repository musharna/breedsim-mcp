# Mutation checks

Each guard was actually disabled in the working tree, the paired test was run
against the mutated code, and the file was restored from a backup before the next
mutant. A guard whose test passes with the guard removed is not a test.

Baseline: `uv run pytest -q` → 30 passed.

| guard                        | mutation applied                                          | result |
| ---------------------------- | --------------------------------------------------------- | ------ |
| replicate floor (THE rule)   | `if replicates < MIN_REPLICATES:` → `if False:`           | RED    |
| floor at the **tool** layer  | `replicates=replicates` → `replicates=max(replicates, 5)` | RED    |
| `reproducible` flag          | `generator == "quickHaplo"` → `True`                      | RED    |
| thread pin                   | `os.environ.setdefault("OMP_NUM_THREADS","1")` → `pass`   | RED    |
| `nondeterministic_founders`  | early-return made unconditional                           | RED    |
| `threads_not_pinned`         | early-return made unconditional                           | RED    |
| `replicates_too_few`         | early-return made unconditional                           | RED    |
| `variance_exhausted`         | early-return made unconditional                           | RED    |
| `run_program` `outputSchema` | `-> RunResult` → `-> dict`                                | RED    |
| standard deviation           | `statistics.stdev(...)` → `0.0` (fake precision)          | RED    |

## Two mutants worth explaining

**The floor is mutated at BOTH layers, deliberately.** The library-level mutant
(`replication.py`) and the tool-level mutant (`server.py`) are separate entries
because a library test does not protect a server passthrough. That exact pairing
error survived two rounds on `plantcv-mcp` — a parameter correct in the library
and silently dropped at the server had no test at all, even after being "fixed".
Pair a mutant with a test that exercises the layer the mutation is in.

**Forcing `sd` to zero** is the fake-precision mutant. A collapsed confidence
interval does not look like a bug; it looks like an unusually clean result. Since
the entire point of this server is that a lone number is not an answer, a silently
zero interval would defeat it while appearing to strengthen it.

## Round 5 — the tool-layer sequence (added after a P0)

| # | mutant | test that went red |
| - | ------ | ------------------ |
| 11 | `engine._rpy2()` reverted to importing rpy2 lazily on first use | `test_tool_layer_sequence.py::test_four_tool_calls_in_one_fresh_process` |
| 12 | `INSTRUCTIONS` f-prefix removed, leaking a literal `{RUNMACS_RNG_NOTE}` | `test_diagnostics_and_server.py::test_agent_facing_text_derives_from_one_source` |

Mutant 11 is the one worth reading. It restores the code that shipped, and the
whole rest of the suite stays green against it — because every other test imports
rpy2 into the pytest process's root context via a direct library call before any
tool is invoked, which masks the defect completely. Only a **fresh subprocess that
touches R exclusively through `call_tool`** goes red, with the real error:
`Conversion rules for rpy2.robjects appear to be missing`.

That is the layer-pairing rule again, and this time it cost a P0: 27 passing tests
described a server that was broken for every real client after its first request.
A test that cannot fail in the process it runs in is not covering the thing it
names.

## Not mutated, and why

`diagnostics.BLOCKING_CODES` is empty by design, so there is nothing to disable.
Unlike `plantcv-mcp`, no warning here withholds a result: outputs are always
distributions, so a caller can already see when an answer is too noisy to use.

Re-run these whenever a guard's logic changes.
