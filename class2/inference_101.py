from __future__ import annotations

import json
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

CLASS2_ROOT = Path(__file__).resolve().parent
GGUF_PATH = CLASS2_ROOT / "models" / "model.gguf"
PORT = 8081
BASE_URL = f"http://127.0.0.1:{PORT}"
CONTAINER = "class2-inference-101"


def ensure_gguf() -> None:
    if GGUF_PATH.is_file():
        return
    script = CLASS2_ROOT / "scripts" / "download_gguf.py"
    subprocess.run([sys.executable, str(script)], check=True)


def port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def fetch_health() -> dict | None:
    try:
        r = httpx.get(f"{BASE_URL}/health", timeout=2.0)
        if r.status_code == 200:
            return r.json()
    except httpx.HTTPError:
        pass
    return None


def container_running(name: str) -> bool:
    r = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", name],
        capture_output=True,
        text=True,
    )
    return r.returncode == 0 and r.stdout.strip() == "true"


def llama_docker_args() -> tuple[list[str], str]:
    if shutil.which("nvidia-smi"):
        image = "ghcr.io/ggml-org/llama.cpp:server-cuda"
        ngl = "999"
    else:
        image = "ghcr.io/ggml-org/llama.cpp:server"
        ngl = "0"
    cmd = [
        "docker",
        "run",
        "--rm",
        "--name",
        CONTAINER,
        "-p",
        f"{PORT}:{PORT}",
        "-v",
        f"{GGUF_PATH.parent}:/models:ro",
        image,
        "--host",
        "0.0.0.0",
        "--port",
        str(PORT),
        "-m",
        "/models/model.gguf",
        "-c",
        "2048",
        "-ngl",
        ngl,
    ]
    return cmd, image


def wait_ready(proc: subprocess.Popen[bytes], timeout_s: float = 180.0) -> float:
    t0 = time.perf_counter()
    deadline = t0 + timeout_s
    while time.perf_counter() < deadline:
        code = proc.poll()
        if code is not None:
            err = proc.stderr.read().decode() if proc.stderr else ""
            raise RuntimeError(f"docker exited (code {code}).\n{err}".strip())
        if not container_running(CONTAINER):
            time.sleep(0.5)
            continue
        health = fetch_health()
        if health is not None:
            return (time.perf_counter() - t0) * 1000
        time.sleep(0.5)
    raise TimeoutError(f"llama.cpp did not become ready at {BASE_URL}/health")


def print_curls() -> None:
    print()
    print("GET — health:")
    print(f"  curl -s {BASE_URL}/health | jq")
    print()
    print("POST — chat completion:")
    print(
        f"  curl -s {BASE_URL}/v1/chat/completions \\\n"
        "    -H 'Content-Type: application/json' \\\n"
        '    -d \'{"model":"llama","messages":[{"role":"user","content":"What is inference?"}],'
        '"max_tokens":32}\' | jq'
    )


def print_status(health: dict, load_ms: float, *, reused: bool) -> None:
    print(json.dumps({
        "status": "ok",
        "engine": "llama.cpp",
        "model_file": GGUF_PATH.name,
        "base_url": BASE_URL,
        "load_ms": round(load_ms, 1),
        "reused_existing_server": reused,
        "health": health,
    }, indent=2))


def main() -> None:
    print("Step 1 — llama.cpp engine (local HTTP)")
    ensure_gguf()
    size_mb = GGUF_PATH.stat().st_size / (1024 * 1024)
    print(f"model file: {GGUF_PATH} ({size_mb:.0f} MB)")

    existing = fetch_health()
    if existing is not None:
        print(f"server already listening on {BASE_URL} — not starting a new container")
        print_status(existing, 0.0, reused=True)
        print_curls()
        return

    if port_open("127.0.0.1", PORT):
        raise SystemExit(
            f"Port {PORT} is in use but /health did not respond.\n"
            "Stop whatever is on that port, e.g.:\n"
            "  docker compose --profile intro down\n"
            f"  docker ps --filter publish={PORT}"
        )

    subprocess.run(["docker", "rm", "-f", CONTAINER], capture_output=True)
    docker_cmd, image = llama_docker_args()
    print(f"starting {image} on {BASE_URL} ...")
    proc = subprocess.Popen(docker_cmd, stderr=subprocess.PIPE)

    def stop(_signum=None, _frame=None) -> None:
        proc.terminate()
        subprocess.run(["docker", "rm", "-f", CONTAINER], capture_output=True)
        sys.exit(0)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    try:
        load_ms = wait_ready(proc)
        health = fetch_health() or {}
        print_status(health, load_ms, reused=False)
        print_curls()
        print()
        print("Server running — use the curls above in another terminal. Ctrl+C to stop.")
        proc.wait()
    except (TimeoutError, RuntimeError) as exc:
        proc.terminate()
        subprocess.run(["docker", "rm", "-f", CONTAINER], capture_output=True)
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
