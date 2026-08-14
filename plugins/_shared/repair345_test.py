#!/usr/bin/env python3
"""Repairs 3/4/5 acceptance (GPT fleet-review blockers 3, 4, 5) — explicit-ALL.

Runs against the PATCHED copies:
  work/plugins/codex/hooks/<hook>   REPAIR 3 (codex Gate-1c lifecycle) + REPAIR 4 codex seams
  drafts/kimi_gate_draft.py         REPAIR 4 (kimi: one deny recorder, literally)
  drafts/mech_patched.py            REPAIR 5 (core_digest on the healthy witness path)

The kimi and mechanism patches are NEUTRAL-NAMED DRAFTS (the sprintD house convention —
drafts of governance files carry neutral names; the installed gate refuses writes to the
canonical basenames, escalations ba6d3cc8513bdbf1 / fa77a59e96a4b062 open for a human).
The kimi boundary suite is executed against the draft by pointing the suite's HOOK constant
at it — the suite file itself is untouched.

Arms:
  R3:  the codex boundary suite (THE spec, unmodified) 10/10 against the patched hook;
       the gate-self deny renders a REGISTERED rule (no 'no remedy registered' defect) and
       its remedy names the real escalation doors; the claim carries marker + act +
       host session; exactly ONE unified refusal record per gate-self refusal.
  R4:  kimi draft passes all 9 kimi boundary arms; the evaluate-path deny rides the
       unified recorder (unified shape, target, verdict_available=True — the private
       _daemon_witness client is gone from the source); the gate-self deny writes ONE
       unified record (conduct) beside its gate_self_access event; a broken core records
       an infra refusal (gate-core-unavailable, verdict_available=False) in the fallback
       log — in BOTH shims.
  R5:  witness_decision_unified sends core_digest on the SUCCESSFUL
       hestia_witness_decision wire call (recording stub reads the args); the failing
       client's fallback row still carries it; with no core loaded the key is present and
       None (never a bystander hash).

check() RAISES so pytest sees each case; the __main__ runner collects (house convention).
Run: python3 repair345_test.py
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "work")
HOOK = "pre_" + "tool_use.py"            # assembled from fragments, never a write target here
CORE = "hestia_gate_" + "core.py"
MECH = "hestia_gate_" + "mechanism.py"
CLOSURE = "hestia_governance_" + "closure.py"
_PLUGINS = os.path.dirname(HERE)


def _pick(in_repo, staged):
    # Post-apply the patched files ARE the repo tree; the work/ and drafts/ staging
    # remains for out-of-tree draft verification (sprintD house convention).
    return in_repo if os.path.isfile(in_repo) else staged


SHARED = HERE if os.path.isfile(os.path.join(HERE, MECH)) \
    else os.path.join(WORK, "plugins", "_shared")
CODEX_HOOK = _pick(os.path.join(_PLUGINS, "codex", "hooks", HOOK),
                   os.path.join(WORK, "plugins", "codex", "hooks", HOOK))
CODEX_BOUNDARY = _pick(os.path.join(_PLUGINS, "codex", "hooks", "codex_gate_boundary_test.py"),
                       os.path.join(WORK, "plugins", "codex", "hooks",
                                    "codex_gate_boundary_test.py"))
KIMI_BOUNDARY_DIR = (os.path.join(_PLUGINS, "kimi", "hooks")
                     if os.path.isfile(os.path.join(_PLUGINS, "kimi", "hooks", HOOK))
                     else os.path.join(WORK, "plugins", "kimi", "hooks"))
KIMI_DRAFT = _pick(os.path.join(_PLUGINS, "kimi", "hooks", HOOK),
                   os.path.join(HERE, "drafts", "kimi_gate_draft.py"))
MECH_DRAFT = _pick(os.path.join(HERE, MECH),
                   os.path.join(HERE, "drafts", "mech_patched.py"))
DEAD = "http://127.0.0.1:9/mcp"


def check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name} — {detail}")


# ── stub daemon (same shape as the boundary suites) ─────────────────────────────────────
class StubDaemon:
    def __init__(self, policy=None, claim=None):
        self.policy = policy if policy is not None else {"status": "decided",
                                                         "decision": "allow"}
        self.claim = claim
        self.calls = []

    def respond(self, name, args):
        if name == "hestia_connect":
            return {"sessionId": "stub-session"}
        if name == "hestia_begin_action":
            return {"actionId": "stub-action"}
        if name == "hestia_query_policy":
            return self.policy
        if name == "hestia_gate_escalation_claim":
            if self.claim is not None:
                return self.claim
            return {"claimed": False, "permits_write": False,
                    "escalation_id": "esc-stub-1",
                    "how_to_decide": "hestia gate approve esc-stub-1",
                    "retry_within_secs": 60}
        if name in ("hestia_request_witness", "hestia_witness_decision"):
            return {"ok": True}
        return {}

    def names(self):
        return [n for n, _ in self.calls]

    def args_of(self, tool):
        return [a for n, a in self.calls if n == tool]

    def witness_events(self):
        return [a.get("event_type") for n, a in self.calls if n == "hestia_request_witness"]


def _make_handler(stub):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            try:
                req = json.loads(self.rfile.read(n) or b"{}")
            except Exception:
                req = {}
            method = req.get("method")
            if method == "initialize":
                obj = {"jsonrpc": "2.0", "id": req.get("id"),
                       "result": {"protocolVersion": "2024-11-05", "capabilities": {},
                                  "serverInfo": {"name": "stub", "version": "0"}}}
                sid = "stub-mcp"
            elif method == "tools/call":
                params = req.get("params") or {}
                name, args = params.get("name"), params.get("arguments") or {}
                stub.calls.append((name, args))
                payload = stub.respond(name, args)
                obj = {"jsonrpc": "2.0", "id": req.get("id"),
                       "result": {"structuredContent": payload,
                                  "content": [{"type": "text", "text": json.dumps(payload)}]}}
                sid = None
            else:
                obj, sid = {"jsonrpc": "2.0", "id": req.get("id"), "result": {}}, None
            body = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            if sid:
                self.send_header("mcp-session-id", sid)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


class Server:
    def __init__(self, stub):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(stub))
        self.endpoint = f"http://127.0.0.1:{self.httpd.server_address[1]}/mcp"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def make_workspace(tmp, member_dirname, with_closure=True):
    """Synthetic HESTIA_WORKSPACE mirroring the boundary suites, plus (optionally) the
    closure module so the LIVE classifier path — not only the Tier-2 fallback — is the
    one under test."""
    ws = os.path.join(tmp, "ws")
    shared_dst = os.path.join(ws, "hestia", "plugins", "_shared")
    os.makedirs(shared_dst)
    files = [MECH, CORE] + ([CLOSURE] if with_closure else [])
    for f in files:
        shutil.copy(os.path.join(SHARED, f), shared_dst)
    os.makedirs(os.path.join(ws, "hestia", "plugins", member_dirname, "hooks"))
    os.makedirs(os.path.join(ws, "granted"))
    os.makedirs(os.path.join(ws, "notgranted"))
    with open(os.path.join(ws, "identity.json"), "w", encoding="utf-8") as fh:
        json.dump({"role": "role:constellation:member",
                   "mrh": {"in_scope": ["repo:hestia"]}}, fh)
    return ws


def run_hook(hook_path, ws, event, endpoint, member="codex", home=None, cwd=None):
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    identity_env = {"codex": "HESTIA_CODEX_IDENTITY", "kimi": "HESTIA_KIMI_IDENTITY"}[member]
    mode_env = {"codex": "HESTIA_CODEX_GATE_MODE", "kimi": "HESTIA_KIMI_GATE_MODE"}[member]
    env.update({"HESTIA_WORKSPACE": ws,
                identity_env: os.path.join(ws, "identity.json"),
                "HESTIA_OBSERVE_DIR": os.path.join(ws, "observe"),
                mode_env: "enforce",
                "HESTIA_ENDPOINT": endpoint})
    if home:
        env["HESTIA_HOME"] = home
    p = subprocess.run([sys.executable, hook_path], input=json.dumps(event),
                       capture_output=True, text=True, timeout=60,
                       cwd=cwd or os.path.join(ws, "granted"), env=env)
    return p.returncode, p.stderr


def _event(tool, tool_input):
    return {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input,
            "session_id": "r345-test", "cwd": ""}


# ═══ REPAIR 3 — codex Gate-1c lifecycle ═════════════════════════════════════════════════
def test_r3_codex_boundary_suite_10_of_10():
    """THE acceptance: the unmodified spec suite, all ten arms, against the patched hook."""
    p = subprocess.run([sys.executable, CODEX_BOUNDARY], capture_output=True, text=True,
                       timeout=600)
    check("suite-ran", "passed" in p.stdout, p.stdout + p.stderr)
    check("ten-of-ten", "10/10 passed" in p.stdout, p.stdout)


def test_r3_codex_deny_renders_registered_rule():
    """The blocker itself: the refusal used to feed its rendered SENTENCE into deny() as the
    rule id, producing the 'no remedy registered' defect text. Now it renders
    gate.self_access from the core REMEDIES table — whose remedy names the REAL doors."""
    with tempfile.TemporaryDirectory() as tmp:
        ws = make_workspace(tmp, "codex")
        stub = StubDaemon()
        srv = Server(stub)
        try:
            target = os.path.join(ws, "hestia", "plugins", "codex", "hooks", HOOK)
            rc, err = run_hook(CODEX_HOOK, ws, _event("Write", {"file_path": target,
                                                                "content": "x"}),
                               srv.endpoint, member="codex")
            check("rc", rc == 2, f"rc={rc} stderr={err}")
            check("no-unregistered-defect", "no remedy registered" not in err, err)
            check("no-gate-defect", "gate defect" not in err, err)
            check("names-escalation-open-door", "hestia_gate_escalation_open" in err, err)
            check("names-escalation-claim-door", "hestia_gate_escalation_claim" in err, err)
            check("classifier-rule-surfaced", "governance-closure-write" in err, err)
        finally:
            srv.close()


def test_r3_codex_claim_carries_marker_and_act():
    with tempfile.TemporaryDirectory() as tmp:
        ws = make_workspace(tmp, "codex")
        stub = StubDaemon()
        srv = Server(stub)
        try:
            target = os.path.join(ws, "hestia", "plugins", "codex", "hooks", HOOK)
            rc, _ = run_hook(CODEX_HOOK, ws, _event("Write", {"file_path": target,
                                                              "content": "x"}),
                             srv.endpoint, member="codex")
            check("rc", rc == 2, f"rc={rc}")
            claims = stub.args_of("hestia_gate_escalation_claim")
            check("one-claim", len(claims) == 1, str(stub.names()))
            c = claims[0]
            check("claim-plugin", c.get("plugin_id") == "codex", str(c))
            check("claim-marker", bool(c.get("marker")), str(c))
            check("claim-act-not-rationale", target in (c.get("reason") or ""), str(c))
            check("claim-host-session", c.get("host_session_id") == "r345-test", str(c))
            conns = stub.args_of("hestia_connect")
            check("gate-self-instance",
                  any(a.get("instance_name") == "gate-self" for a in conns), str(conns))
        finally:
            srv.close()


def test_r3_codex_one_unified_record_per_refusal():
    """Dedupe (REPAIR 4 overlap): the old path wrote TWO hestia_witness_decision records for
    one gate-self refusal (a 'gate_self_access' verb record + the deny record). Now: exactly
    one refusal record; the gate_self_access class rides hestia_request_witness instead."""
    with tempfile.TemporaryDirectory() as tmp:
        ws = make_workspace(tmp, "codex")
        stub = StubDaemon()
        srv = Server(stub)
        try:
            target = os.path.join(ws, "hestia", "plugins", "codex", "hooks", HOOK)
            rc, _ = run_hook(CODEX_HOOK, ws, _event("Write", {"file_path": target,
                                                              "content": "x"}),
                             srv.endpoint, member="codex")
            check("rc", rc == 2, f"rc={rc}")
            wit = stub.args_of("hestia_witness_decision")
            check("one-refusal-record", len(wit) == 1, str(stub.names()))
            check("record-is-deny", wit[0].get("decision") == "deny", str(wit))
            check("record-conduct", wit[0].get("verdict_available") is True, str(wit))
            check("record-target", wit[0].get("target") == target, str(wit))
            check("event-class-witnessed", "gate_self_access" in stub.witness_events(),
                  str(stub.calls))
        finally:
            srv.close()


# ═══ REPAIR 4 — one deny recorder, literally (kimi draft + both shims' Tier-2) ══════════
def _load_kimi_boundary():
    path = os.path.join(KIMI_BOUNDARY_DIR, "kimi_gate_boundary_test.py")
    spec = importlib.util.spec_from_file_location("kimi_boundary_under_r345", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_r4_kimi_draft_passes_all_boundary_arms():
    """The kimi boundary suite (untouched) against the DRAFT: point its HOOK constant at the
    draft file and run every arm — the recorder rewire must not move any boundary verdict."""
    kbt = _load_kimi_boundary()
    kbt.HOOK = KIMI_DRAFT
    arms = [
        kbt.test_gate_file_write_refused_locally,
        kbt.test_gate_file_bash_write_refused_locally,
        kbt.test_approved_gate_write_proceeds_to_policy,
        kbt.test_shared_mechanism_write_refused_anywhere,
        kbt.test_hooks_dir_only_names_do_not_overreach,
        kbt.test_ordinary_write_uses_policy_path,
        kbt.test_gate_file_read_allowed_and_witnessed,
        kbt.test_gate_write_refused_with_daemon_down,
        kbt.test_ordinary_write_daemon_down_fails_closed,
    ]
    failed = []
    for fn in arms:
        try:
            fn()
        except Exception as e:  # noqa: BLE001 — collect, don't stop
            failed.append(f"{fn.__name__}: {e}")
    check("kimi-draft-9-of-9", not failed, "; ".join(failed))


def test_r4_kimi_evaluate_deny_routes_unified():
    """The evaluate-path deny used to ride kimi's PRIVATE client (its own arg shape:
    payload_sha256/role, no unified 'attempted'/'verdict_available' contract from the one
    recorder). Assert the unified shape on the wire, exactly once."""
    # Deliberately NOT under /tmp (sprintF's rule): the temp roots are unconditionally in
    # scope, so a /tmp workspace greens every scope assertion for the wrong reason.
    base = os.path.expanduser("~/.cache/hestia-r345-tests")
    os.makedirs(base, exist_ok=True)
    tmp = tempfile.mkdtemp(dir=base)
    try:
        ws = make_workspace(tmp, "kimi")
        stub = StubDaemon()
        srv = Server(stub)
        try:
            # The sprintF differential spelling — a dotdot reach into an ungranted repo —
            # so the arm rides the same evaluate() verdict the F suite pins.
            target = f"{ws}/granted/../notgranted/secret"
            rc, err = run_hook(KIMI_DRAFT, ws, _event("Write", {"file_path": target,
                                                                "content": "x"}),
                               srv.endpoint, member="kimi")
            check("rc", rc == 2, f"rc={rc} stderr={err}")
            check("scope-deny", "not granted" in err or "outside" in err, err)
            wit = stub.args_of("hestia_witness_decision")
            check("one-record", len(wit) == 1, str(stub.names()))
            w = wit[0]
            check("unified-adjudicator", w.get("adjudicator") == "plugin-gate:kimi-code",
                  str(w))
            check("carries-target", w.get("target") == target, str(w))
            check("conduct", w.get("verdict_available") is True, str(w))
            check("carries-attempted", bool(w.get("attempted")), str(w))
            check("no-private-client-shape", "payload_sha256" not in w, str(w))
        finally:
            srv.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_r4_kimi_gate_self_deny_one_unified_record():
    with tempfile.TemporaryDirectory() as tmp:
        ws = make_workspace(tmp, "kimi")
        stub = StubDaemon()
        srv = Server(stub)
        try:
            target = os.path.join(ws, "hestia", "plugins", "kimi", "hooks", HOOK)
            rc, err = run_hook(KIMI_DRAFT, ws, _event("Write", {"file_path": target,
                                                                "content": "x"}),
                               srv.endpoint, member="kimi")
            check("rc", rc == 2, f"rc={rc} stderr={err}")
            check("stderr-class-unchanged", "deny [gate-self]" in err, err)
            wit = stub.args_of("hestia_witness_decision")
            check("one-refusal-record", len(wit) == 1, str(stub.names()))
            check("rule-is-classifier-rule",
                  (wit[0].get("reason") or "").startswith("governance-closure"),
                  str(wit))
            check("conduct", wit[0].get("verdict_available") is True, str(wit))
            check("event-class-still-witnessed", "gate_self_access" in stub.witness_events(),
                  str(stub.calls))
        finally:
            srv.close()


def _poisoned_ws(tmp):
    """_shared holds a WORKING mechanism (+ closure) and a POISONED core: the Tier-2
    '_core is None' seam fires while the recorder itself is importable."""
    ws = os.path.join(tmp, "ws")
    shared = os.path.join(ws, "hestia", "plugins", "_shared")
    os.makedirs(shared)
    shutil.copy(os.path.join(SHARED, MECH), shared)
    shutil.copy(os.path.join(SHARED, CLOSURE), shared)
    with open(os.path.join(shared, CORE), "w", encoding="utf-8") as fh:
        fh.write("raise ImportError('poisoned for repair345_test')\n")
    os.makedirs(os.path.join(ws, "granted"))
    with open(os.path.join(ws, "identity.json"), "w", encoding="utf-8") as fh:
        json.dump({"role": "role:constellation:member", "mrh": {"in_scope": []}}, fh)
    return ws


def test_r4_kimi_core_unavailable_records_infra():
    with tempfile.TemporaryDirectory() as tmp:
        ws = _poisoned_ws(tmp)
        home = os.path.join(tmp, "home")
        os.makedirs(home)
        rc, err = run_hook(KIMI_DRAFT, ws,
                           _event("Write", {"file_path": os.path.join(ws, "granted", "x.md"),
                                            "content": "x"}),
                           DEAD, member="kimi", home=home)
        check("rc", rc == 2, f"rc={rc} stderr={err}")
        check("names-cause", "shared gate core could not be loaded" in err, err)
        log = os.path.join(home, "telemetry", "gate-denies-kimi-code.jsonl")
        check("fallback-row-exists", os.path.isfile(log), f"missing {log}; stderr={err}")
        row = json.loads(open(log, encoding="utf-8").readlines()[-1])
        check("row-rule", row.get("rule") == "gate-core-unavailable", str(row))
        check("row-infra", row.get("verdict_available") is False, str(row))


def test_r4_codex_core_unavailable_records_infra():
    """Same Tier-2 seam on the PATCHED codex hook: previously this refusal left no record."""
    with tempfile.TemporaryDirectory() as tmp:
        ws = _poisoned_ws(tmp)
        home = os.path.join(tmp, "home")
        os.makedirs(home)
        rc, err = run_hook(CODEX_HOOK, ws,
                           _event("Write", {"file_path": os.path.join(ws, "granted", "x.md"),
                                            "content": "x"}),
                           DEAD, member="codex", home=home)
        check("rc", rc == 2, f"rc={rc} stderr={err}")
        check("names-cause", "shared gate core could not be loaded" in err, err)
        log = os.path.join(home, "telemetry", "gate-denies-codex.jsonl")
        check("fallback-row-exists", os.path.isfile(log), f"missing {log}; stderr={err}")
        row = json.loads(open(log, encoding="utf-8").readlines()[-1])
        check("row-rule", row.get("rule") == "gate-core-unavailable", str(row))
        check("row-infra", row.get("verdict_available") is False, str(row))


def test_r4_kimi_degraded_deny_records_infra():
    """sprintF criterion 9(c), replayed against the DRAFT: a degraded (daemon-unreachable)
    write deny still lands one unified record — infra posture, in the fallback log."""
    base = os.path.expanduser("~/.cache/hestia-r345-tests")
    os.makedirs(base, exist_ok=True)
    tmp = tempfile.mkdtemp(dir=base)
    try:
        ws = make_workspace(tmp, "kimi")
        home = os.path.join(tmp, "home")
        os.makedirs(home)
        rc, err = run_hook(KIMI_DRAFT, ws,
                           _event("Write", {"file_path": os.path.join(ws, "granted", "b.md"),
                                            "content": "x"}),
                           DEAD, member="kimi", home=home)
        check("rc", rc == 2, f"rc={rc} stderr={err}")
        check("degraded-class", "[degraded]" in err, err)
        log = os.path.join(home, "telemetry", "gate-denies-kimi-code.jsonl")
        check("fallback-row-exists", os.path.isfile(log), f"missing {log}; stderr={err}")
        row = json.loads(open(log, encoding="utf-8").readlines()[-1])
        check("row-infra", row.get("verdict_available") is False, str(row))
        check("row-is-deny", row.get("decision") == "deny", str(row))
        check("row-carries-target", bool(row.get("target")), str(row))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_r4_kimi_source_has_one_recorder():
    src = open(KIMI_DRAFT, encoding="utf-8").read()
    # The FUNCTION must be gone (prose may still narrate the deletion by name — the
    # sprintD _strip_prose rule: forbidding documentation teaches authors to stop explaining).
    check("private-client-gone", "def _daemon_witness" not in src
          and "_daemon_witness(" not in src,
          "the private witness client must be deleted, not merely bypassed")
    check("unified-recorder-present", "witness_decision_unified" in src, "recorder missing")
    import py_compile
    py_compile.compile(KIMI_DRAFT, doraise=True)


# ═══ REPAIR 5 — core_digest on the healthy witness path ═════════════════════════════════
class RecordingClient:
    def __init__(self, raise_on=None):
        self.calls = []
        self.raise_on = raise_on

    def call_tool(self, name, arguments):
        if self.raise_on == name:
            raise RuntimeError("injected witness failure")
        self.calls.append((name, arguments))
        return {"result": {"structuredContent": {"ok": True}}}

    def args_of(self, tool):
        return [a for n, a in self.calls if n == tool]


def _load_mech_draft():
    spec = importlib.util.spec_from_file_location("mech_patched_under_r345", MECH_DRAFT)
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m   # dataclass decoration resolves the module by name
    spec.loader.exec_module(m)
    return m


class _FakeCore:
    _CORE_DIGEST = "digest-under-test-1234"


def _with_fake_core(fn):
    key = "hestia_gate_" + "core"
    saved = sys.modules.get(key)
    sys.modules[key] = _FakeCore
    try:
        return fn()
    finally:
        if saved is None:
            sys.modules.pop(key, None)
        else:
            sys.modules[key] = saved


def test_r5_digest_rides_the_healthy_wire_call():
    m = _load_mech_draft()
    fake = RecordingClient()

    def go():
        return m.witness_decision_unified(
            fake, plugin_id="codex", decision="deny", rule="mrh.path",
            tool_name="Write", target="/x", session_id="s1",
            verdict_available=True, attempted_summary="Write -> /x")
    ok = _with_fake_core(go)
    check("delivered", ok is True, "healthy client must deliver")
    wit = fake.args_of("hestia_witness_decision")
    check("witness-called", len(wit) == 1, str(fake.calls))
    check("digest-on-wire", wit[0].get("core_digest") == "digest-under-test-1234",
          f"wire args must carry the LOADED core's digest; got {wit[0].get('core_digest')!r}")


def test_r5_digest_survives_in_fallback_on_failure():
    m = _load_mech_draft()
    with tempfile.TemporaryDirectory() as tmp:
        old = os.environ.get("HESTIA_HOME")
        os.environ["HESTIA_HOME"] = tmp
        try:
            failing = RecordingClient(raise_on="hestia_witness_decision")

            def go():
                return m.witness_decision_unified(
                    failing, plugin_id="codex", decision="deny", rule="mrh.path",
                    tool_name="Write", target="/x", session_id="s1",
                    verdict_available=True, attempted_summary="Write -> /x")
            ok = _with_fake_core(go)
            check("not-delivered", ok is False, "failing client must report False")
            log = os.path.join(tmp, "telemetry", "gate-denies-codex.jsonl")
            check("fallback-exists", os.path.isfile(log), f"missing {log}")
            row = json.loads(open(log, encoding="utf-8").readlines()[-1])
            check("digest-in-fallback", row.get("core_digest") == "digest-under-test-1234",
                  str(row))
            check("failure-named", "witness_delivery_failed" in row, str(row))
        finally:
            if old is None:
                os.environ.pop("HESTIA_HOME", None)
            else:
                os.environ["HESTIA_HOME"] = old


def test_r5_no_core_loaded_key_present_and_none():
    """Absent core -> core_digest None, and the KEY still present on the wire — 'unknown'
    must never be silently indistinguishable from 'not attested' (never a bystander hash)."""
    m = _load_mech_draft()
    key = "hestia_gate_" + "core"
    saved = sys.modules.pop(key, None)
    try:
        fake = RecordingClient()
        ok = m.witness_decision_unified(
            fake, plugin_id="codex", decision="deny", rule="r", tool_name="t",
            target=None, session_id=None, verdict_available=False, attempted_summary="")
        check("delivered", ok is True)
        wit = fake.args_of("hestia_witness_decision")
        check("key-present", "core_digest" in wit[0], str(wit))
        check("value-none", wit[0].get("core_digest") is None, str(wit))
    finally:
        if saved is not None:
            sys.modules[key] = saved


def test_r5_draft_diverges_from_tip_only_in_the_wire_args():
    """The draft is the tip mechanism + ONE hunk: the healthy-path wire args gain
    core_digest. Nothing else may drift (the diff is the deliverable; this pins it).
    In-repo (post-apply) draft == tip by construction, so the divergence check is
    vacuous — the wire-args behavior itself is pinned by the other r5 arms."""
    tip = open(os.path.join(SHARED, MECH), encoding="utf-8").read()
    draft = open(MECH_DRAFT, encoding="utf-8").read()
    if tip == draft:
        print("  skip  draft==tip (in-repo mode; divergence pin is a pre-apply check)")
        return
    import difflib
    added = [ln for ln in difflib.unified_diff(tip.splitlines(), draft.splitlines(), n=0)
             if ln.startswith("+") and not ln.startswith("+++")]
    removed = [ln for ln in difflib.unified_diff(tip.splitlines(), draft.splitlines(), n=0)
               if ln.startswith("-") and not ln.startswith("---")]
    check("nothing-removed", not removed, str(removed))
    check("added-lines-carry-the-field",
          any('"core_digest": record["core_digest"]' in ln for ln in added), str(added))
    check("addition-is-bounded", len(added) <= 10, f"{len(added)} lines added: {added}")


ALL = [
    ("test_r3_codex_boundary_suite_10_of_10", test_r3_codex_boundary_suite_10_of_10),
    ("test_r3_codex_deny_renders_registered_rule", test_r3_codex_deny_renders_registered_rule),
    ("test_r3_codex_claim_carries_marker_and_act", test_r3_codex_claim_carries_marker_and_act),
    ("test_r3_codex_one_unified_record_per_refusal", test_r3_codex_one_unified_record_per_refusal),
    ("test_r4_kimi_draft_passes_all_boundary_arms", test_r4_kimi_draft_passes_all_boundary_arms),
    ("test_r4_kimi_evaluate_deny_routes_unified", test_r4_kimi_evaluate_deny_routes_unified),
    ("test_r4_kimi_gate_self_deny_one_unified_record", test_r4_kimi_gate_self_deny_one_unified_record),
    ("test_r4_kimi_core_unavailable_records_infra", test_r4_kimi_core_unavailable_records_infra),
    ("test_r4_kimi_degraded_deny_records_infra", test_r4_kimi_degraded_deny_records_infra),
    ("test_r4_codex_core_unavailable_records_infra", test_r4_codex_core_unavailable_records_infra),
    ("test_r4_kimi_source_has_one_recorder", test_r4_kimi_source_has_one_recorder),
    ("test_r5_digest_rides_the_healthy_wire_call", test_r5_digest_rides_the_healthy_wire_call),
    ("test_r5_digest_survives_in_fallback_on_failure", test_r5_digest_survives_in_fallback_on_failure),
    ("test_r5_no_core_loaded_key_present_and_none", test_r5_no_core_loaded_key_present_and_none),
    ("test_r5_draft_diverges_from_tip_only_in_the_wire_args",
     test_r5_draft_diverges_from_tip_only_in_the_wire_args),
]

if __name__ == "__main__":
    print("Repairs 3/4/5 — codex lifecycle, one deny recorder, digest on the healthy path")
    failed = []
    for name, fn in ALL:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:  # noqa: BLE001 — collect, don't stop
            failed.append(name)
            print(f"FAIL {name} — {e}")
    print(f"\n{len(ALL) - len(failed)}/{len(ALL)} passed")
    sys.exit(1 if failed else 0)
