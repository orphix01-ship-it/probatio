"""Exact checker for binary linear codes [n, k, d].

Candidate: a generator matrix given as k binary strings of length n. The checker
verifies the rows are linearly independent over GF(2) (so the code has dimension
exactly k), then computes the minimum distance d by enumerating all 2^k - 1
nonzero codewords and taking the minimum Hamming weight. It also reports A_d,
the number of codewords of minimum weight.

All 2^k codewords are built by repeated doubling with XOR (vectorised with
numpy on 64-bit words): exact integer arithmetic only.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from .base import Checker, Verdict

MAX_K = 24
MAX_N = 128


def gf2_rank(rows: list[int]) -> int:
    basis: dict[int, int] = {}
    for v in rows:
        while v:
            p = v.bit_length() - 1
            if p in basis:
                v ^= basis[p]
            else:
                basis[p] = v
                break
    return len(basis)


def _split(v: int) -> tuple[int, int]:
    return v & ((1 << 64) - 1), v >> 64


def min_distance(rows: list[int], n: int) -> tuple[int, int, list[int]]:
    """Return (d, A_d, weight_distribution) by exhaustive enumeration."""
    k = len(rows)
    lo = np.array([_split(r)[0] for r in rows], dtype=np.uint64)
    hi = np.array([_split(r)[1] for r in rows], dtype=np.uint64)
    # Codeword for message m is XOR of rows whose bit is set in m. Build all 2^k
    # codewords by doubling: words(t+1) = words(t) ++ (words(t) XOR row_t).
    wlo = np.zeros(1, dtype=np.uint64)
    whi = np.zeros(1, dtype=np.uint64)
    for t in range(k):
        wlo = np.concatenate([wlo, wlo ^ lo[t]])
        whi = np.concatenate([whi, whi ^ hi[t]])
    weights = np.bitwise_count(wlo).astype(np.int64) + np.bitwise_count(whi).astype(np.int64)
    weights = weights[1:]  # drop the zero codeword
    dist = np.bincount(weights, minlength=n + 1).tolist()
    d = int(weights.min())
    return d, int(dist[d]), dist


class LinearCodeChecker(Checker):
    name = "linear_code"
    version = "0.1.0"
    trust = "T2"

    def check(self, problem: dict[str, Any], candidate: dict[str, Any]) -> Verdict:
        params = problem.get("params", {})
        rows_s = candidate.get("generator")
        if not isinstance(rows_s, list) or not rows_s or not all(isinstance(r, str) for r in rows_s):
            return self._verdict(False, reason="candidate.generator must be a non-empty list of bit strings")
        n = len(rows_s[0])
        k = len(rows_s)
        if any(len(r) != n or set(r) - {"0", "1"} for r in rows_s):
            return self._verdict(False, reason="rows must be equal-length strings of 0 and 1")
        if n > MAX_N or k > MAX_K:
            return self._verdict(False, reason=f"supports n <= {MAX_N}, k <= {MAX_K}")
        if params.get("n") not in (None, n) or params.get("k") not in (None, k):
            return self._verdict(False, reason=f"code is [{n},{k}], problem requires "
                                               f"[{params.get('n')},{params.get('k')}]")
        rows = [int(r[::-1], 2) for r in rows_s]  # bit i = coordinate i
        rank = gf2_rank(rows)
        if rank != k:
            return self._verdict(False, reason=f"rows are dependent: rank {rank} < k = {k}")
        d, ad, dist = min_distance(rows, n)
        log = [f"generator matrix {k} x {n}; GF(2) rank = {k}, so dimension is exactly {k}",
               f"enumerated all {2 ** k - 1} nonzero codewords",
               f"minimum weight {d}, attained by {ad} codewords; this is a [{n},{k},{d}] code"]
        return self._verdict(True, score={"n": n, "k": k, "d": d, "A_d": ad}, transcript=log)
