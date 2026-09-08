#!/usr/bin/env python3
"""Arms for the launch-identity census, on fixtures: parsers and verdicts, no box, no chain."""
from __future__ import annotations

import importlib.util
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("census", HERE / "launch_identity_census.py")
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)

FAILURES = []


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + ("" if ok else f"  <- {detail}"))
    if not ok:
        FAILURES.append(name)


def main() -> int:
    print("A. parsers read what a launcher declares")
    u = c.parse_unit("[Service]\nEnvironment=HESTIA_HOME=%h/.hestia\n"
                     "Environment=HESTIA_MESH_PLUGIN=codex HESTIA_MESH_HOST_AGENT=codex-watch\n"
                     "ExecStart=/x/plugins/member-mesh/hestia-watch-member.sh codex codex-watch /x\n")
    check("A1 unit plugin", u["plugin"] == "codex", str(u))
    check("A1 unit declares no role -> None (never a default)", u["role"] is None, str(u))
    check("A1 exec captured", u["exec"].startswith("/x/plugins/member-mesh/"), str(u))
    h = c.parse_launch_line('HESTIA_HOME="${HESTIA_HOME:-$HOME/.hestia}" '
                            'HESTIA_ROLE="${HESTIA_ROLE:-role:constellation:interactive-dev}" python3 x.py')
    check("A2 hook line role through the ${VAR:-default} spelling",
          h["roles"] == {"role:constellation:interactive-dev"}, str(h))
    f0 = c.parse_launch_line('# HESTIA_ROLE="${HESTIA_ROLE:-role:constellation:interactive-dev}" on the hook line\n'
                             'export HESTIA_ROLE="role:constellation:mesh-worker"\n')
    check("A2 a role quoted in a COMMENT is not a declaration (fire-claude.sh's shape)",
          f0["roles"] == {"role:constellation:mesh-worker"}, str(f0))
    j = c.parse_launch_line('"command": "HESTIA_HOME=\\"${HESTIA_HOME:-$HOME/.hestia}\\" '
                            'HESTIA_ROLE=\\"${HESTIA_ROLE:-role:constellation:interactive-dev}\\" python3 x.py"')
    check("A2b the JSON-escaped spelling in settings.json is a declaration too (it was read as none)",
          j["roles"] == {"role:constellation:interactive-dev"}, str(j))
    f = c.parse_launch_line('export HESTIA_ROLE="role:constellation:mesh-worker"\n'
                            'claude -p --session-id "$WAKE_SID" "$PROMPT"')
    check("A3 fire script role + per-wake session flag",
          f["roles"] == {"role:constellation:mesh-worker"} and f["session_id_flag"], str(f))
    check("A3 a fire script without --session-id says so",
          c.parse_launch_line('export HESTIA_ROLE="role:constellation:mesh-worker"\ncodex exec')["session_id_flag"] is False)

    print("B. verdicts name each failure class, from declared + observed")
    obs = {
        "codex": {"rows": 320, "roles": Counter({c.DEFAULT_ROLE: 320}), "no_role_kinds": Counter(),
                  "host_sessions": {"h1"}},
        "claude-code": {"rows": 10, "roles": Counter({"role:constellation:interactive-dev": 8}),
                        "no_role_kinds": Counter({"gate_self_read": 2}), "host_sessions": {"h2"}},
        "agent-inventory": {"rows": 5, "roles": Counter({c.DEFAULT_ROLE: 5}), "no_role_kinds": Counter(),
                            "host_sessions": set()},
        "stranger": {"rows": 1, "roles": Counter(), "no_role_kinds": Counter({"x": 1}), "host_sessions": set()},
    }
    dec = {
        "codex": {"roles": {"role:constellation:mesh-worker"}, "connects": None, "wake_session": False,
                  "undeclared_sources": ["config.toml"]},
        "claude-code": {"roles": {"role:constellation:interactive-dev"}, "connects": None, "wake_session": True,
                        "undeclared_sources": []},
        "agent-inventory": {"roles": set(), "connects": None, "wake_session": None,
                            "undeclared_sources": ["hestia-agent-inventory.service"]},
        "hestia-deploy": {"roles": set(), "connects": False, "wake_session": None, "undeclared_sources": []},
        "gemini": {"roles": set(), "connects": None, "wake_session": None, "undeclared_sources": ["settings.json"]},
    }
    v = c.verdicts(dec, obs)
    check("B1 a declared launcher that never connects is NOBODY", v["hestia-deploy"] == ["NOBODY"], str(v))
    check("B2 no declared role + default-role rows is SILENT-DEFAULT, naming the launcher",
          "SILENT-DEFAULT:hestia-agent-inventory.service" in v["agent-inventory"], str(v))
    check("B2 codex: the fire script's role does NOT hide the interactive line's silence",
          "SILENT-DEFAULT:config.toml" in v["codex"], str(v))
    check("B2 a declared actor with no rows is NO-ROWS-IN-WINDOW, not ok",
          v["gemini"] == ["NO-ROWS-IN-WINDOW"], str(v))
    check("B3 a declared role that never appears is DECLARED!=SEEN",
          any(x.startswith("DECLARED!=SEEN:role:constellation:mesh-worker") for x in v["codex"]), str(v))
    check("B3 and codex's fire script without --session-id is NO-WAKE-SESSION",
          "NO-WAKE-SESSION" in v["codex"], str(v))
    check("B4 event kinds carrying no role are named, not folded into a default",
          any(x.startswith("ROLE-OFF-RECORD:gate_self_read") for x in v["claude-code"]), str(v))
    check("B5 a healthy declared+seen actor gets only the off-record note, nothing else",
          [x for x in v["claude-code"] if not x.startswith("ROLE-OFF-RECORD")] == [], str(v))
    check("B6 an actor on the chain with no launcher is UNDECLARED-LAUNCHER",
          v["stranger"] == ["UNDECLARED-LAUNCHER"], str(v))

    print("C. the declared fold keeps a launcher that says nothing as saying nothing")
    d = c.fold_declared(
        {"hestia-watch-codex.service": {"plugin": "codex", "role": None, "exec": "/m/hestia-watch-member.sh"},
         "hestia-deploy.service": {"plugin": None, "role": None, "exec": "/x/hestia-deploy"}},
        {"fire-codex.sh": {"plugin": None, "roles": {"role:constellation:mesh-worker"}, "session_id_flag": False}},
        {"codex": [{"config": "/h/.codex/config.toml", "present": True, "plugin": "codex", "roles": set(),
                    "session_id_flag": False}]},
    )
    check("C1 codex's only declared role comes from the fire script; the interactive line adds none",
          d["codex"]["roles"] == {"role:constellation:mesh-worker"}, str(d["codex"]))
    check("C2 the deploy unit is folded as a launcher that does not connect",
          d["hestia-deploy"]["connects"] is False, str(d.get("hestia-deploy")))
    check("C3 three sources are all recorded for codex",
          len(d["codex"]["sources"]) == 3, str(d["codex"]["sources"]))
    check("C4 the two role-less sources are named as such; the fire script is not",
          set(d["codex"]["undeclared_sources"]) == {"hestia-watch-codex.service", "config.toml"},
          str(d["codex"]["undeclared_sources"]))

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
