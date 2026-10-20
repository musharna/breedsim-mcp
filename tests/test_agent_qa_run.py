"""The agent harness's model plumbing (--model) and its seven-day usage stop.

Each test pairs the case that must pass with one that must not.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

BENCH = Path(__file__).resolve().parent.parent / "benchmarks" / "agent_qa"
sys.path.insert(0, str(BENCH))

import run as R

HAIKU = "claude-haiku-5-5"


@pytest.fixture(autouse=True)
def _restore_globals(monkeypatch):
    monkeypatch.setattr(R, "MODEL", R.DEFAULT_MODEL)
    monkeypatch.setattr(R, "RUNS", R.RUNS)


def test_another_models_transcripts_go_beside_the_default_models_not_over_them(
    tmp_path,
):
    runs = tmp_path / "runs"
    R.set_model(R.DEFAULT_MODEL, runs)
    assert (R.MODEL, R.RUNS) == (R.DEFAULT_MODEL, runs)
    R.set_model(HAIKU, runs)
    assert R.MODEL == HAIKU
    assert R.RUNS == tmp_path / f"runs-{HAIKU}"
    assert R.RUNS != runs


def _write(path: Path, rows: list[dict]) -> Path:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return path


def test_a_results_file_from_another_model_is_refused_and_its_own_is_resumed(
    tmp_path,
):
    # Rows from before --model carry only the served model.
    opus = _write(tmp_path / "opus.jsonl", [{"arm": "alt", "model": R.DEFAULT_MODEL}])
    haiku = _write(
        tmp_path / "haiku.jsonl",
        # served under a dated id: what was asked for decides, not what came back
        [{"arm": "alt", "model": f"{HAIKU}-20261001", "model_requested": HAIKU}],
    )
    R.set_model(R.DEFAULT_MODEL, tmp_path / "runs")
    R.check_results_model(opus)  # the default model resumes its own file
    R.check_results_model(tmp_path / "absent.jsonl")
    with pytest.raises(SystemExit, match=r"holds rows run on \['claude-haiku-5-5'\]"):
        R.check_results_model(haiku)
    R.set_model(HAIKU, tmp_path / "runs")
    R.check_results_model(haiku)
    with pytest.raises(SystemExit, match=r"holds rows run on \['claude-opus-5-5'\]"):
        R.check_results_model(opus)


def test_versions_json_gains_the_models_the_init_events_reported(tmp_path):
    results = _write(
        tmp_path / "results.jsonl",
        [{"model": HAIKU}, {"model": HAIKU}, {"model": None}],
    )
    (tmp_path / "versions.json").write_text(json.dumps({"model": HAIKU}))
    R.record_models_served(results)
    v = json.loads((tmp_path / "versions.json").read_text())
    assert v == {"model": HAIKU, "models_served": {HAIKU: 2, "None": 1}}


def test_the_sweep_stops_at_the_seven_day_gate_and_not_below_it():
    assert R.seven_day_exhausted({"seven_day": 0.90})
    assert R.seven_day_exhausted({"seven_day": 0.93})
    assert not R.seven_day_exhausted({"seven_day": 0.89})
    assert not R.seven_day_exhausted({"seven_day": None})
