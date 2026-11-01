"""The browser verifier (JavaScript) must agree with the Python checkers on every
stored certificate. Skipped when Node.js is not installed."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_js_verifier_agrees_with_python():
    r = subprocess.run(["node", str(ROOT / "tests/js/check_certs.js")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
