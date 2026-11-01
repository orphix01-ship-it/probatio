"""Cross-check the stabilizer checker against an independent, deliberately naive
implementation: string-based Pauli algebra and full stabilizer-group enumeration.
Shares no code with probatio.checkers.stabilizer_code."""
import random
from itertools import product

from probatio.checkers.stabilizer_code import analyse_code

MUL = {("I", p): p for p in "IXYZ"} | {(p, "I"): p for p in "IXYZ"} | {
    (p, p): "I" for p in "IXYZ"} | {("X", "Y"): "Z", ("Y", "X"): "Z", ("Y", "Z"): "X",
                                    ("Z", "Y"): "X", ("Z", "X"): "Y", ("X", "Z"): "Y"}


def mul(a, b):
    return "".join(MUL[(x, y)] for x, y in zip(a, b))


def commutes(a, b):
    anti = sum(1 for x, y in zip(a, b) if x != "I" and y != "I" and x != y)
    return anti % 2 == 0


def naive(gens):
    n = len(gens[0])
    group = {"I" * n}
    for g in gens:
        group |= {mul(g, h) for h in group}
    rank = len(group).bit_length() - 1
    k = n - rank
    best = None
    for p in product("IXYZ", repeat=n):
        p = "".join(p)
        w = n - p.count("I")
        if w == 0 or (best is not None and w >= best):
            continue
        if all(commutes(p, g) for g in gens) and (k == 0 or p not in group):
            best = w
    return n, k, best


def shifts(s):
    return [s[-i:] + s[:-i] if i else s for i in range(len(s))]


def test_all_cyclic_codes_up_to_6_agree():
    """Every self-commuting cyclic seed for n = 3..6, compared exactly."""
    seen_d = set()
    cases = 0
    for n in (3, 4, 5, 6):
        for seed in product("IXYZ", repeat=n):
            seed = "".join(seed)
            if not seed.strip("I"):
                continue
            gens = shifts(seed)
            if not all(commutes(a, b) for a in gens for b in gens):
                continue
            r = analyse_code(gens)
            expect = naive(gens)
            assert (r["n"], r["k"], r["d"]) == expect, seed
            seen_d.add(expect[2])
            cases += 1
    assert cases > 100 and {1, 2, 3} <= seen_d


def test_random_general_codes_with_distance_agree():
    """Random commuting sets, keeping a quota of codes with d >= 2 and d >= 3."""
    rng = random.Random(11)
    quota = {1: 60, 2: 60, 3: 15}
    tries = 0
    while any(v > 0 for v in quota.values()) and tries < 200000:
        tries += 1
        n = rng.choice([4, 5, 6])
        gens = []
        for _ in range(rng.randint(2, n)):
            for _ in range(50):
                g = "".join(rng.choice("IXYZ") for _ in range(n))
                if g.strip("I") and all(commutes(g, h) for h in gens):
                    gens.append(g)
                    break
        r = analyse_code(gens)
        d = min(r["d"], 3)
        if quota.get(d, 0) <= 0:
            continue
        assert (r["n"], r["k"], r["d"]) == naive(gens), gens
        quota[d] -= 1
    assert all(v <= 0 for v in quota.values()), quota


def test_symmetry_reduced_enumeration_is_complete():
    """The exhaustive proposer's rotation/relabel reduction must not lose the optimum:
    compare against brute force over every seed for n = 5..8."""
    from probatio.spaces import CyclicCodeSpace
    for n in (5, 6, 7, 8):
        space = CyclicCodeSpace({"params": {"n": n, "k": 1, "family": "cyclic"}})
        reduced = full = 0
        for c in space.enumerate():
            r = analyse_code(c["generators"])
            if r["k"] == 1:
                reduced = max(reduced, r["d"])
        for seed in product("IXYZ", repeat=n):
            seed = "".join(seed)
            if not seed.strip("I") or not space.self_commuting(seed):
                continue
            r = analyse_code(shifts(seed))
            if r["k"] == 1:
                full = max(full, r["d"])
        assert reduced == full, (n, reduced, full)
