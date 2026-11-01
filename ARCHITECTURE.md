# PROBATIO — Architecture

**A verified discovery engine for mathematics and physics.**
Machines propose. Independent checkers certify. Only certified results count.

Status: v0.1 (reference implementation). Experimental, unaudited.

---

## 1. Thesis

AI models can now generate mathematical candidates — proofs, counterexamples,
constructions, programs — faster and more broadly than any human. What they cannot
do is guarantee correctness. The research systems producing genuine new results
(DeepMind's Lean-based proof agents, AlphaEvolve, FunSearch) all share one shape:

```
generate at scale  →  verify mechanically  →  keep only what verifies  →  feed back
```

PROBATIO is an open, general implementation of that loop, built so that **every
claim it makes is independently re-checkable by anyone, without trusting the AI,
the search, or the author.**

Design rule zero: *the proposer is untrusted.* An AI model, a genetic algorithm and
a random number generator are treated identically. Trust lives only in checkers.

---

## 2. Goals and non-goals

**Goals**
1. Produce machine-certified results on real open or benchmark problems.
2. Make every result reproducible from its certificate alone (`probatio verify`).
3. Plug in any proposer (LLM, evolutionary, exhaustive, human) behind one interface.
4. Plug in any checker (exact arithmetic, Lean kernel, physics simulator).
5. Execute untrusted generated code safely.
6. Keep an append-only, tamper-evident record of everything, including failures.
7. Report honestly: costs, attempts, failures, and novelty status.

**Non-goals**
- Claiming novelty automatically. Novelty requires a human literature check;
  the engine only flags "beats our recorded best known".
- Writing cryptographic or proof-checking primitives from scratch. We call Lean's
  kernel; we never re-implement it.
- Being a general chatbot for mathematics.

---

## 3. System overview

```
                      ┌──────────────────────────────┐
                      │        Problem Registry       │  problems/*.json
                      │  statement · format · checker │
                      │  objective · known bounds     │
                      └──────────────┬───────────────┘
                                     │
          ┌──────────────────────────▼──────────────────────────┐
          │                    Orchestrator                      │
          │  budget · islands · population DB · scheduling       │
          └───────┬───────────────────────────────────▲─────────┘
                  │ request candidates                │ scored results
       ┌──────────▼──────────┐                        │
       │      Proposers      │  (UNTRUSTED)           │
       │ LLM · program-evolve│                        │
       │ mutation · exhaustive│                       │
       └──────────┬──────────┘                        │
                  │ candidate (data or program)       │
       ┌──────────▼──────────┐                        │
       │      Sandbox        │  rlimits · timeout ·   │
       │ (programs only)     │  no network · tmp dir  │
       └──────────┬──────────┘                        │
                  │ candidate data                    │
       ┌──────────▼──────────┐                        │
       │      Checkers       │  (TRUSTED, minimal)    │
       │ exact · Lean · sim  │────────────────────────┘
       └──────────┬──────────┘
                  │ verdict + transcript
       ┌──────────▼──────────┐       ┌───────────────────────┐
       │  Certificate Store  │──────▶│  Ledger (hash-chained) │
       │ content-addressed   │       │  append-only JSONL     │
       └──────────┬──────────┘       └───────────┬───────────┘
                  │                              │
                  └──────────────┬───────────────┘
                       ┌─────────▼─────────┐
                       │ Reports · Verify  │  static HTML · CLI re-check
                       └───────────────────┘
```

---

## 4. Components

### 4.1 Problem Registry

Each problem is a JSON spec in `problems/`. It is the contract between proposers
and checkers.

| Field | Meaning |
|---|---|
| `id` | Stable identifier, e.g. `qec.cyclic.n13` |
| `domain` | `quantum-codes`, `combinatorics`, `formal-proof`, … |
| `statement` | Human-readable statement, used verbatim in LLM prompts |
| `candidate_format` | Schema of a candidate (e.g. list of Pauli strings) |
| `checker` | Registered checker name |
| `params` | Problem parameters (e.g. `n`, `k`) |
| `objective` | `maximize` / `minimize` / `prove` and the scored field |
| `known_best` | Recorded best-known value with source citation, or `null` |
| `references` | Literature to check before claiming anything |

`known_best` values are entered only from cited sources and are versioned. A
result that beats `known_best` is flagged **CANDIDATE-NEW**, never "new".

### 4.2 Proposers (untrusted)

One interface:

```python
class Proposer:
    def propose(self, problem, context) -> list[Candidate]: ...
```

`context` carries the best verified candidates so far plus recent failures with
checker messages, so proposers learn from verification feedback.

Shipped proposers:
- **MutationProposer** — local search / simulated annealing over the candidate
  space. Needs no AI; establishes an honest baseline every AI run must beat.
- **ExhaustiveProposer** — enumerates small search spaces completely, producing
  *optimality* evidence ("no better candidate exists in this family").
- **LLMProposer** — asks a model for candidates directly (JSON) or for a
  *program* that generates candidates (FunSearch/AlphaEvolve style). Provider is
  pluggable (Anthropic, OpenAI-compatible, local Ollama). Records model, prompt
  hash, token counts and cost for every call.
- **ProgramEvolutionProposer** — keeps a population of generator programs,
  asks the LLM to mutate the best ones, executes them in the sandbox, scores the
  output with the checker. Islands with periodic migration prevent collapse.

### 4.3 Sandbox

Generated programs are hostile until proven otherwise.

- Separate process, fresh temporary directory, minimal environment variables.
- `RLIMIT_CPU`, `RLIMIT_AS` (memory), `RLIMIT_FSIZE`, `RLIMIT_NPROC`, `RLIMIT_NOFILE`.
- Wall-clock timeout with process-group kill.
- Network denied via `unshare -rn` (Linux user+net namespace) when available;
  on macOS the run is marked `network_isolation: false` in the record.
- A Python audit-hook guard is injected ahead of every program (audit hooks
  cannot be removed once installed). It blocks process spawning, sockets,
  `ctypes`, and any write, delete, rename or chmod outside the sandbox
  directory. Defence in depth, not a hard boundary on its own.
- `PROBATIO_SANDBOX=docker` backend for production: `--network none`,
  read-only filesystem, dropped capabilities, non-root user, PID and memory
  limits.
- Output contract: the program prints one JSON document on stdout; anything else
  is a failed candidate. Output size is capped.
- Python's `-I -S` isolated mode; no site-packages beyond the allow-list.

The sandbox only *produces* candidate data. Its output is then checked exactly
like any other candidate; a malicious program can at worst waste its budget.

### 4.4 Checkers (trusted computing base)

Checkers are the only code that must be correct, so they are kept small, pure,
deterministic and heavily tested. Each returns:

```json
{ "valid": true, "score": {...}, "transcript": "...", "checker": "name@version" }
```

Shipped checkers:

| Checker | What it certifies | Method |
|---|---|---|
| `stabilizer_code` | A set of Pauli strings defines an `[[n,k,d]]` quantum error-correcting code | Exact GF(2) symplectic linear algebra: commutation, rank → `k`, exhaustive minimum-weight logical operator search → `d` |
| `golomb_ruler` | A set of integer marks is a Golomb ruler of given length | Exact pairwise-difference distinctness |
| `lean_proof` | A Lean 4 file proves the stated theorem | Runs the Lean kernel; rejects `sorry`, `admit`, new `axiom`s, and statement tampering by checking the theorem signature hash |

Trust levels recorded per checker:
- **T1 kernel** — a proof assistant kernel (Lean).
- **T2 exact** — exact integer/finite-field computation, open source, tested.
- **T3 numeric** — floating-point simulation; never sufficient alone for a claim.

### 4.5 Certificates

A certificate is a self-contained JSON document:

```json
{
  "problem_id": "...", "problem_hash": "sha256 of the problem spec",
  "candidate": { ... }, "candidate_hash": "sha256",
  "verdict": { "valid": true, "score": {...} },
  "checker": "stabilizer_code@0.1.0", "trust": "T2",
  "provenance": { "proposer": "...", "model": "...", "prompt_hash": "...",
                  "seed": 123, "cost_usd": 0.0, "attempt": 4812 },
  "created_at": "ISO-8601"
}
```

Stored content-addressed at `results/certs/<sha256>.json`. Anyone can run
`probatio verify <cert>`: it reloads the problem, re-runs the checker on the
candidate from scratch and compares the verdict. Provenance is informational —
verification never depends on it.

### 4.6 Ledger

`results/ledger.jsonl`, append-only. Each entry:

```json
{ "seq": 41, "prev": "<hash of entry 40>", "type": "certificate|run|failure",
  "ref": "<cert hash>", "summary": {...}, "hash": "<sha256 of this entry>" }
```

- Hash chain makes silent edits or deletions detectable (`probatio audit`).
- Optional Ed25519 signature per entry (`PROBATIO_SIGNING_KEY`) binds results
  to the operator. Public key published in the repo.
- Failures and run summaries are logged too: honest reporting of attempts and
  cost is part of the scientific record.

### 4.7 Orchestrator

- Budget limits: max candidates, max wall time, max USD for paid models.
- Population database per problem: best-N verified candidates, deduplicated by
  canonical form (e.g. codes up to qubit permutation and cyclic shift).
- Islands: independent populations with periodic migration of elites.
- Deterministic seeds so runs can be replayed.

### 4.8 Novelty pipeline (human-in-the-loop)

1. Engine flags `CANDIDATE-NEW` when a certified score beats `known_best`.
2. Operator checks references, code tables (e.g. codetables.de), arXiv, OEIS,
   the Erdős problems site.
3. Operator records the decision (`confirmed-new`, `known`, `rediscovery`) as a
   signed ledger entry with the sources consulted.

Rationale: several publicised "AI solutions to open problems" were already in
the literature. Verification proves correctness, not novelty.

### 4.9 Reporting

`probatio report` builds a static HTML page from the ledger: per-problem best
certified results, comparison with known bounds, attempts and cost, and a
re-verification command for every result. No server, no database.

---

## 5. Initial problem domains

### 5.1 Quantum error-correcting codes (physics)
Quantum computers need error correction; better codes mean fewer physical qubits
per logical qubit. A stabilizer code on `n` qubits is a set of commuting Pauli
operators; it protects `k = n − rank` logical qubits and corrects errors up to
weight `⌊(d−1)/2⌋`.

v0.1 searches **cyclic stabilizer codes** (generators are cyclic shifts of one
Pauli string) for maximal distance at each `n`, with exhaustive search proving
optimality *within the cyclic family* for small `n`. Calibration targets the
engine must rediscover: the perfect `[[5,1,3]]` code; the `[[13,1,5]]` cyclic code.

Roadmap: general stabilizer codes, CSS codes from classical code pairs,
quasi-cyclic and bivariate-bicycle (qLDPC) codes, and circuit-level noise
simulation (Stim) as a T3 secondary score.

### 5.2 Combinatorics
**Golomb rulers** — sets of marks with all pairwise differences distinct. Optimal
lengths are known up to 28 marks (distributed.net). Used as an exact calibration
benchmark: can the engine reach known optima, and how fast versus baselines?

Roadmap: Sidon sets, cap sets (FunSearch's benchmark), OEIS conjectures, Erdős
problems with finite witnesses.

### 5.3 Formal proof (pure mathematics)
Lean 4 statements; the LLM proposes proofs; the Lean kernel certifies. Roadmap:
autoformalization of textbook results, Erdős problem formalizations from the
Formal Conjectures project.

---

## 6. Security model

| Threat | Mitigation |
|---|---|
| Generated code escapes or exfiltrates | Sandbox: rlimits, timeout, network namespace, temp dir, minimal env |
| Proposer fakes a result | Proposer output is never trusted; checker recomputes everything |
| Lean proof cheats (`sorry`, new axioms, altered statement) | Token scan + `#print axioms` allow-list + statement hash check |
| Checker bug yields false certificate | Small TCB, unit tests with known codes, property tests, cross-check against independent implementation where available |
| Silent edit of past results | Hash-chained ledger + optional signatures; `probatio audit` |
| API key leakage | Keys only via environment; never logged; never passed to sandbox |
| Overclaiming | CANDIDATE-NEW flag only; novelty needs signed human review |

---

## 7. Repository layout

```
probatio/
  ARCHITECTURE.md  BUILD_PROMPT.md  README.md  SECURITY.md
  pyproject.toml
  probatio/
    cli.py            # run · verify · audit · report · problems
    registry.py       # problem loading + hashing
    orchestrator.py   # search loop, budget, population DB
    sandbox.py        # untrusted program execution
    ledger.py         # hash-chained ledger + certificates
    report.py         # static HTML report
    proposers/        # mutation · exhaustive · llm · program_evolution
    checkers/         # stabilizer_code · golomb_ruler · lean_proof
  problems/           # JSON problem specs
  results/            # certs/ ledger.jsonl report.html
  tests/
  scripts/            # bash helpers: setup, run-all, verify-all
```

---

## 8. Roadmap

| Phase | Deliverable |
|---|---|
| v0.1 | Engine, three checkers, mutation + exhaustive + LLM proposers, ledger, report, calibration results |
| v0.2 | Program-evolution with islands; Stim noise simulation; CSS / qLDPC code families |
| v0.3 | Lean pipeline on Formal Conjectures problems; Ed25519-signed releases |
| v0.4 | Public results site; reproducibility bundle per result; external review |

---

## 9. Success criteria

1. Every published result re-verifies from its certificate on a clean machine.
2. Calibration: the engine rediscovers known optima ([[5,1,3]], [[13,1,5]],
   optimal Golomb rulers to 10+ marks) and reports how it compares to baselines.
3. At least one CANDIDATE-NEW result that survives human literature review —
   the point at which the project moves from demonstration to contribution.
