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

import os

# Per-axis ceilings, each generous on its own. They do NOT bound a founding by
# themselves: its cost grows with n_ind x n_chr x seg_sites, so a founding is
# also checked against FOUNDING_MEMORY_MIB below. Raise them if you own the
# process and want to wait.
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


# The per-axis ceilings above do not bound a founding's cost, because the cost
# scales with their PRODUCT. `_founder_hash` pulls every haplotype value into
# Python (n_ind x n_chr x seg_sites x 2), and peak memory grows with that count.
# Measured on found_population (peak RSS growth per haplotype value, 2026-11-10):
# 38 B at 400x10x400, 36 B at 500x10x500, 29 B at 1000x10x1000 (0.55 GiB,
# 142 s). At the ceilings (5000 x 40 x 5000) that extrapolates to 55-71 GiB,
# more than the reference machine has. 40 B rounds up from the largest
# measurement, so the estimate errs toward refusing.
BYTES_PER_HAPLOTYPE_VALUE = 40

# Environment variable that sets the founding memory budget, in MiB. The server
# already takes its configuration from the environment (OMP_NUM_THREADS,
# R_LIBS_USER), which an MCP client sets in its `env` block.
FOUNDING_MEMORY_ENV = "BREEDSIM_FOUNDING_MEMORY_MIB"

# 1 GiB admits about 27 million haplotype values: the largest measured founding
# (1000 x 10 x 1000, 20 million values, 142 s) fits with a third to spare, and
# the call stays in the low minutes, which is what the per-axis ceilings were
# meant to promise. Raise it if you own the machine and want to wait.
DEFAULT_FOUNDING_MEMORY_MIB = 1024


def founding_memory_budget_mib(environ: dict[str, str] | None = None) -> int:
    """The founding memory budget in MiB, from the environment or the default.

    A value that is set but is not a positive whole number is refused, not
    replaced by the default: a typo in a client's config should stop the
    server, not quietly run it with a limit the owner did not choose.
    """
    env = os.environ if environ is None else environ
    raw = env.get(FOUNDING_MEMORY_ENV)
    if raw is None or raw.strip() == "":
        return DEFAULT_FOUNDING_MEMORY_MIB
    refusal = (
        f"{FOUNDING_MEMORY_ENV}={raw!r} is not a positive whole number of MiB. "
        f"Unset it for the default of {DEFAULT_FOUNDING_MEMORY_MIB}, or set it "
        "to the budget you want, e.g. 4096."
    )
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise ValueError(refusal) from exc
    if value < 1:
        raise ValueError(refusal)
    return value


# Read once, at import, like the thread pin: it is a property of the process.
FOUNDING_MEMORY_MIB = founding_memory_budget_mib()


def haplotype_values(n_ind: int, n_chr: int, seg_sites: int) -> int:
    """How many haplotype values a founding holds: two copies of each site."""
    return n_ind * n_chr * seg_sites * 2


def founding_memory_mib(n_ind: int, n_chr: int, seg_sites: int) -> float:
    """Estimated peak memory of a founding, in MiB."""
    values = haplotype_values(n_ind, n_chr, seg_sites)
    return values * BYTES_PER_HAPLOTYPE_VALUE / 2**20


def check_founding_memory(
    n_ind: int, n_chr: int, seg_sites: int, budget_mib: int | None = None
) -> None:
    """Refuse a founding whose estimated memory exceeds the budget, before R runs."""
    budget = FOUNDING_MEMORY_MIB if budget_mib is None else budget_mib
    estimate = founding_memory_mib(n_ind, n_chr, seg_sites)
    if estimate <= budget:
        return
    values = haplotype_values(n_ind, n_chr, seg_sites)
    raise LimitExceededError(
        f"n_ind={n_ind:,} x n_chr={n_chr:,} x seg_sites={seg_sites:,} is "
        f"{values:,} haplotype values; at about {BYTES_PER_HAPLOTYPE_VALUE} bytes "
        f"each that is an estimated {estimate:,.0f} MiB, over this server's "
        f"founding budget of {budget:,} MiB. Each size is within its own ceiling, "
        "but memory grows with their product. Lower one of the three, or, if you "
        f"run this server, raise the budget with {FOUNDING_MEMORY_ENV}."
    )


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
