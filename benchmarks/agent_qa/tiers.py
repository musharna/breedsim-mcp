"""The 2026-10-20 model-tier verdict, from each tier's analysis.json.

No new Claude runs. For each tier (Haiku 5.5, Sonnet 5.5) it reads the
primary endpoint that ``analyse.py`` already computes, headline questions
right in all 3 runs, mcp vs alt (exact McNemar, and the 95% bootstrap of the
mcp - alt accuracy), applies Holm across the tiers present, and the win rule
in PREREG_2026-10-20_model-tiers.md. It also gives the mechanism readout
(server tool calls per run) and the secondary, non-concurrent substitute
comparison (a tier's server arm against the 10-18 Opus alt rows).

    python3 benchmarks/agent_qa/tiers.py \\
        haiku=benchmarks/agent_qa/tiers_2026-10-20/haiku \\
        sonnet=benchmarks/agent_qa/tiers_2026-10-20/sonnet \\
        --opus benchmarks/agent_qa/rerun_2026-10-18
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analyse as A
import build_questions as B

HERE = Path(__file__).resolve().parent
ALPHA = 0.05
SERVER_PREFIX = "mcp__breedsim__"


def holm(ps: dict[str, float]) -> dict[str, float]:
    """Holm-adjusted p-values (step-down, monotone, capped at 1)."""
    order = sorted(ps, key=lambda k: ps[k])
    out: dict[str, float] = {}
    run = 0.0
    for rank, k in enumerate(order):
        run = max(run, min(1.0, (len(ps) - rank) * ps[k]))
        out[k] = run
    return out


def direction(t: dict[str, Any]) -> str:
    """'lift', 'loss' or 'none' for one tier, from its Holm-adjusted p."""
    if t["p_holm"] >= ALPHA:
        return "none"
    return "lift" if t["mcp only"] > t["alt only"] else "loss"


def verdict(tiers: dict[str, dict[str, Any]]) -> str:
    """WIN: a significant lift at >= 1 tier and no significant loss at any.
    LOSS: a significant loss at >= 1 tier and no lift. MIXED: both. TIE: neither."""
    dirs = {direction(t) for t in tiers.values()}
    if "lift" in dirs:
        return "MIXED" if "loss" in dirs else "WIN"
    return "LOSS" if "loss" in dirs else "TIE"


def right_rows(analysis: dict[str, Any], headline: set[str]) -> list[dict[str, Any]]:
    """The headline rows of an analysis.json, with ``right`` as analyse.py
    defines it (valid and scored right)."""
    return [
        {**r, "right": r["valid"] and r["verdict"] == "right"}
        for r in analysis["rows"]
        if r["qid"] in headline
    ]


def mechanism(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Server tool calls per mcp run, and the runs that made none."""
    mcp = [r for r in results if r["arm"] == "mcp"]
    calls = [sum(t.startswith(SERVER_PREFIX) for t in r["tool_calls"]) for r in mcp]
    used: dict[str, int] = {}
    for r in mcp:
        for t in set(r["tool_calls"]):
            used[t] = used.get(t, 0) + 1
    return {
        "mcp_runs": len(mcp),
        "server_calls_median": statistics.median(calls) if calls else None,
        "server_calls_mean": round(statistics.fmean(calls), 2) if calls else None,
        "runs_with_0_server_calls": sum(c == 0 for c in calls),
        "runs_with_0_server_calls_outside_control": sum(
            c == 0
            for c, r in zip(calls, mcp, strict=True)
            if r["category"] not in A.NO_TOOLS_NEEDED
        ),
        "bare_name_calls": sum(
            not t.startswith("mcp__") for r in mcp for t in r["tool_calls"]
        ),
        "runs_using_tool": dict(sorted(used.items())),
        "runs_using_final_only": sum(
            any("final_only" in names for names in r["tool_arg_names"]) for r in mcp
        ),
        "models_served": sorted({str(r.get("model")) for r in results}),
    }


def tier(path: Path, headline: set[str]) -> dict[str, Any]:
    analysis = json.loads((path / "analysis.json").read_text())
    results = [
        json.loads(ln) for ln in (path / "results.jsonl").read_text().splitlines() if ln
    ]
    h = analysis["headline"]
    pair = h["mcp_vs_alt"]
    arms = h["arms"]
    return {
        "questions": pair["questions"],
        "right_in_all_3": {
            arm: sum(A.per_question(right_rows(analysis, headline), arm).values())
            for arm in A.ARMS
        },
        "mcp only": pair["mcp only"],
        "alt only": pair["alt only"],
        "p_exact_mcnemar": pair["p_exact_mcnemar"],
        "mcp_minus_alt_accuracy_ci95": h["bootstrap_95"].get("mcp - alt accuracy"),
        "right_of_runs": {a: [arms[a]["right"], arms[a]["runs"]] for a in A.ARMS},
        "invalid": {a: arms[a]["invalid"] for a in A.ARMS},
        "median_cost": {a: arms[a]["median_cost"] for a in A.ARMS},
        "median_seconds": {a: arms[a]["median_seconds"] for a in A.ARMS},
        "total_cost": round(sum(r["cost_usd"] or 0.0 for r in results), 4),
        "cost_mcp_vs_alt": h["cost_mcp_vs_alt"],
        "mcp_vs_bare": h["mcp_vs_bare"],
        "alt_vs_bare": h["alt_vs_bare"],
        "mechanism": mechanism(results),
        "_rows": right_rows(analysis, headline),
    }


def substitute(
    rows: list[dict[str, Any]], opus: list[dict[str, Any]]
) -> dict[str, Any]:
    """A tier's server arm against Opus's own scripts on 10-18: secondary and
    NOT concurrent (different day, different sweep)."""
    joined = [r for r in rows if r["arm"] == "mcp"] + [
        {**r, "arm": "alt"} for r in opus if r["arm"] == "alt"
    ]
    return {"non_concurrent": True, **A.paired(joined, "mcp", "alt")}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "tiers", nargs="+", help="name=dir with analysis.json + results.jsonl"
    )
    ap.add_argument(
        "--opus", type=Path, help="the 10-18 Opus re-run dir (analysis.json)"
    )
    ap.add_argument("--out", type=Path, help="write the verdict JSON here")
    a = ap.parse_args()
    questions = json.loads((HERE / "questions.json").read_text())["questions"]
    headline = {q["id"] for q in questions if q["category"] not in B.NOT_HEADLINE}
    tiers = {}
    for spec in a.tiers:
        name, _, d = spec.partition("=")
        tiers[name] = tier(Path(d), headline)
    adj = holm({k: t["p_exact_mcnemar"] for k, t in tiers.items()})
    for k, t in tiers.items():
        t["p_holm"] = adj[k]
        t["direction"] = direction(t)
    opus = None
    if a.opus:
        opus = right_rows(json.loads((a.opus / "analysis.json").read_text()), headline)
    out: dict[str, Any] = {
        "tiers_present": sorted(tiers),
        "holm_over": len(tiers),
        "verdict": verdict(tiers) if len(tiers) == 2 else "PENDING (one tier)",
        "tiers": {},
    }
    for k, t in tiers.items():
        rows = t.pop("_rows")
        if opus is not None:
            t["substitute_mcp_vs_opus_alt_1018"] = substitute(rows, opus)
        out["tiers"][k] = t
    text = json.dumps(out, indent=1) + "\n"
    if a.out:
        a.out.write_text(text)
    print(text)


if __name__ == "__main__":
    main()
