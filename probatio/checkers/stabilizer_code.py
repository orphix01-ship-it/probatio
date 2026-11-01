"""Exact checker for quantum stabilizer codes.

A candidate is a list of Pauli strings over {I, X, Y, Z}, all of length n. The
checker verifies, using exact GF(2) arithmetic only:

1. every pair of generators commutes (symplectic inner product is zero);
2. k = n - rank, where rank is computed over GF(2) in the binary symplectic
   representation;
3. the distance d = minimum weight of a Pauli operator that commutes with every
   generator but is not itself in the stabilizer group (for k = 0, the minimum
   weight of a non-identity stabilizer element). Found by exhaustive search in
   order of increasing weight, so the first hit is the exact minimum.

Signs/phases are ignored: for any independent commuting set of Pauli operators
there is a choice of signs giving a valid stabilizer group, and n, k and d do
not depend on that choice.
"""
from __future__ import annotations

from itertools import combinations, product
from typing import Any

from .base import Checker, Verdict

_BITS = {"I": (0, 0), "X": (1, 0), "Z": (0, 1), "Y": (1, 1)}
MAX_N = 63


def pauli_to_xz(p: str) -> tuple[int, int]:
    """Return (x_mask, z_mask); qubit i maps to bit i."""
    x = z = 0
    for i, c in enumerate(p):
        bx, bz = _BITS[c]
        x |= bx << i
        z |= bz << i
    return x, z


def symplectic_product(a: tuple[int, int], b: tuple[int, int]) -> int:
    """0 if the Paulis commute, 1 if they anticommute."""
    return (((a[0] & b[1]) ^ (a[1] & b[0])).bit_count()) & 1


def gf2_basis(vectors: list[int]) -> dict[int, int]:
    """Row-reduce integer bit-vectors over GF(2). Returns {pivot_bit: vector}."""
    basis: dict[int, int] = {}
    for v in vectors:
        v = reduce_vector(v, basis)
        if v:
            pivot = v.bit_length() - 1
            # keep basis fully reduced on pivots for a canonical span test
            for p, b in list(basis.items()):
                if (b >> pivot) & 1:
                    basis[p] = b ^ v
            basis[pivot] = v
    return basis


def reduce_vector(v: int, basis: dict[int, int]) -> int:
    while v:
        pivot = v.bit_length() - 1
        if pivot in basis:
            v ^= basis[pivot]
        else:
            return v
    return 0


def cyclic_shifts(seed: str) -> list[str]:
    n = len(seed)
    return [seed[n - i:] + seed[: n - i] for i in range(n)]


def analyse_code(gens: list[str], max_weight: int | None = None) -> dict[str, Any]:
    """Compute n, k, d exactly. Raises ValueError on malformed input."""
    if not gens:
        raise ValueError("no generators")
    n = len(gens[0])
    if n == 0 or n > MAX_N:
        raise ValueError(f"n must be in 1..{MAX_N}")
    for g in gens:
        if len(g) != n:
            raise ValueError("generators have different lengths")
        if any(c not in _BITS for c in g):
            raise ValueError(f"invalid character in generator {g!r}")

    xz = [pauli_to_xz(g) for g in gens]
    for i in range(len(xz)):
        for j in range(i + 1, len(xz)):
            if symplectic_product(xz[i], xz[j]):
                raise ValueError(f"generators {i} and {j} anticommute")

    basis = gf2_basis([(x << n) | z for x, z in xz])
    rank = len(basis)
    k = n - rank
    if k < 0:  # impossible for a commuting set; defensive
        raise ValueError("rank exceeds n")
    stab = [((v >> n), v & ((1 << n) - 1)) for v in basis.values()]

    # Syndrome contribution of a single-qubit Pauli on qubit q: bit j set iff it
    # anticommutes with independent generator j. Syndromes add by XOR.
    singles = [(1, 0), (0, 1), (1, 1)]  # X, Z, Y
    syn = [[0, 0, 0] for _ in range(n)]
    for q in range(n):
        for t, (bx, bz) in enumerate(singles):
            s = 0
            for j, (gx, gz) in enumerate(stab):
                if ((bx & (gz >> q)) ^ (bz & (gx >> q))) & 1:
                    s |= 1 << j
            syn[q][t] = s

    cap = n if max_weight is None else min(max_weight, n)
    examined = 0
    for w in range(1, cap + 1):
        for support in combinations(range(n), w):
            for types in product(range(3), repeat=w):
                examined += 1
                s = 0
                for q, t in zip(support, types):
                    s ^= syn[q][t]
                if s:
                    continue
                if k == 0:
                    return _result(n, k, w, None, support, types, examined)
                x = z = 0
                for q, t in zip(support, types):
                    bx, bz = singles[t]
                    x |= bx << q
                    z |= bz << q
                if reduce_vector((x << n) | z, basis):  # not in stabilizer -> logical
                    return _result(n, k, w, None, support, types, examined)
    return _result(n, k, None, cap + 1, None, None, examined)


def _result(n, k, d, d_lower, support, types, examined) -> dict[str, Any]:
    witness = None
    if support is not None:
        chars = ["I"] * n
        for q, t in zip(support, types):
            chars[q] = "XZY"[t]
        witness = "".join(chars)
    return {"n": n, "k": k, "d": d, "d_lower": d_lower,
            "min_weight_witness": witness, "operators_examined": examined}


class StabilizerCodeChecker(Checker):
    name = "stabilizer_code"
    version = "0.1.0"
    trust = "T2"

    def check(self, problem: dict[str, Any], candidate: dict[str, Any]) -> Verdict:
        params = problem.get("params", {})
        log: list[str] = []
        gens = candidate.get("generators")
        if not isinstance(gens, list) or not all(isinstance(g, str) for g in gens):
            return self._verdict(False, reason="candidate.generators must be a list of strings")

        if params.get("family") == "cyclic":
            seed = candidate.get("seed")
            if not isinstance(seed, str) or cyclic_shifts(seed) != gens:
                return self._verdict(False, reason="generators are not the cyclic shifts of seed")
            log.append("family: generators are exactly the n cyclic shifts of the seed")

        try:
            res = analyse_code(gens, params.get("max_weight"))
        except ValueError as exc:
            return self._verdict(False, reason=str(exc))

        log.append(f"all {len(gens)} generators pairwise commute")
        log.append(f"GF(2) rank = {res['n'] - res['k']}, so k = {res['k']}")
        if res["d"] is not None:
            log.append(f"exhaustive search: no logical operator of weight < {res['d']}; "
                       f"witness of weight {res['d']}: {res['min_weight_witness']}")
        else:
            log.append(f"no logical operator up to weight {res['d_lower'] - 1}; d >= {res['d_lower']}")

        if "n" in params and res["n"] != params["n"]:
            return self._verdict(False, reason=f"n={res['n']} but problem requires n={params['n']}",
                                 score=res, transcript=log)
        if "k" in params and res["k"] != params["k"]:
            return self._verdict(False, reason=f"k={res['k']} but problem requires k={params['k']}",
                                 score=res, transcript=log)
        return self._verdict(True, score=res, transcript=log)
