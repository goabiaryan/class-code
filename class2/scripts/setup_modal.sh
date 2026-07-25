#!/usr/bin/env bash
# Authenticate Modal CLI from env vars. Never commit token values.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

pick_env_file() {
  if [[ -n "${MODAL_ENV_FILE:-}" ]]; then
    echo "$MODAL_ENV_FILE"
    return
  fi
  if [[ -f "$ROOT/secrets/modal.env" ]]; then
    echo "$ROOT/secrets/modal.env"
    return
  fi
  if [[ -f "$ROOT/.env" ]]; then
    echo "$ROOT/.env"
    return
  fi
  echo ""
}

ENV_FILE="$(pick_env_file)"
if [[ -z "$ENV_FILE" || ! -f "$ENV_FILE" ]]; then
  cat <<'EOF'
Modal credentials not found.

Students:
  cp .env.example .env
  # Edit .env — set MODAL_TOKEN_ID and MODAL_TOKEN_SECRET from modal.com/settings
  bash scripts/setup_modal.sh

Instructor (optional secrets file):
  cp secrets/modal.env.example secrets/modal.env
  # Edit secrets/modal.env, then:
  bash scripts/setup_modal.sh
EOF
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

if [[ -z "${MODAL_TOKEN_ID:-}" || -z "${MODAL_TOKEN_SECRET:-}" ]]; then
  echo "Missing MODAL_TOKEN_ID or MODAL_TOKEN_SECRET in $ENV_FILE"
  exit 1
fi

if [[ "$MODAL_TOKEN_ID" == *"xxxxxxxx"* || "$MODAL_TOKEN_SECRET" == *"xxxxxxxx"* ]]; then
  echo "Replace placeholder tokens in $ENV_FILE before running setup."
  exit 1
fi

python -m pip install -q 'modal>=0.64' 2>/dev/null || python -m pip install 'modal>=0.64'

modal token set \
  --token-id "$MODAL_TOKEN_ID" \
  --token-secret "$MODAL_TOKEN_SECRET"

echo "Modal CLI authenticated (using $ENV_FILE)."
