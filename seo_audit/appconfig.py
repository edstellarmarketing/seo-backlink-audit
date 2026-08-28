"""
Configuration and credential loading.

Credentials live in .env, never in config.yaml, so the file you edit and
share is not the file that holds your API keys.
"""

import os
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_env(path: str):
    """Minimal .env reader so credentials never live in config.yaml."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip().strip('"').strip("'")
            if v:
                os.environ.setdefault(k.strip(), v)


def load_config(path: str) -> dict:
    if not os.path.exists(path):
        sys.exit(f"ERROR: config not found: {path}")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
