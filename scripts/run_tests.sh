#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"

if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

if [ -z "${TEST_COMMAND:-}" ]; then
  echo "No TEST_COMMAND is configured. Add one to .env, for example: TEST_COMMAND=\"python3 -m pytest\""
  exit 0
fi

echo "Running test command: $TEST_COMMAND"
cd "$ROOT_DIR"
eval "$TEST_COMMAND"
