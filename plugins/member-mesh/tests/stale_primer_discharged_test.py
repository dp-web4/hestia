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
  3. UNMEASURED IS FIRED -- ON THE YOUNG EDGE. Below the 6h default floor, absence
     from the fold means "hidden by the floor", and that edge fires. The stub honours
     `older_than_secs` exactly as the daemon does, so this case is red if the guard
     ever trusts the floor, whether because the argument was misspelled (#155
     discards it into a success) or because someone deleted the min-age check as
     redundant. The OLD edge changed on 2026-09-02: past the daemon's 7d prune the
     row is gone, a binding to it is witnessed unverifiable and the sender's ledger
     cannot credit it, so a list whose every notice is past the TTL is set aside as
     `.expired` rather than fired (3a); one live notice keeps the list live (3a2).
  7. THE FOLD IS DATA, NOT AN ARGUMENT. A fold past the kernel's 128 KiB
     per-argument cap must still reach the judge (it did not: 2026-09-02).
  8. JUDGED ON A CADENCE. A retained primer whose debt is paid after startup is
     retired by the hourly sweep, without a restart and without a fire.
  4. A REFUSAL IS NOT AN EMPTY DEBT. When the `unanswered` RPC fails, the primer fires.
     `{}` and a 500 must not read as "nothing owed" -- that is the shape this corpus
     keeps finding, and here it would delete the only copy of a work list.

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
FLOORS_SEEN = []
PAD_OWED_TO_ME = 0         # case 7: rows in `owed_to_me`, which the guard never reads


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
            # The daemon ECHOES the floor it APPLIED, not the one it was asked for.
            # Measured against the live daemon 2026-08-06, same session, four cells:
            #   older_than_secs=0 -> 0 | omitted -> 21600 | older_than_seconds=0 -> 21600
            #   | older_than_secs=60 -> 60.  The misspelled cell reports the fallback,
            # which is what makes the echo usable as an oracle rather than a mirror.
            # `floor` here is post-fallback for exactly that reason.
            # `owed_to_me` is the sender's side of the ledger. The guard reads only `i_owe`,
            # but the fold travels as ONE string, and on CBP 2026-09-02 that string was
            # 388,367 bytes for claude-code at floor 0 (738 `owed_to_me` rows). Case 7
            # pads it past the kernel's per-argument limit for exactly that reason.
            pad = [{"id": 500000 + i, "kind": "review_request", "from_plugin": PLUGIN,
                    "to_plugin": "kimi-code", "queued_at": ago(3 * 86400), "drained_at": None,
                    "pointer_uri": "https://github.com/dp-web4/hestia/pull/" + str(i) + "#" + ("x" * 300)}
                   for i in range(PAD_OWED_TO_ME)]
            payload = {"i_owe": shown, "owed_to_me": pad, "older_than_secs": floor}
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


def write_fire(path, log, rc=0):
    with open(path, "w") as f:
        f.write(f'''#!/usr/bin/env bash
python3 - "$1" "{log}" <<'PY'
import json,sys
try: d=json.load(open(sys.argv[1]))
except Exception: d={{}}
open(sys.argv[2],"a").write(json.dumps({{"primer":sys.argv[1],
    "ids":[n.get("id") for n in d.get("notices",[])]}})+"\\n")
PY
exit {rc}
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
             ignore_floor_arg=False, pad_owed=0, sweep_every=None, then=None):
    """Run the real watcher once. The observable that says the startup stale pass has
    finished is the member's OWN fresh mail being fired -- the drain happens after that
    pass, so a sentinel in the log means every stale decision is already made. Never a
    fixed sleep: a duration is a coin flip on a loaded host."""
    global DEBTS, REFUSE_UNANSWERED, IGNORE_FLOOR_ARG, PAD_OWED_TO_ME
    PAD_OWED_TO_ME = pad_owed
    state = os.path.join(tmp, label)
    primers = os.path.join(state, "primers", PLUGIN)
    os.makedirs(primers)
    log = os.path.join(tmp, f"{label}.log")
    fire = os.path.join(tmp, f"{label}-fire.sh")
    write_fire(fire, log, rc=70)          # every fire REFUSES, so nothing is deleted
    for name, notices in planted.items():
        plant(primers, name, notices)

    DEBTS = list(debts)
    REFUSE_UNANSWERED = refuse
    IGNORE_FLOOR_ARG = ignore_floor_arg
    INBOX[PLUGIN] = [notice(sentinel_id, 60, kind="coordination")]

    env = dict(os.environ)
    env.update(HESTIA_MESH_STATE=state, HESTIA_ENDPOINT=ep, HOME=state,
               WATCH_INTERVAL="1", UNANSWERED_EVERY="99999",
               DISCHARGE_SWEEP_EVERY=str(sweep_every if sweep_every is not None else 99999))
    p = subprocess.Popen([WATCHER, PLUGIN, f"{PLUGIN}-watch", fire],
                         env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    deadline = time.time() + 60
    while time.time() < deadline and sentinel_id not in fired_ids(log):
        if p.poll() is not None:
            break
        time.sleep(0.2)
    if then is not None and p.poll() is None:
        # Case 8: the startup pass is over (the sentinel fired). Change the world, then
        # wait for the watcher's own cadence to notice -- never a fixed sleep.
        then(primers)
        deadline = time.time() + 30
        while time.time() < deadline and not os.path.exists(
                os.path.join(primers, "notice-SWEEPD.json.discharged")):
            if p.poll() is not None:
                break
            time.sleep(0.2)
    p.kill()
    out, _ = p.communicate()
    REFUSE_UNANSWERED = False
    IGNORE_FLOOR_ARG = False
    PAD_OWED_TO_ME = 0
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

    # ---- 3. UNMEASURED IS FIRED, BOTH EDGES.
    # 30d: past the daemon's 7d prune -- absent because pruned, not because answered.
    # 30min: below the default floor -- absent because the floor hides it. The stub
    # applies the floor for real, so if the guard leans on the fold here it retires a
    # notice that IS owed, which is the one unrecoverable error in this design.
    young = notice(901, 1800)
    got, primers, out = run_case(
        tmp, ep, "unmeasured",
        planted={"OLDOLD": [notice(330, 30 * 86400)], "YOUNGY": [young]},
        debts=[{"id": 901, "kind": "reply", "from_plugin": "kimi-code",
                "to_plugin": PLUGIN, "queued_at": young["queued_at"], "drained_at": None}],
        want_ids={330, 901})
    # 3a REVERSED 2026-09-02. It used to read "past the inbox TTL is unmeasured, so it
    # fires". Past the TTL the daemon has pruned the row: a disposition bound to it is
    # witnessed `binding_verified: false`, the sender's `owed_to_me` cannot hold it, and
    # the fire buys a wake whose answer discharges nothing. Measured on CBP the day of
    # the change: 11 of 21 consecutive kimi-code stale re-fires were on notices 8-15
    # days old, all answered on the chain in August, all re-answered unverifiably. So a
    # list whose EVERY notice is past the TTL is set aside as `.expired` -- kept, named
    # in the journal, never fired. A list with one live notice still fires (3a2).
    check("3a. a notice past the inbox TTL is owed to nobody, so it is set aside, not fired",
          330 not in got
          and os.path.exists(os.path.join(primers, "notice-OLDOLD.json.expired"))
          and not os.path.exists(os.path.join(primers, "notice-OLDOLD.json")),
          f"fired ids={sorted(got)} dir={sorted(os.listdir(primers))}\n{out[-1500:]}")
    check("3a1. and it is set ASIDE, not retired as discharged (nobody proved that)",
          not os.path.exists(os.path.join(primers, "notice-OLDOLD.json.discharged")),
          f"dir={sorted(os.listdir(primers))}")
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

    # ---- 4. A REFUSAL IS NOT AN EMPTY DEBT.
    got, primers, out = run_case(
        tmp, ep, "refused",
        planted={"REFUSE": [notice(709, 2 * 86400)]},
        debts=[], want_ids={709}, refuse=True)
    check("4. when the unanswered RPC fails, the primer fires rather than being retired",
          709 in got and not os.path.exists(os.path.join(primers, "notice-REFUSE.json.discharged")),
          f"fired ids={sorted(got)} dir={sorted(os.listdir(primers))}\n{out[-1500:]}")

    # ---- 7. THE FOLD IS DATA, NOT AN ARGUMENT.
    # Identical to case 1 -- two days old, nothing owed, retirable -- with one change
    # the guard is not supposed to see: the fold is large. `primer_spent` handed the
    # whole fold to python as ONE argv string, and Linux caps a single argument at
    # MAX_ARG_STRLEN = 131072 bytes (32 pages; measured on CBP: 131,000 passes,
    # 131,072 fails). Past that, `python3` never starts: bash prints "Argument list
    # too long", the function returns nonzero, and nonzero is the guard's "unmeasured
    # -> fire" arm. So a fold that has grown past 128 KiB fires EVERY retained primer,
    # discharged or not, at every restart, to the attempt budget -- which is what the
    # kimi-code watcher on CBP did on 2026-09-02: 21 consecutive stale re-fires from
    # 04:22Z to 10:26Z, "Argument list too long" printed before 8 of the 8 whose
    # journal survived, four of them on notices already answered with
    # `binding_verified: true` in August. The fold crosses the limit on its own: the
    # claude-code fold at floor 0 was 388,367 bytes the same day, and every stale
    # re-fire adds rows to the peer's fold. Red before the fix; the padding rows sit
    # in `owed_to_me`, which the guard does not read, so the ONLY thing that can fail
    # here is delivery of the fold to the judge.
    got, primers, out = run_case(
        tmp, ep, "big-fold",
        planted={"BIGFLD": [notice(709, 2 * 86400)]},
        debts=[], want_ids=set(), pad_owed=600)
    check("7a. a discharged primer is retired even when the fold exceeds the kernel's "
          "per-argument limit (128 KiB)", got == set(),
          f"fired ids={sorted(got)}\n{out[-1500:]}")
    check("7b. and the watcher did not print 'Argument list too long' on the way",
          "Argument list too long" not in out, out[-1500:])

    # ---- 3a2. A LIST WITH ONE LIVE NOTICE IS A LIVE LIST.
    # The set-aside is for lists the daemon has forgotten ENTIRELY. One notice inside
    # the window beside two past it: the live one is still owed (it is in `i_owe`), so
    # the whole list fires, exactly as before.
    live = notice(931, 2 * 86400)
    got, primers, out = run_case(
        tmp, ep, "mixed-age",
        planted={"MIXAGE": [notice(930, 30 * 86400), live, notice(932, 31 * 86400)]},
        debts=[{"id": 931, "kind": "reply", "from_plugin": "kimi-code",
                "to_plugin": PLUGIN, "queued_at": live["queued_at"], "drained_at": None}],
        want_ids={930, 931, 932})
    check("3a2. a list with one live, owed notice beside expired ones still fires whole",
          {930, 931, 932} <= got
          and not os.path.exists(os.path.join(primers, "notice-MIXAGE.json.expired")),
          f"fired ids={sorted(got)} dir={sorted(os.listdir(primers))}\n{out[-1500:]}")

    # ---- 8. JUDGED INSIDE THE WINDOW, NOT ONLY AT RESTART.
    # The startup pass is the only place a retained primer was ever judged, and a
    # watcher restarts rarely (kimi-code on CBP: 2026-08-20 -> 09-01 without one). A
    # primer retained during that run was first judged twelve days later, past the 6d
    # judging window, and could only be "unmeasured -> fire": 45 of 57 claude-code
    # retained primers were in that state on 2026-09-02. Here the primer is OWED at
    # startup (fires, is preserved), the debt is then paid, and the watcher's own sweep
    # must retire it -- without a restart and without a second fire.
    owed8 = notice(940, 2 * 86400)
    debt8 = {"id": 940, "kind": "reply", "from_plugin": "kimi-code",
             "to_plugin": PLUGIN, "queued_at": owed8["queued_at"], "drained_at": None}

    def pay(primers):
        global DEBTS
        DEBTS = []

    got, primers, out = run_case(
        tmp, ep, "swept",
        planted={"SWEEPD": [owed8]},
        debts=[debt8], want_ids={940}, sweep_every=1, then=pay)
    check("8a. an owed primer fires at startup and is preserved", 940 in got, f"{out[-1500:]}")
    check("8b. once the debt is paid, the cadence sweep retires it without a restart",
          os.path.exists(os.path.join(primers, "notice-SWEEPD.json.discharged"))
          and not os.path.exists(os.path.join(primers, "notice-SWEEPD.json")),
          f"dir={sorted(os.listdir(primers))}\n{out[-1500:]}")
    check("8c. and the sweep never fires: exactly one fire of 940, the startup one",
          sum(1 for f in fired(os.path.join(tmp, "swept.log")) if 940 in f["ids"]) == 1,
          f"{fired(os.path.join(tmp, 'swept.log'))}")

    srv.shutdown()
    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): " + ", ".join(failures))
        return 1
    print("all properties hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
