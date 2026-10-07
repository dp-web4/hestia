#!/usr/bin/env python3
"""Hermetic pins for tools/upgrade_path_test.py's plumbing (no daemon, no git history).

The harness itself needs a daemon built from the candidate and full history, so it runs in its
own workflow. What can go wrong in it WITHOUT a daemon is the reading: how it classifies a
deploy cycle from the log, which registered line it treats as a member's gate, which declared
probes it turns into its allow and deny acts, and what it counts as "the second cycle changed
nothing". A misreading there is a verdict about the wrong thing, so each is pinned here against
the real log lines and the real declarations.

Run: python3 tools/upgrade_path_plumbing_test.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
spec = importlib.util.spec_from_file_location("upgrade_path_test", HERE / "upgrade_path_test.py")
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)

FAILS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  -- {detail}"))
    if not cond:
        FAILS.append(name)


# ---- describe strings ------------------------------------------------------------------------
check("describe_hash_len reads an 8-char abbreviation", h.describe_hash_len("v0.0.4-968-ga7e33bc4") == 8)
check("describe_hash_len reads a 7-char abbreviation", h.describe_hash_len("v0.0.4-965-g588684d") == 7)
check("describe_hash_len survives -dirty", h.describe_hash_len("v0.0.4-965-g588684d-dirty") == 7)
check("describe_hash_len reads a bare --always sha", h.describe_hash_len("a7e33bc4") == 8)
check("describe_hash_len refuses a tag-only describe", h.describe_hash_len("v0.0.4") is None)
check("describe_of_version is hestia-deploy's describe_of",
      h.describe_of_version("hestia 0.0.4 (v0.0.4-968-ga7e33bc4)") == "v0.0.4-968-ga7e33bc4")

# ---- classifying a cycle from the lines it wrote (real lines from the 2026-10-06 runs) ---------
HALF = """2026-10-06T04:05:12Z target=v0.0.4-968-ga7e33bc4 (a7e33bc4, web4 1, atlas unavailable(clone failed)) running=v0.0.4-968-ga7e33bc4 ondisk=v0.0.4-968-ga7e33bc4 bin=x
2026-10-06T04:05:12Z CURRENT v0.0.4-968-ga7e33bc4 but manifest says 'v0.0.4-965-g588684d'; re-running the members' install
2026-10-06T04:05:14Z REFUSED members' install: FAILED(registered candidate gate did not retain the recovery probes; rc=4) — the daemon deploy stands
2026-10-06T04:05:14Z CURRENT v0.0.4-968-ga7e33bc4 manifest-repair hooks=refused(FAILED(registered candidate gate did not retain the recovery probes; rc=4)) inventory=skipped(HESTIA_DEPLOY_INVENTORY=0)
2026-10-06T04:05:14Z HALF-DEPLOYED v0.0.4-968-ga7e33bc4: binary current, manifest still 'v0.0.4-965-g588684d'
"""
GOOD = """2026-10-06T04:06:12Z CURRENT v0.0.4-965-g588684d6 but manifest says 'v0.0.4-964-gc61176a4'; re-running the members' install
2026-10-06T04:06:14Z CURRENT v0.0.4-965-g588684d6 manifest-repair hooks=ok inventory=skipped(HESTIA_DEPLOY_INVENTORY=0)
"""
NOOP = "2026-10-06T04:06:20Z CURRENT v0.0.4-965-g588684d6 inventory=skipped(HESTIA_DEPLOY_INVENTORY=0)\n"
FULL = ("2026-10-06T04:06:20Z DEPLOYED v1 -> v2 (hestia abc, web4 def, atlas none) hooks=ok "
        "inventory=ok in 300s\n")
check("a half deploy classifies HALF-DEPLOYED", h.classify_cycle(HALF, 1)["outcome"] == "HALF-DEPLOYED")
check("a half deploy names its bad lines", len(h.classify_cycle(HALF, 1)["bad_lines"]) == 2)
check("a manifest repair with hooks=ok classifies DEPLOYED", h.classify_cycle(GOOD, 0)["outcome"] == "DEPLOYED")
check("a binary deploy with hooks=ok classifies DEPLOYED", h.classify_cycle(FULL, 0)["outcome"] == "DEPLOYED")
check("an idle cycle classifies CURRENT", h.classify_cycle(NOOP, 0)["outcome"] == "CURRENT")
check("rc=0 with a REFUSED line is never a pass",
      h.classify_cycle(HALF, 0)["outcome"] == "HALF-DEPLOYED")
check("a silent nonzero exit is FAILED, not CURRENT", h.classify_cycle("", 2)["outcome"] == "FAILED(rc=2)")

# ---- which registered line is the gate --------------------------------------------------------
cmds = ["/h/.codex/hooks/observe.sh",
        "HESTIA_WORKSPACE=/w python3 /h/.codex/hooks/pre_tool_use.py",
        "python3 /h/.codex/hooks/witness.py"]
check("gate_command picks the line invoking the entrypoint",
      h.gate_command(cmds, "hooks/pre_tool_use.py") == cmds[1])
check("command_target is the absolute path, not the assignment",
      h.command_target(cmds[1], "hooks/pre_tool_use.py") == "/h/.codex/hooks/pre_tool_use.py")
check("gate_command answers None when the gate is not registered",
      h.gate_command(cmds[::2], "hooks/pre_tool_use.py") is None)

# ---- the declared probes are what the harness drives -----------------------------------------
for expects in sorted((REPO / "plugins").glob("*/expects.json")):
    install = json.loads(expects.read_text()).get("install") or {}
    probe = install.get("gate_probe")
    if not isinstance(probe, dict):
        continue
    allow, deny = h.probe_events(probe)
    member = expects.parent.name
    check(f"{member}: gate_probe declares a {{scratch}} read (the allow act)", allow is not None)
    check(f"{member}: gate_probe declares a {{hold}} shell act (re-aimed as the deny act)", deny is not None)
    if deny is not None:
        aimed = h.render_event(deny, {"{scratch}": "/tmp/s", "{hold}": "/h/gate.py"})
        check(f"{member}: the deny act names the target", "/h/gate.py" in json.dumps(aimed))

check("every KNOWN_SELF_WRITE_HOLES member is a real plugin",
      all((REPO / "plugins" / m / "expects.json").is_file() for m in h.KNOWN_SELF_WRITE_HOLES))

# ---- what counts as a deny, and a deny for the law -------------------------------------------
check("payload deny (permissionDecision)", h.payload_denies('{"permissionDecision": "deny"}'))
check("payload deny (decision)", h.payload_denies('{"decision": "deny", "reason": "x"}'))
check("payload deny (hookSpecificOutput)",
      h.payload_denies('{"hookSpecificOutput": {"permissionDecision": "deny"}}'))
check("an allow payload is not a deny", not h.payload_denies('{"decision": "allow"}'))
check("non-JSON stdout is not a deny", not h.payload_denies("hello"))
check("gate-self deny is for the law",
      h.deny_is_for_the_law("hestia: deny [gate-self] — 'Bash' would WRITE to the governance surface: /x"))
check("gate.self_access deny is for the law",
      h.deny_is_for_the_law("hestia: deny [gate.self_access] — 'Shell' would WRITE the governance surface"))
check("config.unbacked deny is NOT for the law",
      not h.deny_is_for_the_law("hestia: deny [config.unbacked] - HESTIA_HOME is not set"))
check("a missing-engine deny is NOT for the law",
      not h.deny_is_for_the_law("hestia: deny [no-shared-authority] - the shared shell classifier"))

check("last_line prefers the deny [rule] line over the remedy text after it",
      h.last_line("hestia: deny [gate-self] x\nIf a gate change is needed, ESCALATE\n") == "hestia: deny [gate-self] x")
check("last_line falls back to the last line", h.last_line("a\nb\n") == "b")

# ---- the no-op snapshot -----------------------------------------------------------------------
with tempfile.TemporaryDirectory() as raw:
    root = Path(raw)
    (root / "d").mkdir()
    (root / "d" / "a").write_text("1")
    (root / "f").write_text("x")
    os.symlink("d", root / "link")
    roots = [root / "d", root / "f", root / "link", root / "absent"]
    before = h.snapshot(roots)
    check("snapshot is stable across identical reads", h.snapshot(roots) == before)
    (root / "d" / "a").write_text("2")
    (root / "d" / "b").write_text("new")
    os.remove(root / "link")
    os.symlink("f", root / "link")
    diff = h.snapshot_diff(before, h.snapshot(roots))
    check("snapshot_diff reports a changed file", any(d.startswith("changed:") and d.endswith("/d/a") for d in diff), str(diff))
    check("snapshot_diff reports an added file", any(d.startswith("added:") and d.endswith("/d/b") for d in diff), str(diff))
    check("snapshot_diff reports a re-pointed symlink", any(d.endswith("/link") for d in diff), str(diff))

# ---- the simulated machine's environment ------------------------------------------------------
with tempfile.TemporaryDirectory() as raw:
    m = h.Machine.__new__(h.Machine)
    m.root = Path(raw)
    m.home = Path(raw) / "home"
    m.hestia_home = m.home / ".hestia"
    m.workspace = m.home / "ai-workspace"
    m.endpoint = "http://127.0.0.1:1/mcp"
    m.unit = "sim.service"
    m.guard_dir = Path(raw) / "guard"
    m.guard_log = Path(raw) / "live-port-connects.log"
    saved = {k: os.environ.get(k) for k in ("HESTIA_HOME", "CLAUDECODE", "HESTIA_ROLE")}
    os.environ.update({"HESTIA_HOME": "/real/.hestia", "CLAUDECODE": "1", "HESTIA_ROLE": "r"})
    try:
        base = m.base_env()
        check("the caller's HESTIA_HOME does not leak into the machine", "HESTIA_HOME" not in base)
        check("a governed session's CLAUDECODE does not leak into the machine", "CLAUDECODE" not in base)
        check("HESTIA_ROLE does not leak into the machine", "HESTIA_ROLE" not in base)
        check("HOME is the fake one", base["HOME"] == str(m.home))
        check("every process is told the isolated endpoint", base["HESTIA_ENDPOINT"] == m.endpoint)
        check("every Python process carries the live-port guard",
              base["PYTHONPATH"] == str(m.guard_dir) and base["UPGRADE_PATH_GUARD_PORT"] == str(h.LIVE_PORT))
        dep = m.deploy_env()
        check("the deploy never restarts anything", dep["HESTIA_RESTART_CMD"] == "false")
        check("the deploy endpoint is never the live daemon's", ":7711" not in dep["HESTIA_ENDPOINT"])
        (m.home / ".claude").mkdir(parents=True)
        (m.home / ".claude" / "settings.json").write_text(json.dumps({"env": {"HESTIA_HOME": "/x"}}))
        check("Claude Code's settings env reaches its hooks",
              m.launcher_env("claude-code", "python3 /g.py", {"CLAUDECODE": "1"}).get("HESTIA_HOME") == "/x")
        check("another member does not inherit Claude Code's settings env",
              "HESTIA_HOME" not in m.launcher_env("codex", "python3 /g.py", {}))
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

check("free_port never answers the live daemon's port", h.free_port() != h.LIVE_PORT)

# ---- the live-port guard actually refuses, and says so -----------------------------------------
# Exercised on a FREE port nothing listens on, never on the live one: if the guard failed to
# load, the worst case is a natural "connection refused" from an empty port, which the checks
# below tell apart from the guard's refusal by its message and its log line.
import subprocess  # noqa: E402
with tempfile.TemporaryDirectory() as raw:
    guard = Path(raw) / "guard"
    guard.mkdir()
    (guard / "sitecustomize.py").write_text(h.GUARD_SOURCE)
    log = Path(raw) / "connects.log"
    port = h.free_port()
    probe = ("import socket, urllib.request\n"
             "for f in (lambda: socket.create_connection(('127.0.0.1', %d), timeout=2),\n"
             "          lambda: urllib.request.urlopen('http://127.0.0.1:%d/mcp', timeout=2)):\n"
             "    try:\n"
             "        f(); print('CONNECTED')\n"
             "    except Exception as e:\n"
             "        print('REFUSED', e)\n") % (port, port)
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PYTHONPATH": str(guard),
           "UPGRADE_PATH_GUARD_PORT": str(port), "UPGRADE_PATH_GUARD_LOG": str(log)}
    out = subprocess.run([sys.executable, "-c", probe], env=env, capture_output=True, text=True, timeout=30)
    check("the guard refuses a raw socket connect to the guarded port",
          out.stdout.count("upgrade-path guard") >= 1, out.stdout + out.stderr)
    check("the guard refuses an HTTP request to the guarded port (urllib)",
          out.stdout.count("upgrade-path guard") == 2, out.stdout + out.stderr)
    logged = log.read_text().splitlines() if log.exists() else []
    check("the guard logs every blocked attempt", len(logged) == 2, str(logged))
    env["UPGRADE_PATH_GUARD_PORT"] = str(h.free_port())
    log.unlink(missing_ok=True)
    out = subprocess.run([sys.executable, "-c", probe], env=env, capture_output=True, text=True, timeout=30)
    check("the guard leaves other ports alone", "upgrade-path guard" not in out.stdout and not log.exists(),
          out.stdout)

print()
if FAILS:
    print(f"{len(FAILS)} FAILURE(S): {FAILS}")
    sys.exit(1)
print("ALL CHECKS PASSED")
