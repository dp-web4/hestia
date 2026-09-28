"""Test fixture: a rendered seat projection under a fixture HESTIA_HOME.

The seat consumes ONLY `$HESTIA_HOME/seats/<plugin_id>.env` (PRD_CONFIG_FROM_VAULT; #944).
Any suite that runs the hook end-to-end therefore needs one, or the hook refuses before it
reads stdin — which is the behaviour, not a test artefact. This writes the same shape the
daemon renders (`seat_config::render`), so a test's projection is the real thing, not a
lookalike: header, `# member:` line, one `KEY=value` per line, trailing newline.
"""
from __future__ import annotations

import os
from pathlib import Path

PROJECTION_DIR = "seats"


def write_projection(home: Path | str, plugin_id: str = "claude-code", env: dict | None = None,
                     note: str = "") -> Path:
    """Render a projection for `plugin_id` under `home`; returns its path. `HESTIA_HOME` is
    written to equal `home` unless the caller supplies a different value (to stage a miswire)."""
    home = Path(home)
    values = {"HESTIA_HOME": str(home)}
    values.update(env or {})
    path = home / PROJECTION_DIR / f"{plugin_id}{'.' + 'env'}"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# rendered from the vault by hestia. Do not edit: this file is a projection,",
             "# and an edit here is reported as a miswire rather than applied.",
             f"# member: {plugin_id}"]
    if note:
        lines.append(f"# note: {note}")
    for k in sorted(values):
        lines.append(f"{k}={values[k]}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def projection_env(home: Path | str, base: dict | None = None, **extra) -> dict:
    """An environment for a subprocess that runs the hook against `home`: the launcher's part
    only (HESTIA_HOME), with any ambient seam removed so the projection is the sole source."""
    env = dict(base if base is not None else os.environ)
    env["HESTIA_HOME"] = str(home)
    for k in ("HESTIA_SHARED_DIR", "HESTIA_WORKSPACE", "HESTIA_ENDPOINT", "HESTIA_STATE_DIR"):
        env.pop(k, None)
    env.update(extra)
    return env
