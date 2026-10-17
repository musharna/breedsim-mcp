"""Draw the agent benchmark's questions and fix their answers by theory.

Every answer is a quantitative-genetics expectation computed in ``theory.py``
(breeder's equation, finite-sample selection intensity, the Bulmer effect,
drift through Ne). This script never imports breedsim_mcp, so a bug in the
server cannot also be in the key.

Each answer carries a band, because an honest simulation of the design lands
near the expectation, not on it. The band is

    half_width = 3 * SE_one_session + slack * |theory|

- ``SE_one_session`` is the standard error of a careful estimate made on ONE
  founder set: ``sqrt(sigma_f^2 + sigma_s^2 / R)``, where ``sigma_f`` is the
  founder-set-to-founder-set spread (which more replicates on one session
  cannot remove), ``sigma_s`` the seed-to-seed spread within a founder set,
  and ``R`` the replicate count assumed (20 for a mean, 100 for an SD). Both
  are measured by ``calibrate.R``: AlphaSimR driven directly, not the server.
- ``slack`` is a per-category allowance for where the theory is an
  approximation (finite loci, drift during selection). The build FAILS if a
  calibration mean lands outside ``slack * |theory| + 3 * SE_calibration`` of
  the theory, so the key cannot accept a value that a correct simulation does
  not reach, nor sit where one cannot reach it.

The MC fraction of each band (``3 * SE_one_session / half_width``) is stored
with the question.

    uv run python benchmarks/agent_qa/build_questions.py   # writes questions.json
"""

from __future__ import annotations

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
R_MEAN, R_SD = 20, 100  # replicates assumed for a one-session estimate
Z = 3.0

# Theory slack per category, as a fraction of |theory|. Set before the
# calibration ran, from what each approximation leaves out; the build checks
# the calibration against it rather than tuning it to the calibration.
SLACK = {
    # Exact for normal phenotypes; 1% for the founder sample being rescaled to
    # variance exactly 1 and for 100 biallelic QTL not being exactly normal.
    "intensity": 0.01,
    # Breeder's equation is exact in expectation for one cycle (R = h2 S).
    "response_1cycle": 0.03,
    # Bulmer, one cycle; allele-frequency change at 100 QTL is not in it.
    "bulmer_variance": 0.03,
    # Two or three cycles: drift and finite-loci losses compound.
    "multi_cycle_gain": 0.04,
    "paired_difference": 0.03,
    # Founder-set rescaling inflates small-N variances (a Jensen term).
    "drift_sd": 0.05,
}

SETUP = (
    "Consider this AlphaSimR simulation. Founders: {N} diploid individuals from "
    "quickHaplo(nInd={N}, nChr={c}, segSites={s}), so loci start in linkage "
    "equilibrium. One purely additive trait with {q} QTL per chromosome "
    "(addTraitA: founder genetic mean 0, founder additive genetic variance 1). "
    "Residual variance is set once, at founding, so that narrow-sense "
    "heritability in the founders is {h2} (setVarE(h2={h2})), and stays fixed after."
)
GENERATION = (
    " Each generation: phenotype everyone, keep the {n} with the highest phenotypes "
    "(selectInd, use='pheno'), and make {m} progeny from random pairs of the kept "
    "individuals (randCross, one progeny per cross)."
)
TOLERANCE = " Answers within ±{pct}% of the expected value count as right."


def _setup(d: dict[str, Any]) -> str:
    return SETUP.format(N=d["n_ind"], c=N_CHR, s=SEG_SITES, q=N_QTL, h2=d["h2"])


def draw(rng: random.Random) -> list[dict[str, Any]]:
    """Every question's design, drawn from fixed grids by a seeded RNG, so no
    design is hand-picked. Constraints keep each one discriminating (e.g. the
    Bulmer questions need strong selection on a heritable trait, or the
    variance does not move outside the noise)."""
    qs: list[dict[str, Any]] = []

    def add(category: str, **d: Any) -> None:
        d.setdefault("n_chr", N_CHR)
        d.setdefault("seg_sites", SEG_SITES)
        d.setdefault("n_qtl_per_chr", N_QTL)
        qs.append({"category": category, "design": d})

    # Selection intensity: four finite samples, two infinite-population ones.
    seen = set()
    while len([q for q in qs if q["category"] == "intensity"]) < 4:
        N = rng.choice([500, 1000, 2000])
        p = rng.choice([0.02, 0.05, 0.1, 0.2, 0.3])
        if (N, p) in seen:
            continue
        seen.add((N, p))
        add(
            "intensity", kind="finite", n_ind=N, n_select=round(p * N), h2=1.0, cycles=1
        )
    for p in rng.sample([0.01, 0.05, 0.15, 0.25, 0.4], 2):
        add("intensity", kind="infinite", p=p, n_ind=5000, n_select=round(p * 5000),
            h2=1.0, cycles=1)  # fmt: skip

    def scheme(min_p: float = 0.02, max_p: float = 0.3, h2s: tuple = ()) -> tuple:
        N = rng.choice([200, 500, 1000])
        p = rng.choice([x for x in (0.02, 0.05, 0.1, 0.2, 0.3) if min_p <= x <= max_p])
        h2 = rng.choice(h2s or (0.1, 0.2, 0.3, 0.4, 0.5, 0.6))
        return N, max(2, round(p * N)), h2

    for _ in range(8):
        N, n, h2 = scheme()
        add("response_1cycle", n_ind=N, n_select=n, h2=h2, cycles=1)
    for _ in range(6):
        N, n, h2 = scheme(max_p=0.1, h2s=(0.5, 0.6, 0.7, 0.8, 0.9))
        add("bulmer_variance", n_ind=N, n_select=n, h2=h2, cycles=1)
    for _ in range(8):
        N, n, h2 = scheme(min_p=0.05)
        add("multi_cycle_gain", n_ind=N, n_select=n, h2=h2, cycles=rng.choice([2, 3]))
    for _ in range(6):
        N, n_a, h2 = scheme(max_p=0.05, h2s=(0.2, 0.3, 0.4, 0.5))
        n_b = round(rng.choice([0.2, 0.3, 0.5]) * N)
        add("paired_difference", n_ind=N, n_select=n_a, n_select_b=n_b, h2=h2,
            cycles=rng.choice([1, 2]))  # fmt: skip
    seen = set()
    while len([q for q in qs if q["category"] == "drift_sd"]) < 6:
        N, t = rng.choice([50, 100, 200]), rng.choice([5, 10, 20, 30])
        if (N, t) in seen:
            continue
        seen.add((N, t))
        add("drift_sd", n_ind=N, n_select=N, h2=0.4, cycles=t)
    for k, q in enumerate(qs, 1):
        q["id"] = f"q{k:02d}"
        q["design"].setdefault("n_cross", q["design"]["n_ind"])
    return qs


def theory_value(q: dict[str, Any]) -> tuple[float, str]:
    d, c = q["design"], q["category"]
    if c == "intensity":
        if d["kind"] == "infinite":
            return T.intensity_infinite(d["p"]), "i = phi(z_p) / p"
        return T.intensity_finite(
            d["n_select"], d["n_ind"]
        ), "E[mean of top n of N std normals]"
    if c == "drift_sd":
        ne = T.effective_size(d["n_ind"], d["n_cross"])
        f = 1 - (1 - 1 / (2 * ne)) ** d["cycles"]
        return math.sqrt(
            2 * f
        ), f"sqrt(2 F_t), F_t = 1 - (1 - 1/(2 Ne))^t, Ne = {ne:.2f}"
    prog = T.programme(d["n_ind"], d["n_select"], d["h2"], d["cycles"], d["n_cross"])
    if c in ("response_1cycle", "multi_cycle_gain"):
        return prog[-1]["mean"], "breeder's equation per cycle, Bulmer-reduced variance"
    if c == "bulmer_variance":
        return prog[0]["var"], "Bulmer: between-pair + Mendelian variance, finite n"
    if c == "paired_difference":
        b = T.programme(d["n_ind"], d["n_select_b"], d["h2"], d["cycles"], d["n_cross"])
        return prog[-1]["mean"] - b[-1]["mean"], "difference of two programme() means"
    raise ValueError(c)


def calibration_design(q: dict[str, Any], k: int) -> dict[str, Any]:
    d = q["design"]
    sd_kind = q["category"] == "drift_sd"
    arms = [{"label": "a", "n_select": d["n_select"], "n_cross": d["n_cross"]}]
    if q["category"] == "paired_difference":
        arms.append(
            {"label": "b", "n_select": d["n_select_b"], "n_cross": d["n_cross"]}
        )
    return {
        "id": q["id"],
        "n_ind": d["n_ind"],
        "n_chr": d["n_chr"],
        "seg_sites": d["seg_sites"],
        "n_qtl_per_chr": d["n_qtl_per_chr"],
        "h2": d["h2"],
        "cycles": d["cycles"],
        "founder_sets": 6 if sd_kind else 12,
        "seeds": 40 if sd_kind else 8,
        "founder_seed0": 100_000 + 1000 * k,
        "seed0": 2_000_000 + 100_000 * k,
        "arms": arms,
    }


def run_calibration(designs: list[dict[str, Any]]) -> dict[str, Any]:
    env = dict(os.environ, OMP_NUM_THREADS="1")
    env.setdefault("R_LIBS_USER", str(Path.home() / "R" / "library"))
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp) / "designs.json", Path(tmp) / "out.json"
        src.write_text(json.dumps(designs))
        subprocess.run(
            ["Rscript", str(HERE / "calibrate.R"), str(src), str(dst)],
            check=True, env=env, timeout=3600,
        )  # fmt: skip
        out = json.loads(dst.read_text())
    return {o["id"]: o["arms"] for o in out}


def _grid(rows: list[list[float]], col: int) -> np.ndarray:
    """rows of [founder_set, seed, cycle_1, ...] -> K x S array of one cycle."""
    a = np.array(rows, dtype=float)
    ks = sorted(set(a[:, 0]))
    return np.array([a[a[:, 0] == k, 2 + col] for k in ks])


def components(x: np.ndarray) -> tuple[float, float, float]:
    """(grand mean, sigma_f, sigma_s) from a K x S one-way layout (ANOVA)."""
    S = x.shape[1]
    within = float(x.var(axis=1, ddof=1).mean())
    between = float(x.mean(axis=1).var(ddof=1))
    sigma_f2 = max(between - within / S, 0.0)
    return float(x.mean()), math.sqrt(sigma_f2), math.sqrt(within)


def band(q: dict[str, Any], arms: dict[str, Any], value: float) -> dict[str, Any]:
    c, d = q["category"], q["design"]
    t = d["cycles"] - 1
    slack = SLACK[c] * abs(value)
    if c == "drift_sd":
        g = _grid(arms["a"]["gain"], t)
        K, S = g.shape
        sds = g.std(axis=1, ddof=1)
        # Per-set SD sampling variance ~ sd^2 / (2(S-1)); the rest of the
        # spread of per-set SDs is real founder-set variation.
        samp = float(np.mean(sds**2) / (2 * (S - 1)))
        sigma_f = math.sqrt(max(float(sds.var(ddof=1)) - samp, 0.0))
        sigma = float(np.sqrt(np.mean(sds**2)))
        se_one = math.sqrt(sigma_f**2 + sigma**2 / (2 * (R_SD - 1)))
        calib_mean = float(sds.mean())
        se_calib = math.sqrt(sigma_f**2 / K + samp / K)
        stats = {"sigma_f": sigma_f, "sigma_s": sigma, "replicates_assumed": R_SD}
    else:
        key = "var" if c == "bulmer_variance" else "gain"
        a = _grid(arms["a"][key], t)
        if c == "paired_difference":
            b = _grid(arms["b"][key], t)
            diff = a - b
            calib_mean, sigma_f, _ = components(diff)
            # Unpaired seed noise, so an estimate made from two separate runs is
            # also inside the band; pairing only narrows it.
            sa, sb = components(a)[2], components(b)[2]
            sigma_s = math.sqrt(sa**2 + sb**2)
        else:
            calib_mean, sigma_f, sigma_s = components(a)
        K, S = a.shape
        se_one = math.sqrt(sigma_f**2 + sigma_s**2 / R_MEAN)
        se_calib = math.sqrt(sigma_f**2 / K + sigma_s**2 / (K * S))
        stats = {"sigma_f": sigma_f, "sigma_s": sigma_s, "replicates_assumed": R_MEAN}
    half = Z * se_one + slack
    return {
        "half_width": half,
        "mc_fraction": Z * se_one / half,
        "calibration_mean": calib_mean,
        "calibration_se": se_calib,
        "calibration_ok": abs(calib_mean - value) <= slack + Z * se_calib,
        **{k: round(v, 5) if isinstance(v, float) else v for k, v in stats.items()},
    }


def question_text(q: dict[str, Any], pct: int) -> str:
    d, c = q["design"], q["category"]
    if c == "intensity":
        if d["kind"] == "infinite":
            body = (
                f"Truncation selection keeps the top {d['p']:.0%} of a very large "
                "population on a normally distributed phenotype. What is the "
                "selection intensity, the selection differential in phenotypic "
                "standard deviations?"
            )
        else:
            body = (
                f"A normally distributed phenotype is measured on a random sample "
                f"of {d['n_ind']} individuals and the best {d['n_select']} are kept. "
                "What is the expected selection intensity for this finite sample: "
                "the expected mean of the kept individuals minus the population "
                "mean, in phenotypic standard deviations?"
            )
        return body + TOLERANCE.format(pct=pct)
    if c == "drift_sd":
        return (
            _setup(d)
            + f" Every generation all {d['n_ind']} individuals are kept as parents (no "
            f"selection) and make {d['n_cross']} progeny from random pairs (randCross, one "
            "progeny per cross). Many replicate populations are run independently "
            "from the same founders. What is the expected standard deviation, "
            "across replicates, of the population's mean genetic value after "
            f"{d['cycles']} generations, in founder additive genetic SD units?"
            + TOLERANCE.format(pct=pct)
        )
    gen = GENERATION.format(n=d["n_select"], m=d["n_cross"])
    t = d["cycles"]
    after = "one generation" if t == 1 else f"{t} generations"
    if c in ("response_1cycle", "multi_cycle_gain"):
        ask = (
            f" What is the expected mean genetic value of the population after {after}, "
            "in founder additive genetic SD units (the founder mean is 0)?"
        )
        return _setup(d) + gen + ask + TOLERANCE.format(pct=pct)
    if c == "bulmer_variance":
        ask = (
            " What is the expected additive genetic variance of the progeny after one "
            "generation (the population variance of their genetic values), as a "
            "fraction of the founder variance?"
        )
        return _setup(d) + gen + ask + TOLERANCE.format(pct=pct)
    if c == "paired_difference":
        return (
            _setup(d) + " Two programmes start from these same founders and run for "
            f"{after}. Each generation, programme A keeps the {d['n_select']} and "
            f"programme B the {d['n_select_b']} individuals with the highest "
            f"phenotypes (selectInd, use='pheno'); both make {d['n_cross']} progeny "
            "from random pairs of the kept individuals (randCross, one progeny per "
            "cross). What is the expected difference in mean genetic value after "
            f"{after}, A minus B, in founder additive genetic SD units?"
            + TOLERANCE.format(pct=pct)
        )
    raise ValueError(c)


def alphasimr_version() -> str:
    env = dict(os.environ)
    env.setdefault("R_LIBS_USER", str(Path.home() / "R" / "library"))
    return subprocess.run(
        ["Rscript", "-e", 'cat(as.character(packageVersion("AlphaSimR")))'],
        check=True, capture_output=True, text=True, env=env,
    ).stdout.strip()  # fmt: skip


def main() -> None:
    signal.alarm(3600)  # walltime guard: the calibration is minutes, not hours
    qs = draw(random.Random(SEED))
    arms = run_calibration([calibration_design(q, k) for k, q in enumerate(qs)])
    bad = []
    for q in qs:
        value, formula = theory_value(q)
        b = band(q, arms[q["id"]], value)
        pct = max(1, math.ceil(100 * b["half_width"] / abs(value)))
        # The stated tolerance is rounded up to a whole percent and the scorer
        # uses exactly what was stated, so question and key cannot disagree.
        half = pct / 100 * abs(value)
        q["question"] = question_text(q, pct)
        q["answer_format"] = "a single number (decimal, not a fraction or range)"
        q["truth"] = {
            "value": round(value, 5),
            "half_width": round(half, 5),
            "tolerance_pct": pct,
        }
        q["key"] = {
            "theory": formula,
            "slack": SLACK[q["category"]],
            **{k: round(v, 5) if isinstance(v, float) else v for k, v in b.items()},
        }
        if not b["calibration_ok"]:
            bad.append(
                (
                    q["id"],
                    q["category"],
                    value,
                    b["calibration_mean"],
                    b["calibration_se"],
                )
            )
    for row in bad:
        print("calibration outside slack + 3 SE:", row, file=sys.stderr)
    if bad:
        sys.exit(
            f"{len(bad)} questions whose theory a correct simulation does not reach"
        )
    out = {
        "built": datetime.now(UTC).date().isoformat(),
        "seed": SEED,
        "alphasimr": alphasimr_version(),
        "band": f"{Z} * SE(one session; {R_MEAN} replicates for a mean, {R_SD} for an SD)"
        " + slack * |theory|, rounded up to a whole percent",
        "questions": qs,
    }
    (HERE / "questions.json").write_text(json.dumps(out, indent=1) + "\n")
    print(f"wrote {len(qs)} questions")


def wrong_formulas(q: dict[str, Any]) -> dict[str, float]:
    """Answers that common mistakes give for a question, to measure which
    mistakes its band can tell from the right answer."""
    c, d = q["category"], q["design"]
    out: dict[str, float] = {}
    if c == "intensity" and d["kind"] == "finite":
        out["infinite-population i(p) for a finite sample"] = T.intensity_infinite(
            d["n_select"] / d["n_ind"]
        )
    if c == "response_1cycle":
        i = T.intensity_finite(d["n_select"], d["n_ind"])
        out["R = i h2 (sigma_P dropped)"] = i * d["h2"]
        out["R = i h with infinite-population i"] = T.intensity_infinite(
            d["n_select"] / d["n_ind"]
        ) * math.sqrt(d["h2"])
    if c == "bulmer_variance":
        k = T.variance_reduction_infinite(d["n_select"] / d["n_ind"])
        out["1 - k h2 (no halving)"] = 1 - k * d["h2"]
        out["1 - k h2 / 2 (infinite population)"] = 1 - k * d["h2"] / 2
        out["1 (no change)"] = 1.0
    if c == "multi_cycle_gain":
        one = T.programme(d["n_ind"], d["n_select"], d["h2"], 1, d["n_cross"])[0][
            "mean"
        ]
        out["t x one-cycle response (no Bulmer effect)"] = d["cycles"] * one
    if c == "drift_sd":
        n, t = d["n_ind"], d["cycles"]
        out["sqrt(F) (factor 2 dropped)"] = math.sqrt(1 - (1 - 1 / (2 * n)) ** t)
        out["Ne = N/2"] = math.sqrt(2 * (1 - (1 - 1 / n) ** t))
    return out


def discrimination() -> None:
    """For each common mistake: in how many questions does it fall outside
    the band (so the band can tell it from the right answer)?"""
    qs = json.loads((HERE / "questions.json").read_text())["questions"]
    tally: dict[tuple[str, str], list[bool]] = {}
    for q in qs:
        t = q["truth"]
        for name, x in wrong_formulas(q).items():
            tally.setdefault((q["category"], name), []).append(
                abs(x - t["value"]) > t["half_width"]
            )
    print("| Kind | Mistake | Outside the band in |\n|---|---|---|")
    for (c, name), v in tally.items():
        print(f"| {c} | {name} | {sum(v)} of {len(v)} |")


if __name__ == "__main__":
    if sys.argv[1:] == ["--discrimination"]:
        discrimination()
    else:
        main()
