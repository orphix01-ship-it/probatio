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


def space_for(problem: dict[str, Any], override: str | None = None) -> Space:
    """The problem's own search space, or a compatible alternative named by an arm."""
    name = override or problem["space"]
    if override and not name.startswith(problem["space"]):
        raise ValueError(f"space {override!r} is not compatible with problem space {problem['space']!r}")
    return SPACES[name](problem)


class CapSetSpace(Space):
    """Cap sets in F_3^n. Candidates are built greedily so every one is valid by
    construction; mutation removes a few points and greedily refills."""

    def __init__(self, problem):
        super().__init__(problem)
        self.n = self.params["n"]
        self.all = list(product(range(3), repeat=self.n))

    @staticmethod
    def _third(a, b):
        return tuple((-(x + y)) % 3 for x, y in zip(a, b))

    def _fill(self, cap: list, rng) -> list:
        forbidden = set()
        for i in range(len(cap)):
            for j in range(i + 1, len(cap)):
                forbidden.add(self._third(cap[i], cap[j]))
        have = set(cap)
        order = self.all[:]
        rng.shuffle(order)
        for p in order:
            if p in have or p in forbidden:
                continue
            for q in cap:
                forbidden.add(self._third(p, q))
            cap.append(p)
            have.add(p)
        return cap

    def _cand(self, cap):
        return {"points": sorted("".join(map(str, p)) for p in cap)}

    def random(self, rng):
        return self._cand(self._fill([], rng))

    def mutate(self, c, rng):
        cap = [tuple(int(ch) for ch in p) for p in c["points"]]
        rng.shuffle(cap)
        drop = rng.choice((1, 2, 2, 3, 4))
        return self._cand(self._fill(cap[drop:], rng))

    def canonical(self, c):
        return ",".join(sorted(c["points"]))


class LinearCodeSpace(Space):
    """Binary linear [n, k] codes in systematic form [I_k | A]."""

    def __init__(self, problem):
        super().__init__(problem)
        self.n, self.k = self.params["n"], self.params["k"]

    def _cand(self, A):
        rows = []
        for i in range(self.k):
            rows.append("".join("1" if j == i else "0" for j in range(self.k)) + "".join(map(str, A[i])))
        return {"generator": rows}

    def random(self, rng):
        return self._cand([[rng.randint(0, 1) for _ in range(self.n - self.k)] for _ in range(self.k)])

    def mutate(self, c, rng):
        A = [[int(b) for b in r[self.k:]] for r in c["generator"]]
        for _ in range(rng.choice((1, 1, 2, 3))):
            i, j = rng.randrange(self.k), rng.randrange(self.n - self.k)
            A[i][j] ^= 1
        return self._cand(A)

    def canonical(self, c):
        return "|".join(c["generator"])

    def shaped(self, score, value):
        """Tie-break equal distance by fewer minimum-weight codewords."""
        if value is None:
            return None
        return value - score.get("A_d", 0) / (2 ** self.k)


class PointSpreadSpace(Space):
    """n points in the unit square; coordinates kept as 7-decimal strings so the
    checker can evaluate them exactly."""

    def __init__(self, problem):
        super().__init__(problem)
        self.n = self.params["n"]

    @staticmethod
    def _fmt(v: float) -> str:
        return f"{min(1.0, max(0.0, v)):.7f}"

    def random(self, rng):
        return {"points": [[self._fmt(rng.random()), self._fmt(rng.random())] for _ in range(self.n)]}

    def mutate(self, c, rng):
        pts = [[float(x), float(y)] for x, y in c["points"]]
        sigma = rng.choice((0.1, 0.03, 0.01, 0.003, 0.001, 0.0003))
        for _ in range(rng.choice((1, 1, 1, 2, 3))):
            i = rng.randrange(self.n)
            pts[i][0] += rng.gauss(0, sigma)
            pts[i][1] += rng.gauss(0, sigma)
        return {"points": [[self._fmt(x), self._fmt(y)] for x, y in pts]}

    def canonical(self, c):
        return ";".join(sorted(f"{x},{y}" for x, y in c["points"]))


SPACES.update({"cap_set": CapSetSpace, "linear_code": LinearCodeSpace, "point_spread": PointSpreadSpace})


class GolombConstructiveSpace(GolombSpace):
    """Golomb rulers built mark by mark so every candidate is valid by construction.

    A stronger baseline than placing marks at random: each new mark is drawn only
    from positions whose differences to all existing marks are still unused.
    Mutation removes one or two marks and rebuilds. The bound on length is the
    smaller of the problem's search bound and a slack above the best seen.
    """

    def _extend(self, marks: list[int], rng, L: int) -> list[int] | None:
        marks = sorted(marks)
        used = {b - a for i, a in enumerate(marks) for b in marks[i + 1:]}
        while len(marks) < self.m:
            opts = []
            for p in range(1, L + 1):
                if p in marks:
                    continue
                ds = [abs(p - x) for x in marks]
                if len(set(ds)) == len(ds) and not used.intersection(ds):
                    opts.append(p)
            if not opts:
                return None
            # bias towards short rulers: pick among the smallest feasible positions
            p = opts[min(len(opts) - 1, int(rng.expovariate(1 / 3)))]
            used.update(abs(p - x) for x in marks)
            marks = sorted(marks + [p])
        shift = marks[0]
        return [x - shift for x in marks]

    def random(self, rng):
        for _ in range(50):
            r = self._extend([0], rng, self.max_len)
            if r:
                return {"marks": r}
        return super().random(rng)

    def mutate(self, c, rng):
        marks = sorted(c["marks"])
        L = marks[-1]
        for _ in range(20):
            keep = list(marks)
            for _ in range(rng.choice((1, 1, 2))):
                if len(keep) > 2:
                    keep.pop(rng.randrange(1, len(keep)))
            # try to rebuild no longer than the current ruler (or slightly longer)
            r = self._extend(keep, rng, min(self.max_len, L + rng.choice((-2, -1, 0, 0, 1))))
            if r:
                return {"marks": r}
        return self.random(rng)


class QuasiCyclicCodeSpace(LinearCodeSpace):
    """Quasi-cyclic binary codes: generator [I | C_1 | ... | C_{m-1}] of circulants.

    Rows are the p = k cyclic shifts of one generating row; each block C_j is the
    circulant of a polynomial of degree < p. The [mp, k] code is punctured to
    length n by deleting trailing coordinates. Quasi-cyclic codes hold many
    records in the codetables.de tables (e.g. Chen's constructions), so this is a
    far stronger search space than unstructured generator matrices: k(n-k) free
    bits shrink to about n - k.
    """

    def __init__(self, problem):
        super().__init__(problem)
        self.p = self.k
        self.blocks = -(-self.n // self.p)  # ceil(n / p) circulant blocks, first is identity

    def _from_polys(self, polys: list[list[int]]) -> dict[str, Any]:
        p, rows = self.p, []
        for s in range(p):
            row = [1 if j == s else 0 for j in range(p)]
            for poly in polys:
                row += [poly[(j - s) % p] for j in range(p)]
            rows.append("".join(map(str, row[: self.n])))
        return {"generator": rows, "polynomials": ["".join(map(str, q)) for q in polys]}

    def _polys(self, c) -> list[list[int]]:
        if "polynomials" in c:
            return [[int(b) for b in q] for q in c["polynomials"]]
        first = c["generator"][0]
        return [[int(first[(j + 1) * self.p + i]) if (j + 1) * self.p + i < self.n else 0
                 for i in range(self.p)] for j in range(self.blocks - 1)]

    def random(self, rng):
        return self._from_polys([[rng.randint(0, 1) for _ in range(self.p)] for _ in range(self.blocks - 1)])

    def mutate(self, c, rng):
        polys = self._polys(c)
        for _ in range(rng.choice((1, 1, 2, 3))):
            j, i = rng.randrange(len(polys)), rng.randrange(self.p)
            polys[j][i] ^= 1
        return self._from_polys(polys)

    def normalize(self, c):
        return self._from_polys(self._polys(c)) if "polynomials" in c else c

    def canonical(self, c):
        # A common cyclic shift of all polynomials gives an equivalent code (same weight
        # distribution) only when no coordinates are punctured.
        polys = ["".join(map(str, q)) for q in self._polys(c)]
        if self.n % self.p:
            return "|".join(polys)
        return min("|".join(q[s:] + q[:s] for q in polys) for s in range(self.p))


SPACES.update({"golomb_constructive": GolombConstructiveSpace, "linear_code_qc": QuasiCyclicCodeSpace})
