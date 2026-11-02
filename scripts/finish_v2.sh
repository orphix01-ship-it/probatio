#!/usr/bin/env bash
# Finish study v2: resume the frozen protocol from its ledger, then verify, audit and analyse.
# Usage: scripts/finish_v2.sh [--jobs N] [--with-local-ai]
#   --with-local-ai  also run the free local-model arms (needs Ollama on 127.0.0.1 and
#                    `ollama pull qwen2.5-coder:7b`; these arms always run one at a time)
set -euo pipefail
cd "$(dirname "$0")/.."

JOBS=4
LOCAL_AI=0
while [ $# -gt 0 ]; do
  case "$1" in
    --jobs) JOBS="$2"; shift 2 ;;
    --with-local-ai) LOCAL_AI=1; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

R=results/study-v2
PROTO=experiments/protocol-v2.json
P=(python3 -m probatio.cli --results "$R")

"${P[@]}" audit                                   # refuse to build on a broken ledger
"${P[@]}" note "Resumed on $(uname -sm), $(python3 --version 2>&1), --jobs $JOBS."
"${P[@]}" study run --protocol "$PROTO" --jobs "$JOBS"

if [ "$LOCAL_AI" = 1 ]; then
  curl -fsS --noproxy '*' http://127.0.0.1:11434/api/tags >/dev/null \
    || { echo "Ollama is not answering on 127.0.0.1:11434 (run: ollama serve)" >&2; exit 1; }
  "${P[@]}" study run --protocol "$PROTO" --arms local-llm-direct local-llm-program
fi

"${P[@]}" verify --all | tail -1
"${P[@]}" audit
"${P[@]}" study analyze
"${P[@]}" study notebook
"${P[@]}" site
echo "done: tables in $R/analysis, site in $R/site/index.html"
