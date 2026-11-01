"""Exact checker for Golomb rulers: integer marks with all pairwise differences distinct."""
from __future__ import annotations

from typing import Any

from .base import Checker, Verdict


class GolombRulerChecker(Checker):
    name = "golomb_ruler"
    version = "0.1.0"
    trust = "T2"

    def check(self, problem: dict[str, Any], candidate: dict[str, Any]) -> Verdict:
        marks = candidate.get("marks")
        if not isinstance(marks, list) or not all(isinstance(m, int) and not isinstance(m, bool)
                                                  for m in marks):
            return self._verdict(False, reason="candidate.marks must be a list of integers")
        want = problem.get("params", {}).get("marks")
        if want is not None and len(marks) != want:
            return self._verdict(False, reason=f"{len(marks)} marks given, problem requires {want}")
        if len(set(marks)) != len(marks):
            return self._verdict(False, reason="duplicate marks")
        m = sorted(marks)
        if m and m[0] != 0:
            return self._verdict(False, reason="ruler must start at 0")
        seen: dict[int, tuple[int, int]] = {}
        for i in range(len(m)):
            for j in range(i + 1, len(m)):
                diff = m[j] - m[i]
                if diff in seen:
                    a, b = seen[diff]
                    return self._verdict(False, reason=f"difference {diff} repeated: "
                                         f"{b}-{a} and {m[j]}-{m[i]}")
                seen[diff] = (m[i], m[j])
        length = m[-1] if m else 0
        log = [f"{len(m)} marks, {len(seen)} pairwise differences, all distinct",
               f"length = {length}"]
        return self._verdict(True, score={"marks": len(m), "length": length}, transcript=log)
