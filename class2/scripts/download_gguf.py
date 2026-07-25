#!/usr/bin/env python3

from __future__ import annotations

import os
import sys
from pathlib import Path

DEFAULT_URL = (
    "https://huggingface.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF/resolve/main/"
    "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"
)
MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
TARGET = MODELS_DIR / "model.gguf"


def main() -> None:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    if TARGET.exists():
        size_mb = TARGET.stat().st_size / (1024 * 1024)
        print(f"Model already downloaded: {TARGET} ({size_mb:.0f} MB)")
        print("You're ready for Part 4. Run: docker compose --profile relay up")
        return

    url = os.environ.get("GGUF_URL", DEFAULT_URL)
    print("Downloading TinyLlama GGUF for RelayServe llama.cpp backends...")
    print(f"  From: {url}")
    print(f"  To:   {TARGET}")
    print("  (~700 MB — may take a few minutes)\n")

    try:
        import urllib.request

        def progress(block_num: int, block_size: int, total_size: int) -> None:
            if total_size > 0:
                pct = min(100, block_num * block_size * 100 // total_size)
                print(f"\r  Progress: {pct}%", end="", flush=True)

        urllib.request.urlretrieve(url, TARGET, reporthook=progress)
        print()
    except Exception as exc:
        print(f"\nDownload failed: {exc}", file=sys.stderr)
        print()
        print("Manual fallback:")
        print("  1. Download TinyLlama Q4_K_M GGUF from Hugging Face")
        print(f"  2. Save it as: {TARGET}")
        sys.exit(1)

    size_mb = TARGET.stat().st_size / (1024 * 1024)
    print(f"Done ({size_mb:.0f} MB). Next: bash scripts/intro_llama_cli.sh")


if __name__ == "__main__":
    main()
