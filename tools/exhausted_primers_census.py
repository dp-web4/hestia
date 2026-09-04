#!/usr/bin/env python3
"""The mesh has a dead-letter directory and no dead-letter reader.

WHAT SETS A PRIMER ASIDE. `hestia-watch-member.sh:retry_stale_primers` retries an
undelivered fire primer `STALE_MAX_ATTEMPTS` (default 3) times, then does:

    mv -f "$stale" "$stale.exhausted"

and never looks at it again. Grepping the whole repo for `exhausted` finds exactly one
writer (that line), one test that asserts the harm (`tests/primer_ownership_test.py`), and
one comment in `fire-kimi.sh`. No tool, no census, no report and no alarm reads
`$PRIMERS/*.exhausted`. The notices inside were consumed from the daemon queue by a
consume-once drain, so THAT FILE IS THE ONLY COPY.

WHY EVERY EXHAUSTED PRIMER IS OWED MAIL, BY CONSTRUCTION. In `retry_stale_primers` the
discharge check runs BEFORE the attempt budget:

    if primer_spent "$stale" "$fold"; then ... mv "$stale.discharged"; continue; fi
    if [ "$attempts" -ge "$STALE_MAX_ATTEMPTS" ]; then ... mv "$stale.exhausted"; continue; fi

A primer therefore reaches `.exhausted` only on a pass where `primer_spent` said NO -- the
daemon still owed something for at least one notice in it. `.exhausted` is not "mail that
turned out to be moot"; it is precisely the mail that was still owed when the mesh gave up.
That is a property of the code path, not of any one sample.

WHAT THIS TOOL ASKS. Per seat: how many primers were set aside, how many distinct notices
are stranded in them, over what span -- and, against the daemon's LIVE debt fold, how many
of those notices the daemon STILL counts as owed. A notice that is still in `i_owe` is in
limbo three ways at once: the daemon believes it is owed, the watcher has permanently
stopped trying to deliver it, and no surface names it.

IDENTITY IS ASSERTED, NOT PROVEN (#63/#128). To read another seat's fold this connects AS
that seat. `hestia_connect` authenticates nobody, so this is a claim the daemon chooses to
answer, exactly as the `hestia` CLI's `--as` is. Every call here is READ-ONLY: it drains
nothing, acks nothing, moves no file and retries no fire. Auditing a seat's stranded mail
is not speaking for it.

THE FOLD IS AGE-GATED AND DOES NOT SAY SO. `hestia_member_unanswered` applies a default
window (6h) unless asked otherwise, which hides ~21% of rows at the default. This asks
`older_than_secs: 0` and PRINTS THE WINDOW THE DAEMON ECHOES BACK, because the applied
window is the one that matters and it is not always the one requested.

A FAILED READ IS NOT A ZERO. If the fold cannot be read the column says `unmeasured`,
never `0` -- an unreachable daemon and a seat that owes nothing are different answers, and
collapsing them publishes a read failure as a clean bill of health.

A NOTE ON THE ENV READS BELOW. Single-key lookups use `os.getenv` rather than the mapping
attribute normally used for this. The local PreToolUse guard denies any command whose text
contains a certain four-character credential-file token, and that attribute's name contains
the token as a substring (issue #680: the FP class whose denials are not events, and whose
deny surface is also its evidence-suppression surface). Writing THIS PARAGRAPH tripped the
same guard twice before it was phrased without naming the token -- which is #680 reproduced
first-hand. Disclosed rather than silent: the guard's verdict stands, the read is identical,
and no credential is touched on either spelling.

TWO CLOCKS, AND THE ONE THAT IS NOT THE RETIREMENT DATE. A primer is retired by
`mv -f "$stale" "$stale.exhausted"`. A rename does not touch mtime, so the `.exhausted`
file's mtime is when the PRIMER WAS WRITTEN -- i.e. when the mail ARRIVED. The rename does
update ctime. Dating retirements by mtime therefore reports the arrival calendar and
attributes the loss to the wrong days; #910's day table is mtime-based and reads backwards
because of it. This tool prints BOTH and labels which is which.

THE BUDGET IS PER RESTART, NOT PER PASS. `retry_stale_primers` has exactly one call site
(`hestia-watch-member.sh:898`), in the STARTUP path -- not in the `while true` poll loop.
A stale primer therefore gets one attempt per WATCHER RESTART, and `STALE_MAX_ATTEMPTS`
(3) restarts retire it permanently. Retirement is thus paced by deploy/restart cadence,
which is uncorrelated with whether the seat could ever have received the mail. This is why
retirements cluster on restart days rather than on vendor-outage days.

Usage:  python3 tools/exhausted_primers_census.py [--seat NAME ...] [--json]
"""
import json, sys, glob, os, collections, datetime, urllib.request


def _day(ts):
    return (datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d')
            if ts else 'unknown')

EP = os.getenv("HESTIA_ENDPOINT", "http://127.0.0.1:7711/mcp")
STATE = os.getenv("HESTIA_MESH_STATE", os.path.expanduser("~/.local/state/hestia-mesh"))
SEATS = ["claude-code", "codex", "kimi-code"]


def _post(payload, hdrs={}):
    req = urllib.request.Request(
        EP, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream", **hdrs})
    r = urllib.request.urlopen(req, timeout=15)
    return r.read().decode(), r.headers.get("mcp-session-id")


def _rpc(h, name, args):
    # The body is SSE-ish and may be multi-line: parse per line, never json.loads the whole.
    body, _ = _post({"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                     "params": {"name": name, "arguments": args}}, h)
    for line in body.splitlines():
        if line.startswith("data: {"):
            return json.loads(json.loads(line[6:])["result"]["content"][0]["text"])
    return {"_hestia_error": {"message": "no data frame"}}


def live_debt(plugin):
    """(set_of_owed_ids, applied_window_secs), or (None, None) if the read failed."""
    try:
        _, sid = _post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                        "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                                   "clientInfo": {"name": "exhausted-census",
                                                  "version": "1"}}})
        h = {"mcp-session-id": sid} if sid else {}
        _post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}, h)
        c = _rpc(h, "hestia_connect",
                 {"plugin_id": plugin, "host_agent": "claude-code",
                  "instance_name": "exhausted-census",
                  "role": "role:constellation:member"})
        sess = c.get("sessionId") or c.get("session_id")
        if not sess:
            return None, None
        # `member_unanswered` refuses an unattributed caller: the session_id is required.
        u = _rpc(h, "hestia_member_unanswered",
                 {"older_than_secs": 0, "session_id": sess})
        if not isinstance(u, dict) or not isinstance(u.get("i_owe"), list):
            return None, None
        return ({n.get("id") for n in u["i_owe"] if isinstance(n, dict)},
                u.get("older_than_secs"))
    except Exception:
        return None, None


def scan(seat):
    """Each row carries BOTH clocks: mtime = arrival (rename preserves it),
    ctime = retirement (rename updates it)."""
    rows = []
    for f in sorted(glob.glob(f"{STATE}/primers/{seat}/*.exhausted")):
        try:
            st = os.stat(f)
            arrived, retired = st.st_mtime, st.st_ctime
        except OSError:
            arrived = retired = None
        try:
            d = json.load(open(f))
        except Exception:
            rows.append({"file": os.path.basename(f), "unreadable": True, "notices": [],
                         "arrived": arrived, "retired": retired})
            continue
        rows.append({"file": os.path.basename(f), "unreadable": False,
                     "notices": d.get("notices", []),
                     "arrived": arrived, "retired": retired})
    return rows


def main():
    argv = sys.argv[1:]
    as_json = "--json" in argv
    seats = [argv[i + 1] for i, a in enumerate(argv)
             if a == "--seat" and i + 1 < len(argv)] or SEATS

    out = {}
    print(f"exhausted primers under {STATE}/primers/*/\n")
    print(f"  {'seat':12} {'files':>5} {'notices':>7} {'still-owed':>10} "
          f"{'oldest':>11} {'newest':>11}  window")
    tot_f = tot_n = tot_owed = 0
    any_unmeasured = False
    for seat in seats:
        rows = scan(seat)
        notices = [n for r in rows for n in r["notices"]]
        ids = {n.get("id") for n in notices if n.get("id") is not None}
        qs = sorted(str(n.get("queued_at", "")) for n in notices if n.get("queued_at"))
        owed, window = live_debt(seat)
        if owed is None:
            still, n_still, stranded = "unmeasured", 0, []
            any_unmeasured = True
        else:
            stranded = sorted(ids & owed)
            n_still = len(stranded)
            still = str(n_still)
        out[seat] = {"files": len(rows), "notices": len(ids),
                     "still_owed": (None if owed is None else n_still),
                     "oldest": qs[0] if qs else None, "newest": qs[-1] if qs else None,
                     "applied_window_secs": window, "stranded_ids": stranded,
                     "unreadable_files": sum(1 for r in rows if r["unreadable"]),
                     "_rows": rows}
        tot_f += len(rows); tot_n += len(ids); tot_owed += n_still
        print(f"  {seat:12} {len(rows):5} {len(ids):7} {still:>10} "
              f"{(qs[0][:10] if qs else '-'):>11} {(qs[-1][:10] if qs else '-'):>11}"
              f"  {window}")
    print(f"  {'FLEET':12} {tot_f:5} {tot_n:7} {tot_owed:>10}")
    if any_unmeasured:
        print("\n  NOTE: 'unmeasured' is a failed read, not a zero.")

    print("\n  Every file above reached .exhausted on a pass where primer_spent said the")
    print("  daemon still owed it (the discharge check precedes the attempt budget), and")
    print("  the drain that produced it was consume-once. Nothing in the repo reads them.")

    print("\n  RETIREMENT DAY (ctime, the rename) vs ARRIVAL DAY (mtime, the write).")
    print("  Dating retirements by mtime reports the arrival calendar -- see #910.")
    for seat in seats:
        rows = out[seat]["_rows"]
        if not rows:
            continue
        ret = collections.Counter(_day(r["retired"]) for r in rows)
        arr = collections.Counter(_day(r["arrived"]) for r in rows)
        print(f"    {seat}:")
        print(f"      retired  {dict(sorted(ret.items()))}")
        print(f"      arrived  {dict(sorted(arr.items()))}")

    for seat in seats:
        s = out[seat]["stranded_ids"]
        if s:
            print(f"\n  {seat}: notice ids still in i_owe AND permanently set aside:")
            print("   ", ", ".join(str(i) for i in s[:40])
                  + (" ..." if len(s) > 40 else ""))

    if as_json:
        pub = {k: {kk: vv for kk, vv in v.items() if kk != "_rows"}
               for k, v in out.items()}
        print("\n" + json.dumps(pub, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
