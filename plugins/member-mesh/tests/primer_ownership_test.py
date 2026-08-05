#!/usr/bin/env python3
"""A work list that records who SENT every notice, and never who it is FOR.

WHAT HAPPENED (CBP, 2026-07-31). Kimi was woken at 17:35Z by `watch-kimi-code`
with a primer digest whose every row was Codex's mail: notice 215
(claude-code->codex), unanswered 126/127 (claude-code->codex) and 160
(codex->claude-code). Kimi read the pointers, found it could not bind a reply --
`member_notify_reply_binding_not_yours`, the daemon correctly refusing to let a
peer clear another member's row -- and flagged the routing as an anomaly it could
not diagnose from inside the session. Its two hypotheses were a human routing
around a dead watcher, or a watcher/member-id mix-up. It was neither.

`hestia-watch-member.sh` keeps primers in `$STATE/primers/`, where `$STATE` is
`$HOME/.local/state/hestia-mesh` -- ONE directory for every member on the host.
`mktemp notice-XXXXXX.json` names them randomly, and the JSON body records
`from_plugin` on every notice and the recipient NOWHERE. The startup
stale-retry loop then globs `"$STATE"/primers/notice-*.json` -- the whole shared
directory -- and re-fires every file it finds through ITS OWN `$FIRE`.

So delivery of a retained primer is decided by whichever watcher's glob reaches
the file first. From the journals, 2026-07-31, all three watchers having started
at 10:34 local:

    10:35:39  watch-kimi-code  RETRYING stale primer  notice-55IU9T.json  (1/3)
    10:40:45  watch-codex      RETRYING stale primer  notice-55IU9T.json  (2/3)
    10:42:12  watch-codex      stale primer DELIVERED on retry
    10:45:05  watch-kimi-code  stale primer DELIVERED on retry

One consume-once work list, fired into two different members' CLIs, both
watchers recording success. Note the attempt numbers: the `.attempts` sidecar is
in the shared directory too, so `STALE_MAX_ATTEMPTS=3` is a budget spent by all
members jointly, and a primer can be set aside `.exhausted` on failures its own
member never had. At the time of writing that directory held 24 stranded
primers, intermixed: 13 attributable to claude-code, 3 to codex, 1 to kimi-code,
and 7 attributable to nobody -- because the `unanswered` fold at line 236 is the
only thing in the file that names an owner, and it has a fallback path that
writes the drain result alone.

The recovery mechanism is what misdelivers. Stale-primer retry was added
(d2d23ba) because a batch that failed once was stranded permanently -- a real
fix for a real defect, which introduced this one by retrying from a namespace it
did not own.

Four properties, all behavioural against the real scripts with stubbed CLIs and
a stubbed daemon -- no test seam, so this cannot pass by exercising a path only
the test uses:

  1. MISDELIVERY. A primer retained by one member's watcher is never fired by
     another's. This is the case that was red on 2026-07-31.
  2. THE ATTEMPT BUDGET IS THE MEMBER'S OWN. One member's failed retries must not
     consume another's.
  3. THE ARTIFACT NAMES ITS OWNER. The primer JSON carries `for_plugin`, on the
     fold path AND on the fallback path where the unanswered RPC fails -- the
     fallback is exactly how the 7 unattributable files were written, so a stamp
     that only survives the happy path re-creates them.
  4. THE LAUNCHER REFUSES SOMEONE ELSE'S MAIL. Handed a primer stamped for
     another member, a fire template exits non-zero (so the consume-once list is
     RETAINED, never deleted) and does not launch the CLI.

(3) and (4) are defence in depth: (1) is the structural fix and would hold
without them. They exist because the failure this file is about was invisible
for four days -- notice 160 reported Codex unreachable on 2026-07-27 and the
mail kept being misrouted -- and what made it invisible is that the artifact
could not be asked who it belonged to.

Usage: ./primer_ownership_test.py     (runtime ~10s)
"""
import http.server
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
MESH = os.path.abspath(os.path.join(HERE, ".."))
WATCHER = os.path.join(MESH, "hestia-watch-member.sh")

EX_REFUSED = 70

failures = []


def check(label, ok, detail=""):
    if not ok:
        failures.append(label)
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if detail and not ok else ""))


# --------------------------------------------------------------------------
# Stub daemon. Speaks just enough MCP for hestia-watch-member.sh's mesh_rpc:
# initialize (with an mcp-session-id header), notifications/initialized, and
# tools/call answering in SSE `data:` frames.
#
# The inbox and the unanswered rows are keyed on the plugin_id passed to
# hestia_connect, so each member sees only its own -- which is what the real
# daemon does, and is the oracle this test uses to say whose primer a file is.
# --------------------------------------------------------------------------
INBOX = {}
UNANSWERED = {}


class Stub(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or "{}")
        method = body.get("method")
        if method == "initialize":
            self._json({"jsonrpc": "2.0", "id": body.get("id"), "result": {}},
                       extra={"mcp-session-id": "stub-session"})
            return
        if method == "notifications/initialized":
            self._json({})
            return
        params = body.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        if name == "hestia_connect":
            self.plugin = args.get("plugin_id")
            payload = {"sessionId": "sess::" + str(args.get("plugin_id"))}
        else:
            plugin = str(args.get("session_id", "")).split("::", 1)[-1]
            if name == "hestia_member_inbox":
                notices = INBOX.pop(plugin, [])
                payload = {"notices": notices, "total": len(notices), "evicted": 0, "peeked": False}
            elif name == "hestia_member_unanswered":
                payload = UNANSWERED.get(plugin, {"i_owe": [], "owed_to_me": []})
                if payload is FAIL_UNANSWERED:
                    self.send_response(500)
                    self.end_headers()
                    return
            else:
                payload = {}
        self._sse({"jsonrpc": "2.0", "id": body.get("id"),
                   "result": {"content": [{"type": "text", "text": json.dumps(payload)}]}})

    def _json(self, obj, extra=None):
        raw = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _sse(self, obj):
        raw = ("data: " + json.dumps(obj) + "\n\n").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


FAIL_UNANSWERED = object()


def start_stub():
    srv = http.server.HTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/mcp"


# --------------------------------------------------------------------------
# Stub fire templates. `recorder` writes each primer path it is handed (and the
# JSON it contained) to a log and succeeds; `refuser` records and exits 70, the
# code a real template uses for "nothing fireworthy", so the primer is retained.
# --------------------------------------------------------------------------
def write_fire(path, log, rc):
    with open(path, "w") as f:
        f.write(f'''#!/usr/bin/env bash
python3 - "$1" "{log}" <<'PY'
import json,sys
try: d=json.load(open(sys.argv[1]))
except Exception: d={{}}
open(sys.argv[2],"a").write(json.dumps({{"primer":sys.argv[1],"body":d}})+"\\n")
PY
exit {rc}
''')
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def fired(log):
    if not os.path.exists(log):
        return []
    with open(log) as f:
        return [json.loads(l) for l in f if l.strip()]


def owner_of(body):
    """Whose work list is this? Structural, not a guess: `i_owe` rows are
    addressed TO the owner and `owed_to_me` rows are FROM it."""
    who = set()
    u = body.get("unanswered") or {}
    for r in u.get("i_owe") or []:
        who.add(r.get("to_plugin"))
    for r in u.get("owed_to_me") or []:
        who.add(r.get("from_plugin"))
    return who


def run_watcher(plugin, fire, env, log, want, secs=60):
    """Run the real watcher until it has fired `want` times, then stop it.

    It loops forever by design, so something has to end it. That something must
    NOT be a fixed sleep: at 6s this was a coin flip on a loaded host -- green in
    one tree and red in another within the same minute -- and a probabilistic red
    is worse than no test, because the next reader learns to re-run it. So every
    case gives its member something of its own to do and waits for the observable
    that says the startup pass and a drain both completed. The ceiling is a
    backstop for a hang, never the thing being measured.
    """
    p = subprocess.Popen([WATCHER, plugin, f"{plugin}-watch", fire],
                         env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    deadline = time.time() + secs
    while time.time() < deadline and len(fired(log)) < want:
        if p.poll() is not None:
            break
        time.sleep(0.2)
    p.kill()
    out, _ = p.communicate()
    return out


def base_env(state, ep):
    e = dict(os.environ)
    e.update(HESTIA_MESH_STATE=state, HESTIA_ENDPOINT=ep,
             WATCH_INTERVAL="1", UNANSWERED_EVERY="99999", HOME=state)
    return e


def main():
    srv, ep = start_stub()
    tmp = tempfile.mkdtemp(prefix="primer-own-")
    state = os.path.join(tmp, "state")
    os.makedirs(state)
    env = base_env(state, ep)

    recorder = os.path.join(tmp, "fire-record.sh")
    refuser = os.path.join(tmp, "fire-refuse.sh")
    codex_log = os.path.join(tmp, "codex.log")
    kimi_log = os.path.join(tmp, "kimi.log")

    # ---- Arrange: codex has one notice, and a debt report that names it. Its
    # fire refuses (rc=70), so the primer is RETAINED -- the exact state the
    # real shared directory was in.
    INBOX["codex"] = [{"id": 215, "kind": "coordination", "from_plugin": "claude-code",
                       "pointer_uri": "hestia://appeals-waiting-for-you", "queued_at": "2026-07-31T00:00:00Z"}]
    # The notice each member is about (215, 500) is listed as STILL OWED, alongside the
    # older debt that names the owner. This is not decoration: since 2026-08-05 the
    # stale-retry pass asks the daemon whether a retained primer is still owed and
    # retires it without a fire when it is not (stale_primer_discharged_test.py). A
    # fixture whose notices are absent from `i_owe` therefore describes DISCHARGED work,
    # and every retry this file measures would correctly not happen -- case 2 would then
    # pass or fail on the age of a hardcoded 2026-07-31 date relative to whenever the
    # suite runs, which is a flake, not a test. Ownership and budget are what this file
    # is about; keeping its work list live is how they stay measurable.
    UNANSWERED["codex"] = {
        "i_owe": [{"id": 126, "kind": "reply", "from_plugin": "claude-code", "to_plugin": "codex",
                   "pointer_uri": "p", "queued_at": "2026-07-26T00:00:00Z", "drained_at": None},
                  {"id": 215, "kind": "coordination", "from_plugin": "claude-code", "to_plugin": "codex",
                   "pointer_uri": "hestia://appeals-waiting-for-you",
                   "queued_at": "2026-07-31T00:00:00Z", "drained_at": None}],
        "owed_to_me": [],
    }
    UNANSWERED["kimi-code"] = {
        "i_owe": [{"id": 496, "kind": "reply", "from_plugin": "claude-code", "to_plugin": "kimi-code",
                   "pointer_uri": "q", "queued_at": "2026-07-31T00:00:00Z", "drained_at": None},
                  {"id": 500, "kind": "coordination", "from_plugin": "claude-code", "to_plugin": "kimi-code",
                   "pointer_uri": "kimis-own-mail",
                   "queued_at": "2026-07-31T00:00:00Z", "drained_at": None}],
        "owed_to_me": [],
    }
    KIMI_NOTICE = {"id": 500, "kind": "coordination", "from_plugin": "claude-code",
                   "pointer_uri": "kimis-own-mail", "queued_at": "2026-07-31T00:00:00Z"}

    # Both stubs REFUSE. A succeeding retry deletes the primer and its sidecar,
    # which would leave cases 2 and 3a inspecting an empty directory and passing
    # vacuously -- `all()` over nothing is true, and a check that cannot see its
    # subject is not a check. Refusing keeps every artifact on disk to assert on.
    write_fire(refuser, codex_log, EX_REFUSED)
    write_fire(recorder, kimi_log, EX_REFUSED)

    run_watcher("codex", refuser, env, codex_log, 1)
    retained = fired(codex_log)
    check("arrange: codex's fire refused and the primer was retained",
          len(retained) == 1 and owner_of(retained[0]["body"]) == {"codex"},
          f"fired={retained}")

    # ---- 1. MISDELIVERY. kimi's watcher has one notice of its own, so we can wait
    # for a definite observable -- kimi's launcher running -- rather than guessing at
    # a duration. By the time it has fired its own mail, its startup stale-retry pass
    # is long finished, and the question is whether that pass took codex's list too.
    INBOX["kimi-code"] = [dict(KIMI_NOTICE)]
    out = run_watcher("kimi-code", recorder, env, kimi_log, 1)
    got = fired(kimi_log)
    stolen = [g for g in got if "codex" in owner_of(g["body"])]
    check("1-arrange: kimi's watcher ran far enough to fire its own mail",
          any("kimi-code" in owner_of(g["body"]) for g in got),
          f"kimi never fired at all, so case 1 proves nothing: {got}")
    check("1. a primer retained by codex's watcher is never fired at kimi",
          not stolen,
          "kimi's launcher was handed codex's work list:\n        " +
          "\n        ".join(json.dumps(s["body"].get("notices")) for s in stolen) +
          f"\n        watcher said:\n{out}")

    # ---- 2. THE ATTEMPT BUDGET IS THE MEMBER'S OWN.
    #
    # Not asserted on the counter's VALUE: pre-fix the sidecar reads "1" because
    # KIMI created it on codex's primer, so "== 1" is satisfied by the defect.
    # Assert the harm instead -- a primer set aside as exhausted on attempts its
    # own member never made. With the budget cut to 2, codex spends one retry,
    # kimi passes, codex spends its second. Post-fix codex is at 2 of its own 2
    # and the list is still live; pre-fix kimi spent the middle one, so codex's
    # second pass sees the budget already gone and parks the mail.
    env2x = dict(env, STALE_MAX_ATTEMPTS="2")
    n_codex, n_kimi = len(fired(codex_log)), len(fired(kimi_log))
    run_watcher("codex", refuser, env2x, codex_log, n_codex + 1)      # codex's own retry #1
    INBOX["kimi-code"] = [dict(KIMI_NOTICE)]
    run_watcher("kimi-code", recorder, env2x, kimi_log, n_kimi + 1)   # must not touch codex's budget
    run_watcher("codex", refuser, env2x, codex_log, n_codex + 2)      # codex's own retry #2

    # Scoped to codex by CONTENT, not by path: kimi now has retained primers of its
    # own in this state dir, and pre-fix everything shares one directory anyway, so a
    # path filter would either miss the subject or count the wrong member's.
    codex_files = []
    for root, _, files in os.walk(os.path.join(state, "primers")):
        for f in files:
            p = os.path.join(root, f)
            if not (f.startswith("notice-") and (f.endswith(".json") or f.endswith(".exhausted"))):
                continue
            try:
                with open(p) as fh:
                    body = json.load(fh)
            except Exception:
                continue
            if body.get("for_plugin") == "codex" or owner_of(body) == {"codex"}:
                codex_files.append(p)
    exhausted = [p for p in codex_files if p.endswith(".exhausted")]
    live = [p for p in codex_files if p.endswith(".json")]
    check("2. codex's retry budget is spent only by codex",
          live and not exhausted,
          f"codex's work list was parked after 2 of its own attempts on a budget of 2\n"
          f"        exhausted={exhausted}\n        live={live}")

    # ---- 3. THE ARTIFACT NAMES ITS OWNER, on both the fold and fallback paths.
    # The invariant, not just the stamp: every primer names an owner AND sits in that
    # owner's directory. One assertion covers both halves of the fix, for every member
    # in the tree rather than the one this test happens to be about.
    # The read RETRIES, then REPORTS — it does not raise.
    #
    # This walk used a bare `json.load` and crashed on CI with a JSONDecodeError at this line
    # (2026-07-31, blocking every open PR). An unparseable primer is precisely what 3a exists
    # to catch, so the one condition the assertion is for arrived as a traceback with no
    # verdict — the same shape as a green that measures nothing, inverted.
    #
    # Two causes are possible and they want opposite responses, so the read distinguishes
    # them rather than picking one:
    #   - MID-WRITE. The watcher writes primers asynchronously and not atomically, so a walk
    #     can reach a file between create and flush. A fast local box never hits the window;
    #     a shared runner does, which is why this passes locally and fails in CI. A brief
    #     retry settles it and it is not a defect in what was written.
    #   - MALFORMED. The content is genuinely wrong and no amount of waiting fixes it. That
    #     is a real finding and must fail loudly, naming the file and what it held.
    def _read_primer(path, attempts=4, delay=0.15):
        last = None
        for i in range(attempts):
            try:
                with open(path) as fh:
                    return json.load(fh), None
            except (json.JSONDecodeError, OSError) as e:
                last = e
                if i + 1 < attempts:
                    time.sleep(delay)
        try:
            raw = open(path, "rb").read()[:200]
        except OSError:
            raw = b"<unreadable>"
        return None, f"{type(last).__name__}: {last} | first 200 bytes: {raw!r}"

    primers, unparseable = [], []
    for root, _, files in os.walk(os.path.join(state, "primers")):
        for f in files:
            if f.startswith("notice-") and f.endswith(".json"):
                p = os.path.join(root, f)
                body, err = _read_primer(p)
                (primers.append((p, body)) if err is None else unparseable.append((p, err)))

    # Reported as its OWN check. Folding it into 3a would let "a primer could not be read"
    # masquerade as "a primer was misfiled", and those have different repairs.
    check("3a-pre. every primer on disk is readable JSON (retried, so a mid-write is not a fail)",
          not unparseable,
          f"unparseable after retries: {unparseable}")

    misfiled = [(p, b.get("for_plugin")) for p, b in primers
                if b.get("for_plugin") != os.path.basename(os.path.dirname(p))]
    check("3a. every primer names its member and sits in that member's directory",
          primers and not misfiled,
          f"misfiled (path vs for_plugin): {misfiled}")

    # Fallback path: the unanswered RPC fails, so the fold cannot run. This is
    # how the 7 owner-less files in the real directory were written.
    state2 = os.path.join(tmp, "state2")
    os.makedirs(state2)
    env2 = base_env(state2, ep)
    fb_log = os.path.join(tmp, "fallback.log")
    fb_fire = os.path.join(tmp, "fire-fallback.sh")
    write_fire(fb_fire, fb_log, EX_REFUSED)
    INBOX["codex"] = [{"id": 216, "kind": "reply", "from_plugin": "claude-code",
                       "pointer_uri": "p2", "queued_at": "2026-07-31T00:00:00Z"}]
    UNANSWERED["codex"] = FAIL_UNANSWERED
    run_watcher("codex", fb_fire, env2, fb_log, 1)
    fb = fired(fb_log)
    check("3b. and records it even when the unanswered fold fails",
          len(fb) == 1 and fb[0]["body"].get("for_plugin") == "codex",
          f"fallback primer: {[f['body'] for f in fb]}")
    UNANSWERED["codex"] = {"i_owe": [], "owed_to_me": []}

    # ---- 4. THE LAUNCHER REFUSES SOMEONE ELSE'S MAIL.
    # Real fire templates, real primer, stubbed CLI on PATH. A template handed a
    # primer stamped for another member must exit non-zero and not launch.
    bindir = os.path.join(tmp, "bin")
    os.makedirs(bindir, exist_ok=True)
    launched = os.path.join(tmp, "launched.log")
    for cli in ("kimi", "claude", "codex"):
        p = os.path.join(bindir, cli)
        with open(p, "w") as f:
            f.write(f'#!/usr/bin/env bash\necho "$@" >> "{launched}"\nexit 0\n')
        os.chmod(p, 0o755)

    foreign = os.path.join(tmp, "notice-FOREIGN.json")
    with open(foreign, "w") as f:
        json.dump({"for_plugin": "codex", "total": 1, "evicted": 0, "peeked": False,
                   "notices": [{"id": 9001, "kind": "reply", "from_plugin": "claude-code",
                                "pointer_uri": "somebody-elses-mail", "queued_at": "2026-07-31T00:00:00Z"}]}, f)
    fenv = dict(os.environ)
    fenv.update(HOME=os.path.join(tmp, "home4"), PATH=bindir + os.pathsep + os.environ["PATH"])
    os.makedirs(fenv["HOME"], exist_ok=True)
    r = subprocess.run([os.path.join(MESH, "fire-kimi.sh"), foreign], env=fenv,
                       capture_output=True, text=True, timeout=60)
    check("4a. fire-kimi.sh refuses a primer stamped for codex",
          r.returncode != 0,
          f"rc={r.returncode} stdout={r.stdout[-400:]} stderr={r.stderr[-400:]}")
    check("4b. ...and does not launch the CLI",
          not os.path.exists(launched),
          f"launched: {open(launched).read() if os.path.exists(launched) else ''}")

    srv.shutdown()
    shutil.rmtree(tmp, ignore_errors=True)
    print()
    if failures:
        print(f"FAILED ({len(failures)}): " + ", ".join(failures))
        return 1
    print("ok: 0 failure(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
