from __future__ import annotations

import os

import modal

APP_NAME = "litellm"

app = modal.App(APP_NAME)

NAIVE_SERVER_URL = os.environ.get("NAIVE_SERVER_URL", "")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install("litellm[proxy]>=1.30,<2","prisma>=0.11.0,<1.0")
    .add_local_file(
        local_path="config/litellm_config.yaml",
        remote_path="/root/litellm_config.yaml",
        copy=True,
    )
    .env(
        {
            "NAIVE_SERVER_URL": NAIVE_SERVER_URL,
            "PORT": "4000",
        }
    )
)


@app.function(
    image=image,
    timeout=60 * 60,
    scaledown_window=10 * 60,
    max_containers=1,
)
@modal.web_server(4000, startup_timeout=180)
def serve():
    import subprocess

    subprocess.Popen(
        [
            "/usr/local/bin/litellm",
            "--config",
            "/root/litellm_config.yaml",
            "--port",
            "4000",
            "--host",
            "0.0.0.0",
        ],
        env=os.environ.copy(),
        #stdout=subprocess.DEVNULL,
        #stderr=subprocess.DEVNULL,
    )
