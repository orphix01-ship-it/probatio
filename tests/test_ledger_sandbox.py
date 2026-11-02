import json
import os

import pytest

from probatio.ledger import Ledger
from probatio.sandbox import network_isolation_available, run_program


def _ledger(tmp_path):
    led = Ledger(tmp_path)
    for i in range(3):
        ref = led.store_certificate({"i": i})
        led.append("certificate", {"cert": ref})
    return led


def test_audit_clean(tmp_path):
    assert _ledger(tmp_path).audit() == []


def test_audit_detects_modification(tmp_path):
    led = _ledger(tmp_path)
    lines = led.path.read_text().splitlines()
    e = json.loads(lines[1]); e["body"]["cert"] = "f" * 64
    lines[1] = json.dumps(e)
    led.path.write_text("\n".join(lines) + "\n")
    assert led.audit()


def test_audit_detects_deletion_and_reorder(tmp_path):
    led = _ledger(tmp_path)
    lines = led.path.read_text().splitlines()
    led.path.write_text("\n".join([lines[0], lines[2]]) + "\n")
    assert led.audit()
    led.path.write_text("\n".join([lines[1], lines[0], lines[2]]) + "\n")
    assert led.audit()


def test_audit_detects_certificate_tamper(tmp_path):
    led = _ledger(tmp_path)
    cert = next(led.certs.glob("*.json"))
    cert.write_text(json.dumps({"i": 999}))
    assert led.audit()


def test_signed_ledger(tmp_path, monkeypatch):
    pytest.importorskip("cryptography")
    monkeypatch.setenv("PROBATIO_SIGNING_KEY", "11" * 32)
    led = _ledger(tmp_path)
    assert all("sig" in e for e in led.entries())
    assert led.audit() == []


def test_sandbox_ok():
    r = run_program("import json; print(json.dumps({'a': 1}))")
    assert r.ok and r.output == {"a": 1}


def test_sandbox_timeout():
    r = run_program("while True: pass", timeout_s=2, cpu_s=5)
    assert not r.ok


def test_sandbox_memory_bomb():
    # Memory that is actually written (a lazily-zeroed bytearray never touches its pages).
    r = run_program("x = b'x' * (1536 * 1024**2); print('{}')", mem_mb=256, timeout_s=20)
    assert not r.ok


def test_memory_watchdog_alone():
    """The watchdog must stop a bomb even where RLIMIT_AS is not enforced (macOS)."""
    import subprocess, sys, threading
    from probatio.sandbox import _memory_watchdog
    proc = subprocess.Popen([sys.executable, "-c",
                             "import time; x = b'x' * (1536 * 1024**2); time.sleep(5)"],
                            start_new_session=True)
    tripped = threading.Event()
    _memory_watchdog(proc, 256, tripped)
    proc.wait(timeout=10)
    assert tripped.is_set() and proc.returncode != 0


def test_sandbox_env_scrubbed(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret-value")
    r = run_program("import os, json; print(json.dumps(dict(os.environ)))")
    assert r.ok and "ANTHROPIC_API_KEY" not in r.output


def test_sandbox_non_json_rejected():
    assert not run_program("print('hello')").ok


def test_sandbox_output_cap():
    r = run_program("print('[' + ','.join(['1']*500000) + ']')", max_output=1000)
    assert not r.ok


@pytest.mark.parametrize("src", [
    "import os; os.system('true')",
    "import subprocess",
    "import ctypes",
    "open('/tmp/probatio_escape_test', 'w').write('x')",
    "open('../escape', 'w').write('x')",
    "import os; os.remove('/etc/hostname')",
])
def test_sandbox_guard_blocks(src):
    r = run_program(src + "\nprint('{}')")
    assert not r.ok
    assert not os.path.exists("/tmp/probatio_escape_test")


def test_sandbox_allows_local_scratch_file():
    r = run_program("open('scratch.txt','w').write('ok'); import json; print(json.dumps(open('scratch.txt').read()))")
    assert r.ok and r.output == "ok"


@pytest.mark.skipif(not network_isolation_available(), reason="no user namespaces")
def test_sandbox_no_network():
    src = ("import socket, json\n"
           "try:\n"
           "    socket.create_connection(('1.1.1.1', 80), timeout=3); ok = True\n"
           "except OSError:\n"
           "    ok = False\n"
           "print(json.dumps({'net': ok}))")
    r = run_program(src, guard=False)  # test the namespace layer on its own
    assert r.ok and r.output == {"net": False} and r.network_isolated


def test_concurrent_appends_keep_chain(tmp_path):
    from concurrent.futures import ProcessPoolExecutor
    with ProcessPoolExecutor(4) as ex:
        list(ex.map(_append_many, [str(tmp_path)] * 4))
    led = Ledger(tmp_path)
    assert len(led.entries()) == 100 and led.audit() == []


def _append_many(d):
    led = Ledger(d)
    for i in range(25):
        led.append("run", {"i": i, "pid": os.getpid()})
