"""The work-count ratchet: each tool's call counts equal the committed baseline.

Counts, not milliseconds: a timing budget needs headroom, and a regression
smaller than the headroom passes. An exact count is identical on every run, so
the ceiling is the baseline itself. See ``perf_ratchet.py`` for what is counted
and how to record a change (``--update``; a rise also needs
``--allow-increase``).
"""

from __future__ import annotations

import json
import os

import perf_ratchet as pr
import pytest


# mutmut wraps every package function in a trampoline, which changes every
# call count; under it this gate would fail its clean run and "kill" every
# mutant. It sets MUTANT_UNDER_TEST in all of its phases.
@pytest.mark.skipif(
    "MUTANT_UNDER_TEST" in os.environ, reason="mutmut trampolines change call counts"
)
def test_every_tools_work_counts_equal_the_baseline():
    baseline = json.loads(pr.BASELINE.read_text())
    assert set(baseline) == set(pr.WORKLOADS), "baseline and workloads disagree"
    measured = pr.measure()
    problems = pr.compare(baseline, measured)
    assert not problems, (
        "work counts moved (exact gate, zero headroom). If the change is intended, "
        "record it: `uv run python tests/perf_ratchet.py --update` (add "
        "--allow-increase for a rise).\n" + "\n".join(problems)
    )


def test_the_comparison_names_the_function_and_its_delta_and_passes_an_equal_row():
    """The gate's own discrimination, without R: one extra call in one
    function must surface as that function with +1, and an untouched workload
    must not be reported. Paired in one test so a compare() that reported
    everything (or nothing) fails here."""
    base = {
        "a": {
            "counts": {
                "python_calls": 10,
                "r_evals": 3,
                "r_function_calls": 3,
                "x.py:f": 4,
            }
        },
        "b": {
            "counts": {
                "python_calls": 5,
                "r_evals": 1,
                "r_function_calls": 1,
                "x.py:g": 5,
            }
        },
    }
    moved = json.loads(json.dumps(base))
    moved["a"]["counts"]["python_calls"] = 11
    moved["a"]["counts"]["x.py:f"] = 5
    problems = pr.compare(base, moved)
    assert problems[0] == "a: python_calls 10 -> 11"
    assert "    +1  x.py:f  (4 -> 5)" in problems
    assert not any(p.startswith("b:") for p in problems)
    assert pr.compare(base, base) == []


def _row(python_calls: int, sig: list) -> dict:
    return {
        "signature": sig,
        "counts": {"python_calls": python_calls, "r_evals": 3, "r_function_calls": 3},
    }


def test_update_refuses_a_rise_without_allow_increase_and_records_a_drop():
    base = {"a": _row(10, [2, 5]), "b": _row(7, [1])}
    rise = {"a": _row(11, [2, 5]), "b": _row(7, [1])}
    drop = {"a": _row(9, [2, 5]), "b": _row(7, [1])}
    assert "rose in ['a']" in pr.update_refusal(base, rise, allow_increase=False)
    assert pr.update_refusal(base, rise, allow_increase=True) is None
    assert pr.update_refusal(base, drop, allow_increase=False) is None


def test_update_refuses_a_changed_output_signature_even_with_allow_increase():
    base = {"a": _row(10, [2, 5]), "b": _row(7, [1])}
    other = {"a": _row(10, [2, 4]), "b": _row(7, [1])}
    for allow in (False, True):
        msg = pr.update_refusal(base, other, allow_increase=allow)
        assert msg and "signature changed in ['a']" in msg
    # Same signature, same counts: nothing to refuse.
    assert pr.update_refusal(base, base, allow_increase=False) is None
