#!/usr/bin/env python3
"""Prove every *registered* candidate gate can retain the deploy escape hatch.

``hestia-deploy`` used to exercise only the Claude Code adapter before replacing
all member hooks.  That made its green preflight a statement about one harness,
not the set the installer was about to change.  This runner keeps the harness
details in each plugin's ``expects.json`` and tests only gates whose registration
is present on this host.

It deliberately proves availability, not entitlement: a member may have an empty
standing scope and still retain its temp-root read and deploy-hold escape hatch.
The candidate must allow both acts while its normal enforce posture is active.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Iterable


def _commands_from_registration(path: Path, reader: str) -> list[str]:
    """Return declared hook commands, or raise for an unreadable declaration.

    This mirrors the installer's deliberately small readers.  An unknown or
    malformed registration is not evidence that a gate is absent.
    """
    if reader == "json-hook-commands":
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"registration is not readable JSON: {type(exc).__name__}") from exc

        commands: list[str] = []

        def walk(value: Any) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    if key == "command" and isinstance(child, str):
                        commands.append(child)
                    else:
                        walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(document)
        return commands

    if reader == "toml-hook-commands":
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            raise ValueError(f"registration is unreadable: {type(exc).__name__}") from exc
        return [match.group(2) for line in lines
                if (match := re.match(r'''\s*command\s*=\s*(['"])(.*)\1\s*$''', line))]

    raise ValueError(f"unknown install.registration.reader: {reader!r}")


def _registered(commands: Iterable[str], entry: str) -> bool:
    """Whether a registration invokes exactly this gate entrypoint basename."""
    wanted = Path(entry).name
    for command in commands:
        for token in command.split():
            if token.startswith("/") and Path(token).name == wanted:
                return True
    return False


def _render(value: Any, replacements: dict[str, str]) -> Any:
    if isinstance(value, str):
        for marker, replacement in replacements.items():
            value = value.replace(marker, replacement)
        return value
    if isinstance(value, list):
        return [_render(child, replacements) for child in value]
    if isinstance(value, dict):
        return {key: _render(child, replacements) for key, child in value.items()}
    return value


def _payload_denies(stdout: str) -> bool:
    """A harness may encode a policy denial in JSON while exiting zero."""
    try:
        value = json.loads(stdout)
    except ValueError:
        return False
    return isinstance(value, dict) and (
        value.get("permissionDecision") == "deny" or value.get("decision") == "deny"
    )


def run_probes(
    repo: Path,
    home: Path,
    endpoint: str,
    scratch: str,
    hold: str,
    excluded: set[str] | None = None,
    workspace: Path | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """Run candidate probes and return public-safe status rows plus success."""
    excluded = excluded or set()
    rows: list[dict[str, Any]] = []
    good = True
    workspace_text = str((workspace or repo.parent).resolve())

    for expects_path in sorted((repo / "plugins").glob("*/expects.json")):
        member = expects_path.parent.name
        if member in excluded:
            continue
        try:
            spec = json.loads(expects_path.read_text(encoding="utf-8"))
            install = spec.get("install") or {}
            registration = install.get("registration") or {}
            probe = install.get("gate_probe")
            if not isinstance(probe, dict):
                raise ValueError("missing install.gate_probe")
            segments = registration.get("path") or []
            reader = registration.get("reader")
            entry = probe.get("entry")
            events = probe.get("events")
            if (not isinstance(segments, list) or not all(isinstance(x, str) for x in segments)
                    or not isinstance(reader, str) or not isinstance(entry, str)
                    or not isinstance(events, list) or not events):
                raise ValueError("invalid install.gate_probe or registration declaration")
        except (OSError, ValueError, TypeError) as exc:
            rows.append({"member": member, "status": "unmeasured", "reason": str(exc)})
            good = False
            continue

        registration_path = home.joinpath(*segments)
        if not registration_path.exists():
            rows.append({"member": member, "status": "not-registered"})
            continue
        try:
            commands = _commands_from_registration(registration_path, reader)
        except ValueError as exc:
            rows.append({"member": member, "status": "unmeasured", "reason": str(exc)})
            good = False
            continue
        if not _registered(commands, entry):
            rows.append({"member": member, "status": "not-registered"})
            continue

        candidate = expects_path.parent / entry
        if not candidate.is_file():
            rows.append({"member": member, "status": "unmeasured", "reason": "candidate missing"})
            good = False
            continue

        declared_env = probe.get("environment") or {}
        if not isinstance(declared_env, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in declared_env.items()
        ):
            rows.append({"member": member, "status": "unmeasured", "reason": "invalid probe environment"})
            good = False
            continue
        environment = dict(os.environ)
        environment.update(declared_env)
        environment.update({"HESTIA_ENDPOINT": endpoint, "HESTIA_WORKSPACE": workspace_text})

        for declared in events:
            if not isinstance(declared, dict):
                rows.append({"member": member, "status": "unmeasured", "reason": "invalid probe event"})
                good = False
                break
            label = declared.get("label")
            event = declared.get("event")
            if not isinstance(label, str) or not isinstance(event, dict):
                rows.append({"member": member, "status": "unmeasured", "reason": "invalid probe event"})
                good = False
                break
            rendered = _render(event, {"{scratch}": scratch, "{hold}": hold})
            try:
                completed = subprocess.run(
                    [sys.executable, str(candidate)],
                    input=json.dumps(rendered),
                    text=True,
                    capture_output=True,
                    cwd=repo,
                    env=environment,
                    timeout=12,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                rows.append({"member": member, "probe": label, "status": "refused", "reason": "timeout"})
                good = False
                continue
            if completed.returncode != 0 or _payload_denies(completed.stdout):
                reason = (
                    f"candidate exited {completed.returncode}"
                    if completed.returncode != 0
                    else "candidate returned denial payload"
                )
                rows.append({"member": member, "probe": label, "status": "refused", "reason": reason})
                good = False
            else:
                rows.append({"member": member, "probe": label, "status": "ok"})

    return rows, good


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--workspace", type=Path,
                        help="workspace that contains the hestia checkout (defaults to repo parent)")
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--scratch", required=True)
    parser.add_argument("--hold", required=True)
    parser.add_argument("--exclude-member", action="append", default=[])
    args = parser.parse_args(argv)

    rows, good = run_probes(
        args.repo.resolve(), args.home.expanduser(), args.endpoint, args.scratch, args.hold,
        set(args.exclude_member), args.workspace,
    )
    for row in rows:
        # This enters deploy.log. Keep it useful without leaking local paths or hook stderr.
        detail = f" ({row['reason']})" if row.get("reason") else ""
        probe = f" {row['probe']}" if row.get("probe") else ""
        print(f"gate-preflight {row['status']} {row['member']}{probe}{detail}")
    return 0 if good else 4


if __name__ == "__main__":
    raise SystemExit(main())
