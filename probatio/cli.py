"""Command line: probatio problems | run | verify | audit | report"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import orchestrator, registry, report, site, study
from .ledger import Ledger


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="probatio", description="Verified discovery engine")
    ap.add_argument("--results", type=Path, default=orchestrator.DEFAULT_RESULTS)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("problems", help="list registered problems")

    r = sub.add_parser("run", help="search a problem")
    r.add_argument("problem")
    r.add_argument("--proposer", default="mutation")
    r.add_argument("--budget", type=int, default=10_000, help="max candidates checked")
    r.add_argument("--seconds", type=float, default=300)
    r.add_argument("--max-usd", type=float, default=0.0, help="spend cap for paid models")
    r.add_argument("--seed", type=int, default=0)
    r.add_argument("--batch", type=int, default=64)

    v = sub.add_parser("verify", help="re-verify certificates from scratch")
    v.add_argument("cert", nargs="?")
    v.add_argument("--all", action="store_true")

    sub.add_parser("audit", help="check ledger hash chain and certificate integrity")
    sub.add_parser("report", help="build static HTML report")
    sub.add_parser("site", help="build the public results site (results/site/index.html)")
    st = sub.add_parser("study", help="pre-registered study: run | analyze | notebook | plan")
    st.add_argument("action", choices=["run", "analyze", "notebook", "plan"])
    st.add_argument("--protocol", type=Path, default=registry.ROOT / "experiments" / "protocol-v1.json")
    st.add_argument("--jobs", type=int, default=2)
    st.add_argument("--arms", nargs="*")
    nt = sub.add_parser("note", help="append an operator note to the ledger")
    nt.add_argument("text")
    nt.add_argument("--author", default="operator")

    a = ap.parse_args(argv)

    if a.cmd == "problems":
        for pid, p in registry.load_all().items():
            kb = (p.get("known_best") or {}).get("value")
            print(f"{pid:28s} {p['domain']:15s} {p['objective']['sense']:9s} known_best={kb}")
        return 0

    if a.cmd == "run":
        s = orchestrator.run(a.problem, a.proposer, budget=a.budget, seconds=a.seconds,
                             max_usd=a.max_usd, seed=a.seed, batch=a.batch, results_dir=a.results)
        print(json.dumps(s, indent=2))
        return 0

    if a.cmd == "verify":
        led = Ledger(a.results)
        refs = [h for h, _ in led.iter_certificates()] if a.all else [a.cert]
        if not refs or refs == [None]:
            ap.error("give a certificate hash/path or --all")
        failures = 0
        for ref in refs:
            ok, msg = orchestrator.verify(ref, a.results)
            failures += not ok
            print(("PASS " if ok else "FAIL ") + f"{ref[:16]}  {msg}")
        print(f"{len(refs) - failures}/{len(refs)} certificates re-verified")
        return 1 if failures else 0

    if a.cmd == "audit":
        problems = Ledger(a.results).audit()
        if problems:
            print("AUDIT FAILED"); print("\n".join(problems))
            return 1
        print(f"ledger intact: {len(Ledger(a.results).entries())} entries")
        return 0

    if a.cmd == "report":
        print(report.build(a.results))
        return 0
    if a.cmd == "study":
        if a.action == "run":
            study.run_study(a.protocol, a.results, jobs=a.jobs, arms=a.arms)
        elif a.action == "analyze":
            print(study.analyze(a.results))
        elif a.action == "notebook":
            print(study.notebook(a.results))
        elif a.action == "plan":
            proto = json.loads(a.protocol.read_text())
            runs = study.planned_runs(proto, a.arms)
            print(f"{len(runs)} runs, ~{sum(r['seconds'] for r in runs) / 3600:.1f} h of wall clock before parallelism")
        return 0
    if a.cmd == "note":
        e = study.add_note(a.results, a.text, a.author)
        print(f"note recorded as ledger entry {e['seq']}")
        return 0
    if a.cmd == "site":
        page, _ = site.build(a.results)
        print(page)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
