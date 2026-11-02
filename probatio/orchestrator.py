"""Search loop: proposers generate, checkers certify, the ledger records."""
from __future__ import annotations

import random
import sys
import time
from pathlib import Path
from typing import Any

from . import registry
from .checkers import get_checker
from .ledger import Ledger
from .proposers import PROPOSERS
from .proposers.base import Context, Feedback
from .spaces import space_for
from .util import hash_obj, now_iso

DEFAULT_RESULTS = registry.ROOT / "results"


def status_vs_known(problem: dict[str, Any], value: float | None) -> str:
    kb = problem.get("known_best")
    if value is None:
        return "no-valid-result"
    if not kb or kb.get("value") is None:
        return "no-recorded-bound"
    kbv = float(kb["value"])
    tol = float(kb.get("tolerance", 0))
    if abs(value - kbv) <= tol:
        return "matches-known"
    if registry.better(problem, value, kbv):
        return "CANDIDATE-NEW"  # requires human literature review before any claim
    return "below-known"


def run(problem_id: str, proposer: str = "mutation", *, budget: int = 10_000,
        seconds: float = 300, max_usd: float = 0.0, seed: int = 0, batch: int = 64,
        results_dir: Path | None = None, client=None, quiet: bool = False,
        **opts: Any) -> dict[str, Any]:
    problem = registry.get(problem_id)
    checker = get_checker(problem["checker"])
    space = space_for(problem)
    rng = random.Random(seed)
    kwargs = dict(opts)
    if client is not None:
        kwargs["client"] = client
    prop = PROPOSERS[proposer](problem, space, rng, **kwargs)
    ledger = Ledger(results_dir or DEFAULT_RESULTS)
    p_hash = registry.problem_hash(problem)

    ctx = Context()
    cache: dict[str, tuple[bool, float | None, str]] = {}
    cache_scores: dict[str, dict] = {}
    best_v: float | None = None
    best_cert: str | None = None
    checked = valid = dup = 0
    t0 = time.time()
    checks_to_best = seconds_to_best = None
    trajectory: list[list[float]] = []
    reasons: dict[str, int] = {}

    while checked < budget and not prop.done and time.time() - t0 < seconds:
        if max_usd and prop.cost_usd >= max_usd:
            break
        cands = prop.propose(ctx, min(batch, budget - checked))
        if not cands and not prop.done and proposer in ("llm", "program_evolution"):
            ctx.recent_failures.append(Feedback({}, False, None, "no parsable candidates returned"))
        feedback: list[Feedback] = []
        for c in cands:
            try:
                key = space.canonical(c)
            except Exception:
                key = hash_obj(c)
            if key in cache:
                dup += 1
                ok, v, reason = cache[key]
                feedback.append(Feedback(c, ok, v, reason, cache_scores.get(key)))
                continue
            verdict = checker.check(problem, c)
            checked += 1
            v = registry.objective_value(problem, verdict.score) if verdict.valid else None
            cache[key] = (verdict.valid, v, verdict.reason)
            cache_scores[key] = verdict.score
            fb = Feedback(c, verdict.valid, v, verdict.reason, verdict.score)
            feedback.append(fb)
            if not verdict.valid:
                ctx.recent_failures = (ctx.recent_failures + [fb])[-20:]
                rkey = _reason_class(verdict.reason)
                reasons[rkey] = reasons.get(rkey, 0) + 1
                continue
            valid += 1
            if registry.better(problem, v, best_v):
                best_v = v
                checks_to_best, seconds_to_best = checked, round(time.time() - t0, 3)
                trajectory.append([checked, round(time.time() - t0, 3), v])
                cert = {
                    "problem_id": problem_id, "problem_hash": p_hash,
                    "candidate": c, "candidate_hash": hash_obj(c),
                    "verdict": {"valid": True, "score": verdict.score,
                                "transcript": verdict.transcript},
                    "checker": verdict.checker, "trust": verdict.trust,
                    "provenance": {**prop.provenance(), "seed": seed, "attempt": checked},
                    "created_at": now_iso(),
                }
                best_cert = ledger.store_certificate(cert)
                ledger.append("certificate", {"cert": best_cert, "problem_id": problem_id,
                                              "value": v, "proposer": proposer})
                if not quiet:
                    print(f"  [{problem_id}] new best {problem['objective'].get('field')}={v:g} "
                          f"after {checked} checks ({proposer})", file=sys.stderr)
            ctx.best = sorted(ctx.best + [(v, c)], key=lambda t: -t[0]
                              if problem["objective"]["sense"] != "minimize" else t[0])[:10]
        prop.observe(feedback)

    complete = bool(prop.exhaustive and prop.done)
    summary = {
        "problem_id": problem_id, "problem_hash": p_hash, "proposer": proposer,
        "provenance": prop.provenance(), "seed": seed,
        "candidates_checked": checked, "valid": valid, "duplicates_skipped": dup,
        "best_value": best_v, "best_cert": best_cert,
        "exhaustive_complete": complete,
        "checks_to_best": checks_to_best, "seconds_to_best": seconds_to_best,
        "valid_rate": round(valid / checked, 6) if checked else None,
        "invalid_reasons": dict(sorted(reasons.items(), key=lambda t: -t[1])[:8]),
        "trajectory": trajectory[-200:],
        "arm": opts.get("arm", proposer), "protocol": opts.get("protocol"),
        "budget": budget, "time_cap_s": seconds,
        "status": status_vs_known(problem, best_v),
        "seconds": round(time.time() - t0, 2), "cost_usd": round(prop.cost_usd, 6),
    }
    ledger.append("run", summary)
    return summary


def _reason_class(reason: str) -> str:
    """Group checker rejection messages into classes (drop instance specifics)."""
    import re
    r = re.sub(r"\d+", "#", reason or "unknown")
    r = re.sub(r"'[^']*'|\"[^\"]*\"", "…", r)
    return r[:80]


def verify(cert_ref: str, results_dir: Path | None = None) -> tuple[bool, str]:
    """Re-run the checker on a stored certificate from scratch."""
    ledger = Ledger(results_dir or DEFAULT_RESULTS)
    cert = ledger.load_certificate(cert_ref)
    problem = registry.get(cert["problem_id"])
    if registry.problem_hash(problem) != cert["problem_hash"]:
        return False, "problem specification changed since certification"
    if hash_obj(cert["candidate"]) != cert["candidate_hash"]:
        return False, "candidate hash mismatch"
    verdict = get_checker(problem["checker"]).check(problem, cert["candidate"])
    if not verdict.valid:
        return False, f"checker rejects candidate: {verdict.reason}"
    if verdict.score != cert["verdict"]["score"]:
        return False, f"score differs: {verdict.score} vs {cert['verdict']['score']}"
    return True, f"{cert['problem_id']}: re-verified {verdict.score}"
