"""A result should say what produced it and what scale it is on.

Both facts existed before this: engine versions via `list_methods`, and the trait
scale implicitly in whatever was passed to `found_population`. Neither travelled
with the result. A run written to disk, forwarded to another agent, or compared
against one from last month could not answer "which AlphaSimR was this?" or
"gain of 1.4 in what units?" — so the numbers were not attributable.
"""

import asyncio

from breedsim_mcp.server import build_server

FOUND = {
    "generator": "quickHaplo",
    "seed": 3,
    "n_ind": 20,
    "n_chr": 2,
    "seg_sites": 20,
    "n_qtl_per_chr": 3,
}


def _call(srv, name, args):
    return asyncio.run(srv.call_tool(name, args)).structured_content


def _run(run_extra=None, **found_extra):
    srv = build_server()
    s = _call(srv, "found_population", {**FOUND, **found_extra})
    return _call(
        srv,
        "run_program",
        {
            "session_id": s["session_id"],
            "cycles": 1,
            "replicates": 5,
            "n_select": 5,
            **(run_extra or {}),
        },
    )


def test_the_result_carries_the_engine_that_produced_it():
    engine = _run(h2=0.5)["recipe"]["engine"]
    assert engine["alphasimr_version"], "no AlphaSimR version on the result"
    assert engine["r_version"], "no R version on the result"
    assert engine["rpy2_version"], "no rpy2 version on the result"
    # Must match what the introspection tool reports; two sources that can
    # disagree are worse than one.
    methods = _call(build_server(), "list_methods", {})
    assert engine["alphasimr_version"] == methods["alphasimr_version"]
    assert engine["rpy2_version"] == methods["rpy2_version"]


def test_single_trait_gain_is_labelled_in_founder_genetic_sd():
    """addTraitA is called without var, so AlphaSimR's default variance of 1
    applies and gain is in founder additive genetic SD."""
    scale = _run(h2=0.5)["recipe"]["gain_scale"]
    assert "founder additive genetic SD" in scale


def test_multi_trait_gain_is_NOT_labelled_with_the_single_trait_scale():
    """The control that keeps the label honest.

    A multi-trait session sets its own variances, so the single-trait label
    would be a false statement about the units. If `gain_scale` were a constant
    string, this is the test that catches it.
    """
    out = _run(
        run_extra={"index_weights": [1.0, 1.0]}, h2=[0.5, 0.3], trait_correlation=0.2
    )
    scale = out["recipe"]["gain_scale"]
    assert "founder additive genetic SD" not in scale
    assert "caller-supplied variances" in scale
