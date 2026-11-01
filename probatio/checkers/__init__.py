"""Checker registry."""
from __future__ import annotations

from .base import Checker, Verdict
from .golomb_ruler import GolombRulerChecker
from .lean_proof import LeanProofChecker
from .stabilizer_code import StabilizerCodeChecker

CHECKERS: dict[str, Checker] = {
    c.name: c for c in (StabilizerCodeChecker(), GolombRulerChecker(), LeanProofChecker())
}


def get_checker(name: str) -> Checker:
    if name not in CHECKERS:
        raise KeyError(f"unknown checker {name!r}; known: {sorted(CHECKERS)}")
    return CHECKERS[name]


__all__ = ["Checker", "Verdict", "CHECKERS", "get_checker"]
