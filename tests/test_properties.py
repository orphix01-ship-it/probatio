"""Property-based tests: each checker against a naive definition and known invariances."""
import itertools
from fractions import Fraction

import pytest

hyp = pytest.importorskip("hypothesis")
from hypothesis import HealthCheck, given, settings, strategies as st  # noqa: E402

from probatio import registry  # noqa: E402
from probatio.checkers import get_checker  # noqa: E402
from probatio.checkers.stabilizer_code import analyse_code, cyclic_shifts  # noqa: E402
from probatio.ledger import Ledger  # noqa: E402

S = settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
LIN = get_checker("linear_code")


def _naive_weights(rows, n):
    ws = []
    for m in itertools.product((0, 1), repeat=len(rows)):
        if any(m):
            w = [0] * n
            for bit, r in zip(m, rows):
                if bit:
                    w = [a ^ int(b) for a, b in zip(w, r)]
            ws.append(sum(w))
    return ws


def _rank(rows):
    from probatio.checkers.linear_code import gf2_rank
    return gf2_rank([int(r[::-1], 2) for r in rows])


matrices = st.integers(2, 7).flatmap(lambda k: st.integers(k + 1, 18).flatmap(
    lambda n: st.lists(st.text("01", min_size=n, max_size=n), min_size=k, max_size=k)))


@S
@given(matrices)
def test_linear_code_distance_matches_naive(rows):
    n, k = len(rows[0]), len(rows)
    v = LIN.check({"params": {}}, {"generator": rows})
    if _rank(rows) < k:
        assert not v.valid
        return
    ws = _naive_weights(rows, n)
    assert v.valid and v.score["d"] == min(ws) and v.score["A_d"] == ws.count(min(ws))


@S
@given(matrices, st.randoms(use_true_random=False))
def test_linear_code_invariant_under_equivalence(rows, rnd):
    if _rank(rows) < len(rows):
        return
    n = len(rows[0])
    perm = list(range(n)); rnd.shuffle(perm)
    permuted = ["".join(r[p] for p in perm) for r in rows]
    i, j = rnd.sample(range(len(rows)), 2)
    rowop = list(permuted)
    rowop[i] = "".join(str(int(a) ^ int(b)) for a, b in zip(rowop[i], rowop[j]))  # same code
    a = LIN.check({"params": {}}, {"generator": rows}).score
    b = LIN.check({"params": {}}, {"generator": rowop}).score
    assert (a["d"], a["A_d"]) == (b["d"], b["A_d"])


@S
@given(st.integers(3, 4).flatmap(lambda n: st.sets(st.tuples(*[st.integers(0, 2)] * n), min_size=1, max_size=20)))
def test_cap_set_matches_naive(points):
    n = len(next(iter(points)))
    pts = ["".join(map(str, p)) for p in points]
    naive = not any(all((x + y + z) % 3 == 0 for x, y, z in zip(a, b, c))
                    for a, b, c in itertools.combinations(points, 3))
    v = get_checker("cap_set").check({"params": {"n": n}}, {"points": pts})
    assert v.valid == naive
    if v.valid:
        assert v.score["size"] == len(points)


@S
@given(st.sets(st.integers(1, 40), min_size=4, max_size=7))
def test_golomb_matches_naive(rest):
    marks = sorted({0} | rest)
    diffs = [b - a for a, b in itertools.combinations(marks, 2)]
    v = get_checker("golomb_ruler").check({"params": {"marks": len(marks)}}, {"marks": marks})
    assert v.valid == (len(diffs) == len(set(diffs)))
    if v.valid:
        assert v.score["length"] == marks[-1]


coords = st.integers(0, 10 ** 6).map(lambda x: "1" if x == 10 ** 6 else f"0.{x:06d}")


def _mirror(x: str) -> str:
    f = 1 - Fraction(x)
    return str(int(f)) if f.denominator == 1 else f"0.{int(f * 10 ** 6):06d}"


@S
@given(st.lists(st.tuples(coords, coords), min_size=3, max_size=6, unique=True))
def test_point_spread_exact_and_reflection_invariant(pts):
    n = len(pts)
    chk = get_checker("point_spread")
    v = chk.check({"params": {"n": n}}, {"points": [list(p) for p in pts]})
    fr = [(Fraction(x), Fraction(y)) for x, y in pts]
    if len(set(fr)) < n:
        return
    exact = min((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 for a, b in itertools.combinations(fr, 2))
    assert v.valid and Fraction(v.score["min_dist_sq"]) == exact
    mirrored = [[_mirror(x), y] for x, y in pts]
    w = chk.check({"params": {"n": n}}, {"points": mirrored})
    assert Fraction(w.score["min_dist_sq"]) == exact


@settings(max_examples=60, deadline=None)
@given(st.text("IXYZ", min_size=5, max_size=7), st.integers(0, 6))
def test_cyclic_code_invariant_under_seed_rotation(seed, s):
    s %= len(seed)
    def outcome(sd):
        try:
            r = analyse_code(cyclic_shifts(sd))
            return (r.get("k"), r.get("d"))
        except ValueError:
            return "rejected"
    assert outcome(seed) == outcome(seed[s:] + seed[:s])


@settings(max_examples=40, deadline=None)
@given(st.data())
def test_any_byte_change_in_a_certificate_is_detected(tmp_path_factory, data):
    from probatio import orchestrator
    res = tmp_path_factory.mktemp("led")
    r = orchestrator.run("golomb.m6", "exhaustive", budget=10 ** 6, seconds=30, results_dir=res, quiet=True)
    path = next((res / "certs").rglob(r["best_cert"] + "*"))
    raw = bytearray(path.read_bytes())
    i = data.draw(st.integers(0, len(raw) - 1))
    raw[i] = (raw[i] + data.draw(st.integers(1, 255))) % 256
    path.write_bytes(bytes(raw))
    assert Ledger(res).audit() != [] or not orchestrator.verify(r["best_cert"], res)[0]
