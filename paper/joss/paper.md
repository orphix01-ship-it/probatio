---
title: 'PROBATIO: a verified discovery engine for machine-assisted mathematics'
tags:
  - Python
  - mathematics
  - verification
  - quantum error correction
  - coding theory
  - combinatorics
  - reproducibility
authors:
  - name: Vasilios Venegas
    affiliation: 1
    # orcid: 0000-0000-0000-0000   # add before submission
affiliations:
  - name: Independent researcher
    index: 1
date: 1 November 2026
bibliography: paper.bib
---

# Summary

PROBATIO is a Python package for searching mathematical objects with untrusted
proposers, such as exhaustive enumeration, simulated annealing, large language models or
model-written programs, while accepting only results that a small exact checker
certifies. Each certified result is stored as a content-addressed certificate in an
append-only, hash-chained ledger and can be re-verified from the certificate alone with
`probatio verify`, or in a web browser by a second, independent JavaScript implementation.
The package ships exact checkers for quantum stabilizer codes, binary linear codes, cap
sets, Golomb rulers and point spreading in the unit square, plus a Lean 4 proof checker;
a sandbox for executing model-written programs; a pre-registered experiment runner; and
generators for a lab notebook, analysis tables and figures, and a public results site.

# Statement of need

Recent work has produced new mathematical results by pairing generators with verifiers,
for example FunSearch for cap sets [@funsearch2024], AlphaEvolve and related systems for
constructions [@alphaevolve2025; @georgiev2025] and Lean-based agents for open Erdős
problems [@tsoukalas2026]. These systems are not openly available as general tools, and
claims made by AI models without independent checking are unreliable. Researchers who
want to run such searches need three things that are rarely packaged together: exact
checkers with a small, well-tested trusted base; safe execution of model-written code;
and a tamper-evident, reproducible record of what was tried and what was found.
PROBATIO provides all three behind one interface, so a new problem family needs only a
checker, a search space and a problem specification. The pre-registration mechanism,
where the protocol hash is the first ledger entry and runs are refused if it changes,
supports honest benchmarking of AI proposers against classical baselines.

# Design

Proposers are untrusted by construction: their output reaches a verdict only through a
checker that recomputes every quantity. Checkers use exact integer, finite-field or
rational arithmetic, or a proof kernel. The stabilizer-code checker computes
$k = n - \operatorname{rank}[X|Z]$ over GF(2) and the distance by exhaustive search in order
of weight [@gottesman1997]; the linear-code checker enumerates all $2^k$ codewords. Each
checker is cross-checked against an independent naive implementation and known objects,
including the binary Golay codes' weight-enumerator coefficients. Model-written programs
run in a subprocess with resource limits, a memory watchdog, a network namespace where
available and an audit-hook guard; a container backend is provided for stronger
isolation.

# Research use

The package was used for a pre-registered baseline study of classical search across 43
problems in five families (83 million exactly checked candidates, with every result
re-verifiable from its certificate). The complete ledger, certificates, analysis tables
and figures are in the repository, and `scripts/reproduce.sh` regenerates them.

# Acknowledgements

Reference values are taken from codetables.de [@codetables], Packomania [@packomania]
and the OEIS. The software was developed with the assistance of an AI model (Claude,
Anthropic); results are produced and checked by the deterministic code in the package.

# References
