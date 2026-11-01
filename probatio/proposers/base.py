"""Proposer interface. Proposers are UNTRUSTED: their output is only ever data
for a checker to certify."""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Feedback:
    candidate: dict[str, Any]
    valid: bool
    value: float | None
    reason: str = ""


@dataclass
class Context:
    best: list[tuple[float, dict[str, Any]]] = field(default_factory=list)
    recent_failures: list[Feedback] = field(default_factory=list)


class Proposer:
    name = "base"
    exhaustive = False

    def __init__(self, problem: dict[str, Any], space, rng: random.Random, **opts: Any):
        self.problem = problem
        self.space = space
        self.rng = rng
        self.opts = opts
        self.done = False
        self.cost_usd = 0.0
        self.meta: dict[str, Any] = {}

    def propose(self, ctx: Context, batch: int) -> list[dict[str, Any]]:
        raise NotImplementedError

    def observe(self, feedback: list[Feedback]) -> None:
        pass

    def provenance(self) -> dict[str, Any]:
        return {"proposer": self.name, **self.meta}
