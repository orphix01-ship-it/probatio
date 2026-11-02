"""Pre-registered study runner, analysis and lab notebook.

The protocol file is hashed and written as the first ledger entry of the study.
Every later invocation re-hashes the file and refuses to run if it differs, so
the design cannot be changed after results start coming in.
"""
from __future__ import annotations

import csv
import json
import math
import os
import subprocess
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from . import orchestrator, registry
from .ledger import Ledger
from .util import now_iso, sha256_hex


def protocol_hash(path: Path) -> str:
    return sha256_hex(Path(path).read_bytes())


def _git_commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                              cwd=registry.ROOT, timeout=5).stdout.strip() or None
    except Exception:
        return None


def register(protocol_path: Path, results: Path) -> dict[str, Any]:
    """Write the protocol hash as ledger entry 0, or confirm it is unchanged."""
    led = Ledger(results)
    h = protocol_hash(protocol_path)
    ents = led.entries()
    if not ents:
        proto = json.loads(Path(protocol_path).read_text())
        return led.append("protocol", {"protocol_id": proto["id"], "sha256": h,
                                       "file": str(Path(protocol_path).name), "git_commit": _git_commit(),
                                       "registered_at": now_iso()})
    first = ents[0]
    if first["type"] != "protocol":
        raise SystemExit("study ledger does not start with a protocol registration")
    if first["body"]["sha256"] != h:
        raise SystemExit("PROTOCOL CHANGED since registration: refusing to run. "
                         "Create a new protocol version instead.")
    return first


def planned_runs(proto: dict[str, Any], arms: list[str] | None = None) -> list[dict[str, Any]]:
    runs = []
    for arm in proto["arms"]:
        if arms and arm["name"] not in arms:
            continue
        if not arms and arm["status"] != "active":
            continue
        for pid in proto["problems"]:
            for seed in arm["seeds"]:
                runs.append({"problem": pid, "arm": arm["name"], "proposer": arm["proposer"], "seed": seed,
                             "seconds": arm["seconds"], "budget": arm["budget"], "batch": arm["batch"],
                             "max_usd": arm.get("max_usd", 0.0)})
    ex = proto.get("exhaustive")
    if ex and (not arms or ex["name"] in arms) and (arms or ex["status"] == "active"):
        for pid in ex["problems"]:
            runs.append({"problem": pid, "arm": ex["name"], "proposer": "exhaustive", "seed": 0,
                         "seconds": ex["seconds"], "budget": 10 ** 9, "batch": ex["batch"], "max_usd": 0.0})
    return runs


def _done_keys(results: Path) -> set[tuple]:
    keys = set()
    for e in Ledger(results).entries():
        if e["type"] == "run" and e["body"].get("protocol"):
            b = e["body"]
            keys.add((b["problem_id"], b.get("arm"), b.get("seed")))
    return keys


def _execute(job: dict[str, Any], results: str, protocol_id: str) -> dict[str, Any]:
    try:
        return orchestrator.run(job["problem"], job["proposer"], budget=job["budget"], seconds=job["seconds"],
                                max_usd=job["max_usd"], seed=job["seed"], batch=job["batch"],
                                results_dir=Path(results), quiet=True, arm=job["arm"], protocol=protocol_id)
    except Exception as exc:  # recorded, never silently dropped
        Ledger(Path(results)).append("run-error", {"problem_id": job["problem"], "arm": job["arm"],
                                                    "seed": job["seed"], "error": repr(exc)[:500],
                                                    "protocol": protocol_id})
        return {"problem_id": job["problem"], "arm": job["arm"], "error": repr(exc)}


def run_study(protocol_path: Path, results: Path, jobs: int = 2, arms: list[str] | None = None) -> None:
    proto = json.loads(Path(protocol_path).read_text())
    register(protocol_path, results)
    if arms:
        for a in proto["arms"]:
            if a["name"] in arms and a["status"] == "pending" and a["proposer"] in ("llm", "program_evolution"):
                if not os.environ.get("ANTHROPIC_API_KEY"):
                    raise SystemExit(f"arm {a['name']} needs ANTHROPIC_API_KEY")
    todo = [j for j in planned_runs(proto, arms) if (j["problem"], j["arm"], j["seed"]) not in _done_keys(results)]
    # longest first, so exhaustive runs do not straggle at the end
    todo.sort(key=lambda j: -j["seconds"])
    print(f"{len(todo)} runs to do ({jobs} parallel)")
    with ProcessPoolExecutor(jobs) as ex:
        futs = {ex.submit(_execute, j, str(results), proto["id"]): j for j in todo}
        for i, f in enumerate(as_completed(futs), 1):
            r = f.result()
            print(f"[{i}/{len(todo)}] {r.get('problem_id')} {r.get('arm')} -> "
                  f"{r.get('best_value', r.get('error'))} {r.get('status', '')}", flush=True)


# ---------------------------------------------------------------- analysis
def _ref(p: dict[str, Any]) -> float | None:
    kb = p.get("known_best")
    return float(kb["value"]) if kb and kb.get("value") is not None else None


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    ph = k / n
    den = 1 + z * z / n
    c = (ph + z * z / (2 * n)) / den
    h = z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / den
    return (max(0.0, c - h), min(1.0, c + h))


def family_of(pid: str) -> str:
    return {"qec": "Cyclic quantum codes", "golomb": "Golomb rulers", "capset": "Cap sets",
            "lincode": "Binary linear codes", "spread": "Point spreading"}[pid.split(".")[0]]


def collect(results: Path) -> list[dict[str, Any]]:
    probs = registry.load_all()
    rows = []
    for e in Ledger(results).entries():
        if e["type"] not in ("run", "run-error") or not e["body"].get("protocol"):
            continue
        b = e["body"]
        p = probs[b["problem_id"]]
        ref = _ref(p)
        best = b.get("best_value")
        gap = None
        if ref and best is not None:
            gap = abs(best - ref) / ref
        rows.append({
            "problem": b["problem_id"], "family": family_of(b["problem_id"]), "role": p.get("role", "calibration"),
            "arm": b.get("arm"), "seed": b.get("seed"), "best": best, "reference": ref,
            "status": b.get("status", "error"), "success": int(b.get("status") == "matches-known"),
            "new": int(b.get("status") == "CANDIDATE-NEW"), "gap": gap,
            "checked": b.get("candidates_checked"), "valid_rate": b.get("valid_rate"),
            "checks_to_best": b.get("checks_to_best"), "seconds_to_best": b.get("seconds_to_best"),
            "seconds": b.get("seconds"), "cost_usd": b.get("cost_usd", 0.0), "exhaustive": b.get("exhaustive_complete"),
            "cert": b.get("best_cert"), "error": b.get("error"), "trajectory": b.get("trajectory", []),
        })
    return rows


def _median(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2


def summarise(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    keys = sorted({(r["family"], r["arm"]) for r in rows})
    for fam, arm in keys:
        rs = [r for r in rows if r["family"] == fam and r["arm"] == arm and r["role"] == "calibration"]
        if not rs:
            continue
        k, n = sum(r["success"] for r in rs), len(rs)
        lo, hi = wilson(k, n)
        out.append({"family": fam, "arm": arm, "runs": n, "successes": k, "success_rate": k / n,
                    "ci_low": lo, "ci_high": hi, "median_gap": _median([r["gap"] for r in rs]),
                    "median_valid_rate": _median([r["valid_rate"] for r in rs]),
                    "median_checks_to_best": _median([r["checks_to_best"] for r in rs]),
                    "cost_usd": sum(r["cost_usd"] or 0 for r in rs)})
    return out


def fisher_exact(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher exact test for [[a, b], [c, d]]."""
    from math import comb
    n1, n2, m1 = a + b, c + d, a + c
    N = n1 + n2

    def p(x):
        return comb(n1, x) * comb(n2, m1 - x) / comb(N, m1)
    p0 = p(a)
    lo, hi = max(0, m1 - n2), min(n1, m1)
    return min(1.0, sum(p(x) for x in range(lo, hi + 1) if p(x) <= p0 * (1 + 1e-9)))


def analyze(results: Path) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out = Path(results) / "analysis"
    (out / "tables").mkdir(parents=True, exist_ok=True)
    (out / "figures").mkdir(parents=True, exist_ok=True)
    rows = collect(results)
    with (out / "runs.csv").open("w", newline="") as fh:
        cols = [c for c in rows[0].keys() if c != "trajectory"] if rows else []
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    summ = summarise(rows)
    with (out / "summary.csv").open("w", newline="") as fh:
        if summ:
            w = csv.DictWriter(fh, fieldnames=list(summ[0].keys()))
            w.writeheader()
            w.writerows(summ)

    # Fisher tests: anneal vs random per family, Holm-adjusted
    tests = []
    for fam in sorted({r["family"] for r in rows}):
        a = [r for r in rows if r["family"] == fam and r["arm"] == "anneal" and r["role"] == "calibration"]
        b = [r for r in rows if r["family"] == fam and r["arm"] == "random" and r["role"] == "calibration"]
        if a and b:
            sa, sb = sum(r["success"] for r in a), sum(r["success"] for r in b)
            tests.append({"family": fam, "anneal": f"{sa}/{len(a)}", "random": f"{sb}/{len(b)}",
                          "p": fisher_exact(sa, len(a) - sa, sb, len(b) - sb)})
    m = len(tests)
    for rank, t in enumerate(sorted(tests, key=lambda t: t["p"])):
        t["p_holm"] = min(1.0, t["p"] * (m - rank))
    prev = 0.0
    for t in sorted(tests, key=lambda t: t["p"]):
        t["p_holm"] = max(t["p_holm"], prev)
        prev = t["p_holm"]

    # per-problem best across all arms (incl. open targets)
    probs = registry.load_all()
    per_problem = []
    for pid in sorted({r["problem"] for r in rows}, key=_problem_sort):
        rs = [r for r in rows if r["problem"] == pid and r["best"] is not None]
        p = probs[pid]
        best = None
        for r in rs:
            if best is None or registry.better(p, r["best"], best["best"]):
                best = r
        per_problem.append({"problem": pid, "family": family_of(pid), "role": p.get("role", "calibration"),
                            "reference": _ref(p), "upper": (p.get("upper_bound") or {}).get("value"),
                            "best": best["best"] if best else None, "arm": best["arm"] if best else None,
                            "status": best["status"] if best else "no result"})

    _write_tables(out, summ, tests, per_problem)
    _figures(out, rows, per_problem, plt)
    (out / "analysis.json").write_text(json.dumps({"summary": summ, "tests": tests, "per_problem": per_problem,
                                                    "runs": len(rows), "generated": now_iso()}, indent=2))
    return out


def _problem_sort(pid: str):
    parts = pid.split(".")
    nums = [int("".join(ch for ch in x if ch.isdigit()) or 0) for x in parts[1:]]
    return (parts[0], nums)


def _fmt(x, nd=3):
    if x is None:
        return "—"
    if isinstance(x, float):
        return f"{x:.{nd}f}"
    return str(x)


def _write_tables(out: Path, summ, tests, per_problem) -> None:
    md = ["| Family | Arm | Runs | Success | 95% CI | Median gap | Median valid rate | Median checks to best |",
          "|---|---|---|---|---|---|---|---|"]
    tex = [r"\begin{tabular}{llrrcrrr}", r"\toprule",
           r"Family & Arm & Runs & Success & 95\% CI & Med.\ gap & Valid & Checks to best\\", r"\midrule"]
    for s in summ:
        md.append(f"| {s['family']} | {s['arm']} | {s['runs']} | {s['successes']}/{s['runs']} | "
                  f"{_fmt(s['ci_low'], 2)}–{_fmt(s['ci_high'], 2)} | {_fmt(s['median_gap'])} | "
                  f"{_fmt(s['median_valid_rate'], 2)} | {_fmt(s['median_checks_to_best'], 0)} |")
        tex.append(f"{s['family']} & {s['arm']} & {s['runs']} & {s['successes']}/{s['runs']} & "
                   f"[{_fmt(s['ci_low'], 2)}, {_fmt(s['ci_high'], 2)}] & {_fmt(s['median_gap'])} & "
                   f"{_fmt(s['median_valid_rate'], 2)} & {_fmt(s['median_checks_to_best'], 0)}\\\\")
    tex += [r"\bottomrule", r"\end{tabular}"]
    (out / "tables" / "summary.md").write_text("\n".join(md) + "\n")
    (out / "tables" / "summary.tex").write_text("\n".join(tex) + "\n")

    md = ["| Family | Anneal | Random | Fisher p | Holm p |", "|---|---|---|---|---|"]
    tex = [r"\begin{tabular}{lrrrr}", r"\toprule", r"Family & Anneal & Random & Fisher $p$ & Holm $p$\\", r"\midrule"]
    for t in tests:
        md.append(f"| {t['family']} | {t['anneal']} | {t['random']} | {t['p']:.3g} | {t['p_holm']:.3g} |")
        tex.append(f"{t['family']} & {t['anneal']} & {t['random']} & {t['p']:.3g} & {t['p_holm']:.3g}\\\\")
    tex += [r"\bottomrule", r"\end{tabular}"]
    (out / "tables" / "tests.md").write_text("\n".join(md) + "\n")
    (out / "tables" / "tests.tex").write_text("\n".join(tex) + "\n")

    md = ["| Problem | Role | Reference | Upper bound | Best certified | Arm | Status |", "|---|---|---|---|---|---|---|"]
    tex = [r"\begin{longtable}{llrrrll}", r"\toprule", r"Problem & Role & Ref. & Upper & Best & Arm & Status\\",
           r"\midrule", r"\endhead"]
    for p in per_problem:
        best = _fmt(p["best"], 4) if isinstance(p["best"], float) and not float(p["best"]).is_integer() else _fmt(int(p["best"]) if p["best"] is not None else None)
        ref = _fmt(p["reference"], 4) if isinstance(p["reference"], float) and not float(p["reference"]).is_integer() else _fmt(int(p["reference"]) if p["reference"] is not None else None)
        md.append(f"| {p['problem']} | {p['role']} | {ref} | {_fmt(p['upper'])} | {best} | {p['arm'] or '—'} | {p['status']} |")
        tex.append(f"\\texttt{{{p['problem']}}} & {p['role']} & {ref} & {_fmt(p['upper'])} & {best} & "
                   f"{p['arm'] or '---'} & {p['status']}\\\\")
    tex += [r"\bottomrule", r"\end{longtable}"]
    (out / "tables" / "problems.md").write_text("\n".join(md) + "\n")
    (out / "tables" / "problems.tex").write_text("\n".join(tex) + "\n")


def _figures(out: Path, rows, per_problem, plt) -> None:
    plt.rcParams.update({"font.size": 9, "font.family": "serif", "axes.spines.top": False,
                         "axes.spines.right": False})
    arms = [a for a in ("random", "anneal", "exhaustive", "llm-direct", "llm-program")
            if any(r["arm"] == a for r in rows)]
    fams = sorted({r["family"] for r in rows})
    # Figure 1: success rate by family and arm
    fig, ax = plt.subplots(figsize=(6.4, 2.8))
    width = 0.8 / max(1, len(arms))
    for i, arm in enumerate(arms):
        ys, lo, hi = [], [], []
        for f in fams:
            rs = [r for r in rows if r["family"] == f and r["arm"] == arm and r["role"] == "calibration"]
            if rs:
                k, n = sum(r["success"] for r in rs), len(rs)
                l, h = wilson(k, n)
                ys.append(k / n); lo.append(k / n - l); hi.append(h - k / n)
            else:
                ys.append(0); lo.append(0); hi.append(0)
        xs = [j + (i - (len(arms) - 1) / 2) * width for j in range(len(fams))]
        ax.bar(xs, ys, width * 0.92, yerr=[lo, hi], capsize=2, label=arm,
               color=["#9aa0a6", "#8a6a1c", "#15171b", "#2a5a96", "#94304f"][i % 5], error_kw={"lw": 0.7})
    ax.set_xticks(range(len(fams)), [f.replace(" ", "\n") for f in fams])
    ax.set_ylabel("success rate"); ax.set_ylim(0, 1.08)
    ax.legend(frameon=False, ncol=len(arms), loc="upper center", bbox_to_anchor=(0.5, 1.18))
    fig.tight_layout(); fig.savefig(out / "figures" / "success_by_family.pdf"); fig.savefig(out / "figures" / "success_by_family.svg"); plt.close(fig)

    # Figure 2: normalised gap per problem (anneal vs random, median over seeds)
    probs_list = [p["problem"] for p in per_problem if p["reference"]]
    fig, ax = plt.subplots(figsize=(6.4, 3.2))
    for arm, mk, col in (("random", "o", "#9aa0a6"), ("anneal", "s", "#8a6a1c")):
        ys = [_median([r["gap"] for r in rows if r["problem"] == pid and r["arm"] == arm]) for pid in probs_list]
        ax.scatter(range(len(probs_list)), [y if y is not None else float("nan") for y in ys], marker=mk, s=14, label=arm, color=col)
    ax.set_xticks(range(len(probs_list)), probs_list, rotation=90, fontsize=5.5)
    ax.set_ylabel("normalised gap to reference"); ax.set_yscale("symlog", linthresh=1e-3)
    ax.legend(frameon=False)
    fig.tight_layout(); fig.savefig(out / "figures" / "gap_by_problem.pdf"); fig.savefig(out / "figures" / "gap_by_problem.svg"); plt.close(fig)

    # Figure 3: anytime curves for selected problems
    sel = [p for p in ("lincode.n24.k12", "capset.n6", "spread.n10", "golomb.m10") if any(r["problem"] == p for r in rows)]
    if sel:
        fig, axes = plt.subplots(1, len(sel), figsize=(6.4, 2.2))
        axes = axes if len(sel) > 1 else [axes]
        for ax, pid in zip(axes, sel):
            for r in rows:
                if r["problem"] != pid or r["arm"] not in ("random", "anneal") or not r["trajectory"]:
                    continue
                xs = [max(1, t[0]) for t in r["trajectory"]] + [max(1, r["checked"] or 1)]
                ys = [t[2] for t in r["trajectory"]] + [r["trajectory"][-1][2]]
                ax.step(xs, ys, where="post", lw=0.8, color="#8a6a1c" if r["arm"] == "anneal" else "#9aa0a6")
            ref = next(p["reference"] for p in per_problem if p["problem"] == pid)
            if ref:
                ax.axhline(ref, ls="--", lw=0.7, color="#15171b")
            ax.set_xscale("log"); ax.set_title(pid, fontsize=8); ax.set_xlabel("checks", fontsize=7)
            ax.tick_params(labelsize=6)
        fig.tight_layout(); fig.savefig(out / "figures" / "anytime.pdf"); fig.savefig(out / "figures" / "anytime.svg"); plt.close(fig)


# ---------------------------------------------------------------- notebook
def notebook(results: Path) -> Path:
    led = Ledger(results)
    lines = ["# PROBATIO study lab notebook", "",
             "Generated from the hash-chained study ledger. Every entry below corresponds to a ledger entry; "
             "operator notes are recorded with `probatio note`.", ""]
    day = None
    for e in led.entries():
        t = e.get("time", "")
        d = t[:10]
        if d != day:
            lines += ["", f"## {d}", ""]
            day = d
        b = e["body"]
        if e["type"] == "protocol":
            lines.append(f"- **{t[11:19]} Protocol registered** `{b['protocol_id']}`, sha256 `{b['sha256'][:16]}…`, "
                         f"commit `{(b.get('git_commit') or '')[:10]}`.")
        elif e["type"] == "note":
            lines.append(f"- **{t[11:19]} Note** ({b.get('author', 'operator')}): {b['text']}")
        elif e["type"] == "run":
            extra = " — exhaustive search complete" if b.get("exhaustive_complete") else ""
            lines.append(f"- {t[11:19]} `{b['problem_id']}` · {b.get('arm')} · seed {b.get('seed')}: best "
                         f"{b.get('best_value')} ({b.get('status')}), {b.get('candidates_checked'):,} checked, "
                         f"valid rate {b.get('valid_rate')}{extra}.")
        elif e["type"] == "run-error":
            lines.append(f"- {t[11:19]} **Run failed** `{b['problem_id']}` · {b.get('arm')} · seed {b.get('seed')}: {b['error']}")
        elif e["type"] == "certificate" and b.get("value") is not None:
            continue
    p = Path(results) / "NOTEBOOK.md"
    p.write_text("\n".join(lines) + "\n")
    return p


def add_note(results: Path, text: str, author: str = "operator") -> dict[str, Any]:
    return Ledger(results).append("note", {"text": text, "author": author})
