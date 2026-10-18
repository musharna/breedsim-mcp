"""Work-count performance ratchet: exact call counts per tool, never milliseconds.

Each workload drives one MCP tool through ``build_server().call_tool`` on a
tiny, seeded quickHaplo session, in its OWN fresh process (so caches such as
``_t_critical`` and R's global state start the same every time). While only
the tool call runs (setup is not counted), a ``sys.setprofile`` hook counts:

- every call of a function defined under ``src/breedsim_mcp`` -- keyed
  ``relpath:qualname``. Comprehension and generator-expression frames are
  skipped: Python 3.12 inlines list comprehensions (PEP 709) and 3.11 does
  not, so counting them would make the table depend on the CI matrix entry.
- every R evaluation (``rpy2.robjects.R.__call__``, i.e. ``ro.r(code)``),
  keyed by the package function that issued it (``R<-relpath:qualname``),
- every R function invocation through rpy2 (``rinterface.SexpClosure.__call__``).

The gate is the three totals per workload, equal to ``perf_baseline.json``
with zero headroom. A rise fails and needs ``--allow-increase`` to record; a
drop also fails until ``--update`` records it, so a gain cannot be given back
silently. On failure the per-function deltas are printed.

    uv run python tests/perf_ratchet.py                  # check (exit 1 on any change)
    uv run python tests/perf_ratchet.py --update         # record drops
    uv run python tests/perf_ratchet.py --update --allow-increase
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
BASELINE = HERE / "perf_baseline.json"
TOTALS = ("python_calls", "r_evals", "r_function_calls")

# Tiny on purpose: the gate counts work, so a workload only has to touch each
# path once per loop level (2 cycles x 5 replicates, the replicate floor).
FOUND = {
    "generator": "quickHaplo",
    "seed": 7,
    "n_ind": 20,
    "n_chr": 2,
    "seg_sites": 20,
    "n_qtl_per_chr": 3,
    "h2": 0.4,
}
FOUND_CHIP = {**FOUND, "n_snp_per_chr": 5}
RUN = {"cycles": 2, "replicates": 5, "n_select": 5, "base_seed": 11}


def _setup_none(call):
    return {}


def _setup_session(call):
    return {"session_id": call("found_population", FOUND)["session_id"]}


def _setup_chip(call):
    return {"session_id": call("found_population", FOUND_CHIP)["session_id"]}


def _setup_session_run(call):
    sid = call("found_population", FOUND)["session_id"]
    call("run_program", {"session_id": sid, **RUN})
    return {"session_id": sid}


# name -> (setup, tool, args, signature of the output only this workload makes)
# The signature is read from what the tool COMPUTED (counts of cycles,
# replicates, markers), never from an echoed argument, so a worker that fell
# back to a different workload or a default could not satisfy it.
WORKLOADS: dict[str, tuple[Any, str, dict[str, Any], Any]] = {
    "list_methods": (
        _setup_none,
        "list_methods",
        {},
        lambda o: [len(o["generators"]), len(o["selection_methods"]), len(o["limits"])],
    ),
    "found_population": (
        _setup_none,
        "found_population",
        FOUND_CHIP,
        lambda o: [len(o["founder_hash"]), o["linkage_disequilibrium"]["n_markers"]],
    ),
    "run_program": (
        _setup_session,
        "run_program",
        RUN,
        lambda o: [
            len(o["cycles"]),
            o["cycles"][-1]["genetic_gain"]["n"],
            "prediction_accuracy" in o["cycles"][-1],
        ],
    ),
    "run_program_genomic": (
        _setup_chip,
        "run_program",
        {**RUN, "cycles": 1, "selection_method": "genomic"},
        lambda o: [
            len(o["cycles"]),
            o["cycles"][-1]["genetic_gain"]["n"],
            o["cycles"][-1]["prediction_accuracy"]["n"],
        ],
    ),
    "compare_programs": (
        _setup_session,
        "compare_programs",
        {
            "cycles": 2,
            "replicates": 5,
            "a_n_select": 3,
            "b_n_select": 10,
            "base_seed": 11,
        },
        lambda o: [len(o["cycles"]), o["cycles"][-1]["difference"]["n"]],
    ),
    "describe_session": (
        _setup_session_run,
        "describe_session",
        {},
        lambda o: [o["cycles_run"], len(o["founder_hash"])],
    ),
}
EXPECTED_SIGNATURE = {
    "list_methods": [2, 2, 9],
    "found_population": [16, 10],
    "run_program": [2, 5, False],
    "run_program_genomic": [1, 5, 5],
    "compare_programs": [2, 5],
    "describe_session": [2, 16],
}


def _profile_call(fn) -> tuple[Any, dict[str, int]]:
    """Run fn() under a profile hook; return (result, counts)."""
    import rpy2.rinterface as ri
    import rpy2.robjects as ro

    import breedsim_mcp

    pkg = str(Path(breedsim_mcp.__file__).resolve().parent) + os.sep
    r_eval_code = type(ro.r).__call__.__code__
    # SexpClosure.__call__ is wrapped by a result-conversion decorator whose
    # code object is shared with other wrapped functions; the closure cell
    # holds the real method, whose code is unique to "call an R function".
    function_codes = {
        cell.cell_contents.__code__
        for cell in ri.SexpClosure.__call__.__closure__ or ()
        if getattr(cell.cell_contents, "__name__", "") == "__call__"
    }
    if not function_codes:
        raise RuntimeError(
            "rpy2 changed: SexpClosure.__call__ has no inner __call__ to count"
        )
    counts: collections.Counter[str] = collections.Counter()

    def key(code) -> str:
        rel = os.path.relpath(code.co_filename, pkg)
        return f"{rel}:{code.co_qualname}"

    def caller(frame) -> str:
        # The package function that ASKED for the evaluation: engine.r_eval is
        # the one door every call goes through, so naming it would name nothing.
        f = frame.f_back
        while f is not None and (
            not f.f_code.co_filename.startswith(pkg)
            or key(f.f_code) == "engine.py:r_eval"
        ):
            f = f.f_back
        return "R<-" + (key(f.f_code) if f is not None else "?")

    def hook(frame, event, arg):
        if event != "call":
            return
        code = frame.f_code
        if code is r_eval_code:
            counts["r_evals"] += 1
            counts[caller(frame)] += 1
        elif code in function_codes:
            counts["r_function_calls"] += 1
        elif code.co_filename.startswith(pkg):
            name = code.co_name
            if name.startswith("<") and name != "<lambda>":
                return  # listcomp/genexpr frames: version-dependent, see module doc
            counts["python_calls"] += 1
            counts[key(code)] += 1

    # MCPServer runs a sync tool in an anyio worker thread, so the hook has to
    # reach threads too. setprofile_all_threads (3.12+) also covers threads
    # that already exist; on 3.11 threading.setprofile covers the new worker
    # thread each asyncio.run starts, which is the only one a tool runs in.
    set_all = getattr(threading, "setprofile_all_threads", None)
    if set_all is not None:
        set_all(hook)
    else:
        threading.setprofile(hook)
        sys.setprofile(hook)
    try:
        result = fn()
    finally:
        if set_all is not None:
            set_all(None)
        else:
            threading.setprofile(None)
            sys.setprofile(None)
    return result, dict(counts)


def worker(name: str) -> dict[str, Any]:
    """Run one workload in this (fresh) process and return its counts."""
    if name not in WORKLOADS:
        raise SystemExit(f"unknown workload {name!r}; known: {sorted(WORKLOADS)}")
    from breedsim_mcp.server import build_server

    srv = build_server()

    def call(tool: str, args: dict[str, Any]) -> dict[str, Any]:
        res = asyncio.run(srv.call_tool(tool, args))
        if res.is_error or res.structured_content is None:
            raise RuntimeError(f"{tool}({args}) failed: {res.content}")
        return res.structured_content

    setup, tool, args, signature = WORKLOADS[name]
    extra = setup(call)
    out, counts = _profile_call(lambda: call(tool, {**args, **extra}))
    sig = signature(out)
    if sig != EXPECTED_SIGNATURE[name]:
        raise SystemExit(
            f"workload {name!r} produced signature {sig}, expected "
            f"{EXPECTED_SIGNATURE[name]}: the harness did not run what it was asked"
        )
    return {"signature": sig, "counts": dict(sorted(counts.items()))}


def measure(names: list[str] | None = None) -> dict[str, Any]:
    """Each workload in its own subprocess; {name: {"signature", "counts"}}."""
    env = dict(os.environ, OMP_NUM_THREADS="1")
    lib = Path.home() / "R" / "library"
    if lib.is_dir() and "R_LIBS_USER" not in env:
        env["R_LIBS_USER"] = str(lib)
    out = {}
    for name in names or list(WORKLOADS):
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--worker", name],
            capture_output=True, text=True, timeout=600, env=env, check=False,
        )  # fmt: skip
        if proc.returncode != 0:
            raise RuntimeError(
                f"workload {name} failed:\n{proc.stdout}\n{proc.stderr[-4000:]}"
            )
        out[name] = json.loads(proc.stdout.strip().splitlines()[-1])
    return out


def deltas(base: dict[str, int], new: dict[str, int], top: int = 12) -> list[str]:
    keys = set(base) | set(new)
    d = [(k, new.get(k, 0) - base.get(k, 0)) for k in keys]
    d = [x for x in d if x[1] and x[0] not in TOTALS]
    d.sort(key=lambda x: (-abs(x[1]), x[0]))
    return [
        f"    {v:+d}  {k}  ({base.get(k, 0)} -> {new.get(k, 0)})" for k, v in d[:top]
    ]


def compare(baseline: dict[str, Any], measured: dict[str, Any]) -> list[str]:
    """Human-readable lines for every workload whose totals moved; [] if none."""
    problems = []
    for name in sorted(set(baseline) | set(measured)):
        if name not in baseline or name not in measured:
            problems.append(
                f"{name}: in {'measured' if name in measured else 'baseline'} only"
            )
            continue
        b, m = baseline[name]["counts"], measured[name]["counts"]
        moved = [t for t in TOTALS if b.get(t, 0) != m.get(t, 0)]
        if moved:
            totals = ", ".join(f"{t} {b.get(t, 0)} -> {m.get(t, 0)}" for t in moved)
            problems.append(f"{name}: {totals}")
            problems.extend(deltas(b, m))
    return problems


def update_refusal(
    baseline: dict[str, Any], measured: dict[str, Any], *, allow_increase: bool
) -> str | None:
    """Why ``--update`` must not write the measured counts, or None if it may.

    A changed output signature is always refused: the workload computed
    something else, so its counts are not comparable and recording them would
    hide the change. A rise in any total is refused unless ``allow_increase``.
    A drop, or a new workload, may be recorded.
    """
    changed = [
        name
        for name in measured
        if name in baseline
        and baseline[name].get("signature") != measured[name].get("signature")
    ]
    if changed:
        return (
            f"output signature changed in {changed}; fix the workload, not the baseline"
        )
    rises = [
        name
        for name in measured
        if name in baseline
        and any(
            measured[name]["counts"].get(t, 0) > baseline[name]["counts"].get(t, 0)
            for t in TOTALS
        )
    ]
    if rises and not allow_increase:
        return f"counts rose in {rises}; re-run with --allow-increase to accept"
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--worker", help=argparse.SUPPRESS)
    ap.add_argument("--update", action="store_true", help="record the measured counts")
    ap.add_argument(
        "--allow-increase", action="store_true", help="with --update: accept a rise"
    )
    a = ap.parse_args()
    if a.worker:
        print(json.dumps(worker(a.worker)))
        return
    measured = measure()
    baseline = json.loads(BASELINE.read_text()) if BASELINE.exists() else {}
    problems = compare(baseline, measured)
    for name, row in measured.items():
        print(name, {t: row["counts"].get(t, 0) for t in TOTALS})
    if not problems:
        print("perf ratchet: all totals equal the baseline")
        return
    print("\n".join(problems))
    if not a.update:
        sys.exit(1)
    refusal = update_refusal(baseline, measured, allow_increase=a.allow_increase)
    if refusal:
        sys.exit(refusal)
    BASELINE.write_text(json.dumps(measured, indent=1, sort_keys=True) + "\n")
    print(f"wrote {BASELINE.name}")


if __name__ == "__main__":
    main()
