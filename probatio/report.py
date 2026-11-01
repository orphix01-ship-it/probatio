"""Static, dependency-free HTML report built from the ledger."""
from __future__ import annotations

import html
from pathlib import Path

from . import registry
from .ledger import Ledger


def build(results_dir: Path, out: Path | None = None) -> Path:
    ledger = Ledger(results_dir)
    problems = registry.load_all()
    runs = [e["body"] for e in ledger.entries() if e["type"] == "run"]
    audit = ledger.audit()

    rows = []
    for pid, p in problems.items():
        pruns = [r for r in runs if r["problem_id"] == pid]
        if not pruns:
            continue
        valued = [r for r in pruns if r["best_value"] is not None]
        best = None
        for r in valued:
            if best is None or registry.better(p, r["best_value"], best["best_value"]):
                best = r
        complete = any(r["exhaustive_complete"] and best and r["best_value"] == best["best_value"]
                       for r in pruns)
        attempts = sum(r["candidates_checked"] for r in pruns)
        cost = sum(r.get("cost_usd", 0) for r in pruns)
        kb = (p.get("known_best") or {}).get("value")
        ub = (p.get("upper_bound") or {}).get("value")
        cert = best["best_cert"] if best else None
        cert_obj = ledger.load_certificate(cert) if cert else None
        witness = ""
        if cert_obj:
            c = cert_obj["candidate"]
            witness = c.get("seed") or c.get("marks") or "Lean proof"
        rows.append(f"""<tr>
<td class="mono">{html.escape(pid)}</td>
<td>{html.escape(p['domain'])}</td>
<td class="num">{'' if not best else f"{best['best_value']:g}"}</td>
<td class="num">{'' if kb is None else kb}</td>
<td class="num">{'' if ub is None else ub}</td>
<td><span class="tag {html.escape(best['status'] if best else 'none')}">{html.escape(best['status'] if best else 'no result')}</span>
{'<span class="tag exh">optimal in family (exhaustive)</span>' if complete else ''}</td>
<td class="mono small">{html.escape(str(witness))}</td>
<td class="num">{attempts:,}</td>
<td class="num">${cost:.2f}</td>
<td class="mono small">{'' if not cert else f'probatio verify {cert[:16]}…'}</td>
</tr>""")

    audit_html = ("<p class='ok'>Ledger audit: intact — "
                  f"{len(ledger.entries())} entries, hash chain verified.</p>" if not audit else
                  "<p class='bad'>Ledger audit FAILED:<br>" + "<br>".join(map(html.escape, audit)) + "</p>")
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PROBATIO Results</title>
<style>
:root{{--bg:#fff;--fg:#111;--mut:#666;--line:#e5e5e5;--acc:#8a6d1f}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0e0e10;--fg:#eee;--mut:#999;--line:#2a2a2e;--acc:#c79a4a}}}}
body{{background:var(--bg);color:var(--fg);font:300 15px/1.5 -apple-system,Helvetica,Arial,sans-serif;margin:0;padding:32px 16px}}
main{{max-width:1200px;margin:auto}} h1{{font-weight:300;letter-spacing:.08em;margin:0}}
.sub{{color:var(--mut);margin:4px 0 24px}} .wrap{{overflow-x:auto}}
table{{border-collapse:collapse;width:100%;font-size:13px}} th,td{{border-bottom:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:top}}
th{{font-weight:400;color:var(--mut);text-transform:uppercase;font-size:11px;letter-spacing:.06em}}
.num{{text-align:right;font-variant-numeric:tabular-nums}} .mono{{font-family:ui-monospace,Menlo,monospace}} .small{{font-size:11px}}
.tag{{display:inline-block;border:1px solid var(--line);padding:1px 6px;margin:1px 2px 1px 0;font-size:11px}}
.CANDIDATE-NEW{{border-color:var(--acc);color:var(--acc)}} .exh{{color:var(--mut)}}
.ok{{color:var(--mut)}} .bad{{color:#c0392b}} footer{{color:var(--mut);font-size:12px;margin-top:24px}}
</style></head><body><main>
<h1>PROBATIO</h1>
<p class="sub">Verified discovery engine — every result below is re-checkable from its certificate.</p>
{audit_html}
<div class="wrap"><table><thead><tr><th>Problem</th><th>Domain</th><th>Certified</th><th>Known best</th>
<th>Upper bound</th><th>Status</th><th>Witness</th><th>Checked</th><th>Cost</th><th>Verify</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>
<footer>Experimental, unaudited. Verification proves correctness, not novelty: any CANDIDATE-NEW
result requires a human literature review before it is claimed. "Optimal in family" is evidence from
an open exhaustive search, separate from the checker certificate.</footer>
</main></body></html>"""
    out = out or Path(results_dir) / "report.html"
    out.write_text(page)
    return out
