"""Sessions over persisted R state.

A breeding programme is multi-generation stateful, so the founder population and
its simulation parameters live in the R session across calls. Python holds only
the metadata, and **no genotype matrix is ever returned to the caller** — it is
n_individuals x n_markers and would blow up a model's context for no benefit.

That claim is about the TOOL boundary, and used to be worded as though it were
about the R/Python one, which is not true: `_founder_hash` pulls the whole
haplotype matrix into Python once per `found_population` — 200,000 values at the
default sizes, scaling as n_ind x n_chr x seg_sites x 2. It is hashed and
discarded rather than surfaced, so the caller is unaffected, but the cost is
real and the ceilings in `limits.py` are what keep it bounded.

Each session owns uniquely-prefixed R globals so two sessions cannot tread on each
other. AlphaSimR's own convention of a single global `SP` is exactly the collision
we are avoiding.
"""

import uuid
from collections import OrderedDict
from dataclasses import dataclass, field

from .engine import r_eval


class UnknownSessionError(Exception):
    """Raised when a session_id is not in the store."""


@dataclass
class Session:
    session_id: str
    r_prefix: str
    generator: str
    seed: int
    founder_hash: str
    reproducible: bool
    spec: dict
    reason: str | None = None
    cycles_run: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def founders(self) -> str:
        return f"{self.r_prefix}_founders"

    @property
    def sim_param(self) -> str:
        return f"{self.r_prefix}_SP"


class SessionStore:
    def __init__(self, max_sessions: int = 8) -> None:
        if max_sessions < 1:
            raise ValueError(f"max_sessions must be >= 1, got {max_sessions}")
        self._max = max_sessions
        self._sessions: OrderedDict[str, Session] = OrderedDict()

    def new_prefix(self) -> str:
        # R identifiers cannot contain '-', which uuid4 hex avoids anyway.
        return f".bs_{uuid.uuid4().hex[:10]}"

    def add(self, session: Session) -> Session:
        self._sessions[session.session_id] = session
        while len(self._sessions) > self._max:
            _, evicted = self._sessions.popitem(last=False)
            self._free_r_state(evicted)
        return session

    def get(self, session_id: str) -> Session:
        if session_id not in self._sessions:
            raise UnknownSessionError(
                f"Unknown session_id {session_id!r}. Sessions are in-memory and "
                f"capped at {self._max}; the oldest are evicted. Call "
                "found_population() again."
            )
        self._sessions.move_to_end(session_id)
        return self._sessions[session_id]

    def _free_r_state(self, session: Session) -> None:
        """Drop EVERY R object this session owns, by prefix.

        Two bugs lived in the previous version of this method, and both are worth
        naming because the guard looked correct while doing nothing at all.

        **`ls()` hides dot-prefixed names.** It omits anything starting with `.`
        unless `all.names=TRUE`, and `new_prefix()` deliberately starts with a dot.
        The old code intersected the target names against a bare `ls()`, so the
        intersection was ALWAYS empty and the `rm()` was a permanent no-op.
        Measured: after eviction, all five of the session's objects survived.

        **Enumerating names cannot track objects added later.** The old list named
        only `_founders` and `_SP`, so it would still have missed `_p0` (from
        `_founder_hash`) and `_pop`/`_pop_sel` (from `run_replicate`) — the whole
        populations, i.e. the big ones. Matching on the prefix removes the class
        rather than today's two members.

        The prefix is escaped because it begins with `.`, which is a regex
        metacharacter in R's `pattern`.
        """
        pattern = "^" + session.r_prefix.replace(".", "\\\\.")
        r_eval(
            f'rm(list=ls(envir=.GlobalEnv, all.names=TRUE, pattern="{pattern}"), '
            "envir=.GlobalEnv)"
        )

    def __len__(self) -> int:
        return len(self._sessions)
