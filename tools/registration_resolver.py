#!/usr/bin/env python3
"""Resolve the hook artifacts a member's harness actually registers.

Registration is execution truth. Consumers must not rediscover it from convention
paths or grow harness-specific parsers beside one another.

This first increment extracts the read side only. It does not install, compare,
monitor, or mutate anything. `deploy/install-members.sh`, `fleet_manifest.py`, and
the daemon monitor can consume this contract in later increments.

Machine result states are deliberately not collapsed:

  ok              registration was read; `targets` may legitimately be empty
  not_declared    expects.json declares no registration contract
  not_present     declared registration file is absent on this host
  unreadable      registration exists but cannot be read
  unparseable     registration / relevant command syntax cannot be parsed
  unknown_reader  expects.json names an unsupported reader

Only `ok` means the resolver actually inspected the registration. An `ok` result
also carries `complete`: false means at least one registered command could not be
classified without guessing, so a consumer must not treat the returned target set
as exhaustive.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import stat
from pathlib import Path
from typing import Any

_STATE_RC = {
    "ok": 0,
    "not_declared": 2,
    "not_present": 3,
    "unparseable": 4,
    "unknown_reader": 5,
    "unreadable": 6,
}

_ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$", re.S)
_TOML_COMMAND = re.compile(r"^\s*command\s*=\s*(['\"])(.*)\1\s*(?:#.*)?$")
_INTERPRETERS = {
    "python", "python2", "python3", "python.exe", "python3.exe",
    "node", "node.exe", "bash", "sh", "zsh", "ruby", "perl",
}
_PY_NO_VALUE_FLAGS = {
    "-B", "-E", "-I", "-O", "-OO", "-P", "-q", "-s", "-S", "-u", "-v",
}
_PY_VALUE_FLAGS = {"-W", "-X"}


def _result(state: str, **extra: Any) -> dict[str, Any]:
    return {"state": state, **extra}


def _commands_from_json(obj: Any, out: list[str]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "command" and isinstance(v, str):
                out.append(v)
            else:
                _commands_from_json(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _commands_from_json(v, out)


def _commands_from_toml_text(text: str) -> list[str]:
    """Read the command assignments used by Codex/Kimi registrations.

    This deliberately remains dependency-free rather than requiring Python 3.11's
    tomllib on operator hosts. A line that purports to declare `command = ...` but
    cannot be read by the supported quoted-string grammar is UNPARSEABLE, never
    silently ignored.
    """
    out: list[str] = []
    for raw in text.splitlines():
        if not re.match(r"^\s*command\s*=", raw):
            continue
        m = _TOML_COMMAND.match(raw)
        if not m:
            raise ValueError(f"unparseable command assignment: {raw!r}")
        out.append(m.group(2))
    return out


def _kind(path: str) -> str:
    try:
        mode = os.stat(path).st_mode
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "other"
    if stat.S_ISREG(mode):
        return "file"
    if stat.S_ISDIR(mode):
        return "directory"
    return "other"


def _expand_path(tok: str) -> str:
    return os.path.abspath(os.path.expandvars(os.path.expanduser(tok)))


def _strip_env_prefix(tokens: list[str]) -> list[str]:
    i = 0
    while i < len(tokens) and _ENV_ASSIGN.match(tokens[i]):
        i += 1
    return tokens[i:]


def _python_script(args: list[str]) -> str | None:
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            return args[i + 1] if i + 1 < len(args) else None
        if a in {"-c", "-m"}:
            return None
        if a in _PY_VALUE_FLAGS:
            i += 2
            continue
        # Attached forms such as `-Wignore` / `-Xdev` consume themselves.
        if (a.startswith("-W") and len(a) > 2) or (a.startswith("-X") and len(a) > 2):
            i += 1
            continue
        if a in _PY_NO_VALUE_FLAGS:
            i += 1
            continue
        if a.startswith("-"):
            # Python's option surface evolves. Guessing whether an unknown option
            # consumes the next token can turn its value into a phantom hook.
            return None
        return a
    return None


def _node_script(args: list[str]) -> str | None:
    if not args:
        return None
    for i, a in enumerate(args):
        if a == "--":
            return args[i + 1] if i + 1 < len(args) else None
        if a.startswith("-"):
            # Node has many options whose values may be separate path-like tokens
            # (`--require X`, `--loader X`, ...). Until that grammar is explicitly
            # modelled, any pre-script option is unclassified rather than guessed.
            return None
        return a
    return None


def _simple_script_interpreter(args: list[str]) -> str | None:
    if not args:
        return None
    if args[0] == "--":
        return args[1] if len(args) > 1 else None
    # bash/ruby/perl all have value-taking options. The common registered-hook
    # shape is simply `<interpreter> /abs/script`; anything more complex needs a
    # reviewed grammar before it can be called complete.
    if args[0].startswith("-"):
        return None
    return args[0]


def _interpreter_script(tokens: list[str]) -> str | None:
    """Return a script operand only for interpreter shapes we can classify exactly."""
    if not tokens:
        return None
    head = os.path.basename(tokens[0]).lower()
    args = tokens[1:]
    if head in {"python", "python2", "python3", "python.exe", "python3.exe"}:
        return _python_script(args)
    if head in {"node", "node.exe"}:
        return _node_script(args)
    if head in {"bash", "sh", "zsh", "ruby", "perl"}:
        return _simple_script_interpreter(args)
    return None


def _command_target(command: str) -> tuple[str | None, str | None]:
    """Return `(target, reason_if_unclassified)` for one registered command."""
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError as e:
        raise ValueError(f"cannot tokenize registered command {command!r}: {e}") from e

    tokens = _strip_env_prefix(tokens)
    if not tokens:
        return None, "empty after environment assignments"

    # `/usr/bin/env VAR=v python3 /abs/hook.py`.
    if os.path.basename(tokens[0]) == "env":
        rest = tokens[1:]
        while rest and (rest[0].startswith("-") or _ENV_ASSIGN.match(rest[0])):
            # `env -S` has its own string grammar; guessing through it would turn
            # a wrapper we do not understand into a confident target.
            if rest[0] == "-S":
                return None, "env -S wrapper not classified"
            rest = rest[1:]
        tokens = rest
        if not tokens:
            return None, "env has no command"

    head = tokens[0]
    expanded_head = os.path.expandvars(os.path.expanduser(head))
    if os.path.isabs(expanded_head):
        return _expand_path(expanded_head), None

    if os.path.basename(head).lower() in _INTERPRETERS:
        script = _interpreter_script(tokens)
        if script is None:
            return None, "interpreter invocation has no safely classifiable script operand"
        expanded = os.path.expandvars(os.path.expanduser(script))
        if os.path.isabs(expanded):
            return _expand_path(expanded), None
        return None, "interpreter script operand is not absolute"

    # Do not scan arbitrary arguments for absolute paths. That was the CBP
    # `--workspace /abs/dir` phantom. A command whose executable is not itself an
    # absolute artifact and not a known interpreter is recorded as unclassified.
    return None, "command head is neither an absolute artifact nor a known interpreter"


def resolve_registration(
    expects_path: str | os.PathLike[str],
    home: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    expects = Path(expects_path)
    try:
        manifest = json.loads(expects.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return _result("unparseable", expects=str(expects), error=str(e))

    install = manifest.get("install") or {}
    reg = install.get("registration") or {}
    segs = reg.get("path") or []
    reader = reg.get("reader") or ""
    member = expects.parent.name
    if not isinstance(segs, list) or not segs or not reader:
        return _result("not_declared", member=member, expects=str(expects))
    if not all(isinstance(s, str) and s for s in segs):
        return _result(
            "unparseable",
            member=member,
            expects=str(expects),
            error="registration.path must be non-empty string segments",
        )
    if reader not in {"json-hook-commands", "toml-hook-commands"}:
        return _result(
            "unknown_reader", member=member, expects=str(expects), reader=reader
        )

    root = Path(home) if home is not None else Path.home()
    registration = root.joinpath(*segs)
    try:
        text = registration.read_text(encoding="utf-8")
    except FileNotFoundError:
        return _result(
            "not_present",
            member=member,
            expects=str(expects),
            reader=reader,
            registration_path=str(registration),
        )
    except (PermissionError, OSError) as e:
        return _result(
            "unreadable",
            member=member,
            expects=str(expects),
            reader=reader,
            registration_path=str(registration),
            error=str(e),
        )

    try:
        commands: list[str] = []
        if reader == "json-hook-commands":
            _commands_from_json(json.loads(text), commands)
        else:
            commands = _commands_from_toml_text(text)

        targets: list[dict[str, Any]] = []
        discarded: list[dict[str, str]] = []
        unclassified: list[dict[str, str]] = []
        seen: set[str] = set()
        for command in commands:
            target, why = _command_target(command)
            if target is None:
                unclassified.append({"command": command, "reason": why or "unclassified"})
                continue
            kind = _kind(target)
            if kind == "directory":
                discarded.append(
                    {"path": target, "reason": "existing directory is not a hook artifact"}
                )
                continue
            if target in seen:
                continue
            seen.add(target)
            targets.append(
                {
                    "path": target,
                    "basename": os.path.basename(target),
                    "exists": kind != "missing",
                    "kind": kind,
                }
            )
    except (ValueError, TypeError) as e:
        return _result(
            "unparseable",
            member=member,
            expects=str(expects),
            reader=reader,
            registration_path=str(registration),
            error=str(e),
        )

    return _result(
        "ok",
        member=member,
        expects=str(expects),
        reader=reader,
        registration_path=str(registration),
        commands_seen=len(commands),
        complete=(len(unclassified) == 0),
        targets=targets,
        discarded=discarded,
        unclassified_commands=unclassified,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("expects", help="member plugins/<member>/expects.json")
    ap.add_argument("--home", help="override HOME for registration resolution / tests")
    ns = ap.parse_args(argv)
    result = resolve_registration(ns.expects, ns.home)
    print(json.dumps(result, indent=2, sort_keys=True))
    return _STATE_RC[result["state"]]


if __name__ == "__main__":
    raise SystemExit(main())
