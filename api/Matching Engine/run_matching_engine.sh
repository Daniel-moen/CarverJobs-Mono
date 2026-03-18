#!/usr/bin/env zsh

set -o errexit
set -o pipefail

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  read -s "?Enter OPENAI_API_KEY: " OPENAI_API_KEY
  echo
  export OPENAI_API_KEY
fi

# Defensive sanitization in case terminal input includes hidden control chars.
OPENAI_API_KEY="$(printf '%s' "${OPENAI_API_KEY}" | tr -d '\r\n' | tr -d '[:cntrl:]')"
export OPENAI_API_KEY

export OPENAI_MODEL="${OPENAI_MODEL:-gpt-4o-mini}"
export MATCH_BATCH_SIZE="${MATCH_BATCH_SIZE:-5}"

python3 "$(dirname "$0")/main.py"
