# SETUP (once)
cd class2
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH=$PWD
cp .env.example .env
bash scripts/setup_modal.sh
bash scripts/modal.sh deploy all
python scripts/download_gguf.py

# EVERY NEW TAB
cd class2 && source .venv/bin/activate && export PYTHONPATH=$PWD

# WARM-UP
python inference_101.py
curl -s http://127.0.0.1:8081/health | jq
docker compose --profile cpu up
curl -s http://127.0.0.1:8000/healthz | jq
docker compose --profile cpu down

# MODAL ENV
eval "$(bash scripts/modal.sh env naive-server)"
eval "$(bash scripts/modal.sh env llama-engine)"
eval "$(bash scripts/modal.sh env relay-serve)"
eval "$(bash scripts/modal.sh env litellm)"

# PART 0
eval "$(bash scripts/modal.sh env naive-server)"
curl -s "$MODAL_BASE_URL/healthz" | jq
curl -s "$MODAL_BASE_URL/v1/chat/completions" \
  -H 'Content-Type: application/json' \
  -d '{"model":"TinyLlama/TinyLlama-1.1B-Chat-v1.0","messages":[{"role":"user","content":"Hi"}],"max_tokens":8}' | jq '.metrics'

# PART 1
eval "$(bash scripts/modal.sh env naive-server)"
python scripts/part1_anatomy.py

# PART 2
eval "$(bash scripts/modal.sh env naive-server)"
curl -s "$MODAL_BASE_URL/v1/chat/completions" \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"Say hi"}],"max_tokens":8}' | jq

# PART 3 — curl
eval "$(bash scripts/modal.sh env naive-server)"
curl -s "$MODAL_BASE_URL/healthz" | jq
curl -sN "$MODAL_BASE_URL/v1/chat/completions" \
  -H 'Content-Type: application/json' \
  -d '{"model":"TinyLlama/TinyLlama-1.1B-Chat-v1.0","messages":[{"role":"user","content":"Explain KV cache in one paragraph."}],"max_tokens":64,"stream":true}'

# PART 3 — T3
eval "$(bash scripts/modal.sh env naive-server)"
python scripts/part5_observability.py --url "$METRICS_URL" --interval 1 --count 120

# PART 3 — script
eval "$(bash scripts/modal.sh env naive-server)"
python scripts/part3_break_server.py --base-url "$TARGET_URL"

# PART 4
bash scripts/modal.sh compare
eval "$(bash scripts/modal.sh env llama-engine)"
python scripts/part3_break_server.py --base-url "$TARGET_URL"
eval "$(bash scripts/modal.sh env relay-serve)"
python scripts/part5_observability.py --url "$METRICS_URL" --interval 1 --count 60
python scripts/part3_break_server.py --base-url "$TARGET_URL"
curl -s "$METRICS_URL/metrics" | jq
eval "$(bash scripts/modal.sh env litellm)"
python scripts/part3_break_server.py --base-url "$TARGET_URL"

# PART 5
eval "$(bash scripts/modal.sh env relay-serve)"
python scripts/part5_observability.py --url "$METRICS_URL" --interval 1

# PART 6
eval "$(bash scripts/modal.sh env litellm)"
python scripts/part6_litellm_demo.py

# AFTER CLASS
bash scripts/modal.sh stop all
docker compose --profile cpu down
