"""Load gitignored .env files for class2 scripts (no extra dependencies)."""

from __future__ import annotations

import os
from pathlib import Path

CLASS2_ROOT = Path(__file__).resolve().parent.parent


def _parse_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if not key or not value:
            continue
        if key not in os.environ or not os.environ.get(key):
            os.environ[key] = value


def load_class2_env() -> None:
    """Load class2/.env then secrets/*.env (later files do not override earlier)."""
    _parse_env_file(CLASS2_ROOT / ".env")
    secrets = CLASS2_ROOT / "secrets"
    if secrets.is_dir():
        for path in sorted(secrets.glob("*.env")):
            _parse_env_file(path)

    # Hugging Face libraries read these names
    token = os.environ.get("HF_TOKEN") or os.environ.get("HF_SECRET_ACCESS_KEY")
    if token:
        os.environ.setdefault("HF_TOKEN", token)
        os.environ.setdefault("HUGGING_FACE_HUB_TOKEN", token)


def apply_hf_token() -> None:
    load_class2_env()
