#!/usr/bin/env python3
"""A work list is re-fired because a process exited nonzero, not because it is undone.

WHAT HAPPENED (CBP, 2026-08-05). A session was woken by `watch-claude-code` carrying
notice 709 -- kimi's reply on the scope-request thread, queued 2026-08-03T04:30:46Z.
The reply to it had been written, committed and pushed on 2026-08-03T04:43Z, thirteen
minutes after it was queued and six after it was drained. The daemon agreed: with the
staleness floor removed, `i_owe` was empty. The wake was spent establishing that the
work it was woken for was already done.

The primer was not lost and not duplicated. It was RETAINED, because
`hestia-watch-member.sh` keeps a primer when `$FIRE` returns nonzero, and a launcher
that times out returns nonzero whether or not the session inside it did the work. This
mesh has filed nine non-delivery reports on rc=124 and all nine were false. Retention
is then re-fired at every watcher restart, in `mktemp` alphabetical order -- so the
order is a random suffix, not age and not need.

The backlog that pass was walking, measured before the fix:

    18 retained primers for claude-code, carrying 46 notices, all from kimi-code
    31  kind `reply`, inside the 7d window   -> countable in `i_owe`, and `i_owe` was []
    14  kind `ack` (12) / `review_done` (2)  -> kinds that never await a response
     1  outside the window                   -> unmeasurable
    ---
     0  undischarged notices, 18 model wakes queued to re-deliver them

The recovery mechanism is what burns the wakes. Stale-primer retry exists because a
batch that failed once was stranded permanently (d2d23ba) -- a real fix for a real
defect, which had no way to ask whether the work it was retrying was still owed.

The fix asks. `i_owe` is the mesh's own predicate for "this notice awaits my response",
so a notice absent from it is discharged by the same rule every other surface uses.
Four properties, behavioural against the real watcher with a stubbed daemon and stubbed
launchers -- no test seam:

  1. DISCHARGED IS NOT RE-FIRED. A retained primer whose every notice is absent from
     `i_owe` is retired to `.discharged` without spending a wake. Red before the fix.
  2. STILL-OWED IS STILL FIRED. The guard must not eat the case the retry exists for.
  3. THE TWO EDGES OF THE BAND ARE NOT SYMMETRIC. Below the 6h default floor, absence
     means "hidden by the floor": FIRE. The young edge is the dangerous one -- the stub
     honours `older_than_secs` exactly as the daemon does, so this case is red if the
     guard ever trusts the floor, whether because the argument was misspelled (#155
     discards it into a success) or because someone deleted the min-age check as
     redundant. Past the daemon's 7d prune, absence means "pruned" -- and (REVERSED
     2026-09-02, was "unmeasured, fire") pruned is measured and gone: retired as
     `.expired`, no fire. See 9.
  8. A KIND THE FOLD NEVER COUNTS IS SPENT AT ANY AGE. The fold echoes `kinds_counted`;
     a `disposition`/`ack`/`review_done`/`coordination`/`handoff` can never be in
     `i_owe`, so neither band edge has standing over it. Notice 4408 (the daemon's own
     disposition, its grant claimed 41s after approval on 08-24) re-fired this seat
     8.4 days later as attempt 2/3 because the age rule ran before the kind was asked.
     Without the echo (an older daemon) the old age rule stands. Red before the fix.
  9. PAST THE INBOX TTL THE ROW IS PRUNED AND NO FIRE RECOVERS IT. `.expired`, distinct
     from `.discharged`. Between the 6d ceiling and the 7d TTL the old verdict stands
     (fire); a row the fold still owes fires at any age (owed wins). Red before the fix.
  4. A REFUSAL IS NOT AN EMPTY DEBT. When the `unanswered` RPC fails, the primer fires.
     `{}` and a 500 must not read as "nothing owed" -- that is the shape this corpus
     keeps finding, and here it would delete the only copy of a work list.
  7. THE FOLD IS THE DEBT AS IT STANDS WHEN THE VERDICT IS GIVEN, NOT AT PASS START.
     Fires are synchronous and serialised on the member lock, so a startup pass lasts
     as long as the sum of its fires, and the first wake in the pass answers debt that
     later primers are then judged on. Measured on CBP 2026-09-02: the watcher
     restarted 04:22:04Z and read the fold once; the pass's first wake bound the reply
     to notice 7927 at 04:39:31Z; 7927's own primer came up at 04:48:53Z, was judged
     against the 04:22 fold that still owed it, and spent a wake learning it was done.
     Two retained primers, the first fire discharging the second's notice: the second
     must retire, not fire. Red on a once-per-pass fold.

Usage: ./stale_primer_discharged_test.py     (runtime ~20s)
"""
import http.server
import json
import os
import stat
import subprocess
import sys
import tempfile
import threading
import time
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
MESH = os.path.abspath(os.path.join(HERE, ".."))
# The path is overridable for ONE purpose: running this file against the pre-fix script
# to show property 1 red. A criterion nobody watched fail is not a criterion, and the
# only way to watch this one fail is to point it at the watcher that lacks the guard:
#   git show <pre-fix-sha>:plugins/member-mesh/hestia-watch-member.sh > /tmp/old.sh
#   WATCHER_UNDER_TEST=/tmp/old.sh ./stale_primer_discharged_test.py   -> 1a, 1b FAIL
# It is not a seam into the code under test: the default is the real script and every
# property is measured through its ordinary startup path.
WATCHER = os.environ.get("WATCHER_UNDER_TEST") or os.path.join(MESH, "hestia-watch-member.sh")

PLUGIN = "claude-code"
DEFAULT_FLOOR = 21600          # MEMBER_UNANSWERED_DEFAULT_SECS, 6h

failures = []


def check(label, ok, detail=""):
    if not ok:
        failures.append(label)
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if detail and not ok else ""))


def ago(seconds):
    return (datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


# --------------------------------------------------------------------------
# Stub daemon. Speaks the subset of MCP `mesh_rpc` drives, and -- the part that
# matters here -- APPLIES `older_than_secs` the way the daemon does: a row appears
# in `i_owe` only if it is older than the floor, so a request that fails to set the
# floor sees FEWER debts, not more. That is the direction that can retire a live
# work list, and it is why case 3 exists.
# --------------------------------------------------------------------------
INBOX = {}
DEBTS = []                 # rows the member genuinely still owes
REFUSE_UNANSWERED = False
IGNORE_FLOOR_ARG = False   # model #155: the daemon DISCARDS `older_than_secs` and defaults
OMIT_KINDS_COUNTED = False # model a daemon older than the `kinds_counted` echo (case 8b)
KINDS_COUNTED = ["review_request", "reply"]   # MEMBER_KINDS_AWAIT_RESPONSE, handler.rs
FLOORS_SEEN = []
DISCHARGE_DIR = None       # case 7: a fire may DISCHARGE debts mid-pass by touching <id> here


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
            notices = INBOX.pop(PLUGIN, [])
            payload = {"notices": notices, "total": len(notices), "evicted": 0,
                       "peeked": False, "for_plugin": PLUGIN}
        elif name == "hestia_member_unanswered":
            if REFUSE_UNANSWERED:
                self.send_response(500)
                self.end_headers()
                return
            floor = args.get("older_than_secs")
            if IGNORE_FLOOR_ARG or not isinstance(floor, int):
                floor = DEFAULT_FLOOR
            FLOORS_SEEN.append(floor)
            cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=floor)
            shown = [d for d in DEBTS
                     if datetime.datetime.fromisoformat(d["queued_at"].replace("Z", "+00:00")) < cutoff]
            if DISCHARGE_DIR:
                # A debt the member has since answered leaves `i_owe` -- the daemon's
                # rule. The fire under test is the one that answers it (case 7).
                shown = [d for d in shown
                         if not os.path.exists(os.path.join(DISCHARGE_DIR, str(d["id"])))]
            # The daemon ECHOES the floor it APPLIED, not the one it was asked for.
            # Measured against the live daemon 2026-08-06, same session, four cells:
            #   older_than_secs=0 -> 0 | omitted -> 21600 | older_than_seconds=0 -> 21600
            #   | older_than_secs=60 -> 60.  The misspelled cell reports the fallback,
            # which is what makes the echo usable as an oracle rather than a mirror.
            # `floor` here is post-fallback for exactly that reason.
            payload = {"i_owe": shown, "owed_to_me": [], "older_than_secs": floor}
            if not OMIT_KINDS_COUNTED:
                payload["kinds_counted"] = list(KINDS_COUNTED)
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


def write_fire(path, log, rc=0, discharge=(), discharge_dir=None):
    """`discharge`: notice ids this fire ANSWERS as a side effect of running -- the
    shape of a real wake, which takes `unanswered 0` as its work list and binds
    replies to everything in it, not just to the primer it was woken with."""
    touches = "".join(f'touch "{discharge_dir}/{i}"\n' for i in discharge)
    with open(path, "w") as f:
        f.write(f'''#!/usr/bin/env bash
python3 - "$1" "{log}" <<'PY'
import json,sys
try: d=json.load(open(sys.argv[1]))
except Exception: d={{}}
open(sys.argv[2],"a").write(json.dumps({{"primer":sys.argv[1],
    "ids":[n.get("id") for n in d.get("notices",[])]}})+"\\n")
PY
{touches}exit {rc}
''')
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def fired(log):
    if not os.path.exists(log):
        return []
    with open(log) as f:
        return [json.loads(l) for l in f if l.strip()]


def fired_ids(log):
    out = set()
    for f in fired(log):
        out.update(i for i in f["ids"] if i is not None)
    return out


def plant(primers, name, notices):
    """Write a retained primer exactly as a failed fire leaves one."""
    path = os.path.join(primers, f"notice-{name}.json")
    with open(path, "w") as f:
        json.dump({"for_plugin": PLUGIN, "total": len(notices), "evicted": 0,
                   "peeked": False, "notices": notices,
                   "unanswered": {"i_owe": [], "owed_to_me": []}}, f)
    return path


def notice(nid, age_secs, kind="reply"):
    return {"id": nid, "kind": kind, "from_plugin": "kimi-code",
            "from_role": "role:constellation:interactive-dev",
            "pointer_uri": f"forum/post-{nid}.md#anchor", "chain_hash": "0" * 64,
            "queued_at": ago(age_secs), "in_reply_to": None}


def run_case(tmp, ep, label, planted, debts, want_ids, refuse=False, sentinel_id=99999,
             ignore_floor_arg=False, discharge_on_fire=(), omit_kinds_counted=False):
    """Run the real watcher once. The observable that says the startup stale pass has
    finished is the member's OWN fresh mail being fired -- the drain happens after that
    pass, so a sentinel in the log means every stale decision is already made. Never a
    fixed sleep: a duration is a coin flip on a loaded host."""
    global DEBTS, REFUSE_UNANSWERED, IGNORE_FLOOR_ARG, DISCHARGE_DIR, OMIT_KINDS_COUNTED
    state = os.path.join(tmp, label)
    primers = os.path.join(state, "primers", PLUGIN)
    os.makedirs(primers)
    log = os.path.join(tmp, f"{label}.log")
    fire = os.path.join(tmp, f"{label}-fire.sh")
    DISCHARGE_DIR = os.path.join(tmp, f"{label}-discharged")
    os.makedirs(DISCHARGE_DIR)
    # every fire REFUSES, so nothing is deleted
    write_fire(fire, log, rc=70, discharge=discharge_on_fire, discharge_dir=DISCHARGE_DIR)
    for name, notices in planted.items():
        plant(primers, name, notices)

    DEBTS = list(debts)
    REFUSE_UNANSWERED = refuse
    IGNORE_FLOOR_ARG = ignore_floor_arg
    OMIT_KINDS_COUNTED = omit_kinds_counted
    INBOX[PLUGIN] = [notice(sentinel_id, 60, kind="coordination")]

    env = dict(os.environ)
    env.update(HESTIA_MESH_STATE=state, HESTIA_ENDPOINT=ep, HOME=state,
               WATCH_INTERVAL="1", UNANSWERED_EVERY="99999")
    p = subprocess.Popen([WATCHER, PLUGIN, f"{PLUGIN}-watch", fire],
                         env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    deadline = time.time() + 60
    while time.time() < deadline and sentinel_id not in fired_ids(log):
        if p.poll() is not None:
            break
        time.sleep(0.2)
    p.kill()
    out, _ = p.communicate()
    REFUSE_UNANSWERED = False
    IGNORE_FLOOR_ARG = False
    OMIT_KINDS_COUNTED = False
    got = fired_ids(log) - {sentinel_id}
    return got, primers, out


def main():
    srv, ep = start_stub()
    tmp = tempfile.mkdtemp(prefix="stale-discharged-")

    # ---- 1. DISCHARGED IS NOT RE-FIRED.
    # Two days old, so squarely inside the window; nothing owed. This is notice 709.
    got, primers, out = run_case(
        tmp, ep, "discharged",
        planted={"CxrJO4": [notice(709, 2 * 86400)]},
        debts=[], want_ids=set())
    check("1a. a discharged primer is not re-fired", got == set(),
          f"fired ids={sorted(got)}\n{out[-1500:]}")
    check("1b. and it is RETIRED, not left to be re-walked every restart",
          os.path.exists(os.path.join(primers, "notice-CxrJO4.json.discharged"))
          and not os.path.exists(os.path.join(primers, "notice-CxrJO4.json")),
          f"dir={sorted(os.listdir(primers))}")

    # ---- 2. STILL-OWED IS STILL FIRED. Same age, same shape, one difference.
    owed = notice(800, 2 * 86400)
    got, primers, out = run_case(
        tmp, ep, "owed",
        planted={"AAAAAA": [notice(709, 2 * 86400)], "BBBBBB": [owed]},
        debts=[{"id": 800, "kind": "reply", "from_plugin": "kimi-code",
                "to_plugin": PLUGIN, "queued_at": owed["queued_at"], "drained_at": None}],
        want_ids={800})
    check("2a. a primer whose notice is still owed IS fired", 800 in got,
          f"fired ids={sorted(got)}\n{out[-1500:]}")
    check("2b. and the discharged one beside it still is not", 709 not in got,
          f"fired ids={sorted(got)}")
    check("2c. a primer that fired is preserved for the next pass, not retired",
          os.path.exists(os.path.join(primers, "notice-BBBBBB.json")),
          f"dir={sorted(os.listdir(primers))}")

    # ---- 3. THE TWO EDGES OF THE BAND, AND THEY ARE NOT SYMMETRIC.
    # 30min: below the default floor -- absent because the floor hides it. The stub
    # applies the floor for real, so if the guard leans on the fold here it retires a
    # notice that IS owed, which is the one unrecoverable error in this design. FIRE.
    # 30d: past the daemon's 7d prune -- absent because pruned, not because answered.
    # 3a used to pin "unmeasured, so it fires" for this edge too (2026-08-05). REVERSED
    # 2026-09-02: pruned is not unmeasured, it is MEASURED AND GONE. The daemon deleted
    # the row, so it can never re-enter `i_owe`; a binding to it is accepted but
    # unverified; the escalation a review_request points at was reaped days ago. A fire
    # here recovers nothing the ledger still tracks. The primer is retired as `.expired`
    # -- kept on disk, distinct from `.discharged`, one `mv` from revival by a human --
    # and the wake is withheld. 207 of the 242 fires budgeted for >6d primers across
    # three seats that morning were for this edge. The 6d..7d gap keeps the old verdict
    # (9b): unmeasured, fire.
    young = notice(901, 1800)
    got, primers, out = run_case(
        tmp, ep, "unmeasured",
        planted={"OLDOLD": [notice(330, 30 * 86400)], "YOUNGY": [young]},
        debts=[{"id": 901, "kind": "reply", "from_plugin": "kimi-code",
                "to_plugin": PLUGIN, "queued_at": young["queued_at"], "drained_at": None}],
        want_ids={901})
    check("3a. a notice past the inbox TTL is pruned, not unmeasured: retired as .expired, "
          "no fire (REVERSES the 08-05 pin; see 9a-9c for the edges of the new rule)",
          330 not in got and os.path.exists(os.path.join(primers, "notice-OLDOLD.json.expired")),
          f"fired ids={sorted(got)} dir={sorted(os.listdir(primers))}\n{out[-1500:]}")
    check("3b. a notice younger than the default floor is unmeasured, so it fires "
          "(it is genuinely owed and the floor hides it)", 901 in got,
          f"fired ids={sorted(got)}\n{out[-1500:]}")

    # ---- 3c. THE SAME EDGE, WITH THE ARGUMENT DISCARDED.
    # 3b above passes on the min-age check OR on the floor being honoured, and deleting
    # the min-age check leaves it green -- so 3b alone attributes nothing to the guard.
    # Here the stub does what #155 says the daemon does with a key it does not read:
    # accepts it, ignores it, applies MEMBER_UNANSWERED_DEFAULT_SECS, answers success.
    # Notice 901 is genuinely owed and now invisible in the fold, so the min-age refusal
    # to judge it is the ONLY thing standing between a live work list and deletion.
    # Remove `age < min_age` from the watcher and this case goes red on its own.
    young = notice(901, 1800)
    got, primers, out = run_case(
        tmp, ep, "floor-ignored",
        planted={"YOUNGY": [young]},
        debts=[{"id": 901, "kind": "reply", "from_plugin": "kimi-code",
                "to_plugin": PLUGIN, "queued_at": young["queued_at"], "drained_at": None}],
        want_ids={901}, ignore_floor_arg=True)
    check("3c. with `older_than_secs` silently discarded, a young owed notice STILL fires "
          "(the verdict does not depend on the floor)",
          901 in got and not os.path.exists(os.path.join(primers, "notice-YOUNGY.json.discharged")),
          f"fired ids={sorted(got)} dir={sorted(os.listdir(primers))}\n{out[-1500:]}")

    # ---- 5. A PROMPTLY-ANSWERED NOTICE IS RETIRABLE.
    # The price of case 3's blanket min-age band was the modal case on this mesh: a
    # notice answered within 6h could never be retired, so if its fire ever returned
    # nonzero it re-fired to the attempt budget. Measured on CBP 2026-08-06: three
    # retained claude-code primers, all absent from `i_owe` at floor 0, all held only
    # by the band -- and the wake that found it was attempt 1 of 3 for notice 1208,
    # answered 45 minutes earlier.
    #
    # The band now shrinks to the floor the fold ADMITS to. Same 30-minute notice as
    # 3b/3c, one difference: nothing owes it. Red before the fix (the band alone fires).
    got, primers, out = run_case(
        tmp, ep, "young-discharged",
        planted={"YNGDIS": [notice(910, 1800)]},
        debts=[], want_ids=set())
    check("5a. a notice answered inside the 6h default is retired, not re-fired, "
          "when the fold reports it covered floor 0", got == set(),
          f"fired ids={sorted(got)}\n{out[-1500:]}")
    check("5b. and it is RETIRED rather than left for the next restart",
          os.path.exists(os.path.join(primers, "notice-YNGDIS.json.discharged")),
          f"dir={sorted(os.listdir(primers))}")

    # ---- 6. THE ECHO IS AN ORACLE, NOT A MIRROR.
    # 5 passes if the guard trusts the floor it REQUESTED; this one only passes if it
    # trusts the floor the fold REPORTED. Identical to 5 except the stub discards the
    # argument (#155) and says so in the echo. The notice is answered here, so absence
    # from `i_owe` is real -- but at an admitted floor of 6h it is UNMEASURABLE, and a
    # guard that cannot tell the two apart is one misspelling away from deleting a live
    # work list. Gate on `args["older_than_secs"]` instead of the echo and this is red.
    got, primers, out = run_case(
        tmp, ep, "young-floor-ignored",
        planted={"YNGIGN": [notice(911, 1800)]},
        debts=[], want_ids={911}, ignore_floor_arg=True)
    check("6. when the fold admits it applied the 6h default, a young notice is "
          "unmeasurable and fires -- absence under a floor is not an answer",
          911 in got and not os.path.exists(os.path.join(primers, "notice-YNGIGN.json.discharged")),
          f"fired ids={sorted(got)} dir={sorted(os.listdir(primers))}\n{out[-1500:]}")

    # ---- 7. THE FOLD IS RE-READ PER PRIMER.
    # Two owed notices in two retained primers. The FIRST fire answers the second's
    # notice (a real wake works `unanswered 0`, not its primer). Glob order puts
    # AAAAAA first, so by the time BBBBBB is judged, 801 is no longer owed. A fold read
    # once at pass start still says 801 is owed and fires it: that wake's entire output
    # is "already answered", and on CBP 2026-09-02 it was this seat's, notice 7927.
    first = notice(800, 2 * 86400)
    second = notice(801, 2 * 86400)
    got, primers, out = run_case(
        tmp, ep, "fold-per-primer",
        planted={"AAAAAA": [first], "BBBBBB": [second]},
        debts=[{"id": 800, "kind": "reply", "from_plugin": "kimi-code",
                "to_plugin": PLUGIN, "queued_at": first["queued_at"], "drained_at": None},
               {"id": 801, "kind": "reply", "from_plugin": "kimi-code",
                "to_plugin": PLUGIN, "queued_at": second["queued_at"], "drained_at": None}],
        want_ids={800}, discharge_on_fire=(801,))
    check("7a. the first owed primer fires", 800 in got,
          f"fired ids={sorted(got)}\n{out[-1500:]}")
    check("7b. a notice the first fire answered is NOT re-fired by the same pass "
          "(the fold is read when the verdict is given, not when the pass began)",
          801 not in got, f"fired ids={sorted(got)}\n{out[-1500:]}")
    check("7c. and its primer is RETIRED, not preserved for the next restart",
          os.path.exists(os.path.join(primers, "notice-BBBBBB.json.discharged"))
          and not os.path.exists(os.path.join(primers, "notice-BBBBBB.json")),
          f"dir={sorted(os.listdir(primers))}")

    # ---- 8. A KIND THE FOLD NEVER COUNTS IS SPENT AT ANY AGE.
    # Notice 4408: the daemon's own `disposition` for an escalation whose grant was
    # claimed 41s after approval on 2026-08-24. Its first fire died (0-byte log); the
    # primer was retained; 8.4 days later it re-fired this seat as attempt 2 of 3,
    # because ">6d -> unmeasured -> fire" ran before anyone asked what kind it was. A
    # `disposition` cannot appear in `i_owe` at ANY age -- the fold says so itself in
    # `kinds_counted` -- so absence is structural and the age band has no standing.
    got, primers, out = run_case(
        tmp, ep, "dispo-old",
        planted={"DISPO8": [notice(4408, int(8.4 * 86400), kind="disposition")]},
        debts=[], want_ids=set())
    check("8a. a never-counted kind older than the 6d ceiling is retired without a fire",
          got == set() and os.path.exists(os.path.join(primers, "notice-DISPO8.json.discharged")),
          f"fired ids={sorted(got)} dir={sorted(os.listdir(primers))}\n{out[-1500:]}")
    # 8b. The kind list comes from the FOLD, never from this script. A daemon that does
    # not echo `kinds_counted` gets the old verdict: kind-blind, age-gated, fire. Placed
    # in the 6d..7d gap so the TTL rule (9) cannot answer for it; the same primer with
    # the echo present is 8a's case and retires.
    got, primers, out = run_case(
        tmp, ep, "dispo-old-noecho",
        planted={"DISPON": [notice(4409, int(6.5 * 86400), kind="disposition")]},
        debts=[], want_ids={4409}, omit_kinds_counted=True)
    check("8b. without the fold's `kinds_counted` echo the old age rule stands and it fires",
          4409 in got, f"fired ids={sorted(got)}\n{out[-1500:]}")
    # 8c. And the 6h floor has no standing either: a floor hides OWED rows, and a kind
    # that can never be owed has none to hide. Same #155 stub as case 6.
    got, primers, out = run_case(
        tmp, ep, "dispo-young-floor-ignored",
        planted={"DISPOY": [notice(4410, 1800, kind="disposition")]},
        debts=[], want_ids=set(), ignore_floor_arg=True)
    check("8c. a never-counted kind under an admitted 6h floor is still retired",
          got == set() and os.path.exists(os.path.join(primers, "notice-DISPOY.json.discharged")),
          f"fired ids={sorted(got)} dir={sorted(os.listdir(primers))}\n{out[-1500:]}")

    # ---- 9. PAST THE DAEMON'S INBOX TTL THE ROW IS PRUNED; NO FIRE RECOVERS IT.
    # The ceiling fired anything older than 6d on the grounds that absence means
    # "pruned, not answered". Past INBOX_TTL_SECS (7d, core/src/storage/inbox.rs) that
    # is exactly the point: the daemon has deleted the row, it can never re-enter
    # `i_owe`, and the mesh has written the obligation off. Retired as `.expired`,
    # a distinct suffix from `.discharged`, so the record says which door closed it.
    got, primers, out = run_case(
        tmp, ep, "reply-past-ttl",
        planted={"OLDRPL": [notice(920, 8 * 86400)]},
        debts=[], want_ids=set())
    check("9a. a counted kind past the inbox TTL is retired as .expired without a fire",
          got == set() and os.path.exists(os.path.join(primers, "notice-OLDRPL.json.expired"))
          and not os.path.exists(os.path.join(primers, "notice-OLDRPL.json.discharged")),
          f"fired ids={sorted(got)} dir={sorted(os.listdir(primers))}\n{out[-1500:]}")
    # 9b. Between the ceiling and the TTL the old verdict stands: unmeasured, fire.
    got, primers, out = run_case(
        tmp, ep, "reply-6d-to-7d",
        planted={"MIDRPL": [notice(921, int(6.5 * 86400))]},
        debts=[], want_ids={921})
    check("9b. a counted kind between the 6d ceiling and the 7d TTL still fires",
          921 in got, f"fired ids={sorted(got)}\n{out[-1500:]}")
    # 9c. A row the fold STILL OWES past the TTL contradicts the TTL; the owed check
    # runs first and wins. Every failure direction fires.
    old = notice(922, 8 * 86400)
    got, primers, out = run_case(
        tmp, ep, "reply-past-ttl-but-owed",
        planted={"OWDRPL": [old]},
        debts=[{"id": 922, "kind": "reply", "from_plugin": "kimi-code",
                "to_plugin": PLUGIN, "queued_at": old["queued_at"], "drained_at": None}],
        want_ids={922})
    check("9c. a notice the fold still owes fires even past the TTL (owed wins over age)",
          922 in got and not os.path.exists(os.path.join(primers, "notice-OWDRPL.json.expired")),
          f"fired ids={sorted(got)} dir={sorted(os.listdir(primers))}\n{out[-1500:]}")

    # ---- 4. A REFUSAL IS NOT AN EMPTY DEBT.
    got, primers, out = run_case(
        tmp, ep, "refused",
        planted={"REFUSE": [notice(709, 2 * 86400)]},
        debts=[], want_ids={709}, refuse=True)
    check("4. when the unanswered RPC fails, the primer fires rather than being retired",
          709 in got and not os.path.exists(os.path.join(primers, "notice-REFUSE.json.discharged")),
          f"fired ids={sorted(got)} dir={sorted(os.listdir(primers))}\n{out[-1500:]}")

    srv.shutdown()
    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): " + ", ".join(failures))
        return 1
    print("all properties hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
