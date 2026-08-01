"""Selecting everyone is not a breeding programme, and must not read like one.

`n_select == n_ind` selects the whole population, so the selection differential
is zero and the expected genetic gain is zero BY CONSTRUCTION. The run is still
allowed — a drift-only arm is a legitimate control — but reporting it without
saying so invites the caller to read drift as response.

The audit that produced this file measured a run at n_select == n_ind returning
mean -0.097 with a CI spanning zero, carrying exactly one advisory:
`replicates_too_few`, telling the caller to re-run with more replicates. No
number of replicates can move a structurally-zero effect off zero, so that
advice was not merely unhelpful, it pointed the wrong way.
"""

import pytest

from breedsim_mcp.diagnostics import no_selection_warning, replicates_too_few_warning

# A mean near zero with an interval spanning it — the shape a drift-only run
# actually produces, taken from the audit run rather than invented.
DRIFT_GAIN = {"mean": -0.097, "ci_low": -0.298, "ci_high": 0.103, "n": 5}


def test_selecting_everyone_is_flagged():
    w = no_selection_warning(n_select=30, n_ind=30)
    assert w is not None, "selecting the whole population raised no advisory"
    assert w.code == "no_selection"
    # The message has to carry WHY more replicates will not help, because the
    # advisory it replaces said the opposite.
    assert "zero by construction" in w.message
    assert "more replicates will not change" in w.message


def test_real_selection_is_not_flagged():
    """Positive control. A guard that fires on everything is not a guard."""
    assert no_selection_warning(n_select=5, n_ind=30) is None
    assert no_selection_warning(n_select=29, n_ind=30) is None


def test_the_advisory_it_replaces_would_have_misdiagnosed_this_run():
    """Pins the reason the fix exists, not just its effect.

    On the very gain summary a no-selection run produces, `replicates_too_few`
    fires and recommends more replicates. That is the misdiagnosis. This test
    documents it deliberately: if that advisory is ever changed to handle the
    zero-effect case itself, this test fails and the suppression in server.py
    can be removed rather than quietly kept forever.
    """
    misdiagnosis = replicates_too_few_warning(DRIFT_GAIN)
    assert misdiagnosis is not None
    assert "more replicates" in misdiagnosis.message.lower()


@pytest.mark.parametrize("n_select,n_ind,expected", [(30, 30, True), (31, 30, True)])
def test_at_or_above_population_size_counts_as_no_selection(n_select, n_ind, expected):
    """`>` is unreachable through the tool (program.py rejects it), but the
    predicate is `>=` so a future caller of this function cannot slip past it."""
    assert (no_selection_warning(n_select, n_ind) is not None) is expected


def _run(n_select: int, h2: float = 0.5) -> dict:
    """Drive the real tools; the advisory set is assembled in server.py, not below it."""
    import asyncio

    from breedsim_mcp.server import build_server

    srv = build_server()

    def call(name, args):
        return asyncio.run(srv.call_tool(name, args)).structured_content

    s = call(
        "found_population",
        {
            "generator": "quickHaplo",
            "seed": 3,
            "n_ind": 30,
            "n_chr": 2,
            "seg_sites": 30,
            "n_qtl_per_chr": 3,
            "h2": h2,
        },
    )
    return call(
        "run_program",
        {
            "session_id": s["session_id"],
            "cycles": 1,
            "replicates": 5,
            "n_select": n_select,
        },
    )


def test_a_drift_only_run_says_so_and_does_not_ask_for_replicates():
    """The end-to-end shape. Codes are read off the real tool result."""
    codes = {w["code"] for w in _run(n_select=30).get("warnings", [])}
    assert "no_selection" in codes, (
        f"a run that selected the whole population did not say so; got {codes}"
    )
    assert "replicates_too_few" not in codes, (
        "still recommending more replicates for an effect that is zero by "
        f"construction; got {codes}"
    )


def test_a_selecting_run_still_gets_the_replicate_advice_when_it_is_noisy():
    """Positive control for the suppression.

    Withholding `replicates_too_few` must be conditional on there being no
    selection. If the suppression were unconditional this file would still pass
    while the advisory had been silently disabled for every run.

    h2 is low deliberately. At h2=0.5 this configuration selects cleanly enough
    that the interval is TIGHT and the advisory correctly stays silent — which
    is a fine outcome but proves nothing about the suppression. A barely
    heritable trait is what makes the run genuinely underpowered, so the
    advisory has something real to fire on.
    """
    codes = {w["code"] for w in _run(n_select=5, h2=0.05).get("warnings", [])}
    assert "no_selection" not in codes
    assert "replicates_too_few" in codes, (
        f"the replicate advisory no longer fires on a real, noisy run; got {codes}"
    )
