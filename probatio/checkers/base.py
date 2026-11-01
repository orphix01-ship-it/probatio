"""Checker interface. Checkers are the trusted computing base."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Verdict:
    valid: bool
    score: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    transcript: list[str] = field(default_factory=list)
    checker: str = ""
    trust: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "score": self.score,
            "reason": self.reason,
            "transcript": self.transcript,
            "checker": self.checker,
            "trust": self.trust,
        }


class Checker:
    """A checker certifies a candidate against a problem.

    Implementations must be deterministic, must recompute everything from the
    candidate itself, and must never trust fields the proposer supplied as
    results (e.g. a claimed distance).
    """

    name = "base"
    version = "0.0.0"
    trust = "T2"

    @property
    def ident(self) -> str:
        return f"{self.name}@{self.version}"

    def check(self, problem: dict[str, Any], candidate: dict[str, Any]) -> Verdict:
        raise NotImplementedError

    def _verdict(self, valid: bool, **kw: Any) -> Verdict:
        return Verdict(valid=valid, checker=self.ident, trust=self.trust, **kw)
