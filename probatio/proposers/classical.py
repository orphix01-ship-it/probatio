"""Non-AI proposers: honest baselines that every AI run must beat."""
from __future__ import annotations

import math

from .base import Context, Feedback, Proposer


class RandomProposer(Proposer):
    name = "random"

    def propose(self, ctx: Context, batch: int):
        return [self.space.random(self.rng) for _ in range(batch)]


class MutationProposer(Proposer):
    """Simulated annealing with random restarts, driven only by checker feedback."""
    name = "mutation"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.current = None
        self.current_v = -math.inf
        hints = self.problem.get("search_hints", {})
        self.temp0 = float(self.opts.get("temp", hints.get("temp", 1.0)))
        self.temp = self.temp0
        self.cool = float(self.opts.get("cool", hints.get("cool", 0.999)))
        self.stale = 0
        self.restart_after = int(self.opts.get("restart_after", hints.get("restart_after", 2000)))
        self._pending: list = []

    def propose(self, ctx: Context, batch: int):
        if self.current is None:
            self.current = self.space.random(self.rng)
        return [self.space.mutate(self.current, self.rng) for _ in range(batch)]

    def observe(self, feedback: list[Feedback]):
        sense = self.problem["objective"]["sense"]
        shaped = getattr(self.space, "shaped", None)
        for fb in feedback:
            raw = fb.value
            if fb.valid and raw is not None and shaped and fb.score is not None:
                raw = shaped(fb.score, raw)
            v = raw if fb.valid and raw is not None else -1e9
            if sense == "minimize" and fb.valid and raw is not None:
                v = -raw
            delta = v - self.current_v
            if delta > 0 or (self.temp > 1e-9 and self.rng.random() < math.exp(delta / self.temp)):
                if delta > 0:
                    self.stale = 0
                self.current, self.current_v = fb.candidate, v
            self.stale += 1
        self.temp *= self.cool
        if self.stale > self.restart_after:
            self.current, self.current_v, self.stale = None, -math.inf, 0
            self.temp = self.temp0


class ExhaustiveProposer(Proposer):
    """Complete enumeration of a (symmetry-reduced) family.

    When it finishes, the best certified value is optimal *within the family*
    (and within the checker's distance cap). This is search evidence produced
    by open, untrusted code, recorded separately from checker certificates.
    """
    name = "exhaustive"
    exhaustive = True

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._it = self.space.enumerate()
        self.enumerated = 0

    def propose(self, ctx: Context, batch: int):
        out = []
        for _ in range(batch):
            try:
                out.append(next(self._it))
            except StopIteration:
                self.done = True
                break
        self.enumerated += len(out)
        self.meta["enumerated"] = self.enumerated
        return out

    def observe(self, feedback):
        if self.space.first_is_optimal and any(fb.valid for fb in feedback):
            self.done = True
