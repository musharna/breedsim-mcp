# Lessons

One line per missed bar: the class of miss, and the mechanism that now catches it.

- 2026-09-22 — A refusal allowlist named this package's exceptions but not the engine's (rpy2 `RRuntimeError`), so every R-side failure was masked. Now converted once at `engine.r_eval`; `test_an_unanticipated_r_error_reaches_the_caller_with_rs_message` pins the class, not an instance.
- 2026-09-22 — A lookup table that rounds to the nearest listed entry rounded every statistic in the unsafe direction (t quantile too small → CIs too narrow). Replaced with the exact function; `tests/test_t_quantile.py` checks every allowed n against an R-independent reference.
- 2026-09-22 — A diagnostic's baseline was "the first reported value", which is after the effect it measures had already acted (cycle-1 variance, post-selection). Baselines are now the pre-treatment state, tested through the tool on a one-cycle run.
- 2026-09-22 — A validation lived only inside the branch where it was first needed (`n_qtl_per_chr <= seg_sites` only with a SNP chip). Bounds that hold unconditionally are now checked unconditionally; each is tested through the MCP layer with its valid extreme as a positive control.
