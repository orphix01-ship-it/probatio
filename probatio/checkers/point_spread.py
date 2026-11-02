"""Exact checker for spreading points in the unit square (equivalently, packing
equal circles in a square).

Candidate: n points with coordinates given as exact rationals, written as
decimal strings ("0.25") or fractions ("1/4"). The checker parses them with
exact rational arithmetic, confirms every point lies in [0,1]^2, and computes
the minimum pairwise distance squared exactly. The reported min_distance is the
square root of that exact value, rounded for display; comparisons against known
records use the exact squared value.
"""
from __future__ import annotations

import math
from fractions import Fraction
from typing import Any

from .base import Checker, Verdict

MAX_DIGITS = 40


def parse_exact(s: Any) -> Fraction:
    if not isinstance(s, str) or len(s) > MAX_DIGITS * 2:
        raise ValueError(f"coordinate {s!r} must be a string")
    return Fraction(s.strip())


class PointSpreadChecker(Checker):
    name = "point_spread"
    version = "0.1.0"
    trust = "T2"

    def check(self, problem: dict[str, Any], candidate: dict[str, Any]) -> Verdict:
        want = problem.get("params", {}).get("n")
        pts = candidate.get("points")
        if not isinstance(pts, list) or not all(isinstance(p, list) and len(p) == 2 for p in pts):
            return self._verdict(False, reason="candidate.points must be a list of [x, y] pairs")
        if want is not None and len(pts) != want:
            return self._verdict(False, reason=f"{len(pts)} points given, problem requires {want}")
        try:
            P = [(parse_exact(x), parse_exact(y)) for x, y in pts]
        except (ValueError, ZeroDivisionError) as exc:
            return self._verdict(False, reason=f"bad coordinate: {exc}")
        for i, (x, y) in enumerate(P):
            if not (0 <= x <= 1 and 0 <= y <= 1):
                return self._verdict(False, reason=f"point {i} lies outside the unit square")
        best = None
        pair = (0, 0)
        for i in range(len(P)):
            for j in range(i + 1, len(P)):
                dx, dy = P[i][0] - P[j][0], P[i][1] - P[j][1]
                d2 = dx * dx + dy * dy
                if best is None or d2 < best:
                    best, pair = d2, (i, j)
        if best is None or best == 0:
            return self._verdict(False, reason="two points coincide")
        md = math.sqrt(best.numerator / best.denominator)
        log = [f"{len(P)} points, all inside [0,1]^2 (exact rational check)",
               f"minimum pairwise distance squared = {best} exactly (points {pair[0]} and {pair[1]})",
               f"minimum distance = {md:.9f}; equal circles of radius {md / (2 * (1 + md)):.9f} "
               "fit in a unit square"]
        return self._verdict(True, score={"n": len(P), "min_distance": round(md, 12),
                                          "min_dist_sq": str(best)}, transcript=log)
