from probatio.checkers import get_checker
from probatio.checkers.stabilizer_code import analyse_code, cyclic_shifts

STEANE = ["IIIXXXX", "IXXIIXX", "XIXIXIX", "IIIZZZZ", "IZZIIZZ", "ZIZIZIZ"]


def test_five_qubit_code():
    r = analyse_code(cyclic_shifts("XZZXI"))
    assert (r["n"], r["k"], r["d"]) == (5, 1, 3)


def test_steane_code():
    r = analyse_code(STEANE)
    assert (r["n"], r["k"], r["d"]) == (7, 1, 3)


def test_four_two_two():
    r = analyse_code(["XXXX", "ZZZZ"])
    assert (r["n"], r["k"], r["d"]) == (4, 2, 2)


def test_bit_flip_code_distance_one():
    r = analyse_code(["ZZI", "IZZ"])
    assert (r["n"], r["k"], r["d"]) == (3, 1, 1)


def test_shor_code():
    gens = ["ZZIIIIIII", "IZZIIIIII", "IIIZZIIII", "IIIIZZIII", "IIIIIIZZI", "IIIIIIIZZ",
            "XXXXXXIII", "IIIXXXXXX"]
    r = analyse_code(gens)
    assert (r["n"], r["k"], r["d"]) == (9, 1, 3)


def test_bell_state_k0():
    r = analyse_code(["XX", "ZZ"])
    assert r["k"] == 0 and r["d"] == 2


def test_dependent_generators_ok():
    r = analyse_code(["XXXX", "ZZZZ", "YYYY"])  # YYYY = XXXX*ZZZZ up to phase
    assert r["k"] == 2


def test_anticommuting_rejected():
    v = get_checker("stabilizer_code").check({"params": {}}, {"generators": ["XI", "ZI"]})
    assert not v.valid and "anticommute" in v.reason


def test_cyclic_family_enforced():
    chk = get_checker("stabilizer_code")
    prob = {"params": {"family": "cyclic", "n": 5, "k": 1}}
    good = chk.check(prob, {"seed": "XZZXI", "generators": cyclic_shifts("XZZXI")})
    assert good.valid and good.score["d"] == 3
    bad = chk.check(prob, {"seed": "XZZXI", "generators": STEANE})
    assert not bad.valid


def test_claimed_distance_ignored():
    chk = get_checker("stabilizer_code")
    v = chk.check({"params": {}}, {"generators": ["ZZI", "IZZ"], "d": 99})
    assert v.score["d"] == 1


def test_golomb_valid_and_invalid():
    chk = get_checker("golomb_ruler")
    optimal = {4: [0, 1, 4, 6], 5: [0, 1, 4, 9, 11], 6: [0, 1, 4, 10, 12, 17],
               7: [0, 1, 4, 10, 18, 23, 25], 8: [0, 1, 4, 9, 15, 22, 32, 34],
               9: [0, 1, 5, 12, 25, 27, 35, 41, 44], 10: [0, 1, 6, 10, 23, 26, 34, 41, 53, 55]}
    for m, marks in optimal.items():
        v = chk.check({"params": {"marks": m}}, {"marks": marks})
        assert v.valid, (m, v.reason)
    assert not chk.check({"params": {}}, {"marks": [0, 1, 2]}).valid
    assert not chk.check({"params": {}}, {"marks": [0, 1, 3, 4]}).valid


def test_lean_forbidden_and_unavailable():
    chk = get_checker("lean_proof")
    prob = {"params": {"statement": "theorem t : 1 + 1 = 2", "theorem_name": "t"}}
    assert "forbidden" in chk.check(prob, {"lean_source": "theorem t : 1 + 1 = 2 := by sorry"}).reason
    assert "tampering" in chk.check(prob, {"lean_source": "theorem t : 2 = 2 := rfl"}).reason
    v = chk.check(prob, {"lean_source": "theorem t : 1 + 1 = 2 := rfl"})
    # valid only if a real Lean is installed; never valid without one
    import os
    if os.environ.get("PROBATIO_REQUIRE_LEAN"):
        assert v.valid, v.reason
        # and a false statement must be rejected by the kernel
        bad = chk.check({"params": {"statement": "theorem t : 1 + 1 = 3", "theorem_name": "t"}},
                        {"lean_source": "theorem t : 1 + 1 = 3 := rfl"})
        assert not bad.valid
    else:
        assert v.valid or "checker-unavailable" in v.reason
