#!/usr/bin/env bash
# Reproduce every number, table and figure from the committed ledger and certificates.
#   scripts/reproduce.sh            verify + regenerate from the stored study ledgers
#   scripts/reproduce.sh --rerun    also re-execute the v2 classical arms from scratch
# v2 budgets are counted in checker calls, so a re-run gives the same results on any
# hardware for a given seed (wall-clock caps only guard against hangs).
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"
STUDIES=(results/study-v1 results/study-v2)

echo "== tests"; "$PY" -m pytest -q
echo "== calibration ledger"; "$PY" -m probatio.cli verify --all | tail -1; "$PY" -m probatio.cli audit
for S in "${STUDIES[@]}"; do
  [[ -f "$S/ledger.jsonl" ]] || continue
  echo "== $S: verify, audit, analyse"
  "$PY" -m probatio.cli --results "$S" verify --all | tail -1
  "$PY" -m probatio.cli --results "$S" audit
  "$PY" -m probatio.cli --results "$S" study analyze
  "$PY" -m probatio.cli --results "$S" study notebook
  "$PY" -m probatio.cli --results "$S" site
done

if [[ "${1:-}" == "--rerun" ]]; then
  echo "== re-running v2 classical arms into results/study-v2-rerun"
  "$PY" -m probatio.cli --results results/study-v2-rerun study run \
    --protocol experiments/protocol-v2.json --jobs "${JOBS:-2}"
fi

if command -v pdflatex >/dev/null; then
  echo "== paper"
  (cd paper/study && pdflatex -interaction=nonstopmode -halt-on-error main.tex >/dev/null \
     && bibtex main >/dev/null && pdflatex -interaction=nonstopmode main.tex >/dev/null \
     && pdflatex -interaction=nonstopmode main.tex >/dev/null && echo "paper/study/main.pdf")
fi
