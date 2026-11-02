# PROBATIO Study v1 — Pre-registered protocol

**Protocol id:** `probatio-study-v1`
**Status:** frozen before any study run. The machine-readable form is
`experiments/protocol-v1.json`; its SHA-256 is written as entry 0 of the study ledger
(`results/study-v1/ledger.jsonl`), and the runner refuses to execute if the file changes.
Amendments are made only as a new protocol version with a stated reason.

## 1. Research questions

- **RQ1 — Validity.** When candidates are checked exactly, what fraction of each
  search method's proposals are valid? (For AI methods: how often are model-generated
  mathematical objects actually correct?)
- **RQ2 — Calibration.** How often does each method reach the known optimum or best
  known value within a fixed budget, across problem families?
- **RQ3 — Efficiency.** How many checked candidates, how much time, and how much model
  spend does each method need to reach its best value and, where reached, the reference?
- **RQ4 — Discovery.** Does any method produce a certified result that beats a recorded
  best known value on an open target? Any such result is reported only after the
  literature review in §7.

## 2. Problems

Six families, 43 scored problems (Lean problems are excluded from scoring until a Lean
toolchain is part of the reproducibility image):

| Family | Problems | Reference values | Role |
|---|---|---|---|
| Cyclic quantum stabilizer codes, k = 1 | n = 5–15 | Quantum Singleton bound; [[5,1,3]] optimal | calibration |
| Golomb rulers | m = 6–12 marks | OEIS A003022 (proven optima) | calibration |
| Cap sets in F₃ⁿ | n = 3–6 | proven maxima 9, 20, 45, 112 | calibration |
| Cap sets in F₃ⁿ | n = 7, 8 | best known 236, 512 (FunSearch) | open target |
| Binary linear codes | 7 cells with Lb = Ub | codetables.de | calibration |
| Binary linear codes | [48,14], [60,16], [70,18] | Lb 16/20/24, Ub 17/22/26 (codetables.de, 2026-11-01) | open target |
| Point spreading in the unit square | n = 2–10 | proven optima (Packomania), tolerance 10⁻⁴ | calibration |

Every reference value is recorded with its source in the problem specification.

## 3. Arms (search methods)

| Arm | Proposer | Seeds | Budget per run | Status in v1 |
|---|---|---|---|---|
| `random` | independent random candidates | 1, 2, 3 | 30 s wall clock | active |
| `anneal` | simulated annealing with restarts, driven only by checker feedback | 1, 2, 3 | 30 s wall clock | active |
| `exhaustive` | complete symmetry-reduced enumeration (cyclic codes n ≤ 13, Golomb m ≤ 11) | — | 1800 s | active |
| `llm-direct` | model proposes candidates as JSON, shown best-so-far and checker rejections | 1, 2, 3 | 30 model calls, US$1.00 cap | **pending** |
| `llm-program` | model writes generator programs, run in the sandbox (FunSearch-style) | 1, 2, 3 | 30 model calls, US$1.00 cap | **pending** |

Pending arms are specified now and run later under this same protocol; the model
identifier and pricing are recorded per call. The classical arms use equal wall-clock
budgets; candidate counts differ by method and are reported, not equalised.

## 4. Measurements (per run)

best value; status against the reference (`matches-known`, `below-known`,
`CANDIDATE-NEW`); candidates checked; valid fraction; classes of rejection reasons;
checks and seconds to best; best-so-far trajectory; model spend; certificate hash of the
best candidate.

## 5. Primary and secondary outcomes

- **Primary:** success rate, the fraction of (problem, seed) runs whose best value matches
  the reference, per arm and family.
- **Secondary:** normalised gap `|best − ref| / ref` at end of budget; valid fraction;
  checks-to-best; spend.

## 6. Analysis plan

- Report every run; no run is excluded after the fact. Crashed runs are reported as
  failures with their error.
- Per (family, arm): success rate with Wilson 95% intervals; median and IQR of the
  normalised gap; median checks-to-best.
- Arm comparisons on success rate use Fisher's exact test on pooled runs per family;
  gaps are compared with a paired bootstrap over problems (10,000 resamples). With six
  families, comparisons are reported with Holm-adjusted p-values and treated as
  descriptive, not confirmatory.
- Anytime performance: best-so-far against checked candidates for selected problems.

## 7. Novelty review (RQ4)

A `CANDIDATE-NEW` result is reported as new only after: (1) independent re-verification
with `probatio verify` and the browser verifier; (2) a check of the current
codetables.de / Packomania / cap-set literature and arXiv for the same parameters;
(3) a signed ledger entry recording the sources consulted and the decision.

## 8. Integrity

All certificates are content-addressed and every run, including failures, is appended
to the hash-chained ledger. Results are reproducible from the repository with
`scripts/reproduce.sh`.
