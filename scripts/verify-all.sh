#!/usr/bin/env bash
# Independently re-check every stored result from scratch, then audit the ledger.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m pytest -q
python3 -m probatio.cli verify --all
python3 -m probatio.cli audit
