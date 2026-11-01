"""Problem registry: loads and validates problems/*.json."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .checkers import CHECKERS
from .util import hash_obj

REQUIRED = ("id", "domain", "statement", "checker", "objective", "params")
ROOT = Path(__file__).resolve().parent.parent


def problems_dir() -> Path:
    return ROOT / "problems"


def validate(p: dict[str, Any]) -> None:
    missing = [f for f in REQUIRED if f not in p]
    if missing:
        raise ValueError(f"problem {p.get('id')!r} missing fields {missing}")
    if p["checker"] not in CHECKERS:
        raise ValueError(f"problem {p['id']!r}: unknown checker {p['checker']!r}")
    obj = p["objective"]
    if obj.get("sense") not in ("maximize", "minimize", "prove"):
        raise ValueError(f"problem {p['id']!r}: objective.sense must be maximize/minimize/prove")


def load_all(directory: Path | None = None) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for f in sorted((directory or problems_dir()).glob("*.json")):
        data = json.loads(f.read_text())
        for p in data if isinstance(data, list) else [data]:
            validate(p)
            if p["id"] in out:
                raise ValueError(f"duplicate problem id {p['id']}")
            out[p["id"]] = p
    return out


def get(problem_id: str) -> dict[str, Any]:
    probs = load_all()
    if problem_id not in probs:
        raise KeyError(f"unknown problem {problem_id!r}")
    return probs[problem_id]


def problem_hash(p: dict[str, Any]) -> str:
    """Hash of the parts of a problem that define correctness (not commentary)."""
    return hash_obj({k: p[k] for k in ("id", "checker", "params", "objective")})


def objective_value(p: dict[str, Any], score: dict[str, Any]) -> float | None:
    """Numeric objective from a verdict score, or None if not scorable."""
    field = p["objective"].get("field")
    if p["objective"]["sense"] == "prove":
        return 1.0 if score.get("proved") else None
    v = score.get(field)
    return float(v) if isinstance(v, (int, float)) else None


def better(p: dict[str, Any], a: float | None, b: float | None) -> bool:
    """True if objective value a strictly beats b."""
    if a is None:
        return False
    if b is None:
        return True
    return a < b if p["objective"]["sense"] == "minimize" else a > b
