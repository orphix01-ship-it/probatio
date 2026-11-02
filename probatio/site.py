"""Public results site: one static HTML file built from the ledger and certificates.

Certificates and ledger entries are embedded as the exact canonical strings that
were hashed, so the page can recompute every hash in the browser and display
only what it has verified.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import registry
from .ledger import Ledger
from .util import canonical_json

ASSETS = Path(__file__).resolve().parent / "site_assets"


def build_data(results_dir: Path) -> dict[str, Any]:
    ledger = Ledger(results_dir)
    problems = registry.load_all()
    entries = ledger.entries()
    runs = [e["body"] for e in entries if e["type"] == "run"]
    certs = {h: c for h, c in ledger.iter_certificates()}

    results = []
    for pid, p in problems.items():
        pruns = [r for r in runs if r["problem_id"] == pid]
        if not pruns:
            continue
        best = None
        for r in pruns:
            if r["best_value"] is not None and (best is None or registry.better(p, r["best_value"], best["best_value"])):
                best = r
        results.append({
            "id": pid,
            "domain": p["domain"],
            "statement": p["statement"],
            "checker": p["checker"],
            "params": p["params"],
            "objective": p["objective"],
            "known_best": p.get("known_best"),
            "upper_bound": p.get("upper_bound"),
            "references": p.get("references", []),
            "role": p.get("role", "calibration"),
            "best_value": best["best_value"] if best else None,
            "best_cert": best["best_cert"] if best else None,
            "status": best["status"] if best else "no-valid-result",
            "exhaustive": any(r["exhaustive_complete"] and best and r["best_value"] == best["best_value"]
                              for r in pruns),
            "attempts": sum(r["candidates_checked"] for r in pruns),
            "seconds": round(sum(r["seconds"] for r in pruns), 1),
            "cost_usd": round(sum(r.get("cost_usd", 0) for r in pruns), 4),
            "runs": [{k: r[k] for k in ("proposer", "candidates_checked", "best_value",
                                        "exhaustive_complete", "seconds", "status")} for r in pruns],
        })

    used = {r["best_cert"] for r in results if r["best_cert"]}
    return {
        "results": results,
        "certs": {h: canonical_json(certs[h]) for h in used},
        "ledger": [{"core": canonical_json({k: e[k] for k in ("seq", "prev", "type", "body", "time")}),
                    "hash": e["hash"]} for e in entries],
        "generated": entries[-1]["time"] if entries else None,
        "total_certs": len(certs),
    }


def build(results_dir: Path, out_dir: Path | None = None) -> tuple[Path, Path]:
    """Write the GitHub Pages site (full document) and an embeddable fragment."""
    data = build_data(results_dir)
    template = (ASSETS / "template.html").read_text()
    verify_js = (ASSETS / "verify.js").read_text()
    blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    fragment = template.replace("/*__VERIFY_JS__*/", verify_js).replace("/*__DATA__*/null", blob)
    out_dir = Path(out_dir or Path(results_dir) / "site")
    out_dir.mkdir(parents=True, exist_ok=True)
    frag_path = out_dir / "fragment.html"
    frag_path.write_text(fragment)
    page_path = out_dir / "index.html"
    page_path.write_text('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
                         '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
                         '</head><body>\n' + fragment + "\n</body></html>\n")
    return page_path, frag_path
