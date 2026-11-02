"""Known mathematical facts for the cap set, linear code and point-spread checkers,
plus an independent naive cross-check for linear-code distance."""
import itertools
import random

from probatio.checkers import get_checker


# ---------- linear codes ----------
def cyclic_rows(gpoly_bits, n):
    """Rows x^i * g(x) for i < n - deg(g); bit string index = coefficient of x^j."""
    deg = len(gpoly_bits) - 1
    return ["0" * i + gpoly_bits + "0" * (n - deg - 1 - i) for i in range(n - deg)]


HAMMING = ["1000110", "0100011", "0010111", "0001101"]
GOLAY_G = "101011100011"          # 1 + x^2 + x^4 + x^5 + x^6 + x^10 + x^11
GOLAY23 = cyclic_rows(GOLAY_G, 23)
GOLAY24 = [r + str(r.count("1") % 2) for r in GOLAY23]


def check_code(rows, n=None, k=None):
    return get_checker("linear_code").check({"params": {"n": n, "k": k}}, {"generator": rows})


def test_hamming_7_4_3():
    v = check_code(HAMMING)
    assert v.valid and (v.score["d"], v.score["A_d"]) == (3, 7)


def test_golay_codes():
    v = check_code(GOLAY23)
    assert v.valid and (v.score["k"], v.score["d"], v.score["A_d"]) == (12, 7, 253)
    v = check_code(GOLAY24)
    assert v.valid and (v.score["d"], v.score["A_d"]) == (8, 759)


def test_dependent_rows_rejected():
    v = check_code(["1100", "0110", "1010"])
    assert not v.valid and "dependent" in v.reason


def test_dimension_mismatch_rejected():
    assert not check_code(HAMMING, n=7, k=3).valid


def naive_distance(rows):
    n = len(rows[0])
    best = n
    for coeffs in itertools.product([0, 1], repeat=len(rows)):
        if not any(coeffs):
            continue
        w = [0] * n
        for c, r in zip(coeffs, rows):
            if c:
                w = [a ^ int(b) for a, b in zip(w, r)]
        best = min(best, sum(w))
    return best


def test_linear_distance_crosscheck_random():
    rng = random.Random(3)
    done = 0
    while done < 120:
        n, k = rng.randint(5, 14), rng.randint(2, 6)
        if k > n:
            continue
        rows = ["".join(rng.choice("01") for _ in range(n)) for _ in range(k)]
        v = check_code(rows)
        if not v.valid:
            continue
        assert v.score["d"] == naive_distance(rows), rows
        done += 1


def test_wide_code_over_64_bits():
    # repetition-style rows spanning > 64 coordinates exercise the high word
    n = 100
    rows = ["1" * 50 + "0" * 50, "0" * 50 + "1" * 50]
    v = check_code(rows)
    assert v.valid and v.score["d"] == 50 and v.score["A_d"] == 2


# ---------- cap sets ----------
def check_cap(pts, n):
    return get_checker("cap_set").check({"params": {"n": n}}, {"points": pts})


def test_cap_set_dim2_size4():
    v = check_cap(["00", "01", "10", "11"], 2)
    assert v.valid and v.score["size"] == 4


def test_cap_set_line_rejected():
    v = check_cap(["00", "01", "02"], 2)
    assert not v.valid and "line" in v.reason


def test_cap_set_dim4_size20_crosscheck():
    # Build a maximal cap greedily and confirm with a naive all-triples test.
    rng = random.Random(1)
    pts = ["".join(p) for p in itertools.product("012", repeat=4)]
    rng.shuffle(pts)
    cap = []
    for p in pts:
        if check_cap(cap + [p], 4).valid:
            cap.append(p)
    v = check_cap(cap, 4)
    assert v.valid
    for a, b, c in itertools.combinations(cap, 3):
        assert any((int(x) + int(y) + int(z)) % 3 for x, y, z in zip(a, b, c))


# ---------- point spreading ----------
def check_pts(pts):
    return get_checker("point_spread").check({"params": {"n": len(pts)}}, {"points": pts})


def test_four_corners_exact():
    v = check_pts([["0", "0"], ["1", "0"], ["0", "1"], ["1", "1"]])
    assert v.valid and v.score["min_dist_sq"] == "1" and v.score["min_distance"] == 1.0


def test_nine_point_grid():
    g = [[str(a), str(b)] for a in ("0", "1/2", "1") for b in ("0", "1/2", "1")]
    v = check_pts(g)
    assert v.valid and v.score["min_dist_sq"] == "1/4"


def test_outside_square_rejected():
    assert not check_pts([["0", "0"], ["1.0000001", "0"]]).valid


def test_coincident_rejected():
    assert not check_pts([["0.5", "0.5"], ["1/2", "0.50"]]).valid
