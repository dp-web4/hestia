#!/usr/bin/env python3
"""Register every installed member's hestia hooks in that member's OWN harness config.

dp, 2026-09-27 (#1133): "the auto install process is supposed to take care of all this. isn't
there a script? editing files by hand is unacceptable friction for product we're trying to
release generally." There was no script. `deploy/install-members.sh` copies a hook file only
where the harness ALREADY registers it (it derives the target from the registration, never
from `expects.json`'s dest — #315), and the daemon's `install_claude_code` (core/src/
orchestrators.rs) merges exactly one hook for one member. Every other registration was a hand
edit, which is how codex ran 14 days with `witness.py` registered nowhere: skipped by the
installer every cycle ("not registered on this host") and read as governed by the inventory.

This script closes the loop the installer left open. For each `plugins/<member>/expects.json`
that declares `install.registration` and ships a `hooks/hooks.json` template:

  1. Is the harness on this host?  Its config DIRECTORY exists (`~/.codex`, `~/.claude`, ...).
     Absent -> skip, said aloud. Never mint a registration for a harness that is not here
     (#1130: "offer and accept only what is installed here").
  2. Render the template: `@HESTIA_PLUGIN_ROOT@/<member>/hooks/<file>` -> `<install.dest>/<file>`
     (the declared dest, which install-members.sh will then find REGISTERED and install to —
     the two scripts agree by construction). `HESTIA_WORKSPACE=@HESTIA_WORKSPACE@` renders from
     the environment when set and is dropped when not (every hook has a default). Any other
     placeholder left unrendered REFUSES the member: a template that advertises a path nobody
     rendered must never reach a config (plugins/codex/README.md).
  3. Merge, idempotently, by TARGET BASENAME: a hook whose file is already registered on that
     event — by any command, any spelling — is left exactly as it is. Only the missing ones are
     added, as a new matcher group (JSON: appended to `hooks.<Event>`; TOML: an appended
     `[[hooks.<Event>]]` + `[[hooks.<Event>.hooks]]` block under a marker comment). Nothing
     already in the file is rewritten or reordered; a second run is a byte-identical no-op.
  4. Validate the result before it stands: JSON must reload; TOML must parse under tomllib
     when the interpreter has it (3.11+). A failed parse restores the backup and exits 6 —
     a broken hook table would disable EVERY hook, gate included, which is worse than the gap.
  5. `install.registration.ensure` (optional): lines a harness needs for hooks to fire at
     all — codex's `[features] codex_hooks = true`. Added only when the key is absent.

Reader semantics are the installer's (json-hook-commands / toml-hook-commands: the target is
the absolute-path token of a `command` value); this script reads registration exactly the way
install-members.sh does, so what it writes is what the installer will see.

    DRY_RUN=1      print what would change, write nothing (exit 0)
    --plugins DIR  read plugin dirs from DIR (tests); default: this checkout's plugins/
    --home DIR     treat DIR as the home directory (tests); default: ~
    --member NAME  only this member

Exit: 0 clean (registered or nothing to do); 6 a write failed validation and was restored;
7 a template carries an unrendered placeholder (that member skipped, others proceed).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
MARK = "# hestia: registered by deploy/register-members.py"
_PLACEHOLDER = re.compile(r"@[A-Z_]+@")
_TOML_CMD = re.compile(r"""\s*command\s*=\s*(['"])(.*)\1\s*$""")
ENV = os.environ


class Unrendered(Exception):
    pass


def log(msg: str) -> None:
    print(msg, flush=True)


# ---------------------------------------------------------------- rendering --------------
def render_command(cmd: str, member: str, dest: str) -> str:
    cmd = cmd.replace(f"@HESTIA_PLUGIN_ROOT@/{member}/hooks/", dest.rstrip("/") + "/")
    ws = ENV.get("HESTIA_WORKSPACE")
    if "@HESTIA_WORKSPACE@" in cmd:
        if ws:
            cmd = cmd.replace("@HESTIA_WORKSPACE@", ws)
        else:
            cmd = re.sub(r"\bHESTIA_WORKSPACE=@HESTIA_WORKSPACE@\s+", "", cmd)
    if _PLACEHOLDER.search(cmd):
        raise Unrendered(cmd)
    return cmd


def target_basename(cmd: str) -> str | None:
    """The installer's rule: the target is the token that is an absolute path."""
    for tok in cmd.split():
        if tok.startswith("/"):
            return os.path.basename(tok)
    return None


def rendered_groups(template: dict, member: str, dest: str) -> dict[str, list[dict]]:
    """{event: [{matcher?, hooks:[{type, command, statusMessage?, timeout?}]}]} with commands
    rendered. Raises Unrendered."""
    hooks = template.get("hooks", template)
    out: dict[str, list[dict]] = {}
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            continue
        for g in groups:
            if not isinstance(g, dict):
                continue
            ng = {k: v for k, v in g.items() if k != "hooks"}
            ng["hooks"] = []
            for h in g.get("hooks") or []:
                if not isinstance(h, dict) or not isinstance(h.get("command"), str):
                    continue
                nh = dict(h)
                nh["command"] = render_command(h["command"], member, dest)
                ng["hooks"].append(nh)
            if ng["hooks"]:
                out.setdefault(event, []).append(ng)
    return out


# ---------------------------------------------------------------- reading ----------------
def registered_json(path: str) -> dict[str, set[str]]:
    """{event: {target basenames}} — json-hook-commands semantics."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    out: dict[str, set[str]] = {}
    for event, groups in (data.get("hooks") or {}).items():
        if not isinstance(groups, list):
            continue
        for g in groups:
            for h in (g.get("hooks") or []) if isinstance(g, dict) else []:
                if isinstance(h, dict) and isinstance(h.get("command"), str):
                    b = target_basename(h["command"])
                    if b:
                        out.setdefault(event, set()).add(b)
    return out


def registered_toml(path: str) -> dict[str, set[str]]:
    """{event: {target basenames}} — toml-hook-commands semantics (a line scan: the installer
    deliberately does not require tomllib). The event is the nearest preceding
    `[[hooks.<Event>...]]` header."""
    out: dict[str, set[str]] = {}
    event = None
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = re.match(r"\s*\[\[\s*hooks\.([A-Za-z_]+)", line)
            if m:
                event = m.group(1)
                continue
            m = _TOML_CMD.match(line)
            if m and event:
                b = target_basename(m.group(2))
                if b:
                    out.setdefault(event, set()).add(b)
    return out


# ---------------------------------------------------------------- writing ----------------
def _backup(path: str) -> None:
    bak = path + ".pre-register.bak"
    if not os.path.exists(bak):
        shutil.copy2(path, bak)


def _write_atomic(path: str, text: str) -> None:
    """Write `text` to `path` so a crash leaves the old file or the new one, never half of one.
    The temp file takes the original's mode: ~/.codex/config.toml is 0600, and a fresh temp file
    (0644 under the usual umask) would loosen a harness config every time this ran."""
    d = os.path.dirname(path) or "."
    tmp = os.path.join(d, f".{os.path.basename(path)}.register-tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    if os.path.exists(path):
        shutil.copymode(path, tmp)
    os.replace(tmp, path)


def _toml_str(s: str) -> str:
    return json.dumps(s)          # a JSON string literal is a valid TOML basic string


def toml_block(member: str, event: str, group: dict, hook: dict) -> str:
    lines = [f"\n{MARK} ({member}) — do not hand-edit; re-run deploy/install-members.sh",
             f"[[hooks.{event}]]"]
    if isinstance(group.get("matcher"), str):
        lines.append(f"matcher = {_toml_str(group['matcher'])}")
    lines += ["", f"[[hooks.{event}.hooks]]",
              f"type = {_toml_str(str(hook.get('type', 'command')))}",
              f"command = {_toml_str(hook['command'])}"]
    if isinstance(hook.get("statusMessage"), str):
        lines.append(f"statusMessage = {_toml_str(hook['statusMessage'])}")
    t = hook.get("timeout")
    if isinstance(t, (int, float)) and not isinstance(t, bool):
        lines.append(f"timeout = {int(t)}")
    return "\n".join(lines) + "\n"


def toml_ensure(text: str, ensure: list[dict]) -> tuple[str, list[str]]:
    """Add `line` under `[table]` when no `key =` exists anywhere. Insert after an existing
    header; append the table when there is none."""
    added = []
    for e in ensure or []:
        key, line, table = e.get("key"), e.get("line"), e.get("table")
        if not (key and line and table):
            continue
        if re.search(rf"^\s*{re.escape(key)}\s*=", text, re.M):
            continue
        hdr = re.compile(rf"^\s*\[{re.escape(table)}\]\s*$", re.M)
        m = hdr.search(text)
        if m:
            text = text[:m.end()] + "\n" + line + text[m.end():]
        else:
            text = text.rstrip("\n") + f"\n\n[{table}]\n{line}\n"
        added.append(f"[{table}] {line}")
    return text, added


def validate_toml(text: str) -> str | None:
    try:
        import tomllib  # type: ignore
    except ImportError:
        return None                       # no parser here: the line scan is the reader anyway
    try:
        tomllib.loads(text)
        return None
    except Exception as e:                # noqa: BLE001
        return f"{type(e).__name__}: {e}"


def register_member(member: str, spec: dict, template: dict, home: str, dry: bool) -> tuple[str, list[str]]:
    """-> (verdict, changes). verdict in {registered, ok, skip, refused, failed}."""
    reg = spec.get("registration") or {}
    segs, reader = reg.get("path") or [], reg.get("reader", "")
    dest = spec.get("dest") or ""
    if not segs or not reader or not dest:
        return "skip", ["declares no install.registration/dest — nothing to render into"]
    cfg = os.path.join(home, *segs)
    cfg_dir = os.path.dirname(cfg)
    if not os.path.isdir(cfg_dir):
        return "skip", [f"{cfg_dir} absent — harness not on this host"]
    dest = os.path.join(home, dest[2:]) if dest.startswith("~/") else os.path.expanduser(dest)
    try:
        groups = rendered_groups(template, member, dest)
    except Unrendered as e:
        return "refused", [f"template carries an unrendered placeholder: {e}"]
    if not groups:
        return "skip", ["template registers no command hooks"]

    changes: list[str] = []
    if reader == "json-hook-commands":
        if os.path.exists(cfg):
            with open(cfg, encoding="utf-8") as fh:
                raw = fh.read()
            try:
                data = json.loads(raw)
            except ValueError as e:
                return "failed", [f"{cfg} is not parseable JSON ({e}); refusing to guess"]
            have = registered_json(cfg)
        else:
            raw, data, have = "", {}, {}
        if not isinstance(data, dict):
            return "failed", [f"{cfg} is not a JSON object"]
        hooks = data.setdefault("hooks", {})
        for event, gs in groups.items():
            for g in gs:
                want = [h for h in g["hooks"]
                        if target_basename(h["command"]) not in have.get(event, set())]
                if not want:
                    continue
                hooks.setdefault(event, []).append(
                    {**{k: v for k, v in g.items() if k != "hooks"}, "hooks": want})
                for h in want:
                    b = target_basename(h["command"]) or ""
                    changes.append(f"{event}/{b}")
                    have.setdefault(event, set()).add(b)
        if not changes:
            return "ok", []
        if dry:
            return "registered", [f"would add {c}" for c in changes]
        new = json.dumps(data, indent=2) + "\n"
        json.loads(new)
        if raw:
            _backup(cfg)
        _write_atomic(cfg, new)
        return "registered", changes

    if reader == "toml-hook-commands":
        if os.path.exists(cfg):
            with open(cfg, encoding="utf-8", errors="replace") as fh:
                raw = fh.read()
            have = registered_toml(cfg)
        else:
            raw, have = "", {}
        new = raw
        for event, gs in groups.items():
            for g in gs:
                for h in g["hooks"]:
                    b = target_basename(h["command"])
                    if b in have.get(event, set()):
                        continue
                    new += toml_block(member, event, g, h)
                    changes.append(f"{event}/{b}")
                    have.setdefault(event, set()).add(b or "")
        new, ensured = toml_ensure(new, reg.get("ensure") or [])
        changes += [f"ensure {e}" for e in ensured]
        if not changes:
            return "ok", []
        err = validate_toml(new)
        if err:
            return "failed", [f"rendered {cfg} would not parse ({err}); nothing written"]
        if dry:
            return "registered", [f"would add {c}" for c in changes]
        if raw:
            _backup(cfg)
        _write_atomic(cfg, new)
        with open(cfg, encoding="utf-8", errors="replace") as fh:
            back = fh.read()
        err = validate_toml(back)
        if err:
            # Restore what THIS run read, not `.pre-register.bak`: that backup is written once,
            # on the first run ever, so restoring it would roll the harness config back past
            # every edit made since. A file that did not exist goes back to not existing.
            if raw:
                _write_atomic(cfg, raw)
            else:
                os.remove(cfg)
            return "failed", [f"{cfg} failed to parse after write ({err}); restored as it was"]
        return "registered", changes

    return "skip", [f"unknown registration reader {reader!r} — refusing to guess"]


def main(argv: list[str]) -> int:
    plugins = os.path.join(REPO_ROOT, "plugins")
    home = os.path.expanduser("~")
    only = None
    it = iter(argv)
    for a in it:
        if a == "--plugins":
            plugins = next(it)
        elif a == "--home":
            home = next(it)
        elif a == "--member":
            only = next(it)
        elif a in ("-h", "--help"):
            print(__doc__)
            return 0
    dry = ENV.get("DRY_RUN") == "1"
    rc = 0
    log(f"register-members: plugins={plugins} home={home}{' DRY RUN' if dry else ''}")
    for member in sorted(os.listdir(plugins)):
        if only and member != only:
            continue
        expects = os.path.join(plugins, member, "expects.json")
        tpl = os.path.join(plugins, member, "hooks", "hooks.json")
        if not os.path.isfile(expects):
            continue
        try:
            with open(expects, encoding="utf-8") as fh:
                spec = json.load(fh).get("install") or {}
        except ValueError:
            log(f"  skip  {member} — expects.json unparseable")
            continue
        if not os.path.isfile(tpl):
            if spec.get("registration"):
                log(f"  skip  {member} — declares a registration but ships no hooks/hooks.json "
                    "template; its registration stays a hand edit until it does")
            continue
        with open(tpl, encoding="utf-8") as fh:
            template = json.load(fh)
        verdict, changes = register_member(member, spec, template, home, dry)
        if verdict == "ok":
            log(f"  ok    {member} — every templated hook is registered")
        elif verdict == "registered":
            for c in changes:
                log(f"  {'would' if dry else 'REGISTERED'} {member}: {c}")
        elif verdict == "skip":
            log(f"  skip  {member} — {'; '.join(changes)}")
        elif verdict == "refused":
            log(f"  REFUSED {member} — {'; '.join(changes)}")
            rc = rc or 7
        else:
            log(f"  FAILED {member} — {'; '.join(changes)}")
            rc = 6
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
