"""Multi-trait architecture and index selection.

The failure this file exists to catch is not a crash. It is a multi-trait
programme that *looks* multi-trait and is actually selecting on trait 1 alone —
AlphaSimR's `selectInd` defaults to `trait=1`, so omitting the index would give
a perfectly plausible result in which the second trait was merely along for the
ride. Every test here therefore checks that the WEIGHTS CHANGED THE OUTCOME,
not merely that a number came back.
"""

import asyncio

import pytest

from breedsim_mcp.founding import found_population
from breedsim_mcp.replication import MIN_REPLICATES, run_program
from breedsim_mcp.server import build_server
from breedsim_mcp.session import SessionStore

SMALL = {"n_ind": 60, "n_chr": 4, "seg_sites": 60, "n_qtl_per_chr": 6}


def _two_trait(store, correlation=0.0, seed=1):
    return found_population(
        store,
        generator="quickHaplo",
        seed=seed,
        h2=[0.5, 0.5],
        trait_correlation=correlation,
        **SMALL,
    )


# --------------------------------------------------------------------------
# founding
# --------------------------------------------------------------------------


def test_a_list_of_heritabilities_declares_the_trait_count():
    store = SessionStore()
    s = _two_trait(store)
    assert s.spec["n_traits"] == 2
    assert s.spec["h2"] == [0.5, 0.5]

    # Positive control: a scalar h2 still yields exactly one trait, and reports
    # the scalar back rather than a one-element list.
    single = found_population(store, generator="quickHaplo", seed=1, h2=0.4, **SMALL)
    assert single.spec["n_traits"] == 1
    assert single.spec["h2"] == 0.4


def test_single_trait_founders_are_byte_identical_to_before_multi_trait():
    """The single-trait R call must be unchanged, or every existing seed moves.

    Multi-trait added arguments to addTraitA. Had they been threaded through the
    single-trait path with defaults, the RNG draw sequence would have shifted and
    every previously-recorded founder_hash would silently become wrong.
    """
    store = SessionStore()
    a = found_population(store, generator="quickHaplo", seed=7, h2=0.4, **SMALL)
    b = found_population(store, generator="quickHaplo", seed=7, h2=0.4, **SMALL)
    assert a.founder_hash == b.founder_hash

    # GOLDEN VALUE, recorded before multi-trait shipped. Comparing two sessions
    # to each other cannot catch a changed code path: if BOTH went through the
    # multi-trait branch they would still agree with each other.
    assert a.founder_hash == "9d387ca4f2c853c6", "founder genotypes moved"

    # founder_hash is NOT sufficient on its own, and believing it was is an
    # error this test made first. The founders come out of quickHaplo BEFORE
    # addTraitA runs, so the trait construction cannot move that hash at all --
    # a mutant routing the single-trait path through the multi-trait addTraitA
    # call survived the hash assertion completely. The trait effects, and hence
    # every phenotype and every gain, DO depend on it. So the invariant is
    # pinned downstream, where the change would actually show.
    out = run_program(
        store, a.session_id, cycles=1, replicates=5, n_select=10, base_seed=99
    )
    assert out["cycles"][0]["genetic_gain"]["mean"] == pytest.approx(
        1.1495833871545191, rel=1e-9
    ), (
        "a seeded single-trait run no longer reproduces its recorded gain. The "
        "trait architecture or the RNG draw sequence changed, which silently "
        "invalidates every previously-published number from this engine."
    )
    # And a one-element LIST must mean the same thing as the scalar.
    c = found_population(store, generator="quickHaplo", seed=7, h2=[0.4], **SMALL)
    assert c.founder_hash == a.founder_hash


def test_trait_correlation_without_multiple_traits_is_refused():
    """Accepting it silently would imply a correlation that cannot exist."""
    store = SessionStore()
    with pytest.raises(ValueError, match="single trait"):
        found_population(
            store,
            generator="quickHaplo",
            seed=1,
            h2=0.4,
            trait_correlation=0.5,
            **SMALL,
        )
    # Positive control: the same value IS accepted with two traits.
    assert _two_trait(store, correlation=0.5).spec["trait_correlation"] == 0.5


def test_out_of_range_heritabilities_are_refused_per_trait():
    store = SessionStore()
    with pytest.raises(ValueError, match="every h2"):
        found_population(store, generator="quickHaplo", seed=1, h2=[0.4, 1.5], **SMALL)


# --------------------------------------------------------------------------
# index selection
# --------------------------------------------------------------------------


def test_multi_trait_run_without_index_weights_is_refused():
    """AlphaSimR would default to trait=1 and look entirely successful."""
    store = SessionStore()
    s = _two_trait(store)
    with pytest.raises(ValueError, match="index_weights"):
        run_program(store, s.session_id, cycles=1, replicates=MIN_REPLICATES)


def test_index_weights_on_a_single_trait_session_are_refused():
    store = SessionStore()
    s = found_population(store, generator="quickHaplo", seed=1, h2=0.4, **SMALL)
    with pytest.raises(ValueError, match="single trait"):
        run_program(
            store,
            s.session_id,
            cycles=1,
            replicates=MIN_REPLICATES,
            index_weights=[1.0, 1.0],
        )


def test_wrong_number_of_weights_is_refused():
    store = SessionStore()
    s = _two_trait(store)
    with pytest.raises(
        ValueError, match="one weight per trait|weights but the session"
    ):
        run_program(
            store,
            s.session_id,
            cycles=1,
            replicates=MIN_REPLICATES,
            index_weights=[1.0],
        )


def test_all_zero_weights_are_refused():
    store = SessionStore()
    s = _two_trait(store)
    with pytest.raises(ValueError, match="all zero"):
        run_program(
            store,
            s.session_id,
            cycles=1,
            replicates=MIN_REPLICATES,
            index_weights=[0.0, 0.0],
        )


def test_multi_trait_returns_per_trait_distributions_and_no_bare_gain():
    """A bare `genetic_gain` would have to mean trait 1."""
    store = SessionStore()
    s = _two_trait(store)
    out = run_program(
        store,
        s.session_id,
        cycles=2,
        replicates=MIN_REPLICATES,
        index_weights=[1.0, 1.0],
    )
    for cycle in out["cycles"]:
        assert "genetic_gain" not in cycle, (
            "a multi-trait cycle must not publish a single genetic_gain: it could "
            "only mean trait 1, read as though it were the whole objective"
        )
        assert len(cycle["traits"]) == 2
        for t in cycle["traits"]:
            assert {"mean", "sd", "ci_low", "ci_high", "n"} <= set(t["genetic_gain"])
            # A VARIANCE, not a covariance. varG returns a full covariance
            # matrix for several traits; handing it back whole would make
            # trait 2's "variance" the trait1-trait2 covariance, which is a
            # different quantity and can be negative.
            assert t["genetic_variance"]["mean"] > 0, (
                f"trait {t['trait']} reports a non-positive genetic variance "
                f"({t['genetic_variance']['mean']}) — this is probably a "
                "covariance read out of varG's matrix"
            )
    assert out["recipe"]["n_traits"] == 2
    assert out["recipe"]["index_weights"] == [1.0, 1.0]


def test_the_weights_actually_steer_which_trait_gains():
    """THE test. Selecting hard on trait 2 must beat selecting against it.

    If the index were ignored — AlphaSimR silently using trait=1 — both runs
    would be identical and this could not fail. The traits are negatively
    correlated so the two objectives genuinely pull apart.
    """
    store = SessionStore()
    s = _two_trait(store, correlation=-0.5, seed=3)

    favour_t2 = run_program(
        store,
        s.session_id,
        cycles=3,
        replicates=MIN_REPLICATES,
        index_weights=[0.0, 1.0],
        base_seed=500,
    )
    favour_t1 = run_program(
        store,
        s.session_id,
        cycles=3,
        replicates=MIN_REPLICATES,
        index_weights=[1.0, 0.0],
        base_seed=500,
    )

    t2_when_favoured = favour_t2["cycles"][-1]["traits"][1]["genetic_gain"]["mean"]
    t2_when_not = favour_t1["cycles"][-1]["traits"][1]["genetic_gain"]["mean"]
    assert t2_when_favoured > t2_when_not, (
        "weighting trait 2 did not raise trait 2's gain relative to weighting "
        f"trait 1 ({t2_when_favoured} vs {t2_when_not}) — the index is not "
        "reaching selectInd, or is being ignored"
    )

    # Same seeds, same founders: the ONLY difference is the weights.
    assert favour_t2["recipe"]["base_seed"] == favour_t1["recipe"]["base_seed"]


def test_compare_programs_refuses_multi_trait_rather_than_picking_a_trait():
    from breedsim_mcp.comparison import compare_programs

    store = SessionStore()
    s = _two_trait(store)
    with pytest.raises(ValueError, match="single paired verdict|ONE criterion"):
        compare_programs(store, s.session_id, cycles=1, replicates=MIN_REPLICATES)


# --------------------------------------------------------------------------
# MCP surface
# --------------------------------------------------------------------------


def test_multi_trait_over_the_real_mcp_layer():
    server = build_server()
    found = asyncio.run(
        server.call_tool(
            "found_population",
            {
                "generator": "quickHaplo",
                "seed": 1,
                "h2": [0.5, 0.5],
                "trait_correlation": 0.2,
                **SMALL,
            },
        )
    ).structured_content
    assert found["spec"]["n_traits"] == 2

    out = asyncio.run(
        server.call_tool(
            "run_program",
            {
                "session_id": found["session_id"],
                "cycles": 1,
                "replicates": MIN_REPLICATES,
                "index_weights": [1.0, 0.5],
            },
        )
    ).structured_content
    assert len(out["cycles"][0]["traits"]) == 2
    assert out["recipe"]["index_weights"] == [1.0, 0.5]
