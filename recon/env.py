"""Tiny .env loader for local runs (no python-dotenv). Real env vars always win."""
import os
from pathlib import Path

ENV = Path(__file__).parent.parent / ".env"   # gitignored


def load_env(path: Path = ENV):
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))
