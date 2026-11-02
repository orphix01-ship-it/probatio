"""Local open-weight model backend (Ollama API), tested against a fake server on loopback."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from probatio import orchestrator
from probatio.proposers.llm import LocalClient, _is_loopback

CALLS = []


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send({"models": [{"name": "fake:1b", "digest": "abc123def4567890"}]})

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["content-length"])))
        CALLS.append(req)
        # A Golomb ruler with 6 marks (optimal length 17) and one invalid ruler.
        text = "Here you go:\n```json\n[{\"marks\": [0, 1, 4, 10, 12, 17]}, {\"marks\": [0, 1, 2, 3, 4, 5]}]\n```"
        self._send({"message": {"role": "assistant", "content": text}, "prompt_eval_count": 50, "eval_count": 20})


@pytest.fixture()
def server(monkeypatch):
    srv = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("PROBATIO_LOCAL_HOST", f"http://127.0.0.1:{srv.server_port}")
    CALLS.clear()
    yield srv
    srv.shutdown()


def test_loopback_only():
    assert _is_loopback("127.0.0.1") and _is_loopback("localhost") and _is_loopback("::1")
    assert not _is_loopback("10.0.0.5") and not _is_loopback("example.com")
    with pytest.raises(RuntimeError, match="loopback"):
        LocalClient(model="x", host="http://example.com:11434")


def test_missing_model_is_reported(server):
    with pytest.raises(RuntimeError, match="ollama pull"):
        LocalClient(model="not-pulled:7b")


def test_local_llm_run_is_free_seeded_and_capped(server, tmp_path):
    r = orchestrator.run("golomb.m6", "llm", budget=10 ** 6, seconds=60, seed=7, batch=8,
                         results_dir=tmp_path, quiet=True, backend="local", model="fake:1b", max_calls=3)
    assert len(CALLS) == 3                                  # call budget respected
    assert [c["options"]["seed"] for c in CALLS] == [7, 8, 9]  # repeatable sampling
    assert r["cost_usd"] == 0.0
    assert r["best_value"] == 17
    assert r["candidates_checked"] == 2                     # repeats are deduplicated, not re-checked
