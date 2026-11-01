# Security model

PROBATIO executes code and accepts output from untrusted sources (AI models and
search programs). Its security goal: **no proposer can obtain a false certificate,
and no generated program can harm the host or leak secrets.**

## Threats and mitigations

| Threat | Mitigation | Tested |
|---|---|---|
| Proposer fakes a result (e.g. claims a distance) | Checkers recompute every quantity from the raw candidate; proposer-supplied results are ignored | `test_claimed_distance_ignored` |
| Checker bug yields a false certificate | Small trusted core; exact GF(2) arithmetic; cross-checked against an independent naive implementation on every cyclic code up to 6 qubits and random codes with d = 1..3 | `test_crosscheck.py` |
| Generated program reaches the network | Linux user + network namespace (`unshare -rn`); socket imports blocked by the audit-hook guard; docker backend uses `--network none` | `test_sandbox_no_network`, guard tests |
| Generated program writes or deletes host files | Audit-hook guard blocks writes, deletes, renames and chmods outside the sandbox directory; docker backend mounts read-only | `test_sandbox_guard_blocks` |
| Generated program spawns processes / loads native code | Guard blocks `os.system`, `exec*`, `fork`, `subprocess`, `ctypes`; `RLIMIT_NPROC` | guard tests |
| Resource exhaustion | `RLIMIT_CPU`, `RLIMIT_AS`, `RLIMIT_FSIZE`, `RLIMIT_NOFILE`, wall-clock kill of the process group, output size cap | timeout, memory, output tests |
| Secret leakage (API keys) | Sandbox receives a scrubbed environment; keys are read only by the API client and never logged | `test_sandbox_env_scrubbed` |
| Lean proof cheats | Rejects `sorry`, `admit`, `axiom`, `unsafe`, `implemented_by`, `extern`, `opaque`, `native_decide`; statement must match verbatim; `#print axioms` allow-list | `test_lean_forbidden_and_unavailable` |
| Silent edit of results | Content-addressed certificates; hash-chained ledger; optional Ed25519 signatures; `probatio audit` | ledger tests |
| Overclaiming novelty | Software only ever says `CANDIDATE-NEW`; novelty requires signed human literature review | — |

## Honest limits

- The Python audit-hook guard is defence in depth, not a hard boundary: a
  determined attacker with a CPython memory-corruption bug could bypass it.
  For untrusted models at scale, run with `PROBATIO_SANDBOX=docker`
  (read-only filesystem, no network, dropped capabilities, non-root user,
  PID and memory limits).
- On macOS, `unshare` is unavailable; network isolation then relies on the
  guard alone unless the docker backend is used. Results record whether
  network isolation was achieved.
- The Lean checker is only as trustworthy as the installed Lean toolchain.
- "Optimal in family" claims come from open exhaustive-search code, not from a
  checker; they are labelled separately and covered by
  `test_symmetry_reduced_enumeration_is_complete`.
- This software has not been independently audited.

## Reporting

Report vulnerabilities privately to the repository owner before public disclosure.
