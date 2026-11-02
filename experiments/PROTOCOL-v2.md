# PROBATIO Study v2 — Pre-registered protocol

**Protocol id:** `probatio-study-v2` (supersedes v1, whose results stay as recorded)
**Status:** frozen before any v2 run. Machine-readable form: `experiments/protocol-v2.json`.
Its SHA-256 is ledger entry 0 of `results/study-v2/ledger.jsonl`. The runner refuses to
execute if the file changes, and the analysis locates the protocol by that hash.

## What changed from v1, and why

| Change | Reason |
|---|---|
| Budgets in **checker calls** per family (cap sets 2,000; Golomb 5,000; cyclic codes 5,000; linear codes 10,000; point spreading 50,000), 900 s safety cap | v1's 30 s wall-clock budgets depended on hardware and load |
| **Five seeds** (v1: three) | Narrower intervals |
| **Structured arms**: `anneal-qc` (quasi-cyclic codes) on linear codes; `anneal-constructive` (valid-by-construction) on Golomb rulers | v1 showed unstructured baselines are weak; strong baselines are needed to measure AI fairly |
| **Free AI arms** `local-llm-direct` and `local-llm-program`: open-weight `qwen2.5-coder:7b` via Ollama on the operator's machine, loopback only, seeded, model digest recorded; 20 calls per run | Measure AI proposers at zero cost |
| Optional paid arms `claude-direct`, `claude-program` (20 calls, US$1 cap) | Run only if funded; reported separately |
| References for cyclic codes n = 6–15 fixed here (codetables.de general optima) | v1 had none; fixed before any v2 run |
| Five new open linear-code cells: [45,15], [51,17], [56,14], [72,18], [80,20] | More record targets |
| Secondary outcome: **best within the first 200 checks** (`fair_checks`) | AI arms check ~200 candidates; this compares all arms at equal checks |
| **Paired bootstrap** of gaps (problems as units, 10,000 resamples, seed 0) | Specified in v1's plan but omitted from v1's analysis |

## Questions, measurements and outcomes

As v1 (RQ1 validity, RQ2 calibration, RQ3 efficiency, RQ4 discovery). Primary outcome:
success rate (best value equals the reference) per family and arm, Wilson 95% intervals.
Secondary: success within 200 checks, normalised gap, validity, checks-to-best, seconds,
spend.

## Comparisons (declared in advance)

anneal vs random; anneal-qc vs anneal; anneal-constructive vs anneal; each AI arm vs
random and vs anneal. Fisher exact tests per family with Holm adjustment over all tests
performed; paired bootstrap of mean gap difference. Descriptive, not confirmatory.

## Novelty review and integrity

As v1 §7–8. Any `CANDIDATE-NEW` is written to `CANDIDATES.md` unreviewed; it is claimed
only after re-verification in both implementations, a check of the live table and the
literature, and a signed ledger note recording the sources and the decision.
