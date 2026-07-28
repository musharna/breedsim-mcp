# Mutation checks

Each guard was actually disabled in the working tree, the paired test was run
against the mutated code, and the file was restored from a backup before the next
mutant. A guard whose test passes with the guard removed is not a test.

Baseline: `uv run pytest -q` → 27 passed.

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

## Not mutated, and why

`diagnostics.BLOCKING_CODES` is empty by design, so there is nothing to disable.
Unlike `plantcv-mcp`, no warning here withholds a result: outputs are always
distributions, so a caller can already see when an answer is too noisy to use.

Re-run these whenever a guard's logic changes.
