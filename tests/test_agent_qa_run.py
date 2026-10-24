"""The agent harness's model plumbing (--model) and its seven-day usage stop.

Each test pairs the case that must pass with one that must not.
"""

from __future__ import annotations

import json
import sys
import time
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


def test_a_row_that_failed_before_its_init_event_neither_blocks_nor_hides_a_mismatch(
    tmp_path,
):
    # A timeout before the init event leaves "model": None and, before
    # --model, no model_requested: it says nothing about the file's model.
    failed = {"arm": "alt", "model": None}
    legacy = _write(tmp_path / "legacy.jsonl", [failed, {"model": R.DEFAULT_MODEL}])
    mixed = _write(tmp_path / "mixed.jsonl", [failed, {"model": R.DEFAULT_MODEL}])
    R.set_model(R.DEFAULT_MODEL, tmp_path / "runs")
    R.check_results_model(legacy)
    R.set_model(HAIKU, tmp_path / "runs")
    with pytest.raises(SystemExit, match=r"holds rows run on \['claude-opus-5-5'\]"):
        R.check_results_model(mixed)


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


def _sweep(monkeypatch, tmp_path, seven_day_at: int | None) -> tuple[int, list]:
    """main() over 2 questions x 3 reps on the bare arm, with run_one faked:
    the run numbered ``seven_day_at`` reports seven_day 0.95."""
    calls = []
    results = tmp_path / "results.jsonl"

    def written() -> int:
        return len(results.read_text().splitlines()) if results.exists() else 0

    def fake_run_one(arm, q, rep):
        calls.append((q["id"], rep))
        # Real runs take seconds; a fake one returns at once and the worker
        # would finish the queue before the main thread reads a result. So
        # each run starts only once the one before it is written.
        for _ in range(1000):
            if written() >= len(calls) - 1:
                break
            time.sleep(0.01)
        else:
            raise AssertionError("the previous run was never written")
        hot = seven_day_at is not None and len(calls) >= seven_day_at
        return {"arm": arm, "qid": q["id"], "rep": rep, "verdict": "right",
                "exit": 0, "seconds": 1.0, "tool_calls": [], "cost_usd": 0.0,
                "model": HAIKU, "model_requested": HAIKU,
                "rate_limit": {"seven_day": 0.95 if hot else 0.5}}  # fmt: skip

    monkeypatch.setattr(R, "run_one", fake_run_one)
    monkeypatch.setattr(R, "preflight", lambda key: None)
    monkeypatch.setattr(
        sys, "argv",
        ["run.py", "--model", HAIKU, "--arms", "bare", "--reps", "3", "--only", "q01,q02",
         "--results", str(results), "--runs", str(tmp_path / "runs")],
    )  # fmt: skip
    with pytest.raises(SystemExit) as exc:
        R.main()
    rows = [json.loads(ln) for ln in results.read_text().splitlines()]
    return exc.value.code, rows


def test_the_seven_day_stop_keeps_every_finished_run_and_starts_no_more(
    monkeypatch, tmp_path
):
    code, rows = _sweep(monkeypatch, tmp_path, seven_day_at=None)
    assert (code, len(rows)) == (0, 6)
    (tmp_path / "results.jsonl").unlink()
    code, rows = _sweep(monkeypatch, tmp_path, seven_day_at=2)
    assert code == 3
    # The run that saw it is written, then the run in flight. A fake run ends
    # the moment its predecessor is written, so one more can start in the
    # microseconds before the cancel; a real run takes seconds. Without the
    # stop all 6 run.
    assert 2 <= len(rows) <= 4
    assert [(r["qid"], r["rep"]) for r in rows] == [
        ("q01", 1), ("q02", 1), ("q01", 2), ("q02", 2)
    ][: len(rows)]  # fmt: skip


def test_the_spend_gate_refuses_a_run_and_the_sweep_stops_keeping_finished_rows(
    monkeypatch, tmp_path
):
    """API-billed sweeps (2026-10-23): run_one asks BENCH_SPEND_GATE first and
    raises SpendStop when it exits non-zero; main() then starts no more runs,
    keeps the rows written, and exits 3. Under the cap or unset, no stop."""
    gate_py = tmp_path / "gate.py"
    gate_py.write_text("import os, sys\nprint('cap reached', file=sys.stderr)\nsys.exit(int(os.environ['GATE_RC']))\n")
    monkeypatch.setenv("BENCH_SPEND_GATE", str(gate_py))
    monkeypatch.setenv("GATE_RC", "0")
    assert R.spend_stop() is None  # under the cap
    monkeypatch.setenv("GATE_RC", "3")
    with pytest.raises(R.SpendStop, match="cap reached"):
        R.run_one("bare", {"id": "q01"}, 1)  # refused before it touches anything
    monkeypatch.delenv("BENCH_SPEND_GATE")
    assert R.spend_stop() is None  # unset: subscription sweeps unchanged

    real_run_one = R.run_one
    calls = []

    def fake_run_one(arm, q, rep):
        calls.append((q["id"], rep))
        if len(calls) >= 3:
            monkeypatch.setenv("BENCH_SPEND_GATE", str(gate_py))
            return real_run_one(arm, q, rep)  # the gate refuses this one
        return {"arm": arm, "qid": q["id"], "rep": rep, "verdict": "right",
                "exit": 0, "seconds": 1.0, "tool_calls": [], "cost_usd": 0.0,
                "model": HAIKU, "model_requested": HAIKU, "rate_limit": {"seven_day": 0.5}}  # fmt: skip

    results = tmp_path / "results.jsonl"
    monkeypatch.setattr(R, "run_one", fake_run_one)
    monkeypatch.setattr(R, "preflight", lambda key: None)
    monkeypatch.setattr(
        sys, "argv",
        ["run.py", "--model", HAIKU, "--arms", "bare", "--reps", "3", "--only", "q01,q02",
         "--results", str(results), "--runs", str(tmp_path / "runs")],
    )  # fmt: skip
    with pytest.raises(SystemExit) as exc:
        R.main()
    rows = [json.loads(ln) for ln in results.read_text().splitlines()]
    assert exc.value.code == 3
    assert [(r["qid"], r["rep"]) for r in rows] == [("q01", 1), ("q02", 1)]
