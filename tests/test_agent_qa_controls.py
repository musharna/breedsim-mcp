"""The agent benchmark's controls: the oracle, validity, the leak scan, the
paired test and the baselines.

Each test pairs the case that must pass with one that must not, in the same
test, so a check that always (or never) fires fails here.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

BENCH = Path(__file__).resolve().parent.parent / "benchmarks" / "agent_qa"
sys.path.insert(0, str(BENCH))

import analyse as A
import build_questions as B
from score import score

QUESTIONS = json.loads((BENCH / "questions.json").read_text())["questions"]


def test_the_frozen_key_as_replies_scores_all_right_and_a_shifted_key_all_wrong():
    """Oracle: the key's own values, written as replies, through the real
    scorer, are 40 of 40 right; the same values moved 1.5 band-widths are 0."""
    right = [
        score(q, f"Done.\nANSWER: {q['truth']['value']}")["verdict"] for q in QUESTIONS
    ]
    assert right == ["right"] * len(QUESTIONS)
    wrong = [
        score(q, f"ANSWER: {q['truth']['value'] + 1.5 * q['truth']['half_width']}")[
            "verdict"
        ]
        for q in QUESTIONS
    ]
    assert wrong == ["wrong"] * len(QUESTIONS)


def _row(arm: str, **kw) -> dict:
    tools = {"bare": [], "alt": ["Bash", "Read"], "mcp": ["mcp__breedsim__run_program"]}
    servers = {"mcp": [{"name": "breedsim", "status": "connected"}]}
    row = {
        "arm": arm,
        "category": "long_term_gain",
        "exit": 0,
        "tools_available": tools[arm],
        "mcp_servers": servers.get(arm, []),
        "tool_calls": [] if arm == "bare" else ["x"],
    }
    return row | kw


def test_one_validity_rule_for_every_arm():
    for arm in A.ARMS:
        assert A.invalid_reason(_row(arm), []) is None, arm
        assert A.invalid_reason(_row(arm, exit="timeout"), []) == "exit timeout"
        assert A.invalid_reason(_row(arm), ["questions\\.json"]).startswith("leak")
    assert (
        A.invalid_reason(_row("bare", tools_available=["Bash"]), [])
        == "tools offered to bare"
    )
    assert (
        A.invalid_reason(_row("alt", tools_available=["Read"]), [])
        == "Bash not offered"
    )
    assert (
        A.invalid_reason(
            _row("mcp", mcp_servers=[{"name": "breedsim", "status": "failed"}]), []
        )
        == "server not connected"
    )
    # A tool arm that answered a simulation question without a tool call is
    # invalid; on the control, which theory answers, it is not.
    for arm in ("alt", "mcp"):
        assert A.invalid_reason(_row(arm, tool_calls=[]), []) == "no tool call"
        assert (
            A.invalid_reason(_row(arm, tool_calls=[], category="control_response"), [])
            is None
        )


def test_the_leak_scan_reads_tool_inputs_and_outputs_but_not_the_prompt(tmp_path):
    def transcript(tool_input: str, tool_output: str) -> Path:
        p = tmp_path / f"t{len(list(tmp_path.iterdir()))}.jsonl"
        events = [
            {"type": "system", "subtype": "init", "cwd": "/home/x/agent_qa"},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "input": {"command": tool_input}}]}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "content": tool_output}]}},
        ]  # fmt: skip
        p.write_text("\n".join(json.dumps(e) for e in events))
        return p

    clean = A.transcript_text(transcript("Rscript /tmp/sim/s.R", "5.98 0.67"))
    assert A.leaks(clean) == []
    assert A.leaks(A.transcript_text(transcript("cat ~/x/questions.json", "{}")))
    assert A.leaks(A.transcript_text(transcript("ls", "simulate_key.R")))
    url = "https://github.com/musharna/breedsim-mcp/tree/master/benchmarks/agent_qa"
    assert A.leaks(A.transcript_text(transcript(f"curl {url}", "")))
    # The repo's front page is not the benchmark.
    assert A.leaks("https://github.com/musharna/breedsim-mcp") == []


def test_exact_mcnemar_matches_the_binomial_tail():
    assert A.mcnemar_exact(5, 0) == pytest.approx(2 / 32)
    assert A.mcnemar_exact(3, 3) == 1.0
    assert A.mcnemar_exact(0, 0) == 1.0
    assert A.mcnemar_exact(10, 1) == pytest.approx(2 * 12 / 2048)


def test_the_paired_comparison_counts_discordant_questions():
    rows = [
        {"arm": "mcp", "qid": "q1", "right": True},
        {"arm": "alt", "qid": "q1", "right": True},
        {"arm": "mcp", "qid": "q2", "right": True},
        {"arm": "alt", "qid": "q2", "right": False},
        {"arm": "mcp", "qid": "q3", "right": True},
        {"arm": "mcp", "qid": "q3", "right": False},  # not right in every run
        {"arm": "alt", "qid": "q3", "right": True},
    ]
    p = A.paired(rows, "mcp", "alt")
    assert (p["mcp only"], p["alt only"], p["both"], p["neither"]) == (1, 1, 1, 0)


def test_baselines_score_through_the_real_scorer_and_the_textbook_control_hits():
    base = A.baselines(QUESTIONS)
    by = {}
    for b in base:
        by.setdefault((b["setup"], b["category"]), []).append(b["right"])
    assert all(by[("breeder's equation, R = i(n,N) h", "control_response")])
    assert not any(by[("R = h2 S every cycle, finite i(n,N)", "long_term_gain")])
    # The constant that keeps prob_beats out of the headline is the one the
    # scorer finds inside most of its bands.
    shares = B.constant_inside_share(QUESTIONS)
    assert shares["prob_beats"] > 2 / 3 and "prob_beats" in B.NOT_HEADLINE
    assert sum(by[(B.CONSTANT, "prob_beats")]) == round(shares["prob_beats"] * 6)
    assert all(c in B.PLAN for c in B.NOT_HEADLINE)
