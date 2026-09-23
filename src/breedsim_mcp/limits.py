"""Upper bounds on caller-supplied sizes.

0.1.0 validated only floors: every size parameter had a `< 1` or
`< MIN_REPLICATES` check and no ceiling at all. That is a availability problem
rather than a correctness one, and it is specific to how this server is built.

R is a SINGLE interpreter and the MCP tools are synchronous, so calls serialise.
One oversized request therefore blocks every other request for as long as it
runs — there is no second worker to take the next call. And the caller here is a
language model, which will cheerfully ask for `replicates=10000` because the
number sounds thorough. That is an accident, not an attack, and the fix is a cap
with an error that explains the trade rather than a silent clamp.

The ceilings are deliberately generous: they are set where a call stops being
slow and starts being an outage, not where it stops being cheap.
"""

# Chosen so that a single call stays in the seconds-to-low-minutes range on the
# reference machine. Raise them if you own the process and want to wait.
LIMITS: dict[str, int] = {
    "n_ind": 5_000,
    "n_chr": 40,
    "seg_sites": 5_000,
    "n_qtl_per_chr": 1_000,
    # Markers are pulled into Python as a dense n_ind x (n_snp_per_chr * n_chr)
    # matrix for the LD measurement, and RRBLUP solves over the same width once
    # per cycle per replicate, so this ceiling is lower than the others.
    "n_snp_per_chr": 1_000,
    "cycles": 50,
    "replicates": 200,
    "n_select": 5_000,
    "n_cross": 10_000,
}


class LimitExceededError(ValueError):
    """A size parameter is above what this server will run in one call."""


def check_upper(name: str, value: int) -> None:
    """Refuse a value above its ceiling, saying why and what to do instead."""
    cap = LIMITS[name]
    if value <= cap:
        return
    raise LimitExceededError(
        f"{name}={value:,} exceeds the maximum of {cap:,}. R runs as a single "
        "interpreter here and tool calls are serialised, so one oversized call "
        "blocks every other call until it finishes — there is no second worker. "
        "Either lower the value, or run the large job outside this server with "
        "AlphaSimR directly."
    )


def check_all(**values: int | None) -> None:
    """Bounds-check several parameters at once; None means 'not supplied'."""
    for name, value in values.items():
        if value is not None:
            check_upper(name, value)


# R's integer range. set.seed() coerces to integer, and -2**31 is NA_integer_,
# so the valid seeds are symmetric: |seed| <= 2**31 - 1. Measured on R 4.3.3:
# set.seed(2147483648) and set.seed(-2147483648) both stop with "supplied seed
# is not a valid integer".
R_INT_MAX = 2**31 - 1


def check_seed_range(name: str, first: int, count: int = 1) -> None:
    """Refuse a seed, or a run of `count` consecutive seeds, outside R's range.

    run_program and compare_programs seed replicate i with `base_seed + i`, so it
    is the whole run of seeds that has to fit, not only the first one.
    """
    last = first + count - 1
    if -R_INT_MAX <= first and last <= R_INT_MAX:
        return
    span = (
        f"{name}={first:,}"
        if count == 1
        else f"{name}={first:,} with {count} replicates (seeds {first:,}..{last:,})"
    )
    raise ValueError(
        f"{span} is outside the range R accepts for a seed, "
        f"-{R_INT_MAX:,} to {R_INT_MAX:,}. set.seed() coerces its argument to "
        "an R integer, and anything outside that range is not one."
    )
