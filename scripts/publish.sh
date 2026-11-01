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
# Host the results site on GitHub Pages (served from /docs on main)
mkdir -p docs && cp results/site/index.html docs/index.html
git add docs && git commit -m "Publish results site" && git push
gh api -X POST repos/orphix01-ship-it/probatio/pages -f "source[branch]=main" -f "source[path]=/docs" || true
echo "Site: https://orphix01-ship-it.github.io/probatio/"
