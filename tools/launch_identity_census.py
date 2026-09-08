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
  DECLARED!=SEEN    a declared role that never appears on the chain
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
    return {
        "plugin": next(iter(PLUGIN_RE.findall(code)), None),
        "roles": set(ROLE_RE.findall(code)),
        "session_id_flag": "--session-id" in code,
    }


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


def fire_scripts(mesh_dir: Path | None) -> dict[str, dict]:
    if not mesh_dir:
        return {}
    out = {}
    for p in sorted(mesh_dir.glob("fire-*.sh")):
        try:
            out[p.name] = parse_launch_line(p.read_text())
        except OSError:
            continue
    return out


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


def observe(since: str, max_entries: int = 20000) -> dict[str, dict]:
    sys.path.insert(0, str(REPO / "tools"))
    import chain_walk as cw  # noqa: E402

    acts: dict[str, dict] = collections.defaultdict(lambda: {
        "rows": 0, "roles": collections.Counter(), "no_role_kinds": collections.Counter(),
        "kinds": collections.Counter(), "host_sessions": set(),
    })
    for e in cw.ChainWalker().walk(max_entries=max_entries):
        ts = (e.get("timestamp") or "")[:19]
        if ts < since:
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
        for r in d["roles"]:
            if not obs or not obs["roles"].get(r):
                out[actor].append(f"DECLARED!=SEEN:{r}")
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
                                                           "undeclared_sources": []})
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
        if f["roles"]:
            d[actor]["roles"] |= f["roles"]
        else:
            d[actor]["undeclared_sources"].append(name)
        d[actor]["wake_session"] = bool(f["session_id_flag"])
    for member, lines in hooks.items():
        for ln in lines:
            if not ln.get("present"):
                continue
            src = Path(ln["config"]).name
            d[member]["sources"].append(src)
            if ln.get("roles"):
                d[member]["roles"] |= ln["roles"]
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
    observed = observe(args.since)
    verd = verdicts(declared, observed)

    if args.json:
        print(json.dumps({
            "mesh_dir": str(mesh) if mesh else None,
            "declared": {k: {**v, "roles": sorted(v["roles"])} for k, v in declared.items()},
            "observed": {k: {"rows": v["rows"], "roles": dict(v["roles"]),
                             "no_role_kinds": dict(v["no_role_kinds"]),
                             "host_sessions": len(v["host_sessions"])} for k, v in observed.items()},
            "verdicts": verd,
        }, indent=2))
        return 0

    print(f"launch-identity census on {home.name}; chain window since {args.since}")
    print(f"mesh launchers execute from: {mesh or '(no watcher unit found)'}")
    print(f"\n{'actor':16} {'declared roles':34} {'wake sid':8} {'rows':>5} {'observed roles':40} verdicts")
    for actor in sorted(set(declared) | set(observed)):
        d = declared.get(actor, {"roles": set(), "wake_session": None})
        o = observed.get(actor)
        dr = ",".join(sorted(r.split(":")[-1] for r in d["roles"])) or "-"
        ws = {True: "yes", False: "NO", None: "-"}[d.get("wake_session")]
        orr = ",".join(f"{r.split(':')[-1]}={n}" for r, n in o["roles"].most_common()) if o else "-"
        rows = o["rows"] if o else 0
        print(f"{actor:16} {dr:34} {ws:8} {rows:>5} {orr[:40]:40} {' '.join(verd.get(actor, [])) or 'ok'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
