import json

import pytest

from probatio import study
from probatio.ledger import Ledger


def _proto(tmp_path, problems=("capset.n3",), seconds=2):
    p = tmp_path / "proto.json"
    p.write_text(json.dumps({"id": "t", "problems": list(problems),
                             "arms": [{"name": "anneal", "proposer": "mutation", "seeds": [1, 2],
                                       "seconds": seconds, "budget": 10 ** 6, "batch": 32, "status": "active"},
                                      {"name": "llm-direct", "proposer": "llm", "seeds": [1], "seconds": 5,
                                       "budget": 10, "batch": 5, "status": "pending"}]}))
    return p


def test_protocol_registered_first_and_change_refused(tmp_path):
    p = _proto(tmp_path)
    res = tmp_path / "res"
    study.register(p, res)
    assert Ledger(res).entries()[0]["type"] == "protocol"
    study.register(p, res)  # unchanged: fine
    p.write_text(p.read_text().replace('"seeds": [1, 2]', '"seeds": [1, 2, 3]'))
    with pytest.raises(SystemExit, match="PROTOCOL CHANGED"):
        study.register(p, res)


def test_pending_arms_skipped_and_runs_resume(tmp_path):
    p = _proto(tmp_path)
    res = tmp_path / "res"
    study.run_study(p, res, jobs=1)
    runs = [e for e in Ledger(res).entries() if e["type"] == "run"]
    assert len(runs) == 2 and {r["body"]["arm"] for r in runs} == {"anneal"}
    study.run_study(p, res, jobs=1)  # resume: nothing new
    assert len([e for e in Ledger(res).entries() if e["type"] == "run"]) == 2
    assert Ledger(res).audit() == []


def test_llm_arm_requires_key(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="ANTHROPIC_API_KEY"):
        study.run_study(_proto(tmp_path), tmp_path / "res", arms=["llm-direct"])


def test_analysis_and_notebook(tmp_path):
    p = _proto(tmp_path, problems=("capset.n3", "golomb.m6"), seconds=1)
    res = tmp_path / "res"
    study.run_study(p, res, jobs=1)
    study.add_note(res, "pilot looks fine")
    out = study.analyze(res)
    assert (out / "tables" / "summary.tex").exists() and (out / "figures" / "success_by_family.pdf").exists()
    nb = study.notebook(res).read_text()
    assert "Protocol registered" in nb and "pilot looks fine" in nb


def test_fisher_and_wilson():
    assert abs(study.fisher_exact(3, 1, 1, 3) - 0.4857) < 1e-3
    lo, hi = study.wilson(5, 10)
    assert 0.23 < lo < 0.24 and 0.76 < hi < 0.77


def test_problems_without_reference_are_not_scored(tmp_path):
    # qec n6 has no recorded reference: it must not count as a failure in success rates,
    # and its post-hoc reference appears only in the exploratory table.
    p = _proto(tmp_path, problems=("qec.cyclic.n5.k1", "qec.cyclic.n6.k1"), seconds=1)
    res = tmp_path / "res"
    study.run_study(p, res, jobs=1)
    rows = study.collect(res)
    assert all(r["scored"] == (r["problem"] == "qec.cyclic.n5.k1") for r in rows)
    summ = study.summarise(rows)
    assert all(s["runs"] == 2 for s in summ)  # only the two n5 seeds
    out = study.analyze(res)
    ph = (out / "tables" / "posthoc.md").read_text()
    assert "qec.cyclic.n6.k1" in ph and "qec.cyclic.n5.k1" not in ph


def test_wilson_interval_contains_estimate():
    for k, n in [(0, 5), (5, 5), (3, 3), (1, 7)]:
        lo, hi = study.wilson(k, n)
        assert lo - 1e-12 <= k / n <= hi + 1e-12
