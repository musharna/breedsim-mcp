"""Ask every question to Claude Code under each arm, and score the replies.

Arms (same model, same prompt, isolated: no user settings, hooks or other MCP
servers, an empty working directory per run):

- ``bare``: no tools at all.
- ``alt``:  what a user has without this server: Bash (with R + AlphaSimR and
  Python on PATH), Read, WebSearch and WebFetch. Claude can write its own
  AlphaSimR or theory code.
- ``mcp``:  breedsim-mcp (pinned PyPI release, via uvx) only.

Each finished run is appended to ``results.jsonl`` with its score; a rerun
skips (arm, question, rep) triples already there, so an interrupted sweep
resumes. Raw stream-json transcripts go to ``<runs>/<arm>/<qid>-<rep>.jsonl``
(``--runs``; keep it, and ``--results``, outside the repository for new
sweeps, e.g. under ~/breedsim-mcp-artifacts/, so a Bash-armed agent cannot
come across earlier transcripts by listing the tree).

    uv run python benchmarks/agent_qa/run.py --reps 3 --workers 1
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from score import score

HERE = Path(__file__).resolve().parent
MODEL = "claude-opus-5-5"
SERVER = "breedsim-mcp==0.5.1"  # latest on PyPI, checked 2026-10-16
RUN_TIMEOUT_S = 1800
R_LIBS_USER = os.environ.get("R_LIBS_USER") or str(Path.home() / "R" / "library")
# Every arm gets this in place of Claude Code's own system prompt, which
# describes tools even when --tools "" removes them all (in plant-genomics-mcp's
# pilot the no-tools arm wrote fake tool calls as text instead of answering).
SYSTEM = "You are a helpful assistant. Answer the user's question."
PROMPT = (
    "{question}\n\nGive the answer as {answer_format}. Keep your reply short, and end it "
    "with one line of the form\nANSWER: <answer>\nIf you cannot determine the answer, end "
    "with\nANSWER: UNKNOWN"
)
ALT_TOOLS = "Bash,Read,WebSearch,WebFetch"


def arm_flags(arm: str, tmp: Path) -> list[str]:
    empty = tmp / "no-mcp.json"
    empty.write_text('{"mcpServers": {}}')
    if arm == "bare":
        return ["--tools", "", "--strict-mcp-config", "--mcp-config", str(empty)]
    if arm == "alt":
        return [
            "--tools", ALT_TOOLS, "--allowedTools", ALT_TOOLS,
            "--strict-mcp-config", "--mcp-config", str(empty),
        ]  # fmt: skip
    if arm == "mcp":
        cfg = tmp / "mcp.json"
        server = {
            "command": "uvx",
            # A uv-managed CPython, as pyproject's [tool.uv] asks for: a conda
            # interpreter's libstdc++ breaks rpy2's dlopen of libR.so.
            "args": ["--python-preference", "only-managed", SERVER],
            "env": {"R_LIBS_USER": R_LIBS_USER, "OMP_NUM_THREADS": "1"},
        }
        cfg.write_text(json.dumps({"mcpServers": {"breedsim": server}}))
        return [
            "--tools", "", "--allowedTools", "mcp__breedsim",
            "--strict-mcp-config", "--mcp-config", str(cfg),
        ]  # fmt: skip
    raise ValueError(arm)


def run_env(tmp: Path) -> dict[str, str]:
    env = dict(os.environ, R_LIBS_USER=R_LIBS_USER, OMP_NUM_THREADS="1")
    # A private TMPDIR per run, so tempfile-using code in one run cannot see
    # another's files. (A script that writes a literal /tmp path still can;
    # the README says so.)
    (tmp / "tmp").mkdir(exist_ok=True)
    env["TMPDIR"] = str(tmp / "tmp")
    # A 100-replicate run_program is tens of seconds; Claude Code's default
    # MCP tool timeout would cut it off and read as the server failing.
    env.setdefault("MCP_TOOL_TIMEOUT", "900000")
    env.setdefault("MCP_TIMEOUT", "120000")  # first uvx start resolves rpy2
    # The same 15-minute ceiling for the alt arm's own simulations: Bash's
    # 2-minute default would cut a 50-replicate AlphaSimR script short.
    env.setdefault("BASH_DEFAULT_TIMEOUT_MS", "900000")
    env.setdefault("BASH_MAX_TIMEOUT_MS", "900000")
    return env


RUNS = HERE / "runs"


def run_one(arm: str, q: dict[str, Any], rep: int) -> dict[str, Any]:
    out = RUNS / arm / f"{q['id']}-{rep}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    prompt = PROMPT.format(question=q["question"], answer_format=q["answer_format"])
    with tempfile.TemporaryDirectory(prefix=f"agentqa-{arm}-") as d:
        tmp = Path(d)
        cmd = [
            "claude", "-p", prompt, "--model", MODEL, "--setting-sources", "",
            "--output-format", "stream-json", "--verbose", "--system-prompt", SYSTEM,
            *arm_flags(arm, tmp),
        ]  # fmt: skip
        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                cwd=tmp,
                capture_output=True,
                text=True,
                timeout=RUN_TIMEOUT_S,
                env=run_env(tmp),
                check=False,  # a failed run is recorded with its exit code, not raised
            )
            stdout, rc = proc.stdout, proc.returncode
        except subprocess.TimeoutExpired as exc:
            stdout = (
                (exc.stdout or b"").decode()
                if isinstance(exc.stdout, bytes)
                else exc.stdout or ""
            )
            rc = "timeout"
        seconds = round(time.monotonic() - t0, 1)
    out.write_text(stdout)
    events = [json.loads(ln) for ln in stdout.splitlines() if ln.startswith("{")]
    init = next(
        (e for e in events if e.get("type") == "system" and e.get("subtype") == "init"),
        {},
    )
    result = next((e for e in events if e.get("type") == "result"), {})
    tools = [
        b["name"]
        for e in events
        if e.get("type") == "assistant"
        for b in e["message"].get("content", [])
        if b.get("type") == "tool_use"
    ]
    reply = result.get("result") or ""
    return {
        "arm": arm,
        "qid": q["id"],
        "category": q["category"],
        "rep": rep,
        "exit": rc,
        "seconds": seconds,
        "claude_code": init.get("claude_code_version"),
        "model": init.get("model"),
        "mcp_servers": init.get("mcp_servers"),
        "tools_available": init.get("tools") or [],
        "tool_calls": tools,
        "cost_usd": result.get("total_cost_usd"),
        "reply": reply,
        **score(q, reply),
    }


def alphasimr_version() -> str:
    env = dict(os.environ, R_LIBS_USER=R_LIBS_USER)
    return subprocess.run(
        ["Rscript", "-e", 'cat(as.character(packageVersion("AlphaSimR")))'],
        check=True, capture_output=True, text=True, env=env, timeout=120,
    ).stdout.strip()  # fmt: skip


def preflight(key: dict[str, Any]) -> None:
    """Refuse to start a sweep whose R library is not the key's AlphaSimR
    (every arm uses it), or whose scorer would not score the key itself right."""
    have = alphasimr_version()
    if have != key["alphasimr"]:
        sys.exit(
            f"AlphaSimR {have} in {R_LIBS_USER}, but the key was built on "
            f"{key['alphasimr']}: rebuild the key or install that version"
        )
    wrong = [
        q["id"]
        for q in key["questions"]
        if score(q, f"ANSWER: {q['truth']['value']}")["verdict"] != "right"
    ]
    if wrong:
        sys.exit(f"oracle check failed: the key's own values score wrong for {wrong}")


def rescore(results: Path, by_id: dict[str, dict[str, Any]]) -> None:
    """Score each stored reply again, so a key or scorer fix reaches runs
    made before it; prints every verdict that changed."""
    rows = [json.loads(ln) for ln in results.read_text().splitlines()]
    for r in rows:
        new = score(by_id[r["qid"]], r["reply"])
        if new["verdict"] != r["verdict"]:
            print(f"{r['arm']:4} {r['qid']} rep{r['rep']} {r['verdict']} -> {new['verdict']}"
                  f" ({new['value']!r})")  # fmt: skip
        r.update(new)
    results.write_text("".join(json.dumps(r) + "\n" for r in rows))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", default="bare,alt,mcp")
    ap.add_argument("--reps", type=int, default=3)
    # One worker by default: each mcp run holds its own R process, and the
    # alt arm may run AlphaSimR itself.
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--only", default="", help="comma-separated question ids")
    ap.add_argument("--results", default=str(HERE / "results.jsonl"))
    ap.add_argument("--runs", default=str(HERE / "runs"), help="where transcripts go")
    ap.add_argument(
        "--rescore",
        action="store_true",
        help="re-score every stored reply against the current questions.json, run nothing",
    )
    a = ap.parse_args()
    global RUNS
    RUNS = Path(a.runs).expanduser()
    key = json.loads((HERE / "questions.json").read_text())
    questions = key["questions"]
    if a.rescore:
        rescore(Path(a.results), {q["id"]: q for q in questions})
        return
    preflight(key)
    if a.only:
        keep = set(a.only.split(","))
        questions = [q for q in questions if q["id"] in keep]
    results = Path(a.results)
    done = set()
    if results.exists():
        for ln in results.read_text().splitlines():
            r = json.loads(ln)
            done.add((r["arm"], r["qid"], r["rep"]))
    todo = [
        (arm, q, rep)
        for rep in range(1, a.reps + 1)
        for q in questions
        for arm in a.arms.split(",")
        if (arm, q["id"], rep) not in done
    ]
    print(f"{len(todo)} runs to do ({len(done)} already in {results.name})", flush=True)
    lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        futures = [pool.submit(run_one, *t) for t in todo]
        for n, f in enumerate(as_completed(futures), 1):
            r = f.result()
            with lock, results.open("a") as fh:
                fh.write(json.dumps(r) + "\n")
            print(
                f"[{n}/{len(todo)}] {r['arm']:4} {r['qid']} rep{r['rep']} {r['verdict']:9}"
                f" exit={r['exit']} {r['seconds']}s calls={len(r['tool_calls'])}"
                f" ${r['cost_usd']}",
                flush=True,
            )
    sys.exit(0)


if __name__ == "__main__":
    main()
