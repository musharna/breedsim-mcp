"""Genomic selection, and the measurement that decides whether it means anything.

The central claim under test is not "RRBLUP runs". It is that this server can tell
a population where genomic prediction works from one where it cannot, and that it
does so by MEASURING linkage disequilibrium rather than by trusting a proxy.

That distinction is load-bearing because the obvious proxy fails. Measured at 20
replicates, a population with an LD ratio of 1.00 — no linkage structure at all —
reached out-of-sample prediction accuracy 0.208 by cycle three, beating a
genuinely linked population at the same selection intensity. Accuracy rises with
relatedness, so a guard built on accuracy would pass exactly the population it
exists to catch. See `genomic` for the full table.
"""

import math

import pytest

from breedsim_mcp.diagnostics import (
    no_linkage_disequilibrium_warning,
    prediction_accuracy_low_warning,
)
from breedsim_mcp.engine import r_eval
from breedsim_mcp.founding import found_population
from breedsim_mcp.genomic import LD_RATIO_FLOOR, NoSnpChipError
from breedsim_mcp.limits import LIMITS, LimitExceededError
from breedsim_mcp.program import run_replicate
from breedsim_mcp.replication import run_program
from breedsim_mcp.session import Session, SessionStore

# Large enough that the LD estimate is stable, small enough that a runMacs
# founding stays around half a minute.
GENOTYPED = {
    "n_ind": 120,
    "n_chr": 5,
    "seg_sites": 60,
    "n_qtl_per_chr": 5,
    "h2": 0.4,
    "n_snp_per_chr": 25,
}


def _genotyped(store, generator="quickHaplo", seed=3, **over):
    return found_population(
        store, generator=generator, seed=seed, **{**GENOTYPED, **over}
    )


# ---------------------------------------------------------------------------
# The measurement
# ---------------------------------------------------------------------------


def test_ld_measurement_separates_a_linked_population_from_an_unlinked_one():
    """The discriminator itself, against both regimes of real founders.

    quickHaplo draws haplotypes with no coalescent history, so adjacent markers
    are no more correlated than distant ones and the ratio sits at 1. runMacs
    simulates a coalescent, so adjacent markers are markedly more correlated.

    Both arms are asserted deliberately. A test that only checked quickHaplo
    would pass just as happily if `measure_ld` always returned a ratio of 1 — the
    runMacs arm is the positive control that proves the measurement can detect LD
    when LD is there, rather than merely failing to find it everywhere.
    """
    store = SessionStore(max_sessions=4)

    unlinked = _genotyped(store, generator="quickHaplo").ld
    linked = _genotyped(store, generator="runMacs").ld
    assert unlinked is not None and linked is not None

    assert unlinked["ratio"] < LD_RATIO_FLOOR, unlinked
    assert unlinked["has_linkage_disequilibrium"] is False

    assert linked["ratio"] > LD_RATIO_FLOOR, linked
    assert linked["has_linkage_disequilibrium"] is True

    # The separation must be real, not a threshold landing between two noisy
    # numbers that happen to straddle it.
    assert linked["ratio"] > unlinked["ratio"] * 1.5, (
        f"LD ratios too close to discriminate: {linked['ratio']:.2f} linked vs "
        f"{unlinked['ratio']:.2f} unlinked"
    )


def test_no_chip_means_no_ld_measurement():
    """Ungenotyped founders report None, not a fabricated zero."""
    store = SessionStore()
    s = found_population(store, generator="quickHaplo", seed=1, n_ind=40, n_chr=2)
    assert s.ld is None
    assert s.n_snp_per_chr == 0


# ---------------------------------------------------------------------------
# The advisory keys on the measurement, not on a proxy
# ---------------------------------------------------------------------------


def _fake(generator: str, ratio: float | None) -> Session:
    """A session carrying only what the advisory reads.

    Constructed rather than simulated so the generator name and the measured LD
    can be varied INDEPENDENTLY. Real founders cannot do that — runMacs always
    has LD and quickHaplo never does — so a test built only on real populations
    could not tell a name-based guard from a measurement-based one. The two
    hypotheses are only separable on inputs that nature does not produce.
    """
    ld = (
        None
        if ratio is None
        else {
            "adjacent": 0.02 * ratio,
            "background": 0.02,
            "ratio": ratio,
            "n_markers": 100,
            "has_linkage_disequilibrium": ratio >= LD_RATIO_FLOOR,
        }
    )
    return Session(
        session_id="bs-x",
        r_prefix=".bs_x",
        generator=generator,
        seed=1,
        founder_hash="h",
        reproducible=(generator == "quickHaplo"),
        spec={},
        ld=ld,
    )


def test_ld_advisory_keys_on_the_measurement_not_the_generator_name():
    """The guard must follow the number, even when the name says otherwise.

    A `generator == "quickHaplo"` check would produce identical results on every
    population AlphaSimR actually generates, and would silently fail on a runMacs
    configuration whose parameters had flattened its LD. These two cases are the
    only ones that can tell the implementations apart.
    """
    # Named like the trustworthy generator, measured flat -> must still fire.
    fired = no_linkage_disequilibrium_warning(_fake("runMacs", ratio=1.02))
    assert fired is not None, "advisory missed a flat-LD runMacs population"
    assert fired.code == "no_linkage_disequilibrium"

    # Named like the untrustworthy generator, measured linked -> must NOT fire.
    assert no_linkage_disequilibrium_warning(_fake("quickHaplo", ratio=4.0)) is None


def test_ld_advisory_is_silent_without_a_chip():
    """No markers means no claim to make about them, either way."""
    assert no_linkage_disequilibrium_warning(_fake("quickHaplo", ratio=None)) is None


def test_ld_advisory_reports_the_numbers_and_the_reproducibility_trade():
    """The message has to carry the measurement and the cost of the fix.

    Telling a caller to switch to runMacs without telling them runMacs is not
    reproducible trades one silent wrong answer for another.
    """
    advisory = no_linkage_disequilibrium_warning(_fake("quickHaplo", ratio=1.0))
    assert advisory is not None
    msg = advisory.message
    assert "1.00" in msg
    assert "runMacs" in msg
    assert "reproducible" in msg.lower()


def test_accuracy_advisory_cannot_substitute_for_the_ld_check():
    """The measured counterexample, encoded.

    0.208 is what a zero-LD population actually reached at cycle three. The
    accuracy advisory stays silent on it — correctly, since the model IS
    predicting — which is precisely why it cannot be the thing that detects
    absent linkage disequilibrium.
    """
    healthy_looking = {
        "mean": 0.208,
        "sd": 0.1,
        "ci_low": 0.143,
        "ci_high": 0.274,
        "n": 20,
    }
    assert prediction_accuracy_low_warning(healthy_looking) is None
    # ... while the LD advisory, on the same population, does fire.
    assert no_linkage_disequilibrium_warning(_fake("quickHaplo", ratio=1.0)) is not None


# ---------------------------------------------------------------------------
# Running it
# ---------------------------------------------------------------------------


def test_genomic_selection_without_a_chip_is_refused_before_r_sees_it():
    """AlphaSimR's own error here is `subscript out of bounds`, which tells the
    caller nothing about the decision they got wrong."""
    store = SessionStore()
    s = found_population(store, generator="quickHaplo", seed=1, n_ind=40, n_chr=2)
    with pytest.raises(NoSnpChipError, match="n_snp_per_chr"):
        run_program(
            store, s.session_id, cycles=1, replicates=5, selection_method="genomic"
        )


def test_reported_accuracy_is_out_of_sample_not_the_models_own_fit():
    """Scoring the model on its training generation would overstate it.

    This is the mutation that matters: drop the second `setEBV` in
    `run_replicate` — the one that re-scores the fitted model against the progeny
    — and the reported number silently becomes an in-sample fit. It would still
    look like a plausible accuracy, which is why the test compares against the
    in-sample value computed here rather than merely checking the range.
    """
    store = SessionStore()
    s = _genotyped(store, generator="quickHaplo", seed=11)

    record = run_replicate(s, 1, 20, 60, seed=99, selection_method="genomic")[0]
    reported = record.prediction_accuracy
    assert reported is not None

    # Refit exactly what the first cycle fitted, and score it on its OWN
    # training generation. Same seed, same founders, same model.
    in_sample = float(
        r_eval(f"""
        set.seed(99)
        .t_pop <- newPop({s.founders}, simParam={s.sim_param})
        .t_sol <- RRBLUP(.t_pop, simParam={s.sim_param})
        .t_pop <- setEBV(.t_pop, .t_sol, simParam={s.sim_param})
        suppressWarnings(cor(as.numeric(ebv(.t_pop)[, 1]),
                             as.numeric(gv(.t_pop)[, 1])))
        """)[0]
    )
    r_eval('rm(list=c(".t_pop", ".t_sol"), envir=.GlobalEnv)')

    assert not math.isclose(reported, in_sample, abs_tol=1e-6), (
        f"reported accuracy {reported:.6f} equals the model's in-sample fit — "
        "it is being scored on the individuals it was trained on"
    )
    # In-sample fit is the optimistic one; that direction is what makes reporting
    # it dishonest rather than merely different.
    assert in_sample > reported, (
        f"expected in-sample {in_sample:.3f} to exceed out-of-sample {reported:.3f}"
    )


def test_genomic_runs_report_accuracy_as_a_distribution():
    """One replicate's accuracy is a draw, exactly like one replicate's gain."""
    store = SessionStore()
    s = _genotyped(store, seed=5)
    out = run_program(
        store,
        s.session_id,
        cycles=2,
        replicates=5,
        n_select=30,
        selection_method="genomic",
    )
    acc = out["cycles"][-1]["prediction_accuracy"]
    assert {"mean", "sd", "ci_low", "ci_high", "n"} <= set(acc)
    assert acc["n"] == 5
    assert acc["ci_low"] <= acc["mean"] <= acc["ci_high"]
    assert out["recipe"]["selection_method"] == "genomic"


def test_phenotypic_runs_report_no_accuracy_at_all():
    """Absent, not zero. A zero would read as a model that failed, when in fact
    no model was fitted."""
    store = SessionStore()
    s = _genotyped(store, seed=6)
    out = run_program(
        store,
        s.session_id,
        cycles=2,
        replicates=5,
        n_select=30,
        selection_method="phenotypic",
    )
    for cycle in out["cycles"]:
        assert "prediction_accuracy" not in cycle


def test_the_two_methods_take_different_paths():
    """Genomic selection must not silently fall through to phenotypic.

    Same founders, same seed, same intensity: if the branch were dead, the two
    arms would return identical gains.
    """
    store = SessionStore()
    s = _genotyped(store, seed=8)
    common = {"cycles": 2, "replicates": 5, "n_select": 30}
    gain = {
        method: run_program(store, s.session_id, selection_method=method, **common)[
            "cycles"
        ][-1]["genetic_gain"]["mean"]
        for method in ("phenotypic", "genomic")
    }
    assert gain["phenotypic"] != gain["genomic"], (
        "both selection methods produced identical gain — the genomic branch is "
        f"not being taken ({gain})"
    )


def test_comparison_can_contrast_the_two_methods_on_shared_founders():
    """The flagship question — is genotyping worth it here — in one paired call."""
    from breedsim_mcp.comparison import compare_programs

    store = SessionStore()
    s = _genotyped(store, seed=9)
    out = compare_programs(
        store,
        s.session_id,
        a_n_select=30,
        b_n_select=30,
        cycles=2,
        replicates=5,
        a_selection_method="genomic",
        b_selection_method="phenotypic",
    )
    assert out["programs"]["a"]["selection_method"] == "genomic"
    assert out["programs"]["b"]["selection_method"] == "phenotypic"
    assert out["paired"] is True
    # The verdict must still come from the interval, not from the larger mean.
    diff = out["cycles"][-1]["difference"]
    expected = "a" if diff["ci_low"] > 0 else "b" if diff["ci_high"] < 0 else None
    assert out["favours"] == expected


# ---------------------------------------------------------------------------
# Bounds
# ---------------------------------------------------------------------------


def test_markers_and_qtl_together_cannot_exceed_the_segregating_sites():
    """R's own message here is "Not enough eligible sites", which names none of
    the three numbers the caller has to reconcile."""
    store = SessionStore()
    with pytest.raises(ValueError, match="seg_sites"):
        found_population(
            store,
            generator="quickHaplo",
            seed=1,
            n_ind=40,
            n_chr=2,
            seg_sites=60,
            n_qtl_per_chr=10,
            n_snp_per_chr=55,
        )

    # Positive control: a total that exactly fills the sites is legal, so the
    # bound is a ceiling rather than an off-by-one.
    ok = found_population(
        store,
        generator="quickHaplo",
        seed=1,
        n_ind=40,
        n_chr=2,
        seg_sites=60,
        n_qtl_per_chr=10,
        n_snp_per_chr=50,
    )
    assert ok.n_snp_per_chr == 50


def test_snp_count_has_an_upper_bound():
    store = SessionStore()
    with pytest.raises(LimitExceededError, match="n_snp_per_chr"):
        found_population(
            store,
            generator="quickHaplo",
            seed=1,
            n_ind=40,
            n_chr=2,
            seg_sites=60,
            n_snp_per_chr=LIMITS["n_snp_per_chr"] + 1,
        )


def test_unknown_selection_method_is_refused_with_the_valid_ones():
    store = SessionStore()
    s = _genotyped(store, seed=10)
    with pytest.raises(ValueError, match="phenotypic"):
        run_program(
            store, s.session_id, cycles=1, replicates=5, selection_method="gblup"
        )
