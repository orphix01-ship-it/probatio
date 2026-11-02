#!/usr/bin/env bash
# Reproduce every number, table and figure from the committed ledger and certificates.
#   scripts/reproduce.sh            verify + regenerate from the stored study ledger
#   scripts/reproduce.sh --rerun    also re-execute the classical arms from scratch
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"
STUDY=results/study-v1

echo "== tests"; "$PY" -m pytest -q
echo "== calibration ledger"; "$PY" -m probatio.cli verify --all | tail -1; "$PY" -m probatio.cli audit
echo "== study ledger"; "$PY" -m probatio.cli --results "$STUDY" verify --all | tail -1
"$PY" -m probatio.cli --results "$STUDY" audit

if [[ "${1:-}" == "--rerun" ]]; then
  echo "== re-running classical arms into results/study-v1-rerun"
  "$PY" -m probatio.cli --results results/study-v1-rerun study run --jobs "${JOBS:-2}"
fi

echo "== analysis"; "$PY" -m probatio.cli --results "$STUDY" study analyze
"$PY" -m probatio.cli --results "$STUDY" study notebook
"$PY" -m probatio.cli --results "$STUDY" site

if command -v pdflatex >/dev/null; then
  echo "== paper"
  (cd paper/study && pdflatex -interaction=nonstopmode -halt-on-error main.tex >/dev/null \
     && bibtex main >/dev/null && pdflatex -interaction=nonstopmode main.tex >/dev/null \
     && pdflatex -interaction=nonstopmode main.tex >/dev/null && echo "paper/study/main.pdf")
fi
