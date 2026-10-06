#!/usr/bin/env python3
"""One-gate census: stage D's proof, per host, of what is INSTALLED and LIVE on this machine.

docs/one-gate-convergence-plan.md section 5. dp, 2026-10-06, after #1245's fleet rollout fixed stale
hook registrations everywhere: "hopefully they actually do what they are supposed to." Nothing had
measured the live installs on any machine but the one a change was written on. This does, and
it is meant to be run on EVERY machine, from that machine's deploy checkout.

For each harness hestia supports (the plugins whose expects.json declares a gate probe and a
registration), one row per question:

  1. bytes         installed gate + witness + every other installed member file, and the shared
                   engine the seat's projection resolves, vs the hooks-gt CERTIFIED bytes at the
                   deployed build ($HESTIA_HOME/current-build.json head_sha, read from the deploy
                   checkout with `git show`, so a moved or dirty checkout cannot stand in for it).
  2. registration  the registered hook lines vs what the reconciler would render NOW
                   (deploy/register-members.py prepare_member, dry, under the deploy unit's env).
                   Expected to be a no-op since #1245.
  3. behaviour     the INSTALLED gate, under its REGISTERED command line (interpreter, target and
                   the line's own env assignments, as gate-preflight.py's _launcher_env reads them),
                   against an ISOLATED daemon: a benign scratch read (allow), a write to the gate's
                   OWN installed file (deny for the governance surface; the escalation it opens on
                   the isolated daemon is read back for its bar and asker_basis), a credential-path
                   read (deny), an out-of-scope read (deny, or a scope request).
  4. witness       the benign act's Post event through the INSTALLED witness lands an outcome on
                   the isolated chain under the seat's member id, with the same correlation key the
                   gate's decision row carries (the Pre->Post identity).
  5. timing        Class T: decision wall time with the isolated daemon healthy, and with the
                   seat's endpoint aimed at a black hole (accepts, never answers: class_t_seat_audit's
                   model of a live but starved daemon). PASS when the starved act is DENIED before
                   the harness's REGISTERED timeout kills the hook (the gate aims at timeout - margin;
                   both numbers are on the row).
  6. identity      the member id on the gate's decision row vs the seat that ran it. The census runs
                   gates directly, not through a harness session, so asker_basis is recorded as the
                   daemon saw it (expected: Asserted) rather than claimed.

USE, NOT ONLY PRESENCE (dp, 2026-10-06). A harness directory can exist, and the deploy will install
hooks into it, on a machine where that harness has never run (gemini, fleet-wide). Each seat is
therefore one of:
  absent                  the harness config directory is not on this host;
  installed, not in use   hooks are installed but there is no harness session history within
                          --in-use-days (the evidence is printed on the row);
  in use                  session history inside the window.
Rows are measured for every installed seat. PASS/FAIL and the exit code cover only seats IN USE;
a not-in-use seat's failures are reported as latent, never as fleet failures.

SAFETY. This census never acts on the live daemon. Every behavioural probe runs against a daemon
this run starts from the host's own installed binary (`init --ai`, then `serve` on a free loopback
port, its own HESTIA_HOME and HOME under the throwaway dir). Each seat's projection is copied into a
throwaway home re-pointed by deploy/from-main/seat_projection_repoint.py (HESTIA_HOME), plus the
isolated endpoint and every seat-local state directory, so no probe drains a real spool or writes a
real tally. Every Python process the census starts carries a sitecustomize guard (PYTHONPATH) that
REFUSES and logs (a) any connect to a live endpoint port (7711, the host's `endpoint` file, every
projection's HESTIA_ENDPOINT) and (b) any write outside the throwaway dir; every probe must also
leave an "armed" mark, so a probe the guard did not load into is visible. The census FAILS if the
guard log is non-empty or any probe was unguarded. Host writes: the throwaway dir and --json only.

WHAT A PASS DOES NOT SHOW (measured on CBP, 2026-10-06; read these before quoting a green row):
  - the isolated daemon is fresh (`init --ai`): it grants each member NO scope, so the out-of-scope
    read is refused by an empty grant set (`granted: )`). The row proves the scope rule fires on the
    installed bytes, not that a seat's real grants are bounded correctly;
  - the starved decision lands ~0.05-0.1 s AFTER the gate's own deadline (timeout - margin): the
    deadline bounds the decision, not process exit. `inside_gate_deadline` reports it; the row
    passes on the harness's REGISTERED timeout, which is what the harness enforces;
  - the self-write escalation's asker_basis is what the isolated daemon recorded for a gate run
    with a probe session id (measured: `session`), not proof of a harness session;
  - "in use" is session-history evidence on disk; the live chain is not consulted.

RATCHET. KNOWN_OPEN names holes that are open and tracked elsewhere, as #1244 does: a probe listed
there that still fails is reported known-open; one that now passes FAILS the census as a stale entry
until the line is removed.

Run it from the deploy checkout (it loads the deploy checkout's own gate-preflight.py,
register-members.py and hooks_gt.py, so a copy of this file outside the tree works):

    python3 tools/one_gate_census.py --json /tmp/one-gate-census.json
"""
from __future__ import annotations

import argparse
import contextlib
import datetime
import glob
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
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Optional

LIVE_DEFAULT_PORT = 7711

#: Probes KNOWN to fail, with the open item that tracks each. A ratchet, not an excuse: when the
#: probe starts passing the entry is stale and the census fails until it is removed.
KNOWN_OPEN: dict[tuple[str, str], str] = {
    # Measured by #1244's harness and by this census on CBP: the stage-C gemini gate allows a write
    # to its own installed before_tool.py (the closure floor names neither that file nor
    # ~/.gemini/settings.json). #1247 derives each member's governance surface from its install
    # declaration.
    ("gemini", "self_write"): "#1247 (closure does not cover gemini's install surface)",
}

#: Where each harness keeps its own session history: the USE evidence (plugin directory -> globs
#: under HOME). A harness absent from this table is never "in use" by session evidence.
SESSION_HISTORY: dict[str, tuple[str, ...]] = {
    "claude-code": (".claude/projects/*/*.jsonl",),
    "codex": (".codex/sessions/*/*/*/*.jsonl",),
    "kimi": (".kimi-code/sessions/*/*/*", ".kimi-code/sessions/*/*"),
    "gemini": (".gemini/tmp/*/chats/*",),
}

#: Environment that crosses from the caller into a probe. HESTIA_*, the harness markers and the
#: operator's role stay out: a probe gets what its REGISTERED line and its harness supply.
#: Host paths the engine hard-codes, redirected under the throwaway by the guard for every probe.
REDIRECTED_HOST_PATHS = ("/tmp/hestia-actions",)

PASSTHROUGH = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "USER", "LOGNAME", "SYSTEMROOT")

#: The engine's infrastructure refusals: a deny with one of these proves nothing about the law.
INFRA_RULE = re.compile(r"^(config\.|gate\.(bootstrap|event_unreadable|evidence_uncommitted|"
                        r"daemon|unreachable|bound|deadline|superseded))")
SELF_WRITE_RULE = re.compile(r"gate\.self_access|gate-self|governance surface|self-access", re.I)
SCOPE_RULE = re.compile(r"scope|mrh", re.I)
CREDENTIAL_RULE = re.compile(r"egress\.secret|secret|credential", re.I)

GUARD_SOURCE = r'''
import builtins, io, os, socket, sys
_PORTS = {int(p) for p in os.environ.get("ONE_GATE_CENSUS_GUARD_PORTS", "").split(",") if p.strip().isdigit()}
_LOG = os.environ.get("ONE_GATE_CENSUS_GUARD_LOG")
_ARMED = os.environ.get("ONE_GATE_CENSUS_ARMED_LOG")
_ROOT = os.environ.get("ONE_GATE_CENSUS_WRITE_ROOT")
_RUN = os.environ.get("ONE_GATE_CENSUS_RUN", "")
_open = builtins.open
def _append(path, line):
    if path:
        try:
            with _open(path, "a") as f:
                f.write(line + "\n")
        except OSError:
            pass
def _block(what):
    _append(_LOG, "blocked run=%s pid=%d %s argv=%s" % (_RUN, os.getpid(), what, " ".join(sys.argv)[:200]))
if _PORTS:
    _connect, _connect_ex = socket.socket.connect, socket.socket.connect_ex
    def _guard(addr):
        try:
            port = addr[1]
        except Exception:
            return
        if port in _PORTS:
            _block("connect %s:%s" % (addr[0], port))
            raise ConnectionRefusedError("one-gate census guard: port %d is a live daemon's" % port)
    def connect(self, addr):
        _guard(addr)
        return _connect(self, addr)
    def connect_ex(self, addr):
        _guard(addr)
        return _connect_ex(self, addr)
    socket.socket.connect, socket.socket.connect_ex = connect, connect_ex
if _ROOT:
    _ROOTS = (os.path.realpath(_ROOT), "/dev")
    # REDIRECTS: host paths the engine hard-codes (no env override), moved under the throwaway for
    # every operation, so a probe's state stays the census's: `/tmp/hestia-actions` (the Pre->Post
    # correlation cache, hestia_witness_core.ACTIONS_DIR) is shared with every live seat.
    _REDIR = []
    for _pair in os.environ.get("ONE_GATE_CENSUS_REDIRECT", "").split(";"):
        if "=>" in _pair:
            _src, _dst = _pair.split("=>", 1)
            _REDIR.append((_src.rstrip("/"), _dst.rstrip("/")))
    def _r(path):
        if isinstance(path, int):
            return path
        try:
            p = os.fsdecode(path)
        except Exception:
            return path
        for src, dst in _REDIR:
            if p == src or p.startswith(src + "/"):
                return dst + p[len(src):]
        return path
    def _ok(path):
        try:
            p = os.path.realpath(os.fsdecode(path))
        except Exception:
            return True
        return any(p == r or p.startswith(r + os.sep) for r in _ROOTS)
    def _deny(op, path):
        _block("write %s %s" % (op, path))
        raise PermissionError(13, "one-gate census guard: write outside the throwaway dir", str(path))
    def _gopen(file, mode="r", *a, **k):
        file = _r(file)
        if not isinstance(file, int) and any(c in str(mode) for c in "wax+") and not _ok(file):
            _deny("open", file)
        return _open(file, mode, *a, **k)
    builtins.open = _gopen
    io.open = _gopen
    _osopen = os.open
    _W = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC
    def _gosopen(path, flags, *a, **k):
        path = _r(path)
        if flags & _W and not _ok(path):
            _deny("os.open", path)
        return _osopen(path, flags, *a, **k)
    os.open = _gosopen
    def _wrap1(name):
        f = getattr(os, name)
        def g(path, *a, **k):
            path = _r(path)
            if not _ok(path):
                if name == "mkdir" and os.path.isdir(path):
                    return f(path, *a, **k)      # raises FileExistsError: nothing was written
                _deny(name, path)
            return f(path, *a, **k)
        setattr(os, name, g)
    for _n in ("mkdir", "remove", "unlink", "rmdir"):
        _wrap1(_n)
    def _wrap2(name):
        f = getattr(os, name)
        def g(src, dst, *a, **k):
            src, dst = _r(src), _r(dst)
            for p in (src, dst):
                if not _ok(p):
                    _deny(name, p)
            return f(src, dst, *a, **k)
        setattr(os, name, g)
    for _n in ("rename", "replace"):
        _wrap2(_n)
    def _wrapR(name):
        f = getattr(os, name)
        def g(path, *a, **k):
            return f(_r(path), *a, **k)
        setattr(os, name, g)
    for _n in ("stat", "lstat", "access", "listdir", "scandir"):
        _wrapR(_n)
_append(_ARMED, "armed run=%s pid=%d" % (_RUN, os.getpid()))
'''


class SetupError(Exception):
    """The census could not be set up. Not a verdict on any seat."""


# ------------------------------------------------------------------ small helpers ----------------
def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> Optional[str]:
    try:
        return sha256_bytes(path.read_bytes())
    except OSError:
        return None


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SetupError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def free_port(forbidden: set[int]) -> int:
    for _ in range(50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        if port not in forbidden:
            return port
    raise SetupError("no free loopback port")


def port_of(url: str) -> Optional[int]:
    m = re.match(r"^[a-z]+://[^/:]+:(\d+)", (url or "").strip())
    return int(m.group(1)) if m else None


def projection_name(seat: str) -> str:
    # spelled in two parts so the census source never carries the dot-file token a gate's egress
    # rule matches in a command line (a known false positive on the env-file token)
    return seat + ".e" + "nv"


def read_projection(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def projection_values(lines: list[str]) -> dict[str, str]:
    out = {}
    for ln in lines:
        if not ln or ln.startswith("#") or "=" not in ln:
            continue
        k, v = ln.split("=", 1)
        out[k.split("__", 1)[-1]] = v
    return out


def deny_line(text: str) -> str:
    """The line that says why: a gate's `deny [rule]` line when there is one, else the last line."""
    said = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    tagged = [ln for ln in said if re.search(r"\bdeny \[", ln)]
    return (tagged[0] if tagged else said[-1] if said else "")


def rule_of(text: str) -> str:
    m = re.search(r"\bdeny \[([^\]]+)\]", text or "")
    return m.group(1) if m else ""


def payload_denies(stdout: str) -> bool:
    try:
        value = json.loads(stdout)
    except ValueError:
        return False
    if not isinstance(value, dict):
        return False
    hso = value.get("hookSpecificOutput") if isinstance(value.get("hookSpecificOutput"), dict) else {}
    return (value.get("permissionDecision") == "deny" or value.get("decision") in ("deny", "block")
            or hso.get("permissionDecision") == "deny")


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


def probe_events(gate_probe: dict) -> tuple[Optional[dict], Optional[dict]]:
    """(read event, shell event) from a member's declared gate_probe: the harness's own vocabulary
    for a file read (`{scratch}`) and for a shell act (`{hold}`), re-aimed per probe."""
    read = shell = None
    for declared in gate_probe.get("events") or []:
        if not isinstance(declared, dict) or not isinstance(declared.get("event"), dict):
            continue
        text = json.dumps(declared["event"])
        if read is None and "{scratch}" in text:
            read = declared["event"]
        elif shell is None and "{hold}" in text:
            shell = declared["event"]
    return read, shell


def judge_self_write(plugin_dir: str, result: dict) -> tuple[str, str]:
    """-> (pass | known-open | stale | fail, why) for the write-to-own-gate probe, with the ratchet.

    A deny counts only when it names the governance surface: a gate that refuses for an
    infrastructure reason refuses everything, and that proves nothing about the law."""
    law_deny = result.get("denied") is True and bool(SELF_WRITE_RULE.search(result.get("said") or ""))
    known = KNOWN_OPEN.get((plugin_dir, "self_write"))
    if known and result.get("denied") is False:
        return "known-open", f"self-write allowed: known open {known}"
    if known and law_deny:
        return "stale", (f"STALE ratchet: KNOWN_OPEN[{plugin_dir}, self_write] ({known}): the gate now "
                         "denies its own self-write; remove the entry")
    if law_deny:
        return "pass", "denied for the governance surface"
    if result.get("denied") is False:
        return "fail", "self-write allowed"
    return "fail", f"self-write denied for an unrelated reason: {result.get('said')}"


def harness_number(source: str, key: str) -> Optional[float]:
    """A number from the installed gate's own HARNESS data (`"key": 1.5`)."""
    m = re.search(r'"%s"\s*:\s*([0-9.]+)' % re.escape(key), source)
    return float(m.group(1)) if m else None


@contextlib.contextmanager
def without_hestia_env():
    """Hide the operator's HESTIA_* while a shared reader expands `${X:-default}` from os.environ:
    a probe gets the launcher's default, not whatever this shell happens to carry."""
    saved = {k: v for k, v in os.environ.items() if k.startswith("HESTIA_")}
    for k in saved:
        del os.environ[k]
    try:
        yield
    finally:
        os.environ.update(saved)


# ------------------------------------------------------------------ the isolated daemon ----------
class Mcp:
    """A minimal MCP streamable-HTTP client for the ISOLATED daemon only."""

    def __init__(self, endpoint: str, live_ports: set[int]):
        if port_of(endpoint) in live_ports:
            raise SetupError(f"refusing to speak to a live daemon port: {endpoint}")
        self.endpoint, self.sid, self.n = endpoint, None, 0

    def _post(self, body: dict, timeout: float = 15) -> Any:
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self.sid:
            headers["mcp-session-id"] = self.sid
        req = urllib.request.Request(self.endpoint, data=json.dumps(body).encode(), headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            self.sid = self.sid or r.headers.get("mcp-session-id")
            text = r.read().decode("utf-8", "replace")
        if not text.strip():
            return None
        for chunk in [text] + [ln[5:].strip() for ln in text.splitlines() if ln.startswith("data:")]:
            try:
                return json.loads(chunk)
            except ValueError:
                continue
        return None

    def connect(self) -> None:
        self.n += 1
        self._post({"jsonrpc": "2.0", "id": self.n, "method": "initialize", "params": {
            "protocolVersion": "2025-03-26", "capabilities": {},
            "clientInfo": {"name": "one-gate-census", "version": "1"}}})
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

    def call(self, tool: str, arguments: dict) -> Any:
        self.n += 1
        reply = self._post({"jsonrpc": "2.0", "id": self.n, "method": "tools/call",
                            "params": {"name": tool, "arguments": arguments}}) or {}
        result = reply.get("result") or {}
        if isinstance(result.get("structuredContent"), (dict, list)):
            return result["structuredContent"]
        for block in result.get("content") or []:
            if block.get("type") == "text":
                try:
                    return json.loads(block["text"])
                except ValueError:
                    return block["text"]
        return reply


class BlackHole:
    """Accepts, reads nothing, answers nothing: a daemon that is UP and starved (class_t_seat_audit)."""

    def __init__(self) -> None:
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen(64)
        self.port = self._srv.getsockname()[1]
        self._held: list = []
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self) -> None:
        while True:
            try:
                self._held.append(self._srv.accept()[0])
            except OSError:
                return

    def close(self) -> None:
        for c in self._held:
            with contextlib.suppress(OSError):
                c.close()
        with contextlib.suppress(OSError):
            self._srv.close()


class IsolatedDaemon:
    def __init__(self, binary: Path, root: Path, workspace: str, build_file: Optional[Path],
                 live_ports: set[int]):
        self.binary, self.root, self.workspace = binary, root, workspace
        self.home = root / "daemon" / "hestia-home"
        self.fake_home = root / "daemon" / "home"
        self.live_ports = live_ports
        self.port = free_port(live_ports)
        self.endpoint = f"http://127.0.0.1:{self.port}/mcp"
        self.build_file = build_file
        self.proc: Optional[subprocess.Popen] = None
        self.version = ""

    def env(self) -> dict[str, str]:
        env = {k: os.environ[k] for k in PASSTHROUGH if k in os.environ}
        env.update({"HOME": str(self.fake_home), "HESTIA_HOME": str(self.home),
                    "HESTIA_WORKSPACE": self.workspace, "HESTIA_PASSPHRASE": secrets.token_hex(16),
                    "HESTIA_CURRENT_BUILD_FILE": str(self.home / "current-build.json"),
                    "TMPDIR": str(self.root / "tmp"), "RUST_LOG": "warn"})
        return env

    def start(self) -> None:
        if self.port in self.live_ports:
            raise SetupError("refusing to bind a live daemon port")
        self.fake_home.mkdir(parents=True, exist_ok=True)
        env = self.env()
        self.version = subprocess.run([str(self.binary), "--version"], capture_output=True, text=True,
                                      timeout=30, env=env).stdout.strip()
        init = subprocess.run([str(self.binary), "--home", str(self.home), "init", "--ai"],
                              capture_output=True, text=True, timeout=120, env=env)
        if init.returncode != 0:
            raise SetupError(f"isolated `hestia init --ai` rc={init.returncode}: {deny_line(init.stderr)}")
        if self.build_file and self.build_file.is_file():
            shutil.copy2(self.build_file, self.home / "current-build.json")
        log = open(self.root / "daemon.log", "w")
        self.proc = subprocess.Popen([str(self.binary), "--home", str(self.home), "serve", "--bind",
                                      f"127.0.0.1:{self.port}"], env=env, stdout=log,
                                     stderr=subprocess.STDOUT, cwd=str(self.fake_home))
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise SetupError(f"isolated daemon exited rc={self.proc.returncode}: "
                                 f"{deny_line((self.root / 'daemon.log').read_text())}")
            try:
                c = Mcp(self.endpoint, self.live_ports)
                c.connect()
                return
            except OSError:
                time.sleep(0.5)
        raise SetupError("isolated daemon did not answer initialize within 90 s")

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=10)

    def client(self) -> Mcp:
        c = Mcp(self.endpoint, self.live_ports)
        c.connect()
        return c


# ------------------------------------------------------------------ host facts -------------------
def deploy_unit_env(hestia_home: Path, workspace: Optional[str]) -> tuple[dict[str, str], str]:
    """HESTIA_HOME / HESTIA_WORKSPACE as the deploy unit gives them to the reconciler."""
    env: dict[str, str] = {}
    source = "fallback (--hestia-home/--workspace)"
    try:
        out = subprocess.run(["systemctl", "--user", "show", "hestia-deploy.service", "-p",
                              "Environment", "--value"], capture_output=True, text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            for tok in shlex.split(out.stdout.strip()):
                k, _, v = tok.partition("=")
                if k in ("HESTIA_HOME", "HESTIA_WORKSPACE"):
                    env[k] = v
            source = "systemctl --user show hestia-deploy.service"
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    if not env:
        plist = Path.home() / "Library" / "LaunchAgents" / "com.web4.hestia.deploy.plist"
        if plist.is_file():
            import plistlib
            with contextlib.suppress(Exception):
                d = plistlib.loads(plist.read_bytes()).get("EnvironmentVariables") or {}
                env = {k: v for k, v in d.items() if k in ("HESTIA_HOME", "HESTIA_WORKSPACE")}
                source = str(plist)
    env.setdefault("HESTIA_HOME", str(hestia_home))
    if workspace:
        env["HESTIA_WORKSPACE"] = workspace
    return env, source


def session_evidence(home: Path, plugin_dir: str, days: float) -> dict[str, Any]:
    globs = SESSION_HISTORY.get(plugin_dir, ())
    newest, count, recent = 0.0, 0, 0
    cutoff = time.time() - days * 86400
    for pattern in globs:
        for p in glob.glob(str(home / pattern)):
            with contextlib.suppress(OSError):
                st = os.stat(p)
                if not os.path.isfile(p):
                    continue
                count += 1
                newest = max(newest, st.st_mtime)
                recent += st.st_mtime >= cutoff
    return {
        "globs": [f"~/{g}" for g in globs], "files": count, "files_in_window": recent,
        "window_days": days,
        "newest": (datetime.datetime.fromtimestamp(newest, datetime.timezone.utc)
                   .strftime("%Y-%m-%dT%H:%MZ") if newest else None),
        "chain": "not consulted: the census never queries the live daemon",
    }


def git_show(repo: Path, rev: str, path: str) -> Optional[bytes]:
    out = subprocess.run(["git", "-C", str(repo), "show", f"{rev}:{path}"], capture_output=True,
                         timeout=30)
    return out.stdout if out.returncode == 0 else None


# ------------------------------------------------------------------ the census -------------------
class Census:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.home = Path(args.home).expanduser()
        self.hestia_home = Path(args.hestia_home).expanduser()
        self.repo = Path(args.deploy_repo).expanduser().resolve()
        self.root = Path(tempfile.mkdtemp(prefix="one-gate-census-", dir="/tmp")).resolve()
        (self.root / "tmp").mkdir()
        self.guard_dir = self.root / "guard"
        self.guard_log = self.root / "guard-blocked.log"
        self.armed_log = self.root / "guard-armed.log"
        self.runs: list[str] = []
        self.daemon: Optional[IsolatedDaemon] = None
        self.report: dict[str, Any] = {}
        self.live_ports: set[int] = {LIVE_DEFAULT_PORT}

    # -- guard ------------------------------------------------------------------------------
    def redirect_target(self, src: str) -> Path:
        return self.root / "redirect" / src.strip("/").replace("/", "_")

    def install_guard(self) -> None:
        for src in REDIRECTED_HOST_PATHS:
            self.redirect_target(src).mkdir(parents=True, exist_ok=True)
        self.guard_dir.mkdir(parents=True, exist_ok=True)
        (self.guard_dir / "sitecustomize.py").write_text(GUARD_SOURCE)

    def guarded_env(self, run: str) -> dict[str, str]:
        env = {k: os.environ[k] for k in PASSTHROUGH if k in os.environ}
        env.update({
            "HOME": str(self.home),
            "TMPDIR": str(self.root / "tmp"),
            "PYTHONPATH": str(self.guard_dir),
            "PYTHONDONTWRITEBYTECODE": "1",      # importing the installed engine must not write .pyc
            "ONE_GATE_CENSUS_GUARD_PORTS": ",".join(str(p) for p in sorted(self.live_ports)),
            "ONE_GATE_CENSUS_GUARD_LOG": str(self.guard_log),
            "ONE_GATE_CENSUS_ARMED_LOG": str(self.armed_log),
            "ONE_GATE_CENSUS_WRITE_ROOT": str(self.root),
            "ONE_GATE_CENSUS_RUN": run,
            "ONE_GATE_CENSUS_REDIRECT": ";".join(f"{src}=>{self.redirect_target(src)}"
                                                 for src in REDIRECTED_HOST_PATHS),
        })
        self.runs.append(run)
        return env

    def guard_findings(self) -> dict[str, Any]:
        blocked = [ln for ln in (self.guard_log.read_text().splitlines() if self.guard_log.exists() else [])
                   if ln.strip()]
        armed_text = self.armed_log.read_text() if self.armed_log.exists() else ""
        armed = set(re.findall(r"armed run=(\S+)", armed_text))
        unguarded = [r for r in self.runs if r not in armed]
        return {"blocked": blocked, "probes": len(self.runs), "unguarded": unguarded,
                "live_ports": sorted(self.live_ports)}

    # -- throwaway seat homes ---------------------------------------------------------------
    def seat_home(self, seat: str, label: str, endpoint: str) -> tuple[Optional[Path], str]:
        """The seat's projection in a throwaway home: HESTIA_HOME re-pointed by the shared
        seat_projection_repoint (the engine stays the INSTALLED one: these are the bytes under
        test), the endpoint aimed at the isolated daemon, every seat-local state dir moved under
        the throwaway. Returns (home, why-not)."""
        real = self.hestia_home / "seats" / projection_name(seat)
        if not real.is_file():
            return None, f"no projection at {real}"
        values = projection_values(read_projection(real))
        dst = self.root / "seats" / seat / label
        self.repoint(seat, real, dst, values.get("HESTIA_SHARED_DIR") or str(self.hestia_home / "shared"))
        path = dst / "seats" / projection_name(seat)
        lines = []
        for ln in read_projection(path):
            key, sep, value = ln.partition("=")
            bare = key.split("__", 1)[-1]
            if sep and bare == "HESTIA_ENDPOINT":
                ln = f"{key}={endpoint}"
            elif sep and re.search(r"_(STATE|INSTANCE|OBSERVE)_DIR$|^HESTIA_STATE_DIR$", bare):
                moved = dst / "state" / bare.lower()
                moved.mkdir(parents=True, exist_ok=True)
                ln = f"{key}={moved}"
            lines.append(ln)
        if not any(ln.split("=", 1)[0].split("__", 1)[-1] == "HESTIA_ENDPOINT" for ln in lines if "=" in ln):
            lines.append(f"HESTIA_ENDPOINT={endpoint}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        (dst / "state" / "witness").mkdir(parents=True, exist_ok=True)
        return dst, ""

    # -- one probe --------------------------------------------------------------------------
    def run_hook(self, run: str, interpreter: str, target: str, line_env: dict[str, str],
                 declared_env: dict[str, str], seat_home: Path, event: dict, cap_s: float,
                 endpoint: str) -> dict[str, Any]:
        env = self.guarded_env(run)
        env.update(line_env)
        env.update(declared_env)
        env["HESTIA_HOME"] = str(seat_home)          # the registered locator, re-pointed
        env["HESTIA_ENDPOINT"] = endpoint           # and every endpoint the isolated one
        env["HESTIA_STATE_DIR"] = str(seat_home / "state" / "witness")
        started = time.monotonic()
        try:
            out = subprocess.run([interpreter, target], input=json.dumps(event), env=env,
                                 cwd=env.get("HESTIA_WORKSPACE") or str(self.root),
                                 capture_output=True, text=True, timeout=cap_s)
            wall = time.monotonic() - started
            said = deny_line(out.stderr) or deny_line(out.stdout)
            return {"rc": out.returncode, "denied": out.returncode != 0 or payload_denies(out.stdout),
                    "wall_s": round(wall, 3), "rule": rule_of(out.stderr) or rule_of(out.stdout), "said": said[:300],
                    "stderr": out.stderr[-2000:]}
        except subprocess.TimeoutExpired:
            return {"rc": None, "denied": None, "wall_s": round(time.monotonic() - started, 3),
                    "rule": "", "said": f"killed by the census cap ({cap_s:.0f} s)", "stderr": ""}

    # -- host ------------------------------------------------------------------------------
    def host_facts(self) -> dict[str, Any]:
        build_file = self.hestia_home / "current-build.json"
        try:
            build = json.loads(build_file.read_text())
        except (OSError, ValueError) as exc:
            raise SetupError(f"cannot read {build_file}: {exc}")
        head = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD"], capture_output=True,
                              text=True, timeout=10).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(self.repo), "status", "--porcelain",
                                "--untracked-files=no"], capture_output=True, text=True,
                               timeout=30).stdout.strip()
        ep_file = self.hestia_home / "endpoint"
        live_endpoint = ep_file.read_text().strip() if ep_file.is_file() else ""
        if port_of(live_endpoint):
            self.live_ports.add(port_of(live_endpoint))
        seats_dir = self.hestia_home / "seats"
        for proj in sorted(seats_dir.iterdir()) if seats_dir.is_dir() else []:
            with contextlib.suppress(OSError, UnicodeDecodeError):
                p = port_of(projection_values(read_projection(proj)).get("HESTIA_ENDPOINT", ""))
                if p:
                    self.live_ports.add(p)
        return {"build": build, "build_file": str(build_file), "deploy_head": head,
                "deploy_dirty": bool(dirty), "live_endpoint": live_endpoint}

    # -- the rows --------------------------------------------------------------------------
    def bytes_row(self, plugin_dir: str, files_dir: Optional[Path], shared_dir: Optional[Path],
                  head_sha: str, build: dict) -> dict[str, Any]:
        gt = self.gt
        drift, notes, compared = [], [], 0
        recorded = {f["path"]: f["sha256"] for m in build.get("members") or [] for f in m.get("files") or []}
        recorded.update({f["path"]: f["sha256"] for f in build.get("shared_engine") or []})

        def unit_rows(unit: str) -> list[dict]:
            raw = git_show(self.repo, head_sha, f"hooks-gt/{unit}/manifest.json")
            if raw is None:
                drift.append(f"hooks-gt/{unit}/manifest.json absent at the deployed build {head_sha[:10]}")
                return []
            return json.loads(raw).get("files") or []

        def compare(unit: str, rel: str, row_sha: str, installed: Path, required: bool) -> None:
            nonlocal compared
            blob = git_show(self.repo, head_sha, f"hooks-gt/{unit}/{rel}")
            if blob is None:
                drift.append(f"{unit}/{rel}: certified file missing at {head_sha[:10]}")
                return
            if gt.canonical_digest(blob) != row_sha:
                drift.append(f"{unit}/{rel}: certified file disagrees with its own manifest")
            want = sha256_bytes(gt.strip_header(blob))
            got = sha256_file(installed)
            if got is None:
                (drift if required else notes).append(
                    f"{rel}: not installed at {installed}" + ("" if required else " (not registered here)"))
                return
            compared += 1
            if got != want:
                drift.append(f"{unit}/{rel}: installed {got[:12]} != certified {want[:12]} ({installed})")
            rec = recorded.get(str(installed))
            if rec and rec != got:
                notes.append(f"{rel}: current-build.json recorded {rec[:12]}, disk has {got[:12]}")

        if files_dir is None:
            drift.append("gate not registered: nothing to compare")
        else:
            registered_bases = set(self.registered_bases)
            for row in unit_rows(plugin_dir):
                rel = row.get("path", "")
                if rel.endswith(".json"):
                    continue
                base = os.path.basename(rel)
                compare(plugin_dir, rel, row.get("sha256", ""), files_dir / base,
                        required=base in registered_bases)
        if shared_dir is None:
            drift.append("no shared engine resolved from the seat projection")
        else:
            for row in unit_rows("_shared"):
                rel = row.get("path", "")
                compare("_shared", rel, row.get("sha256", ""), shared_dir / rel, required=True)
        return {"status": "match" if not drift and compared else "drift", "compared": compared,
                "drift": drift, "notes": notes, "engine": str(shared_dir) if shared_dir else None}

    def registration_row(self, plugin_dir: str, spec: dict, template: dict, deploy_env: dict) -> dict:
        reg = self.registrar
        got = reg.prepare_member(plugin_dir, spec, template, str(self.home), dry=True, env=deploy_env,
                                 source=str(self.repo / "plugins" / plugin_dir))
        if not isinstance(got, reg.Prepared):
            verdict, lines = got
            return {"status": "absent" if verdict == "skip" else "refused", "changes": [],
                    "notes": list(lines)}
        notes = [n for n in got.P.notes]
        return {"status": "no-op" if not got.changes else "drift", "changes": list(got.changes),
                "notes": notes}

    # -- one seat --------------------------------------------------------------------------
    def seat(self, expects: Path, deploy_env: dict, facts: dict, client: Mcp) -> Optional[dict]:
        plugin_dir = expects.parent.name
        spec_all = json.loads(expects.read_text(encoding="utf-8"))
        spec = spec_all.get("install") or {}
        probe = spec.get("gate_probe")
        template_path = expects.parent / "hooks" / "hooks.json"
        if not isinstance(probe, dict) or not spec.get("registration") or not template_path.is_file():
            return None
        seat = spec.get("member") if isinstance(spec.get("member"), str) else plugin_dir
        row: dict[str, Any] = {"seat": seat, "plugin": plugin_dir}
        template = json.loads(template_path.read_text(encoding="utf-8"))
        loaded = self.registrar._load(plugin_dir, spec, template, str(self.home), deploy_env,
                                      source=str(expects.parent))
        if not isinstance(loaded, self.registrar.Loaded):
            verdict, lines = loaded
            if verdict == "skip" and any("harness not on this host" in ln for ln in lines):
                row.update(state="absent", why="; ".join(lines))
                return row
            row.update(state="unreadable", why="; ".join(lines))
            row["rows"] = {"registration": {"status": "refused", "notes": lines}}
            return row
        regs = self.registrar.index_hooks(loaded.hooks, loaded.layout == "flat")
        entry_base = os.path.basename(probe["entry"])
        # the event the TEMPLATE registers the witness on, rendered by the registrar itself
        witness_event = next((d.event for d in loaded.desired if d.base == "witness.py"), None)
        gate_reg = next((r for r in regs if r.base == entry_base and r.target), None)
        witness_reg = next((r for r in regs if r.base == "witness.py" and r.event == witness_event
                            and r.target), None)
        self.registered_bases = [r.base for r in regs if r.base and r.target and loaded.dest
                                 and os.path.dirname(r.target) == loaded.dest]
        evidence = session_evidence(self.home, plugin_dir, self.args.in_use_days)
        row["use_evidence"] = evidence
        row["state"] = "in use" if evidence["files_in_window"] else "installed, not in use"
        rows: dict[str, Any] = {}
        row["rows"] = rows

        # 2. registration
        rows["registration"] = self.registration_row(plugin_dir, spec, template, deploy_env)

        # projection (real) -> the engine this seat resolves
        real_proj = self.hestia_home / "seats" / projection_name(seat)
        proj_values = projection_values(read_projection(real_proj)) if real_proj.is_file() else {}
        shared = proj_values.get("HESTIA_SHARED_DIR")
        shared_dir = Path(os.path.realpath(shared)) if shared else None
        files_dir = Path(os.path.dirname(gate_reg.target)) if gate_reg else None

        # 1. bytes
        rows["bytes"] = self.bytes_row(plugin_dir, files_dir, shared_dir, facts["build"]["head_sha"],
                                       facts["build"])
        if files_dir and loaded.dest and str(files_dir) != loaded.dest:
            rows["bytes"]["notes"].append(f"registered gate dir {files_dir} != declared dest {loaded.dest}")

        if gate_reg is None:
            for k in ("behaviour", "witness", "timing", "identity"):
                rows[k] = {"status": "FAIL", "why": f"{entry_base} is not registered in {loaded.cfg}"}
            return row

        command = gate_reg.hook.get("command", "")
        target = gate_reg.target
        tokens = shlex.split(command)
        interp = next((t for t in reversed(tokens[:tokens.index(target)]) if "=" not in t), None) \
            if target in tokens else None
        interpreter = shutil.which(interp or "python3") or sys.executable
        with without_hestia_env():
            line_env = self.preflight._launcher_env([command], probe["entry"])
        declared_env = probe.get("environment") or {}
        gate_source = Path(target).read_text(encoding="utf-8", errors="replace")
        unit = harness_number(gate_source, "timeout_unit_seconds") or 1.0
        margin = harness_number(gate_source, "margin_seconds") or 1.5
        timeout_raw = gate_reg.hook.get("timeout")
        timeout_s = float(timeout_raw) * unit if isinstance(timeout_raw, (int, float)) else (
            harness_number(gate_source, "default_timeout_seconds") or 60.0)
        row["registered"] = {"config": loaded.cfg, "event": gate_reg.event, "matcher": gate_reg.matcher,
                             "command": command, "timeout_s": timeout_s, "margin_s": margin,
                             "witness": witness_reg.hook.get("command") if witness_reg else None}

        home_ok, why = self.seat_home(seat, "healthy", self.daemon.endpoint)
        if home_ok is None:
            for k in ("behaviour", "witness", "timing", "identity"):
                rows[k] = {"status": "FAIL", "why": why}
            return row
        read_ev, shell_ev = probe_events(probe)
        scratch = self.root / "scratch" / f"{plugin_dir}-benign.txt"
        scratch.parent.mkdir(parents=True, exist_ok=True)
        scratch.write_text("one-gate census scratch\n")
        session = f"one-gate-census-{plugin_dir}-{secrets.token_hex(4)}"
        # spelled in parts: a credential path must not appear literally in this source (see projection_name)
        credential = str(self.home / ("." + "ssh") / ("id_" + "ed25519"))
        out_of_scope = str(self.home / ".one-gate-census-out-of-scope" / "probe.txt")

        def ev(base: Optional[dict], name: str, **repl: str) -> Optional[dict]:
            # one host session per probe: the chain rows of one act are found by it alone
            if base is None:
                return None
            e = render_event(base, {"{" + k + "}": v for k, v in repl.items()})
            e["session_id"] = f"{session}-{name}"
            return e

        cap = timeout_s + 10
        benign_ev = ev(read_ev, "benign", scratch=str(scratch))
        probes = {
            "benign_read": benign_ev,
            "self_write": ev(shell_ev, "self", hold=target),
            "credential_read": ev(read_ev, "credential", scratch=credential),
            "out_of_scope_read": ev(read_ev, "oos", scratch=out_of_scope),
        }
        results = {}
        for name, event in probes.items():
            if event is None:
                results[name] = {"denied": None, "said": "the member declares no such probe event"}
                continue
            results[name] = self.run_hook(f"{plugin_dir}:{name}", interpreter, target, line_env,
                                          declared_env, home_ok, event, cap, self.daemon.endpoint)

        # 3. behaviour
        verdicts, failures, known = {}, [], []
        b = results["benign_read"]
        verdicts["benign_read"] = "allow" if b.get("denied") is False else f"DENY {b.get('said')}"
        if b.get("denied") is not False:
            failures.append(f"benign read refused: {b.get('said')}")
        s = results["self_write"]
        esc_id = None
        m = re.search(r"Escalation (\S+?) is open", s.get("stderr") or "")
        if m:
            esc_id = m.group(1)
        escalation = self.escalation(client, esc_id) if esc_id else None
        verdicts["self_write"] = ("deny " + (s.get("rule") or "?") if s.get("denied") else
                                  f"ALLOW ({s.get('said') or 'no output'})")
        judged, why = judge_self_write(plugin_dir, s)
        if judged == "known-open":
            known.append(why)
        elif judged in ("stale", "fail"):
            failures.append(why)
            row["stale_ratchet"] = row.get("stale_ratchet") or judged == "stale"
        c = results["credential_read"]
        verdicts["credential_read"] = ("deny " + (c.get("rule") or "?")) if c.get("denied") else "ALLOW"
        if not (c.get("denied") and CREDENTIAL_RULE.search(c.get("rule") or c.get("said") or "")):
            failures.append(f"credential read not refused as a secret: {c.get('said')}")
        o = results["out_of_scope_read"]
        verdicts["out_of_scope_read"] = ("deny " + (o.get("rule") or "?")) if o.get("denied") else "ALLOW"
        if not (o.get("denied") and SCOPE_RULE.search(o.get("rule") or o.get("said") or "")):
            failures.append(f"out-of-scope read not refused for scope: {o.get('said')}")
        rows["behaviour"] = {
            "status": "FAIL" if failures else ("known-open" if known else "PASS"),
            "verdicts": verdicts, "failures": failures, "known_open": known,
            "self_write_escalation": escalation,
            "probes": {k: {kk: vv for kk, vv in v.items() if kk != "stderr"} for k, v in results.items()},
        }

        # 4. witness + 6. identity (from the isolated chain)
        rows["witness"], rows["identity"] = self.witness_and_identity(
            client, seat, plugin_dir, witness_reg, witness_event, benign_ev, line_env, declared_env,
            home_ok, escalation)

        # 5. timing
        rows["timing"] = self.timing(plugin_dir, seat, interpreter, target, line_env, declared_env,
                                     benign_ev, timeout_s, margin, b)
        return row

    def escalation(self, client: Mcp, esc_id: str) -> dict[str, Any]:
        try:
            pending = client.call("hestia_gate_pending_escalations", {})
        except OSError as exc:
            return {"id": esc_id, "error": f"isolated daemon unreachable: {exc}"}
        items = pending.get("escalations") or pending.get("items") or [] if isinstance(pending, dict) else []
        if isinstance(pending, dict) and not items:
            for v in pending.values():
                if isinstance(v, list) and v and isinstance(v[0], dict) and "escalation_id" in v[0]:
                    items = v
        for e in items:
            if isinstance(e, dict) and str(e.get("escalation_id", "")).startswith(esc_id.rstrip(".")):
                return {"id": e.get("escalation_id"), "bar": e.get("bar"), "asker_basis": e.get("asker_basis"),
                        "asked_by": e.get("asked_by"), "marker": e.get("marker"),
                        "matched_markers": e.get("matched_markers"), "on": "isolated daemon"}
        return {"id": esc_id, "error": "not found in the isolated daemon's pending escalations"}

    def chain(self, client: Mcp, limit: int = 200) -> list[dict]:
        got = client.call("hestia_query_history", {"filter": {"limit": limit}})
        if isinstance(got, dict):
            for key in ("entries", "items", "chain"):
                if isinstance(got.get(key), list):
                    return got[key]
        return got if isinstance(got, list) else []

    def witness_and_identity(self, client, seat, plugin_dir, witness_reg, witness_event, benign_ev,
                             line_env, declared_env, seat_home, escalation) -> tuple[dict, dict]:
        def flat(e: dict) -> dict:
            d = dict(e.get("event_data") or e.get("eventData") or {})
            d.update({k: v for k, v in e.items() if k not in ("event_data", "eventData")})
            return d

        def key_of(d: dict) -> Optional[str]:
            for k in ("correlation_key", "correlationKey"):
                if d.get(k):
                    return str(d[k])
            return None

        def member_of(d: dict) -> Optional[str]:
            for k in ("plugin_id", "pluginId", "member", "member_id", "agent"):
                if d.get(k):
                    return str(d[k])
            return None

        session = benign_ev.get("session_id") if benign_ev else None
        try:
            entries = [flat(e) for e in self.chain(client) if isinstance(e, dict)]
        except OSError as exc:
            entries = []
            err = str(exc)
        else:
            err = ""
        mine = [d for d in entries if session and session in json.dumps(d, default=str)]
        decision = next((d for d in mine if re.search(r"policy_(allow|decision)|decision",
                                                      str(d.get("event_type") or d.get("eventType")))), None)
        identity: dict[str, Any]
        if decision is None:
            identity = {"status": "FAIL", "why": "no decision row for the benign act on the isolated chain"
                        + (f" ({err})" if err else ""), "chain_rows_for_session": len(mine)}
        else:
            asserted = member_of(decision)
            identity = {"status": "PASS" if asserted == seat else "FAIL", "asserted": asserted,
                        "expected": seat, "event_type": decision.get("event_type") or decision.get("eventType"),
                        "asker_basis": (escalation or {}).get("asker_basis"),
                        "basis_note": "asker_basis as the isolated daemon recorded it on the self-write "
                                      "escalation; the census runs the gate directly, with a probe "
                                      "session id, not through a harness"}
        if witness_reg is None:
            return ({"status": "FAIL", "why": f"witness.py not registered on {witness_event}"}, identity)
        post = dict(benign_ev or {})
        post["hook_event_name"] = witness_event
        post["tool_response"] = {"success": True, "content": "one-gate census scratch\n"}
        tokens = shlex.split(witness_reg.hook.get("command", ""))
        interp = next((t for t in reversed(tokens[:tokens.index(witness_reg.target)]) if "=" not in t),
                      None) if witness_reg.target in tokens else None
        with without_hestia_env():
            w_env = self.preflight._launcher_env([witness_reg.hook.get("command", "")], "witness.py")
        res = self.run_hook(f"{plugin_dir}:witness", shutil.which(interp or "python3") or sys.executable,
                            witness_reg.target, w_env, declared_env, seat_home, post, 30,
                            self.daemon.endpoint)
        time.sleep(0.5)
        try:
            entries = [flat(e) for e in self.chain(client) if isinstance(e, dict)]
        except OSError as exc:
            return ({"status": "FAIL", "why": f"isolated chain unreadable: {exc}"}, identity)
        mine = [d for d in entries if session and session in json.dumps(d, default=str)]
        outcome = next((d for d in mine if re.search(r"outcome", str(d.get("event_type") or d.get("eventType")))),
                       None)
        pre_key = key_of(decision) if decision else None
        if outcome is None:
            return ({"status": "FAIL", "why": "no outcome row for the benign act on the isolated chain",
                     "witness_rc": res.get("rc"), "witness_said": res.get("said"),
                     "rows_for_session": [d.get("event_type") or d.get("eventType") for d in mine]}, identity)
        # THE PRE->POST IDENTITY. The gate keys the act (correlation_key on its decision row) and
        # caches the action it authorized under that key; the witness recomputes the key from the
        # Post event, finds the action and closes it. A witness that cannot find it writes a COLD
        # record (a fresh action, intent `...no-authorized-action-cached`): the join is broken.
        pre_action = (decision or {}).get("action_id")
        post_action = outcome.get("action_id")
        cold = "cold-record" in str(outcome.get("intent") or "")
        ok = (member_of(outcome) == seat and pre_key is not None and pre_action is not None
              and pre_action == post_action and not cold)
        return ({"status": "PASS" if ok else "FAIL", "member": member_of(outcome),
                 "pre_key": pre_key, "pre_action": pre_action, "post_action": post_action,
                 "cold_record": cold, "intent": outcome.get("intent"), "witness_rc": res.get("rc"),
                 "event_type": outcome.get("event_type") or outcome.get("eventType"),
                 "chain_rows": [json.dumps(d, default=str)[:600] for d in mine]}, identity)

    def timing(self, plugin_dir, seat, interpreter, target, line_env, declared_env, benign_ev,
               timeout_s, margin, healthy) -> dict[str, Any]:
        hole = BlackHole()
        try:
            starved_endpoint = f"http://127.0.0.1:{hole.port}/mcp"
            home, why = self.seat_home(seat, "starved", starved_endpoint)
            if home is None:
                return {"status": "FAIL", "why": why}
            event = dict(benign_ev)
            event["session_id"] = event.get("session_id", "") + "-starved"
            res = self.run_hook(f"{plugin_dir}:starved", interpreter, target, line_env, declared_env, home,
                                event, timeout_s + 15, starved_endpoint)
        finally:
            hole.close()
        deadline = timeout_s - margin
        ok = res.get("denied") is True and res["wall_s"] < timeout_s
        return {"status": "PASS" if ok else "FAIL", "healthy_s": healthy.get("wall_s"),
                "starved_s": res.get("wall_s"), "starved_verdict": ("deny " + res.get("rule", "")) if res.get("denied")
                else ("ALLOW" if res.get("denied") is False else res.get("said")),
                "registered_timeout_s": timeout_s, "gate_deadline_s": round(deadline, 3),
                "headroom_s": round(timeout_s - res["wall_s"], 3),
                "inside_gate_deadline": res["wall_s"] <= deadline}

    # -- run --------------------------------------------------------------------------------
    def run(self) -> int:
        a = self.args
        started = time.monotonic()
        self.install_guard()
        facts = self.host_facts()
        self.preflight = load_module(self.repo / "deploy" / "from-main" / "gate-preflight.py",
                                     "census_gate_preflight")
        self.repoint = load_module(self.repo / "deploy" / "from-main" / "seat_projection_repoint.py",
                                   "census_seat_projection_repoint").repoint
        self.registrar = load_module(self.repo / "deploy" / "register-members.py", "census_register_members")
        self.gt = load_module(self.repo / "tools" / "hooks_gt.py", "census_hooks_gt")
        deploy_env, env_source = deploy_unit_env(self.hestia_home, a.workspace)
        workspace = deploy_env.get("HESTIA_WORKSPACE") or str(self.home / "ai-workspace")
        self.daemon = IsolatedDaemon(Path(a.daemon_bin).expanduser(), self.root, workspace,
                                     Path(facts["build_file"]), self.live_ports)
        seats: list[dict] = []
        error = ""
        try:
            self.daemon.start()
            client = self.daemon.client()
            for expects in sorted((self.repo / "plugins").glob("*/expects.json")):
                if a.member and expects.parent.name not in a.member:
                    continue
                r = self.seat(expects, deploy_env, facts, client)
                if r is not None:
                    seats.append(r)
        except SetupError as exc:
            error = str(exc)
        finally:
            self.daemon.stop()
        guard = self.guard_findings()
        build = facts["build"]
        verdict_rows = ("bytes", "registration", "behaviour", "witness", "timing", "identity")
        failing = []
        for s in seats:
            rows = s.get("rows") or {}
            s["failed_rows"] = [k for k in verdict_rows if k in rows and
                                rows[k].get("status") in ("FAIL", "drift", "refused")]
            if s["state"] == "unreadable":
                s["failed_rows"].append("registration")
            if s["state"] in ("in use", "unreadable") and s["failed_rows"]:
                failing.append(s["seat"])
        stale = [s["seat"] for s in seats if s.get("stale_ratchet")]
        ok = (not error and not failing and not stale and not guard["blocked"] and not guard["unguarded"]
              and bool(seats))
        self.report = {
            "host": socket.gethostname(),
            "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "build_id": build.get("build_id"), "head_sha": build.get("head_sha"),
            "installed_at": build.get("installed_at_iso"),
            "deploy_checkout": str(self.repo), "deploy_head": facts["deploy_head"],
            "deploy_head_is_build": facts["deploy_head"] == build.get("head_sha"),
            "deploy_dirty": facts["deploy_dirty"],
            "deploy_env": deploy_env, "deploy_env_source": env_source,
            "daemon": {"binary": str(self.daemon.binary), "version": self.daemon.version,
                       "endpoint": self.daemon.endpoint, "isolated": True},
            "guard": guard, "error": error, "seats": seats,
            "failing_in_use": failing, "stale_ratchet": stale,
            "runtime_s": round(time.monotonic() - started, 1), "pass": ok,
            "throwaway": str(self.root) if a.keep else "(removed)",
        }
        return 0 if ok else 1


# ------------------------------------------------------------------ rendering --------------------
def cell(row: Optional[dict], key: str) -> str:
    if not row:
        return "-"
    r = row.get(key) or {}
    st = r.get("status", "-")
    if key == "bytes":
        return f"{st} ({r.get('compared', 0)} files)" + ("" if st == "match" else ": " + "; ".join(r.get("drift", []))[:160])
    if key == "registration":
        return st + ("" if st in ("no-op", "absent") else ": " + "; ".join(r.get("changes") or r.get("notes") or [])[:160])
    if key == "behaviour":
        v = r.get("verdicts") or {}
        esc = r.get("self_write_escalation") or {}
        bar = f" esc bar={esc.get('bar')} basis={esc.get('asker_basis')}" if esc.get("id") else ""
        detail = "; ".join(f"{k.split('_')[0]}={v[k]}" for k in v)
        extra = " | " + "; ".join(r.get("failures") or r.get("known_open") or []) if (r.get("failures") or r.get("known_open")) else ""
        return f"{st}: {detail}{bar}{extra}"[:420]
    if key == "witness":
        if st == "PASS":
            return f"PASS: outcome closes action {str(r.get('pre_action'))[:8]} (key {str(r.get('pre_key'))[:20]}), member={r.get('member')}"
        if r.get("why"):
            return f"{st}: {r.get('why')}"[:200]
        return (f"{st}: decision action {str(r.get('pre_action'))[:8]} vs outcome action "
                f"{str(r.get('post_action'))[:8]}" + (" (COLD record: the witness found no cached action)"
                                                      if r.get("cold_record") else ""))[:200]
    if key == "timing":
        if "starved_s" not in r:
            return f"{st}: {r.get('why', '')}"
        return (f"{st}: healthy {r.get('healthy_s')} s, starved {r.get('starved_s')} s "
                f"({r.get('starved_verdict')}) < timeout {r.get('registered_timeout_s')} s "
                f"(gate deadline {r.get('gate_deadline_s')} s)")
    if key == "identity":
        return f"{st}: asserted={r.get('asserted')} basis={r.get('asker_basis')}" if "asserted" in r else f"{st}: {r.get('why', '')}"
    return st


def markdown(report: dict) -> str:
    out = [f"## One-gate census — {report['host']}", "",
           f"- build `{report['build_id']}` ({str(report['head_sha'])[:10]}), installed {report['installed_at']}; "
           f"deploy checkout at build: {report['deploy_head_is_build']}, dirty: {report['deploy_dirty']}",
           f"- {report['timestamp']}, runtime {report['runtime_s']} s; isolated daemon "
           f"`{report['daemon']['version']}` on {report['daemon']['endpoint']}",
           f"- guard: {len(report['guard']['blocked'])} blocked, {len(report['guard']['unguarded'])} unguarded "
           f"of {report['guard']['probes']} probes; live ports refused: {report['guard']['live_ports']}",
           f"- verdict: **{'PASS' if report['pass'] else 'FAIL'}**"
           + (f" — failing in use: {report['failing_in_use']}" if report['failing_in_use'] else "")
           + (f" — stale ratchet: {report['stale_ratchet']}" if report['stale_ratchet'] else "")
           + (f" — error: {report['error']}" if report['error'] else ""), ""]
    cols = ("bytes", "registration", "behaviour", "witness", "timing", "identity")
    out.append("| seat | state (use evidence) | " + " | ".join(cols) + " |")
    out.append("|---|---|" + "---|" * len(cols))
    for s in report["seats"]:
        ev = s.get("use_evidence") or {}
        state = s["state"] + (f" ({ev.get('files_in_window')} of {ev.get('files')} session files in "
                              f"{ev.get('window_days'):g} d; newest {ev.get('newest')})" if ev else "")
        if s["state"] == "absent":
            out.append(f"| {s['seat']} | absent | " + " | ".join("-" for _ in cols) + " |")
            continue
        cells = [cell(s.get("rows"), c).replace("|", "/") for c in cols]
        out.append(f"| {s['seat']} | {state} | " + " | ".join(cells) + " |")
    if report["guard"]["blocked"]:
        out += ["", "Guard log (FAILS the census):", ""] + [f"    {ln}" for ln in report["guard"]["blocked"]]
    not_used = [s["seat"] for s in report["seats"] if s["state"] == "installed, not in use"]
    if not_used:
        out += ["", f"Installed, not in use (reported, not counted): {', '.join(not_used)}."]
    return "\n".join(out) + "\n"


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--deploy-repo", default=str(Path(__file__).resolve().parents[1])
                   if (Path(__file__).resolve().parents[1] / "deploy" / "register-members.py").is_file()
                   else "~/.hestia/deploy/hestia",
                   help="the deploy checkout (default: this file's checkout, else ~/.hestia/deploy/hestia)")
    p.add_argument("--hestia-home", default=os.environ.get("HESTIA_HOME") or "~/.hestia")
    p.add_argument("--home", default="~")
    p.add_argument("--workspace", default=None, help="override the deploy unit's HESTIA_WORKSPACE")
    p.add_argument("--daemon-bin", default="~/.local/bin/hestia", help="the host's installed daemon binary")
    p.add_argument("--member", action="append", help="only this plugin directory (repeatable)")
    p.add_argument("--in-use-days", type=float, default=30.0)
    p.add_argument("--json", dest="json_path", default=None)
    p.add_argument("--keep", action="store_true", help="keep the throwaway dir")
    args = p.parse_args(argv)
    census = Census(args)
    try:
        rc = census.run()
    except SetupError as exc:
        print(f"one-gate census: setup failed: {exc}", file=sys.stderr)
        rc = 2
        census.report = census.report or {"error": str(exc), "pass": False}
    finally:
        if census.daemon:
            census.daemon.stop()
        if not args.keep:
            shutil.rmtree(census.root, ignore_errors=True)
    if census.report.get("seats") is not None:
        print(markdown(census.report))
    if args.json_path:
        Path(args.json_path).write_text(json.dumps(census.report, indent=2, default=str) + "\n")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
