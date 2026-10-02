#!/usr/bin/env python3
"""Four-harness gate parity runner — the acceptance fence for the one-gate consolidation.

Measures TODAY's per-seat verdicts over `tools/gate_parity_corpus.py` so the converged gate
can later be diffed against them. Each act is rendered into each harness's NATIVE hook event
JSON and fed to that seat's real shim as a subprocess (`python3 <shim>`, event on stdin),
so the measured path is the shim's full normalize -> evaluate -> emit, not an imported
function (cross_harness_closure_test imports; this runner deliberately does not).

THE DAEMON IS A STUB, and that is the point. Every shim consults the policy daemon over
MCP-over-HTTP (JSON-RPC, optionally SSE-framed; see hestia_gate_mechanism._McpHttp). Running
96 probes against the live daemon would mint witness entries into the real chain, so this
runner stands up an in-process stub (stdlib http.server, ephemeral loopback port) that
answers the full handshake — initialize, notifications/initialized, hestia_connect,
hestia_begin_action, hestia_query_policy, hestia_operating_law, hestia_scope_status,
hestia_gate_escalation_claim, hestia_request_witness, hestia_witness_decision — with a
NEUTRAL policy layer: every policy query decides `allow` (no opinion), every witness/claim
gets a deterministic fake hash, every escalation claim is refused-with-escalation-opened.
What is measured is therefore each shim's LOCAL decision surface (closure classification,
scope/egress law, degraded posture, emit contract) with the daemon layer present but
neutralized. Consequences, stated so the table is read honestly:

  * Rows whose expected verdict is produced DAEMON-SIDE (the destructive preset — e.g.
    `cd X && rm -rf out`) measure `allow` on every seat here and flag as
    expected-mismatches. That is a stub limitation, not four gate bugs.
  * `degraded` marks a fail-closed-NO-VERDICT cell (config.unbacked, no-shared-authority,
    [fail-closed], [degraded], a crash, a timeout). The stub is built so these are rare;
    a whole degraded seat means the harness is broken, not the seat.

Scope layout: HESTIA_WORKSPACE is the repo's PARENT (the fleet layout the launch-cwd grant
is defined against — "the repo the member is launched in is always in scope"), and each shim
runs with cwd = the repo, so the launch-cwd bridge grants exactly this checkout, per seat.
`{HOME}` renders to a FIXED NONEXISTENT absolute path (/home/gate-parity-probe): the acts
that name it (.env, .ssh, settings.json, a home dotfile) must classify by TEXT alone, and a
nonexistent target guarantees no real home is ever touched. Seat homes (HESTIA_HOME and the
subprocess $HOME) are throwaway dirs under a per-run temp root, so every default that would
otherwise land in ~/.hestia / ~/.kimi-code / ~/.codex / ~/.claude lands in the fixture.

Families: cells normalize to (verdict, rule, family, escalatable, degraded) with family in
the corpus's vocabulary — "governance-closure" | "scope" | "safety-preset". One documented
alias: the corpus's `deny:gate-self` (the settings/registration surface) compares as
"governance-closure", because since Sprint B every seat renders that surface through the ONE
closure classifier (rule governance-closure-write, event class gate-self-access) — the old
rule-0 label is not separately observable on any shim today. The settings row still measures
deny on every seat; gemini denies it at Gate-1b scope first (it has no closure layer of its
own and its governor only sees in-scope acts) — that family divergence is a real finding,
not runner noise.

Run:  python3 tools/gate_parity_runner.py            # full 24x4 matrix, writes the report
      python3 tools/gate_parity_runner.py --seat kimi --act secret-cat-id_rsa
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "tools"
sys.path.insert(0, str(TOOLS))
from gate_parity_corpus import CORPUS  # noqa: E402

# The seat projection fixture: renders exactly what the daemon would render for a seat
# ($HESTIA_HOME/seats/<plugin>.env) so projection-consuming shims get the real shape.
sys.path.insert(0, str(REPO / "plugins" / "claude-code" / "tests"))
import projection_fixture  # noqa: E402

WORKSPACE = str(REPO.parent)          # the fleet workspace: the launch-cwd grant names REPO's dir
SHARED_DIR = str(REPO / "plugins" / "_shared")
CLAUDE_SHIM = REPO / "plugins" / "claude-code" / "hooks" / "pre_tool_use.py"

# {HOME} is TEXT the gates classify, never a path we touch: nonexistent, outside /tmp,
# outside the workspace, and outside every seat's home markers.
PROBE_HOME = "/home/gate-parity-probe"

SEATS = ("claude-code", "kimi", "codex", "gemini")
SEAT_SHIM = {
    "claude-code": "plugins/claude-code/hooks/pre_tool_use.py",
    "kimi": "plugins/kimi/hooks/pre_tool_use.py",
    "codex": "plugins/codex/hooks/pre_tool_use.py",
    "gemini": "plugins/gemini/hooks/before_tool.py",
}
# The plugin id each seat asserts to the daemon (kimi's directory is `kimi`, its id `kimi-code`).
SEAT_PLUGIN_ID = {"claude-code": "claude-code", "kimi": "kimi-code",
                  "codex": "codex", "gemini": "gemini"}

# Gemini's native tool vocabulary (source-read from tools/definitions/base-declarations.ts and
# live-verified per the shim's own header): Read->read_file, Edit->replace, Write->write_file,
# Bash->run_shell_command. tool_input field names survive unchanged (file_path / old_string /
# new_string / content / command are the names gemini itself emits).
GEMINI_TOOL = {"Read": "read_file", "Edit": "replace", "Write": "write_file",
               "Bash": "run_shell_command"}


# ── The stub daemon ─────────────────────────────────────────────────────────────────────────
class StubDaemon:
    """A NEUTRAL in-process MCP-over-HTTP daemon: the wire protocol the shims speak, with the
    policy layer removed. Every hestia_query_policy decides `allow`; every witness/claim is
    acked with a deterministic fake hash; every escalation claim is refused with an
    escalation opened (the live daemon's shape for a first touch). Never the live daemon."""

    def __init__(self) -> None:
        self.requests: list[str] = []          # (method | tool name) log, in order
        self._lock = threading.Lock()
        self._srv = ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
        self._srv.stub = self                  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._srv.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._srv.server_address[1]}/mcp"

    def __enter__(self) -> "StubDaemon":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._srv.shutdown()
        self._srv.server_close()
        self._thread.join(timeout=5)

    def _fake_hash(self, name: str, arguments) -> str:
        blob = name + "\0" + json.dumps(arguments, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def tool_payload(self, name: str, arguments: dict) -> dict:
        """The unwrapped payload for one tools/call — the fields each consumer actually reads
        (hestia_gate_mechanism._poll_policy/_interpret, fetch_policy_snapshot, the shims'
        claim/witness paths)."""
        digest = self._fake_hash(name, arguments)
        if name == "hestia_connect":
            return {"sessionId": f"stub-session-{digest[:12]}",
                    "plugin_id": arguments.get("plugin_id"),
                    "role": arguments.get("role") or "role:constellation:member"}
        if name == "hestia_begin_action":
            return {"actionId": f"stub-action-{digest[:12]}"}
        if name == "hestia_query_policy":
            # NEUTRAL: an explicit, recognized allow so the shim's LOCAL law decides.
            return {"status": "decided", "decision": "allow", "enforced": True,
                    "ruleName": "stub.neutral",
                    "reason": "gate-parity stub: no opinion (daemon policy layer neutralized)"}
        if name == "hestia_operating_law":
            return {"identity": {"plugin_id": arguments.get("plugin_id") or "unknown",
                                 "role": "role:constellation:member"},
                    "law_hash": "0" * 64, "operator_grant": None}
        if name == "hestia_scope_status":
            # A certified-but-empty snapshot: no grants (the launch-cwd bridge carries the
            # repo), a generation and a future honor horizon so resolve_agent_policy takes it.
            return {"live_grants": [], "standing_grants": [], "society_floor": [],
                    "generation": 1, "snapshot_expires_at": int(time.time()) + 3600}
        if name == "hestia_gate_escalation_claim":
            # Refused-with-escalation-opened: the first-touch shape a real daemon returns.
            return {"claimed": False, "permits_write": False,
                    "escalation_id": f"stub-esc-{digest[:12]}",
                    "how_to_decide": "stub: no human decides during a parity measurement",
                    "retry_within_secs": 300}
        if name in ("hestia_request_witness", "hestia_witness_decision"):
            return {"ok": True, "witnessEntryHash": digest, "id": f"stub-wit-{digest[:12]}"}
        return {"ok": True, "stub": True, "hash": digest}

    def handle(self, req: dict) -> tuple[dict | None, str | None]:
        """(response, session_header); response None = notification (empty 200)."""
        method = req.get("method")
        if method == "initialize":
            with self._lock:
                self.requests.append("initialize")
            return ({"jsonrpc": "2.0", "id": req.get("id"),
                     "result": {"protocolVersion": "2024-11-05", "capabilities": {},
                                "serverInfo": {"name": "gate-parity-stub", "version": "1"}}},
                    "stub-mcp-session")
        if isinstance(method, str) and method.startswith("notifications/"):
            with self._lock:
                self.requests.append(method)
            return None, None
        if method == "tools/call":
            params = req.get("params") or {}
            name = params.get("name") or "?"
            with self._lock:
                self.requests.append(name)
            payload = self.tool_payload(name, params.get("arguments") or {})
            return ({"jsonrpc": "2.0", "id": req.get("id"),
                     "result": {"content": [{"type": "text", "text": json.dumps(payload)}],
                                "structuredContent": payload}},
                    None)
        return ({"jsonrpc": "2.0", "id": req.get("id"),
                 "error": {"code": -32601, "message": f"stub: unknown method {method!r}"}},
                None)

    def summary(self) -> dict:
        out: dict[str, int] = {}
        for r in self.requests:
            out[r] = out.get(r, 0) + 1
        return out


class _StubHandler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:    # silence per-request stderr noise
        pass

    def do_POST(self) -> None:
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        raw = self.rfile.read(n) if n else b"{}"
        try:
            req = json.loads(raw.decode("utf-8", "replace"))
        except (ValueError, UnicodeDecodeError):
            req = {}
        resp, session = self.server.stub.handle(req)   # type: ignore[attr-defined]
        if resp is None:
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = json.dumps(resp).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        if session:
            self.send_header("mcp-session-id", session)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ── Native event rendering ──────────────────────────────────────────────────────────────────
def render_event(seat: str, tool: str, tool_input: dict, cwd: str, session: str) -> dict:
    """The act in THIS harness's native hook event JSON (each shim's stdin parsing, read
    from the shims themselves and cross-checked against plugins/*/expects.json)."""
    if seat == "gemini":
        return {"hook_event_name": "BeforeTool",
                "session_id": session,
                "cwd": cwd,
                "timestamp": "2026-10-01T00:00:00Z",
                "tool_name": GEMINI_TOOL.get(tool, tool),
                "tool_input": tool_input}
    event = {"hook_event_name": "PreToolUse",
             "session_id": session,
             "cwd": cwd,
             "tool_name": tool,
             "tool_input": tool_input}
    # The call-id spelling the seat's witness correlation keys on (hestia_witness_core).
    if seat == "kimi":
        event["tool_call_id"] = f"{session}-call"
    else:
        event["tool_use_id"] = f"{session}-call"
    return event


def render_value(value, mapping: dict[str, str]):
    if isinstance(value, str):
        for marker, replacement in mapping.items():
            value = value.replace(marker, replacement)
        return value
    if isinstance(value, list):
        return [render_value(v, mapping) for v in value]
    if isinstance(value, dict):
        return {k: render_value(v, mapping) for k, v in value.items()}
    return value


# ── Outcome normalization ───────────────────────────────────────────────────────────────────
@dataclass
class ProbeResult:
    rc: int | None
    stdout: str
    stderr: str
    timed_out: bool = False


@dataclass
class Cell:
    verdict: str           # allow | warn | deny
    rule: str              # the specific rule id where the shim named one, else ""
    family: str            # governance-closure | scope | safety-preset | degraded | none | unknown
    escalatable: bool
    degraded: bool         # fail-closed NO VERDICT (infra), never a policy ruling
    note: str = ""


# Order matters: the first pattern that matches the shim's combined output owns the family.
# Rule ids are the ones the shims actually emit (read from their source, not invented):
# kimi/codex name the classifier's rule id explicitly ("rule governance-closure-write");
# claude-code renders the event class ("[gate-self-access]"); core law denies carry their
# rule id in brackets on claude ("[egress.secret]") and render "[scope]" on kimi/codex.
_FAMILY_RULES = [
    (re.compile(r"governance-closure-[a-z-]+"), "governance-closure"),
    (re.compile(r"\[gate-self(?:-access)?\]|gate\.self_access|gate_self_access"),
     "governance-closure"),
    (re.compile(r"\[(egress\.secret|mrh\.(?:path|command|repo))\]"), "scope"),
    (re.compile(r"\[scope\]"), "scope"),
    (re.compile(r"\[safety\]|society[.-]safety|society\.safety"), "safety-preset"),
]
_DEGRADED_RE = re.compile(
    r"\[fail-closed\]|no verdict|\[degraded\]|config\.unbacked|config\.miswired|"
    r"no-shared-authority|gate-internal-error|gate\.core_unavailable|gate\.degraded|"
    r"could not parse the tool event|the gate crashed|gate-core-unavailable")
_WARN_RE = re.compile(r"hestia: warn|would-deny \(audit-only\)")
_RULE_ID_RE = re.compile(
    r"governance-closure-[a-z-]+|gate-self-access|gate\.self_access|egress\.secret|"
    r"mrh\.(?:path|command|repo)|society\.[a-z]+|gate\.degraded")


def _stdout_deny_payload(stdout: str) -> bool:
    """A harness may encode a policy denial in stdout JSON while exiting zero (the two deny
    spellings the deploy preflight's _payload_denies pins: permissionDecision / decision)."""
    try:
        value = json.loads(stdout.strip())
    except ValueError:
        return False
    return isinstance(value, dict) and (
        value.get("permissionDecision") == "deny" or value.get("decision") == "deny")


def classify_cell(seat: str, result: ProbeResult) -> Cell:
    """(verdict, rule, family, escalatable, degraded) from one shim's raw output.

    Degraded dominates: a fail-closed no-verdict cell is infra, not a ruling, and is never
    counted as matching (or diverging from) an expectation — only as degraded.
    """
    text = (result.stderr or "") + "\n" + (result.stdout or "")
    degraded = bool(_DEGRADED_RE.search(text))
    note = ""

    if result.timed_out:
        # No verdict observed at all. On the claude-lineage engines a killed hook fails OPEN
        # at the harness layer — this cell measures "the shim could not answer", nothing more.
        return Cell("deny", "", "degraded", False, True, "subprocess timeout")

    if seat == "gemini":
        # TWO DENY CHANNELS (the shim's own contract): a POLICY deny is exit 0 + stdout JSON
        # {"decision":"deny",...}; exit 2 + stderr is the ANOMALY channel = could not vouch.
        if _stdout_deny_payload(result.stdout):
            verdict = "deny"
        elif result.rc == 0:
            verdict = "warn" if _WARN_RE.search(text) else "allow"
        else:
            verdict, degraded = "deny", True
            note = note or f"anomaly channel (exit {result.rc})"
    else:
        # claude-code / kimi / codex: exit 0 = allow, exit 0 + stderr warn text = warn,
        # exit 2 = deny. A stdout deny payload is honoured here too (belt; none emit one).
        if _stdout_deny_payload(result.stdout):
            verdict = "deny"
        elif result.rc == 0:
            verdict = "warn" if _WARN_RE.search(text) else "allow"
        elif result.rc == 2:
            verdict = "deny"
        else:
            verdict, degraded = "deny", True
            note = note or f"unexpected exit {result.rc}"

    family = "none"
    rule = ""
    if verdict == "deny":
        family = "unknown"
        for pattern, fam in _FAMILY_RULES:
            m = pattern.search(text)
            if m:
                family = fam
                rule = m.group(1) if m.lastindex else m.group(0)
                break
        if not rule:
            m = _RULE_ID_RE.search(text)
            rule = m.group(0) if m else ""
    elif verdict == "warn":
        m = re.search(r"\[([a-z][a-z0-9._-]*)\]", text)
        rule = m.group(1) if m else ""
        for pattern, fam in _FAMILY_RULES:
            if pattern.search(text):
                family = fam
                break
        else:
            family = "unknown"
    if degraded and verdict == "deny" and family in ("unknown", "none"):
        family = "degraded"
    escalatable = "escalat" in text.lower()
    return Cell(verdict, rule, family, escalatable, degraded, note)


# ── Expected-value comparison ───────────────────────────────────────────────────────────────
# The corpus's "deny:gate-self" (the settings/registration surface) and "deny:governance-closure"
# are ONE observable surface on today's shims: since Sprint B all four render both through the
# shared closure classifier (rule governance-closure-write / event class gate-self-access).
EXPECTED_FAMILY_ALIASES = {"gate-self": "governance-closure"}


def parse_expected(expected: str) -> tuple[str, str | None]:
    """"allow" -> ("allow", None); "deny:scope" -> ("deny", "scope"); "PIN" -> ("PIN", None)."""
    if expected == "PIN":
        return "PIN", None
    verdict, _, fam = expected.partition(":")
    return verdict, (EXPECTED_FAMILY_ALIASES.get(fam, fam) if fam else None)


def cell_matches_expected(cell: Cell, expected: str) -> bool | None:
    """None = not judgeable (degraded, or a PIN row: those check agreement only)."""
    verdict, family = parse_expected(expected)
    if verdict == "PIN" or cell.degraded:
        return None
    if cell.verdict != verdict:
        return False
    if family is not None and cell.family != family:
        return False
    return True


# ── Fixture construction ────────────────────────────────────────────────────────────────────
def build_seat_home(homes: Path, seat: str, endpoint: str) -> Path:
    """A throwaway HESTIA_HOME for one seat: its rendered projection (the real shape, via the
    repo's own fixture), a minimal identity replica, and — for gemini — a SECOND projection
    for claude-code, because gemini's Gate 2 spawns the claude-code shim as its governor and
    that shim consumes $HESTIA_HOME/seats/claude-code.env at import."""
    home = homes / seat
    home.mkdir(parents=True)
    projection_env = {"HESTIA_SHARED_DIR": SHARED_DIR,
                      "HESTIA_WORKSPACE": WORKSPACE,
                      "HESTIA_ENDPOINT": endpoint}
    projection_fixture.write_projection(home, SEAT_PLUGIN_ID[seat], projection_env,
                                        note="gate-parity throwaway seat")
    if seat == "gemini":
        projection_fixture.write_projection(home, "claude-code", projection_env,
                                            note="gate-parity: gemini's spawned governor")
    (home / "identity.json").write_text(json.dumps(
        {"plugin_id": SEAT_PLUGIN_ID[seat], "role": "role:constellation:member",
         "mrh": {"in_scope": []}}), encoding="utf-8")
    return home


def seat_env(seat: str, home: Path, endpoint: str) -> dict:
    """The subprocess environment: every ambient HESTIA_* stripped (a leak could re-point a
    shim at the LIVE daemon), then the seat's pins. HOME is the throwaway seat home so every
    ~-default (observe dirs, telemetry, identity) lands in the fixture, never in a live dir.
    Gate modes stay at their defaults (enforce) — the corpus measures the enforcing posture."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("HESTIA_")}
    env.update({
        "HOME": str(home),
        "HESTIA_HOME": str(home),
        "HESTIA_SHARED_DIR": SHARED_DIR,
        "HESTIA_WORKSPACE": WORKSPACE,
        "HESTIA_ENDPOINT": endpoint,
        "HESTIA_STATE_DIR": str(home / "state"),
        "HESTIA_OBSERVE_DIR": str(home / "observe"),
        "HESTIA_KIMI_IDENTITY": str(home / "identity.json"),
        "HESTIA_CODEX_IDENTITY": str(home / "identity.json"),
        "HESTIA_GEMINI_IDENTITY": str(home / "identity.json"),
        # The launch-cwd grant: "the repo the member is launched in is always in scope".
        "HESTIA_KIMI_LAUNCH_CWD": str(REPO),
        "HESTIA_CODEX_LAUNCH_CWD": str(REPO),
        "HESTIA_GEMINI_LAUNCH_CWD": str(REPO),
        # Gemini's Gate 2 spawns this shim as its governor.
        "HESTIA_SOCIETY_GATE": str(CLAUDE_SHIM),
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    return env


# An innocuous patch the closure classifier can READ (an unreadable patch file is an
# unconditional governance-closure-opaque-writer deny by construction). Its targets name no
# closure path.
PATCH_FIXTURE = """\
diff --git a/scratchpad/parity-fixture.txt b/scratchpad/parity-fixture.txt
index 0000000..1111111 100644
--- a/scratchpad/parity-fixture.txt
+++ b/scratchpad/parity-fixture.txt
@@ -1 +1 @@
-old
+new
"""


def build_scratch(root: Path) -> Path:
    scratch = root / "scratch"
    scratch.mkdir(parents=True)
    (scratch / "patch.diff").write_text(PATCH_FIXTURE, encoding="utf-8")
    (scratch / "approved.patch").write_text(PATCH_FIXTURE, encoding="utf-8")
    return scratch


# ── The probe loop ──────────────────────────────────────────────────────────────────────────
def run_shim(shim_path: Path, event: dict, env: dict, cwd: Path, timeout: float) -> ProbeResult:
    """The subprocess layer (stubbed by the unit test): python3 <shim>, event on stdin."""
    try:
        proc = subprocess.run([sys.executable, str(shim_path)],
                              input=json.dumps(event), capture_output=True, text=True,
                              cwd=str(cwd), env=env, timeout=timeout, check=False)
        return ProbeResult(proc.returncode, proc.stdout, proc.stderr)
    except subprocess.TimeoutExpired as exc:
        def _s(v):
            return v.decode("utf-8", "replace") if isinstance(v, bytes) else (v or "")
        return ProbeResult(None, _s(exc.stdout), _s(exc.stderr), timed_out=True)


def run_matrix(seats: list[str], acts: list, timeout: float) -> dict:
    report: dict = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "repo": str(REPO), "workspace": WORKSPACE, "shared_dir": SHARED_DIR,
                    "probe_home": PROBE_HOME, "seats": seats, "cells": {}, "rows": []}
    with tempfile.TemporaryDirectory(prefix="gate-parity-") as tmp:
        root = Path(tmp)
        scratch = build_scratch(root)
        with StubDaemon() as stub:
            endpoint = stub.url
            for seat in seats:
                home = build_seat_home(root / "homes", seat, endpoint)
                env = seat_env(seat, home, endpoint)
                shim = REPO / SEAT_SHIM[seat]
                for act in acts:
                    act_id, act_class, tool, tool_input, expected, note = act
                    mapping = {"{REPO}": str(REPO), "{SCRATCH}": str(scratch),
                               "{HOME}": PROBE_HOME, "{SELF}": seat}
                    rendered_input = render_value(tool_input, mapping)
                    session = f"gate-parity-{os.getpid()}-{seat}-{act_id}"
                    event = render_event(seat, tool, rendered_input, str(REPO), session)
                    result = run_shim(shim, event, env, REPO, timeout)
                    cell = classify_cell(seat, result)
                    report["cells"][f"{act_id}|{seat}"] = {
                        "verdict": cell.verdict, "rule": cell.rule, "family": cell.family,
                        "escalatable": cell.escalatable, "degraded": cell.degraded,
                        "note": cell.note, "rc": result.rc, "timed_out": result.timed_out,
                        "event": event, "stdout": result.stdout, "stderr": result.stderr,
                    }
            report["stub_requests"] = stub.summary()
    for act in acts:
        act_id, act_class, tool, _ti, expected, note = act
        row = {"id": act_id, "class": act_class, "tool": tool, "expected": expected,
               "note": note, "seats": {}}
        for seat in seats:
            cell = report["cells"][f"{act_id}|{seat}"]
            row["seats"][seat] = {"verdict": cell["verdict"], "rule": cell["rule"],
                                  "family": cell["family"], "escalatable": cell["escalatable"],
                                  "degraded": cell["degraded"],
                                  "matches_expected": cell_matches_expected(
                                      Cell(cell["verdict"], cell["rule"], cell["family"],
                                           cell["escalatable"], cell["degraded"]), expected)}
        verdicts = {s["verdict"] for s in row["seats"].values() if not s["degraded"]}
        families = {s["family"] for s in row["seats"].values()
                    if not s["degraded"] and s["verdict"] == "deny"}
        row["agreement"] = len(verdicts) <= 1 and len(families) <= 1 and not any(
            s["degraded"] for s in row["seats"].values())
        row["diverged"] = not row["agreement"]
        report["rows"].append(row)
    return report


# ── Rendering ───────────────────────────────────────────────────────────────────────────────
def _cell_text(seat_cell: dict) -> str:
    v = seat_cell["verdict"]
    fam = seat_cell["family"]
    text = v if v == "allow" else f"{v}:{fam}"
    if seat_cell["degraded"]:
        text += "![degraded]"
    elif seat_cell["escalatable"]:
        text += "(esc)"
    return text


def print_report(report: dict) -> None:
    seats = report["seats"]
    width = max(len(s) for s in seats) + 2
    print(f"gate parity — {len(report['rows'])} acts x {len(seats)} seats "
          f"(stub daemon: {sum(report['stub_requests'].values())} requests served)")
    print(f"repo: {report['repo']}   workspace: {report['workspace']}")
    print()
    header = "act".ljust(30) + "".join(s.ljust(width) for s in seats) + "flags"
    print(header)
    print("-" * len(header))
    n_agree = n_diverge = n_degraded = 0
    mismatches: list[str] = []
    for row in report["rows"]:
        flags = []
        if row["diverged"]:
            n_diverge += 1
            flags.append("DIVERGES")
        else:
            n_agree += 1
        row_degraded = [s for s in seats if row["seats"][s]["degraded"]]
        n_degraded += len(row_degraded)
        if row_degraded:
            flags.append("degraded:" + ",".join(row_degraded))
        if row["expected"] != "PIN":
            bad = [s for s in seats if row["seats"][s]["matches_expected"] is False]
            if bad:
                flags.append("!=expected:" + ",".join(bad))
                mismatches.append(row["id"])
        elif row["agreement"]:
            flags.append("pin-ok")
        else:
            flags.append("PIN-DIVERGES")
        cells = "".join(_cell_text(row["seats"][s]).ljust(width) for s in seats)
        print(row["id"].ljust(30) + cells + " ".join(flags))
    print()
    judged = [(r["id"], s) for r in report["rows"] if r["expected"] != "PIN"
              for s in seats if r["seats"][s]["matches_expected"] is not None]
    matched = [(i, s) for i, s in judged
               if next(r for r in report["rows"] if r["id"] == i)["seats"][s][
                   "matches_expected"]]
    print(f"rows in full agreement: {n_agree}/{len(report['rows'])}")
    print(f"rows diverging across seats: {n_diverge}")
    print(f"expected-mismatch cells: {len(judged) - len(matched)}/{len(judged)} judged "
          f"(rows: {', '.join(mismatches) if mismatches else 'none'})")
    print(f"degraded cells (fail-closed, no verdict): {n_degraded}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seat", action="append", choices=SEATS, default=None,
                    help="measure only this seat (repeatable)")
    ap.add_argument("--act", action="append", default=None,
                    help="measure only this corpus act id (repeatable)")
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--output", type=Path, default=TOOLS / "gate_parity_report.json")
    args = ap.parse_args(argv)

    seats = args.seat or list(SEATS)
    acts = [a for a in CORPUS if not args.act or a[0] in args.act]
    if not acts:
        print("no corpus acts selected", file=sys.stderr)
        return 2

    report = run_matrix(seats, acts, args.timeout)
    print_report(report)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"\nreport written: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
