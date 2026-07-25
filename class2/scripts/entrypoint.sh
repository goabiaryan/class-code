#!/usr/bin/env bash
set -euo pipefail

cd /workspace/class2
export PYTHONPATH="/workspace/class2:${PYTHONPATH:-}"

cmd="${1:-help}"

case "$cmd" in
  naive)
    echo "Starting naive inference server on :${NAIVE_SERVER_PORT:-8000}"
    exec python -m naive_server.server
    ;;
  relay)
    echo "Starting RelayServe on :${RELAYSERVE_PORT:-8080}"
    echo "Backends: ${RELAYSERVE_BACKENDS:-none}"
    exec relayserve
    ;;
  litellm)
    PORT="${LITELLM_PORT:-4000}"
    UPSTREAM="${NAIVE_SERVER_URL:-http://naive-server:8000/v1}"
    echo "Starting LiteLLM proxy on :${PORT} -> ${UPSTREAM}"
    exec litellm --config config/litellm_config.yaml --port "$PORT" --host 0.0.0.0
    ;;
  jupyter)
    PORT="${JUPYTER_PORT:-8888}"
    echo "Jupyter Lab: http://127.0.0.1:${PORT} (token printed below)"
    exec jupyter lab \
      --ip=0.0.0.0 \
      --port="$PORT" \
      --no-browser \
      --allow-root \
      --NotebookApp.token='class2' \
      --NotebookApp.password=''
    ;;
  load-test)
    python -m lib.load_test --sweep "${@:2}"
    ;;
  part1)
    python scripts/part1_anatomy.py "${@:2}"
    ;;
  metrics-watch)
    python scripts/part5_observability.py "${@:2}"
    ;;
  help|*)
    cat <<'EOF'
Class 2 — available commands:

  naive          Start the naive inference server     → http://localhost:8000
  relay          Start RelayServe + llama.cpp         → http://localhost:8080
  litellm        Start LiteLLM proxy                  → http://localhost:4000
  jupyter        Open the lab notebook                → http://localhost:8888  (token: class2)
  load-test      Run Part 3 concurrency sweep
  part1          Run Part 1 anatomy script
  metrics-watch  Run Part 5 /metrics poller

See README.md for the full lab flow.
EOF
    ;;
esac
