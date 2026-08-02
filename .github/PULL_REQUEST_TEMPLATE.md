<!-- Thanks for contributing to breedsim-mcp! -->

## What does this PR do?

<!-- A short description of the change and the motivation. Link any related issue. -->

Fixes #

## Checklist

- [ ] `uv run ruff check .` and `uv run ruff format --check .` pass
- [ ] `uv run pytest -q` passes
- [ ] Any new test was **seen to fail** against the broken state, for the stated reason
- [ ] Any test asserting a refusal also asserts the legitimate path succeeds (positive control)
- [ ] No silent fallbacks or swallowed errors added
- [ ] Updated `CHANGELOG.md` for any user-facing change
- [ ] Updated README/docs if tool signatures or configuration changed
- [ ] Simulation-behaviour changes state the replicate count and report a distribution, never a single run
