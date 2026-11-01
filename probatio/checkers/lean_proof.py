"""Lean 4 proof checker (trust level T1: the Lean kernel decides).

The problem supplies the exact theorem statement. The candidate supplies a full
Lean source file. The checker:

1. rejects escape hatches (sorry, admit, new axioms, unsafe, implemented_by,
   native_decide unless the problem allows it);
2. requires the problem's statement to appear verbatim in the file;
3. appends ``#print axioms <name>`` and runs Lean;
4. requires exit code 0 and that the theorem depends only on the standard
   axioms (propext, Quot.sound, Classical.choice).

If Lean is not installed the verdict is invalid with reason
``checker-unavailable``. It is never reported as valid.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from typing import Any

from .base import Checker, Verdict

FORBIDDEN = [r"\bsorry\b", r"\badmit\b", r"^\s*axiom\b", r"\bunsafe\b", r"implemented_by",
             r"\bextern\b", r"#eval", r"run_cmd", r"\bopaque\b"]
ALLOWED_AXIOMS = {"propext", "Quot.sound", "Classical.choice"}


def find_lean() -> str | None:
    found = shutil.which("lean")
    if found:
        return found
    candidate = os.path.expanduser("~/.elan/bin/lean")
    return candidate if os.path.exists(candidate) else None


class LeanProofChecker(Checker):
    name = "lean_proof"
    version = "0.1.0"
    trust = "T1"

    def check(self, problem: dict[str, Any], candidate: dict[str, Any]) -> Verdict:
        params = problem.get("params", {})
        statement = params.get("statement", "").strip()
        theorem = params.get("theorem_name", "")
        source = candidate.get("lean_source")
        if not statement or not theorem:
            return self._verdict(False, reason="problem lacks params.statement / params.theorem_name")
        if not isinstance(source, str) or len(source) > 200_000:
            return self._verdict(False, reason="candidate.lean_source must be a string under 200 kB")

        forbidden = list(FORBIDDEN)
        if not params.get("allow_native_decide", False):
            forbidden.append(r"native_decide")
        for pat in forbidden:
            if re.search(pat, source, flags=re.MULTILINE):
                return self._verdict(False, reason=f"forbidden construct matched: {pat}")
        if statement not in source:
            return self._verdict(False, reason="theorem statement not present verbatim (tampering check)")

        lean = find_lean()
        if lean is None:
            return self._verdict(False, reason="checker-unavailable: Lean 4 not installed")

        with tempfile.TemporaryDirectory(prefix="probatio-lean-") as tmp:
            path = os.path.join(tmp, "Candidate.lean")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(source.rstrip() + f"\n\n#print axioms {theorem}\n")
            try:
                proc = subprocess.run([lean, path], capture_output=True, text=True,
                                      timeout=params.get("timeout_s", 300), cwd=tmp)
            except subprocess.TimeoutExpired:
                return self._verdict(False, reason="lean timed out")

        out = (proc.stdout + proc.stderr).strip()
        log = [f"lean exit code {proc.returncode}"]
        if proc.returncode != 0:
            return self._verdict(False, reason="lean rejected the file", transcript=log + [out[-4000:]])
        if "depends on axioms" in out:
            used = set(re.findall(r"[\w.]+", out.split("depends on axioms", 1)[1].split("]")[0]))
            extra = used - ALLOWED_AXIOMS
            if extra:
                return self._verdict(False, reason=f"non-standard axioms used: {sorted(extra)}",
                                     transcript=log + [out[-4000:]])
            log.append(f"axioms used: {sorted(used)}")
        elif "does not depend on any axioms" in out:
            log.append("theorem depends on no axioms")
        else:
            return self._verdict(False, reason="could not confirm axioms", transcript=log + [out[-4000:]])
        return self._verdict(True, score={"proved": True, "theorem": theorem}, transcript=log)
