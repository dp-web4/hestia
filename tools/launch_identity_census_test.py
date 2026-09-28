#!/usr/bin/env python3
"""Arms for the launch-identity census, on fixtures: parsers and verdicts, no box, no chain."""
from __future__ import annotations

import importlib.util
import json
import os
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
        # codex's only role comes from its FIRE script (as the fold records in C1/C5); the
        # interactive line declares none. No fire-run count is given here: unknown.
        "codex": {"roles": {"role:constellation:mesh-worker"}, "connects": None, "wake_session": False,
                  "undeclared_sources": ["config.toml"],
                  "fire_roles": {"role:constellation:mesh-worker"}, "hook_roles": set()},
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
    # B3, GPT's hold on #1000: a fire script's role absent from the chain is only "lost"
    # if the fire script RAN. The fixture above declares mesh-worker from a fire script,
    # records interactive member rows, and says nothing about fire runs — so the verdict
    # must be the weaker one, never a diagnosis of role loss.
    check("B3 fire-declared role absent, fire runs unknown -> DECLARED-NOT-OBSERVED, not DECLARED!=SEEN",
          "DECLARED-NOT-OBSERVED:role:constellation:mesh-worker" in v["codex"]
          and not any(x.startswith("DECLARED!=SEEN") for x in v["codex"]), str(v))
    dec_zero = {**dec, "codex": {**dec["codex"], "exercised": 0}}
    vz = c.verdicts(dec_zero, obs)
    check("B3 the zero-fire fixture: interactive member rows + mesh-worker fire declaration + ZERO fires "
          "-> UNTESTED-LAUNCHER, never role-loss",
          "UNTESTED-LAUNCHER:role:constellation:mesh-worker" in vz["codex"]
          and not any(x.startswith("DECLARED!=SEEN") for x in vz["codex"]), str(vz))
    dec_ran = {**dec, "codex": {**dec["codex"], "exercised": 3}}
    vr = c.verdicts(dec_ran, obs)
    check("B3 three fires ran and the role is still absent -> DECLARED!=SEEN (carried and lost)",
          "DECLARED!=SEEN:role:constellation:mesh-worker" in vr["codex"], str(vr))
    # A HOOK-declared role needs no fire count: the actor's own rows are the launcher running.
    dec_hook = {**dec, "kimi-code": {"roles": {"role:constellation:mesh-worker"}, "connects": None,
                                     "wake_session": None, "undeclared_sources": [],
                                     "hook_roles": {"role:constellation:mesh-worker"}, "fire_roles": set()}}
    obs_hook = {**obs, "kimi-code": {"rows": 4, "roles": Counter({c.DEFAULT_ROLE: 4}),
                                     "no_role_kinds": Counter(), "host_sessions": set()}}
    vh = c.verdicts(dec_hook, obs_hook)
    check("B3 a hook-line role absent from an actor WITH rows is DECLARED!=SEEN without a fire count",
          "DECLARED!=SEEN:role:constellation:mesh-worker" in vh["kimi-code"], str(vh))
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
    check("C5 the fold records WHICH launcher kind declared the role, and which fire scripts exist",
          d["codex"]["fire_roles"] == {"role:constellation:mesh-worker"} and d["codex"]["hook_roles"] == set()
          and d["codex"]["fire_scripts"] == ["fire-codex.sh"] and d["codex"]["exercised"] is None,
          str(d["codex"]))

    print("F. a literal role inside a FALLBACK is not the launcher's declaration (#1010)")
    import tempfile as _tf
    with _tf.TemporaryDirectory() as tmp:
        home = Path(tmp)
        (home / ".seat" / "hestia-instance").mkdir(parents=True)
        ident = home / ".seat" / "hestia-instance" / "identity.json"
        # The real shape: resolve from the member's identity file, fall back to a literal.
        script = (
            'if [[ -z "${HESTIA_ROLE:-}" ]]; then\n'
            f'  _ident="{ident}"\n'
            '  [[ -n "$_role" ]] && export HESTIA_ROLE="$_role"\n'
            '  if [[ -z "${HESTIA_ROLE:-}" ]]; then\n'
            '    export HESTIA_ROLE="role:constellation:mesh-worker"\n'
            '  fi\n'
            'fi\n'
        )
        facts = c.parse_launch_line(script)
        check("F1 the literal is recorded as a FALLBACK, not as a declared role",
              facts["roles"] == set()
              and facts["fallback_roles"] == {"role:constellation:mesh-worker"}
              and facts["identity_path"] == str(ident), str(facts))

        mesh = home / "mesh"
        mesh.mkdir()
        (mesh / "fire-seat.sh").write_text(script)

        # (a) The identity file resolves a role: THAT is what the fire exports.
        ident.write_text(json.dumps({"role": "role:constellation:interactive-dev"}))
        fs = c.fire_scripts(mesh)["fire-seat.sh"]
        check("F2 an identity file that names a role IS the declaration, not the fallback",
              fs["roles"] == {"role:constellation:interactive-dev"}
              and fs["identity_role"] == "role:constellation:interactive-dev", str(fs))
        d = c.fold_declared({}, {"fire-seat.sh": fs}, {})
        obs = {"fire-seat.sh": {"rows": 5, "roles": Counter({"role:constellation:interactive-dev": 5}),
                                "no_role_kinds": Counter(), "host_sessions": set()}}
        v = c.verdicts(d, obs)
        check("F2 and the seat is NOT accused of losing the fallback role it never declared",
              not any(x.startswith("DECLARED!=SEEN") for x in v.get("fire-seat.sh", [])),
              str(v))
        check("F2 nor is it called provisional while its identity file is readable",
              not any(x.startswith("PROVISIONAL-ROLE") for x in v.get("fire-seat.sh", [])), str(v))

        # (b) The identity file is ABSENT: now the fallback really is what runs, and that is
        #     its own loud state rather than a silent declaration.
        ident.unlink()
        fs = c.fire_scripts(mesh)["fire-seat.sh"]
        check("F3 an absent identity file makes the fallback the live path",
              fs["roles"] == {"role:constellation:mesh-worker"}
              and fs["identity_role"] is None and fs["identity_readable"] is False, str(fs))
        d = c.fold_declared({}, {"fire-seat.sh": fs}, {})
        obs = {"fire-seat.sh": {"rows": 5, "roles": Counter({"role:constellation:mesh-worker": 5}),
                                "no_role_kinds": Counter(), "host_sessions": set()}}
        v = c.verdicts(d, obs)
        check("F3 and it is reported as PROVISIONAL-ROLE, naming the file that is missing",
              any(x.startswith("PROVISIONAL-ROLE") and "identity.json" in x
                  for x in v.get("fire-seat.sh", [])), str(v))

        # (c) A file that exists but names no usable role: readable, no declaration, and the
        #     census must not silently promote the fallback to a declaration either.
        ident.write_text(json.dumps({"role": "not-a-role-lct"}))
        fs = c.fire_scripts(mesh)["fire-seat.sh"]
        check("F4 a file naming no usable role leaves the declaration empty, not the fallback",
              fs["roles"] == set() and fs["identity_readable"] is True, str(fs))

    print("D. launcher exercise is counted from the fire script's OWN per-run logs")
    import tempfile
    import time
    # The fire scripts stamp in the HOST'S local clock; pin the host to UTC for the counting
    # arms so the fixture reads the same on every box, and to a DST zone for the straddle.
    saved_tz = os.environ.get("TZ")

    def set_tz(name):
        os.environ["TZ"] = name
        time.tzset()

    set_tz("UTC")
    with tempfile.TemporaryDirectory() as tmp:
        logs = Path(tmp) / "logs"
        logs.mkdir()
        for stamp in ("20260905-235959", "20260906-000000", "20260907-120000"):
            (logs / f"codex-{stamp}.log").write_text("x")
        (logs / "codex-20260907-130000.log.bak").write_text("x")     # not a run log
        (logs / "claude-20260907-140000.log").write_text("x")        # another launcher's run
        fires = {
            "fire-codex.sh": {"roles": set(), "session_id_flag": False, "plugin": None,
                              "log_dir": str(logs), "log_prefix": "codex"},
            "fire-kimi.sh": {"roles": set(), "session_id_flag": False, "plugin": None,
                             "log_dir": None, "log_prefix": None},
            "fire-claude.sh": {"roles": set(), "session_id_flag": False, "plugin": None,
                               "log_dir": str(Path(tmp) / "missing"), "log_prefix": "claude"},
        }
        ex = c.fire_exercise(fires, "2026-09-06T00:00:00")
        check("D1 runs at or after the window start are counted; earlier ones are not",
              ex["fire-codex.sh"] == 2, str(ex))
        check("D2 a script that names no log location is None (unknown), not zero",
              ex["fire-kimi.sh"] is None, str(ex))
        check("D3 an unlistable log dir is None (unknown), not zero",
              ex["fire-claude.sh"] is None, str(ex))
        # The location and prefix are read off the script text itself.
        mesh = Path(tmp) / "mesh"
        mesh.mkdir()
        (mesh / "fire-codex.sh").write_text('LOG_DIR="$HOME/.local/state/hestia-mesh/logs"; mkdir -p "$LOG_DIR"\n'
                                            'timeout 5 codex -p "$PROMPT" > "$LOG_DIR/codex-$STAMP.log" 2>&1\n')
        fs = c.fire_scripts(mesh)
        check("D4 fire_scripts reads the log dir and prefix off the script's own text",
              fs["fire-codex.sh"]["log_prefix"] == "codex"
              and fs["fire-codex.sh"]["log_dir"] == os.path.expanduser("~/.local/state/hestia-mesh/logs"),
              str(fs))

        # D5, GPT's clock-domain hold. The host is in a DST zone (UTC-7 in September); the
        # window is chain time. Two fires straddle the window start by the host offset: a
        # local stamp that READS after the window's date digits but is before it in real
        # time, and one that reads before local midnight but is inside. A lexical compare
        # of the digits gets both wrong; the epoch compare gets both right.
        set_tz("America/Los_Angeles")
        straddle = Path(tmp) / "straddle"
        straddle.mkdir()
        (straddle / "kimi-20260909-000100.log").write_text("x")   # 00:01 PDT = 07:01Z Sep 9
        (straddle / "kimi-20260908-225959.log").write_text("x")   # 22:59 PDT = 05:59Z Sep 9
        (straddle / "kimi-20260908-230001.log").write_text("x")   # 23:00 PDT = 06:00Z Sep 9
        fires_s = {"fire-kimi.sh": {"roles": set(), "session_id_flag": False, "plugin": None,
                                    "log_dir": str(straddle), "log_prefix": "kimi"}}
        ex = c.fire_exercise(fires_s, "2026-09-09T06:00:00Z")
        check("D5 window 06:00Z on a UTC-7 host: 23:00 local and later count, 22:59 local does not",
              ex["fire-kimi.sh"] == 2, str(ex))
        ex = c.fire_exercise(fires_s, "2026-09-09T00:00:00")
        check("D5 a naive window start is chain time (UTC), so a lexical read of the date digits "
              "would count 1 and the epoch compare counts all 3",
              ex["fire-kimi.sh"] == 3, str(ex))
        ex = c.fire_exercise(fires_s, "2026-09-08T23:00:00-07:00")
        check("D5 an explicit offset on the window is honoured (same instant as 06:00Z)",
              ex["fire-kimi.sh"] == 2, str(ex))
        check("D5 the conversion is the host's timezone rules, not a constant: stamp_epoch moves "
              "with TZ", c.stamp_epoch("20260909-000000") == c.since_epoch("2026-09-09T07:00:00Z"))
        set_tz("UTC")
        check("D5 under a UTC host the same stamp is the same instant as its digits",
              c.stamp_epoch("20260909-000000") == c.since_epoch("2026-09-09T00:00:00Z"))

        # E, GPT's third hold: the verdict is a JOIN, and one clock domain must govern both
        # inputs. The same explicit-offset window must include and exclude the same boundary
        # instants on the fire side and on the chain side. Chain rows are newest-first, as
        # the walker yields them, with the daemon's nine-digit fractions and +00:00.
        set_tz("America/Los_Angeles")
        window = "2026-09-08T23:00:00-07:00"                    # 06:00Z Sep 9, as an offset
        rows = [
            {"timestamp": "2026-09-09T06:00:00.000000001+00:00", "eventType": "outcome",
             "eventData": {"plugin_id": "kimi-code", "role_lct": "role:constellation:mesh-worker"}},
            {"timestamp": "2026-09-09T05:59:59.999999999+00:00", "eventType": "outcome",
             "eventData": {"plugin_id": "kimi-code", "role_lct": "role:constellation:interactive-dev"}},
            {"timestamp": "2026-09-08T23:00:00.000000000+00:00", "eventType": "outcome",
             "eventData": {"plugin_id": "kimi-code", "role_lct": "role:constellation:interactive-dev"}},
        ]
        obs_e = c.observe(window, entries=rows)
        check("E1 chain side: the row at 06:00Z is in, the rows before it are out — the walk stops "
              "at the instant, not at the string '2026-09-08T23:00:00'",
              obs_e["kimi-code"]["rows"] == 1 and obs_e["kimi-code"]["roles"].get("role:constellation:mesh-worker") == 1,
              str(dict(obs_e)))
        ex_e = c.fire_exercise(fires_s, window)
        check("E1 fire side, same window: 23:00 local (06:00:01Z) and later are in, 22:59 is out",
              ex_e["fire-kimi.sh"] == 2, str(ex_e))
        # The same rows under a Z window at the same instant: identical answer on both sides.
        obs_z = c.observe("2026-09-09T06:00:00Z", entries=rows)
        ex_z = c.fire_exercise(fires_s, "2026-09-09T06:00:00Z")
        check("E2 an offset window and its Z equivalent give the same answer on both sides",
              obs_z["kimi-code"]["rows"] == obs_e["kimi-code"]["rows"] and ex_z == ex_e,
              f"{dict(obs_z)} {ex_z}")
        # A trailing Z on the window used to make the 19-char lexical cut subtly wrong; the
        # boundary row itself is included under every spelling of the same instant.
        check("E3 the nine-digit daemon fraction parses, and a row exactly at the boundary is IN",
              c.chain_epoch("2026-09-09T06:00:00.000000000+00:00") == c.since_epoch("2026-09-09T06:00:00Z")
              and c.chain_epoch("garbage") is None)
    if saved_tz is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = saved_tz
    time.tzset()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
