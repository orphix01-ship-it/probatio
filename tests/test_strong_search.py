"""Stronger search spaces and the record-hunt tooling."""
import random

import pytest

from probatio import hunt, orchestrator, registry
from probatio.checkers import get_checker
from probatio.spaces import space_for


def test_constructive_golomb_is_valid_by_construction():
    p = registry.get("golomb.m9")
    sp, ch, rng = space_for(p, "golomb_constructive"), get_checker("golomb_ruler"), random.Random(3)
    c = sp.random(rng)
    for _ in range(100):
        assert ch.check(p, c).valid
        c = sp.mutate(c, rng)


def test_quasi_cyclic_generator_matches_polynomials():
    p = registry.get("lincode.n24.k12")
    sp, rng = space_for(p, "linear_code_qc"), random.Random(1)
    c = sp.random(rng)
    g = c["generator"]
    assert len(g) == 12 and all(len(r) == 24 for r in g)
    # row s is the cyclic shift by s of row 0 within each 12-column block
    for s in range(12):
        for b in range(2):
            blk0, blk = g[0][12 * b:12 * b + 12], g[s][12 * b:12 * b + 12]
            assert blk == blk0[-s:] + blk0[:-s] if s else blk == blk0
    assert sp.normalize({"polynomials": c["polynomials"]})["generator"] == g


def test_quasi_cyclic_canonical_is_an_equivalence():
    p = registry.get("lincode.n24.k12")
    sp, ch, rng = space_for(p, "linear_code_qc"), get_checker("linear_code"), random.Random(5)
    c = sp.random(rng)
    q = c["polynomials"][0]
    shifted = sp.normalize({"polynomials": [q[3:] + q[:3]]})
    assert sp.canonical(c) == sp.canonical(shifted)
    a, b = ch.check(p, c).score, ch.check(p, shifted).score
    assert (a["d"], a["A_d"]) == (b["d"], b["A_d"])


def test_quasi_cyclic_search_finds_golay(tmp_path):
    r = orchestrator.run("lincode.n24.k12", "mutation", budget=20000, seconds=60, seed=1,
                         results_dir=tmp_path, quiet=True, search_space="linear_code_qc")
    assert r["best_value"] == 8 and r["provenance"]["search_space"] == "linear_code_qc"
    ok, _ = orchestrator.verify(r["best_cert"], tmp_path)
    assert ok


def test_incompatible_space_refused():
    with pytest.raises(ValueError, match="not compatible"):
        space_for(registry.get("golomb.m6"), "linear_code_qc")


def test_candidate_record_written_for_review(tmp_path):
    r = orchestrator.run("lincode.n7.k4", "mutation", budget=500, seconds=10, seed=1,
                         results_dir=tmp_path, quiet=True)
    path = hunt._record_candidate(tmp_path, {**r, "status": "CANDIDATE-NEW"})
    text = path.read_text()
    assert "UNREVIEWED" in text and r["best_cert"] in text and "generator" in text
