"""The benchmark key simulates what the server simulates, seed for seed.

The key (benchmarks/agent_qa/simulate_key.R) drives AlphaSimR directly and
never imports breedsim_mcp. Its questions pin the founders with a seed, so a
server user who founds with that seed and runs the stated programme is
estimating the same expectation the key holds. This test checks that premise
on the real engine: on the same founder seed and the same replicate seeds, the
server's per-cycle means equal the key script's, for phenotypic selection,
genomic selection (gain and out-of-sample accuracy) and a paired comparison.
A mismatch in call order, seeding or the accuracy definition fails here.
"""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import subprocess
import tempfile
from pathlib import Path

import pytest

from breedsim_mcp.server import build_server

KEY_R = (
    Path(__file__).resolve().parent.parent
    / "benchmarks"
    / "agent_qa"
    / "simulate_key.R"
)
FOUND = {"generator": "quickHaplo", "seed": 4242, "n_ind": 30, "n_chr": 2, "seg_sites": 30,
         "n_qtl_per_chr": 4, "h2": 0.4, "n_snp_per_chr": 6}  # fmt: skip
BASE_SEED, REPS, CYCLES = 900, 5, 2


def _key(arms: list[dict]) -> dict:
    design = {
        "id": "t", "founder_seed": FOUND["seed"], "n_ind": FOUND["n_ind"],
        "n_chr": FOUND["n_chr"], "seg_sites": FOUND["seg_sites"],
        "n_qtl_per_chr": FOUND["n_qtl_per_chr"], "n_snp_per_chr": FOUND["n_snp_per_chr"],
        "h2": FOUND["h2"], "cycles": CYCLES, "replicates": REPS, "seed0": BASE_SEED,
        "arms": arms,
    }  # fmt: skip
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp) / "d.json", Path(tmp) / "o.json"
        src.write_text(json.dumps([design]))
        subprocess.run(
            ["Rscript", str(KEY_R), str(src), str(dst)],
            check=True, timeout=600, env=dict(os.environ, OMP_NUM_THREADS="1"),
        )  # fmt: skip
        return json.loads(dst.read_text())[0]["arms"]


def _mean(rows: list[list[float]], cycle: int) -> float:
    return statistics.fmean(r[cycle] for r in rows)


def _call(srv, name: str, args: dict) -> dict:
    res = asyncio.run(srv.call_tool(name, args))
    assert not res.is_error, res.content
    return res.structured_content


@pytest.fixture(scope="module")
def server_runs():
    srv = build_server()
    sid = _call(srv, "found_population", FOUND)["session_id"]
    common = {
        "session_id": sid,
        "cycles": CYCLES,
        "replicates": REPS,
        "base_seed": BASE_SEED,
    }
    pheno = _call(srv, "run_program", {**common, "n_select": 6})
    genomic = _call(
        srv, "run_program", {**common, "n_select": 6, "selection_method": "genomic"}
    )
    compare = _call(
        srv, "compare_programs", {**common, "a_n_select": 3, "b_n_select": 15}
    )
    return pheno, genomic, compare


def test_phenotypic_gain_and_variance_match_the_key_seed_for_seed(server_runs):
    pheno = server_runs[0]
    key = _key([{"label": "a", "method": "pheno", "n_select": 6, "n_cross": 30}])["a"]
    for c in range(CYCLES):
        assert pheno["cycles"][c]["genetic_gain"]["mean"] == pytest.approx(
            _mean(key["gain"], c), abs=1e-9
        )
        assert pheno["cycles"][c]["genetic_variance"]["mean"] == pytest.approx(
            _mean(key["var"], c), abs=1e-9
        )
    # Positive control for the comparison itself: a different selection
    # intensity must NOT match, or the equality above could be vacuous.
    other = _key([{"label": "a", "method": "pheno", "n_select": 12, "n_cross": 30}])[
        "a"
    ]
    assert (
        abs(_mean(other["gain"], 1) - pheno["cycles"][1]["genetic_gain"]["mean"]) > 1e-3
    )


def test_genomic_gain_and_out_of_sample_accuracy_match_the_key(server_runs):
    genomic = server_runs[1]
    key = _key([{"label": "a", "method": "genomic", "n_select": 6, "n_cross": 30}])["a"]
    for c in range(CYCLES):
        cyc = genomic["cycles"][c]
        assert cyc["genetic_gain"]["mean"] == pytest.approx(
            _mean(key["gain"], c), abs=1e-9
        )
        assert cyc["prediction_accuracy"]["mean"] == pytest.approx(
            _mean(key["acc"], c), abs=1e-9
        )


def test_a_paired_comparison_matches_the_keys_paired_difference(server_runs):
    compare = server_runs[2]
    key = _key(
        [
            {"label": "a", "method": "pheno", "n_select": 3, "n_cross": 30},
            {"label": "b", "method": "pheno", "n_select": 15, "n_cross": 30},
        ]
    )
    diffs = [
        a[-1] - b[-1] for a, b in zip(key["a"]["gain"], key["b"]["gain"], strict=True)
    ]
    assert compare["cycles"][-1]["difference"]["mean"] == pytest.approx(
        statistics.fmean(diffs), abs=1e-9
    )


def test_the_installed_alphasimr_is_the_version_the_key_was_built_on():
    """The key is a simulation, so it holds only for its AlphaSimR version;
    CI pins that version (scripts/install-r-deps.R) and this checks the pin."""
    built = json.loads((KEY_R.parent / "questions.json").read_text())["alphasimr"]
    pinned = next(
        ln.split('"')[1]
        for ln in (KEY_R.parents[2] / "scripts" / "install-r-deps.R")
        .read_text()
        .splitlines()
        if ln.startswith("ALPHASIMR <-")
    )
    have = subprocess.run(
        ["Rscript", "-e", 'cat(as.character(packageVersion("AlphaSimR")))'],
        check=True, capture_output=True, text=True, timeout=120,
    ).stdout.strip()  # fmt: skip
    assert built == pinned == have, (built, pinned, have)
