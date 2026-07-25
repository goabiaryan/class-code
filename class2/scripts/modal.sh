
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

URL_DIR="$ROOT/.modal_urls"
LEGACY_URL_FILE="$ROOT/.modal_url"

# Deploy order: naive → llama-engine → relay-serve → litellm
APPS=(naive-server llama-engine relay-serve litellm)

load_modal_env() {
  if [[ -n "${MODAL_ENV_FILE:-}" && -f "$MODAL_ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$MODAL_ENV_FILE"
    set +a
    return
  fi
  if [[ -f "$ROOT/secrets/modal.env" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ROOT/secrets/modal.env"
    set +a
    return
  fi
  if [[ -f "$ROOT/.env" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ROOT/.env"
    set +a
  fi
}

app_module() {
  case "$1" in
    naive-server) echo "modal_apps/naive_server_app.py" ;;
    llama-engine) echo "modal_apps/llama_engine.py" ;;
    relay-serve)  echo "modal_apps/relay_serve.py" ;;
    litellm)      echo "modal_apps/litellm.py" ;;
    *) echo "Unknown app: $1" >&2; exit 1 ;;
  esac
}

lab_label() {
  case "$1" in
    naive-server) echo "A — bad engine, no gateway" ;;
    llama-engine) echo "B — llama.cpp engine only (no gateway)" ;;
    relay-serve)  echo "C — same engine as B + RelayServe gateway" ;;
    litellm)      echo "D — LiteLLM gateway on naive engine (counterfactual)" ;;
    *) echo "$1" ;;
  esac
}

url_file() {
  echo "$URL_DIR/$1"
}

parse_deploy_url() {
  local log="$1"
  local url
  url="$(grep -oE 'https://[^[:space:]]+\.modal\.run' "$log" | tail -1 || true)"
  if [[ -z "$url" ]]; then
    url="$(grep -oE '=> https://[^[:space:]]+\.modal\.run' "$log" | grep -oE 'https://[^[:space:]]+\.modal\.run' | tail -1 || true)"
  fi
  printf '%s' "$url"
}

require_auth() {
  if ! modal profile current &>/dev/null; then
    echo "Modal not authenticated. Run: bash scripts/setup_modal.sh"
    exit 1
  fi
}

deploy_one() {
  local app="$1"
  local module deploy_env=()
  module="$(app_module "$app")"

  if [[ "$app" == "llama-engine" ]]; then
    :
  elif [[ "$app" == "relay-serve" ]]; then
    local engine_url_file
    engine_url_file="$(url_file llama-engine)"
    if [[ ! -f "$engine_url_file" ]]; then
      echo "Deploy llama-engine first (RelayServe routes to that engine)." >&2
      exit 1
    fi
    local engine_url
    engine_url="$(tr -d '[:space:]' < "$engine_url_file")"
    deploy_env+=(RELAYSERVE_BACKENDS="$engine_url")
    echo "RelayServe backend (System B engine): $engine_url"
  elif [[ "$app" == "litellm" ]]; then
    local naive_url_file
    naive_url_file="$(url_file naive-server)"
    if [[ ! -f "$naive_url_file" ]]; then
      echo "Deploy naive-server first (LiteLLM counterfactual routes to naive)." >&2
      exit 1
    fi
    local naive_url
    naive_url="$(tr -d '[:space:]' < "$naive_url_file")"
    deploy_env+=(NAIVE_SERVER_URL="${naive_url}/v1")
    echo "LiteLLM upstream (naive engine): ${naive_url}/v1"
  fi

  echo "Deploying Modal app: $app ($(lab_label "$app"))"
  echo "Expected URL: https://<workspace>--${app}-serve.modal.run"
  echo "Module: $module"
  echo ""

  mkdir -p "$URL_DIR"
  local log
  log="$(mktemp)"
  if [[ ${#deploy_env[@]} -gt 0 ]]; then
    if ! env "${deploy_env[@]}" modal deploy "$module" 2>&1 | tee "$log"; then
      rm -f "$log"
      echo "Deploy failed for $app." >&2
      exit 1
    fi
  elif ! modal deploy "$module" 2>&1 | tee "$log"; then
    rm -f "$log"
    echo "Deploy failed for $app." >&2
    exit 1
  fi

  local url
  url="$(parse_deploy_url "$log")"
  rm -f "$log"

  if [[ -z "$url" ]]; then
    echo "Deploy finished but could not parse URL for $app." >&2
    echo "Look for: Created web function serve => https://....modal.run" >&2
    exit 1
  fi

  echo "$url" > "$(url_file "$app")"
  if [[ "$app" == "naive-server" ]]; then
    echo "$url" > "$LEGACY_URL_FILE"
  fi

  echo ""
  echo "Deployed $app: $url"
  echo "  eval \"\$(bash scripts/modal.sh env $app)\""
  echo "  bash scripts/modal.sh verify $app"
}

verify_one() {
  local app="$1"
  local file
  file="$(url_file "$app")"
  if [[ ! -f "$file" ]]; then
    echo "No URL for $app — run: bash scripts/modal.sh deploy $app" >&2
    exit 1
  fi
  local url
  url="$(tr -d '[:space:]' < "$file")"
  echo "APP=$app ($(lab_label "$app"))"
  echo "URL=$url"

  case "$app" in
    naive-server|relay-serve)
      echo "GET $url/healthz ..."
      curl -sS -m 60 "$url/healthz" | jq . 2>/dev/null || curl -sS -m 60 "$url/healthz"
      ;;
    llama-engine)
      echo "GET $url/health ..."
      curl -sS -m 60 "$url/health" | jq . 2>/dev/null || curl -sS -m 60 "$url/health"
      ;;
    litellm)
      echo "GET $url/health/liveliness ..."
      curl -sS -m 60 "$url/health/liveliness" | jq . 2>/dev/null || curl -sS -m 60 "$url/health/liveliness"
      ;;
  esac
}

env_one() {
  local app="$1"
  local file
  file="$(url_file "$app")"
  if [[ ! -f "$file" ]]; then
    echo "No URL for $app — run: bash scripts/modal.sh deploy $app" >&2
    exit 1
  fi
  local url
  url="$(tr -d '[:space:]' < "$file")"

  case "$app" in
    naive-server)
      echo "export LAB_SYSTEM=A"
      echo "export LAB_LABEL='bad engine, no gateway'"
      echo "export MODAL_APP=naive-server"
      echo "export MODAL_BASE_URL=$url"
      echo "export OPENAI_BASE_URL=$url/v1"
      echo "export TARGET_URL=$url/v1"
      echo "export METRICS_URL=$url"
      echo "export MODEL_ID=TinyLlama/TinyLlama-1.1B-Chat-v1.0"
      ;;
    llama-engine)
      echo "export LAB_SYSTEM=B"
      echo "export LAB_LABEL='llama.cpp engine only, no gateway'"
      echo "export MODAL_APP=llama-engine"
      echo "export ENGINE_BASE_URL=$url"
      echo "export OPENAI_BASE_URL=$url/v1"
      echo "export TARGET_URL=$url/v1"
      echo "export METRICS_URL=$url"
      echo "export MODEL_ID=llama"
      ;;
    relay-serve)
      echo "export LAB_SYSTEM=C"
      echo "export LAB_LABEL='same engine as B + RelayServe gateway'"
      echo "export MODAL_APP=relay-serve"
      echo "export RELAY_BASE_URL=$url"
      echo "export OPENAI_BASE_URL=$url/v1"
      echo "export TARGET_URL=$url/v1"
      echo "export METRICS_URL=$url"
      echo "export MODEL_ID=relay-gguf"
      ;;
    litellm)
      echo "export LAB_SYSTEM=D"
      echo "export LAB_LABEL='LiteLLM gateway on naive engine (counterfactual)'"
      echo "export MODAL_APP=litellm"
      echo "export LITELLM_BASE_URL=$url/v1"
      echo "export OPENAI_BASE_URL=$url/v1"
      echo "export TARGET_URL=$url/v1"
      echo "export MODEL_ID=naive-local"
      ;;
  esac
}

load_modal_env

cmd="${1:-help}"
target="${2:-}"

case "$cmd" in
  deploy)
    require_auth
    load_modal_env
    if [[ -z "$target" ]]; then
      echo "Usage: bash scripts/modal.sh deploy <app|all>" >&2
      exit 1
    fi
    if [[ "$target" == "all" ]]; then
      for app in "${APPS[@]}"; do
        deploy_one "$app"
        echo ""
      done
      echo "All apps deployed. Run: bash scripts/modal.sh compare"
    else
      deploy_one "$target"
    fi
    ;;

  verify)
    if [[ -z "$target" ]]; then
      echo "Usage: bash scripts/modal.sh verify <app|all>" >&2
      exit 1
    fi
    if [[ "$target" == "all" ]]; then
      for app in "${APPS[@]}"; do
        echo "=== $app ==="
        verify_one "$app" || true
        echo ""
      done
    else
      verify_one "$target"
    fi
    ;;

  env)
    if [[ -z "$target" ]]; then
      echo "Usage: bash scripts/modal.sh env <app>" >&2
      exit 1
    fi
    if [[ "$target" == "all" ]]; then
      for app in "${APPS[@]}"; do
        env_one "$app"
        echo ""
      done
    else
      env_one "$target"
    fi
    ;;

  url)
    if [[ -z "$target" ]]; then
      echo "Usage: bash scripts/modal.sh url <app>" >&2
      exit 1
    fi
    cat "$(url_file "$target")"
    ;;

  stop)
    require_auth
    if [[ -z "$target" ]]; then
      echo "Usage: bash scripts/modal.sh stop <app|all>" >&2
      exit 1
    fi
    if [[ "$target" == "all" ]]; then
      for app in "${APPS[@]}"; do
        modal app stop "$app" || true
      done
      modal app stop class2-naive-server || true
      echo "Stopped all Class 2 Modal apps (if running)."
    else
      modal app stop "$target" || true
      if [[ "$target" == "naive-server" ]]; then
        modal app stop class2-naive-server || true
      fi
      echo "Stopped $target (if it was running)."
    fi
    ;;

  logs)
    require_auth
    if [[ -z "$target" ]]; then
      echo "Usage: bash scripts/modal.sh logs <app>" >&2
      exit 1
    fi
    modal app logs "$target"
    ;;

  compare)
    echo "Class 2 experimental design — same load test, switch TARGET_URL:"
    echo ""
    printf "%-4s %-14s %s\n" "Sys" "App" "Role"
    printf "%-4s %-14s %s\n" "---" "--------------" "----"
    printf "%-4s %-14s %s\n" "A" "naive-server" "FastAPI + Transformers (baseline)"
    printf "%-4s %-14s %s\n" "B" "llama-engine" "Direct llama.cpp (engine only)"
    printf "%-4s %-14s %s\n" "C" "relay-serve" "RelayServe → same engine as B"
    printf "%-4s %-14s %s\n" "D" "litellm" "LiteLLM → naive (gateway-only counterfactual)"
    echo ""
    for app in "${APPS[@]}"; do
      local_file="$(url_file "$app")"
      if [[ -f "$local_file" ]]; then
        u="$(tr -d '[:space:]' < "$local_file")"
        echo "  $app  $u"
      else
        echo "  $app  (not deployed)"
      fi
    done
    echo ""
    echo "Same script each time (record LAB_SYSTEM in your table):"
    echo "  eval \"\$(bash scripts/modal.sh env <app>)\""
    echo "  python scripts/part3_break_server.py --base-url \"\$TARGET_URL\""
    ;;

  help|*)
    cat <<EOF
Usage: bash scripts/modal.sh <command> <app>

Four Modal apps — fixed experimental design (same part3_break_server.py):

  A  naive-server   Bad engine, no gateway        (Parts 2–3)
  B  llama-engine   llama.cpp only                (Part 4 step 1)
  C  relay-serve     RelayServe → engine B         (Part 4 step 2)
  D  litellm         LiteLLM → naive (counterfactual) (Part 6)

URL pattern: https://<workspace>--<app>-serve.modal.run

Commands:
  deploy all         Deploy A → B → C → D (recommended once per student)
  deploy <app>       Deploy one app
  verify all         Health-check all URLs
  env <app>          Export TARGET_URL + LAB_SYSTEM=A|B|C|D
  compare            Show design + deployed URLs
  stop all           Stop billing

Example:
  bash scripts/modal.sh deploy all
  bash scripts/modal.sh compare
  eval "\$(bash scripts/modal.sh env naive-server)"
  python scripts/part3_break_server.py --base-url "\$TARGET_URL"
EOF
    ;;
esac
