#!/usr/bin/env bash
# Publish PROBATIO to GitHub as a public repo (run on your Mac, from the unpacked folder).
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m pytest -q
python3 -m probatio.cli verify --all
python3 -m probatio.cli audit
gh repo create orphix01-ship-it/probatio --public --source . --push \
  --description "Verified discovery engine: AI and search propose, exact checkers certify."
gh repo edit orphix01-ship-it/probatio --add-topic quantum-error-correction,formal-verification,ai-for-math,lean4,combinatorics
