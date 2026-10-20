"""Ask every question to Claude Code under each arm, and score the replies.

Arms (same model, same prompt, isolated: no user settings, hooks or other MCP
servers, an empty working directory per run):

- ``bare``: no tools at all.
- ``alt``:  what a user has without this server: Bash (with R + AlphaSimR and
  Python on PATH), Read, WebSearch and WebFetch. Claude can write its own
  AlphaSimR or theory code.
- ``mcp``:  breedsim-mcp (pinned PyPI release, via uvx) only. ``--server-spec``
  runs an unreleased commit instead (a git URL by full SHA), and
  ``--exclude-newer`` pins that environment's dependencies to a date.

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
import datetime as dt
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
DEFAULT_MODEL = MODEL
SERVER = "breedsim-mcp==0.5.1"  # latest on PyPI, checked 2026-10-16
# --server-spec runs an unreleased commit instead of the PyPI pin: the git URL
# of a commit pushed to the PR branch, by full SHA so it cannot move. Set once by
# main() before any run; recorded in every row and in versions.json.
SPEC_PREFIX = "git+https://github.com/musharna/breedsim-mcp@"
SERVER_SPEC: str | None = None
# --exclude-newer: uvx resolves the server's dependencies (mcp, rpy2, numpy) as
# of this date, so a re-run does not pick up a release made after the last sweep.
EXCLUDE_NEWER: str | None = None
# The account's usage windows, read from each transcript's rate_limit_event.
# A run that sees the five-hour window at or above this, or a rejected request,
# makes the sweep sleep until the window resets (each pause is logged).
PAUSE_AT = 0.85
# The seven-day window does not reset within a sweep: at or above this the
# sweep stops (exit 3) after writing the run that saw it; a later resume
# carries on from there.
STOP_SEVEN_DAY = 0.90
PAUSES: Path | None = None
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


def server_uvx() -> list[str]:
    """uvx arguments that start the server under test."""
    pins = ["--exclude-newer", EXCLUDE_NEWER] if EXCLUDE_NEWER else []
    # A uv-managed CPython, as pyproject's [tool.uv] asks for: a conda
    # interpreter's libstdc++ breaks rpy2's dlopen of libR.so.
    managed = ["--python-preference", "only-managed"]
    if SERVER_SPEC is None:
        return [*pins, *managed, SERVER]
    return [*pins, *managed, "--from", SERVER_SPEC, "breedsim-mcp"]


def set_server_spec(spec: str | None, exclude_newer: str | None) -> None:
    global SERVER_SPEC, EXCLUDE_NEWER
    if spec is not None:
        sha = spec.removeprefix(SPEC_PREFIX)
        if (
            not spec.startswith(SPEC_PREFIX)
            or len(sha) != 40
            or not all(c in "0123456789abcdef" for c in sha)
        ):
            sys.exit(
                f"--server-spec must be {SPEC_PREFIX}<full 40-hex sha>, got {spec!r}"
            )
    SERVER_SPEC, EXCLUDE_NEWER = spec, exclude_newer


def set_model(model: str, runs: Path) -> None:
    """--model runs every arm on another model. Its transcripts go to
    ``<runs>-<model>/`` so they never overwrite the default model's."""
    global MODEL, RUNS
    MODEL = model
    RUNS = runs if model == DEFAULT_MODEL else runs.with_name(f"{runs.name}-{model}")


def check_results_model(results: Path) -> None:
    """Refuse to resume a results file made on another model: resume skips
    every (arm, question, rep) already there, so a Haiku sweep pointed at the
    Opus results would run nothing and report Opus rows as its own. Rows from
    before --model existed carry only the served model."""
    if not results.exists():
        return
    other = sorted(
        {
            m
            for ln in results.read_text().splitlines()
            if ln.strip()
            for r in [json.loads(ln)]
            if (m := r.get("model_requested", r.get("model"))) != MODEL
        }
    )
    if other:
        sys.exit(
            f"{results} holds rows run on {other}, not {MODEL}: use another --results"
        )


def server_versions() -> dict[str, str]:
    """What the mcp arm's uvx environment resolves to, read from inside it."""
    code = (
        "import importlib.metadata as m, platform, json; print(json.dumps("
        "{d: m.version(d) for d in ('breedsim-mcp', 'mcp', 'rpy2', 'numpy')}"
        " | {'python': platform.python_version()}))"
    )
    uvx = server_uvx()
    if SERVER_SPEC is None:  # `uvx breedsim-mcp==x` names the tool; run python in it
        uvx = [*uvx[:-1], "--from", SERVER]
    else:
        uvx = uvx[:-1]
    out = subprocess.run(
        ["uvx", *uvx, "python", "-c", code],
        check=True, capture_output=True, text=True, timeout=900, env=clean_env(),
    ).stdout  # fmt: skip
    return json.loads(out.strip().splitlines()[-1])


def clean_env() -> dict[str, str]:
    """The caller's environment without this repository's virtualenv: under
    ``uv run`` its python (which can import breedsim_mcp) would come first on
    the alt arm's PATH, and its path names the benchmark's worktree."""
    venv = os.environ.get("VIRTUAL_ENV")
    env = {
        k: v for k, v in os.environ.items() if k not in ("VIRTUAL_ENV", "PYTHONPATH")
    }
    if venv:
        env["PATH"] = os.pathsep.join(
            p for p in env.get("PATH", "").split(os.pathsep) if not p.startswith(venv)
        )
    return env


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
            "args": server_uvx(),
            "env": {"R_LIBS_USER": R_LIBS_USER, "OMP_NUM_THREADS": "1"},
        }
        cfg.write_text(json.dumps({"mcpServers": {"breedsim": server}}))
        return [
            "--tools", "", "--allowedTools", "mcp__breedsim",
            "--strict-mcp-config", "--mcp-config", str(cfg),
        ]  # fmt: skip
    raise ValueError(arm)


def run_env(tmp: Path) -> dict[str, str]:
    env = dict(clean_env(), R_LIBS_USER=R_LIBS_USER, OMP_NUM_THREADS="1")
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
# Per-run working directories (each with its own TMPDIR); None = the system temp.
WORK: Path | None = None


def rate_limit(events: list[dict[str, Any]]) -> dict[str, Any]:
    """The last rate_limit_event's status and five-hour / seven-day windows."""
    info = next(
        (e["rate_limit_info"] for e in reversed(events)
         if e.get("type") == "rate_limit_event" and e.get("rate_limit_info")),
        {},
    )  # fmt: skip
    win = info.get("unifiedWindows") or {}
    return {
        "status": info.get("status"),
        "five_hour": (win.get("five_hour") or {}).get("utilization"),
        "seven_day": (win.get("seven_day") or {}).get("utilization"),
        "resets_at": (win.get("five_hour") or {}).get("resetsAt")
        or info.get("resetsAt"),
    }


def api_failure(events: list[dict[str, Any]]) -> bool:
    """The API ended the run before the model answered: a request was rejected
    for the rate limit and no assistant message came back. Read from the
    transcript, never from the reply or its score."""
    rejected = rate_limit(events)["status"] == "rejected"
    answered = any(e.get("type") == "assistant" for e in events)
    return rejected and not answered


def seven_day_exhausted(rl: dict[str, Any]) -> bool:
    return (rl.get("seven_day") or 0) >= STOP_SEVEN_DAY


def pause_if_limited(rl: dict[str, Any], where: str) -> None:
    """Sleep until the five-hour window resets when it is at PAUSE_AT or a
    request was rejected; log the pause beside the results."""
    hot = rl["status"] == "rejected" or (rl["five_hour"] or 0) >= PAUSE_AT
    if not hot or not rl["resets_at"]:
        return
    wait = max(0.0, rl["resets_at"] - time.time()) + 120
    start = dt.datetime.now().astimezone()
    print(f"pausing {wait / 60:.0f} min after {where}: {rl}", flush=True)
    if PAUSES is not None:
        with PAUSES.open("a") as fh:
            fh.write(json.dumps({"after": where, "at": start.isoformat(timespec="seconds"),
                                 "sleep_s": round(wait), **rl}) + "\n")  # fmt: skip
    time.sleep(wait)


def run_one(arm: str, q: dict[str, Any], rep: int) -> dict[str, Any]:
    out = RUNS / arm / f"{q['id']}-{rep}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    prompt = PROMPT.format(question=q["question"], answer_format=q["answer_format"])
    with tempfile.TemporaryDirectory(prefix=f"agentqa-{arm}-", dir=WORK) as d:
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
    uses = [
        b
        for e in events
        if e.get("type") == "assistant"
        for b in e["message"].get("content", [])
        if b.get("type") == "tool_use"
    ]
    tools = [b["name"] for b in uses]
    reply = result.get("result") or ""
    rl = rate_limit(events)
    row = {
        "arm": arm,
        "qid": q["id"],
        "category": q["category"],
        "rep": rep,
        "exit": rc,
        "seconds": seconds,
        "claude_code": init.get("claude_code_version"),
        "model": init.get("model"),  # the model actually served
        "model_requested": MODEL,
        "mcp_servers": init.get("mcp_servers"),
        "tools_available": init.get("tools") or [],
        "tool_calls": tools,
        "tool_arg_names": [sorted(b.get("input") or {}) for b in uses],
        "cost_usd": result.get("total_cost_usd"),
        "server_spec": (SERVER_SPEC or SERVER) if arm == "mcp" else None,
        "exclude_newer": EXCLUDE_NEWER if arm == "mcp" else None,
        "rate_limit": rl,
        "api_failure": api_failure(events),
        "reply": reply,
        **score(q, reply),
    }
    pause_if_limited(rl, f"{arm} {q['id']} rep{rep}")
    return row


def record_models_served(results: Path) -> None:
    """Add the models the init events reported (every row's ``model``) to
    versions.json, so it shows what was served, not only what was asked for."""
    versions = results.parent / "versions.json"
    if not versions.exists() or not results.exists():
        return
    rows = [json.loads(ln) for ln in results.read_text().splitlines() if ln.strip()]
    served: dict[str, int] = {}
    for r in rows:
        served[str(r.get("model"))] = served.get(str(r.get("model")), 0) + 1
    v = json.loads(versions.read_text())
    v["models_served"] = served
    versions.write_text(json.dumps(v, indent=1) + "\n")
    print("models served:", served, flush=True)


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


def drop_api_failures(results: Path) -> None:
    """Move every row the API ended to results.api_failures.jsonl, unless its
    triple was already dropped once (then it stays, and counts as invalid)."""
    side = results.with_name("results.api_failures.jsonl")
    dropped = set()
    if side.exists():
        for ln in side.read_text().splitlines():
            r = json.loads(ln)
            dropped.add((r["arm"], r["qid"], r["rep"]))
    rows = [json.loads(ln) for ln in results.read_text().splitlines()]
    keep, move = [], []
    for r in rows:
        t = (r["arm"], r["qid"], r["rep"])
        (move if r.get("api_failure") and t not in dropped else keep).append(r)
    with side.open("a") as fh:
        fh.writelines(json.dumps(r) + "\n" for r in move)
    results.write_text("".join(json.dumps(r) + "\n" for r in keep))
    print(
        f"moved {len(move)} API-failure rows to {side.name}; resume to re-run them once"
    )


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
    ap.add_argument("--work", default=None, help="parent of the per-run working dirs")
    ap.add_argument(
        "--server-spec",
        help=f"run the server from {SPEC_PREFIX}<full sha> instead of {SERVER}",
    )
    ap.add_argument(
        "--exclude-newer",
        help="uvx --exclude-newer date for the server environment's dependencies",
    )
    ap.add_argument(
        "--drop-api-failures",
        action="store_true",
        help="move rows the API ended (api_failure) to results.api_failures.jsonl "
        "so a resume runs them again; a triple is re-run at most once",
    )
    ap.add_argument(
        "--rescore",
        action="store_true",
        help="re-score every stored reply against the current questions.json, run nothing",
    )
    ap.add_argument(
        "--model",
        default=MODEL,
        help=f"claude --model for every arm (default {MODEL}); another model's "
        "transcripts go to <runs>-<model>/",
    )
    a = ap.parse_args()
    global WORK, PAUSES
    set_model(a.model, Path(a.runs).expanduser())
    if a.work:
        WORK = Path(a.work).expanduser()
        WORK.mkdir(parents=True, exist_ok=True)
    PAUSES = Path(a.results).parent / "pauses.jsonl"
    set_server_spec(a.server_spec, a.exclude_newer)
    key = json.loads((HERE / "questions.json").read_text())
    questions = key["questions"]
    if a.rescore:
        rescore(Path(a.results), {q["id"]: q for q in questions})
        return
    if a.drop_api_failures:
        drop_api_failures(Path(a.results))
        return
    check_results_model(Path(a.results))
    preflight(key)
    if "mcp" in a.arms.split(","):
        versions = server_versions()
        print("server environment:", json.dumps(versions), flush=True)
        if SERVER_SPEC is None and versions["breedsim-mcp"] != SERVER.split("==")[1]:
            sys.exit(
                f"uvx resolved breedsim-mcp {versions['breedsim-mcp']}, not {SERVER}"
            )
        Path(a.results).parent.mkdir(parents=True, exist_ok=True)
        # What this sweep ran, beside its results; rewritten at every start, so
        # a resume that resolved anything differently shows it in git.
        (Path(a.results).parent / "versions.json").write_text(
            json.dumps(
                {
                    "server_spec": SERVER_SPEC or SERVER,
                    "server_uvx": server_uvx(),
                    "exclude_newer": EXCLUDE_NEWER,
                    "model": MODEL,
                    "runs_dir": RUNS.name,
                    "alphasimr": key["alphasimr"],
                    "server_environment": versions,
                    "claude_effort_env": os.environ.get("CLAUDE_EFFORT"),
                },
                indent=1,
            )
            + "\n"
        )
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
            if seven_day_exhausted(r["rate_limit"]):
                print(
                    f"STOP: seven_day {r['rate_limit']['seven_day']} >= {STOP_SEVEN_DAY}",
                    flush=True,
                )
                pool.shutdown(wait=True, cancel_futures=True)
                record_models_served(results)
                sys.exit(3)
    record_models_served(results)
    sys.exit(0)


if __name__ == "__main__":
    main()
