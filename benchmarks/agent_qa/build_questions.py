"""Draw the agent benchmark's questions and fix their answers by simulation.

The questions sit where closed forms fail (many cycles in small populations,
paired scheme comparisons, genomic prediction accuracy), so the key is an
AlphaSimR simulation, not a formula. ``simulate_key.R`` drives AlphaSimR
directly and this script never imports breedsim_mcp, so a bug in the server
cannot also be in the key. The key and the server do share the engine:
the benchmark measures whether an agent sets up and runs the stated
simulation correctly. (``tests/test_agent_qa_key_matches_server.py`` checks
the two agree seed for seed.)

Each question pins its founders with a seed and states the R calls, so the
key is the expectation over replicate seeds for that founder set, estimated
from ``R_KEY`` replicates. The question also states how many replicates the
answer should rest on (``R_ANSWER``), and the band is the noise of such an
answer plus the key's own:

    half_width = 3 * sd * sqrt(1 / R_ANSWER + 1 / R_KEY)

with ``sd`` the per-replicate standard deviation of the quantity (for a
proportion, ``sqrt(p (1 - p))``), rounded UP to two significant figures and
stated in the question. Nothing else is in the band, so it holds no theory
slack to hide a shortcut in.

Designs are drawn from fixed grids by a seeded RNG. A candidate becomes a
question only if every shortcut named for its category (``theory.py``:
infinite-population intensity, R = h2 S every cycle, Bulmer without drift,
drift-only variance, Daetwyler's formula, ...) lands OUTSIDE the band; the
control category keeps the opposite rule, that the textbook answer lands
INSIDE it. How many candidates each rule rejected is stored in
questions.json and printed.

    uv run python benchmarks/agent_qa/build_questions.py                  # writes questions.json
    uv run python benchmarks/agent_qa/build_questions.py --discrimination # shortcut table
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import signal
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import theory as T

SEED = 20261016
HERE = Path(__file__).resolve().parent
N_CHR, SEG_SITES, N_QTL = 10, 100, 10
R_KEY = {"genomic_accuracy": 300}  # replicates behind the key; 400 elsewhere
R_KEY_DEFAULT = 400
R_ANSWER = {"prob_beats": 100}  # replicates the question asks for; 50 elsewhere
R_ANSWER_DEFAULT = 50
Z = 3.0
WORKERS = 4

# category -> (questions wanted, candidates drawn)
PLAN = {
    "control_response": (6, 18),
    "long_term_gain": (8, 16),
    "remaining_variance": (8, 16),
    "scheme_difference": (7, 14),
    "prob_beats": (6, 40),
    "genomic_accuracy": (5, 12),
}

INTRO = "This question is about a stochastic simulation in the R package AlphaSimR."
TOLERANCE = " Answers within ±{tol} of the expected value count as right."


def r_key(cat: str) -> int:
    return R_KEY.get(cat, R_KEY_DEFAULT)


def r_answer(cat: str) -> int:
    return R_ANSWER.get(cat, R_ANSWER_DEFAULT)


def draw(rng: random.Random) -> list[dict[str, Any]]:
    """Candidate designs, PLAN[cat][1] per category, in seeded order."""
    out: list[dict[str, Any]] = []

    def n_of(p: float, N: int) -> int:
        return max(2, round(p * N))

    for cat, (_, pool) in PLAN.items():
        for _ in range(pool):
            d: dict[str, Any] = {
                "founder_seed": rng.randrange(1, 1_000_000),
                "n_chr": N_CHR,
                "seg_sites": SEG_SITES,
                "n_qtl_per_chr": N_QTL,
                "n_snp_per_chr": 0,
            }
            if cat == "control_response":
                N = rng.choice([500, 1000])
                d |= {
                    "n_ind": N,
                    "h2": rng.choice([0.2, 0.3, 0.4, 0.5, 0.6]),
                    "cycles": 1,
                }
                d["n_select"] = n_of(rng.choice([0.05, 0.1, 0.2, 0.3]), N)
            elif cat in ("long_term_gain", "remaining_variance"):
                N = rng.choice([20, 30, 50, 100])
                d |= {"n_ind": N, "h2": rng.choice([0.2, 0.4, 0.6, 0.8])}
                d["n_select"] = n_of(rng.choice([0.1, 0.2, 0.3]), N)
                d["cycles"] = rng.choice([5, 8, 10])
            elif cat in ("scheme_difference", "prob_beats"):
                N = rng.choice([30, 50, 100])
                d |= {"n_ind": N, "h2": rng.choice([0.2, 0.4, 0.6])}
                d["n_select"] = n_of(rng.choice([0.05, 0.1]), N)
                d["n_select_b"] = n_of(rng.choice([0.3, 0.5]), N)
                d["cycles"] = rng.choice([5, 10, 15])
            elif cat == "genomic_accuracy":
                N = rng.choice([100, 200, 300])
                d |= {"n_ind": N, "h2": rng.choice([0.2, 0.5, 0.8])}
                d["n_select"] = n_of(rng.choice([0.1, 0.2]), N)
                d["n_snp_per_chr"] = rng.choice([10, 20, 40])
                # quickHaplo founders carry no marker-QTL LD, so first-cycle
                # accuracy is ~0; the LD that selection and drift build over
                # several cycles is what the question is about.
                d["cycles"] = rng.choice([4, 6])
            d["n_cross"] = d["n_ind"]
            out.append({"category": cat, "design": d})
    for k, c in enumerate(out):
        c["candidate"] = k
    return out


def key_design(c: dict[str, Any]) -> dict[str, Any]:
    d, cat = c["design"], c["category"]
    method = "genomic" if cat == "genomic_accuracy" else "pheno"
    arms = [
        {
            "label": "a",
            "method": method,
            "n_select": d["n_select"],
            "n_cross": d["n_cross"],
        }
    ]
    if "n_select_b" in d:
        arms.append(
            {
                "label": "b",
                "method": "pheno",
                "n_select": d["n_select_b"],
                "n_cross": d["n_cross"],
            }
        )
    return {
        "id": str(c["candidate"]),
        **{
            k: d[k]
            for k in ("founder_seed", "n_ind", "n_chr", "seg_sites", "n_qtl_per_chr")
        },
        "n_snp_per_chr": d["n_snp_per_chr"],
        "h2": d["h2"],
        "cycles": d["cycles"],
        "replicates": r_key(cat),
        "seed0": 5_000_000 + 1000 * c["candidate"],
        "arms": arms,
    }


def simulate(designs: list[dict[str, Any]]) -> dict[str, Any]:
    """Run simulate_key.R over the designs in WORKERS parallel R processes."""
    env = dict(os.environ, OMP_NUM_THREADS="1")
    env.setdefault("R_LIBS_USER", str(Path.home() / "R" / "library"))
    # Each design's output is cached under a hash of the design itself, so a
    # rebuild after changing one category only simulates what changed.
    default = Path.home() / ".cache" / "breedsim-agent-qa-key"
    cache = Path(os.environ.get("AGENT_QA_KEY_CACHE", default))
    cache.mkdir(parents=True, exist_ok=True)
    script = (HERE / "simulate_key.R").read_bytes()

    def slot(d: dict[str, Any]) -> Path:
        h = hashlib.sha256(script + json.dumps(d, sort_keys=True).encode())
        return cache / f"{h.hexdigest()[:24]}.json"

    out: dict[str, Any] = {}
    todo = []
    for d in designs:
        if slot(d).exists():
            out[d["id"]] = json.loads(slot(d).read_text())
        else:
            todo.append(d)
    print(f"simulating {len(todo)} designs ({len(out)} cached)", flush=True)
    chunks = [todo[i::WORKERS] for i in range(WORKERS) if todo[i::WORKERS]]
    with tempfile.TemporaryDirectory() as tmp:
        procs = []
        for i, chunk in enumerate(chunks):
            src, dst = Path(tmp) / f"d{i}.json", Path(tmp) / f"o{i}.json"
            src.write_text(json.dumps(chunk))
            cmd = ["Rscript", str(HERE / "simulate_key.R"), str(src), str(dst)]
            procs.append((subprocess.Popen(cmd, env=env), dst))
        for proc, dst in procs:
            if proc.wait(timeout=7200) != 0:
                raise RuntimeError(f"simulate_key.R exited {proc.returncode}")
            by_id = {d["id"]: d for d in todo}
            for o in json.loads(dst.read_text()):
                slot(by_id[o["id"]]).write_text(json.dumps(o["arms"]))
                out[o["id"]] = o["arms"]
    return out


def _col(rows: list[list[float]], t: int) -> np.ndarray:
    # jsonlite writes a one-cycle vector as a bare number (auto_unbox).
    return np.array(
        [r if isinstance(r, float | int) else r[t] for r in rows], dtype=float
    )


def statistic(cat: str, arms: dict[str, Any], cycles: int) -> tuple[float, float]:
    """(key value, per-replicate SD) of the quantity the question asks for."""
    t = cycles - 1
    if cat in ("control_response", "long_term_gain"):
        x = _col(arms["a"]["gain"], t)
    elif cat == "remaining_variance":
        x = _col(arms["a"]["var"], t)
    elif cat == "genomic_accuracy":
        x = _col(arms["a"]["acc"], t)
    elif cat == "scheme_difference":
        x = _col(arms["a"]["gain"], t) - _col(arms["b"]["gain"], t)
    elif cat == "prob_beats":
        p = float(np.mean(_col(arms["a"]["gain"], t) > _col(arms["b"]["gain"], t)))
        return p, math.sqrt(p * (1 - p))
    else:
        raise ValueError(cat)
    return float(x.mean()), float(x.std(ddof=1))


def round_up_2sig(x: float) -> float:
    if x <= 0:
        return 0.0
    e = math.floor(math.log10(x)) - 1
    return round(math.ceil(x / 10**e - 1e-9) * 10**e, 10)


def shortcuts(cat: str, d: dict[str, Any]) -> dict[str, tuple[float, str]]:
    """name -> (value, role): role "outside" (must miss the band), "inside"
    (the control's textbook answer, must hit it) or "info" (reported only)."""
    h = math.sqrt(d["h2"])
    t = d["cycles"]
    N, n = d["n_ind"], d["n_select"]
    p = n / N
    out: dict[str, tuple[float, str]] = {}
    if cat == "control_response":
        out["breeder's equation, R = i(n,N) h"] = (
            T.intensity_finite(n, N) * h,
            "inside",
        )
        out["R = i h2 (sigma_P dropped)"] = (T.intensity_finite(n, N) * d["h2"], "info")
    if cat == "long_term_gain":
        out["R = h2 S every cycle, infinite-population i"] = (
            t * T.intensity_infinite(p) * h,
            "outside",
        )
        out["R = h2 S every cycle, finite i(n,N)"] = (
            t * T.intensity_finite(n, N) * h,
            "outside",
        )
        out["Bulmer effect, no drift"] = (
            T.bulmer_infinite(p, d["h2"], t)[-1]["mean"],
            "outside",
        )
        out["Bulmer + drift, infinitesimal"] = (
            T.programme(N, n, d["h2"], t)[-1]["mean"],
            "info",
        )
    if cat == "remaining_variance":
        out["unchanged (1)"] = (1.0, "outside")
        out["drift only, (1 - 1/(2n))^t over the n parents"] = (
            (1 - 1 / (2 * n)) ** t,
            "outside",
        )
        out["Bulmer effect, no drift"] = (
            T.bulmer_infinite(p, d["h2"], t)[-1]["var"],
            "outside",
        )
        out["Bulmer + drift, infinitesimal"] = (
            T.programme(N, n, d["h2"], t)[-1]["var"],
            "info",
        )
    if cat in ("scheme_difference", "prob_beats"):
        nb = d["n_select_b"]
        pb = nb / N
        naive_inf = t * (T.intensity_infinite(p) - T.intensity_infinite(pb)) * h
        naive_fin = t * (T.intensity_finite(n, N) - T.intensity_finite(nb, N)) * h
        bul = (
            T.bulmer_infinite(p, d["h2"], t)[-1]["mean"]
            - T.bulmer_infinite(pb, d["h2"], t)[-1]["mean"]
        )
        full = (
            T.programme(N, n, d["h2"], t)[-1]["mean"]
            - T.programme(N, nb, d["h2"], t)[-1]["mean"]
        )
        if cat == "scheme_difference":
            out["R = h2 S every cycle, infinite-population i"] = (naive_inf, "outside")
            out["R = h2 S every cycle, finite i(n,N)"] = (naive_fin, "outside")
            out["Bulmer effect, no drift"] = (bul, "outside")
            out["Bulmer + drift, infinitesimal"] = (full, "info")
        else:
            out["certain: 1 or 0 by the sign of the breeder's-equation difference"] = (
                1.0 if naive_fin > 0 else 0.0,
                "outside",
            )
            out["coin flip (0.5)"] = (0.5, "outside")
    if cat == "genomic_accuracy":
        m = d["n_snp_per_chr"] * d["n_chr"]
        out["accuracy of phenotypic selection, h"] = (h, "outside")
        out["Daetwyler, Me = number of markers"] = (
            T.daetwyler_accuracy(N, d["h2"], m),
            "outside",
        )
        out["zero (no LD in quickHaplo founders)"] = (0.0, "outside")
    return out


def found_code(d: dict[str, Any]) -> str:
    chip = (
        f"SP$addSnpChip(nSnpPerChr={d['n_snp_per_chr']}); "
        if d["n_snp_per_chr"]
        else ""
    )
    return (
        f"set.seed({d['founder_seed']}); founders <- quickHaplo(nInd={d['n_ind']}, "
        f"nChr={d['n_chr']}, segSites={d['seg_sites']}); SP <- SimParam$new(founders); "
        f"SP$addTraitA(nQtlPerChr={d['n_qtl_per_chr']}); {chip}SP$setVarE(h2={d['h2']})"
    )


def question_text(cat: str, d: dict[str, Any], tol: str) -> str:
    R = r_answer(cat)
    t = d["cycles"]
    head = (
        f"{INTRO} Founders and trait, exactly these calls in this order: `{found_code(d)}`. "
        "The trait is purely additive, with founder genetic mean 0 and founder genetic "
        "variance 1. Each replicate starts from these same founders with its own seed s: "
        "`set.seed(s); pop <- newPop(founders, simParam=SP)`."
    )
    gen = (
        f' Then, each generation: `sel <- selectInd(pop, nInd={d["n_select"]}, use="pheno", '
        f"simParam=SP); pop <- randCross(sel, nCrosses={d['n_cross']}, simParam=SP)`."
    )
    gens = "one generation" if t == 1 else f"{t} generations"
    tail = TOLERANCE.format(tol=tol)
    if cat in ("control_response", "long_term_gain"):
        return (
            head
            + gen
            + f" Run {gens}. What is the expected meanG(pop) after generation "
            f"{t}? Base your answer on {R} replicates." + tail
        )
    if cat == "remaining_variance":
        return (
            head
            + gen
            + f" Run {gens}. What is the expected genetic variance, varG(pop), "
            f"after generation {t}? Base your answer on {R} replicates." + tail
        )
    if cat in ("scheme_difference", "prob_beats"):
        body = (
            head + f" Two schemes run for {gens}. Each generation, scheme A keeps "
            f"nInd={d['n_select']} and scheme B nInd={d['n_select_b']} (selectInd, "
            f'use="pheno"), and both make nCrosses={d["n_cross"]} with randCross. '
            "Replicates are paired: for each seed s, set.seed(s) before scheme A's newPop "
            "and again before scheme B's."
        )
        if cat == "scheme_difference":
            return (
                body + f" What is the expected difference meanG(A) - meanG(B) after "
                f"generation {t}? Base your answer on {R} paired replicates." + tail
            )
        return (
            body
            + f" In what fraction of paired replicates does scheme A end generation "
            f"{t} with a higher meanG than scheme B? Base your answer on {R} paired "
            "replicates and give it as a proportion between 0 and 1." + tail
        )
    if cat == "genomic_accuracy":
        return (
            head + f" Then {gens} of genomic selection, each one: `sol <- RRBLUP(pop, "
            "simParam=SP); pop <- setEBV(pop, sol, simParam=SP); sel <- selectInd(pop, "
            f'nInd={d["n_select"]}, use="ebv", simParam=SP); pop <- randCross(sel, '
            f"nCrosses={d['n_cross']}, simParam=SP); pop <- setEBV(pop, sol, "
            "simParam=SP)`, so each generation's model is fitted afresh and then scored on "
            "the progeny it never saw. The prediction accuracy of a generation is "
            "cor(ebv(pop), gv(pop)) at the end of it, taken as 0 if undefined. What is the "
            f"expected prediction accuracy in generation {t}? Base your answer on {R} "
            "replicates." + tail
        )
    raise ValueError(cat)


def alphasimr_version() -> str:
    env = dict(os.environ)
    env.setdefault("R_LIBS_USER", str(Path.home() / "R" / "library"))
    return subprocess.run(
        ["Rscript", "-e", 'cat(as.character(packageVersion("AlphaSimR")))'],
        check=True, capture_output=True, text=True, env=env,
    ).stdout.strip()  # fmt: skip


def evaluate(c: dict[str, Any], arms: dict[str, Any]) -> dict[str, Any]:
    """The candidate's key, band and shortcut verdicts."""
    cat, d = c["category"], c["design"]
    value, sd = statistic(cat, arms, d["cycles"])
    rk, ra = r_key(cat), r_answer(cat)
    half = round_up_2sig(Z * sd * math.sqrt(1 / ra + 1 / rk))
    sc = {
        name: {
            "value": round(x, 5),
            "role": role,
            "outside_band": abs(x - value) > half,
        }
        for name, (x, role) in shortcuts(cat, d).items()
    }
    ok = all(
        s["outside_band"] if s["role"] == "outside" else not s["outside_band"]
        for s in sc.values()
        if s["role"] != "info"
    )
    if cat == "prob_beats":
        ok = ok and 0.05 < value < 0.95  # an extreme proportion has a degenerate band
    return {
        "value": value,
        "sd": sd,
        "half": half,
        "shortcuts": sc,
        "ok": ok,
        "replicates_key": rk,
        "replicates_answer": ra,
        "key_se": sd / math.sqrt(rk),
        # Share of the band's variance that is the answer's own MC noise; the
        # rest is the key's.
        "answer_noise_share": (1 / ra) / (1 / ra + 1 / rk),
    }


def main() -> None:
    signal.alarm(4 * 3600)  # walltime guard
    cands = draw(random.Random(SEED))
    sims = simulate([key_design(c) for c in cands])
    chosen: list[dict[str, Any]] = []
    rejected: dict[str, int] = {}
    for c in cands:
        cat = c["category"]
        if sum(q["category"] == cat for q in chosen) >= PLAN[cat][0]:
            continue
        ev = evaluate(c, sims[str(c["candidate"])])
        if not ev["ok"]:
            rejected[cat] = rejected.get(cat, 0) + 1
            continue
        tol = f"{ev['half']:g}"
        chosen.append(
            {
                "category": cat,
                "design": c["design"],
                "candidate": c["candidate"],
                "question": question_text(cat, c["design"], tol),
                "answer_format": "a single number (decimal, not a fraction or range)",
                "truth": {"value": round(ev["value"], 5), "half_width": ev["half"], "tolerance": tol},
                "key": {k: (round(v, 5) if isinstance(v, float) else v)
                        for k, v in ev.items() if k not in ("value", "half", "ok")},
            }
        )  # fmt: skip
    short = {
        cat: PLAN[cat][0] - sum(q["category"] == cat for q in chosen) for cat in PLAN
    }
    for cat, (want, pool) in PLAN.items():
        got = want - short[cat]
        print(
            f"{cat}: {got} of {want} kept, {rejected.get(cat, 0)} of {pool} candidates rejected"
        )
    chosen.sort(key=lambda q: (list(PLAN).index(q["category"]), q["candidate"]))
    for k, q in enumerate(chosen, 1):
        q["id"] = f"q{k:02d}"
    out = {
        "built": datetime.now(UTC).date().isoformat(),
        "seed": SEED,
        "alphasimr": alphasimr_version(),
        "band": f"{Z} * sd * sqrt(1/R_answer + 1/R_key), rounded up to 2 significant figures",
        "candidates": {
            cat: {"wanted": w, "drawn": p, "rejected": rejected.get(cat, 0)}
            for cat, (w, p) in PLAN.items()
        },
        "questions": chosen,
    }
    (HERE / "questions.json").write_text(json.dumps(out, indent=1) + "\n")
    print(f"wrote {len(chosen)} questions")
    if any(short.values()):
        sys.exit(
            f"too few candidates passed in: { {k: v for k, v in short.items() if v} }"
        )


def discrimination() -> None:
    """Per category and shortcut: in how many questions it misses the band."""
    qs = json.loads((HERE / "questions.json").read_text())["questions"]
    tally: dict[tuple[str, str, str], list[bool]] = {}
    for q in qs:
        for name, s in q["key"]["shortcuts"].items():
            tally.setdefault((q["category"], name, s["role"]), []).append(
                s["outside_band"]
            )
    print("| Kind | Shortcut | Must | Outside the band in |\n|---|---|---|---|")
    for (c, name, role), v in tally.items():
        must = {"outside": "miss", "inside": "hit", "info": "(reported)"}[role]
        print(f"| {c} | {name} | {must} | {sum(v)} of {len(v)} |")


if __name__ == "__main__":
    if sys.argv[1:] == ["--discrimination"]:
        discrimination()
    else:
        main()
