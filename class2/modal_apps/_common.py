from __future__ import annotations

NAIVE_APP = "naive-server"
LLAMA_ENGINE_APP = "llama-engine"
RELAY_APP = "relay-serve"
LITELLM_APP = "litellm"

MODEL_ID = "TinyLlama/TinyLlama-1.1B-Chat-v1.0"
GGUF_URL = (
    "https://huggingface.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF/resolve/main/"
    "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"
)
LLAMA_CPP_IMAGE = "ghcr.io/ggml-org/llama.cpp:server-cuda"

LAB_SYSTEM_A = "naive-server"
LAB_SYSTEM_B = "llama-engine"
LAB_SYSTEM_C = "relay-serve"
LAB_SYSTEM_D = "litellm"
