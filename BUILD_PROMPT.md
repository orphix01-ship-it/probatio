# PROBATIO — Build Prompt

Paste everything below the line into a coding agent (Claude Code or similar) at the
root of an empty repository that contains `ARCHITECTURE.md`. It is written to be
executed end to end without further clarification.

---

You are a principal engineer building **PROBATIO**, a verified discovery engine for
mathematics and physics. Read `ARCHITECTURE.md` in full before writing any code. It is
the specification; where this prompt and the architecture disagree, the architecture wins.

## Mission

Build a system where untrusted proposers (AI models, search algorithms) generate
mathematical candidates and small, trusted checkers certify them. Every result must be
re-verifiable from its certificate alone by anyone, on a clean machine, without trusting
the proposer or the author.

## Non-negotiable principles

1. **The proposer is untrusted.** Never let proposer output influence a verdict except
   through the checker. Treat LLM output and generated programs as hostile input.
2. **Checkers are the trusted computing base.** Keep them small, pure, deterministic,
   dependency-light, and exhaustively tested against known mathematical facts.
3. **Exactness.** Certificates rest on exact arithmetic (integers, GF(2)) or a proof
   kernel. Floating point may only produce secondary T3 scores.
4. **Never overclaim.** A result that beats the recorded best-known value is flagged
   `CANDIDATE-NEW`. Nothing is ever called "new" by the software.
5. **Log everything.** Successes, failures, attempts, costs. The ledger is append-only and
   hash-chained.
6. **Security first.** Generated code runs only in the sandbox. API keys come from the
   environment, are never logged, and never reach the sandbox.
7. **No hand-rolled cryptography or proof checking.** Use `hashlib`, the Lean kernel, and
   well-known libraries.

## Build order (each step must pass its tests before the next)

1. **Scaffold.** `pyproject.toml` (Python ≥3.11, only dependency `numpy`; optional extras
   `llm` and `sign`), package layout exactly as in ARCHITECTURE §7, console script
   `probatio`.
2. **Registry.** Load and validate `problems/*.json`; compute canonical SHA-256
   `problem_hash` over sorted-key JSON.
3. **Checkers.**
   - `stabilizer_code`: input a list of Pauli strings over {I,X,Y,Z}. Convert to binary
     symplectic form; verify all generators commute; compute GF(2) rank; `k = n − rank`;
     compute distance `d` as the minimum weight of a Pauli that commutes with all
     generators but is not in the stabilizer group (exhaustive by increasing weight, with
     a configurable cap). For `k = 0` report `d` as the minimum weight of a stabilizer
     element and mark the code as a stabilizer state.
     Tests: `[[5,1,3]]` from cyclic shifts of `XZZXI`; Steane `[[7,1,3]]`; `[[4,2,2]]`;
     the 3-qubit bit-flip code reports `d = 1`; non-commuting input is rejected.
   - `golomb_ruler`: exact distinct-differences check; score = length; tests on known
     optimal rulers for 4–10 marks and on invalid rulers.
   - `lean_proof`: write the candidate to a temp Lean project, run `lean`, require exit 0;
     reject `sorry`, `admit`, `axiom`, `@[implemented_by]`, `unsafe`, `native_decide`
     unless allowed by the problem; verify the theorem statement text exactly matches the
     problem's statement; run `#print axioms` and allow only `propext`, `Quot.sound`,
     `Classical.choice`. If Lean is not installed, return `valid=false` with reason
     `checker-unavailable` (never `true`).
4. **Ledger + certificates.** Content-addressed certs, hash-chained JSONL ledger,
   `audit` detecting any modified, reordered or deleted entry (test all three), optional
   Ed25519 signing when `cryptography` is installed and `PROBATIO_SIGNING_KEY` is set.
5. **Sandbox.** Subprocess with `python -I -S`, rlimits (CPU, address space, file size,
   processes, open files), wall-clock timeout with process-group kill, fresh temp
   directory, scrubbed environment, `unshare -rn` network isolation when available.
   Record whether isolation was achieved. Tests: infinite loop is killed; memory bomb is
   stopped; network access fails when namespaces are available; environment secrets are
   not visible; oversized output is rejected.
6. **Proposers.** `mutation` (simulated annealing with restarts), `exhaustive` (complete
   enumeration up to canonical form), `llm` (Anthropic Messages API over HTTPS via the
   standard library; model from `PROBATIO_MODEL`; asks for JSON candidates or a generator
   program; includes best-so-far and recent checker failures in the prompt; records token
   usage and cost), `program_evolution` (population of generator programs mutated by the
   LLM, executed in the sandbox).
7. **Orchestrator.** Budgets (candidates, seconds, USD), dedup by canonical form,
   population of best-N, deterministic seeding, CANDIDATE-NEW flagging against
   `known_best`.
8. **CLI.** `probatio problems | run <id> --proposer P --budget N --seed S |
   verify <cert|--all> | audit | report`.
9. **Report.** Static, dependency-free HTML from the ledger: best certified result per
   problem, known bound, status, attempts, cost, and the exact verify command.
10. **Problems.** Cyclic stabilizer codes for n = 5…15 (`known_best` only where you can
    cite a source; otherwise `null`); Golomb rulers for 6–12 marks with known optimal
    lengths cited; one small Lean theorem as a pipeline test.
11. **Calibration run.** Run exhaustive and mutation proposers on every problem, verify
    every certificate with `probatio verify --all`, run `probatio audit`, generate the
    report, and commit results.

## Definition of done

- `pytest` passes; checker tests cover every known-code fact above.
- `probatio verify --all` re-certifies every stored result from scratch.
- `probatio audit` passes, and fails when any ledger byte is altered.
- README explains the thesis in plain language, shows the results table, and states the
  limits: experimental, unaudited, verification proves correctness not novelty.
- `SECURITY.md` contains the threat model from ARCHITECTURE §6.
- No secrets, client data or personal data anywhere in the repository or its history.

## Style

Clear module boundaries, type hints, docstrings on every public function, no clever
one-liners in checkers, explicit error messages. Prefer boring, auditable code.
Operational helper scripts in `scripts/` are bash.
