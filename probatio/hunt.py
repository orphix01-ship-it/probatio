"""Record hunting: long, resumable, exploratory searches on open targets.

A hunt is not part of a pre-registered study. It runs repeated searches with
fresh seeds until a time limit, records every run in its own ledger, and when a
checker-certified value beats the recorded best it writes the candidate to
CANDIDATES.md for the mandatory literature review before any claim.
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from . import orchestrator, registry
from .ledger import Ledger


def _next_seed(results: Path, pid: str, arm: str) -> int:
    seeds = [e["body"].get("seed", 0) for e in Ledger(results).entries()
             if e["type"] == "run" and e["body"]["problem_id"] == pid and e["body"].get("arm") == arm]
    return max(seeds, default=0) + 1


def _one(pid: str, seed: int, results: str, arm: str, proposer: str, seconds: float, opts: dict) -> dict:
    return orchestrator.run(pid, proposer, budget=10 ** 12, seconds=seconds, seed=seed, batch=64,
                            results_dir=Path(results), quiet=True, arm=arm, **opts)


def _record_candidate(results: Path, r: dict[str, Any]) -> Path:
    led = Ledger(results)
    cert = led.load_certificate(r["best_cert"])
    p = registry.get(r["problem_id"])
    out = results / "CANDIDATES.md"
    block = [f"## {r['problem_id']}: certified {r['best_value']} > recorded {p['known_best']['value']}",
             "", f"- certificate: `{r['best_cert']}`", f"- reference: {p['known_best']['source']}",
             f"- found by: {r.get('arm')} seed {r.get('seed')}", "- status: UNREVIEWED. Before any claim: re-verify,"
             " re-check the live table, search the literature, then submit to the table maintainer.", "",
             "```json", json.dumps(cert["candidate"], indent=1), "```", ""]
    with out.open("a") as fh:
        fh.write("\n".join(block) + "\n")
    return out


def hunt(problems: list[str], results: Path, hours: float, jobs: int = 2, proposer: str = "mutation",
         seconds_per_run: float = 900, opts: dict[str, Any] | None = None) -> list[dict]:
    opts = dict(opts or {})
    arm = "hunt-" + (opts.get("search_space") or "default") + "-" + proposer
    deadline = time.time() + hours * 3600
    seeds = {pid: _next_seed(results, pid, arm) for pid in problems}
    found: list[dict] = []
    best: dict[str, float] = {}
    with ProcessPoolExecutor(jobs) as ex:
        futs = {}

        def submit(pid):
            futs[ex.submit(_one, pid, seeds[pid], str(results), arm, proposer, seconds_per_run, opts)] = pid
            seeds[pid] += 1

        queue = list(problems)
        for i in range(jobs):
            submit(queue[i % len(queue)])
        nxt = jobs
        while futs:
            for f in as_completed(list(futs)):
                pid = futs.pop(f)
                r = f.result()
                if r["best_value"] is not None and (pid not in best or registry.better(registry.get(pid),
                                                                                        r["best_value"], best[pid])):
                    best[pid] = r["best_value"]
                print(f"{pid} seed {r['seed']}: {r['best_value']} ({r['status']}); best this hunt {best.get(pid)}",
                      flush=True)
                if r["status"] == "CANDIDATE-NEW":
                    path = _record_candidate(results, r)
                    found.append(r)
                    print(f"*** CANDIDATE-NEW {pid} = {r['best_value']} — written to {path}; review before any claim",
                          flush=True)
                if time.time() + seconds_per_run < deadline:
                    submit(queue[nxt % len(queue)])
                    nxt += 1
                break
    return found
