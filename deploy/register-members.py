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
FORCE_LINE_SCAN = False   # tests set this to exercise the fallback reader on a host with tomllib
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
ALL_MATCHERS = (None, "", "*", ".*", ".+")


def covers(have, want) -> bool:
    """Does an existing registration's matcher cover what the template's matcher asks for?
    A template matcher that matches every tool (absent, "", "*", ".*") is covered only by an
    existing matcher that also matches every tool; a specific one is covered by itself or by an
    all-tools matcher. #1142 review: a gate registered only for `Read` was reported as "every
    templated hook is registered" because presence was judged by basename and event alone."""
    if have is UNPARSED:
        return False                      # never certify a gate whose matcher could not be read
    if have in ALL_MATCHERS:
        return True
    if want in ALL_MATCHERS:
        return False
    return have == want


def registered_json(path: str) -> dict[str, dict[str, list]]:
    """{event: {target basename: [matcher of each group that registers it]}} —
    json-hook-commands semantics. A group with no `matcher` key is recorded as None (all tools)."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    out: dict[str, dict[str, list]] = {}
    for event, groups in (data.get("hooks") or {}).items():
        if not isinstance(groups, list):
            continue
        for g in groups:
            if not isinstance(g, dict):
                continue
            m = g.get("matcher")
            for h in g.get("hooks") or []:
                if isinstance(h, dict) and isinstance(h.get("command"), str):
                    b = target_basename(h["command"])
                    if b:
                        out.setdefault(event, {}).setdefault(b, []).append(m)
    return out


UNPARSED = object()   # a matcher line the fallback reader could not decode: covers NOTHING


def _toml_structural(path: str):
    """{event: {basename: [matcher]}} from a real TOML parse, or None when no parser is available
    (or FORCE_LINE_SCAN is set, for the tests of the fallback)."""
    if FORCE_LINE_SCAN:
        return None
    try:
        import tomllib  # type: ignore
    except ImportError:
        return None
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    out: dict[str, dict[str, list]] = {}
    for event, groups in (data.get("hooks") or {}).items():
        if not isinstance(groups, list):
            continue
        for g in groups:
            if not isinstance(g, dict):
                continue
            m = g.get("matcher")
            m = m if (m is None or isinstance(m, str)) else UNPARSED
            for h in g.get("hooks") or []:
                cmd = h.get("command") if isinstance(h, dict) else None
                b = target_basename(cmd) if isinstance(cmd, str) else None
                if b:
                    out.setdefault(event, {}).setdefault(b, []).append(m)
    return out


# one TOML string value, basic ("...", with escapes) or literal ('...'), then optional whitespace and an
# optional comment -- the forms the fallback accepts; anything else on a matcher line is UNPARSED
_TOML_VALUE = r"""\s*=\s*(?:"((?:[^"\\]|\\.)*)"|'([^']*)')\s*(?:#.*)?$"""
_MATCHER_LINE = re.compile(r"\s*matcher" + _TOML_VALUE)
_CMD_LINE = re.compile(r"\s*command" + _TOML_VALUE)


def _toml_basic(s: str) -> str:
    """Decode a TOML basic string body (the escapes TOML shares with JSON)."""
    try:
        return json.loads('"' + s + '"')
    except ValueError:
        return s


def registered_toml(path: str) -> dict[str, dict[str, list]]:
    """{event: {target basename: [matcher of each group that registers it]}} -- toml-hook-commands
    semantics. A structural parse (tomllib) when the host has one; otherwise a line scan, in which the
    event is the nearest `[[hooks.<Event>...]]` header and the matcher the `matcher = ...` line under
    the nearest GROUP header, None when the group has none.

    #1142 re-review P1: the old scan required the closing quote to END the line, so
    `matcher = "shell" # deliberately narrow` was not recognised, the matcher stayed None, and None is
    all-tools -- a narrow gate certified as complete. Now a matcher line the scan cannot decode is
    UNPARSED, which covers nothing: an unreadable matcher can never become a wider one."""
    got = _toml_structural(path)
    if got is not None:
        return got
    out: dict[str, dict[str, list]] = {}
    event, matcher = None, None
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = re.match(r"\s*\[\[\s*hooks\.([A-Za-z_]+)(\.hooks)?\s*\]\]", line)
            if m:
                event = m.group(1)
                if not m.group(2):
                    matcher = None
                continue
            if re.match(r"\s*\[", line):            # any other table ends the hooks context
                event = None
                continue
            if not event:
                continue
            if re.match(r"\s*matcher\s*=", line):
                mm = _MATCHER_LINE.match(line)
                if mm is None:
                    matcher = UNPARSED
                else:
                    matcher = _toml_basic(mm.group(1)) if mm.group(1) is not None else mm.group(2)
                continue
            mc = _CMD_LINE.match(line)
            if mc:
                cmd = _toml_basic(mc.group(1)) if mc.group(1) is not None else mc.group(2)
                b = target_basename(cmd)
                if b:
                    out.setdefault(event, {}).setdefault(b, []).append(matcher)
    return out


def target_path(cmd: str) -> str | None:
    """The installer's rule, the whole path: the first token that is an absolute path."""
    for tok in cmd.split():
        if tok.startswith("/"):
            return tok
    return None


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


def _decide(groups: dict, have: dict, dry: bool, plan: bool):
    """For each templated hook: present (a covering registration exists), NARROW (registered only
    under a matcher that does not cover the template's -- reported, never silently widened, never
    counted as present), PENDING (its target file is not installed yet -- never registered, so no
    live registration points at a missing file), or WANT (register it).
    -> (want [(event, group, hook)], narrow [str], pending [str], planned [(base, target)])"""
    want, narrow, pending, planned = [], [], [], []
    for event, gs in groups.items():
        for g in gs:
            tm = g.get("matcher")
            for h in g["hooks"]:
                b = target_basename(h["command"]) or ""
                t = target_path(h["command"])
                existing = have.get(event, {}).get(b)
                if existing:
                    if any(covers(m, tm) for m in existing):
                        continue
                    narrow.append(f"{event}/{b} is registered only for matcher "
                                  f"{', '.join('<unreadable>' if m is UNPARSED else repr(m) for m in existing)}; "
                                  f"the template wants {tm!r} "
                                  f"-- left as it is, not reported as registered")
                    continue
                planned.append((b, t))
                if plan:
                    continue
                if not dry and (t is None or not os.path.isfile(t)):
                    pending.append(f"{event}/{b} -> {t} is not installed yet; not registered "
                                   f"(install-members.sh installs it, then registers)")
                    continue
                want.append((event, g, h))
    return want, narrow, pending, planned


def register_member(member: str, spec: dict, template: dict, home: str, dry: bool,
                    plan: bool = False) -> tuple[str, list[str]]:
    """-> (verdict, lines). verdict in {registered, ok, skip, refused, failed, narrow, pending, plan}.
    `lines` are the changes made (or planned: 'base\ttarget'), then any 'NARROW ...' / 'PENDING ...'."""
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
    if reader not in ("json-hook-commands", "toml-hook-commands"):
        return "skip", [f"unknown registration reader {reader!r} — refusing to guess"]

    raw, data = "", {}
    if os.path.exists(cfg):
        with open(cfg, encoding="utf-8", errors="replace") as fh:
            raw = fh.read()
        if reader == "json-hook-commands":
            try:
                data = json.loads(raw) if raw.strip() else {}
            except ValueError as e:
                return "failed", [f"{cfg} is not parseable JSON ({e}); refusing to guess"]
            if not isinstance(data, dict):
                return "failed", [f"{cfg} is not a JSON object"]
            have = registered_json(cfg) if raw.strip() else {}
        else:
            have = registered_toml(cfg)
    else:
        have = {}

    want, narrow, pending, planned = _decide(groups, have, dry, plan)
    notes = [f"NARROW {n}" for n in narrow] + [f"PENDING {p}" for p in pending]
    if plan:
        return "plan", [f"{b}\t{t}" for b, t in planned] + notes

    changes: list[str] = []
    if reader == "json-hook-commands":
        hooks = data.setdefault("hooks", {})
        for event, g, h in want:
            hooks.setdefault(event, []).append({**{k: v for k, v in g.items() if k != "hooks"}, "hooks": [h]})
            changes.append(f"{event}/{target_basename(h['command'])}")
        if changes and not dry:
            new = json.dumps(data, indent=2) + "\n"
            json.loads(new)
            if raw:
                _backup(cfg)
            _write_atomic(cfg, new)
    else:
        new = raw
        for event, g, h in want:
            new += toml_block(member, event, g, h)
            changes.append(f"{event}/{target_basename(h['command'])}")
        new, ensured = toml_ensure(new, reg.get("ensure") or [])
        changes += [f"ensure {e}" for e in ensured]
        if changes:
            err = validate_toml(new)
            if err:
                return "failed", [f"rendered {cfg} would not parse ({err}); nothing written"] + notes
            if not dry:
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
                    return "failed", [f"{cfg} failed to parse after write ({err}); restored as it was"] + notes

    lines = ([f"would add {c}" for c in changes] if dry else changes) + notes
    # #1142 re-review P2: a run that registered some hooks and left others PENDING returned
    # "registered" and exited 0. Narrow and pending are unfinished work: they outrank a partial
    # registration (the additions are still in `lines` and still reported).
    if narrow:
        return "narrow", lines
    if pending:
        return "pending", lines
    if changes:
        return "registered", lines
    return "ok", lines


def main(argv: list[str]) -> int:
    plugins = os.path.join(REPO_ROOT, "plugins")
    home = os.path.expanduser("~")
    only = None
    plan = False
    it = iter(argv)
    for a in it:
        if a == "--plugins":
            plugins = next(it)
        elif a == "--home":
            home = next(it)
        elif a == "--member":
            only = next(it)
        elif a == "--plan":
            plan = True
        elif a in ("-h", "--help"):
            print(__doc__)
            return 0
    dry = ENV.get("DRY_RUN") == "1"
    rc = 0
    if not plan:
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
            if spec.get("registration") and not plan:
                log(f"  skip  {member} — declares a registration but ships no hooks/hooks.json "
                    "template; its registration stays a hand edit until it does")
            continue
        with open(tpl, encoding="utf-8") as fh:
            template = json.load(fh)
        verdict, lines = register_member(member, spec, template, home, dry, plan=plan)
        if plan:
            # machine-readable, for install-members.sh: member<TAB>basename<TAB>absolute target
            for ln in lines:
                if "\t" in ln and not ln.startswith(("NARROW", "PENDING")):
                    print(f"{member}\t{ln}", flush=True)
            continue
        adds = [ln for ln in lines if not ln.startswith(("NARROW ", "PENDING "))]
        notes = [ln for ln in lines if ln.startswith(("NARROW ", "PENDING "))]
        if verdict in ("registered", "narrow", "pending", "ok"):
            for c in adds:
                log(f"  {'would' if dry else 'REGISTERED'} {member}: {c}")
            for n in notes:
                log(f"  {n.split(' ', 1)[0]} {member}: {n.split(' ', 1)[1]}")
            if verdict == "ok":
                log(f"  ok    {member} — every templated hook is registered")
            # the exit code comes from the NOTES, not the headline verdict: a member can be narrow AND
            # pending, and neither may be hidden behind the other or behind a successful addition
            if any(n.startswith("NARROW ") for n in notes):
                rc = rc or 8
            if any(n.startswith("PENDING ") for n in notes):
                rc = rc or 9
        elif verdict == "skip":
            log(f"  skip  {member} — {'; '.join(lines)}")
        elif verdict == "refused":
            log(f"  REFUSED {member} — {'; '.join(lines)}")
            rc = rc or 7
        else:
            log(f"  FAILED {member} — {'; '.join(lines)}")
            rc = 6
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
