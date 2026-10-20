"""Where each arm's tokens go, from the raw ``claude -p`` transcripts.

Per run: the tool count in the init event; the fixed context the first API
call reads (system prompt + tool definitions + question: the first call's
cache creation + cache read); the tokens each tool result added (the next
call's cache creation, which is the new content since the last call); the
number of API calls and of turns; and cache creation vs cache read vs output
from the result event's ``usage``. Usage is deduplicated by message id,
because Claude Code repeats one message's usage on each of its content blocks.

    uv run python benchmarks/agent_qa/diagnose.py RUNS_DIR [RUNS_DIR ...]
    uv run python benchmarks/agent_qa/diagnose.py --mechanism RESULTS.jsonl RUNS_DIR

--mechanism counts, from a results file's recorded tool and argument names,
how many valid server-arm runs used each tool or parameter added on
2026-10-18, and how many tool calls named a tool without its
``mcp__breedsim__`` prefix (Claude Code refuses those). A fix no run used was
not tested by the sweep. The other two changes (short instructions, rounded
floats) apply to every server run, so they need no count.
"""

from __future__ import annotations

import json
import statistics as st
import sys
from pathlib import Path


def one(path: Path) -> dict | None:
    ev = [json.loads(ln) for ln in path.read_text().splitlines() if ln.startswith("{")]
    init = next((e for e in ev if e.get("subtype") == "init"), None)
    res = next((e for e in ev if e.get("type") == "result"), None)
    if not init or not res:
        return None
    calls, seen = [], set()
    for e in ev:
        if e.get("type") != "assistant":
            continue
        m = e["message"]
        if m.get("id") in seen:
            continue
        seen.add(m.get("id"))
        calls.append(m["usage"])
    text_chars = 0
    for e in ev:
        if e.get("type") != "user":
            continue
        for b in e["message"].get("content") or []:
            if not isinstance(b, dict) or b.get("type") != "tool_result":
                continue
            c = b.get("content")
            if isinstance(c, str):
                text_chars += len(c)
                continue
            for x in c or []:
                if x.get("type") == "text":
                    text_chars += len(x.get("text", ""))
    u = res["usage"]
    first = calls[0] if calls else {}
    fixed = (
        first.get("cache_creation_input_tokens", 0)
        + first.get("cache_read_input_tokens", 0)
        + first.get("input_tokens", 0)
    )
    # Tokens added after each tool result = cache creation of every call but the
    # first (the first call's creation is the uncached part of the fixed prefix).
    added = sum(c.get("cache_creation_input_tokens", 0) for c in calls[1:])
    return {
        "tools": len(init.get("tools") or []),
        "fixed_ctx": fixed,
        # The fixed context's uncached part: what the first call writes to the
        # cache. Claude Code puts server instructions here, after the question.
        "first_create": first.get("cache_creation_input_tokens", 0),
        "first_read": first.get("cache_read_input_tokens", 0),
        "api_calls": len(calls),
        "turns": res.get("num_turns"),
        "tool_added": added,
        "result_text_chars": text_chars,
        "cache_create": u.get("cache_creation_input_tokens", 0),
        "cache_read": u.get("cache_read_input_tokens", 0),
        "input": u.get("input_tokens", 0),
        "output": u.get("output_tokens", 0),
        "cost": res.get("total_cost_usd") or 0.0,
    }


def tokens_by_tool(files: list[Path]) -> dict[str, list[int]]:
    """Tokens each tool result added: the cache creation of the API call that
    follows it (results of parallel calls are counted together, joined by
    '+'). It includes the model's own output between the two calls, which is
    small next to a 10-cycle table."""
    out: dict[str, list[int]] = {}
    for f in files:
        names: dict[str, str] = {}
        pending: list[str] = []
        seen: set[str] = set()
        for ln in f.read_text().splitlines():
            if not ln.startswith("{"):
                continue
            e = json.loads(ln)
            if e.get("type") == "assistant":
                m = e["message"]
                if m.get("id") not in seen:
                    seen.add(m.get("id"))
                    if pending:
                        key = "+".join(sorted(pending))
                        out.setdefault(key, []).append(
                            m["usage"].get("cache_creation_input_tokens", 0)
                        )
                        pending = []
                for b in m.get("content", []):
                    if b.get("type") == "tool_use":
                        names[b["id"]] = b["name"].removeprefix("mcp__breedsim__")
            elif e.get("type") == "user":
                for b in e["message"].get("content") or []:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        pending.append(names.get(b.get("tool_use_id"), "?"))
    return out


def summarize(name: str, rows: list[dict]) -> None:
    keys = [k for k in rows[0] if k != "tools"]
    print(
        f"\n{name}: {len(rows)} runs, tools in init {sorted({r['tools'] for r in rows})}"
    )
    print(f"  {'':18} {'median':>10} {'mean':>10} {'total':>12}")
    for k in keys:
        v = [r[k] for r in rows]
        fmt = "{:>10.4f}" if k == "cost" else "{:>10.0f}"
        print(f"  {k:18} " + fmt.format(st.median(v)) + " " + fmt.format(st.mean(v))
              + " " + ("{:>12.2f}" if k == "cost" else "{:>12.0f}").format(sum(v)))  # fmt: skip
    # Dollars per token type. These are the per-token prices that reproduce
    # every 10-17 run's total_cost_usd (all 360, largest residual 1.4e-17 USD):
    # input $4, 1 h cache write $8, cache read $0.20, output $20 per million.
    w = {"input": 4e-6, "cache_create": 8e-6, "cache_read": 0.2e-6, "output": 20e-6}
    tot = {k: sum(r[k] for r in rows) * w[k] for k in w}
    s = sum(tot.values())
    print(
        "  cost by token type: "
        + ", ".join(f"{k} ${v:.2f} ({100 * v / s:.0f}%)" for k, v in tot.items())
    )
    fixed_reads = sum(r["fixed_ctx"] * r["api_calls"] for r in rows)
    print(
        f"  fixed context re-read across calls: {100 * fixed_reads / max(1, sum(r['cache_read'] for r in rows)):.0f}% of cache reads"
    )


# (label, tool, argument name or None for any call of the tool)
MECHANISMS = (
    ("run_program, any", "run_program", None),
    ("run_program with final_only", "run_program", "final_only"),
    ("compare_programs, any", "compare_programs", None),
    ("compare_programs with final_only", "compare_programs", "final_only"),
)


def mechanism(results: Path, runs: Path) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import analyse as A

    rows = [json.loads(ln) for ln in results.read_text().splitlines()]
    mcp = [
        r
        for r in rows
        if r["arm"] == "mcp"
        and A.invalid_reason(
            r,
            A.leaks(A.transcript_text(runs / "mcp" / f"{r['qid']}-{r['rep']}.jsonl")),
        )
        is None
    ]
    print("label\truns_using\tof_valid_mcp_runs\tright_when_used\tcategories")
    for label, tool, arg in MECHANISMS:
        used = [
            r
            for r in mcp
            if any(
                name == f"mcp__breedsim__{tool}" and (arg is None or arg in args)
                for name, args in zip(r["tool_calls"], r["tool_arg_names"], strict=True)
            )
        ]
        cats = sorted({r["category"] for r in used})
        right = sum(r["verdict"] == "right" for r in used)
        print(f"{label}\t{len(used)}\t{len(mcp)}\t{right}\t{','.join(cats)}")
    bare = [
        (r["qid"], r["rep"], n)
        for r in rows
        if r["arm"] == "mcp"
        for n in r["tool_calls"]
        if not n.startswith("mcp__breedsim__")
    ]
    print(f"tool calls without the mcp__breedsim__ prefix: {len(bare)} {bare[:10]}")


def main() -> None:
    if sys.argv[1:2] == ["--mechanism"]:
        mechanism(Path(sys.argv[2]), Path(sys.argv[3]))
        return
    for d in map(Path, sys.argv[1:]):
        rows = [r for f in sorted(d.glob("*.jsonl")) if (r := one(f))]
        if rows:
            summarize(str(d), rows)
            by_tool = tokens_by_tool(sorted(d.glob("*.jsonl")))
            total = sum(sum(v) for v in by_tool.values())
            print("  tokens added per tool result (top 8):")
            for k, v in sorted(by_tool.items(), key=lambda kv: -sum(kv[1]))[:8]:
                print(
                    f"    {k:34} n {len(v):4} median {st.median(v):7.0f} "
                    f"total {sum(v):8} ({100 * sum(v) / total:.0f}%)"
                )


if __name__ == "__main__":
    main()
