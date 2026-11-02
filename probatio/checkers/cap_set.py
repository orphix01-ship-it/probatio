"""Exact checker for cap sets in F_3^n.

A cap set is a set of points in (Z/3Z)^n with no three distinct points on a line.
Three distinct points a, b, c are collinear exactly when a + b + c = 0 (mod 3),
so for every pair a != b the third point on their line is c = -(a + b) mod 3,
and a cap set must never contain it.
"""
from __future__ import annotations

from typing import Any

from .base import Checker, Verdict


def third_point(a: tuple[int, ...], b: tuple[int, ...]) -> tuple[int, ...]:
    return tuple((-(x + y)) % 3 for x, y in zip(a, b))


class CapSetChecker(Checker):
    name = "cap_set"
    version = "0.1.0"
    trust = "T2"

    def check(self, problem: dict[str, Any], candidate: dict[str, Any]) -> Verdict:
        n = problem.get("params", {}).get("n")
        pts = candidate.get("points")
        if not isinstance(pts, list) or not all(isinstance(p, str) for p in pts):
            return self._verdict(False, reason="candidate.points must be a list of strings over 0,1,2")
        if not pts:
            return self._verdict(False, reason="empty set")
        for p in pts:
            if (n is not None and len(p) != n) or any(c not in "012" for c in p):
                return self._verdict(False, reason=f"point {p!r} is not a length-{n} string over 0,1,2")
        tuples = [tuple(int(c) for c in p) for p in pts]
        s = set(tuples)
        if len(s) != len(tuples):
            return self._verdict(False, reason="duplicate points")
        for i in range(len(tuples)):
            for j in range(i + 1, len(tuples)):
                c = third_point(tuples[i], tuples[j])
                if c in s:
                    return self._verdict(False, reason=f"{pts[i]}, {pts[j]} and {''.join(map(str, c))} "
                                                       "lie on a line")
        pairs = len(tuples) * (len(tuples) - 1) // 2
        log = [f"{len(tuples)} distinct points in F_3^{n}",
               f"checked all {pairs} pairs: the third point on each line is never in the set",
               f"cap set of size {len(tuples)}"]
        return self._verdict(True, score={"n": n, "size": len(tuples)}, transcript=log)
