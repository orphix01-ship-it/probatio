import json

from probatio import orchestrator, registry
from probatio.ledger import Ledger


class FakeClient:
    """Stands in for a model: returns a fixed program / JSON, no network."""
    model = "fake-model"

    def __init__(self, text):
        self.text = text

    def complete(self, system, user, max_tokens=4000):
        return self.text, {"model": self.model, "usage": {}, "cost_usd": 0.0}


def test_registry_loads():
    probs = registry.load_all()
    assert "qec.cyclic.n5.k1" in probs and "golomb.m8" in probs


def test_exhaustive_finds_perfect_code_and_verifies(tmp_path):
    s = orchestrator.run("qec.cyclic.n5.k1", "exhaustive", budget=10**6, results_dir=tmp_path, quiet=True)
    assert s["best_value"] == 3 and s["exhaustive_complete"] and s["status"] == "matches-known"
    ok, msg = orchestrator.verify(s["best_cert"], tmp_path)
    assert ok, msg
    assert Ledger(tmp_path).audit() == []


def test_mutation_finds_golomb(tmp_path):
    s = orchestrator.run("golomb.m6", "mutation", budget=20000, seconds=60, results_dir=tmp_path,
                         quiet=True, seed=1)
    assert s["best_value"] is not None and s["best_value"] >= 17


def test_tampered_certificate_fails_verification(tmp_path):
    s = orchestrator.run("qec.cyclic.n5.k1", "exhaustive", budget=10**6, results_dir=tmp_path, quiet=True)
    path = tmp_path / "certs" / f"{s['best_cert']}.json"
    cert = json.loads(path.read_text())
    cert["verdict"]["score"]["d"] = 5
    path.write_text(json.dumps(cert))
    try:
        ok, _ = orchestrator.verify(str(path), tmp_path)
    except ValueError:
        ok = False
    assert not ok


def test_llm_proposer_with_fake_model(tmp_path):
    client = FakeClient('```json\n[{"seed": "XZZXI"}, {"seed": "XXXXX"}]\n```')
    s = orchestrator.run("qec.cyclic.n5.k1", "llm", budget=2, results_dir=tmp_path,
                         client=client, quiet=True)
    assert s["best_value"] == 3


def test_program_evolution_runs_in_sandbox(tmp_path):
    prog = ("```python\nimport json\n"
            "print(json.dumps([{'seed': 'XZZXI'}]))\n```")
    s = orchestrator.run("qec.cyclic.n5.k1", "program_evolution", budget=1, results_dir=tmp_path,
                         client=FakeClient(prog), quiet=True)
    assert s["best_value"] == 3
    assert s["provenance"]["sandbox_runs"] == 1


def test_malicious_program_contained(tmp_path):
    prog = "```python\nimport os\nos.system('echo pwned > /tmp/probatio_pwned')\nwhile True: pass\n```"
    s = orchestrator.run("qec.cyclic.n5.k1", "program_evolution", budget=1, seconds=6,
                         results_dir=tmp_path, client=FakeClient(prog), quiet=True,
                         program_timeout=2)
    assert s["best_value"] is None
