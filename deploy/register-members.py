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

  6. THE TIMEOUT IS THE GATE'S BOUND (one-gate stage C). Every seat's gate READS the timeout
     its harness registered and decides inside `start + timeout - margin`, so it always fails
     closed before the harness kills it and fails open. Registration length is therefore the
     AVAILABILITY knob: a template's value (claude-code 10 s, codex 15 s, kimi 15 s, gemini
     15000 ms) absorbs one cold member connect (measured 4.6-5.1 s); a shorter one turns that
     connect into a recorded denial. A templated hook already registered with a SHORTER timeout
     (or none) is reported SHORT (exit 10) and, with --raise-timeouts, raised to the template's
     value in place — raised only, never lowered, nothing else on the line touched. A registered
     gate command carrying an env override no gate reads any more (HESTIA_PRE_TOTAL_BUDGET_MS,
     HESTIA_PRE_REQUEST_TIMEOUT_S, a per-seat HESTIA_<SEAT>_GATE_MODE) is reported INERT; the
     script never rewrites a command, so removing it is the operator's edit.

    DRY_RUN=1        print what would change, write nothing (exit 0)
    --plugins DIR    read plugin dirs from DIR (tests); default: this checkout's plugins/
    --home DIR       treat DIR as the home directory (tests); default: ~
    --member NAME    only this member
    --raise-timeouts raise every SHORT templated hook's timeout to the template's value

Exit: 0 clean (registered or nothing to do); 6 a write failed validation and was restored;
7 a template carries an unrendered placeholder (that member skipped, others proceed); 8 narrow;
9 pending; 10 a templated hook is registered with a timeout below its template's.
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


def _toml_structural(path: str, flat: bool = False):
    """{event: {basename: [matcher]}} from a real TOML parse, or None when no parser is available
    (or FORCE_LINE_SCAN is set, for the tests of the fallback)."""
    if FORCE_LINE_SCAN:
        return None
    try:
        import tomllib  # type: ignore
    except ImportError:
        return None
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as e:
        # not valid TOML: nothing in it can be certified, whichever reader looks
        raise TomlUnsupported(f"not valid TOML ({e})") from e
    out: dict[str, dict[str, list]] = {}
    if flat:
        for tbl in data.get("hooks") or []:
            if not isinstance(tbl, dict) or not isinstance(tbl.get("event"), str):
                continue
            m = tbl.get("matcher")
            m = m if (m is None or isinstance(m, str)) else UNPARSED
            cmd = tbl.get("command")
            b = target_basename(cmd) if isinstance(cmd, str) else None
            if b:
                out.setdefault(tbl["event"], {}).setdefault(b, []).append(m)
        return out
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


class TomlUnsupported(Exception):
    """The fallback reader met TOML it cannot verify. The registrar refuses to certify anything."""


# The fallback's whole grammar. Keys: bare or quoted. Headers: [a.b] / [[a.b]] with bare or quoted
# segments. Values: one basic or literal string, an integer, or a boolean. Each line may end in a comment.
_KEY = r"""(?:[A-Za-z0-9_-]+|"(?:[^"\\]|\\.)*"|'[^']*')"""
_KEYPATH = rf"{_KEY}(?:\s*\.\s*{_KEY})*"
_HEADER = re.compile(rf"""^\s*(\[\[|\[)\s*({_KEYPATH})\s*(\]\]|\])\s*(?:#.*)?$""")
_ASSIGN = re.compile(rf"""^\s*({_KEYPATH})\s*=\s*(.*?)\s*$""")
_VALUE = re.compile(r"""^(?:"((?:[^"\\]|\\.)*)"|'([^']*)'|([+-]?[0-9_]+)|(true|false))\s*(?:#.*)?$""")
_KEYSEG = re.compile(_KEY)


_TOML_ESCAPES = {"b": "\b", "t": "\t", "n": "\n", "f": "\f", "r": "\r", '"': '"', "\\": "\\"}


def _toml_basic(s: str) -> str:
    r"""Decode a TOML basic-string body EXACTLY (TOML 1.0: \b \t \n \f \r \" \\ \uXXXX \UXXXXXXXX), or raise
    TomlUnsupported. Never return the raw spelling: #1142's fourth review showed `"\U0000006datcher"` -- a
    valid TOML spelling of `matcher` -- decoded by JSON (which has no \U escape), failed, came back raw, and
    became an unrelated key, so a narrow gate read as all-tools."""
    out, i, n = [], 0, len(s)
    while i < n:
        ch = s[i]
        if ch == "\\":
            if i + 1 >= n:
                raise TomlUnsupported("a basic string ends in a lone backslash")
            e = s[i + 1]
            if e in _TOML_ESCAPES:
                out.append(_TOML_ESCAPES[e])
                i += 2
                continue
            if e in ("u", "U"):
                width = 4 if e == "u" else 8
                hexs = s[i + 2:i + 2 + width]
                if len(hexs) != width or not all(c in "0123456789abcdefABCDEF" for c in hexs):
                    raise TomlUnsupported(f"a malformed \\{e} escape in a basic string")
                cp = int(hexs, 16)
                if cp > 0x10FFFF or 0xD800 <= cp <= 0xDFFF:
                    raise TomlUnsupported(f"\\{e}{hexs} is not a Unicode scalar value")
                out.append(chr(cp))
                i += 2 + width
                continue
            raise TomlUnsupported(f"the escape \\{e} is not TOML")
        if ch != "\t" and (ord(ch) < 0x20 or ord(ch) == 0x7F):
            raise TomlUnsupported("a control character inside a basic string")
        out.append(ch)
        i += 1
    return "".join(out)


def _segments(keypath: str) -> list[str]:
    out = []
    for m in _KEYSEG.finditer(keypath):
        k = m.group(0)
        if k.startswith('"'):
            k = _toml_basic(k[1:-1])
        elif k.startswith("'"):
            k = k[1:-1]
        out.append(k)
    return out


def _toml_scan(path: str, flat: bool = False) -> tuple[dict, set]:
    """The fallback reader: ({event: {basename: [matcher]}}, {absolute target}). Raises TomlUnsupported
    on anything outside its grammar that could bear on hooks -- it never guesses.

    #1142 third review: `"matcher" = "shell"` (a quoted key, valid TOML) was not recognised, the matcher
    stayed None, and None is all-tools. Quoted keys and quoted header segments are now read the TOML way,
    and every other form the scan cannot parse is a refusal, not an absence."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    if '"' * 3 in text or "'" * 3 in text:
        raise TomlUnsupported("a multi-line string (it can hide table headers from a line scan)")
    have: dict[str, dict[str, list]] = {}
    targets: set[str] = set()
    ctx = None                     # None | ("group", event) | ("entry", event) | ("flat",) | ("other",)
    matcher = None
    table: dict = {}               # the current flat [[hooks]] table's keys

    def flush_flat() -> None:
        ev, cmd = table.get("event"), table.get("command")
        if isinstance(ev, str) and isinstance(cmd, str):
            t = target_path(cmd)
            if t:
                targets.add(t)
            b = target_basename(cmd)
            if b:
                have.setdefault(ev, {}).setdefault(b, []).append(table.get("matcher"))
    for n, line in enumerate(text.splitlines(), 1):
        st = line.strip()
        if not st or st.startswith("#"):
            continue
        h = _HEADER.match(line)
        if h:
            segs = _segments(h.group(2))
            arr = h.group(1) == "[["
            if ctx == ("flat",):
                flush_flat()
                table = {}
            if flat:
                if segs and segs[0] == "hooks":
                    if arr and segs == ["hooks"]:
                        ctx = ("flat",)
                        continue
                    raise TomlUnsupported(f"line {n}: hooks table form {st!r} in a flat layout")
                ctx = ("other",)
                continue
            if segs and segs[0] == "hooks" and not arr and len(segs) >= 2 and segs[1] == "state":
                ctx = ("other",)          # codex's per-hook approval state: defines no hooks
            elif segs and segs[0] == "hooks":
                if arr and len(segs) == 2:
                    ctx, matcher = ("group", segs[1]), None
                elif arr and len(segs) == 3 and segs[2] == "hooks" and ctx and ctx[0] in ("group", "entry") and ctx[1] == segs[1]:
                    ctx = ("entry", segs[1])
                else:
                    raise TomlUnsupported(f"line {n}: hooks table form {st!r}")
            else:
                ctx = ("other",)
            continue
        if st.startswith("["):
            raise TomlUnsupported(f"line {n}: unparseable table header {st!r}")
        a = _ASSIGN.match(line)
        segs = _segments(a.group(1)) if a else []
        in_hooks = ctx is not None and ctx[0] in ("group", "entry", "flat")
        if not a:
            if in_hooks:
                raise TomlUnsupported(f"line {n}: {st!r}")
            continue                              # an unrelated value spanning lines (a multi-line array)
        if ctx is None and segs and segs[0] == "hooks":
            raise TomlUnsupported(f"line {n}: hooks set by a top-level key {st!r}")
        if not in_hooks:
            continue
        if len(segs) != 1:
            raise TomlUnsupported(f"line {n}: dotted key inside a hooks table {st!r}")
        v = _VALUE.match(a.group(2))
        if v is None:
            raise TomlUnsupported(f"line {n}: value the scan cannot read {st!r}")
        sval = _toml_basic(v.group(1)) if v.group(1) is not None else v.group(2)
        key = segs[0]
        if ctx[0] == "flat":
            if key in ("event", "command", "matcher"):
                if sval is None:
                    raise TomlUnsupported(f"line {n}: non-string {key} {st!r}")
                if key in table:
                    raise TomlUnsupported(f"line {n}: {key} set twice in one [[hooks]] table")
                table[key] = sval
            continue
        if ctx[0] == "group" and key == "matcher":
            if sval is None:
                raise TomlUnsupported(f"line {n}: non-string matcher {st!r}")
            matcher = sval
        elif ctx[0] == "entry" and key == "command" and sval is not None:
            t = target_path(sval)
            if t:
                targets.add(t)
            b = target_basename(sval)
            if b:
                have.setdefault(ctx[1], {}).setdefault(b, []).append(matcher)
    if ctx == ("flat",):
        flush_flat()
    return have, targets


def registered_toml(path: str, flat: bool = False) -> dict[str, dict[str, list]]:
    """{event: {target basename: [matcher of each group that registers it]}} -- toml-hook-commands
    semantics. A structural parse (tomllib) when the host has one; otherwise `_toml_scan`, which
    refuses (TomlUnsupported) rather than reading an unrecognised matcher as absent -- absent is
    all-tools, so a misread would certify a narrow gate (#1142 reviews 2 and 3)."""
    got = _toml_structural(path, flat)
    if got is not None:
        return got
    return _toml_scan(path, flat)[0]


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


def toml_block_flat(member: str, event: str, hook: dict, group: dict | None = None) -> str:
    """One flat `[[hooks]]` table (kimi's layout, #1149): the event is a key, not the header. A group
    matcher that is not all-tools is carried as a `matcher` key -- dropping it would widen the gate."""
    lines = [f"\n{MARK} ({member}) — do not hand-edit; re-run deploy/install-members.sh",
             "[[hooks]]",
             f"event = {_toml_str(event)}"]
    m = (group or {}).get("matcher")
    if isinstance(m, str) and m not in ALL_MATCHERS:
        lines.append(f"matcher = {_toml_str(m)}")
    lines.append(f"command = {_toml_str(hook['command'])}")
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


def registered_targets(cfg: str, reader: str, flat: bool = False) -> set[str]:
    """Every absolute target a config registers (the installer's rule: the first absolute path in the
    command), read structurally. Empty when the file is absent or unreadable."""
    out: set[str] = set()
    try:
        if reader == "json-hook-commands":
            with open(cfg, encoding="utf-8") as fh:
                data = json.load(fh)
            groups = (data.get("hooks") or {}).values()
        else:
            try:
                if FORCE_LINE_SCAN:
                    raise ImportError
                import tomllib  # type: ignore
            except ImportError:
                return _toml_scan(cfg, flat)[1]
            with open(cfg, "rb") as fh:
                hooks = tomllib.load(fh).get("hooks") or ({} if not flat else [])
            if flat:
                for tbl in hooks if isinstance(hooks, list) else []:
                    c = tbl.get("command") if isinstance(tbl, dict) else None
                    t = target_path(c) if isinstance(c, str) else None
                    if t:
                        out.add(t)
                return out
            groups = hooks.values()
        for gs in groups:
            for g in gs if isinstance(gs, list) else []:
                for h in (g.get("hooks") or []) if isinstance(g, dict) else []:
                    c = h.get("command") if isinstance(h, dict) else None
                    t = target_path(c) if isinstance(c, str) else None
                    if t:
                        out.add(t)
    except Exception:                     # noqa: BLE001 -- absent, unparseable, or no tomllib: no repair rows
        return set()
    return out


# ---------------------------------------------------------------- timeouts ---------------
#: Env overrides on a registered gate command that no gate reads since one-gate stage C (the
#: deadline is the registration's). Reported INERT, never rewritten.
INERT_GATE_ENV = re.compile(r"\b(HESTIA_PRE_TOTAL_BUDGET_MS|HESTIA_PRE_REQUEST_TIMEOUT_S|"
                            r"HESTIA_[A-Z]+_GATE_MODE)=\S*")


def registered_timeouts(cfg: str, reader: str, flat: bool = False):
    """{event: {basename: [(timeout or None, command)]}} read structurally, or None when the
    file cannot be read that way (absent, unparseable, or TOML without tomllib)."""
    try:
        if reader == "json-hook-commands":
            with open(cfg, encoding="utf-8") as fh:
                hooks = (json.load(fh).get("hooks") or {})
        else:
            if FORCE_LINE_SCAN:
                return None
            import tomllib  # type: ignore
            with open(cfg, "rb") as fh:
                hooks = tomllib.load(fh).get("hooks") or ({} if not flat else [])
    except Exception:  # noqa: BLE001
        return None
    out: dict[str, dict[str, list]] = {}

    def add(event, h):
        cmd = h.get("command") if isinstance(h, dict) else None
        b = target_basename(cmd) if isinstance(cmd, str) else None
        if b:
            out.setdefault(event, {}).setdefault(b, []).append((h.get("timeout"), cmd))
    if flat:
        for tbl in hooks if isinstance(hooks, list) else []:
            if isinstance(tbl, dict) and isinstance(tbl.get("event"), str):
                add(tbl["event"], tbl)
        return out
    for event, gs in (hooks.items() if isinstance(hooks, dict) else []):
        for g in gs if isinstance(gs, list) else []:
            for h in (g.get("hooks") or []) if isinstance(g, dict) else []:
                add(event, h)
    return out


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def timeout_findings(groups: dict, registered) -> tuple[list, list]:
    """(short, inert). short: (event, basename, registered timeout or None, template timeout)
    for each templated hook registered below its template's timeout (or with none); inert:
    (event, basename, [stray env assignments]) for registered gate commands carrying one."""
    short, inert = [], []
    if not registered:
        return short, inert
    for event, gs in groups.items():
        for g in gs:
            for h in g["hooks"]:
                want = h.get("timeout")
                base = target_basename(h["command"]) or ""
                for t, cmd in registered.get(event, {}).get(base, []):
                    if _is_num(want) and not (_is_num(t) and t >= want):
                        short.append((event, base, t, want))
                    stray = [m.group(0) for m in INERT_GATE_ENV.finditer(cmd or "")]
                    if stray:
                        inert.append((event, base, sorted(set(stray))))
    return short, inert


def raise_json_timeouts(data: dict, short: list) -> list[str]:
    """Raise each SHORT hook's timeout in a parsed JSON config. Returns what changed."""
    changed = []
    want = {(e, b): w for e, b, _t, w in short}
    for event, gs in (data.get("hooks") or {}).items():
        for g in gs if isinstance(gs, list) else []:
            for h in (g.get("hooks") or []) if isinstance(g, dict) else []:
                b = target_basename(h.get("command") or "") if isinstance(h, dict) else None
                w = want.get((event, b))
                if w is not None and not (_is_num(h.get("timeout")) and h["timeout"] >= w):
                    changed.append(f"timeout {event}/{b} {h.get('timeout')} -> {w}")
                    h["timeout"] = w
    return changed


def raise_toml_timeouts(text: str, short: list, flat: bool) -> tuple[str, list[str]]:
    """Raise each SHORT hook's `timeout =` line in TOML text, inside the table that carries its
    command (inserting one after the command when the table has none). Only lines of tables
    whose command names a SHORT basename are touched; every other byte is kept."""
    lines = text.split("\n")
    changed = []
    bases = {b: w for _e, b, _t, w in short}
    i = 0
    while i < len(lines):
        m = _TOML_CMD.match(lines[i])
        b = target_basename(m.group(2)) if m else None
        if b in bases:
            w = bases[b]
            j, found = i + 1, None
            start = i
            while start > 0 and not lines[start - 1].lstrip().startswith("["):
                start -= 1
            for k in list(range(start, i)) + list(range(i + 1, len(lines))):
                if k > i and lines[k].lstrip().startswith("["):
                    break
                tm = re.match(r"^(\s*timeout\s*=\s*)([0-9]+)(.*)$", lines[k])
                if tm:
                    found = k
                    break
            if found is None:
                lines.insert(i + 1, f"timeout = {int(w)}")
                changed.append(f"timeout {b} (none) -> {int(w)}")
                j = i + 2
            else:
                tm = re.match(r"^(\s*timeout\s*=\s*)([0-9]+)(.*)$", lines[found])
                if int(tm.group(2)) < w:
                    lines[found] = f"{tm.group(1)}{int(w)}{tm.group(3)}"
                    changed.append(f"timeout {b} {tm.group(2)} -> {int(w)}")
            i = j
            continue
        i += 1
    return "\n".join(lines), changed


def _decide(groups: dict, have: dict, dry: bool, plan: bool, own: set | None = None):
    """For each templated hook: present (a covering registration exists), NARROW (registered only
    under a matcher that does not cover the template's -- reported, never silently widened, never
    counted as present), PENDING (its target file is not installed yet -- never registered, so no
    live registration points at a missing file), or WANT (register it).
    -> (want [(event, group, hook)], narrow [str], pending [str], planned [(base, target)])"""
    want, narrow, pending, planned = [], [], [], []
    own = own or set()
    for event, gs in groups.items():
        for g in gs:
            tm = g.get("matcher")
            for h in g["hooks"]:
                b = target_basename(h["command"]) or ""
                t = target_path(h["command"])
                existing = have.get(event, {}).get(b)
                if existing:
                    if any(covers(m, tm) for m in existing):
                        # registered -- but a registration is only as good as the file it names. When the
                        # registration names THIS template's target (one this script wrote) and that file is
                        # missing -- a host left registered with nothing installed (HUB 2026-09-28, #1153) --
                        # it is PENDING, not ok, and --plan lists it so the installer puts the file there.
                        # A registration naming some other path is the installer's to check, as before.
                        if t is not None and t in own and not os.path.isfile(t):
                            if plan:
                                planned.append((b, t))
                            elif not dry:
                                pending.append(f"{event}/{b} is registered but {t} is not installed "
                                               f"(install-members.sh installs it)")
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
                    plan: bool = False, raise_timeouts: bool = False) -> tuple[str, list[str]]:
    """-> (verdict, lines). verdict in {registered, ok, skip, refused, failed, narrow, pending, plan}.
    `lines` are the changes made (or planned: 'base\ttarget'), then any 'NARROW ...' / 'PENDING ...'
    / 'SHORT ...' / 'INERT ...' notes."""
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

    flat = reg.get("layout") == "flat"
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
            try:
                have = registered_toml(cfg, flat=flat)
            except TomlUnsupported as e:
                return "refused", [f"{cfg}: this config cannot be verified ({e}); nothing registered, "
                                   f"nothing certified -- fix the file, or, on a host without tomllib, "
                                   f"run with Python >= 3.11 or register by hand"]
    else:
        have = {}

    own = registered_targets(cfg, reader, flat) if os.path.exists(cfg) else set()
    want, narrow, pending, planned = _decide(groups, have, dry, plan, own)
    notes = [f"NARROW {n}" for n in narrow] + [f"PENDING {p}" for p in pending]
    if plan:
        return "plan", [f"{b}\t{t}" for b, t in planned] + notes
    # The registered timeout is the bound the gate decides inside (stage C): read it.
    short, inert = timeout_findings(
        groups, registered_timeouts(cfg, reader, flat) if os.path.exists(cfg) else None)

    def done(verdict: str, changes: list[str]) -> tuple[str, list[str]]:
        # What this script registers points INTO `dest`, and install-members.sh refuses a
        # registration whose directory is absent ("registered at … but … does not exist") —
        # correctly, for a hand edit to a path nobody made. For a registration THIS script
        # wrote, the directory is ours to make: registering without it turned every deploy on
        # a host whose harness had never been hand-wired (HUB, 2026-09-28: ~/.codex present,
        # ~/.codex/hooks never created) into a FATAL that stopped the whole members' install.
        # Made on the `ok` arm too, so a host already left in that state repairs itself.
        if not dry and verdict in ("ok", "registered") and not os.path.isdir(dest):
            os.makedirs(dest, exist_ok=True)
            log(f"  made  {member}: {dest} — the directory its registration points into")
        return verdict, changes

    changes: list[str] = []
    if reader == "json-hook-commands":
        hooks = data.setdefault("hooks", {})
        for event, g, h in want:
            hooks.setdefault(event, []).append({**{k: v for k, v in g.items() if k != "hooks"}, "hooks": [h]})
            changes.append(f"{event}/{target_basename(h['command'])}")
        if raise_timeouts and short:
            changes += raise_json_timeouts(data, short)
            short = []
        if changes and not dry:
            new = json.dumps(data, indent=2) + "\n"
            json.loads(new)
            if raw:
                _backup(cfg)
            _write_atomic(cfg, new)
    else:
        new = raw
        for event, g, h in want:
            new += toml_block_flat(member, event, h, g) if flat else toml_block(member, event, g, h)
            changes.append(f"{event}/{target_basename(h['command'])}")
        new, ensured = toml_ensure(new, reg.get("ensure") or [])
        changes += [f"ensure {e}" for e in ensured]
        if raise_timeouts and short:
            new, raised = raise_toml_timeouts(new, short, flat)
            changes += raised
            short = []
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

    notes += [f"SHORT {e}/{b} is registered with timeout {t!r}, below the template's {w!r}: the "
              f"gate decides inside the registered value, so a cold member connect (4.6-5.1 s) "
              f"becomes a denial -- re-run with --raise-timeouts" for e, b, t, w in short]
    notes += [f"INERT {e}/{b} command carries {', '.join(s)}, which no gate reads since one-gate "
              f"stage C (the deadline is the registration's); remove it from the registered "
              f"command" for e, b, s in inert]
    lines = ([f"would add {c}" for c in changes] if dry else changes) + notes
    # #1142 re-review P2: a run that registered some hooks and left others PENDING returned
    # "registered" and exited 0. Narrow and pending are unfinished work: they outrank a partial
    # registration (the additions are still in `lines` and still reported).
    if narrow:
        return "narrow", lines
    if pending:
        return "pending", lines
    if changes:
        return done("registered", lines)
    return done("ok", lines)


def main(argv: list[str]) -> int:
    plugins = os.path.join(REPO_ROOT, "plugins")
    home = os.path.expanduser("~")
    global FORCE_LINE_SCAN
    only = None
    plan = False
    raise_timeouts = "--raise-timeouts" in argv
    argv = [a for a in argv if a != "--raise-timeouts"]
    if "--toml-line-scan" in argv:
        FORCE_LINE_SCAN = True
        argv = [a for a in argv if a != "--toml-line-scan"]
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
        verdict, lines = register_member(member, spec, template, home, dry, plan=plan,
                                         raise_timeouts=raise_timeouts)
        if plan:
            # machine-readable, for install-members.sh: member<TAB>basename<TAB>absolute target
            for ln in lines:
                if "\t" in ln and not ln.startswith(("NARROW", "PENDING")):
                    print(f"{member}\t{ln}", flush=True)
            continue
        kinds = ("NARROW ", "PENDING ", "SHORT ", "INERT ")
        adds = [ln for ln in lines if not ln.startswith(kinds)]
        notes = [ln for ln in lines if ln.startswith(kinds)]
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
            if any(n.startswith("SHORT ") for n in notes):
                rc = rc or 10
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
