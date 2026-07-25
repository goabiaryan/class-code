from __future__ import annotations

import modal

# Inlined — Modal mounts this file as a top-level module; do not import modal_apps here.
APP_NAME = "naive-server"
MODEL_ID = "TinyLlama/TinyLlama-1.1B-Chat-v1.0"

app = modal.App(APP_NAME)

hf_cache = modal.Volume.from_name("class2-hf-cache", create_if_missing=True)

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "fastapi>=0.110,<1",
        "uvicorn[standard]>=0.27,<1",
        "transformers>=4.38,<5",
        "torch>=2.1,<3",
        "accelerate>=0.27,<1",
        "pydantic>=2",
        "httpx>=0.27,<1",
    )
    .env(
        {
            "MODEL_ID": MODEL_ID,
            "HF_HOME": "/cache/huggingface",
            "TRANSFORMERS_CACHE": "/cache/huggingface",
            "TORCH_DTYPE": "auto",
            "NAIVE_SERVER_HOST": "0.0.0.0",
        }
    )
    .add_local_python_source("naive_server")
)


@app.function(
    image=image,
    gpu="T4",
    timeout=60 * 60,
    scaledown_window=10 * 60,
    max_containers=1,
    volumes={"/cache/huggingface": hf_cache},
)
@modal.asgi_app()
def serve():
    from naive_server.server import app as fastapi_app

    return fastapi_app
