#!/usr/bin/env python3
"""The one rc that PROVES the primer was delivered is the one that reports it undelivered.

WHAT HAPPENED (CBP, 2026-08-20). claude-code sent kimi-code two `review_done` notices:
4121 (PR #525) and 4127 (PR #549). Both arrived. kimi's wake `kimi-20260820-011755`
opens by naming them by id and kind, spends 3700 lines arguing them, and its successor
lands the fixes citing "#525 re-review -- invariant 1" and "claude asked for a test with
a member holding a live scope grant and not connected". Then that wake ran past
`timeout -k 30 1800`. rc=124 at 08:46:56Z, primer retained -- and `report_unreachable`
mailed claude-code two `kind=reply` notices saying 4121 and 4127 were undelivered.

They were delivered and answered. `reply` is in MEMBER_KINDS_AWAIT_RESPONSE, so each
false report also became a row in the SENDER's `i_owe` and woke a session to read it.
The amplifier points the wrong way: the longer and more thorough a wake, the likelier
the bound cuts it, and the more peers are told they were not heard.

The measurement was already in this directory. `stale_primer_discharged_test.py` opens
with "This mesh has filed nine non-delivery reports on rc=124 and all nine were false"
-- and that number bought a `primer_spent` guard on the RE-FIRE path and nothing on the
REPORT path, which runs first and every time. The wake amplification was fixed; the
false reports it was measured from were not. These are instances ten and eleven.

WHY rc=124 SPECIFICALLY. Every `fire-*.sh` runs `timeout -k 30 1800 <cli> ... "$PRIMER"`,
so 124 means the launcher STARTED the member's CLI with the primer path in its argv and
later cut it short. Delivery is what 124 proves. Every other rc is unchanged: 75 (the
member lock refused -- the CLI never ran), 1 (out-of-credits, egress-blocked, usage
error), 69, 70 all still report.

NOT the symmetric fix. Reusing `primer_spent` here would be wrong one-sidedly: `i_owe`
only holds MEMBER_KINDS_AWAIT_RESPONSE, so a `review_done` is absent from the fold
whether it was answered or never seen -- gating on it would suppress the report for
exactly the kinds where the report is the only trace, and on genuinely dead fires too.
Property 4 pins that: a `review_done` on a NON-124 failure still reports.

Four properties, behavioural against the real watcher with a stubbed daemon and stubbed
launchers -- no test seam:

  1. rc=124 FILES NO REPORT, and the primer is still retained (the work is not lost,
     the retry path owns it). Red before the fix.
  2. rc=1 STILL FILES ONE. The guard must not eat the case the report exists for.
  3. rc=75 STILL FILES ONE -- the lock refusal, where the CLI genuinely never ran. This
     is the arm that fails if someone "simplifies" the guard to `[ "$RC" != 0 ]`-ish
     breadth or keys it on `why=timeout` (the classifier returns `timeout` from log TEXT
     under any rc; the integer is the fact, the classifier is a lead).
  4. A `review_done` ON A NON-124 FAILURE STILL REPORTS. The kinds outside
     MEMBER_KINDS_AWAIT_RESPONSE are the ones an `i_owe`-based guard would have eaten;
     this is the arm that goes red if the symmetric fix is ever substituted in.

To watch property 1 fail, point the harness at the pre-fix watcher:
    git show <pre-fix-sha>:plugins/member-mesh/hestia-watch-member.sh > /tmp/old.sh
    WATCHER_UNDER_TEST=/tmp/old.sh ./rc124_is_not_unreachable_test.py   -> 1a FAILS

Usage: ./rc124_is_not_unreachable_test.py     (runtime ~25s)
"""
import datetime
import http.server
import json
import os
import stat
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
MESH = os.path.abspath(os.path.join(HERE, ".."))
WATCHER = os.environ.get("WATCHER_UNDER_TEST") or os.path.join(MESH, "hestia-watch-member.sh")

PLUGIN = "claude-code"
SENDER = "kimi-code"
SUBJECT = 4121          # the notice under test
SENTINEL = 99999        # its fire succeeds; its appearance means the subject's fire is decided

failures = []


def check(label, ok, detail=""):
    if not ok:
        failures.append(label)
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if detail and not ok else ""))


def ago(seconds):
    return (datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


# --------------------------------------------------------------------------
# Stub daemon. Serves inbox batches in order and RECORDS every hestia_member_notify,
# which is the observable this whole file is about.
# --------------------------------------------------------------------------
BATCHES = []
NOTIFIES = []


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
            payload = {"sessionId": "sess::" + str(args.get("plugin_id")),
                       "roleDeclarationHonored": True,
                       "constellationRole": args.get("role")}
        elif name == "hestia_member_inbox":
            notices = BATCHES.pop(0) if BATCHES else []
            payload = {"notices": notices, "total": len(notices), "evicted": 0,
                       "peeked": False, "for_plugin": PLUGIN}
        elif name == "hestia_member_unanswered":
            # Healthy and empty. Deliberately: if the guard ever leans on the debt fold
            # instead of the rc, property 4 and property 2 go red here rather than
            # passing for the wrong reason.
            payload = {"i_owe": [], "owed_to_me": [], "older_than_secs": 0}
        elif name == "hestia_member_notify":
            NOTIFIES.append(dict(args))
            payload = {"queued_id": 500000 + len(NOTIFIES), "chain_hash": "f" * 64}
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


def start_stub():
    srv = http.server.HTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/mcp"


def write_fire(path, log, rc):
    """Fails with `rc` for the primer carrying SUBJECT, succeeds for the sentinel."""
    with open(path, "w") as f:
        f.write(f'''#!/usr/bin/env bash
IDS=$(python3 - "$1" "{log}" <<'PY'
import json,sys
try: d=json.load(open(sys.argv[1]))
except Exception: d={{}}
ids=[n.get("id") for n in d.get("notices",[])]
open(sys.argv[2],"a").write(json.dumps({{"primer":sys.argv[1],"ids":ids}})+"\\n")
print(" ".join(str(i) for i in ids))
PY
)
case " $IDS " in
  *" {SUBJECT} "*) exit {rc} ;;
  *) exit 0 ;;
esac
''')
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def fired_ids(log):
    out = set()
    if not os.path.exists(log):
        return out
    with open(log) as f:
        for line in f:
            if line.strip():
                out.update(i for i in json.loads(line)["ids"] if i is not None)
    return out


def notice(nid, kind="review_done", age=900):
    return {"id": nid, "kind": kind, "from_plugin": SENDER,
            "from_role": "role:constellation:mesh-worker",
            "pointer_uri": f"https://github.com/dp-web4/hestia/pull/525#issuecomment-{nid}:HOLD",
            "chain_hash": "0" * 64, "queued_at": ago(age), "in_reply_to": None}


def run_case(tmp, ep, label, rc, kind="review_done"):
    """One watcher run. The sentinel's fire is the synchroniser: report_unreachable for
    the subject runs synchronously between the subject's fire returning and the next
    poll's drain, so a sentinel in the fire log means the report decision is already
    made. Never a fixed sleep -- a duration is a coin flip on a loaded host."""
    global BATCHES, NOTIFIES
    state = os.path.join(tmp, label)
    os.makedirs(os.path.join(state, "primers", PLUGIN))
    log = os.path.join(tmp, f"{label}.log")
    fire = os.path.join(tmp, f"{label}-fire.sh")
    write_fire(fire, log, rc)

    BATCHES = [[notice(SUBJECT, kind=kind)], [notice(SENTINEL, kind="coordination")]]
    NOTIFIES = []

    env = dict(os.environ)
    env.update(HESTIA_MESH_STATE=state, HESTIA_ENDPOINT=ep, HOME=state,
               WATCH_INTERVAL="1", UNANSWERED_EVERY="99999")
    p = subprocess.Popen([WATCHER, PLUGIN, f"{PLUGIN}-watch", fire],
                         env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    deadline = time.time() + 60
    while time.time() < deadline and SENTINEL not in fired_ids(log):
        if p.poll() is not None:
            break
        time.sleep(0.2)
    p.kill()
    out, _ = p.communicate()
    reports = [n for n in NOTIFIES if "#undelivered" in str(n.get("pointer_uri", ""))]
    primers = os.path.join(state, "primers", PLUGIN)
    retained = [f for f in os.listdir(primers) if f.endswith(".json")]
    return reports, retained, fired_ids(log), out


def main():
    srv, ep = start_stub()
    tmp = tempfile.mkdtemp(prefix="rc124-report-")

    # ---- 1. rc=124 FILES NO REPORT, AND LOSES NOTHING.
    reports, retained, fired, out = run_case(tmp, ep, "rc124", 124)
    check("1a. rc=124 files no undelivered report (the CLI ran; the primer was delivered)",
          reports == [],
          f"reports={json.dumps(reports)[:600]}\n{out[-1500:]}")
    check("1b. the subject's fire really did run (the arm is not vacuously green)",
          SUBJECT in fired, f"fired={sorted(fired)}\n{out[-1500:]}")
    check("1c. and the primer is RETAINED, so the retry path still owns the wake",
          len(retained) == 1, f"retained={retained}\n{out[-1500:]}")

    # ---- 2. rc=1 STILL FILES ONE. The guard is keyed to 124 and nothing broader.
    reports, retained, fired, out = run_case(tmp, ep, "rc1", 1)
    check("2a. rc=1 still files exactly one undelivered report", len(reports) == 1,
          f"reports={json.dumps(reports)[:600]}\n{out[-1500:]}")
    # `forum-note` since 2026-09-05, not `reply` (#926): a delivery failure is an
    # announcement, not a debt booked against the member whose mail died. The
    # PROPERTY — that the kind is sendable and uncounted — is asserted against
    # handler.rs's own constants in branch4_unreachable_report_test.py case I;
    # this arm only pins the literal so the two files cannot disagree silently.
    check("2b. addressed to the SENDER and bound to the notice it reports on",
          bool(reports) and reports[0].get("to_plugin_id") == SENDER
          and reports[0].get("in_reply_to") == SUBJECT
          and reports[0].get("kind") == "forum-note",
          f"reports={json.dumps(reports)[:600]}")

    # ---- 3. rc=75 STILL FILES ONE. with-member-lock refused: the CLI never started,
    # which is the case the report is FOR. Red if the guard widens past the integer 124
    # or keys on `why=timeout` (the classifier returns `timeout` from log text too).
    reports, retained, fired, out = run_case(tmp, ep, "rc75", 75)
    check("3a. rc=75 (member lock refused, CLI never ran) still files a report",
          len(reports) == 1, f"reports={json.dumps(reports)[:600]}\n{out[-1500:]}")

    # ---- 4. A KIND OUTSIDE MEMBER_KINDS_AWAIT_RESPONSE STILL REPORTS ON A DEAD FIRE.
    # `disposition` can never appear in `i_owe`, so an `i_owe`-based guard would suppress
    # this one -- and for such kinds the report is the only trace the notice existed.
    reports, retained, fired, out = run_case(tmp, ep, "kind", 1, kind="disposition")
    check("4a. a `disposition` on a non-124 failure still reports "
          "(an `i_owe`-based guard would have eaten it)",
          len(reports) == 1, f"reports={json.dumps(reports)[:600]}\n{out[-1500:]}")

    srv.shutdown()
    print()
    if failures:
        print(f"FAILED {len(failures)}: " + "; ".join(failures))
        return 1
    print("all properties hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
