"""Hestia endpoint discovery.

Plugins connect to a user-level Hestia daemon. The SDK auto-discovers
the endpoint in this order:
1. Explicit `hestia_endpoint` in client config
2. `HESTIA_ENDPOINT` env var
3. `~/.hestia/endpoint` file (written by Hestia daemon on startup)
4. `http://127.0.0.1:7711` (default fallback)
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_HESTIA_ENDPOINT: str = "http://127.0.0.1:7711"


def discover_hestia_endpoint(override: str | None = None) -> str:
    """Resolve the Hestia MCP endpoint for this session."""
    if override:
        return override

    env = os.environ.get("HESTIA_ENDPOINT")
    if env:
        return env

    try:
        file_path = Path.home() / ".hestia" / "endpoint"
        if file_path.is_file():
            content = file_path.read_text(encoding="utf-8").strip()
            if content:
                return content
    except OSError:
        pass

    return DEFAULT_HESTIA_ENDPOINT
