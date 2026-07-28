"""Sessions over persisted R state.

A breeding programme is multi-generation stateful, so the founder population and
its simulation parameters live in the R session across calls. Python holds only
the metadata; the genotype matrix never crosses the boundary, because it is
n_individuals x n_markers and would blow up a model's context for no benefit.

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
        """Drop the evicted session's R objects, or they leak for the process's life."""
        r_eval(
            f'rm(list=intersect(c("{session.founders}", "{session.sim_param}"), ls(envir=.GlobalEnv)), envir=.GlobalEnv)'
        )

    def __len__(self) -> int:
        return len(self._sessions)
