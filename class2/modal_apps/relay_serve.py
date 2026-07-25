from __future__ import annotations

import os

import modal

APP_NAME = "relay-serve"

app = modal.App(APP_NAME)

# Set at deploy time from scripts/modal.sh (llama-engine base URL, no /v1 suffix).
BACKEND_URL = os.environ.get("RELAYSERVE_BACKENDS", "")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install("relayserve==1.1")
    .env(
        {
            "RELAYSERVE_PORT": "8080",
            "RELAYSERVE_BACKENDS": BACKEND_URL,
            "RELAYSERVE_MODEL_ID": "relay-gguf",
            "RELAYSERVE_BATCH_SIZE": "4",
            "RELAYSERVE_BATCH_WAIT_MS": "10",
        }
    )
)


@app.function(
    image=image,
    timeout=60 * 60,
    scaledown_window=10 * 60,
    max_containers=1,
)
@modal.web_server(8080, startup_timeout=120)
def serve():
    import subprocess

    subprocess.Popen(
        ["relayserve"],
        env=os.environ.copy(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
