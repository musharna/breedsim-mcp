"""The model-tier verdict (tiers.py): Holm across tiers, the win rule, the
mechanism readout and the non-concurrent substitute comparison.

Each test pairs the case that must pass with one that must not.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BENCH = Path(__file__).resolve().parent.parent / "benchmarks" / "agent_qa"
sys.path.insert(0, str(BENCH))

import tiers as T


def test_holm_doubles_the_smaller_p_and_keeps_the_order():
    adj = T.holm({"haiku": 0.02, "sonnet": 0.04})
    assert adj == pytest.approx({"haiku": 0.04, "sonnet": 0.04})
    adj = T.holm({"haiku": 0.03, "sonnet": 0.6})
    assert adj == pytest.approx({"haiku": 0.06, "sonnet": 0.6})
    # the larger p never ends below the smaller one's adjusted value
    adj = T.holm({"haiku": 0.03, "sonnet": 0.04})
    assert adj == pytest.approx({"haiku": 0.06, "sonnet": 0.06})


def _t(p_holm: float, mcp_only: int, alt_only: int) -> dict:
    return {"p_holm": p_holm, "mcp only": mcp_only, "alt only": alt_only}


def test_the_win_rule_needs_a_lift_and_no_loss():
    lift, loss, flat = _t(0.01, 6, 0), _t(0.01, 0, 6), _t(0.5, 2, 1)
    assert T.verdict({"haiku": lift, "sonnet": flat}) == "WIN"
    assert T.verdict({"haiku": lift, "sonnet": loss}) == "MIXED"
    assert T.verdict({"haiku": flat, "sonnet": loss}) == "LOSS"
    assert T.verdict({"haiku": flat, "sonnet": flat}) == "TIE"
    # significant by the raw p only: Holm has already pushed it over 0.05
    assert T.verdict({"haiku": _t(0.05, 6, 0), "sonnet": flat}) == "TIE"


def test_mechanism_counts_server_calls_and_runs_that_made_none():
    rows = [
        {"arm": "mcp", "category": "long_term_gain", "model": "h",
         "tool_calls": ["mcp__breedsim__found_population", "mcp__breedsim__run_program"],
         "tool_arg_names": [["n"], ["final_only", "cycles"]]},
        {"arm": "mcp", "category": "long_term_gain", "model": "h",
         "tool_calls": [], "tool_arg_names": []},
        {"arm": "mcp", "category": "control_response", "model": "h",
         "tool_calls": ["run_program"], "tool_arg_names": [["cycles"]]},
        {"arm": "alt", "category": "long_term_gain", "model": "h",
         "tool_calls": ["Bash"], "tool_arg_names": [["command"]]},
    ]  # fmt: skip
    m = T.mechanism(rows)
    assert m["mcp_runs"] == 3
    assert m["runs_with_0_server_calls"] == 2  # the empty run and the bare-name one
    assert m["runs_with_0_server_calls_outside_control"] == 1
    assert m["bare_name_calls"] == 1
    assert m["runs_using_final_only"] == 1
    assert m["server_calls_median"] == 0


def test_the_substitute_pairs_the_tiers_server_with_opus_alt_not_its_own_alt():
    rows = [
        {"arm": "mcp", "qid": "q1", "right": True},
        {"arm": "mcp", "qid": "q2", "right": True},
        {"arm": "alt", "qid": "q1", "right": False},  # the tier's own alt: ignored
        {"arm": "alt", "qid": "q2", "right": False},
    ]
    opus = [
        {"arm": "alt", "qid": "q1", "right": True},
        {"arm": "alt", "qid": "q2", "right": False},
        {"arm": "mcp", "qid": "q1", "right": False},  # Opus's server: ignored
    ]
    s = T.substitute(rows, opus)
    assert s["non_concurrent"] is True
    assert (s["mcp only"], s["alt only"], s["both"]) == (1, 0, 1)
