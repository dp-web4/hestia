#!/usr/bin/env python3
"""Launch-identity census: what each launcher on this box DECLARES, versus what the chain
RECORDS it as. Read-only. (#984, and #244 from the other side.)

WHY. A governed act is attributed to (plugin_id, role_lct, session). All three come from the
LAUNCHER — the hook line in a harness config, a fire script, a systemd unit — and none is
established by the daemon. So an actor is whatever its launcher said, and a launcher that
says nothing gets `role:constellation:member` by default, silently. #244 measured the mirror
image (identity absent, role present). This census puts both sides of every actor on one
line so a launcher that forgets is VISIBLE rather than defaulting.

WHAT IT READS (declared side, all on THIS box, resolved not assumed):
  * systemd user units `hestia*.service`: HESTIA_PLUGIN_ID / HESTIA_MESH_PLUGIN / HESTIA_ROLE,
    and whether ExecStart is a launcher at all;
  * the mesh directory the watcher units actually execute (taken from their ExecStart, which
    is how "merged is not deployed" (#606) becomes visible here rather than assumed away);
    each fire-*.sh's declared role and whether it chooses a per-wake --session-id;
  * each harness's interactive hook lines, at the config path plugins/*/expects.json declares.
WHAT IT READS (observed side): the witness chain, over a window — per actor, rows, roles
  (read from `role_lct` OR `requested_by.role_lct`, because the chain carries it in both
  places depending on event type), rows carrying NO role, and host sessions.

VERDICTS, per actor (several can apply):
  NOBODY            a launcher that never connects as a member (the deploy timer)
  SILENT-DEFAULT    a launcher declares no HESTIA_ROLE and rows carry role:constellation:member
                    (named per launcher: an actor's fire script can declare a role while its
                    interactive hook line declares none, and that line is the one defaulting)
  NO-ROWS-IN-WINDOW a declared, connecting actor with nothing on the chain in the window
  DECLARED!=SEEN    a declared role that never appears on the chain, from a launcher that
                    DID run in the window — so the declaration was carried and lost
  UNTESTED-LAUNCHER a fire script declares a role and ran ZERO times in the window: its
                    role's absence from the chain is evidence of nothing (GPT's hold on
                    #1000 — absence in an actor aggregate is not a launcher's failure)
  PROVISIONAL-ROLE  a fire script resolves its role from the member's identity file and that
                    file is ABSENT, so every act it starts rides the launcher's declared-by-
                    fire fallback rather than a hydrated identity (#1010)
  DECLARED-NOT-OBSERVED
                    a fire script declares a role, the role is absent, and whether the
                    script ran cannot be established (no fire logs readable)
  NO-WAKE-SESSION   a fire script with no --session-id: its wakes are indistinguishable
                    from each other and from the interactive seat (#974's root)
  ROLE-OFF-RECORD   event kinds this actor emits that carry no role field at all

    HESTIA_HOME=... python3 tools/launch_identity_census.py [--since ISO] [--json]
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# The value may be bare, quoted, JSON-escaped (`\\"` inside settings.json), or the
# `${HESTIA_ROLE:-default}` spelling the hook lines use; all four are declarations.
ROLE_RE = re.compile(r"HESTIA_ROLE=\\?\"?\$?\{?(?:HESTIA_ROLE:-)?(role:[a-z:_-]+)")
PLUGIN_RE = re.compile(r"HESTIA_(?:MESH_)?PLUGIN(?:_ID)?=([a-z0-9-]+)")
#: A launcher that resolves its role from the member's identity file names that file. When it
#: does, any literal role in the same script is a FALLBACK, not the declaration (#1010).
IDENTITY_PATH_RE = re.compile(r'_ident="([^"]*identity\.json)"')
DEFAULT_ROLE = "role:constellation:member"


# ---- declared side ----------------------------------------------------------------------


def parse_unit(text: str) -> dict:
    """Identity-bearing facts from one systemd unit's text."""
    env = " ".join(re.findall(r"^Environment=(.*)$", text, flags=re.M))
    exec_start = next(iter(re.findall(r"^ExecStart=(.*)$", text, flags=re.M)), "")
    return {
        "plugin": next(iter(PLUGIN_RE.findall(env + " " + exec_start)), None),
        "role": next(iter(ROLE_RE.findall(env + " " + exec_start)), None),
        "exec": exec_start.strip(),
    }


def parse_launch_line(text: str) -> dict:
    """Identity-bearing facts from one hook command line or a whole fire-script.

    Comment lines are dropped first, and EVERY role the text can set is collected. The first
    version took the first match over the raw text and read `fire-claude.sh`'s role off a
    comment that quotes the interactive hook line — so a script whose only real export is
    `mesh-worker` was recorded as declaring `interactive-dev`. A reader that takes the first
    thing it sees is the #975 defect again, in a shell script.
    """
    code = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
    facts = {
        "plugin": next(iter(PLUGIN_RE.findall(code)), None),
        "roles": set(ROLE_RE.findall(code)),
        "session_id_flag": "--session-id" in code,
        "identity_path": None,
        "fallback_roles": set(),
    }
    # A LITERAL ROLE INSIDE A FALLBACK IS NOT A DECLARATION (2026-09-10, #1010).
    #
    # The fire scripts resolve the role from the member's OWN identity file and fall back to
    # a literal only when that read fails:
    #
    #     if [[ -z "${HESTIA_ROLE:-}" ]]; then
    #       _ident="~/.<seat>/hestia-instance/identity.json"
    #       ...                                            # <- the normal path
    #       [[ -n "$_role" ]] && export HESTIA_ROLE="$_role"
    #       if [[ -z "${HESTIA_ROLE:-}" ]]; then
    #         export HESTIA_ROLE="role:constellation:mesh-worker"   # <- only if unreadable
    #
    # Collecting every literal made the FALLBACK the launcher's declared role, and
    # `DECLARED!=SEEN` followed mechanically for two seats whose identity files resolve
    # something else entirely — a verdict about a declaration that was never made on the path
    # that runs. Same class as #975/#976: reading what the text says instead of what the code
    # would execute, this time in the instrument built to catch exactly that.
    #
    # So: when a script resolves from an identity file, its declared role is whatever that
    # file says AT RUNTIME. The census reads the same file (see `fire_scripts`), which turns
    # an unknowable into a measured fact, and the literal is recorded as the fallback it is.
    m = IDENTITY_PATH_RE.search(code)
    if m:
        facts["identity_path"] = m.group(1)
        facts["fallback_roles"] = set(facts["roles"])
        facts["roles"] = set()
    return facts


def units(config_home: Path) -> dict[str, dict]:
    out = {}
    for p in sorted(glob.glob(str(config_home / "systemd" / "user" / "hestia*.service"))):
        try:
            out[Path(p).name] = parse_unit(Path(p).read_text())
        except OSError:
            continue
    return out


def mesh_dir_from_units(unit_facts: dict[str, dict]) -> Path | None:
    """The directory the watchers EXECUTE from — measured off ExecStart, never assumed."""
    for name, f in unit_facts.items():
        if name.startswith("hestia-watch-") and f["exec"]:
            first = f["exec"].split()[0]
            return Path(first).parent
    return None


def identity_role(path: str | None) -> tuple[str | None, bool]:
    """`(role, readable)` from a member's identity file — the same read the fire script does.

    The launcher resolves its role at runtime from this file, so the census reads it too
    rather than reporting the declaration as unknowable. `readable` distinguishes "the file
    is there and names no usable role" from "the file is absent", because only the second
    means the script's literal fallback is what actually runs.
    """
    if not path:
        return None, False
    resolved = Path(os.path.expanduser(path.replace("~", "~/", 1) if path.startswith("~") and not path.startswith("~/") else path))
    try:
        data = json.loads(resolved.read_text())
    except (OSError, json.JSONDecodeError):
        return None, False
    role = data.get("role")
    # Same acceptance test the fire scripts apply: a string beginning `role:`, else omitted.
    return (role if isinstance(role, str) and role.startswith("role:") else None), True


def fire_scripts(mesh_dir: Path | None) -> dict[str, dict]:
    if not mesh_dir:
        return {}
    out = {}
    for p in sorted(mesh_dir.glob("fire-*.sh")):
        try:
            text = p.read_text()
        except OSError:
            continue
        facts = parse_launch_line(text)
        # RESOLVE THE ROLE THE FIRE WILL ACTUALLY EXPORT, from the same file the fire reads.
        # `identity_role` is the declaration on the normal path; `identity_readable` says
        # whether the fallback is what runs instead. Neither is a guess: both come from the
        # box the census is measuring.
        facts["identity_role"], facts["identity_readable"] = identity_role(facts.get("identity_path"))
        if facts["identity_role"]:
            facts["roles"] = {facts["identity_role"]}
        elif not facts["identity_readable"]:
            # The file the launcher names is not there, so the fallback IS the live path.
            facts["roles"] = set(facts.get("fallback_roles") or set())
        # WHERE THIS LAUNCHER RECORDS ITS OWN RUNS. Every fire script writes one log per
        # invocation, `$LOG_DIR/<prefix>-$STAMP.log`, and names both in its own text. Read
        # from the script rather than assumed, so a box that relocates the state dir is
        # measured, not guessed; None when the script does not say.
        facts["log_dir"] = None
        facts["log_prefix"] = None
        m = re.search(r'^LOG_DIR="([^"]+)"', text, re.M)
        if m:
            facts["log_dir"] = os.path.expandvars(m.group(1).replace("$HOME", os.path.expanduser("~")))
        m = re.search(r'\$LOG_DIR/([a-z0-9_-]+)-\$STAMP\.log', text)
        if m:
            facts["log_prefix"] = m.group(1)
        out[p.name] = facts
    return out


def fire_exercise(fires: dict[str, dict], since: str) -> dict[str, int | None]:
    """How many times each fire script RAN in the window, from its own per-invocation logs.

    `since` is the census window's start — chain time, i.e. UTC unless it carries an offset.
    A log is in the window when the stamp in its name (`<prefix>-YYYYmmdd-HHMMSS.log`) is at
    or after it. None when the script names no log location or the directory cannot be
    listed — the verdict layer then says "not observed", never "never ran". This is the fact
    GPT's hold on #1000 asked for: a launcher's declared role can only be called LOST if the
    launcher was exercised; a declaration nothing ran is untested, not refuted.

    TWO CLOCK DOMAINS, made one explicitly (GPT's second hold). The fire scripts stamp the
    filename with plain `date +%Y%m%d-%H%M%S` — the HOST'S LOCAL clock — while the window is
    chain time. Comparing the digits lexically counted a fire on the wrong side of the window
    for the hours between local midnight and UTC midnight, and here that is not cosmetic:
    zero reads UNTESTED-LAUNCHER, one reads DECLARED!=SEEN. So both sides become epochs: the
    stamp through the host's own timezone database (`time.mktime`, DST and all — never a
    hardcoded offset), the window through `since_epoch`. If the fire scripts ever stamp in
    UTC, `stamp_epoch` is the one place to follow them.
    """
    since_ts = since_epoch(since)
    out: dict[str, int | None] = {}
    for name, f in fires.items():
        d, prefix = f.get("log_dir"), f.get("log_prefix")
        if not d or not prefix:
            out[name] = None
            continue
        try:
            names = os.listdir(d)
        except OSError:
            out[name] = None
            continue
        pat = re.compile(rf"^{re.escape(prefix)}-(\d{{8}}-\d{{6}})\.log$")
        n = 0
        for fn in names:
            m = pat.match(fn)
            if m and stamp_epoch(m.group(1)) >= since_ts:
                n += 1
        out[name] = n
    return out


def since_epoch(since: str) -> float:
    """The window start as an epoch. ISO-8601; a trailing `Z` or an explicit offset is
    honoured, and a naive stamp is UTC because that is what the chain writes."""
    import datetime as _dt
    text = since.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = _dt.datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.timezone.utc)
    return parsed.timestamp()


def stamp_epoch(stamp: str) -> float:
    """A fire-log stamp (`YYYYmmdd-HHMMSS`, the host's LOCAL clock as `date` wrote it) as an
    epoch, through the host's timezone rules — the same rules that produced it."""
    import time as _time
    return _time.mktime(_time.strptime(stamp, "%Y%m%d-%H%M%S"))


def harness_hook_lines(repo: Path, home: Path) -> dict[str, list[dict]]:
    """Per declared seat: the interactive hook lines at the config path expects.json names."""
    out: dict[str, list[dict]] = {}
    for spec_path in sorted(repo.glob("plugins/*/expects.json")):
        try:
            spec = json.loads(spec_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        install = spec.get("install") or {}
        member = install.get("member") or spec_path.parent.name
        reg = (install.get("registration") or {}).get("path") or []
        if not reg:
            continue
        cfg = home.joinpath(*reg)
        if not cfg.exists():
            out[member] = [{"config": str(cfg), "present": False}]
            continue
        try:
            text = cfg.read_text(errors="replace")
        except OSError:
            continue
        lines = [ln for ln in text.splitlines() if "hestia" in ln.lower() and "HESTIA_" in ln]
        out[member] = [{"config": str(cfg), "present": True, **parse_launch_line(ln)} for ln in lines] or [
            {"config": str(cfg), "present": True, "plugin": None, "role": None, "session_id_flag": False}
        ]
    return out


# ---- observed side ----------------------------------------------------------------------


def chain_epoch(timestamp: str) -> float | None:
    """A chain row's RFC3339 timestamp (`2026-09-08T19:33:15.288358535+00:00`) as an epoch,
    or None when it will not parse. The fraction is cut to microseconds because the daemon
    writes nine digits and `fromisoformat` accepts six."""
    import datetime as _dt
    text = timestamp.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    text = re.sub(r"(\.\d{6})\d+", r"\1", text)
    try:
        parsed = _dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.timezone.utc)
    return parsed.timestamp()


def observe(since: str, max_entries: int = 20000, entries=None) -> dict[str, dict]:
    """Per actor: rows, roles, role-less kinds and host sessions, over the window.

    ONE CLOCK DOMAIN GOVERNS BOTH INPUTS of the verdict join (GPT's third hold on #1000).
    The window start is the same instant `fire_exercise` uses (`since_epoch`), and each
    chain timestamp is parsed to an instant before the comparison — never the raw string
    cut to 19 characters, which put an explicit-offset `--since` on a different boundary
    for the two sides of `DECLARED!=SEEN`. `entries` lets a test feed rows without a daemon.
    """
    sys.path.insert(0, str(REPO / "tools"))
    import chain_walk as cw  # noqa: E402

    since_ts = since_epoch(since)
    acts: dict[str, dict] = collections.defaultdict(lambda: {
        "rows": 0, "roles": collections.Counter(), "no_role_kinds": collections.Counter(),
        "kinds": collections.Counter(), "host_sessions": set(),
    })
    rows = entries if entries is not None else cw.ChainWalker().walk(max_entries=max_entries)
    for e in rows:
        ts = chain_epoch(e.get("timestamp") or "")
        if ts is None:
            continue
        if ts < since_ts:
            break
        p = cw.payload(e)
        rb = p.get("requested_by") or {}
        pid = p.get("plugin_id") or rb.get("plugin_id")
        if not pid:
            continue
        a = acts[pid]
        a["rows"] += 1
        a["kinds"][e.get("eventType")] += 1
        role = p.get("role_lct") or rb.get("role_lct")
        if role:
            a["roles"][role] += 1
        else:
            a["no_role_kinds"][e.get("eventType")] += 1
        if p.get("host_session_id"):
            a["host_sessions"].add(p["host_session_id"])
    return acts


# ---- verdicts ---------------------------------------------------------------------------


def verdicts(declared: dict[str, dict], observed: dict[str, dict]) -> dict[str, list[str]]:
    """`declared` is actor -> {"roles": set, "connects": bool|None, "wake_session": bool|None,
    "undeclared_sources": [launcher names that set no role]}."""
    out: dict[str, list[str]] = collections.defaultdict(list)
    for actor, d in declared.items():
        obs = observed.get(actor)
        if d.get("connects") is False:
            out[actor].append("NOBODY")
            continue
        if obs is None or obs["rows"] == 0:
            out[actor].append("NO-ROWS-IN-WINDOW")
        if d.get("undeclared_sources") and obs and obs["roles"].get(DEFAULT_ROLE):
            out[actor].append("SILENT-DEFAULT:" + ",".join(d["undeclared_sources"]))
        for r in sorted(d["roles"]):
            if obs and obs["roles"].get(r):
                continue
            # The role is absent. WHICH launcher declared it decides what that absence
            # means. A hook line's role rides every interactive act, so the actor having
            # rows at all is the launcher being exercised. A fire script's role rides only
            # its wakes, and those are counted from its own logs: zero runs makes the
            # absence evidence of nothing; unknown runs makes it unobserved; runs with the
            # role still absent is the one reading that says "carried and lost".
            fire_only = r in d.get("fire_roles", set()) and r not in d.get("hook_roles", set())
            if not fire_only:
                out[actor].append(f"DECLARED!=SEEN:{r}")
                continue
            ran = d.get("exercised")
            if ran is None:
                out[actor].append(f"DECLARED-NOT-OBSERVED:{r}")
            elif ran == 0:
                out[actor].append(f"UNTESTED-LAUNCHER:{r}")
            else:
                out[actor].append(f"DECLARED!=SEEN:{r}")
        # A launcher running on its PROVISIONAL fallback is its own state, and a loud one: the
        # member's identity file is absent, so every act it starts rides a declared-by-fire
        # role rather than a hydrated one (#1010).
        if d.get("role_source") == "provisional_fallback":
            out[actor].append(f"PROVISIONAL-ROLE:identity absent at {d.get('identity_path')}")
        if d.get("wake_session") is False:
            out[actor].append("NO-WAKE-SESSION")
        if obs and obs["no_role_kinds"]:
            out[actor].append("ROLE-OFF-RECORD:" + ",".join(sorted(obs["no_role_kinds"])))
    for actor in observed:
        if actor not in declared:
            out[actor].append("UNDECLARED-LAUNCHER")
    return dict(out)


def fold_declared(unit_facts, fires, hooks) -> dict[str, dict]:
    """Collapse the three declared sources into one record per actor."""
    d: dict[str, dict] = collections.defaultdict(lambda: {"roles": set(), "connects": None,
                                                           "wake_session": None, "sources": [],
                                                           "undeclared_sources": [],
                                                           # which LAUNCHER KIND declared each
                                                           # role, and how often the fire
                                                           # scripts ran (None = unknown)
                                                           "fire_roles": set(), "hook_roles": set(),
                                                           "fire_scripts": [], "exercised": None,
                                                           "role_source": None, "identity_path": None})
    for name, f in unit_facts.items():
        if name.startswith("hestia-watch-") and f["plugin"]:
            d[f["plugin"]]["sources"].append(name)
            if f["role"]:
                d[f["plugin"]]["roles"].add(f["role"])
            else:
                d[f["plugin"]]["undeclared_sources"].append(name)
        elif name == "hestia-deploy.service":
            d["hestia-deploy"]["sources"].append(name)
            d["hestia-deploy"]["connects"] = False
        elif name == "hestia-agent-inventory.service":
            d["agent-inventory"]["sources"].append(name)
            if f["role"]:
                d["agent-inventory"]["roles"].add(f["role"])
            else:
                d["agent-inventory"]["undeclared_sources"].append(name)
    for name, f in fires.items():
        actor = {"fire-claude.sh": "claude-code", "fire-codex.sh": "codex",
                 "fire-kimi.sh": "kimi-code"}.get(name, f["plugin"] or name)
        d[actor]["sources"].append(name)
        d[actor]["fire_scripts"].append(name)
        if f["roles"]:
            d[actor]["roles"] |= f["roles"]
            d[actor]["fire_roles"] |= f["roles"]
        else:
            d[actor]["undeclared_sources"].append(name)
        d[actor]["wake_session"] = bool(f["session_id_flag"])
        # How the fire got its role, carried so a verdict can say whether a role came from
        # the member's own identity file or from the launcher's provisional fallback (#1010).
        if f.get("identity_path"):
            d[actor]["role_source"] = (
                "identity_file" if f.get("identity_role")
                else "provisional_fallback" if not f.get("identity_readable")
                else "identity_file_names_no_role")
            d[actor]["identity_path"] = f["identity_path"]
    for member, lines in hooks.items():
        for ln in lines:
            if not ln.get("present"):
                continue
            src = Path(ln["config"]).name
            d[member]["sources"].append(src)
            if ln.get("roles"):
                d[member]["roles"] |= ln["roles"]
                d[member]["hook_roles"] |= ln["roles"]
            elif src not in d[member]["undeclared_sources"]:
                # THIS is the silent default's launcher: a hook line that sets no role, so
                # every act it starts lands as role:constellation:member. Kept per SOURCE,
                # because the same actor's fire script may declare a role and hide it.
                d[member]["undeclared_sources"].append(src)
    return dict(d)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--since", default="2026-09-06T00:00:00")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if not os.environ.get("HESTIA_HOME"):
        print("HESTIA_HOME is not set; the bootstrap locator is supplied, not guessed")
        return 2
    home = Path(os.path.expanduser("~"))
    config_home = Path(os.environ.get("XDG_CONFIG_HOME") or (home / ".config"))

    unit_facts = units(config_home)
    mesh = mesh_dir_from_units(unit_facts)
    fires = fire_scripts(mesh)
    hooks = harness_hook_lines(REPO, home)
    declared = fold_declared(unit_facts, fires, hooks)
    # LAUNCHER EXERCISE, from each fire script's own per-run logs, folded per actor: None
    # if any of the actor's fire scripts cannot be counted, else the sum.
    exercise = fire_exercise(fires, args.since)
    for actor, d in declared.items():
        counts = [exercise.get(s) for s in d.get("fire_scripts", [])]
        if counts:
            d["exercised"] = None if any(c is None for c in counts) else sum(counts)
    observed = observe(args.since)
    verd = verdicts(declared, observed)

    if args.json:
        print(json.dumps({
            "mesh_dir": str(mesh) if mesh else None,
            "declared": {k: {**v, "roles": sorted(v["roles"]), "fire_roles": sorted(v["fire_roles"]),
                             "hook_roles": sorted(v["hook_roles"])} for k, v in declared.items()},
            "fire_exercise": exercise,
            "observed": {k: {"rows": v["rows"], "roles": dict(v["roles"]),
                             "no_role_kinds": dict(v["no_role_kinds"]),
                             "host_sessions": len(v["host_sessions"])} for k, v in observed.items()},
            "verdicts": verd,
        }, indent=2))
        return 0

    print(f"launch-identity census on {home.name}; chain window since {args.since}")
    print(f"mesh launchers execute from: {mesh or '(no watcher unit found)'}")
    print(f"\n{'actor':16} {'declared roles':34} {'wake sid':8} {'fires':>5} {'rows':>5} {'observed roles':40} verdicts")
    for actor in sorted(set(declared) | set(observed)):
        d = declared.get(actor, {"roles": set(), "wake_session": None, "exercised": None, "fire_scripts": []})
        o = observed.get(actor)
        dr = ",".join(sorted(r.split(":")[-1] for r in d["roles"])) or "-"
        ws = {True: "yes", False: "NO", None: "-"}[d.get("wake_session")]
        fires_col = "-" if not d.get("fire_scripts") else ("?" if d.get("exercised") is None else str(d["exercised"]))
        orr = ",".join(f"{r.split(':')[-1]}={n}" for r, n in o["roles"].most_common()) if o else "-"
        rows = o["rows"] if o else 0
        print(f"{actor:16} {dr:34} {ws:8} {fires_col:>5} {rows:>5} {orr[:40]:40} {' '.join(verd.get(actor, [])) or 'ok'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
