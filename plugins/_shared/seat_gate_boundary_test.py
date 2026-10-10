#!/usr/bin/env python3
"""Every seat's REAL gate, executed the way its harness executes it, against a stub daemon.

One-gate stage C. Each seat's hook is now the certified template calling the common gate
(`hestia_single_gate.decide`), so the per-seat boundary suites (codex_gate_boundary_test,
kimi_gate_boundary_test), the internal-error and broken-engine proofs (decision_sabotage_test,
break_the_core_test) and their fixtures are migrated here, run on ALL FOUR seats, and kept:
these are the fail-closed safety proofs (#934 status list: "keep them, migrate the fixture, do
not retire").

Each shim runs as a SUBPROCESS: harness-native event JSON on stdin, its own projection
(`$HESTIA_HOME/seats/<member>.env`, its only config source), its own engine directory
(`HESTIA_SHARED_DIR`, a fixture copy of the runtime set so an arm can break it), and the
verdict read from the harness's own channel (exit 2 / stderr; gemini's decided policy deny is
exit 0 with a stdout JSON decision). The invoker declares the timeout it enforces
(HESTIA_HOOK_TIMEOUT_S), exactly what a non-harness caller must do; one arm removes it.

Arms, every seat (explicit list at the bottom):
  - a write whose destination is a gate file is refused before the daemon is asked: an
    escalation is claimed with the host session, `gate_self_access` witnessed, no begin_action;
  - the same through the seat's shell tool (and codex's apply_patch);
  - a claimed human approval lifts the closure bar for that one call, and ordinary law runs;
  - a distinctive governance name (the mechanism, the common gate) governs anywhere, while a
    hooks-dir-only name outside a hooks dir is ordinary work;
  - an ordinary write is asked of the daemon, allowed, and recorded as a committed decision
    carrying the action id and the correlation key;
  - a gate-file READ is allowed and witnessed as its own class (and still asks daemon law);
  - daemon down: a gate write is still refused as gate.self_access; an ordinary write fails
    closed (gate.degraded) on the anomaly channel;
  - a missing engine and a poisoned engine block Read AND Write (gate.bootstrap_unavailable);
  - an internal error at DECISION time denies Read and Write in enforce AND warn rollout
    (gate.internal_error, recorded: no verdict, no act);
  - an unknown harness timeout is refused at once, without a daemon call;
  - an empty event, a missing projection: refused before anything else.

check() RAISES so pytest sees each case; the __main__ runner collects.
Staging seams (unset in the repo and in CI): HESTIA_CONTRACT_REPO, HESTIA_CONTRACT_OVERLAY
({module: path}, copied over the fixture engine), HESTIA_CONTRACT_SHIMS ({seat: path}).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("HESTIA_CONTRACT_REPO") or os.path.abspath(os.path.join(HERE, os.pardir, os.pardir))
SHARED = os.path.join(REPO, "plugins", "_shared")
OVERLAY = json.loads(os.environ.get("HESTIA_CONTRACT_OVERLAY") or "{}")
SHIM_OVERRIDE = json.loads(os.environ.get("HESTIA_CONTRACT_SHIMS") or "{}")
HOOK = "pre_" + "tool_use.py"
GEM_HOOK = "before_" + "tool.py"
CORE = "hestia_gate_" + "core.py"
MECH = "hestia_gate_" + "mechanism.py"
GATE = "hestia_single_" + "gate.py"
SEATS = {
    "claude-code": {"member": "claude-code", "hook": ("claude-code", HOOK), "home": ".claude",
                    "identity": "HESTIA_CLAUDE_IDENTITY"},
    "codex": {"member": "codex", "hook": ("codex", HOOK), "home": ".codex",
              "identity": "HESTIA_CODEX_IDENTITY"},
    "kimi": {"member": "kimi-code", "hook": ("kimi", HOOK), "home": ".kimi-code",
             "identity": "HESTIA_KIMI_IDENTITY"},
    "gemini": {"member": "gemini", "hook": ("gemini", GEM_HOOK), "home": ".gemini",
               "identity": "HESTIA_GEMINI_IDENTITY"},
}


def check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name} — {str(detail)[:900]}")


def shim(seat):
    if seat in SHIM_OVERRIDE:
        return SHIM_OVERRIDE[seat]
    d, f = SEATS[seat]["hook"]
    return os.path.join(REPO, "plugins", d, "hooks", f)


# ── stub daemon (the real wire shape: every reply a `result` with structuredContent) ────────

class Stub:
    def __init__(self, claim=None, verdict="allow"):
        self.claim = claim
        self.verdict = verdict
        self.calls = []
        self.lock = threading.Lock()
        stub = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                method = body.get("method")
                if isinstance(method, str) and method.startswith("notifications/"):
                    self.send_response(202)
                    self.end_headers()
                    return
                if method == "initialize":
                    out = {"jsonrpc": "2.0", "id": body.get("id"), "result": {
                        "protocolVersion": "2024-11-05", "capabilities": {},
                        "serverInfo": {"name": "seat-boundary-stub", "version": "0"}}}
                else:
                    p = body.get("params") or {}
                    name, args = p.get("name"), p.get("arguments") or {}
                    with stub.lock:
                        stub.calls.append((name, args))
                    payload = stub.respond(name, args)
                    out = {"jsonrpc": "2.0", "id": body.get("id"), "result": {
                        "structuredContent": payload,
                        "content": [{"type": "text", "text": json.dumps(payload)}]}}
                data = json.dumps(out).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("mcp-session-id", "stub-mcp")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/mcp"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def respond(self, name, args):
        if name == "hestia_connect":
            return {"sessionId": "s-" + uuid.uuid4().hex[:8], "role": "role:constellation:member"}
        if name == "hestia_operating_law":
            return {"identity": {"role": "role:constellation:member"}}
        if name == "hestia_scope_status":
            return {"live_grants": [], "standing_grants": [], "society_floor": []}
        if name == "hestia_begin_action":
            return {"actionId": str(uuid.uuid4())}
        if name == "hestia_query_policy":
            return {"status": "decided", "decision": self.verdict, "enforced": True,
                    "ruleName": "stub.policy", "reason": f"stub rules {self.verdict}"}
        if name == "hestia_gate_escalation_claim":
            if self.claim is not None:
                return self.claim
            return {"claimed": False, "permits_write": False, "escalation_id": "esc-stub-1",
                    "how_to_decide": "hestia gate approve esc-stub-1"}
        if name == "hestia_request_witness":
            return {"ok": True, "witnessEntryHash": "c" * 64}
        if name == "hestia_witness_decision":
            d = args.get("decision")
            return {"witnessEntryHash": "b" * 64, "decision": d,
                    "eventType": "policy_allow" if d == "allow" else "policy_decision",
                    "recorded": "appended", "actionId": args.get("action_id"),
                    "correlationKey": args.get("correlation_key")}
        return {"ok": True}

    def names(self):
        return [n for n, _ in self.calls]

    def args(self, name):
        return [a for n, a in self.calls if n == name]


DEAD = "http://127.0.0.1:9/mcp"   # discard port: closed by convention, nothing binds it here


# ── fixture ──────────────────────────────────────────────────────────────────────────────────

class Fixture:
    """One throwaway installation: a workspace (NOT under /tmp: temp roots are always in scope,
    which would green a scope check for the wrong reason), an engine dir, a seat home."""

    def __init__(self):
        base = os.path.expanduser("~/.cache/hestia-seat-boundary-tests")
        os.makedirs(base, exist_ok=True)
        self.root = tempfile.mkdtemp(dir=base)
        self.ws = os.path.join(self.root, "ws")
        self.repo = os.path.join(self.ws, "hestia")
        for d in (("plugins", "codex", "hooks"), ("plugins", "_shared"), ("forum", "x"), ("docs",)):
            os.makedirs(os.path.join(self.repo, *d), exist_ok=True)
        self.engine = os.path.join(self.root, "engine")
        os.makedirs(self.engine)
        names = [ln.strip() for ln in open(os.path.join(SHARED, "RUNTIME_MANIFEST.txt"), encoding="utf-8")
                 if ln.strip() and not ln.lstrip().startswith("#")]
        for name in dict.fromkeys(names + [m + ".py" for m in OVERLAY]):
            shutil.copyfile(OVERLAY.get(name[:-3]) or os.path.join(SHARED, name),
                            os.path.join(self.engine, name))

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def poison(self, module_file, body, append=False):
        path = os.path.join(self.engine, module_file)
        with open(path, "a" if append else "w", encoding="utf-8") as fh:
            fh.write(body)

    def home(self, seat, endpoint, rollout="enforce", engine=None, projection=True):
        cfg = SEATS[seat]
        home = os.path.join(self.root, "home-" + uuid.uuid4().hex[:8])
        os.makedirs(os.path.join(home, "seats"))
        os.makedirs(os.path.join(home, cfg["home"]), exist_ok=True)
        token = "".join(c.upper() if c.isalnum() else "_" for c in cfg["member"])
        with open(os.path.join(home, "identity.json"), "w", encoding="utf-8") as fh:
            json.dump({"role": "role:constellation:member"}, fh)
        if projection:
            lines = [f"HESTIA_HOME={home}", f"HESTIA_SHARED_DIR={engine or self.engine}",
                     f"HESTIA_WORKSPACE={self.ws}", f"HESTIA_ENDPOINT={endpoint}",
                     f"{token}__HESTIA_HARNESS_HOME={os.path.join(home, cfg['home'])}",
                     f"{token}__{cfg['identity']}={os.path.join(home, 'identity.json')}",
                     f"{token}__HESTIA_OBSERVE_DIR={os.path.join(home, 'observe')}",
                     f"{token}__HESTIA_GATE_MODE={rollout}"]
            with open(os.path.join(home, "seats", cfg["member"] + ".env"), "w", encoding="utf-8") as fh:
                fh.write("# seat-boundary fixture\n" + "\n".join(lines) + "\n")
        return home


def native(seat, tool, ti, n=1):
    """The act in this harness's own event shape."""
    sid = "seat-boundary-session"
    if seat == "codex":
        if tool in ("Write", "Edit"):
            verb = "Update" if tool == "Edit" else "Add"
            tool, ti = "apply_patch", {"input": f"*** Begin Patch\n*** {verb} File: {ti['file_path']}\n+x\n*** End Patch\n"}
        elif tool == "Read":
            tool, ti = "bash", {"command": f"cat {ti['file_path']}"}
        elif tool == "Bash":
            tool = "bash"
        return {"hook_event_name": "PreToolUse", "session_id": sid, "turn_id": f"t{n}", "cwd": "",
                "tool_name": tool, "tool_input": ti, "tool_use_id": f"call_sb{n}"}
    if seat == "kimi":
        ti = dict(ti)
        if "file_path" in ti:
            ti["path"] = ti.pop("file_path")
        return {"hook_event_name": "PreToolUse", "session_id": sid, "cwd": "", "tool_name": tool,
                "tool_input": ti, "tool_call_id": f"tool_sb{n}"}
    if seat == "gemini":
        gtool = {"Read": "read_file", "Write": "write_file", "Edit": "replace",
                 "Bash": "run_shell_command"}.get(tool, tool)
        ti = dict(ti)
        if "file_path" in ti and gtool == "read_file":
            ti["absolute_path"] = ti.pop("file_path")
        return {"hook_event_name": "BeforeTool", "session_id": sid, "cwd": "", "tool_name": gtool,
                "tool_input": ti, "timestamp": "2026-10-04T00:00:00Z"}
    return {"hook_event_name": "PreToolUse", "session_id": sid, "cwd": "", "tool_name": tool,
            "tool_input": ti, "tool_use_id": f"toolu_sb{n}"}


def run(seat, home, event, *, declare=True, stdin=None, cwd=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("HESTIA_")}
    env.update({"HOME": home, "HESTIA_HOME": home, "PYTHONDONTWRITEBYTECODE": "1"})
    env.pop("PYTHONPATH", None)
    if declare:
        env["HESTIA_HOOK_TIMEOUT_S"] = "20"
    # Launched in the fixture's repo, as a harness launched in a task repo is: the launch-cwd
    # grant (the core's launch_cwd_repo) is what puts that repo in scope.
    cwd = cwd or os.path.join(os.path.dirname(home), "ws", "hestia")
    p = subprocess.run([sys.executable, shim(seat)], input=stdin if stdin is not None else json.dumps(event),
                       capture_output=True, text=True, timeout=60, env=env, cwd=cwd)
    try:
        payload = json.loads(p.stdout.strip() or "null")
    except ValueError:
        payload = None
    if isinstance(payload, dict) and payload.get("decision") == "deny":
        verdict = "deny"
    elif p.returncode == 2:
        verdict = "deny"
    elif p.returncode == 0:
        verdict = "allow"
    else:
        verdict = f"rc{p.returncode}"   # any other exit is a fail-OPEN on these harnesses
    text = p.stderr + "\n" + (payload.get("reason", "") if isinstance(payload, dict) else p.stdout)
    channel = "policy-json" if isinstance(payload, dict) else f"exit{p.returncode}"
    return verdict, text, channel


def gate_file(fx, seat):
    d = SEATS[seat]["hook"][0]
    return os.path.join(fx.repo, "plugins", d, "hooks", SEATS[seat]["hook"][1])


def _each_seat(arm):
    for seat in SEATS:
        fx, stub = Fixture(), None
        try:
            arm(seat, fx)
        finally:
            fx.close()


# ── arms ─────────────────────────────────────────────────────────────────────────────────────

def test_gate_file_write_refused_before_the_daemon():
    def arm(seat, fx):
        stub = Stub()
        try:
            home = fx.home(seat, stub.url)
            v, text, _ = run(seat, home, native(seat, "Write", {"file_path": gate_file(fx, seat), "content": "x"}))
            check(f"{seat}-denied", v == "deny", text)
            check(f"{seat}-rule", "gate.self_access" in text, text)
            check(f"{seat}-escalation-surfaced", "esc-stub-1" in text, text)
            claims = stub.args("hestia_gate_escalation_claim")
            check(f"{seat}-claim-made", len(claims) == 1, stub.names())
            check(f"{seat}-claim-carries-host-session",
                  claims and claims[0].get("host_session_id") == "seat-boundary-session", claims)
            check(f"{seat}-claim-declares-hard-stop", claims and claims[0].get("supersession") == "hard_stop", claims)
            # #810 (recut of #812): the claim carries the closure's resolved targets — the
            # write-position paths, which name the file even when the marker is a directory.
            check(f"{seat}-claim-carries-resolved-target",
                  claims and claims[0].get("resolved_targets") == [gate_file(fx, seat)], claims)
            check(f"{seat}-witnessed", any(a.get("event_type") == "gate_self_access"
                                           for a in stub.args("hestia_request_witness")), stub.calls)
            check(f"{seat}-pre-daemon", "hestia_begin_action" not in stub.names(), stub.names())
        finally:
            stub.close()
    _each_seat(arm)


def test_gate_file_shell_write_refused():
    def arm(seat, fx):
        stub = Stub()
        try:
            home = fx.home(seat, stub.url)
            v, text, _ = run(seat, home, native(seat, "Bash", {"command": f"echo pwned > {gate_file(fx, seat)}"}))
            check(f"{seat}-denied", v == "deny" and "gate.self_access" in text, text)
            check(f"{seat}-claim-made", "hestia_gate_escalation_claim" in stub.names(), stub.names())
            claims = stub.args("hestia_gate_escalation_claim")
            check(f"{seat}-shell-claim-carries-resolved-target",
                  claims and [str(x) for x in claims[0].get("resolved_targets", [])][-1:]
                  and str(claims[0]["resolved_targets"][-1]).endswith(
                      os.path.basename(gate_file(fx, seat))), claims)
            # Codex P1-2 on #1239: an ORDINARY governed target first, padding past the summary's
            # bound, the seat's gate LAST. The closure reports the first; the claim must carry
            # every governed target, so the daemon can price the gate.
            mark = len(stub.calls)
            ordinary = os.path.join(fx.repo, "plugins", "_shared", "ordinary.txt")
            pad = " ".join(os.path.join(fx.repo, "docs", f"pad{i}.txt") for i in range(25))
            v2, text2, _ = run(seat, home, native(seat, "Bash", {
                "command": f"touch {ordinary} {pad} {gate_file(fx, seat)}"}, n=2))
            check(f"{seat}-multi-denied", v2 == "deny" and "gate.self_access" in text2, text2)
            multi = [a for n, a in stub.calls[mark:] if n == "hestia_gate_escalation_claim"]
            check(f"{seat}-multi-claim-carries-every-governed-target",
                  multi and multi[0].get("resolved_targets") == [ordinary, gate_file(fx, seat)],
                  multi)
            check(f"{seat}-multi-summary-lost-the-gate (the case the targets exist for)",
                  multi and os.path.basename(gate_file(fx, seat)) not in multi[0].get("reason", ""),
                  multi)
            # The glob row (kimi, #1231 Q4): `rm <hooks dir>/*.py` is refused, and the claim
            # carries the glob as written — the daemon prices it by what it can expand to.
            mark = len(stub.calls)
            glob = os.path.join(os.path.dirname(gate_file(fx, seat)), "*.py")
            v3, text3, _ = run(seat, home, native(seat, "Bash", {"command": f"rm {glob}"}, n=3))
            check(f"{seat}-glob-denied", v3 == "deny" and "gate.self_access" in text3, text3)
            g = [a for n, a in stub.calls[mark:] if n == "hestia_gate_escalation_claim"]
            check(f"{seat}-glob-claim-carries-the-glob",
                  g and g[0].get("resolved_targets") == [glob], g)
            # Codex notice 17632, P1-2: an ALIAS the closure recognized by its destination. The
            # claim carries the destination too, not only the alias spelling.
            alias = os.path.join(fx.repo, "docs", "alias.txt")
            os.makedirs(os.path.dirname(alias), exist_ok=True)
            os.symlink(gate_file(fx, seat), alias)
            mark = len(stub.calls)
            v3, text3, _ = run(seat, home, native(seat, "Bash", {"command": f"touch {alias}"}, n=3))
            check(f"{seat}-alias-denied", v3 == "deny" and "gate.self_access" in text3, text3)
            al = [a for n, a in stub.calls[mark:] if n == "hestia_gate_escalation_claim"]
            check(f"{seat}-alias-claim-carries-the-destination",
                  al and al[0].get("resolved_targets") == [alias, os.path.realpath(gate_file(fx, seat))],
                  al)
            # P1-1: out of grammar, the matched token is vocabulary, not a resolved path: the
            # write set is unenumerated and says so, beside the target that is known.
            mark = len(stub.calls)
            var = os.path.join(fx.repo, "plugins", "_shared", "$TARGET")
            v4, text4, _ = run(seat, home, native(seat, "Bash", {"command": f"touch {var}"}, n=4))
            check(f"{seat}-out-of-grammar-denied", v4 == "deny" and "gate.self_access" in text4, text4)
            og = [a for n, a in stub.calls[mark:] if n == "hestia_gate_escalation_claim"]
            check(f"{seat}-out-of-grammar-claim-is-unenumerated",
                  og and og[0].get("resolved_targets", [])[-1:] == ["hestia:unpriceable:unenumerated"],
                  og)
            if seat == "codex":
                patch = (f"*** Begin Patch\n*** Update File: {gate_file(fx, seat)}\n@@\n-a\n+b\n"
                         "*** End Patch\n")
                ev = dict(native(seat, "Bash", {"command": "true"}), tool_name="apply_patch",
                          tool_input={"input": patch})
                v, text, _ = run(seat, home, ev)
                check("codex-apply_patch-denied", v == "deny" and "gate.self_access" in text, text)
        finally:
            stub.close()
    _each_seat(arm)


def test_approved_gate_write_proceeds_to_ordinary_law():
    def arm(seat, fx):
        stub = Stub(claim={"claimed": True, "permits_write": True, "decided_by": "test-operator",
                           "decided_via": "test"})
        try:
            home = fx.home(seat, stub.url)
            v, text, _ = run(seat, home, native(seat, "Write", {"file_path": gate_file(fx, seat), "content": "x"}))
            check(f"{seat}-allowed", v == "allow", text)
            check(f"{seat}-approval-noted", "APPROVED" in text, text)
            check(f"{seat}-ordinary-law-ran", "hestia_begin_action" in stub.names(), stub.names())
        finally:
            stub.close()
    _each_seat(arm)


def test_distinctive_names_govern_anywhere_hooks_only_names_do_not():
    def arm(seat, fx):
        stub = Stub()
        try:
            home = fx.home(seat, stub.url)
            for name in (MECH, GATE):
                target = os.path.join(fx.repo, "docs", name)
                v, text, _ = run(seat, home, native(seat, "Write", {"file_path": target, "content": "x"}))
                check(f"{seat}-{name}-anywhere-denied", v == "deny" and "gate.self_access" in text, text)
            mark = len(stub.calls)
            target = os.path.join(fx.repo, "docs", "wit" + "ness.py")
            v, text, _ = run(seat, home, native(seat, "Write", {"file_path": target, "content": "x"}))
            check(f"{seat}-hooks-only-name-is-ordinary", v == "allow", text)
            check(f"{seat}-no-claim", "hestia_gate_escalation_claim" not in [n for n, _ in stub.calls[mark:]],
                  stub.calls[mark:])
        finally:
            stub.close()
    _each_seat(arm)


def test_ordinary_write_is_asked_allowed_and_recorded():
    def arm(seat, fx):
        stub = Stub()
        try:
            home = fx.home(seat, stub.url)
            target = os.path.join(fx.repo, "forum", "x", "post.md")
            v, text, _ = run(seat, home, native(seat, "Write", {"file_path": target, "content": "x"}, n=7))
            check(f"{seat}-allowed", v == "allow", text)
            begins = stub.args("hestia_begin_action")
            recs = stub.args("hestia_witness_decision")
            check(f"{seat}-asked-once", len(begins) == 1, stub.names())
            check(f"{seat}-recorded-once-as-allow", [r.get("decision") for r in recs] == ["allow"], recs)
            check(f"{seat}-record-joins-the-action", recs and recs[0].get("action_id"), recs)
            check(f"{seat}-one-key-everywhere", recs and begins
                  and recs[0].get("correlation_key") == begins[0].get("correlation_key")
                  and recs[0].get("correlation_key"), (begins, recs))
            check(f"{seat}-asks-as-itself", all(a.get("plugin_id") == SEATS[seat]["member"]
                                                for a in stub.args("hestia_connect")), stub.args("hestia_connect"))
        finally:
            stub.close()
    _each_seat(arm)


def test_gate_file_read_allowed_and_witnessed():
    def arm(seat, fx):
        stub = Stub()
        try:
            home = fx.home(seat, stub.url)
            v, text, _ = run(seat, home, native(seat, "Read", {"file_path": gate_file(fx, seat)}))
            check(f"{seat}-allowed", v == "allow", text)
            check(f"{seat}-witnessed-as-read", any(a.get("event_type") == "gate_self_read"
                                                   for a in stub.args("hestia_request_witness")), stub.calls)
            check(f"{seat}-reads-meet-daemon-law", "hestia_begin_action" in stub.names(), stub.names())
        finally:
            stub.close()
    _each_seat(arm)


def test_daemon_down():
    def arm(seat, fx):
        home = fx.home(seat, DEAD)
        v, text, _ = run(seat, home, native(seat, "Write", {"file_path": gate_file(fx, seat), "content": "x"}))
        check(f"{seat}-gate-write-still-gate-self", v == "deny" and "gate.self_access" in text, text)
        target = os.path.join(fx.repo, "forum", "x", "post.md")
        v, text, channel = run(seat, home, native(seat, "Write", {"file_path": target, "content": "x"}))
        check(f"{seat}-ordinary-write-fails-closed", v == "deny" and "gate.degraded" in text, text)
        check(f"{seat}-on-the-anomaly-channel", channel == "exit2", channel)
        v, text, _ = run(seat, home, native(seat, "Read", {"file_path": target}))
        check(f"{seat}-read-fails-closed-too", v == "deny" and "gate.degraded" in text, text)
    _each_seat(arm)


def test_missing_and_poisoned_engine_block():
    def arm(seat, fx):
        stub = Stub()
        try:
            empty = os.path.join(fx.root, "no-engine")
            os.makedirs(empty)
            home = fx.home(seat, stub.url, engine=empty)
            target = os.path.join(fx.repo, "forum", "x", "post.md")
            for tool, ti in (("Write", {"file_path": target, "content": "x"}), ("Read", {"file_path": target})):
                v, text, channel = run(seat, home, native(seat, tool, ti))
                check(f"{seat}-missing-{tool}", v == "deny" and "gate.bootstrap_unavailable" in text, text)
                check(f"{seat}-missing-{tool}-exit2", channel == "exit2", channel)
            fx.poison(CORE, "raise ImportError('seat-boundary: sabotaged core')\n")
            home = fx.home(seat, stub.url)
            for tool, ti in (("Write", {"file_path": target, "content": "x"}), ("Read", {"file_path": target})):
                v, text, _ = run(seat, home, native(seat, tool, ti))
                check(f"{seat}-poisoned-{tool}", v == "deny" and "gate.bootstrap_unavailable" in text, text)
            check(f"{seat}-nothing-asked", stub.calls == [], stub.calls)
        finally:
            stub.close()
    _each_seat(arm)


def test_decision_time_internal_error_denies_in_every_rollout():
    def arm(seat, fx):
        stub = Stub()
        try:
            fx.poison(CORE, "\n\ndef evaluate(*_a, **_k):\n"
                            "    raise RuntimeError('seat-boundary: injected decision-time fault')\n",
                      append=True)
            target = os.path.join(fx.repo, "forum", "x", "post.md")
            for rollout in ("enforce", "warn"):
                home = fx.home(seat, stub.url, rollout=rollout)
                for tool, ti in (("Write", {"file_path": target, "content": "x"}), ("Read", {"file_path": target})):
                    mark = len(stub.calls)
                    v, text, _ = run(seat, home, native(seat, tool, ti))
                    check(f"{seat}-{rollout}-{tool}-denied", v == "deny" and "gate.internal_error" in text, text)
                    recs = [a for n, a in stub.calls[mark:] if n == "hestia_witness_decision"]
                    check(f"{seat}-{rollout}-{tool}-recorded",
                          [r.get("rule_id") for r in recs] == ["gate.internal_error"], recs)
        finally:
            stub.close()
    _each_seat(arm)


def test_unknown_harness_timeout_refused_without_asking():
    def arm(seat, fx):
        stub = Stub()
        try:
            home = fx.home(seat, stub.url)
            target = os.path.join(fx.repo, "forum", "x", "post.md")
            v, text, channel = run(seat, home, native(seat, "Read", {"file_path": target}), declare=False)
            check(f"{seat}-denied", v == "deny" and "gate.harness_timeout_unknown" in text, text)
            check(f"{seat}-exit2", channel == "exit2", channel)
            check(f"{seat}-no-daemon-call", stub.calls == [], stub.calls)
        finally:
            stub.close()
    _each_seat(arm)


def test_no_event_and_no_projection_are_refused_first():
    def arm(seat, fx):
        stub = Stub()
        try:
            home = fx.home(seat, stub.url)
            v, text, _ = run(seat, home, None, stdin="")
            check(f"{seat}-empty-event", v == "deny" and "gate.event_unreadable" in text, text)
            v, text, _ = run(seat, home, None, stdin="not json")
            check(f"{seat}-unparseable-event", v == "deny" and "gate.event_unreadable" in text, text)
            bare = fx.home(seat, stub.url, projection=False)
            v, text, _ = run(seat, bare, native(seat, "Read", {"file_path": os.path.join(fx.repo, "docs")}))
            check(f"{seat}-no-projection", v == "deny" and "config.unbacked" in text, text)
            check(f"{seat}-nothing-asked", stub.calls == [], stub.calls)
        finally:
            stub.close()
    _each_seat(arm)


ALL = [
    test_gate_file_write_refused_before_the_daemon,
    test_gate_file_shell_write_refused,
    test_approved_gate_write_proceeds_to_ordinary_law,
    test_distinctive_names_govern_anywhere_hooks_only_names_do_not,
    test_ordinary_write_is_asked_allowed_and_recorded,
    test_gate_file_read_allowed_and_witnessed,
    test_daemon_down,
    test_missing_and_poisoned_engine_block,
    test_decision_time_internal_error_denies_in_every_rollout,
    test_unknown_harness_timeout_refused_without_asking,
    test_no_event_and_no_projection_are_refused_first,
]

if __name__ == "__main__":
    print("seat gate boundary — every seat's real gate, executed, fails closed")
    failed = []
    for t in ALL:
        try:
            t()
            print("PASS", t.__name__)
        except Exception as e:  # noqa: BLE001 — collect, don't stop
            failed.append(t.__name__)
            print("FAIL", t.__name__, "::", e)
    print()
    if failed:
        print(f"FAILURES: {failed}")
        sys.exit(1)
    print(f"OK — {len(ALL)} tests x {len(SEATS)} seats")
