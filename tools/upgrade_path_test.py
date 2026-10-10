#!/usr/bin/env python3
"""Upgrade-path test: a host on the PREVIOUS release must deploy THIS commit cleanly.

WHY (#1237, #1242; dp 2026-10-06). Stage C (#1231) passed every CI job and then half-deployed
every machine in the fleet: the deploy's preflight refused the members' install because the hook
registrations a host already had (written by the previous release) carried no HESTIA_HOME, and
the candidate gates refuse `config.unbacked` without it. Nothing in CI exercised the one path every
host actually takes: "a box that is on the previous release runs the timer and lands on this
commit". This harness is that path, run against the REAL scripts with redirected roots.

WHAT IT DOES, in the order a host lives it:

  0. A throwaway machine: a fake HOME holding all four harness homes (~/.claude, ~/.codex,
     ~/.kimi-code, ~/.gemini), a fake HESTIA_HOME at the standard ~/.hestia, the deploy root at
     the standard ~/.hestia/deploy, a fake workspace, and an ISOLATED daemon (`hestia init`, then
     `serve` on a free loopback port that is never 7711) whose HOME is the fake one. The daemon
     binary must be built from the CANDIDATE (--daemon-bin): one cycle of the timer swaps the
     binary first and installs the members' surface second, and this harness simulates the cycle
     after the swap. Seat projections come from the real seeder, which install-members.sh runs.
  1. PREVIOUS (default: the latest release tag; --previous REF or --previous-back N for
     origin/main~N). A local bare "origin" whose `main` is PREVIOUS; the deploy checkout and web4
     sibling cloned from it the way deploy/from-main/README.md says; the PREVIOUS
     hestia-deploy.sh installed at ~/.local/bin/hestia-deploy; then PREVIOUS's
     deploy/install-members.sh (plan, install, register, seed) — the members' half of the
     cycle, exactly as a fresh host runs it. The previous release's own `--preflight` is run
     first and REPORTED (not asserted): it answers whether the timer alone could have
     bootstrapped this box.
  2. CANDIDATE. `main` on the local origin moves to CANDIDATE and the INSTALLED
     ~/.local/bin/hestia-deploy runs one full cycle — the previous release's script, as on a real
     host, which self-updates and then runs the candidate's gate-preflight.py and
     install-members.sh from the synced checkout. The binary is already current (the isolated
     daemon IS the candidate), so the cycle takes the "CURRENT but the manifest says otherwise"
     arm: preflight, then the members' install. That arm is the one that printed HALF-DEPLOYED
     across the fleet.
  3. ASSERT
       a. the cycle exits 0 and its log carries no HALF-DEPLOYED / REFUSED; the manifest's
          build_id is the candidate;
       b. per registered member: the file its registration invokes is byte-identical to the
          candidate's gate, and run under its REGISTERED command line (the shell assignments on
          the line, plus what the harness itself supplies: Claude Code's settings.json `env`
          block and the probe's declared harness environment; NOT the deploy unit's or the
          operator's shell) it ALLOWS the declared benign read of a scratch file and DENIES the
          declared deploy-hold probe re-aimed at its own installed gate (a write to the thing
          that governs it: gate-self-access);
       c. a second cycle is a no-op: exit 0, `CURRENT`, and the installed surface (harness
          configs, installed hooks, engine link, manifest, projections) byte-identical.

WHAT IT DELIBERATELY DOES NOT DO: build a daemon (pass one), restart anything (the unit name is
one no systemd knows, the restart command is `false`), reach the network (every remote is a local
path; the agent-atlas URL is a path that does not exist, which the deploy reports and survives),
or touch :7711 (every endpoint is the isolated daemon's, and the run refuses if it is not).

    python3 tools/upgrade_path_test.py --daemon-bin core/target/debug/hestia \
        --previous origin/main --candidate HEAD
    python3 tools/upgrade_path_test.py --daemon-bin BIN --previous 588684d6 --candidate origin/main

Exit 0 every assertion held; 1 an assertion failed (the report names which); 2 the harness could
not set up the simulation (that is not a verdict on the candidate).

This file is NOT run by the plugin-tests job (it needs a daemon binary built from the candidate
and full git history); it has its own CI job. Its plumbing is pinned, hermetically, by
tools/upgrade_path_plumbing_test.py.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import secrets
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent.parent
LIVE_PORT = 7711  # the fleet daemon's port: never bound, never dialled by this harness

#: Words in the deploy log that mean the cycle did NOT finish the members' half.
BAD_OUTCOMES = ("HALF-DEPLOYED", "REFUSED", "FAIL ")

#: Environment that crosses from the caller into the simulated machine. Everything else —
#: HESTIA_*, CLAUDECODE, CODEX_*, the operator's own HOME — stays out, so the simulation cannot
#: lean on the box it runs on.
PASSTHROUGH = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "SYSTEMROOT", "PYTHONDONTWRITEBYTECODE")


#: Installed into every Python process the simulated machine starts (via PYTHONPATH): any
#: connect to the guarded port is REFUSED before it leaves the process, and logged, and the
#: harness fails the run if the log is not empty. WHY (measured on this harness's first runs,
#: 2026-10-06): previous-release gates default HESTIA_ENDPOINT to 127.0.0.1:7711 when no
#: projection loads (hestia_gate_mechanism.py, at 588684d6 and still on main), so a gate probed
#: under a registered line without HESTIA_HOME reached the LIVE daemon and opened real
#: escalations under codex's and kimi-code's names. An isolated daemon is not isolation while
#: any code path still carries the live default; this makes the default unreachable and visible.
GUARD_SOURCE = """\
import os, socket, sys
_PORT = int(os.environ.get("UPGRADE_PATH_GUARD_PORT", "0") or 0)
_LOG = os.environ.get("UPGRADE_PATH_GUARD_LOG")
if _PORT:
    _connect, _connect_ex = socket.socket.connect, socket.socket.connect_ex
    def _guard(addr):
        try:
            port = addr[1]
        except Exception:
            return
        if port == _PORT:
            if _LOG:
                try:
                    with open(_LOG, "a") as f:
                        f.write("blocked pid=%d %s:%s argv=%s\\n" % (os.getpid(), addr[0], port, " ".join(sys.argv)[:300]))
                except OSError:
                    pass
            raise ConnectionRefusedError("upgrade-path guard: port %d is the live daemon's" % port)
    def connect(self, addr):
        _guard(addr)
        return _connect(self, addr)
    def connect_ex(self, addr):
        _guard(addr)
        return _connect_ex(self, addr)
    socket.socket.connect, socket.socket.connect_ex = connect, connect_ex
"""


class SetupError(Exception):
    """The simulation could not be built. Not a verdict on the candidate."""


# ------------------------------------------------------------------ pure helpers --------------
def describe_hash_len(describe: str) -> int | None:
    """The abbreviated-sha length in a `git describe` string (`v0.0.4-968-ga7e33bc4` -> 8)."""
    m = re.search(r"-g([0-9a-f]{4,40})(?:-dirty)?$", describe.strip())
    if m:
        return len(m.group(1))
    m = re.fullmatch(r"([0-9a-f]{4,40})", describe.strip())
    return len(m.group(1)) if m else None


def describe_of_version(line: str) -> str:
    """`hestia 0.0.4 (v0.0.4-968-ga7e33bc4)` -> `v0.0.4-968-ga7e33bc4` (hestia-deploy's describe_of)."""
    m = re.search(r"\(([^)]+)\)", line)
    return m.group(1) if m else ""


def classify_cycle(log_text: str, rc: int) -> dict[str, Any]:
    """What one hestia-deploy cycle did, from the lines IT wrote and its exit code."""
    lines = [ln for ln in log_text.splitlines() if ln.strip()]
    bad = [ln for ln in lines if any(w in ln for w in BAD_OUTCOMES)]
    if rc == 0 and not bad:
        if any(" manifest-repair hooks=ok" in ln or re.search(r" DEPLOYED .* hooks=ok", ln) for ln in lines):
            outcome = "DEPLOYED"
        elif any(re.search(r" CURRENT \S+", ln) for ln in lines):
            outcome = "CURRENT"
        elif any(" SKIP " in ln for ln in lines):
            outcome = "SKIP"
        else:
            outcome = "UNKNOWN"
    elif any("HALF-DEPLOYED" in ln for ln in lines):
        outcome = "HALF-DEPLOYED"
    elif any("REFUSED" in ln for ln in lines):
        outcome = "REFUSED"
    else:
        outcome = f"FAILED(rc={rc})"
    return {"outcome": outcome, "rc": rc, "bad_lines": bad}


def gate_command(commands: Iterable[str], entry: str) -> str | None:
    """The registered command line that invokes exactly this gate entrypoint (by basename)."""
    wanted = Path(entry).name
    for command in commands:
        for token in command.split():
            if token.startswith("/") and Path(token).name == wanted:
                return command
    return None


def command_target(command: str, entry: str) -> str | None:
    """The absolute path in a registered command whose basename is the gate entrypoint."""
    wanted = Path(entry).name
    for token in command.split():
        if token.startswith("/") and Path(token).name == wanted:
            return token
    return None


def render_event(event: Any, replacements: dict[str, str]) -> Any:
    if isinstance(event, str):
        for marker, value in replacements.items():
            event = event.replace(marker, value)
        return event
    if isinstance(event, list):
        return [render_event(v, replacements) for v in event]
    if isinstance(event, dict):
        return {k: render_event(v, replacements) for k, v in event.items()}
    return event


def probe_events(gate_probe: dict) -> tuple[dict | None, dict | None]:
    """(allow event, deny event) from a member's declared gate_probe.

    allow: the declared scratch read (`{scratch}`), which every gate must retain.
    deny:  the declared deploy-hold probe (`{hold}`), re-aimed at the member's OWN installed gate.
           The declaration is the harness's event vocabulary for a shell act; the target makes it
           the clearest deny there is — a seat writing the file that governs it.
    """
    allow = deny = None
    for declared in gate_probe.get("events") or []:
        if not isinstance(declared, dict) or not isinstance(declared.get("event"), dict):
            continue
        text = json.dumps(declared["event"])
        if allow is None and "{scratch}" in text:
            allow = declared["event"]
        elif deny is None and "{hold}" in text:
            deny = declared["event"]
    return allow, deny


def payload_denies(stdout: str) -> bool:
    """A harness may encode a denial in JSON on a zero exit (gate-preflight.py's rule)."""
    try:
        value = json.loads(stdout)
    except ValueError:
        return False
    if not isinstance(value, dict):
        return False
    hso = value.get("hookSpecificOutput") if isinstance(value.get("hookSpecificOutput"), dict) else {}
    return (value.get("permissionDecision") == "deny" or value.get("decision") in ("deny", "block")
            or hso.get("permissionDecision") == "deny")


#: A deny of the self-write probe counts only when the gate names WHY: its governance surface.
#: A gate that denies it for an infrastructure reason (no projection, no engine, a missing safety
#: gate) has refused everything, and its deny proves nothing about the law.
SELF_WRITE_REASON = re.compile(r"gate-self|governance surface|self-access", re.I)


#: Members whose gate is KNOWN to allow a write to its own installed file, with the open issue.
#: Measured by this harness on its first run (2026-10-06): the stage-C gemini gate allows
#: `touch`, `echo >`, `write_file` and `replace` aimed at its own installed before_tool.py, and at
#: ~/.gemini/settings.json (its registration); the same gate denies the identical act aimed at
#: kimi's gate (marker 'pre_tool_use.py'). The closure floor names neither file. Listed so that
#: an OPEN, separately tracked hole does not mask the upgrade-path signal this test exists for
#: (a red that is always red hides the next red). A RATCHET, not an excuse: when the gate starts
#: denying for the law, the entry is stale and the run fails until it is removed.
KNOWN_SELF_WRITE_HOLES = {
    "gemini": "#928 (the closure floor names neither .gemini/settings.json nor before_tool.py)",
}


def deny_is_for_the_law(said: str) -> bool:
    return bool(SELF_WRITE_REASON.search(said or ""))


def last_line(text: str) -> str:
    """The line that says why: a gate's `deny [rule]` line when there is one (its remedy text
    follows it over several lines), else the last line."""
    said = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    tagged = [ln for ln in said if re.search(r"\bdeny \[", ln)]
    return (tagged[0] if tagged else said[-1] if said else "")[:240]


def snapshot(paths: Iterable[Path]) -> dict[str, str]:
    """sha256 of every file (and the target of every symlink) under the given roots."""
    out: dict[str, str] = {}
    for root in paths:
        if root.is_symlink():
            out[str(root)] = "-> " + os.readlink(root)
            continue
        if root.is_file():
            out[str(root)] = hashlib.sha256(root.read_bytes()).hexdigest()
            continue
        if not root.is_dir():
            continue
        for p in sorted(root.rglob("*")):
            if p.is_symlink():
                out[str(p)] = "-> " + os.readlink(p)
            elif p.is_file():
                out[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def snapshot_diff(before: dict[str, str], after: dict[str, str]) -> list[str]:
    diff = []
    for key in sorted(set(before) | set(after)):
        if before.get(key) != after.get(key):
            state = ("added" if key not in before else "removed" if key not in after else "changed")
            diff.append(f"{state}: {key}")
    return diff


def resolve_ref(repo: Path, ref: str) -> str:
    out = subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", f"{ref}^{{commit}}"],
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise SetupError(f"cannot resolve {ref!r} in {repo}: {last_line(out.stderr)}")
    return out.stdout.strip()


def latest_release_tag(repo: Path, of: str) -> str:
    """The newest `v*` release tag reachable from `of` (app-v* tags are the app's, not hestia's)."""
    out = subprocess.run(["git", "-C", str(repo), "describe", "--tags", "--abbrev=0",
                          "--match", "v[0-9]*", of], capture_output=True, text=True)
    if out.returncode != 0:
        raise SetupError(f"no v* release tag reachable from {of}: {last_line(out.stderr)}")
    return out.stdout.strip()


def free_port() -> int:
    for _ in range(20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        if port != LIVE_PORT:
            return port
    raise SetupError("no free loopback port")


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if not spec or not spec.loader:
        raise SetupError(f"cannot import {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------ the simulated machine -----
class Machine:
    def __init__(self, root: Path, source: Path, daemon_bin: Path, verbose: bool = False):
        self.root = root
        self.source = source
        self.daemon_bin = daemon_bin
        self.verbose = verbose
        self.home = root / "home"
        self.hestia_home = self.home / ".hestia"
        self.deploy_root = self.hestia_home / "deploy"
        self.workspace = self.home / "ai-workspace"
        self.origin = root / "origin"
        self.scratch_dir = root / "scratch"
        self.port = free_port()
        self.endpoint = f"http://127.0.0.1:{self.port}/mcp"
        self.passphrase = secrets.token_hex(16)
        self.unit = f"hestia-upgrade-sim-{os.getpid()}.service"
        self.guard_dir = root / "guard"
        self.guard_log = root / "live-port-connects.log"
        self.daemon: subprocess.Popen | None = None
        self.transcript: list[str] = []

    # -- environment ------------------------------------------------------------------------
    def base_env(self) -> dict[str, str]:
        env = {k: os.environ[k] for k in PASSTHROUGH if k in os.environ}
        env["HOME"] = str(self.home)
        env["USER"] = os.environ.get("USER", "sim")
        env["PATH"] = f"{self.home}/.local/bin:" + env.get("PATH", "/usr/bin:/bin")
        # Isolation, twice over: every process is told the isolated endpoint (a projection
        # overrides it with the same value), and every Python process carries the live-port guard.
        env["HESTIA_ENDPOINT"] = self.endpoint
        env["PYTHONPATH"] = str(self.guard_dir)
        env["UPGRADE_PATH_GUARD_PORT"] = str(LIVE_PORT)
        env["UPGRADE_PATH_GUARD_LOG"] = str(self.guard_log)
        return env

    def install_guard(self) -> None:
        self.guard_dir.mkdir(parents=True, exist_ok=True)
        (self.guard_dir / "sitecustomize.py").write_text(GUARD_SOURCE)

    def live_port_attempts(self) -> list[str]:
        try:
            return [ln for ln in self.guard_log.read_text().splitlines() if ln.strip()]
        except OSError:
            return []

    def check_projection_endpoints(self) -> None:
        """Every rendered projection must name the isolated daemon, or gates would follow it."""
        for proj in sorted((self.hestia_home / "seats").iterdir()):
            for line in proj.read_text().splitlines():
                key, _, value = line.partition("=")
                if key.split("__")[-1] == "HESTIA_ENDPOINT" and value != self.endpoint:
                    raise SetupError(f"projection {proj.name} names endpoint {value!r}, not the "
                                     f"isolated daemon's {self.endpoint!r}")

    def deploy_env(self) -> dict[str, str]:
        """What hestia-deploy.service gives the timer, re-rooted at the fake HOME."""
        env = self.base_env()
        env.update({
            "HESTIA_HOME": str(self.hestia_home),
            "HESTIA_WORKSPACE": str(self.workspace),
            "HESTIA_ENDPOINT": self.endpoint,
            "HESTIA_UNIT": self.unit,            # a unit no systemd knows: daemon_exe is unknown
            "HESTIA_RESTART_CMD": "false",       # the cycle under test never restarts anything
            "HESTIA_ATLAS_URL": str(self.root / "no-such-atlas.git"),
            "HESTIA_DEPLOY_INVENTORY": "0",      # the agent inventory is not this test's subject
            "GIT_TERMINAL_PROMPT": "0",
        })
        return env

    def daemon_env(self) -> dict[str, str]:
        env = self.base_env()
        env.update({
            "HESTIA_HOME": str(self.hestia_home),
            "HESTIA_WORKSPACE": str(self.workspace),
            "HESTIA_CURRENT_BUILD_FILE": str(self.hestia_home / "current-build.json"),
            "HESTIA_PASSPHRASE": self.passphrase,
        })
        return env

    def log(self, msg: str) -> None:
        line = f"[upgrade-path] {msg}"
        self.transcript.append(line)
        print(line, flush=True)

    def run(self, argv: list[str], *, env: dict[str, str] | None = None, cwd: Path | None = None,
            timeout: int = 600, check: bool = True, input: str | None = None) -> subprocess.CompletedProcess:
        out = subprocess.run(argv, env=env if env is not None else self.base_env(),
                             cwd=str(cwd) if cwd else None, capture_output=True, text=True,
                             timeout=timeout, input=input)
        if self.verbose:
            print(f"$ {' '.join(shlex.quote(a) for a in argv)} -> rc={out.returncode}")
            if out.stdout.strip():
                print(out.stdout.rstrip())
            if out.stderr.strip():
                print(out.stderr.rstrip())
        if check and out.returncode != 0:
            raise SetupError(f"{' '.join(argv[:3])}... rc={out.returncode}: "
                             f"{last_line(out.stderr) or last_line(out.stdout)}")
        return out

    def git(self, *args: str, cwd: Path | None = None, check: bool = True) -> str:
        return self.run(["git", *args], cwd=cwd, check=check).stdout.strip()

    # -- the box ------------------------------------------------------------------------------
    def build_box(self) -> None:
        """Four harnesses installed, hestia not yet: their config dirs and empty configs."""
        self.install_guard()
        for d in (self.home, self.workspace, self.scratch_dir, self.origin, self.home / ".local" / "bin"):
            d.mkdir(parents=True, exist_ok=True)
        (self.home / ".claude").mkdir()
        (self.home / ".claude" / "settings.json").write_text("{}\n")
        (self.home / ".codex").mkdir()
        (self.home / ".codex" / "config.toml").write_text('model = "sim"\n')
        (self.home / ".kimi-code").mkdir()
        (self.home / ".kimi-code" / "config.toml").write_text('default_model = "sim"\n')
        (self.home / ".gemini").mkdir()
        (self.home / ".gemini" / "settings.json").write_text("{}\n")
        # A git identity for the throwaway repos, in the fake HOME (never the operator's).
        (self.home / ".gitconfig").write_text(
            "[user]\n\tname = upgrade-path-sim\n\temail = sim@invalid\n[init]\n\tdefaultBranch = main\n")
        self.hestia_home.mkdir(mode=0o700)

    def start_daemon(self) -> str:
        if self.port == LIVE_PORT:
            raise SetupError("refusing to bind the live daemon's port")
        version = self.run([str(self.daemon_bin), "--version"]).stdout.strip()
        self.run([str(self.daemon_bin), "--home", str(self.hestia_home), "init", "--ai"],
                 env=self.daemon_env(), timeout=120)
        log = open(self.root / "daemon.log", "w")
        self.daemon = subprocess.Popen(
            [str(self.daemon_bin), "--home", str(self.hestia_home), "serve",
             "--bind", f"127.0.0.1:{self.port}"],
            env=self.daemon_env(), stdout=log, stderr=subprocess.STDOUT, cwd=str(self.workspace))
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-03-26", "capabilities": {},
            "clientInfo": {"name": "upgrade-path", "version": "0"}}}).encode()
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if self.daemon.poll() is not None:
                raise SetupError(f"daemon exited rc={self.daemon.returncode}: "
                                 f"{last_line((self.root / 'daemon.log').read_text())}")
            try:
                req = urllib.request.Request(self.endpoint, data=body, headers={
                    "Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
                with urllib.request.urlopen(req, timeout=5) as r:
                    if b'"result"' in r.read():
                        break
            except OSError:
                pass
            time.sleep(0.5)
        else:
            raise SetupError("isolated daemon never answered initialize within 120 s")
        endpoint_file = self.hestia_home / "endpoint"
        if not endpoint_file.is_file() or str(self.port) not in endpoint_file.read_text():
            raise SetupError(f"daemon did not write {endpoint_file} naming port {self.port}")
        # The installed binary the deploy compares against: the daemon's own bytes.
        shutil.copy2(self.daemon_bin, self.home / ".local" / "bin" / "hestia")
        self.log(f"isolated daemon up on :{self.port} ({version})")
        return describe_of_version(version)

    def stop_daemon(self) -> None:
        if self.daemon and self.daemon.poll() is None:
            self.daemon.terminate()
            try:
                self.daemon.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.daemon.kill()
                self.daemon.wait(timeout=10)

    def build_origins(self, previous: str) -> None:
        """Local bare remotes: hestia (main = PREVIOUS, plus the release tags), web4 (one commit)."""
        hestia_git = self.origin / "hestia.git"
        self.git("init", "-q", "--bare", str(hestia_git))
        self.git("-C", str(self.source), "push", "-q", str(hestia_git),
                 f"{previous}:refs/heads/main", "refs/tags/v*:refs/tags/v*")
        web4_work = self.origin / "web4-work"
        self.git("init", "-q", str(web4_work))
        self.git("-C", str(web4_work), "commit", "-q", "--allow-empty", "-m", "web4 sibling stand-in")
        self.git("clone", "-q", "--bare", str(web4_work), str(self.origin / "web4.git"))

    def move_main(self, sha: str) -> None:
        self.git("-C", str(self.source), "push", "-q", "--force", str(self.origin / "hestia.git"),
                 f"{sha}:refs/heads/main")

    def install_deploy_checkout(self) -> None:
        """deploy/from-main/README.md 'Install — Linux': clone both, install the script."""
        self.deploy_root.mkdir(parents=True, exist_ok=True)
        self.git("clone", "-q", str(self.origin / "hestia.git"), str(self.deploy_root / "hestia"))
        self.git("clone", "-q", str(self.origin / "web4.git"), str(self.deploy_root / "web4"))
        script = self.deploy_root / "hestia" / "deploy" / "from-main" / "hestia-deploy.sh"
        if not script.is_file():
            raise SetupError(f"the previous release has no {script.relative_to(self.deploy_root)}")
        self.run(["install", "-m", "0755", str(script), str(self.home / ".local" / "bin" / "hestia-deploy")])

    def pin_abbrev(self, length: int) -> None:
        """Make the deploy checkout name commits at the daemon binary's abbreviation length.

        On a real host the binary is BUILT in this checkout, so `git describe` there and the
        binary's baked-in describe agree by construction. Here the binary was built elsewhere,
        and git's default abbreviation scales with the object count of the repo it runs in, so
        the same commit can read `-ga7e33bc` in one clone and `-ga7e33bc4` in another.
        """
        self.git("-C", str(self.deploy_root / "hestia"), "config", "core.abbrev", str(length))

    def origin_describe(self, length: int) -> str:
        return self.git("-C", str(self.origin / "hestia.git"), "describe", "--tags", "--always",
                        f"--abbrev={length}", "main")

    # -- the scripts under test ---------------------------------------------------------------
    def deploy_log_offset(self) -> int:
        f = self.hestia_home / "deploy.log"
        return f.stat().st_size if f.exists() else 0

    def deploy_log_since(self, offset: int) -> str:
        f = self.hestia_home / "deploy.log"
        if not f.exists():
            return ""
        with open(f, "rb") as fh:
            fh.seek(offset)
            return fh.read().decode("utf-8", "replace")

    def run_installed_deploy(self, *args: str, timeout: int = 900) -> tuple[int, str]:
        """~/.local/bin/hestia-deploy, as the timer runs it. Returns (rc, the log lines it wrote)."""
        offset = self.deploy_log_offset()
        out = self.run(["bash", str(self.home / ".local" / "bin" / "hestia-deploy"), *args],
                       env=self.deploy_env(), cwd=self.home, timeout=timeout, check=False)
        return out.returncode, self.deploy_log_since(offset)

    def run_install_members(self, timeout: int = 900) -> subprocess.CompletedProcess:
        """The members' half of a cycle, from the deploy checkout (hestia-deploy's install_hooks)."""
        return self.run(["bash", str(self.deploy_root / "hestia" / "deploy" / "install-members.sh")],
                        env=self.deploy_env(), cwd=self.home, timeout=timeout, check=False)

    # -- the installed gates ------------------------------------------------------------------
    def installed_surface(self) -> list[Path]:
        h = self.home
        return [h / ".claude" / "settings.json", h / ".claude" / "hooks",
                h / ".codex" / "config.toml", h / ".codex" / "hooks",
                h / ".kimi-code" / "config.toml", h / ".kimi-code" / "hooks",
                h / ".gemini" / "settings.json", h / ".gemini" / "hestia-plugins",
                self.hestia_home / "shared", self.hestia_home / "shared.builds",
                self.hestia_home / "current-build.json", self.hestia_home / "seats",
                h / ".profile", h / ".local" / "bin" / "hestia-deploy"]

    def launcher_env(self, member_dir: str, command: str, declared_env: dict[str, str]) -> dict[str, str]:
        """What the harness process gives its hook, minus anything the operator's shell adds.

        Claude Code applies settings.json `env` to the hooks it spawns; the probe's declared
        environment is the harness's own identity (CLAUDECODE=1). The assignments ON the command
        line are applied by the shell that runs it, below. HESTIA_HOME published into ~/.profile
        by the installer is deliberately NOT applied: a harness launched from a desktop, a unit
        or a hub carries no login profile, and the preflight measures the same thing.
        """
        env = self.base_env()
        if member_dir == "claude-code":
            try:
                settings = json.loads((self.home / ".claude" / "settings.json").read_text())
            except (OSError, ValueError):
                settings = {}
            for k, v in (settings.get("env") or {}).items():
                if isinstance(k, str) and isinstance(v, str):
                    env[k] = v
        env.update(declared_env)
        return env

    def check_gates(self, candidate_tree: Path, scratch: Path, with_login_home: bool = False) -> list[dict]:
        preflight = load_module(candidate_tree / "deploy" / "from-main" / "gate-preflight.py",
                                "upgrade_gate_preflight")
        rows: list[dict] = []
        for expects in sorted((candidate_tree / "plugins").glob("*/expects.json")):
            member = expects.parent.name
            install = (json.loads(expects.read_text()).get("install") or {})
            probe = install.get("gate_probe")
            reg = install.get("registration") or {}
            if not isinstance(probe, dict) or not reg.get("path"):
                continue
            entry = probe["entry"]
            row: dict[str, Any] = {"member": member}
            rows.append(row)
            reg_path = self.home.joinpath(*reg["path"])
            if not reg_path.exists():
                row.update(status="FAIL", reason=f"no registration file {reg_path.name}")
                continue
            command = gate_command(preflight._commands_from_registration(reg_path, reg["reader"]), entry)
            if not command:
                row.update(status="FAIL", reason=f"{Path(entry).name} is not registered")
                continue
            target = command_target(command, entry)
            row["registered"] = command.replace(str(self.home), "~")
            want = hashlib.sha256((expects.parent / entry).read_bytes()).hexdigest()
            got = hashlib.sha256(Path(target).read_bytes()).hexdigest() if target and Path(target).is_file() else None
            row["installed_is_candidate"] = got == want
            if got != want:
                # Probing the previous release's gate says nothing about the candidate.
                row.update(status="FAIL", reason="the installed gate is not the candidate's bytes "
                           "(the members' install did not land)")
                continue
            allow_event, deny_event = probe_events(probe)
            env = self.launcher_env(member, command, probe.get("environment") or {})
            if with_login_home:
                env["HESTIA_HOME"] = str(self.hestia_home)
            verdicts = {}
            for label, event in (("allow", allow_event), ("deny", deny_event)):
                if event is None:
                    verdicts[label] = {"denied": None, "said": "no such declared probe"}
                    continue
                rendered = render_event(event, {"{scratch}": str(scratch), "{hold}": str(target)})
                try:
                    out = subprocess.run(["/bin/sh", "-c", command], input=json.dumps(rendered),
                                         env=env, cwd=str(self.workspace), capture_output=True,
                                         text=True, timeout=60)
                    denied = out.returncode != 0 or payload_denies(out.stdout)
                    verdicts[label] = {"denied": denied, "rc": out.returncode,
                                       "said": last_line(out.stderr) or last_line(out.stdout)}
                except subprocess.TimeoutExpired:
                    verdicts[label] = {"denied": True, "rc": None, "said": "timeout (60 s)"}
            row["allow"], row["deny"] = verdicts["allow"], verdicts["deny"]
            deny_ok = verdicts["deny"]["denied"] is True and deny_is_for_the_law(verdicts["deny"]["said"])
            known = KNOWN_SELF_WRITE_HOLES.get(member)
            functional = row["installed_is_candidate"] and verdicts["allow"]["denied"] is False
            reasons = []
            if functional and known and verdicts["deny"]["denied"] is False:
                row.update(status="known-open", reason=f"self-write allowed: known hole {known}")
                continue
            if functional and known and deny_ok:
                row.update(status="FAIL", reason=f"stale KNOWN_SELF_WRITE_HOLES entry ({known}): the "
                           "gate now denies its own self-write; remove the entry")
                continue
            ok = functional and deny_ok
            if not row["installed_is_candidate"]:
                reasons.append("installed gate is not the candidate's bytes")
            if verdicts["allow"]["denied"] is not False:
                reasons.append(f"benign read refused: {verdicts['allow']['said']}")
            if verdicts["deny"]["denied"] is not True:
                reasons.append(f"self-write allowed: {verdicts['deny']['said']}")
            elif not deny_ok:
                reasons.append(f"self-write denied for an unrelated reason: {verdicts['deny']['said']}")
            row["status"] = "ok" if ok else "FAIL"
            if reasons:
                row["reason"] = "; ".join(reasons)
        return rows


# ------------------------------------------------------------------ the scenario --------------
def scenario(args: argparse.Namespace) -> int:
    source = Path(args.repo).resolve()
    candidate = resolve_ref(source, args.candidate)
    if args.previous_back is not None:
        previous_ref = f"origin/main~{args.previous_back}"
    else:
        previous_ref = args.previous or latest_release_tag(source, candidate)
    previous = resolve_ref(source, previous_ref)
    daemon_bin = Path(args.daemon_bin).resolve()
    if not os.access(daemon_bin, os.X_OK):
        raise SetupError(f"--daemon-bin {daemon_bin} is not executable")

    parent = Path(args.workdir) if args.workdir else Path(tempfile.gettempdir())
    # The scratch file must sit under a temp root the gate recognises (/tmp or /var/tmp; see
    # hestia-deploy.sh's preflight), so the default workdir is /tmp, never a per-user TMPDIR.
    if not args.workdir and not str(parent.resolve()).startswith(("/tmp", "/var/tmp")):
        parent = Path("/tmp")
    root = Path(tempfile.mkdtemp(prefix="hestia-upgrade-path-", dir=str(parent)))
    m = Machine(root, source, daemon_bin, verbose=args.verbose)
    if m.home.resolve() == Path.home().resolve():
        raise SetupError("the fake HOME resolved to the real one")
    t0 = time.monotonic()
    failures: list[str] = []
    report: dict[str, Any] = {"previous": f"{previous_ref} ({previous[:10]})",
                              "candidate": f"{args.candidate} ({candidate[:10]})", "root": str(root)}
    m.log(f"previous={previous_ref} ({previous[:10]})  candidate={args.candidate} ({candidate[:10]})")
    m.log(f"simulated machine at {root}")
    try:
        m.build_box()
        daemon_describe = m.start_daemon()
        length = describe_hash_len(daemon_describe)
        m.build_origins(previous)
        m.install_deploy_checkout()
        if length:
            m.pin_abbrev(length)

        # ---- 1. the previous release, installed as a fresh host installs it -----------------
        rc, text = m.run_installed_deploy("--preflight")
        verdict = next((ln.split("PREFLIGHT", 1)[1].strip() for ln in text.splitlines()
                        if "PREFLIGHT" in ln), f"rc={rc}")
        report["fresh_host_timer_preflight"] = verdict
        m.log(f"previous: a fresh host's first timer cycle would preflight: {verdict}")
        out = m.run_install_members()
        report["previous_install_rc"] = out.returncode
        (root / "previous-install.log").write_text(out.stdout + out.stderr)
        if out.returncode != 0:
            raise SetupError(f"the previous release's install-members.sh failed rc={out.returncode}: "
                             f"{last_line(out.stderr) or last_line(out.stdout)}")
        seats = sorted(p.name for p in (m.hestia_home / "seats").glob("*.env"))
        m.log(f"previous: installed; manifest build_id="
              f"{json.loads((m.hestia_home / 'current-build.json').read_text()).get('build_id')}; "
              f"seat projections: {', '.join(seats) or 'NONE'}")
        report["previous_seats"] = seats
        m.check_projection_endpoints()

        # ---- 2. the candidate, via the timer's path -------------------------------------------
        m.move_main(candidate)
        target = m.origin_describe(length or 7)
        if target != daemon_describe:
            raise SetupError(f"--daemon-bin describes itself as {daemon_describe!r} but the candidate "
                             f"is {target!r}; build the daemon from the candidate")
        rc, text = m.run_installed_deploy()
        (root / "upgrade-cycle.log").write_text(text)
        cycle = classify_cycle(text, rc)
        report["upgrade_cycle"] = cycle
        m.log(f"upgrade cycle: {cycle['outcome']} (rc={rc})")
        for ln in text.splitlines():
            if any(w in ln for w in ("gate-preflight", "REFUSED", "HALF-DEPLOYED", "PREFLIGHT",
                                     "WARN preflight", "manifest-repair", "self-updated")):
                m.log(f"   | {ln}")
        # CURRENT is a full deploy only when there was nothing to install (previous == candidate's
        # members' surface already); the manifest check below decides that.
        if cycle["outcome"] not in ("DEPLOYED", "CURRENT"):
            failures.append(f"a. upgrade cycle was {cycle['outcome']}, not a full deploy")
        manifest = json.loads((m.hestia_home / "current-build.json").read_text())
        report["manifest_build_id"] = manifest.get("build_id")
        if manifest.get("build_id") != target:
            failures.append(f"a. manifest build_id is {manifest.get('build_id')!r}, not {target!r}")

        # ---- 3b. the installed gates, under their registered lines ----------------------------
        scratch = m.scratch_dir / "probe"
        scratch.write_text("")
        cand_tree = m.deploy_root / "hestia"
        rows = m.check_gates(cand_tree, scratch)
        report["gates"] = rows
        for row in rows:
            def said(probe: str) -> str:
                denied = (row.get(probe) or {}).get("denied")
                return "-" if denied is None else "deny" if denied else "allow"
            m.log(f"gate {row['member']:12} {row['status']:4} "
                  f"read={said('allow')} self-write={said('deny')} "
                  f"candidate-bytes={row.get('installed_is_candidate')}"
                  + (f"  -- {row['reason']}" if row.get("reason") else ""))
            if row["status"] not in ("ok", "known-open"):
                failures.append(f"b. {row['member']}: {row.get('reason')}")
        if any(r["status"] not in ("ok", "known-open") and r.get("installed_is_candidate") for r in rows):
            # Informational: the same gates with the login profile's HESTIA_HOME. Separates "the
            # registered line is missing the locator" from "the gate is broken".
            for row in m.check_gates(cand_tree, scratch, with_login_home=True):
                m.log(f"   (with ~/.profile's HESTIA_HOME) {row['member']:12} {row['status']}"
                      + (f"  -- {row['reason']}" if row.get("reason") else ""))

        # ---- 3c. the second cycle is a no-op ---------------------------------------------------
        before = snapshot(m.installed_surface())
        rc2, text2 = m.run_installed_deploy()
        (root / "second-cycle.log").write_text(text2)
        after = snapshot(m.installed_surface())
        second = classify_cycle(text2, rc2)
        changed = snapshot_diff(before, after)
        report["second_cycle"] = {**second, "changed": [c.replace(str(m.home), "~") for c in changed]}
        m.log(f"second cycle: {second['outcome']} (rc={rc2}), {len(changed)} installed file(s) changed")
        for c in changed[:20]:
            m.log(f"   | {c.replace(str(m.home), '~')}")
        if second["outcome"] != "CURRENT" or changed:
            failures.append(f"c. second cycle was {second['outcome']} and changed {len(changed)} file(s), "
                            "not a no-op")
    finally:
        m.stop_daemon()
        attempts = m.live_port_attempts()
        report["live_port_attempts"] = attempts
        if attempts:
            failures.append(f"d. {len(attempts)} connection attempt(s) to 127.0.0.1:{LIVE_PORT} "
                            "(blocked by the guard; the simulation is NOT isolated)")
            for a in attempts[:10]:
                m.log(f"   | {a}")
        report["seconds"] = round(time.monotonic() - t0, 1)
        report["failures"] = failures
        if args.json:
            Path(args.json).write_text(json.dumps(report, indent=2))
        if not args.keep:
            shutil.rmtree(root, ignore_errors=True)
        else:
            m.log(f"kept {root}")
    m.log(f"{len(failures)} failure(s) in {report['seconds']} s")
    for f in failures:
        m.log(f"FAIL {f}")
    if not failures:
        m.log("PASS: a host on the previous release deploys the candidate cleanly")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--daemon-bin", required=True, help="a hestia binary built from the candidate")
    p.add_argument("--candidate", default="HEAD", help="the commit being deployed (default HEAD)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--previous", help="the release a host is on (default: latest v* tag)")
    g.add_argument("--previous-back", type=int, metavar="N", help="previous = origin/main~N")
    p.add_argument("--repo", default=str(ROOT), help="the git repo holding both commits")
    p.add_argument("--workdir", help="where the throwaway machine is built (default /tmp)")
    p.add_argument("--keep", action="store_true", help="keep the throwaway machine for inspection")
    p.add_argument("--json", help="write the report here")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    try:
        return scenario(args)
    except SetupError as exc:
        print(f"[upgrade-path] SETUP FAILED (not a verdict on the candidate): {exc}", flush=True)
        return 2


if __name__ == "__main__":
    sys.exit(main())
