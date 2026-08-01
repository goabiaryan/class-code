from __future__ import annotations

import modal
import subprocess

APP_NAME = "llama-engine"
GGUF_URL = (
    "https://huggingface.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF/resolve/main/"
    "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"
)
LLAMA_CPP_IMAGE = "ghcr.io/ggml-org/llama.cpp:server-cuda"

app = modal.App(APP_NAME)

gguf_cache = modal.Volume.from_name("class2-gguf-cache", create_if_missing=True)

image = (
    # llama.cpp images set ENTRYPOINT to llama-server; Modal must run Python first.
    modal.Image.from_registry(LLAMA_CPP_IMAGE, add_python="3.11")
    .entrypoint([])
    .env(
        {
            "GGUF_URL": GGUF_URL,
            "GGUF_PATH": "/cache/models/model.gguf",
            "PATH": "$PATH:/app",
        }
    )
)


@app.function(
    image=image,
    gpu="T4",
    timeout=60 * 60,
    scaledown_window=10 * 60,
    max_containers=1,
    volumes={"/cache/models": gguf_cache},
    
)
@modal.web_server(8080, startup_timeout=60)
def serve():
    import os
    import shutil
    import urllib.request
    from pathlib import Path
    
    gguf_path = Path(os.environ.get("GGUF_PATH", "/cache/models/model.gguf"))
    if not gguf_path.exists():
        gguf_path.parent.mkdir(parents=True, exist_ok=True)
        url = os.environ.get("GGUF_URL", GGUF_URL)
        print(f"Downloading GGUF to {gguf_path} ...", flush=True)
        urllib.request.urlretrieve(url, str(gguf_path))
        print(f"GGUF ready ({gguf_path.stat().st_size // (1024 * 1024)} MB)", flush=True)

    llama_server = shutil.which("llama-server")
    if not llama_server:
        raise RuntimeError("llama-server not found in PATH inside llama.cpp image")

    print(f"Starting {llama_server} on :8080", flush=True)
    subprocess.Popen(    [
            llama_server,
            "--host",
            "0.0.0.0",
            "--port",
            "8080",
            "-m",
            str(gguf_path),
            "-c",
            "4096",
            "-ngl",
            "999",
        ],
    )
    
    
