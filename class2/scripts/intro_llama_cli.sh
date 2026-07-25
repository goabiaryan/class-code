
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODEL="$ROOT/models/model.gguf"
PROMPT="${1:-In one sentence, what is LLM inference?}"
N_PRED="${N_PRED:-32}"
IMAGE="${LLAMA_CLI_IMAGE:-ghcr.io/ggml-org/llama.cpp:full}"

if [[ ! -f "$MODEL" ]]; then
  echo "Missing $MODEL"
  echo "Run: python scripts/download_gguf.py"
  exit 1
fi

echo "=== llama.cpp inference (console via Docker) ==="
echo "image:  $IMAGE"
echo "model:  $MODEL"
echo "prompt: $PROMPT"
echo ""

docker run --rm -v "$ROOT/models:/models:ro" "$IMAGE" \
  llama-cli \
  -m /models/model.gguf \
  -p "$PROMPT" \
  -n "$N_PRED" \
  --simple-io

echo ""
echo "Next: docker compose --profile cpu up naive-server-cpu"
echo "      (HTTP server — OpenAI-shaped API on :8000)"
