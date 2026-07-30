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

| #   | mutant                                                                  | test that went red                                                               |
| --- | ----------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| 11  | `engine._rpy2()` reverted to importing rpy2 lazily on first use         | `test_tool_layer_sequence.py::test_four_tool_calls_in_one_fresh_process`         |
| 12  | `INSTRUCTIONS` f-prefix removed, leaking a literal `{RUNMACS_RNG_NOTE}` | `test_diagnostics_and_server.py::test_agent_facing_text_derives_from_one_source` |

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

## Round 6 — paired comparison and species

| #   | mutant                                                                  | test that went red                                                             |
| --- | ----------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| 13  | arm B seeded independently (`seed + 7919`), breaking the pairing        | `test_comparison.py::test_pairing_uses_the_same_seed_for_both_arms`            |
| 14  | `_verdict` returns the sign of the mean instead of reading the interval | `test_comparison.py::test_verdict_reads_the_interval_not_the_mean`             |
| 15  | `species` validation disabled (`if False`)                              | `test_diagnostics_and_server.py::test_species_is_validated_not_passed_through` |

Mutant 13 is the one that quantifies the feature. Breaking the pairing made two
IDENTICAL programmes differ by 0.169 and 0.271 — the same order as the sd 0.247
that the replicate floor exists for. That is precisely the noise common random
numbers removes, and it is why a comparison assembled from two independent
`run_program` calls can invent a winner out of nothing.

Mutant 14 exposed a real coverage gap rather than confirming coverage. The
identical-arms test cannot catch it: its difference is exactly zero, so a verdict
returning the sign of the mean still answers `None` and passes. The interval
logic needed a test built on literals, where a positive mean can be paired with
an interval that straddles zero. **A test whose subject is always zero cannot
discriminate a rule about signs.**

## Round 7 — post-0.1.0 audit

| #   | mutant                                                        | test that went red                                                                   |
| --- | ------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| 16  | `_free_r_state` restored to the version that shipped in 0.1.0 | `test_session_eviction.py::test_eviction_frees_every_object_the_session_owned`       |
| 17  | `check_upper` made a no-op (no ceilings, the 0.1.0 state)     | `test_session_eviction.py::test_oversized_requests_are_refused_at_every_entry_point` |

Mutant 16 is a released bug, not a hypothetical: it restores real 0.1.0 code and
the test goes red with `evicted session leaked R objects: [...]`, five of them.

The instructive part is why no test caught it originally. The obvious eviction
test — list the globals, assert they are gone — **passes against the broken code**
if it lists them with a bare `ls()`, because that is precisely the call that
cannot see dot-prefixed names. The harness would have inherited the bug it was
meant to detect and reported success. The test therefore uses
`ls(all.names=TRUE)`, and the docstring says why.

**A test that reuses the failing component's own assumption cannot detect that
assumption being wrong.**

## Round 8 — genomic selection

| #   | mutant                                                                                              | test that went red                                                                 |
| --- | --------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| 18  | `no_linkage_disequilibrium_warning` keyed on `generator == "runMacs"` instead of the measured ratio | `test_genomic.py::test_ld_advisory_keys_on_the_measurement_not_the_generator_name` |
| 19  | the second `setEBV` dropped, so accuracy is scored on the model's own training generation           | `test_genomic.py::test_reported_accuracy_is_out_of_sample_not_the_models_own_fit`  |
| 20  | genomic branch selects with `use="pheno"`                                                           | `test_genomic.py::test_the_two_methods_take_different_paths`                       |

Mutant 18 is the one worth dwelling on, because the name-based guard **agrees with
the measured guard on every population AlphaSimR actually produces**: runMacs always
has LD, quickHaplo never does. Real founders therefore cannot separate the two
implementations. The test constructs sessions whose generator name and measured LD
disagree — a runMacs population measured flat, a quickHaplo population measured
linked — because those are the only inputs on which the two guards differ. **When
two candidate predicates agree on all natural data, the test has to supply
unnatural data or it is not testing the predicate at all.**

Mutant 19 restores what an obvious simplification would produce. It matters because
the resulting number stays entirely plausible — an in-sample fit looks like a
perfectly reasonable accuracy — so nothing in the output would look wrong. The test
pins it by recomputing the in-sample value and requiring the reported one to differ.

### Not mutated: an accuracy threshold in place of the LD check

Tempting, and it cannot work, so the test asserts the negative directly rather than
mutating toward it. Measured at 20 replicates, a population with an LD ratio of 1.00
reached out-of-sample accuracy **0.208** by cycle three — above any floor worth
setting — because in a closed population markers predict by tracking relatedness as
well as by linkage. An accuracy gate would pass exactly the population it claimed to
catch. `test_accuracy_advisory_cannot_substitute_for_the_ld_check` encodes that
measured counterexample.

**A guard has to be measured on the mechanism it names, not on a downstream symptom
that several mechanisms share.**

## Not mutated, and why

`diagnostics.BLOCKING_CODES` is empty by design, so there is nothing to disable.
Unlike `plantcv-mcp`, no warning here withholds a result: outputs are always
distributions, so a caller can already see when an answer is too noisy to use.

Re-run these whenever a guard's logic changes.
