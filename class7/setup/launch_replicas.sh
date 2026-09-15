#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -f "$ROOT/.env" ]]; then
  set -a
  source "$ROOT/.env"
  set +a
fi
if [[ -x "$ROOT/.venv/bin/vllm" ]]; then
  export PATH="$ROOT/.venv/bin:$PATH"
fi
if [[ -n "${HF_TOKEN:-}" ]]; then
  export HUGGING_FACE_HUB_TOKEN="$HF_TOKEN"
fi

MODEL=${MODEL:-Qwen/Qwen3-0.6B}

if ! command -v nvidia-smi &>/dev/null; then
  echo "launch_replicas.sh runs on the Lambda GPU, not the Mac." >&2
  echo "On your Mac:  cd class-code/class7 && bash setup/sync_to_lambda.sh && bash setup/ssh.sh" >&2
  exit 1
fi

if ! command -v vllm >/dev/null 2>&1; then
  echo "vllm not on PATH. On Lambda:  bash setup/lambda_setup.sh && source .venv/bin/activate"
  exit 1
fi

# Start one replica and block until it serves /v1/models.
# Returns non-zero if it dies or never becomes ready.
start_replica() {
  local port=$1
  vllm serve "$MODEL" --port "$port" \
    --gpu-memory-utilization 0.35 \
    --max-num-seqs 8 \
    --max-model-len 16384 \
    --scheduling-policy priority \
    --served-model-name lab &
  local pid=$!
  echo "$pid" > "/tmp/llm-gateway-lab-${port}.pid"
  echo "  :$port pid $pid — waiting for /v1/models"

  local i
  for i in $(seq 1 180); do
    if curl -sf "http://127.0.0.1:${port}/v1/models" >/dev/null 2>&1; then
      echo "  :$port ready"
      return 0
    fi
    # Fail fast instead of waiting out the full timeout on a dead process.
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "  :$port exited before becoming ready — scroll up for its traceback" >&2
      return 1
    fi
    sleep 2
  done

  echo "  :$port still not ready after 6 minutes" >&2
  return 1
}

echo "starting two replicas of $MODEL  (max-num-seqs=8, gpu-memory-utilization=0.35)"

# Sequential on purpose. Started together, both replicas race to populate the
# same Hugging Face download cache and the same torch.compile artifact cache
# under ~/.cache/vllm, which can kill an engine core during startup with an
# unhelpful "Engine core initialization failed" and an empty failed-process set.
# The first replica warms both caches; the second then starts from them, so the
# stagger costs very little. Memory is not the constraint here: two replicas at
# 0.35 need about 27.6 GiB of the 39.5 GiB card.
start_replica 8001 || exit 1
start_replica 8002 || exit 1

echo "replicas ready on :8001 and :8002"
echo "next:  bash setup/smoke_test.sh"
