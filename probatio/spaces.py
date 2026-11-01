"""Search spaces: how to sample, mutate, enumerate and normalise candidates.

Spaces belong to the untrusted side. Nothing here affects a verdict; the
checker recomputes everything. ``normalize`` only fills derived fields (e.g.
cyclic shifts from a seed) so proposers, including LLMs, can submit compact
candidates — the checker then confirms those fields are consistent.
"""
from __future__ import annotations

import random
from itertools import product
from typing import Any, Iterator

from .checkers.stabilizer_code import cyclic_shifts

PAULI = "IXYZ"


class Space:
    family = "generic"

    def __init__(self, problem: dict[str, Any]):
        self.problem = problem
        self.params = problem["params"]

    def random(self, rng: random.Random) -> dict[str, Any]: raise NotImplementedError
    def mutate(self, c: dict[str, Any], rng: random.Random) -> dict[str, Any]: raise NotImplementedError
    def enumerate(self) -> Iterator[dict[str, Any]]: raise NotImplementedError
    def normalize(self, c: dict[str, Any]) -> dict[str, Any]: return c
    def canonical(self, c: dict[str, Any]) -> str: raise NotImplementedError

    # Exhaustive enumerations may stop early once an optimum is certain
    first_is_optimal = False


class CyclicCodeSpace(Space):
    """Cyclic stabilizer codes: generators are the n cyclic shifts of one seed."""
    family = "cyclic"

    def __init__(self, problem):
        super().__init__(problem)
        self.n = self.params["n"]

    def _cand(self, seed: str) -> dict[str, Any]:
        return {"seed": seed, "generators": cyclic_shifts(seed)}

    def normalize(self, c):
        seed = c.get("seed")
        if isinstance(seed, str):
            return self._cand(seed.strip().upper())
        return c

    def random(self, rng):
        while True:
            s = "".join(rng.choice(PAULI) for _ in range(self.n))
            if s.strip("I"):
                return self._cand(s)

    def mutate(self, c, rng):
        s = list(c["seed"])
        for _ in range(rng.choice((1, 1, 1, 2, 3))):
            i = rng.randrange(self.n)
            s[i] = rng.choice([p for p in PAULI if p != s[i]])
        if not "".join(s).strip("I"):
            return self.random(rng)
        return self._cand("".join(s))

    def self_commuting(self, seed: str) -> bool:
        """Cheap pre-filter: does the seed commute with all of its shifts?"""
        n = self.n
        x = z = 0
        for i, ch in enumerate(seed):
            if ch in "XY":
                x |= 1 << i
            if ch in "ZY":
                z |= 1 << i
        mask = (1 << n) - 1
        for r in range(1, n // 2 + 1):
            xr = ((x << r) | (x >> (n - r))) & mask
            zr = ((z << r) | (z >> (n - r))) & mask
            if ((x & zr) ^ (z & xr)).bit_count() & 1:
                return False
        return True

    def enumerate(self):
        """All seeds up to rotation and global X/Y/Z relabelling (a Clifford
        symmetry preserving n, k, d): first qubit is X; seeds are self-commuting."""
        n = self.n
        seen: set[str] = set()
        for tail in product(PAULI, repeat=n - 1):
            seed = "X" + "".join(tail)
            if not self.self_commuting(seed):
                continue
            key = self._canon_seed(seed)
            if key in seen:
                continue
            seen.add(key)
            yield self._cand(seed)

    @staticmethod
    def _relabel(seed: str, perm: dict[str, str]) -> str:
        return "".join(perm[c] for c in seed)

    def _canon_seed(self, seed: str) -> str:
        n = len(seed)
        best = None
        for a, b, c in (("X", "Y", "Z"), ("X", "Z", "Y"), ("Y", "X", "Z"),
                        ("Y", "Z", "X"), ("Z", "X", "Y"), ("Z", "Y", "X")):
            r = self._relabel(seed, {"I": "I", "X": a, "Y": b, "Z": c})
            for i in range(n):
                for s in (r[i:] + r[:i], (r[i:] + r[:i])[::-1]):
                    if best is None or s < best:
                        best = s
        return best

    def canonical(self, c):
        return self._canon_seed(c["seed"])


class GolombSpace(Space):
    """Golomb rulers with a fixed number of marks."""
    first_is_optimal = True

    def __init__(self, problem):
        super().__init__(problem)
        self.m = self.params["marks"]
        self.max_len = self.params.get("search_max_length", self.m * self.m)

    def random(self, rng):
        marks = {0}
        L = self.max_len
        while len(marks) < self.m:
            marks.add(rng.randrange(1, L + 1))
        return {"marks": sorted(marks)}

    def mutate(self, c, rng):
        marks = sorted(c["marks"])
        i = rng.randrange(1, len(marks))
        marks[i] = max(1, marks[i] + rng.choice((-3, -2, -1, 1, 2, 3)))
        marks = sorted(set(marks))
        while len(marks) < self.m:
            marks = sorted(set(marks) | {rng.randrange(1, self.max_len + 1)})
        if marks[0] != 0:
            marks = [0] + marks[: self.m - 1]
        return {"marks": marks[: self.m]}

    def canonical(self, c):
        m = sorted(c["marks"])
        L = m[-1]
        mirror = sorted(L - x for x in m)
        return str(min(m, mirror))

    def enumerate(self):
        """Branch-and-bound: for L = lower bound upward, find any ruler of length L.
        The first ruler yielded is optimal; the exhaustive proposer stops there."""
        m = self.m
        lower = m * (m - 1) // 2
        for L in range(lower, self.max_len + 1):
            found = self._search(L)
            if found:
                yield {"marks": found}
                return

    def _search(self, L: int) -> list[int] | None:
        m = self.m
        marks = [0]

        def dfs(used: int) -> bool:
            if len(marks) == m - 1:
                # last mark must be exactly L
                ok = True
                u = used
                for x in marks:
                    d = L - x
                    if (u >> d) & 1:
                        ok = False
                        break
                    u |= 1 << d
                if ok:
                    marks.append(L)
                    return True
                return False
            remaining = m - len(marks)
            start = marks[-1] + 1
            # symmetry break: second mark < L - (second-to-last) handled loosely by bound
            for nxt in range(start, L - (remaining - 1) * 1 + 1):
                if nxt >= L:
                    break
                u = used
                ok = True
                for x in marks:
                    d = nxt - x
                    if (u >> d) & 1:
                        ok = False
                        break
                    u |= 1 << d
                if not ok:
                    continue
                marks.append(nxt)
                if dfs(u):
                    return True
                marks.pop()
            return False

        return list(marks) if dfs(0) else None


class LeanSpace(Space):
    def random(self, rng):
        raise NotImplementedError("formal-proof problems need an LLM or human proposer")

    def canonical(self, c):
        return c.get("lean_source", "")


SPACES = {"cyclic_stabilizer": CyclicCodeSpace, "golomb": GolombSpace, "lean": LeanSpace}


def space_for(problem: dict[str, Any]) -> Space:
    return SPACES[problem["space"]](problem)
