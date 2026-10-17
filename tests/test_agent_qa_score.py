"""The agent benchmark's scorer and answer key.

Each scorer test pairs the wrong or declined reply with the right one for the
same question, so a scorer that called everything right (or wrong) fails
here. The key tests check theory.py against published values and against a
seeded simulation of the normal distribution, and check that questions.json
says what the scorer does.
"""

from __future__ import annotations

import ast
import json
import math
import random
import sys
from pathlib import Path

import pytest

BENCH = Path(__file__).resolve().parent.parent / "benchmarks" / "agent_qa"
sys.path.insert(0, str(BENCH))

import theory
from score import extract, number, score

GAIN = {"category": "response_1cycle", "truth": {"value": 1.10, "half_width": 0.11}}
VAR = {"category": "bulmer_variance", "truth": {"value": 0.79, "half_width": 0.05}}
DIFF = {"category": "paired_difference", "truth": {"value": -0.20, "half_width": 0.02}}


def _v(q: dict, reply: str) -> str:
    return score(q, reply)["verdict"]


def test_the_last_answer_line_decides_and_markdown_around_it_is_ignored() -> None:
    reply = "ANSWER: 0.70\nChecking that again...\n**ANSWER:** `1.10`"
    assert extract(reply) == "1.10"
    assert _v(GAIN, reply) == "right"
    assert _v(GAIN, "**ANSWER:** 0.70") == "wrong"


def test_unknown_is_declined_and_a_reply_without_the_line_is_neither() -> None:
    assert _v(GAIN, "Not sure.\nANSWER: UNKNOWN") == "declined"
    assert _v(GAIN, "It is 1.10.") == "no_answer"
    assert _v(GAIN, "It is 1.10.\nANSWER: 1.10") == "right"


def test_the_band_is_inclusive_on_both_sides_and_nothing_beyond_it_is_right() -> None:
    assert _v(GAIN, "ANSWER: 1.21") == "right"  # value + half_width
    assert _v(GAIN, "ANSWER: 0.99") == "right"  # value - half_width
    assert _v(GAIN, "ANSWER: 1.2101") == "wrong"
    assert _v(GAIN, "ANSWER: 0.9899") == "wrong"
    assert _v(GAIN, "ANSWER: 1.1") == "right"


def test_a_percent_is_read_as_a_fraction_of_one() -> None:
    """A variance 'as a fraction of the founder variance' may be written 79%."""
    assert _v(VAR, "ANSWER: 79%") == "right"
    assert _v(VAR, "ANSWER: 79 % of the founder variance") == "right"
    assert _v(VAR, "ANSWER: 79") == "wrong"


def test_a_unicode_minus_is_a_minus_and_the_sign_counts() -> None:
    assert _v(DIFF, "ANSWER: −0.20") == "right"
    assert _v(DIFF, "ANSWER: -0.2 SD") == "right"
    assert _v(DIFF, "ANSWER: 0.20") == "wrong"


def test_the_first_number_on_the_line_is_the_answer_and_words_alone_are_wrong() -> None:
    assert number("≈1.10 (i = 1.74 times h = 0.632)") == pytest.approx(1.10)
    assert number("1,234.5") == pytest.approx(1234.5)
    assert number("2.5e-1") == pytest.approx(0.25)
    assert _v(GAIN, "ANSWER: about one SD") == "wrong"
    assert _v(GAIN, "ANSWER: about 1.1 SD") == "right"


def test_every_answer_records_how_far_it_missed() -> None:
    assert score(GAIN, "ANSWER: 0.88")["rel_error"] == pytest.approx(-0.2)
    assert score(GAIN, "ANSWER: 1.10")["rel_error"] == pytest.approx(0.0)
    assert score(GAIN, "ANSWER: UNKNOWN")["rel_error"] is None


def test_infinite_population_intensity_matches_the_tabulated_values() -> None:
    """The usual three-decimal table values: i = 1.755 at p = 0.10,
    2.063 at p = 0.05, 1.400 at p = 0.20."""
    assert theory.intensity_infinite(0.10) == pytest.approx(1.755, abs=5e-4)
    assert theory.intensity_infinite(0.05) == pytest.approx(2.063, abs=5e-4)
    assert theory.intensity_infinite(0.20) == pytest.approx(1.400, abs=5e-4)


def test_finite_sample_intensity_agrees_with_a_seeded_simulation_and_tends_to_the_limit() -> (
    None
):
    """The integral against draws from random.gauss (a generator theory.py does
    not use), and the finite value below the infinite one, closing on it."""
    rng = random.Random(1)
    n, N, reps = 2, 20, 40000
    sims = [
        sum(sorted(rng.gauss(0, 1) for _ in range(N))[-n:]) / n for _ in range(reps)
    ]
    mc = sum(sims) / reps
    se = math.sqrt(sum((s - mc) ** 2 for s in sims) / (reps - 1) / reps)
    assert abs(theory.intensity_finite(n, N) - mc) < 4 * se
    i_inf = theory.intensity_infinite(0.1)
    gaps = [i_inf - theory.intensity_finite(N // 10, N) for N in (20, 200, 2000)]
    assert all(g > 0 for g in gaps) and gaps == sorted(gaps, reverse=True)


def test_the_key_never_imports_the_server() -> None:
    """A bug in breedsim_mcp must not also be in the key."""
    for name in ("build_questions.py", "theory.py"):
        tree = ast.parse((BENCH / name).read_text())
        mods = {
            a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
        }
        mods |= {
            n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
        }
        assert not any(m.split(".")[0] == "breedsim_mcp" for m in mods), (name, mods)


def test_each_question_states_the_band_the_scorer_applies() -> None:
    key = json.loads((BENCH / "questions.json").read_text())
    assert 30 <= len(key["questions"]) <= 50
    for q in key["questions"]:
        t = q["truth"]
        assert f"±{t['tolerance_pct']}%" in q["question"], q["id"]
        assert t["half_width"] == pytest.approx(
            t["tolerance_pct"] / 100 * abs(t["value"]), rel=1e-3
        )
        assert q["key"]["calibration_ok"] is True, q["id"]
        inside = {"category": q["category"], "truth": t}
        edge = t["value"] + 0.999 * t["half_width"]
        assert score(inside, f"ANSWER: {edge}")["verdict"] == "right", q["id"]
        assert (
            score(inside, f"ANSWER: {t['value'] + 1.01 * t['half_width']}")["verdict"]
            == "wrong"
        )
