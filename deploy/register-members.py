#!/usr/bin/env python3
"""Reconcile every installed member's hestia hooks in that member's OWN harness config.

dp, 2026-09-27 (#1133): "the auto install process is supposed to take care of all this. isn't
there a script? editing files by hand is unacceptable friction for product we're trying to
release generally." There was no script. `deploy/install-members.sh` copies a hook file only
where the harness ALREADY registers it (it derives the target from the registration, never
from `expects.json`'s dest — #315), and the daemon's `install_claude_code` (core/src/
orchestrators.rs) merges exactly one hook for one member. Every other registration was a hand
edit, which is how codex ran 14 days with `witness.py` registered nowhere.

dp, 2026-10-06 (#1237, #1242): "i need the install from git to update properly and automatically
... looking towards release, these frictions are unacceptable to ordinary users." Until then this
script was ADD-ONLY: it never rewrote a command, so a template change (one-gate stage C's
HESTIA_HOME on the gate line) reached no host that was already registered, and the deploy
preflight refused every cycle on CBP, Legion and HUB. THE RULING: THE DEPLOYER OWNS HESTIA'S
REGISTRATION LINES. A line hestia installed is rewritten to the rendered template on every deploy;
a line it did not install is never touched; per-seat customisation goes through the vault's seat
projection, never through a hand edit to a hook line.

For each `plugins/<member>/expects.json` that declares `install.registration` and ships a
`hooks/hooks.json` template:

  1. Is the harness on this host?  Its config DIRECTORY exists (`~/.codex`, `~/.claude`, ...).
     Absent -> skip, said aloud. Never mint a registration for a harness that is not here (#1130).
  2. Render the template. `@HESTIA_PLUGIN_ROOT@/<member>/hooks/<file>` -> `<install.dest>/<file>`
     (the declared dest, which install-members.sh then finds REGISTERED and installs to).
     `@HESTIA_HOME@` -> the deploying environment's HESTIA_HOME, resolved to an ABSOLUTE path;
     unset REFUSES the member — the bootstrap locator has no default, by design (#944), and a
     gate line without it is the #1237 outage. `HESTIA_WORKSPACE=@HESTIA_WORKSPACE@` renders from
     the environment when set and is dropped when not (every hook has a default). Any other
     placeholder left unrendered REFUSES the member.
  3. OWNERSHIP. A registered hook is HESTIA'S when its target (the first absolute-path token of
     its command, the installer's rule) is exactly `<install.dest>/<basename>` for a basename the
     template registers on that event. Nothing else is owned: a hook whose target lies anywhere
     else — even one with the same basename — is FOREIGN and is never rewritten.
  4. RECONCILE, per templated hook (event, basename):
       - missing        -> added (JSON: a new group appended to `hooks.<Event>`; TOML: a new
                           `[[hooks.<Event>]]` + `[[hooks.<Event>.hooks]]` block, or a flat
                           `[[hooks]]` table, under a marker comment). Only once its target file
                           is on disk (else PENDING; install-members.sh plans, installs, then
                           registers, so nothing ever points at a missing file).
       - owned, differs -> rewritten IN PLACE to the rendered value: command, timeout, type,
                           statusMessage (nested/JSON) and the matcher. A matcher lives on a
                           group; when the group also holds hooks that are not this one, the hook
                           is moved to its own group instead, so no foreign hook's matcher moves.
       - owned, equal   -> nothing. A second run is a byte-identical no-op.
       - owned, twice   -> reduced to one owned entry (the one already on the template's matcher,
                           else the first); the others are removed.
       - foreign only   -> left exactly as it is, and reported: FOREIGN when its matcher covers
                           the template's, NARROW when it does not (exit 8), SHORT when its
                           timeout is below the template's (exit 10), INERT when it carries an
                           env override no gate reads since stage C.
     Each rewrite is reported old -> new.
  5. Validate before anything stands. JSON is written structurally and must reload. TOML is
     text-edited line by line (comments, alignment and every byte the reconcile does not own are
     kept), and the edit is PROVED before it is written: the edited text is re-parsed (tomllib on
     3.11+, else this script's strict line grammar) and must equal the reconcile applied to the
     parsed original — every foreign hook and every non-hooks key unchanged. A config this script
     cannot verify is REFUSED (exit 7), never guessed at. A file that fails to parse after the
     write is restored to what this run read (exit 6): a broken hook table disables every hook,
     gate included, which is worse than the gap.
  6. `install.registration.ensure` (optional): lines a harness needs for hooks to fire at all —
     codex's `[features] codex_hooks = true`. Added only when the key is absent.

THE TIMEOUT IS THE GATE'S BOUND (one-gate stage C): every seat's gate reads the timeout its harness
registered and decides inside it. The reconcile sets an owned hook's timeout to the template's
value in both directions; `--raise-timeouts` is kept as an accepted no-op alias.

    DRY_RUN=1        print what would change (each rewrite old -> new), write nothing
    --plan           machine-readable rows for install-members.sh: member<TAB>basename<TAB>target
                     for every templated hook whose file must be installed before it registers
    --plugins DIR    read plugin dirs from DIR; default: this checkout's plugins/
    --home DIR       treat DIR as the home directory; default: ~
    --member NAME    only this member (the plugin directory name)
    --raise-timeouts accepted, does nothing more (the reconcile covers it)

The renderer is shared: `deploy/from-main/gate-preflight.py` loads this file and probes each
candidate gate under `reconciled_commands()` — the registration this install WILL write — not the
one currently on disk (which the install is about to rewrite).

Exit: 0 clean; 6 a write failed validation and was restored; 7 refused (an unrendered placeholder,
HESTIA_HOME unset, or a config that cannot be verified; that member skipped, others proceed);
8 a FOREIGN registration is narrower than the template; 9 pending; 10 a FOREIGN registration's
timeout is below the template's.
"""
from __future__ import annotations

import copy
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
ENV = os.environ
#: The characters a rendered HESTIA_HOME may hold: it lands unquoted on a shell command line (and
#: install-members.sh writes the same value into a sourced ~/.profile, with the same allowlist).
_SAFE_PATH = re.compile(r"^/[A-Za-z0-9/._+@,:-]*$")
DELETE = object()         # a field the reconcile removes


class Unrendered(Exception):
    pass


class TomlUnsupported(Exception):
    """The reader met TOML it cannot verify. The registrar refuses to certify or edit anything."""


class Unlocatable(Exception):
    """A TOML edit could not be placed on, or proved against, the text. Nothing is written."""


def log(msg: str) -> None:
    print(msg, flush=True)


# ---------------------------------------------------------------- rendering --------------
def hestia_home_value(env=None) -> str:
    """The bootstrap locator as it will be written onto a hook line: the deploying environment's
    HESTIA_HOME, resolved to an absolute path. Unset refuses -- there is no default, by design
    (#944); a gate line rendered without it is exactly the #1237/#1242 outage."""
    env = ENV if env is None else env
    raw = env.get("HESTIA_HOME")
    if not raw:
        raise Unrendered("@HESTIA_HOME@: HESTIA_HOME is not set in the deploying environment; "
                         "the bootstrap locator has no default, by design (#944)")
    path = os.path.realpath(os.path.expanduser(raw))
    if not _SAFE_PATH.match(path):
        raise Unrendered(f"@HESTIA_HOME@: HESTIA_HOME resolves to {path!r}, which carries characters "
                         "this registrar will not write onto a shell command line (allowed: letters, "
                         "digits and / . _ + @ , : -)")
    return path


def render_command(cmd: str, member: str, dest: str, env=None) -> str:
    env = ENV if env is None else env
    cmd = cmd.replace(f"@HESTIA_PLUGIN_ROOT@/{member}/hooks/", dest.rstrip("/") + "/")
    if "@HESTIA_HOME@" in cmd:
        cmd = cmd.replace("@HESTIA_HOME@", hestia_home_value(env))
    ws = env.get("HESTIA_WORKSPACE")
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


def target_path(cmd: str) -> str | None:
    """The installer's rule, the whole path: the first token that is an absolute path."""
    for tok in cmd.split():
        if tok.startswith("/"):
            return tok
    return None


def rendered_groups(template: dict, member: str, dest: str, env=None) -> dict[str, list[dict]]:
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
                nh["command"] = render_command(h["command"], member, dest, env)
                ng["hooks"].append(nh)
            if ng["hooks"]:
                out.setdefault(event, []).append(ng)
    return out


class Desired:
    """One templated hook: `group` is the template group's keys (matcher, ...) without `hooks`;
    `hook` the rendered template hook."""
    def __init__(self, event: str, base: str, target, group: dict, hook: dict):
        self.event, self.base, self.target, self.group, self.hook = event, base, target, group, hook

    @property
    def matcher(self):
        return self.group.get("matcher")


def desired_hooks(groups: dict) -> list[Desired]:
    out, seen = [], set()
    for event, gs in groups.items():
        for g in gs:
            for h in g["hooks"]:
                b = target_basename(h["command"]) or ""
                if (event, b) in seen:
                    raise Unrendered(f"the template registers {event}/{b} twice; ownership is keyed by "
                                     "(event, basename), so this template cannot be reconciled")
                seen.add((event, b))
                out.append(Desired(event, b, target_path(h["command"]),
                                   {k: v for k, v in g.items() if k != "hooks"}, h))
    return out


# ---------------------------------------------------------------- reading ----------------
ALL_MATCHERS = (None, "", "*", ".*", ".+")
UNPARSED = object()   # a matcher the reader could not decode: covers NOTHING


def covers(have, want) -> bool:
    """Does an existing registration's matcher cover what the template's matcher asks for?
    A template matcher that matches every tool (absent, "", "*", ".*") is covered only by an
    existing matcher that also matches every tool; a specific one is covered by itself or by an
    all-tools matcher (#1142 review)."""
    if have is UNPARSED:
        return False                      # never certify a gate whose matcher could not be read
    if have in ALL_MATCHERS:
        return True
    if want in ALL_MATCHERS:
        return False
    return have == want


# The strict line grammar (the fallback reader, and the proof of an edit on a host without tomllib).
# Keys: bare or quoted. Headers: [a.b] / [[a.b]] with bare or quoted segments. Values: one basic or
# literal string, an integer, or a boolean. Each line may end in a comment.
_KEY = r"""(?:[A-Za-z0-9_-]+|"(?:[^"\\]|\\.)*"|'[^']*')"""
_KEYPATH = rf"{_KEY}(?:\s*\.\s*{_KEY})*"
_HEADER = re.compile(rf"""^\s*(\[\[|\[)\s*({_KEYPATH})\s*(\]\]|\])\s*(?:#.*)?$""")
_ASSIGN = re.compile(rf"""^\s*({_KEYPATH})\s*=\s*(.*?)\s*$""")
_VALUE = re.compile(r"""^(?:"((?:[^"\\]|\\.)*)"|'([^']*)'|([+-]?[0-9_]+)|(true|false))\s*(?:#.*)?$""")
_KEYSEG = re.compile(_KEY)
_TOML_ESCAPES = {"b": "\b", "t": "\t", "n": "\n", "f": "\f", "r": "\r", '"': '"', "\\": "\\"}


def _toml_basic(s: str) -> str:
    r"""Decode a TOML basic-string body EXACTLY (TOML 1.0: \b \t \n \f \r \" \\ \uXXXX \UXXXXXXXX), or raise
    TomlUnsupported. Never return the raw spelling (#1142's fourth review: `"\U0000006datcher"`)."""
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


def _scan_value(v: re.Match):
    if v.group(1) is not None:
        return _toml_basic(v.group(1))
    if v.group(2) is not None:
        return v.group(2)
    if v.group(3) is not None:
        return int(v.group(3).replace("_", ""))
    return v.group(4) == "true"


def _toml_scan_hooks(text: str, flat: bool = False):
    """The strict reader: the hooks structure in tomllib's shape -- nested: {event: [{matcher?,
    hooks: [{key: value}]}]}; flat: [{event, command, ...}] -- or TomlUnsupported on anything outside
    its grammar that could bear on hooks. It never guesses.

    #1142 third review: `"matcher" = "shell"` (a quoted key) was not recognised and read as all-tools.
    Quoted keys and header segments are read the TOML way; every other form is a refusal."""
    if '"' * 3 in text or "'" * 3 in text:
        raise TomlUnsupported("a multi-line string (it can hide table headers from a line scan)")
    nested: dict[str, list] = {}
    tables: list[dict] = []
    ctx = None                     # None | ("group", event) | ("entry", event) | ("flat",) | ("other",)
    cur: dict | None = None        # the table the keys land in
    for n, line in enumerate(text.splitlines(), 1):
        st = line.strip()
        if not st or st.startswith("#"):
            continue
        h = _HEADER.match(line)
        if h:
            segs = _segments(h.group(2))
            arr = h.group(1) == "[["
            if flat:
                if segs and segs[0] == "hooks":
                    if arr and segs == ["hooks"]:
                        ctx, cur = ("flat",), {}
                        tables.append(cur)
                        continue
                    raise TomlUnsupported(f"line {n}: hooks table form {st!r} in a flat layout")
                ctx, cur = ("other",), None
                continue
            if segs and segs[0] == "hooks" and not arr and len(segs) >= 2 and segs[1] == "state":
                ctx, cur = ("other",), None   # codex's per-hook approval state: defines no hooks
            elif segs and segs[0] == "hooks":
                if arr and len(segs) == 2:
                    ctx, cur = ("group", segs[1]), {}
                    nested.setdefault(segs[1], []).append(cur)
                elif (arr and len(segs) == 3 and segs[2] == "hooks" and ctx and ctx[0] in ("group", "entry")
                      and ctx[1] == segs[1]):
                    ctx = ("entry", segs[1])
                    cur = {}
                    nested[segs[1]][-1].setdefault("hooks", []).append(cur)
                else:
                    raise TomlUnsupported(f"line {n}: hooks table form {st!r}")
            else:
                ctx, cur = ("other",), None
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
        key, val = segs[0], _scan_value(v)
        if key in ("event", "command", "matcher") and not isinstance(val, str):
            raise TomlUnsupported(f"line {n}: non-string {key} {st!r}")
        if key in cur:
            raise TomlUnsupported(f"line {n}: {key} set twice in one table")
        cur[key] = val
    return tables if flat else nested


def toml_hooks(text: str, flat: bool = False):
    """The hooks structure of a TOML config: a structural parse (tomllib) when the host has one,
    otherwise the strict line grammar. Raises TomlUnsupported."""
    if not FORCE_LINE_SCAN:
        try:
            import tomllib  # type: ignore
        except ImportError:
            tomllib = None
        if tomllib is not None:
            try:
                data = tomllib.loads(text)
            except tomllib.TOMLDecodeError as e:
                raise TomlUnsupported(f"not valid TOML ({e})") from e
            hooks = data.get("hooks")
            if flat:
                return [t for t in hooks if isinstance(t, dict)] if isinstance(hooks, list) else []
            return hooks if isinstance(hooks, dict) else {}
    return _toml_scan_hooks(text, flat)


class Reg:
    """One registered hook. `gi`/`hi` index the nested/JSON layout; `ti` the flat one."""
    def __init__(self, event: str, matcher, hook: dict, base, target, gi: int = -1, hi: int = -1,
                 ti: int = -1):
        self.event, self.matcher, self.hook, self.base, self.target = event, matcher, hook, base, target
        self.gi, self.hi, self.ti = gi, hi, ti


def _matcher_of(holder: dict):
    m = holder.get("matcher")
    return m if (m is None or isinstance(m, str)) else UNPARSED


def index_hooks(hooks, flat: bool) -> list[Reg]:
    out: list[Reg] = []
    if flat:
        for ti, t in enumerate(hooks if isinstance(hooks, list) else []):
            if not isinstance(t, dict) or not isinstance(t.get("event"), str):
                continue
            cmd = t.get("command")
            cmd = cmd if isinstance(cmd, str) else ""
            out.append(Reg(t["event"], _matcher_of(t), t, target_basename(cmd), target_path(cmd), ti=ti))
        return out
    for event, gs in (hooks.items() if isinstance(hooks, dict) else []):
        if not isinstance(gs, list):
            continue
        for gi, g in enumerate(gs):
            if not isinstance(g, dict):
                continue
            for hi, h in enumerate(g.get("hooks") or []):
                cmd = h.get("command") if isinstance(h, dict) else None
                if not isinstance(cmd, str):
                    continue
                out.append(Reg(event, _matcher_of(g), h, target_basename(cmd), target_path(cmd), gi=gi, hi=hi))
    return out


def _have(regs: list[Reg]) -> dict[str, dict[str, list]]:
    out: dict[str, dict[str, list]] = {}
    for r in regs:
        if r.base:
            out.setdefault(r.event, {}).setdefault(r.base, []).append(r.matcher)
    return out


def registered_json(path: str) -> dict[str, dict[str, list]]:
    """{event: {target basename: [matcher of each group that registers it]}}."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return _have(index_hooks(data.get("hooks") or {}, False))


def registered_toml(path: str, flat: bool = False) -> dict[str, dict[str, list]]:
    """{event: {target basename: [matcher of each group that registers it]}} -- read structurally
    (tomllib) or by the strict grammar, which refuses rather than reading an unrecognised matcher
    as absent (absent is all-tools)."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        return _have(index_hooks(toml_hooks(fh.read(), flat), flat))


# ---------------------------------------------------------------- reconcile --------------
#: What the reconcile owns on a hook entry. A key outside these on an owned line is left alone.
NESTED_FIELDS = ("type", "command", "statusMessage", "timeout")
FLAT_FIELDS = ("command", "timeout", "matcher")
#: Env overrides on a registered gate command that no gate reads since one-gate stage C.
INERT_GATE_ENV = re.compile(r"\b(HESTIA_PRE_TOTAL_BUDGET_MS|HESTIA_PRE_REQUEST_TIMEOUT_S|"
                            r"HESTIA_[A-Z]+_GATE_MODE)=\S*")


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _flat_matcher(m):
    return None if m in ALL_MATCHERS else m


def _toml_hook(hook: dict) -> dict:
    """The rendered hook as a nested TOML entry holds it (exactly what toml_block writes)."""
    out = {"type": str(hook.get("type", "command")), "command": hook["command"]}
    if isinstance(hook.get("statusMessage"), str):
        out["statusMessage"] = hook["statusMessage"]
    if _is_num(hook.get("timeout")):
        out["timeout"] = int(hook["timeout"])
    return out


def _want_fields(d: Desired, layout: str) -> dict:
    """{field: value or None (absent)} the owned entry must carry."""
    if layout == "flat":
        t = d.hook.get("timeout")
        return {"command": d.hook["command"], "timeout": int(t) if _is_num(t) else None,
                "matcher": _flat_matcher(d.matcher)}
    h = _toml_hook(d.hook) if layout == "toml" else d.hook
    return {f: h.get(f) for f in NESTED_FIELDS}


def _show(v) -> str:
    return "(none)" if v is None else (repr(v) if isinstance(v, str) else str(v))


class Plan:
    def __init__(self):
        self.ops: list = []       # ("set", Reg, {f: v|DELETE}) | ("gmatch", ev, gi, v|DELETE) | ("drop", Reg) | ("add", Desired)
        self.changes: list = []   # (verb, text): verb in add/rewrite/remove
        self.notes: list = []     # "NARROW ..." / "PENDING ..." / ...
        self.planned: list = []   # (base, target) the installer must put on disk
        self.narrow = False
        self.pending = False


def plan_reconcile(desired: list[Desired], regs: list[Reg], hooks, layout: str, *,
                   installed, dry: bool, plan_mode: bool) -> Plan:
    """Decide every op. `layout` in json/toml/flat. `installed(target)` says whether a target file is
    on disk (preflight passes `lambda t: True`: it judges the registration after the install)."""
    P = Plan()
    flat = layout == "flat"
    norm = lambda p: os.path.normpath(p) if p else p  # noqa: E731
    dropped: set[int] = set()
    moved: set[int] = set()
    regroup: dict[tuple, list] = {}               # (event, gi) -> [(Reg, Desired)] needing a matcher
    sets: list[tuple] = []
    for d in desired:
        same = [r for r in regs if r.event == d.event and r.base == d.base and r.base]
        owned = [r for r in same if d.target and norm(r.target) == norm(d.target)]
        foreign = [r for r in same if r not in owned]
        key = f"{d.event}/{d.base}"
        if owned:
            want = _want_fields(d, layout)
            if flat:
                keep = next((r for r in owned if r.hook.get("matcher") == want["matcher"]), owned[0])
            else:
                keep = next((r for r in owned if r.matcher == d.matcher), owned[0])
            for r in owned:
                if r is not keep:
                    dropped.add(id(r))
                    P.ops.append(("drop", r))
                    P.changes.append(("remove", f"{key}: duplicate owned entry {_show(r.hook.get('command'))}"
                                                f" (kept one; {len(owned)} were registered)"))
            diff = {f: v for f, v in want.items() if keep.hook.get(f) != v}
            if diff:
                sets.append((keep, d, diff))
            if not flat and keep.matcher != d.matcher:
                regroup.setdefault((d.event, keep.gi), []).append((keep, d))
            if d.target and not installed(d.target):
                if plan_mode:
                    P.planned.append((d.base, d.target))
                elif not dry:
                    P.pending = True
                    P.notes.append(f"PENDING {key} is registered but {d.target} is not installed "
                                   f"(install-members.sh installs it)")
            continue
        if foreign:
            if any(covers(r.matcher if not flat else r.hook.get("matcher"), d.matcher) for r in foreign):
                for r in foreign:
                    P.notes.append(f"FOREIGN {key} is registered at {r.target}, not under the declared "
                                   f"dest ({os.path.dirname(d.target or '')}); not hestia's line, left as it is")
                    want = d.hook.get("timeout")
                    t = r.hook.get("timeout")
                    if _is_num(want) and not (_is_num(t) and t >= want):
                        P.notes.append(f"SHORT {key} is registered with timeout {t!r}, below the template's "
                                       f"{want!r}, on a line hestia does not own: the gate decides inside the "
                                       f"registered value -- raise it, or let the deploy own the line")
                    stray = sorted({m.group(0) for m in INERT_GATE_ENV.finditer(r.hook.get("command") or "")})
                    if stray:
                        P.notes.append(f"INERT {key} command carries {', '.join(stray)}, which no gate reads "
                                       f"since one-gate stage C; remove it from that (foreign) line")
                continue
            P.narrow = True
            ms = [(r.matcher if not flat else r.hook.get("matcher")) for r in foreign]
            P.notes.append(f"NARROW {key} is registered only for matcher "
                           f"{', '.join('<unreadable>' if m is UNPARSED else repr(m) for m in ms)}; "
                           f"the template wants {d.matcher!r} -- a line hestia does not own (target "
                           f"{foreign[0].target}): left as it is, not reported as registered")
            continue
        P.planned.append((d.base, d.target))
        if plan_mode:
            continue
        if not dry and (d.target is None or not installed(d.target)):
            P.pending = True
            P.notes.append(f"PENDING {key} -> {d.target} is not installed yet; not registered "
                           f"(install-members.sh installs it, then registers)")
            continue
        P.ops.append(("add", d))
        P.changes.append(("add", key))

    # Matchers live on groups (nested/JSON). Rewrite a group's matcher in place only when every
    # surviving hook in it is an owned hook wanting that same matcher; otherwise move each owned hook
    # out to its own group, so no foreign hook's matcher ever moves.
    for (event, gi), pairs in regroup.items():
        members = [r for r in regs if r.event == event and r.gi == gi and id(r) not in dropped]
        wants = {repr(d.matcher) for _r, d in pairs}
        if len(members) == len(pairs) and len(wants) == 1:
            m = pairs[0][1].matcher
            P.ops.append(("gmatch", event, gi, DELETE if m is None else m))
            for r, d in pairs:
                P.changes.append(("rewrite", f"{d.event}/{d.base}: matcher {_show(r.matcher if r.matcher is not UNPARSED else '<unreadable>')} -> {_show(m)}"))
        else:
            for r, d in pairs:
                moved.add(id(r))
                P.ops.append(("drop", r))
                P.ops.append(("add", d))
                P.changes.append(("rewrite", f"{d.event}/{d.base}: matcher {_show(r.matcher if r.matcher is not UNPARSED else '<unreadable>')} -> "
                                             f"{_show(d.matcher)} (moved to its own group: its group also holds "
                                             f"hooks that are not this one)"))
    for keep, d, diff in sets:
        if id(keep) in moved:
            old = {f: keep.hook.get(f) for f in diff}
            P.changes.append(("rewrite", f"{d.event}/{d.base}: " + "; ".join(
                f"{f} {_show(old[f])} -> {_show(v)}" for f, v in diff.items())))
            continue
        P.ops.append(("set", keep, {f: (DELETE if v is None else v) for f, v in diff.items()}))
        P.changes.append(("rewrite", f"{d.event}/{d.base}: " + "; ".join(
            f"{f} {_show(keep.hook.get(f))} -> {_show(v)}" for f, v in diff.items())))
    return P


def _new_group(d: Desired, layout: str) -> dict:
    if layout == "json":
        return {**d.group, "hooks": [dict(d.hook)]}
    g = {"matcher": d.matcher} if isinstance(d.matcher, str) else {}
    g["hooks"] = [_toml_hook(d.hook)]
    return g


def _new_flat(d: Desired) -> dict:
    t = {"event": d.event}
    m = _flat_matcher(d.matcher)
    if isinstance(m, str):
        t["matcher"] = m
    t["command"] = d.hook["command"]
    if _is_num(d.hook.get("timeout")):
        t["timeout"] = int(d.hook["timeout"])
    return t


def apply_structural(hooks, ops: list, layout: str):
    """The reconcile applied to the parsed hooks structure (a deep copy). This is the definition the
    TOML text edit is proved against, and the whole edit for JSON."""
    flat = layout == "flat"
    new = copy.deepcopy(hooks) if hooks is not None else ([] if flat else {})
    drops: set = set()
    adds = []
    for op in ops:
        if op[0] == "set":
            _k, r, fields = op
            tgt = new[r.ti] if flat else new[r.event][r.gi]["hooks"][r.hi]
            for f, v in fields.items():
                if v is DELETE:
                    tgt.pop(f, None)
                else:
                    tgt[f] = v
        elif op[0] == "gmatch":
            _k, event, gi, v = op
            if v is DELETE:
                new[event][gi].pop("matcher", None)
            else:
                new[event][gi]["matcher"] = v
        elif op[0] == "drop":
            r = op[1]
            drops.add(r.ti if flat else (r.event, r.gi, r.hi))
        elif op[0] == "add":
            adds.append(op[1])
    if flat:
        new = [t for i, t in enumerate(new) if i not in drops]
        new += [_new_flat(d) for d in adds]
        return new
    for event in list(new):
        gs = new[event]
        if not isinstance(gs, list):
            continue
        if not any(k[0] == event for k in drops):
            continue
        kept_groups = []
        for gi, g in enumerate(gs):
            hs = g.get("hooks")
            if isinstance(hs, list):
                nh = [h for hi, h in enumerate(hs) if (event, gi, hi) not in drops]
                if not nh and len(nh) != len(hs):
                    continue                      # every hook it held was dropped: the group goes too
                if len(nh) != len(hs):
                    g = dict(g, hooks=nh)
            kept_groups.append(g)
        if kept_groups:
            new[event] = kept_groups
        else:
            del new[event]
    for d in adds:
        new.setdefault(d.event, []).append(_new_group(d, layout))
    return new


# ---------------------------------------------------------------- TOML text edit ---------
class Block:
    """`start`: header line index (-1: the top-level block); `end`: one past its last content line
    (trailing blanks/comments excluded); `keys`: single-segment key -> line index."""
    def __init__(self, start: int, end: int, segs, arr: bool):
        self.start, self.end, self.segs, self.arr = start, end, segs, arr
        self.keys: dict = {}


_VALTOK = r"""(?:"(?:[^"\\]|\\.)*"|'[^']*'|[+-]?[0-9_]+|true|false)"""
_KEYLINE = re.compile(rf"""^(\s*{_KEY}\s*=\s*)({_VALTOK})(\s*(?:#.*)?)$""")


def _blocks(lines: list[str]) -> list[Block]:
    """Every table block of a TOML text, with the line of each single-segment key. Lenient about
    content outside hooks tables (multi-line strings and arrays are skipped); the edit made on these
    blocks is PROVED by re-parsing, so a misplaced header can only refuse, never land."""
    blocks = [Block(-1, 0, None, False)]
    in_ml: str | None = None
    depth = 0
    for i, line in enumerate(lines):
        if in_ml:
            if in_ml in line:
                in_ml = None
            blocks[-1].end = i + 1
            continue
        if depth > 0:
            depth += line.count("[") - line.count("]")
            blocks[-1].end = i + 1
            continue
        st = line.strip()
        if not st or st.startswith("#"):
            continue
        h = _HEADER.match(line)
        if h:
            try:
                segs = _segments(h.group(2))
            except TomlUnsupported:
                segs = ["<undecodable>"]
            blocks.append(Block(i, i + 1, segs, h.group(1) == "[["))
            continue
        blocks[-1].end = i + 1
        a = _ASSIGN.match(line)
        if not a:
            continue
        val = a.group(2)
        for q in ('"""', "'''"):
            if val.startswith(q) and val.count(q) == 1:
                in_ml = q
        if val.startswith("[") and not in_ml:
            depth = val.count("[") - val.count("]")
        try:
            ks = _segments(a.group(1))
        except TomlUnsupported:
            continue
        if len(ks) == 1 and ks[0] not in blocks[-1].keys:
            blocks[-1].keys[ks[0]] = i
    return blocks


def _toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    return _toml_str(str(v))


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
    if _is_num(t):
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
    if _is_num(t):
        lines.append(f"timeout = {int(t)}")
    return "\n".join(lines) + "\n"


def _locate(blocks: list[Block], hooks, flat: bool):
    """Map the parsed structure onto text blocks: flat -> [Block per table]; nested ->
    {event: [(group Block, [entry Block])]}. Raises Unlocatable when the text and the parse
    disagree on the shape (inline tables, headers the lenient scan misread, ...)."""
    if flat:
        tbls = [b for b in blocks if b.segs == ["hooks"] and b.arr]
        n = len(hooks) if isinstance(hooks, list) else 0
        if len(tbls) != n:
            raise Unlocatable(f"{len(tbls)} [[hooks]] headers in the text, {n} tables parsed")
        return tbls
    out: dict[str, list] = {}
    for b in blocks:
        if not (b.arr and b.segs and b.segs[0] == "hooks"):
            continue
        if len(b.segs) == 2:
            out.setdefault(b.segs[1], []).append((b, []))
        elif len(b.segs) == 3 and b.segs[2] == "hooks" and out.get(b.segs[1]):
            out[b.segs[1]][-1][1].append(b)
        else:
            raise Unlocatable(f"line {b.start + 1}: hooks header the edit cannot place")
    parsed = {e: gs for e, gs in (hooks.items() if isinstance(hooks, dict) else []) if isinstance(gs, list)}
    if set(parsed) != set(out):
        raise Unlocatable(f"events in the text {sorted(out)} differ from the parse {sorted(parsed)}")
    for e, gs in parsed.items():
        if len(gs) != len(out[e]) or any(len((g.get("hooks") or [])) != len(out[e][i][1])
                                         for i, g in enumerate(gs)):
            raise Unlocatable(f"hooks.{e}: the text's groups/entries do not match the parse")
    return out


def _set_fields(lines: list[str], b: Block, fields: dict, repl: dict, ins: dict) -> None:
    for f, v in fields.items():
        at = b.keys.get(f)
        if v is DELETE:
            if at is not None:
                repl[at] = None
            continue
        if at is not None:
            m = _KEYLINE.match(lines[at])
            if not m:
                raise Unlocatable(f"line {at + 1}: `{f} = ...` is not a value the edit can rewrite")
            repl[at] = m.group(1) + _toml_value(v) + m.group(3)
        else:
            after = max([b.start] + list(b.keys.values()))
            ins.setdefault(after, []).append(f"{f} = {_toml_value(v)}")


def _drop_range(lines: list[str], a: int, b: int, repl: dict) -> None:
    """Delete lines [a, b), the marker comment this script wrote directly above them (and the blank
    line it put before that), and -- when what precedes is already a blank line -- the blank lines
    that follow, so a removal leaves the file's spacing as it was."""
    for i in range(a, b):
        repl[i] = None
    first = a
    if a - 1 >= 0 and lines[a - 1].startswith(MARK):
        repl[a - 1] = None
        first = a - 1
        if a - 2 >= 0 and not lines[a - 2].strip():
            repl[a - 2] = None
            first = a - 2
    prev = first - 1
    while prev >= 0 and repl.get(prev, "") is None:
        prev -= 1
    if prev < 0 or not lines[prev].strip():
        j = b
        while j < len(lines) and not lines[j].strip() and j < len(lines) - 1:
            repl[j] = None
            j += 1


def apply_toml_text(text: str, hooks, ops: list, layout: str, member: str) -> str:
    """The reconcile as a line edit of `text`. Every byte no op names is kept."""
    flat = layout == "flat"
    lines = text.split("\n")
    edits = [op for op in ops if op[0] != "add"]
    repl: dict[int, str | None] = {}
    ins: dict[int, list[str]] = {}
    if edits:
        loc = _locate(_blocks(lines), hooks, flat)
        dropped: dict[tuple, set] = {}
        for op in edits:
            if op[0] == "set":
                r = op[1]
                b = loc[r.ti] if flat else loc[r.event][r.gi][1][r.hi]
                _set_fields(lines, b, op[2], repl, ins)
            elif op[0] == "gmatch":
                _k, event, gi, v = op
                _set_fields(lines, loc[event][gi][0], {"matcher": v}, repl, ins)
            elif op[0] == "drop":
                r = op[1]
                if flat:
                    b = loc[r.ti]
                    _drop_range(lines, b.start, b.end, repl)
                    continue
                gb, entries = loc[r.event][r.gi]
                dropped.setdefault((r.event, r.gi), set()).add(r.hi)
        for (event, gi), his in dropped.items():
            gb, entries = loc[event][gi]
            if len(his) == len(entries):          # the group goes with its last hook
                _drop_range(lines, gb.start, max(e.end for e in entries), repl)
            else:
                for hi in his:
                    _drop_range(lines, entries[hi].start, entries[hi].end, repl)
    out: list[str] = []
    for i, ln in enumerate(lines):
        if i in repl:
            if repl[i] is not None:
                out.append(repl[i])
        else:
            out.append(ln)
        out.extend(ins.get(i, []))
    new = "\n".join(out)
    for op in ops:
        if op[0] == "add":
            d = op[1]
            new += toml_block_flat(member, d.event, d.hook, d.group) if flat else \
                toml_block(member, d.event, d.group, d.hook)
    return new


def _norm_hooks(h, flat: bool):
    if flat:
        return h if isinstance(h, list) else []
    return {e: v for e, v in (h.items() if isinstance(h, dict) else []) if isinstance(v, list)}


def verify_toml_edit(old: str, new: str, expected_hooks, flat: bool) -> str | None:
    """PROVE the text edit: the edited text re-parses to exactly the reconcile's structure, and with
    a structural parser every non-hooks key (and the non-list part of `hooks`, codex's approval
    state) is unchanged. -> None when proved, else why not."""
    try:
        got = toml_hooks(new, flat)
    except TomlUnsupported as e:
        return f"the edited text does not parse ({e})"
    if _norm_hooks(got, flat) != _norm_hooks(expected_hooks, flat):
        return "the edited text does not parse to the reconciled hooks"
    if FORCE_LINE_SCAN:
        return None
    try:
        import tomllib  # type: ignore
    except ImportError:
        return None
    a, b = tomllib.loads(old), tomllib.loads(new)
    rest = lambda d: {k: v for k, v in d.items() if k != "hooks"}  # noqa: E731
    if rest(a) != rest(b):
        return "the edit changed a key outside the hooks tables"
    if not flat:
        side = lambda d: {k: v for k, v in (d.get("hooks") or {}).items() if not isinstance(v, list)}  # noqa: E731
        if side(a) != side(b):
            return "the edit changed a non-hook key under [hooks]"
    return None


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
        return None                       # no parser here: the strict grammar proved the edit
    try:
        tomllib.loads(text)
        return None
    except Exception as e:                # noqa: BLE001
        return f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------- writing ----------------
def _backup(path: str) -> None:
    bak = path + ".pre-register.bak"
    if not os.path.exists(bak):
        shutil.copy2(path, bak)


def _write_atomic(path: str, text: str) -> None:
    """Write `text` to `path` so a crash leaves the old file or the new one, never half of one.
    The temp file takes the original's mode: ~/.codex/config.toml is 0600."""
    d = os.path.dirname(path) or "."
    tmp = os.path.join(d, f".{os.path.basename(path)}.register-tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    if os.path.exists(path):
        shutil.copymode(path, tmp)
    os.replace(tmp, path)


# ---------------------------------------------------------------- one member -------------
class Loaded:
    def __init__(self, cfg, dest, reader, layout, raw, data, hooks, desired, reg):
        self.cfg, self.dest, self.reader, self.layout = cfg, dest, reader, layout   # layout: json|toml|flat
        self.raw, self.data, self.hooks, self.desired, self.reg = raw, data, hooks, desired, reg


def _load(member: str, spec: dict, template: dict, home: str, env=None):
    """-> Loaded, or (verdict, lines) when the member stops here."""
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
        groups = rendered_groups(template, member, dest, env)
        desired = desired_hooks(groups)
    except Unrendered as e:
        return "refused", [f"template cannot be rendered: {e}"]
    if not groups:
        return "skip", ["template registers no command hooks"]
    if reader not in ("json-hook-commands", "toml-hook-commands"):
        return "skip", [f"unknown registration reader {reader!r} — refusing to guess"]
    layout = "json" if reader == "json-hook-commands" else ("flat" if reg.get("layout") == "flat" else "toml")
    raw, data, hooks = "", None, None
    if os.path.exists(cfg):
        with open(cfg, encoding="utf-8", errors="replace") as fh:
            raw = fh.read()
    if layout == "json":
        try:
            data = json.loads(raw) if raw.strip() else {}
        except ValueError as e:
            return "failed", [f"{cfg} is not parseable JSON ({e}); refusing to guess"]
        if not isinstance(data, dict):
            return "failed", [f"{cfg} is not a JSON object"]
        hooks = data.get("hooks") if isinstance(data.get("hooks"), dict) else {}
    else:
        try:
            hooks = toml_hooks(raw, layout == "flat")
        except TomlUnsupported as e:
            return "refused", [f"{cfg}: this config cannot be verified ({e}); nothing registered, "
                               f"nothing certified -- fix the file, or, on a host without tomllib, "
                               f"run with Python >= 3.11 or register by hand"]
    return Loaded(cfg, dest, reader, layout, raw, data, hooks, desired, reg)


def reconciled_commands(member_dir: str, home: str, env=None) -> tuple[str, list[str], str]:
    """The hook commands this member's registration will carry AFTER the install (every planned file
    assumed installed, which is what install-members.sh does before it registers).
    -> (status, commands, reason); status in {ok, absent, refused}. Shared with the deploy
    preflight, so the probe judges the line that will be written, by the same renderer."""
    member = os.path.basename(os.path.normpath(member_dir))
    expects = os.path.join(member_dir, "expects.json")
    tpl = os.path.join(member_dir, "hooks", "hooks.json")
    try:
        with open(expects, encoding="utf-8") as fh:
            spec = json.load(fh).get("install") or {}
    except (OSError, ValueError) as e:
        return "refused", [], f"expects.json unreadable ({type(e).__name__})"
    if not os.path.isfile(tpl):
        return "absent", [], "ships no hooks/hooks.json template"
    try:
        with open(tpl, encoding="utf-8") as fh:
            template = json.load(fh)
    except (OSError, ValueError) as e:
        return "refused", [], f"hooks/hooks.json unreadable ({type(e).__name__})"
    got = _load(member, spec, template, home, env)
    if not isinstance(got, Loaded):
        verdict, lines = got
        return ("absent" if verdict == "skip" else "refused"), [], "; ".join(lines)
    regs = index_hooks(got.hooks, got.layout == "flat")
    P = plan_reconcile(got.desired, regs, got.hooks, got.layout, installed=lambda t: True,
                       dry=False, plan_mode=False)
    new = apply_structural(got.hooks, P.ops, got.layout)
    return "ok", [r.hook["command"] for r in index_hooks(new, got.layout == "flat")
                  if isinstance(r.hook.get("command"), str)], ""


def register_member(member: str, spec: dict, template: dict, home: str, dry: bool,
                    plan: bool = False, raise_timeouts: bool = False, env=None) -> tuple[str, list[str]]:
    """-> (verdict, lines). verdict in {registered, ok, skip, refused, failed, narrow, pending, plan}.
    `lines`: the changes made (or planned: 'base\\ttarget'), each 'add ...' / 'rewrite ...' /
    'remove ...' / 'ensure ...', then any NARROW / PENDING / SHORT / INERT / FOREIGN notes.
    `raise_timeouts` is accepted and ignored: the reconcile sets every owned timeout."""
    got = _load(member, spec, template, home, env)
    if not isinstance(got, Loaded):
        return got
    L = got
    exists = os.path.exists(L.cfg)
    flat = L.layout == "flat"
    regs = index_hooks(L.hooks, flat)
    P = plan_reconcile(L.desired, regs, L.hooks, L.layout, installed=os.path.isfile, dry=dry, plan_mode=plan)
    if plan:
        return "plan", [f"{b}\t{t}" for b, t in P.planned] + \
            [n for n in P.notes if n.startswith(("NARROW", "PENDING"))]

    def done(verdict: str, out: list[str]) -> tuple[str, list[str]]:
        # What this script registers points INTO `dest`; install-members.sh refuses a registration
        # whose directory is absent. For a registration THIS script wrote, the directory is ours to
        # make (HUB 2026-09-28, #1153). Made on the `ok` arm too, so a host left that way repairs.
        if not dry and verdict in ("ok", "registered") and not os.path.isdir(L.dest):
            os.makedirs(L.dest, exist_ok=True)
            log(f"  made  {member}: {L.dest} — the directory its registration points into")
        return verdict, out

    changes = [f"{verb} {text}" for verb, text in P.changes]
    if L.layout == "json":
        if P.ops:
            data = L.data
            data["hooks"] = apply_structural(L.hooks, P.ops, "json")
            new = json.dumps(data, indent=2) + "\n"
            back = json.loads(new)
            if back.get("hooks") != data["hooks"]:
                return "failed", [f"rendered {L.cfg} does not reload to the reconciled hooks; nothing written"] + P.notes
            if not dry:
                if L.raw:
                    _backup(L.cfg)
                _write_atomic(L.cfg, new)
    else:
        new = L.raw
        if P.ops:
            expected = apply_structural(L.hooks, P.ops, L.layout)
            try:
                new = apply_toml_text(L.raw, L.hooks, P.ops, L.layout, member)
            except Unlocatable as e:
                return "refused", [f"{L.cfg}: the reconcile cannot be placed on this file's text ({e}); "
                                   f"nothing written -- hestia's lines here need a hand repair once"] + P.notes
            why = verify_toml_edit(L.raw, new, expected, flat)
            if why:
                return "refused", [f"{L.cfg}: the edit could not be proved ({why}); nothing written"] + P.notes
        new, ensured = toml_ensure(new, L.reg.get("ensure") or [])
        changes += [f"ensure {e}" for e in ensured]
        if changes:
            err = validate_toml(new)
            if err:
                return "failed", [f"rendered {L.cfg} would not parse ({err}); nothing written"] + P.notes
            if not dry:
                if L.raw:
                    _backup(L.cfg)
                _write_atomic(L.cfg, new)
                with open(L.cfg, encoding="utf-8", errors="replace") as fh:
                    back = fh.read()
                err = validate_toml(back)
                if err:
                    # Restore what THIS run read, not `.pre-register.bak` (written once, on the first
                    # run ever). A file that did not exist goes back to not existing.
                    if exists:
                        _write_atomic(L.cfg, L.raw)
                    else:
                        os.remove(L.cfg)
                    return "failed", [f"{L.cfg} failed to parse after write ({err}); restored as it was"] + P.notes
    lines = changes + P.notes
    # #1142 re-review P2: narrow and pending are unfinished work: they outrank a partial registration.
    if P.narrow:
        return "narrow", lines
    if P.pending:
        return "pending", lines
    if changes:
        return done("registered", lines)
    return done("ok", lines)


# ---------------------------------------------------------------- main -------------------
_VERB = {"add": "REGISTERED", "rewrite": "REWROTE", "remove": "REMOVED", "ensure": "REGISTERED"}
_NOTES = ("NARROW ", "PENDING ", "SHORT ", "INERT ", "FOREIGN ")


def main(argv: list[str]) -> int:
    plugins = os.path.join(REPO_ROOT, "plugins")
    home = os.path.expanduser("~")
    global FORCE_LINE_SCAN
    only = None
    plan = False
    # --raise-timeouts: an accepted no-op alias since the reconcile (dp 2026-10-06) sets every owned
    # timeout to the template's value.
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
        verdict, lines = register_member(member, spec, template, home, dry, plan=plan)
        if plan:
            # machine-readable, for install-members.sh: member<TAB>basename<TAB>absolute target
            for ln in lines:
                if "\t" in ln and not ln.startswith(("NARROW", "PENDING")):
                    print(f"{member}\t{ln}", flush=True)
            continue
        changes = [ln for ln in lines if not ln.startswith(_NOTES)]
        notes = [ln for ln in lines if ln.startswith(_NOTES)]
        if verdict in ("registered", "narrow", "pending", "ok"):
            for c in changes:
                verb, text = c.split(" ", 1)
                if dry:
                    log(f"  would {member}: would {verb} {text}")
                else:
                    log(f"  {_VERB.get(verb, verb.upper())} {member}: {c if verb == 'ensure' else text}")
            for n in notes:
                log(f"  {n.split(' ', 1)[0]} {member}: {n.split(' ', 1)[1]}")
            if verdict == "ok":
                log(f"  ok    {member} — every templated hook is registered as the template renders it")
            # the exit code comes from the NOTES, not the headline verdict
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
