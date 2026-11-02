#!/usr/bin/env python3
"""install-watchers.sh: which members it finds, what authority arms firing, what it retires (#1373, Nova's review of #1374).

Hermetic: HOME, HESTIA_HOME and the mesh state dir are a temp tree, the member table is replaced (fixtures named like a
real harness config are governance closure wherever they sit), and systemctl is a STUB that logs its calls and answers
is-active from a state file -- so no case can drive this machine's own user manager by a real unit name.

Run: python3 install_watchers_test.py   (no pytest; exit 1 on failure)
"""
from __future__ import annotations

import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
SCRIPT = HERE / "install-watchers.sh"
FAILS: list[str] = []
MARK = "installed by the hestia deploy, #1373"


def check(name, got, want):
    if got != want:
        FAILS.append(f"{name}: got {got!r}, want {want!r}")


def ok(name, cond, detail=""):
    if not cond:
        FAILS.append(f"{name}: {detail}")


STUB = """#!/usr/bin/env bash
# systemctl stand-in: log the call; is-active answers from $STUB_STATE/<unit> (absent = inactive)
echo "$*" >> "$STUB_LOG"
[ "$1" = "--user" ] && shift
case "$1" in
  show-environment) exit 0 ;;
  is-active)
    u="${@: -1}"
    if [ -f "$STUB_STATE/$u" ]; then [ "$2" = "--quiet" ] || echo active; exit 0; fi
    [ "$2" = "--quiet" ] || echo inactive; exit 3 ;;
  enable|daemon-reload) exit 0 ;;
  start|restart) touch "$STUB_STATE/${@: -1}"; exit 0 ;;
  disable) [ "$2" = "--now" ] && rm -f "$STUB_STATE/${@: -1}"; exit 0 ;;
esac
exit 0
"""


class Host:
    def __init__(self, root: Path):
        self.root = root
        self.home = root / "home"
        self.hh = root / "hh"
        self.ws = root / "ws"
        self.state = root / "stub-state"
        self.log = root / "stub.log"
        for d in (self.home / "cfg", self.hh, self.ws, self.state):
            d.mkdir(parents=True, exist_ok=True)
        os.chmod(self.hh, 0o700)
        self.stub = root / "systemctl"
        self.stub.write_text(STUB)
        self.stub.chmod(0o755)
        self.units = self.home / ".config" / "systemd" / "user"

    def config(self, name: str, text: str):
        (self.home / "cfg" / name).write_text(text)

    def run(self, *args: str, table: str, systemd=True) -> list[str]:
        env = {k: v for k, v in os.environ.items() if not k.startswith("HESTIA_")}
        env.update(HOME=str(self.home), HESTIA_HOME=str(self.hh), HESTIA_MESH_STATE=str(self.root / "mesh-state"),
                   HESTIA_MESH_WATCH_TABLE=table, HESTIA_WORKSPACE=str(self.ws), HESTIA_MESH_SETTLE="0",
                   STUB_LOG=str(self.log), STUB_STATE=str(self.state),
                   HESTIA_MESH_SYSTEMCTL=str(self.stub) if systemd else str(self.root / "no-such-systemctl"))
        r = subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, env=env, timeout=60)
        if r.returncode != 0:
            FAILS.append(f"installer rc={r.returncode}: {r.stderr[-400:]}")
        return r.stdout.splitlines()


def line(out, mid):
    """The member's STATE line: its last line (a `wrote <unit>` line may precede it)."""
    hits = [ln.strip() for ln in out if ln.strip().startswith(mid + ":")]
    return hits[-1] if hits else ""


JSON_PIN = '{"hooks":{"SessionStart":[{"hooks":[{"type":"command","command":"HESTIA_MESH_PLUGIN=%s /x/session-mesh-inbox.sh"}]}]}}'
TOML_PIN = '[[hooks]]\nevent = "SessionStart"\ncommand = "HESTIA_MESH_PLUGIN=%s /x/session-mesh-inbox.sh"\n'


def test_detection_and_check_writes_nothing():
    with tempfile.TemporaryDirectory() as d:
        h = Host(Path(d))
        h.config("claude.json", JSON_PIN % "claude-code")
        h.config("kimi.toml", TOML_PIN % "kimi-code")
        h.config("codex.toml", '# command = "HESTIA_MESH_PLUGIN=codex /x/session-mesh-inbox.sh"\n')
        h.config("other.toml", TOML_PIN % "claude-code")
        h.config("prefix.toml", TOML_PIN % "kimi-code-x")
        table = ("claude-code|cfg/claude.json|fire-claude.sh\nkimi-code|cfg/kimi.toml|fire-kimi.sh\n"
                 "codex|cfg/codex.toml|fire-codex.sh\nother|cfg/other.toml|fire-claude.sh\n"
                 "prefixed|cfg/prefix.toml|fire-kimi.sh\nmissing|cfg/none.toml|fire-claude.sh")
        out = h.run("--check", table=table)
        ok("claude-code JSON pin found", "WOULD-WRITE" in line(out, "claude-code"), out)
        ok("kimi-code TOML pin found", "WOULD-WRITE" in line(out, "kimi-code"), out)
        check("a commented line does not count", line(out, "codex"), "codex: absent")
        check("another member's pin does not count", line(out, "other"), "other: absent")
        # the table names this member "prefixed" but its config pins kimi-code-x: neither matches
        check("kimi-code-x is not kimi-code", line(out, "prefixed"), "prefixed: absent")
        check("missing config", line(out, "missing"), "missing: absent")
        ok("summary is the last line", out[-1].startswith("mesh: "), out[-1])
        ok("--check wrote no unit", not h.units.exists(), "unit dir created")
        ok("--check started nothing", not h.log.exists() or all(
            ln.split()[1] in ("show-environment", "is-active") for ln in h.log.read_text().splitlines()),
           h.log.read_text() if h.log.exists() else "")


def test_install_writes_a_print_only_unit_and_starts_it():
    with tempfile.TemporaryDirectory() as d:
        h = Host(Path(d))
        h.config("claude.json", JSON_PIN % "claude-code")
        out = h.run(table="claude-code|cfg/claude.json|fire-claude.sh")
        check("state", line(out, "claude-code"), "claude-code: active(print-only)")
        unit = h.units / "hestia-mesh-watch-claude-code.service"
        text = unit.read_text()
        ok("marker", MARK in text, text)
        ok("print-only: no fire script on ExecStart", "fire-claude.sh" not in text, text)
        ok("ExecStart runs the watcher from the checkout",
           f"ExecStart=/usr/bin/env bash {HERE}/hestia-watch-member.sh claude-code claude-code-watch\n" in text, text)
        ok("ordered after the daemon, never after default.target",
           "After=hestia.service" in text and "After=default.target" not in text and "WantedBy=default.target" in text, text)
        ok("start limit can trip", "StartLimitIntervalSec=120" in text and "RestartSec=5" in text, text)
        calls = h.log.read_text()
        ok("enabled and (re)started", "enable hestia-mesh-watch-claude-code.service" in calls
           and "restart hestia-mesh-watch-claude-code.service" in calls, calls)
        # a second run with nothing changed rewrites nothing and restarts nothing
        h.log.write_text("")
        mtime = unit.stat().st_mtime_ns
        out2 = h.run(table="claude-code|cfg/claude.json|fire-claude.sh")
        check("idempotent state", line(out2, "claude-code"), "claude-code: active(print-only)")
        check("unit untouched", unit.stat().st_mtime_ns, mtime)
        ok("no restart on an unchanged unit", "restart" not in h.log.read_text(), h.log.read_text())


def _fire_case(setup) -> tuple[str, str]:
    with tempfile.TemporaryDirectory() as d:
        h = Host(Path(d))
        h.config("claude.json", JSON_PIN % "claude-code")
        setup(h)
        out = h.run(table="claude-code|cfg/claude.json|fire-claude.sh")
        unit = h.units / "hestia-mesh-watch-claude-code.service"
        return line(out, "claude-code"), unit.read_text() if unit.exists() else ""


def test_fire_needs_operator_authority():
    def good(h):
        (h.hh / "mesh-fire.d").mkdir(mode=0o700)
        f = h.hh / "mesh-fire.d" / "claude-code"
        f.write_text("dp 2026-10-23: all three seats on thor\n")
        f.chmod(0o600)
    st, unit = _fire_case(good)
    check("operator-only flag arms firing", st, "claude-code: active(fire)")
    ok("fire script on ExecStart", "fire-claude.sh" in unit, unit)

    def dir_group_writable(h):
        good(h)
        os.chmod(h.hh / "mesh-fire.d", 0o770)
    st, unit = _fire_case(dir_group_writable)
    check("group-writable mesh-fire.d", st, "claude-code: active(print-only(fire flag refused: mesh-fire.d is not operator-only))")
    ok("no fire script", "fire-claude.sh" not in unit, unit)

    def flag_world_writable(h):
        good(h)
        os.chmod(h.hh / "mesh-fire.d" / "claude-code", 0o666)
    st, _ = _fire_case(flag_world_writable)
    check("world-writable flag", st, "claude-code: active(print-only(fire flag refused: the flag is not operator-only))")

    def home_group_writable(h):
        good(h)
        os.chmod(h.hh, 0o770)
    st, _ = _fire_case(home_group_writable)
    check("group-writable HESTIA_HOME", st, "claude-code: active(print-only(fire flag refused: HESTIA_HOME is not operator-only))")

    def flag_symlink(h):
        (h.hh / "mesh-fire.d").mkdir(mode=0o700)
        elsewhere = h.root / "elsewhere"
        elsewhere.write_text("x")
        elsewhere.chmod(0o600)
        (h.hh / "mesh-fire.d" / "claude-code").symlink_to(elsewhere)
    st, _ = _fire_case(flag_symlink)
    check("symlinked flag", st, "claude-code: active(print-only(fire flag refused: the flag is a symlink))")

    def dir_symlink(h):
        real = h.root / "realdir"
        real.mkdir(mode=0o700)
        f = real / "claude-code"
        f.write_text("x")
        f.chmod(0o600)
        (h.hh / "mesh-fire.d").symlink_to(real)
    st, _ = _fire_case(dir_symlink)
    check("symlinked mesh-fire.d", st, "claude-code: active(print-only(fire flag refused: mesh-fire.d is a symlink))")

    def flag_is_dir(h):
        (h.hh / "mesh-fire.d" / "claude-code").mkdir(parents=True, mode=0o700)
        os.chmod(h.hh / "mesh-fire.d", 0o700)
    st, _ = _fire_case(flag_is_dir)
    check("flag that is a directory", st, "claude-code: active(print-only(fire flag refused: the flag is not a regular file))")

    def no_workspace(h):
        good(h)
        h.ws.rmdir()
    st, unit = _fire_case(no_workspace)
    check("fire flag without a workspace stays print-only", st,
          "claude-code: active(print-only(fire flag set, but no HESTIA_WORKSPACE directory for the fired CLI to run in))")
    ok("no fire script", "fire-claude.sh" not in unit, unit)


def test_removing_the_flag_disarms():
    with tempfile.TemporaryDirectory() as d:
        h = Host(Path(d))
        h.config("claude.json", JSON_PIN % "claude-code")
        (h.hh / "mesh-fire.d").mkdir(mode=0o700)
        f = h.hh / "mesh-fire.d" / "claude-code"
        f.write_text("x")
        f.chmod(0o600)
        t = "claude-code|cfg/claude.json|fire-claude.sh"
        check("armed", line(h.run(table=t), "claude-code"), "claude-code: active(fire)")
        f.unlink()
        h.log.write_text("")
        check("disarmed", line(h.run(table=t), "claude-code"), "claude-code: active(print-only)")
        unit = (h.units / "hestia-mesh-watch-claude-code.service").read_text()
        ok("unit rewritten without the fire script", "fire-claude.sh" not in unit, unit)
        ok("restarted onto the new unit", "restart hestia-mesh-watch-claude-code.service" in h.log.read_text(),
           h.log.read_text())


def test_a_member_no_longer_registered_is_retired():
    with tempfile.TemporaryDirectory() as d:
        h = Host(Path(d))
        h.config("claude.json", JSON_PIN % "claude-code")
        t = "claude-code|cfg/claude.json|fire-claude.sh"
        check("installed", line(h.run(table=t), "claude-code"), "claude-code: active(print-only)")
        unit = h.units / "hestia-mesh-watch-claude-code.service"
        h.config("claude.json", '{"hooks":{}}')          # the member's registration is gone
        out = h.run("--check", table=t)
        check("--check names the retirement", line(out, "claude-code"),
              "claude-code: absent(WOULD-RETIRE hestia-mesh-watch-claude-code.service)")
        ok("--check retired nothing", unit.exists(), "unit removed by --check")
        out = h.run(table=t)
        check("retired", line(out, "claude-code"), "claude-code: absent(retired hestia-mesh-watch-claude-code.service)")
        ok("unit file removed", not unit.exists(), "unit still on disk")
        ok("stopped", not (h.state / unit.name).exists(), "stub says still active")
        ok("disable --now called", f"disable --now {unit.name}" in h.log.read_text(), h.log.read_text())


def test_a_unit_without_the_marker_is_never_retired():
    with tempfile.TemporaryDirectory() as d:
        h = Host(Path(d))
        h.units.mkdir(parents=True)
        u = h.units / "hestia-mesh-watch-claude-code.service"
        u.write_text("[Unit]\nDescription=an operator's own watcher\n")
        (h.state / u.name).touch()
        out = h.run(table="claude-code|cfg/claude.json|fire-claude.sh")
        check("reported, left", line(out, "claude-code"),
              "claude-code: absent(hestia-mesh-watch-claude-code.service exists without the deploy's marker; left as it is)")
        ok("still on disk", u.exists(), "")
        ok("not stopped", (h.state / u.name).exists(), "")


def test_a_hand_started_watcher_holding_the_lock_is_not_doubled():
    with tempfile.TemporaryDirectory() as d:
        h = Host(Path(d))
        h.config("claude.json", JSON_PIN % "claude-code")
        ms = h.root / "mesh-state"
        ms.mkdir()
        lock = ms / "watch-claude-code.lock"
        lock.touch()
        holder = subprocess.Popen(["flock", str(lock), "sleep", "30"])
        try:
            import time
            for _ in range(50):
                if subprocess.run(["flock", "-n", str(lock), "true"]).returncode != 0:
                    break
                time.sleep(0.05)
            out = h.run(table="claude-code|cfg/claude.json|fire-claude.sh")
        finally:
            holder.kill()
            holder.wait()
        ok("held", line(out, "claude-code").startswith("claude-code: held("), out)
        ok("no unit written", not (h.units / "hestia-mesh-watch-claude-code.service").exists(), "")


def test_no_systemd_user_manager_is_said_aloud():
    with tempfile.TemporaryDirectory() as d:
        h = Host(Path(d))
        h.config("claude.json", JSON_PIN % "claude-code")
        out = h.run(table="claude-code|cfg/claude.json|fire-claude.sh", systemd=False)
        check("skipped", line(out, "claude-code"), "claude-code: skipped(no systemd user manager)")
        check("summary", out[-1], "mesh: claude-code=skipped")


TESTS = [
    test_detection_and_check_writes_nothing,
    test_install_writes_a_print_only_unit_and_starts_it,
    test_fire_needs_operator_authority,
    test_removing_the_flag_disarms,
    test_a_member_no_longer_registered_is_retired,
    test_a_unit_without_the_marker_is_never_retired,
    test_a_hand_started_watcher_holding_the_lock_is_not_doubled,
    test_no_systemd_user_manager_is_said_aloud,
]


def teardown_module(module=None):
    """Under `python3 -m pytest` the tests record into FAILS and return normally; this turns a non-empty
    record into the failure pytest reports (tools/ci_selfexec_test.py)."""
    assert not FAILS, FAILS


def main() -> int:
    tests = TESTS
    for t in tests:
        before = len(FAILS)
        try:
            t()
        except Exception as e:  # a crash in one case is that case's failure, not the suite's end
            FAILS.append(f"{t.__name__}: raised {e!r}")
        print(("ok    " if len(FAILS) == before else "FAIL  ") + t.__name__)
    for f in FAILS:
        print("  -", f)
    print(f"{len(tests) - len({f.split(':')[0] for f in FAILS})}/{len(tests)} passed" if not FAILS else f"{len(FAILS)} failure(s)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
