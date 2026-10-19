"""Controls and statistics for the agent benchmark, from results.jsonl alone.

No new Claude runs. For every stored run this decides whether it is VALID
(one rule for all arms), scans its transcript for leaks of the key, scores
the no-LLM baselines through the same scorer, and compares the arms per
question with exact tests and bootstrap intervals.

    uv run python benchmarks/agent_qa/analyse.py      # writes analysis.json + baselines.tsv (one row per baseline x question)

Validity, the same rule for every arm:
- the run exited 0 (a timeout or a harness error is recorded, not retried);
- the arm's intended tools were offered (init event): none for ``bare``,
  Bash for ``alt``, a connected breedsim server for ``mcp``;
- outside the control category, which theory answers, a tool arm made at
  least one tool call (the key needs a simulation the model cannot do in
  its head);
- the transcript's tool inputs and outputs never mention the key's files,
  the benchmark directory (locally or on GitHub), or the pilot and run
  directories (``LEAK_PATTERNS``).
Invalid rows stay in every count as "not right" (the headline) and are
also reported per arm and reason; ``valid-only`` accuracy is reported
beside it.
"""

from __future__ import annotations

import json
import math
import random
import re
import statistics
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_questions as B
from score import score

HERE = Path(__file__).resolve().parent
ARMS = ("bare", "alt", "mcp")
NO_TOOLS_NEEDED = {"control_response"}
LEAK_PATTERNS = [
    re.compile(p)
    for p in (
        r"questions\.json",
        r"simulate_key",
        r"build_questions",
        r"calibrate\.R",
        r"results\.jsonl",
        r"agent_qa",
        r"breedsim-agent-qa-key",
        r"bsbench",
        r"\.claude/worktrees",
        r"github(usercontent)?\.com/musharna/breedsim-mcp/.*benchmarks",
    )
]
BOOT = 10_000
ANY_SHORTCUT = "any named closed form (the best one per question)"


def transcript_text(path: Path) -> str:
    """Every tool input and every tool output in a stream-json transcript,
    joined; the prompt and the init event are left out (the prompt is ours).

    The run's own working directory (the init event's cwd) is replaced by
    ``<cwd>``: it is ours too, and on 2026-10-18 it sat under a directory
    named ``agent_qa``, so every alt run that wrote a script into it matched
    that pattern. Any other path under the same parent still counts."""
    parts: list[str] = []
    cwd = None
    if not path.exists():
        return ""
    for ln in path.read_text().splitlines():
        if not ln.startswith("{"):
            continue
        e = json.loads(ln)
        if e.get("type") == "system" and e.get("subtype") == "init":
            cwd = e.get("cwd")
        content = (e.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for b in content:
            if b.get("type") == "tool_use":
                parts.append(json.dumps(b.get("input")))
            elif b.get("type") == "tool_result":
                c = b.get("content")
                parts.append(c if isinstance(c, str) else json.dumps(c))
    text = "\n".join(parts)
    return text.replace(cwd, "<cwd>") if cwd else text


def leaks(text: str) -> list[str]:
    return [p.pattern for p in LEAK_PATTERNS if p.search(text)]


def invalid_reason(row: dict[str, Any], leak_hits: list[str]) -> str | None:
    """None if the row is valid, else why not (see the module docstring)."""
    if row["exit"] != 0:
        return f"exit {row['exit']}"
    tools = set(row.get("tools_available") or [])
    arm = row["arm"]
    if arm == "bare" and tools:
        return "tools offered to bare"
    if arm == "alt" and "Bash" not in tools:
        return "Bash not offered"
    if arm == "mcp":
        connected = any(
            s.get("name") == "breedsim" and s.get("status") == "connected"
            for s in row.get("mcp_servers") or []
        )
        if not connected or not any(t.startswith("mcp__breedsim__") for t in tools):
            return "server not connected"
    if (
        arm != "bare"
        and row["category"] not in NO_TOOLS_NEEDED
        and not row["tool_calls"]
    ):
        return "no tool call"
    if leak_hits:
        return "leak: " + ", ".join(leak_hits)
    return None


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar (sign) test on the discordant pairs."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)


def _ci(xs: list[float]) -> list[float]:
    xs = sorted(xs)
    return [xs[int(0.025 * len(xs))], xs[int(0.975 * len(xs)) - 1]]


def bootstrap(
    rows: list[dict[str, Any]], qids: list[str], seed: int = 1
) -> dict[str, Any]:
    """95% intervals over QUESTIONS (rows of a question move together): each
    arm's accuracy, median cost and median seconds, and the paired mcp - alt
    and mcp - bare accuracy differences."""
    by: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in rows:
        by.setdefault((r["arm"], r["qid"]), []).append(r)
    rng = random.Random(seed)
    draws: dict[str, list[float]] = {}
    for _ in range(BOOT):
        pick = [rng.choice(qids) for _ in qids]
        acc = {}
        for arm in ARMS:
            rs = [r for q in pick for r in by.get((arm, q), [])]
            if not rs:
                continue
            acc[arm] = sum(r["right"] for r in rs) / len(rs)
            draws.setdefault(f"{arm} accuracy", []).append(acc[arm])
            draws.setdefault(f"{arm} median cost", []).append(
                statistics.median(r["cost_usd"] or 0.0 for r in rs)
            )
            draws.setdefault(f"{arm} median seconds", []).append(
                statistics.median(r["seconds"] for r in rs)
            )
        for other in ("alt", "bare"):
            if "mcp" in acc and other in acc:
                draws.setdefault(f"mcp - {other} accuracy", []).append(
                    acc["mcp"] - acc[other]
                )
    return {k: _ci(v) for k, v in draws.items()}


def wilcoxon_exact(d: list[float]) -> float:
    """Two-sided exact Wilcoxon signed-rank p on paired differences. Zeros are
    dropped; tied |d| get their average rank. Ranks are doubled so they are
    integers, and the null distribution of the positive-rank sum is counted
    exactly over all 2^n sign patterns."""
    d = [x for x in d if x != 0]
    n = len(d)
    if n == 0:
        return 1.0
    order = sorted(range(n), key=lambda i: abs(d[i]))
    rank2 = [0] * n  # 2 x rank
    i = 0
    while i < n:
        j = i
        while j + 1 < n and abs(d[order[j + 1]]) == abs(d[order[i]]):
            j += 1
        for k in range(i, j + 1):
            rank2[order[k]] = i + j + 2  # 2 x the average of ranks i+1..j+1
        i = j + 1
    total = sum(rank2)
    counts = [0] * (total + 1)  # counts[w] = sign patterns with positive sum w
    counts[0] = 1
    for r in rank2:
        for w in range(total, r - 1, -1):
            counts[w] += counts[w - r]
    w_pos = sum(r for r, x in zip(rank2, d, strict=True) if x > 0)
    lower = sum(counts[: w_pos + 1]) / 2**n
    upper = sum(counts[w_pos:]) / 2**n
    return min(1.0, 2 * min(lower, upper))


def cost_paired(
    rows: list[dict[str, Any]], a: str = "mcp", b: str = "alt", seed: int = 1
) -> dict[str, Any]:
    """The 2026-10-18 primary endpoint: median cost per answer, a vs b.

    Every run counts (an invalid run still cost money). The test is the exact
    Wilcoxon signed-rank over questions on each question's mean cost per
    answer (a - b); the interval is the 95% bootstrap over questions of the
    difference of the two medians per answer."""
    cost: dict[tuple[str, str], list[float]] = {}
    for r in rows:
        cost.setdefault((r["arm"], r["qid"]), []).append(r["cost_usd"] or 0.0)
    qids = sorted(
        {q for arm, q in cost if arm == a} & {q for arm, q in cost if arm == b}
    )
    if not qids:
        return {}
    d = [statistics.fmean(cost[a, q]) - statistics.fmean(cost[b, q]) for q in qids]
    med = {
        arm: statistics.median(x for q in qids for x in cost[arm, q]) for arm in (a, b)
    }
    rng = random.Random(seed)
    draws = []
    for _ in range(BOOT):
        pick = [rng.choice(qids) for _ in qids]
        draws.append(
            statistics.median(x for q in pick for x in cost[a, q])
            - statistics.median(x for q in pick for x in cost[b, q])
        )
    return {
        "questions": len(qids),
        f"{a} median cost": med[a],
        f"{b} median cost": med[b],
        "difference": med[a] - med[b],
        "difference_ci95": _ci(draws),
        f"questions {a} cheaper": sum(x < 0 for x in d),
        f"questions {b} cheaper": sum(x > 0 for x in d),
        "p_exact_wilcoxon": wilcoxon_exact(d),
    }


def per_question(rows: list[dict[str, Any]], arm: str) -> dict[str, bool]:
    """qid -> right in every run of this arm."""
    out: dict[str, bool] = {}
    for r in rows:
        if r["arm"] == arm:
            out[r["qid"]] = out.get(r["qid"], True) and r["right"]
    return out


def paired(rows: list[dict[str, Any]], a: str, b: str) -> dict[str, Any]:
    pa, pb = per_question(rows, a), per_question(rows, b)
    common = sorted(set(pa) & set(pb))
    only_a = sum(pa[q] and not pb[q] for q in common)
    only_b = sum(pb[q] and not pa[q] for q in common)
    return {
        "questions": len(common),
        f"{a} only": only_a,
        f"{b} only": only_b,
        "both": sum(pa[q] and pb[q] for q in common),
        "neither": sum(not pa[q] and not pb[q] for q in common),
        "p_exact_mcnemar": mcnemar_exact(only_a, only_b),
    }


def baselines(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """No-LLM answers through the real scorer: the category-median constant,
    and every named shortcut on the questions it applies to."""
    const = B.category_constants(questions)
    out = []
    for q in questions:
        answers = {B.CONSTANT: const[q["category"]]}
        answers |= {
            n: x for n, (x, _) in B.shortcuts(q["category"], q["design"]).items()
        }
        hits = {
            name: score(q, f"ANSWER: {x:.6g}")["verdict"] == "right"
            for name, x in answers.items()
        }
        # An upper bound for answering from theory alone: the question counts
        # as right if ANY named closed form lands in its band.
        hits[ANY_SHORTCUT] = any(v for n, v in hits.items() if n != B.CONSTANT)
        out += [
            {"setup": n, "qid": q["id"], "category": q["category"], "right": v}
            for n, v in hits.items()
        ]
    return out


def summarise_arm(rows: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [r for r in rows if r["valid"]]
    reasons: dict[str, int] = {}
    for r in rows:
        if not r["valid"]:
            reasons[r["invalid_reason"]] = reasons.get(r["invalid_reason"], 0) + 1
    return {
        "runs": len(rows),
        "right": sum(r["right"] for r in rows),
        "valid": len(valid),
        "right_of_valid": sum(r["right"] for r in valid),
        "invalid": reasons,
        "median_cost": statistics.median(r["cost_usd"] or 0.0 for r in rows)
        if rows
        else None,
        "median_seconds": statistics.median(r["seconds"] for r in rows)
        if rows
        else None,
        "tool_calls_median": statistics.median(len(r["tool_calls"]) for r in rows)
        if rows
        else None,
    }


def analyse(
    results: list[dict[str, Any]], questions: list[dict[str, Any]], runs: Path
) -> dict[str, Any]:
    rows = []
    for r in results:
        hits = leaks(transcript_text(runs / r["arm"] / f"{r['qid']}-{r['rep']}.jsonl"))
        reason = invalid_reason(r, hits)
        rows.append(
            {
                **r,
                "leak_hits": hits,
                "valid": reason is None,
                "invalid_reason": reason,
                "right": reason is None and r["verdict"] == "right",
            }
        )
    headline = {q["id"] for q in questions if q["category"] not in B.NOT_HEADLINE}
    views = {
        "headline": [r for r in rows if r["qid"] in headline],
        "outside_headline": [r for r in rows if r["qid"] not in headline],
        "all": rows,
    }
    out: dict[str, Any] = {
        "not_headline_categories": B.NOT_HEADLINE,
        "leak_patterns": [p.pattern for p in LEAK_PATTERNS],
        "transcripts_scanned": sum(
            (runs / r["arm"] / f"{r['qid']}-{r['rep']}.jsonl").exists() for r in rows
        ),
        "leak_rows": sum(bool(r["leak_hits"]) for r in rows),
    }
    for view, rs in views.items():
        qids = sorted({r["qid"] for r in rs})
        out[view] = {
            "questions": len(qids),
            "arms": {a: summarise_arm([r for r in rs if r["arm"] == a]) for a in ARMS},
            "mcp_vs_alt": paired(rs, "mcp", "alt"),
            "mcp_vs_bare": paired(rs, "mcp", "bare"),
            "alt_vs_bare": paired(rs, "alt", "bare"),
            "cost_mcp_vs_alt": cost_paired(rs),
            "bootstrap_95": bootstrap(rs, qids) if qids else {},
        }
    base = baselines(questions)
    out["baselines"] = {}
    for view, keep in (("headline", headline), ("all", {q["id"] for q in questions})):
        tab: dict[str, list[int]] = {}
        for b in base:
            if b["qid"] in keep:
                t = tab.setdefault(b["setup"], [0, 0])
                t[0] += b["right"]
                t[1] += 1
        out["baselines"][view] = {
            k: {"right": v[0], "questions": v[1]} for k, v in tab.items()
        }
    out["baselines_by_category"] = {}
    for b in base:
        t = (
            out["baselines_by_category"]
            .setdefault(b["category"], {})
            .setdefault(b["setup"], [0, 0])
        )
        t[0] += b["right"]
        t[1] += 1
    out["rows"] = [
        {
            k: r[k]
            for k in (
                "arm",
                "qid",
                "rep",
                "verdict",
                "valid",
                "invalid_reason",
                "leak_hits",
            )
        }
        for r in rows
    ]
    return out


def main() -> None:
    questions = json.loads((HERE / "questions.json").read_text())["questions"]
    results_path = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "results.jsonl"
    runs = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / "runs"
    results = [json.loads(ln) for ln in results_path.read_text().splitlines() if ln]
    out = analyse(results, questions, runs)
    # Written next to the results they describe (plot.R reads them there).
    outdir = results_path.parent
    (outdir / "analysis.json").write_text(json.dumps(out, indent=1) + "\n")
    with (outdir / "baselines.tsv").open("w") as fh:
        fh.write("setup\tqid\tcategory\tright\n")
        for b in baselines(questions):
            fh.write(
                f"{b['setup']}\t{b['qid']}\t{b['category']}\t{str(b['right']).upper()}\n"
            )
    print(json.dumps({k: v for k, v in out.items() if k not in ("rows",)}, indent=1))


if __name__ == "__main__":
    main()
