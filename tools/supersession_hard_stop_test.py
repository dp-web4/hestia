#!/usr/bin/env python3
"""#1169: a superseded invocation stops at EVERY participating hook, in EVERY rollout mode.

GPT's hold on ca5f394: the daemon fences the ORIGINAL invocation when a reclaim re-delivers its
permit (begin_action answers `_hestia_error.code == "hestia.invocation_superseded"`), but the
shared mechanism folded that refusal into an ordinary no-verdict, and the codex and kimi hooks let
a no-verdict through in warn-rollout mode. So `claim A -> reclaim B -> A's begin is fenced` still
exited 0 for A in warn mode -- A ran, and B held the replacement permit.

Supersession is an INTEGRITY fence, not a policy verdict: the call's permit was transferred to
another invocation. It must stop the call regardless of rollout mode, the same way gate-self
itself is always enforced.

This drives the REAL codex and kimi `main()` and the REAL shared mechanism
(`claim_self_write` -> `query_society_safety` -> `_unwrap_tool_result`) against a stub daemon that
speaks the handler's exact wire shapes (`hestia_error_envelope`), with only the policy snapshot and
scope evaluation stubbed (they are unrelated to this boundary). For each seat x {warn, enforce}:

  A. claim A succeeds; B's reclaim lands before A's begin (the stub fences inv-A as the claim
     returns); A's begin is refused as superseded  -> the hook exits 2 (was 0 in warn);
  B. the REPLACEMENT invocation B (reclaimed permit, unfenced begin) -> exits 0: the fence does
     not stop the call that now owns the permit;
  C. an ORDINARY begin rejection in warn mode still warns and exits 0 -- the change is scoped to
     supersession, not a general change to warn-rollout;
  D. the claim declares `supersession: "hard_stop"` (the daemon refuses a reclaim without it).

Plus the mechanism alone: the superseded refusal is a verdict with `superseded=True`, keyed on the
machine-readable code (not message text), and the daemon's constant matches the mechanism's.

Runs as a script (CI executes discovered files directly).
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
SHARED = REPO / "plugins" / "_shared"
# A THROWAWAY home, set BEFORE any hook or mechanism import: the mechanism resolves its home at
# import, and both hooks keep tallies/identity under $HOME. Nothing here may reach a live seat.
_HOME = Path(tempfile.mkdtemp(prefix="supersede-home-"))
os.environ["HOME"] = str(_HOME)
os.environ["HESTIA_HOME"] = str(_HOME / ".hestia")
os.environ["HESTIA_SHARED_DIR"] = str(SHARED)
os.environ["HESTIA_WORKSPACE"] = str(_HOME)
for _k in ("HESTIA_ENDPOINT", "HESTIA_ROLE", "HESTIA_TEST_SABOTAGE"):
    os.environ.pop(_k, None)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


codex = _load("codex_ptu_supersede", REPO / "plugins" / "codex" / "hooks" / "pre_tool_use.py")
mech = codex._load_mechanism()  # the module object both hooks resolve (sys.modules-pinned)
kimi = _load("kimi_ptu_supersede", REPO / "plugins" / "kimi" / "hooks" / "pre_tool_use.py")
core = sys.modules["hestia_gate_core"]

FAILS: list[str] = []


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + ("" if ok else f"  <- {detail}"))
    if not ok:
        FAILS.append(name)


SUPERSEDED = "hestia.invocation_superseded"


class Stub(BaseHTTPRequestHandler):
    """The daemon, in its exact wire shapes. `fence_on_claim`: the invocation whose permit a
    reclaim re-delivers the moment its own claim returns -- the race GPT's re-review names."""
    claims: list = []
    begins: list = []
    fenced: set = set()
    fence_on_claim: str | None = None
    reclaim: bool = False
    begin_error: str | None = None   # an ordinary (non-supersession) begin rejection

    def log_message(self, *_a):
        pass

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0) or b"{}")
        params = body.get("params") or {}
        args = params.get("arguments") or {}
        name = params.get("name")
        payload: dict = {}
        if name == "hestia_connect":
            payload = {"sessionId": "S-1"}
        elif name == "hestia_gate_escalation_claim":
            Stub.claims.append(args)
            payload = {"claimed": True, "permits_write": True, "escalation_id": "E1",
                       "decided_by": "operator", "decided_via": "operator_session"}
            if Stub.reclaim:
                payload["reclaimed"] = True
            if Stub.fence_on_claim and args.get("invocation_key") == Stub.fence_on_claim:
                Stub.fenced.add(Stub.fence_on_claim)  # B's reclaim lands before A's begin
        elif name == "hestia_begin_action":
            Stub.begins.append(args)
            k = args.get("correlation_key")
            if k in Stub.fenced:
                # handler.rs tool_begin_action -> hestia_error_envelope(SUPERSEDED, ...)
                payload = {"_hestia_error": {
                    "code": SUPERSEDED,
                    "message": f"invocation {k} was superseded by a reclaim of escalation E1",
                    "data": {"correlation_key": k, "escalation_id": "E1", "fenced_at": 1}}}
            elif Stub.begin_error:
                payload = {"_hestia_error": {"code": Stub.begin_error, "message": "x", "data": {}}}
            else:
                payload = {"actionId": "act-" + str(k)}
        elif name == "hestia_query_policy":
            payload = {"status": "decided", "decision": "allow"}
        out = json.dumps({"jsonrpc": "2.0", "id": body.get("id", 1),
                          "result": {"content": [{"type": "text", "text": json.dumps(payload)}]}}).encode()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("mcp-session-id", "stub")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)
        except Exception:
            pass


def reset(**kw):
    Stub.claims, Stub.begins, Stub.fenced = [], [], set()
    Stub.fence_on_claim, Stub.reclaim, Stub.begin_error = None, False, None
    for k, v in kw.items():
        setattr(Stub, k, v)


# Unrelated layers, stubbed: the policy snapshot and scope evaluation decide nothing here. The
# governance classification is REAL (the target below is a governed path), so the hook takes its
# real gate-self claim path.
mech.fetch_policy_snapshot = lambda *a, **k: {"in_scope": [], "role": "citizen"}
core.evaluate = lambda *a, **k: SimpleNamespace(blocks=False)
core.resolve_agent_policy = lambda *a, **k: None
GOVERNED = str(_HOME / "hestia" / "plugins" / "_shared" / "hestia_gate_core.py")


def run_hook(hook, mode: str, inv: str):
    hook.MODE = mode
    event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "session_id": "hs-1",
             "tool_use_id": inv, "cwd": str(_HOME),
             "tool_input": {"command": f"cp /tmp/new_core.py {GOVERNED}"}}
    err = io.StringIO()
    code = None
    real_stdin = sys.stdin
    sys.stdin = io.StringIO(json.dumps(event))
    try:
        with contextlib.redirect_stderr(err):
            hook.main()
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    finally:
        sys.stdin = real_stdin
    return code, err.getvalue()


def main() -> int:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    os.environ["HESTIA_ENDPOINT"] = f"http://127.0.0.1:{srv.server_port}/mcp"

    print("0. the mechanism alone")
    reset(fenced={"inv-M"})
    v = mech.query_society_safety({"tool_name": "Bash", "tool_input": {"command": "true"}},
                                  plugin_id="codex", host_agent="codex", host_session_id="hs-1",
                                  correlation_key="inv-M")
    check("0 superseded begin -> not allowed", v.allow is False, v)
    check("0 ...and marked superseded (a distinct, unconditional stop)",
          getattr(v, "superseded", False) is True, v)
    check("0 ...keyed on the code: the constant is the daemon's",
          getattr(mech, "INVOCATION_SUPERSEDED", None) == SUPERSEDED,
          getattr(mech, "INVOCATION_SUPERSEDED", None))
    check("0 the daemon emits that exact code",
          f'"{SUPERSEDED}"' in (REPO / "core" / "src" / "server" / "handler.rs").read_text())
    reset(begin_error="hestia.some_other_rejection")
    v = mech.query_society_safety({"tool_name": "Bash", "tool_input": {"command": "true"}},
                                  plugin_id="codex", host_agent="codex", host_session_id="hs-1",
                                  correlation_key="inv-N")
    check("0 an ordinary begin rejection is NOT superseded",
          v.allow is False and getattr(v, "superseded", False) is False, v)

    for seat, hook in (("codex", codex), ("kimi", kimi)):
        for mode in ("warn", "enforce"):
            tag = f"{seat}/{mode}"
            print(f"{tag}")
            reset(fence_on_claim="inv-A")
            code, err = run_hook(hook, mode, "inv-A")
            check(f"A {tag} claim A was sent with inv-A",
                  [c.get("invocation_key") for c in Stub.claims] == ["inv-A"], Stub.claims)
            check(f"A {tag} the claim declares supersession hard_stop",
                  bool(Stub.claims) and Stub.claims[0].get("supersession") == "hard_stop", Stub.claims)
            check(f"A {tag} A's begin carried inv-A",
                  [b.get("correlation_key") for b in Stub.begins] == ["inv-A"], Stub.begins)
            check(f"A {tag} superseded A exits 2", code == 2, f"exit {code}; {err[-400:]}")
            check(f"A {tag} ...and says superseded, not warn-rollout",
                  "superseded" in err and "warn-rollout: allowed" not in err, err[-400:])

            reset(reclaim=True, fenced={"inv-A"})
            code, err = run_hook(hook, mode, "inv-B")
            check(f"B {tag} replacement B's begin carried inv-B",
                  [b.get("correlation_key") for b in Stub.begins] == ["inv-B"], Stub.begins)
            check(f"B {tag} replacement B is allowed (exit 0)", code == 0, f"exit {code}; {err[-400:]}")

        reset(begin_error="hestia.some_other_rejection")
        code, err = run_hook(hook, "warn", "inv-C")
        check(f"C {seat}/warn an ordinary no-verdict still warns (exit 0)",
              code == 0 and "warn-rollout" in err, f"exit {code}; {err[-400:]}")

    srv.shutdown()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): {FAILS}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
