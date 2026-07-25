# Class 2 — Build, Break, and Observe an Inference Server
# GPU image (default). For CPU-only hosts use: docker compose --profile cpu up
FROM pytorch/pytorch:2.2.1-cuda12.1-cudnn8-runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/cache/huggingface \
    MODEL_ID=TinyLlama/TinyLlama-1.1B-Chat-v1.0 \
    NAIVE_SERVER_PORT=8000 \
    RELAYSERVE_PORT=8080

WORKDIR /workspace/class2

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

RUN mkdir -p /cache/huggingface

EXPOSE 8000 8080 8888

# Pre-download model at build time (optional — comment out for faster builds)
RUN python -c "\
from transformers import AutoTokenizer, AutoModelForCausalLM; \
mid = __import__('os').environ.get('MODEL_ID', 'TinyLlama/TinyLlama-1.1B-Chat-v1.0'); \
AutoTokenizer.from_pretrained(mid); \
AutoModelForCausalLM.from_pretrained(mid, dtype='auto'); \
print('Model cached:', mid)" || echo "Model download skipped — will fetch at runtime"

CMD ["bash", "scripts/entrypoint.sh", "help"]
