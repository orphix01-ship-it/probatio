#!/usr/bin/env bash
# Calibration run: exhaustive + mutation search on every built-in problem,
# then re-verify every certificate, audit the ledger and build the report.
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"
run() { "$PY" -m probatio.cli run "$@" 2>/dev/null | jq -c '{p:.problem_id,v:.best_value,complete:.exhaustive_complete,checked:.candidates_checked,s:.seconds,status}'; }

for n in $(seq 5 13); do run "qec.cyclic.n$n.k1" --proposer exhaustive --budget 100000000 --seconds 1800 --batch 4096; done
for n in 14 15; do run "qec.cyclic.n$n.k1" --proposer mutation --budget 200000 --seconds 900 --seed 1; done
for m in 6 7 8 9 10; do run "golomb.m$m" --proposer exhaustive --budget 1000000 --seconds 1800; done
for m in 11 12; do run "golomb.m$m" --proposer mutation --budget 500000 --seconds 600 --seed 1; done

"$PY" -m probatio.cli verify --all
"$PY" -m probatio.cli audit
"$PY" -m probatio.cli report
