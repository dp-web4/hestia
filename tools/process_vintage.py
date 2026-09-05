#!/usr/bin/env python3
"""Date the source a RUNNING process is executing — and refuse the witnesses that lie.

WHY THIS EXISTS. `tools/vintage_from_wire.py` (PR #614) dates a deployment from the
CHAIN, and its docstring concedes the case it cannot reach: "that is true of the mesh
fire scripts, which the watchers exec by argv path out of a shared dev tree". The
premise there is that a long-running process's vintage is unmeasurable — you can only
infer it from restart time and branch archaeology.

That premise is FALSE, and this file is the counterexample. Measured on CBP 2026-08-26
against the three member-mesh watchers, FOUR witnesses were available and THREE of them
disagreed. Only cross-checking caught it:

    witness                          said                        verdict
    cat /proc/PID/fd/255             current (54340B, 08-25)     FALSE
    stat -L /proc/PID/fd/255         48681B, mtime 08-18 18:27   FALSE for execution
    WATCH_STARTUP_SHA256 (journal)   489c0076 = a8dccda, 08-06   TRUE
    primer key census / behaviour    predates 08-19 and 08-20    TRUE, independent

WHY EACH FALSE WITNESS IS FALSE — both failure modes are silent and both read as "fine":

  1. `cat /proc/PID/fd/255` RE-OPENS BY PATH on a DrvFs/9p mount (WSL `/mnt/c`), so it
     hands back the CURRENT file even when the fd's own inode is a different, deleted
     one. It reports every stale process as up to date. `stat -L` on the SAME fd said
     48681 bytes while `cat` on it returned 54340 — one fd, two answers. If the two
     agree you have learned nothing; only the DISAGREEMENT is informative.

  2. `stat -L /proc/PID/fd/255` reads the held inode honestly, but the held inode is not
     what is executing. Bash parses a `while` loop — one compound command — ONCE, in
     full, at startup. An in-place rewrite afterwards (a `>` redirect, which truncates
     and grows the SAME inode) changes the bytes the fd sees and changes NOTHING about
     the semantics already parsed into memory. So fd-stat dates the inode's later life,
     not the parse.

WHAT IS TRUE. The vintage of a long-running interpreter is fixed at PARSE TIME, so the
only sound witness is one captured AT STARTUP by the process itself, or a downstream
artifact whose SHAPE the running code determines:

  * a startup self-hash the process prints (member-mesh: `WATCH_STARTUP_SHA256`, emitted
    hourly on the `[hestia-watch] ARTIFACT ...` level line);
  * a KEY CENSUS of an artifact the process writes — a key a known commit added is
    absent below that commit and present above it, exactly the partition
    `vintage_from_wire.py` uses on chain payloads, applied to a file instead;
  * a BEHAVIOURAL probe — a branch a known commit added either runs or does not.

A startup self-hash is a claim by the subject about itself, which is why it is not
enough alone: #567's guard pinned SOURCE and printed "all checks passed" while the
RENDER was broken. Confirm it with a census or a probe, which are properties of output
and cannot be self-reported wrong.

WHAT THIS FOUND. claude-code and kimi-code watchers were executing a8dccda
(2026-08-06); codex was current. FIVE commits to that file had merged to main in
between, including `ebc3719` ("rc=124 proves the primer was delivered — stop reporting
it undelivered"). The fleetwide "undelivered" epidemic was that lag, on two seats,
announced hourly into a journal nobody read.

A startup self-hash also has to be BOUND TO THE RUNNING INVOCATION to mean anything.
`journalctl -u <unit>` spans every invocation still inside the retention window, so its
last ARTIFACT line can be the exit statement of a process that is gone. `cmd_units`
therefore reads `_SYSTEMD_INVOCATION_ID` for the current run, refuses outright on a unit
that is not active, and refuses again when the current invocation has not yet emitted a
level line — the last case being exactly the hour after a restart, when someone is
checking whether the restart took.

Usage:
    process_vintage.py units                 # every member-mesh watcher, resolved
    process_vintage.py fd <pid> <path>       # the two-witness fd contradiction check
"""
import hashlib
import os
import re
import subprocess
import sys

# `[hestia-watch] ARTIFACT plugin=X state=Y reason=Z startup_sha256=... disk_sha256=...`
# The LEVEL line, not the edge alarm. The edge fires once and is gone with the journal's
# retention window; a process older than that window has no edge left to read, which is
# how a 20-day drift stayed invisible while being correctly detected the whole time.
#
# WHY THIS IS AN ANCHOR PLUS A KEY SCAN, NOT ONE ORDERED REGEX. The first version of
# this file (#634) matched `startup_sha256=(\S+)\s+disk_sha256=(\S+)` — the two fields
# ADJACENT, in that order. The NEXT merged PR to the watcher (#636, same day) inserted
# `startup_origin=` between them. From that merge until 2026-09-03 this tool reported
# `vintage NOT MEASURED` for EVERY watcher on the box while the measurement sat in the
# journal, and it said so in the reassuring spelling: "wait for the next level line."
# The line had already arrived. It was never going to parse.
#
# Nothing caught it because the test's fixture was a real journal line captured on
# 2026-08-26 — real, and from before the field existed. A fixture pinned to a capture
# date cannot see a producer that moved after it. So: order-independent key scan for
# the fields we need, unknown fields tolerated BY CONSTRUCTION, and a drift guard
# (`test_the_watcher_still_emits_every_field_this_tool_reads`) that reads the producer
# instead of a copy of its past output.
#
# The anchor stays STRICT — `[hestia-watch] ARTIFACT plugin=` verbatim — for two
# reasons. It is what every one of the 18 committed watcher versions that emit a level
# line actually prints (the other 10 predate the line; no unprefixed spelling has ever
# existed, checked across history). And it excludes the shapes that must NOT be read as
# a level measurement: the `ARTIFACT DRIFT`/`ARTIFACT UNVERIFIABLE` edge alarms, the
# `ARTIFACT DEPLOY plugin=` line #636 added, and journal lines that merely QUOTE a
# notice pointer containing the word.
ARTIFACT_ANCHOR = re.compile(r"\[hestia-watch\]\s+ARTIFACT\s+plugin=")

# `key=value` up to the next whitespace. Values are never quoted or spaced on this line
# (the watcher builds it from unquoted shell expansions), so `\S+` is exact, not lossy.
_KV_RE = re.compile(r"(?P<k>[A-Za-z0-9_]+)=(?P<v>\S+)")

# field on the wire -> key this tool exposes. Adding a name here is how you consume a
# new watcher field; it becomes REQUIRED, and the drift guard then pins it.
ARTIFACT_FIELDS = {
    "plugin": "plugin",
    "state": "state",
    "reason": "reason",
    "startup_sha256": "startup",
    "disk_sha256": "disk",
}

WATCHER_UNITS = ("hestia-watch-claude", "hestia-watch-codex", "hestia-watch-kimi")
WATCH_PATH = "plugins/member-mesh/hestia-watch-member.sh"


def parse_artifact(line):
    """Pull the startup/disk pair out of one ARTIFACT level line.

    Three outcomes, and the caller MUST tell the last two apart:

      * `None`               — not a level line at all. Nothing was claimed.
      * dict, `missing` []   — a measurement. `startup`/`disk` are raw strings;
                               validating them is `classify`'s job, because "this field
                               is not a sha" is a state the watcher reports deliberately
                               (`unverifiable`) and collapsing it into a parse failure
                               would hide it.
      * dict, `missing` [..] — THIS TOOL IS STALE. The producer emitted a level line
                               and it does not carry a field this reader requires. That
                               is a fact about the reader, and returning `None` for it
                               (what #634 did) is what let the producer move for a day
                               while the tool reported "not measured yet". Anything that
                               reads this must say so out loud rather than fall through
                               to the wait-for-the-next-line branch.
    """
    line = line or ""
    m = ARTIFACT_ANCHOR.search(line)
    if not m:
        return None
    kv = {mm.group("k"): mm.group("v")
          for mm in _KV_RE.finditer(line[m.start():])}
    out = {ours: kv.get(wire) for wire, ours in ARTIFACT_FIELDS.items()}
    out["missing"] = sorted(w for w in ARTIFACT_FIELDS if w not in kv)
    return out


def classify(startup, disk):
    """drift / ok / unverifiable, from the pair alone.

    Mirrors `check_artifact_drift` in the watcher so a reader can check the tool against
    the shell without running either. `unverifiable` is NOT `ok`: an absent baseline
    means the question was never answerable, and reporting that as agreement is the
    absence-read-as-pass this whole corpus keeps re-finding.
    """
    hexish = lambda s: bool(re.fullmatch(r"[0-9a-f]{64}", s or ""))
    if not hexish(startup):
        return "unverifiable", "startup-baseline-unavailable"
    if not hexish(disk):
        return "unverifiable", "disk-hash-unavailable"
    if startup != disk:
        return "drift", "differs-from-startup"
    return "ok", "matches-startup"


def fd_witnesses(fd_size, fd_readback_sha, disk_size, disk_sha):
    """Name which fd witness is lying, across ALL FOUR input combinations.

    The point of returning a VERDICT rather than a boolean: when `cat` and `stat`
    agree, that is not corroboration — on a filesystem where `cat` re-opens by path,
    agreement is exactly what an up-to-date process AND a stale one both produce. Only
    disagreement carries information, so `agree` is reported as UNINFORMATIVE.

    CONTENT DECIDES, SIZE NEVER DOES. `git_versions` below already refuses size as a
    key because a 48681-byte inode collided with an unrelated 48681-byte blob. The
    first version of this function applied that doctrine to the commit lookup and NOT
    to the fd two lines above it: `(readback != disk, size == disk)` fell through to
    the agreement arm and printed "both fd witnesses match the on-disk file" about a
    readback that provably did not. Named by codex and kimi-code independently on
    PR #634. Every arm below now branches on the readback first.
    """
    readback_is_disk = (fd_readback_sha == disk_sha)
    stat_is_disk = (fd_size == disk_size)
    if readback_is_disk and not stat_is_disk:
        return ("cat-lies",
                "cat re-opened by path (DrvFs/9p): it returned the CURRENT file while "
                "stat on the same fd reports a different inode. Trust neither for "
                "execution vintage; use the startup self-hash.")
    if not readback_is_disk and not stat_is_disk:
        return ("fd-holds-old-inode",
                "the fd genuinely holds a superseded inode — but that still dates the "
                "INODE, not the parse. Confirm with a startup hash or key census.")
    if not readback_is_disk and stat_is_disk:
        return ("fd-content-differs-size-collides",
                "the fd's CONTENT differs from disk while the sizes happen to match — "
                "a same-size rewrite, or a read caught mid-write. The size agreement "
                "is a collision and carries nothing; this is the old-content case. "
                "It still dates the INODE, not the parse: use the startup self-hash.")
    return ("agree-uninformative",
            "both fd witnesses match the on-disk file. This does NOT show the process "
            "is current: it is also what a stale process looks like when cat re-opens "
            "by path. Uninformative either way.")


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def _run(args):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=60).stdout
    except Exception:
        return ""


def git_versions(repo, path):
    """sha256 -> (commit, iso date, subject) for every committed version of `path`.

    Keyed on the CONTENT hash, never on size: measured 2026-08-26, a 48681-byte inode
    matched a 48681-byte blob at `8af9a76` whose sha256 was entirely different. Size is
    a collision-rich key that produces a confident wrong commit id.
    """
    out = {}
    revs = _run(["git", "-C", repo, "rev-list", "--all", "--", path]).split()
    for c in revs:
        blob = _run(["git", "-C", repo, "rev-parse", f"{c}:{path}"]).strip()
        if not blob:
            continue
        raw = subprocess.run(["git", "-C", repo, "cat-file", "-p", blob],
                             capture_output=True, timeout=60).stdout
        h = sha256_bytes(raw)
        if h not in out:
            meta = _run(["git", "-C", repo, "log", "-1", "--format=%cI\t%s", c]).strip()
            date, _, subj = meta.partition("\t")
            out[h] = (c[:7], date, subj)
    return out


def unit_state(unit):
    """ActiveState / MainPID / InvocationID for ONE unit. Empty dict if systemd is not
    answering — an empty dict is a refusal downstream, never a default.

    Queried one unit at a time on purpose: `systemctl show a b c` emits unlabelled
    property blocks in argument order, so a batched call is positional and one missing
    unit silently shifts every later answer onto the wrong name.
    """
    out = {}
    for line in _run(["systemctl", "--user", "show", unit,
                      "-p", "ActiveState", "-p", "MainPID",
                      "-p", "InvocationID"]).splitlines():
        k, _, v = line.partition("=")
        if k:
            out[k] = v.strip()
    return out


def invocation_log(unit, invocation_id):
    """The journal for the CURRENT run of `unit`, and whether it is actually bound.

    `journalctl -u <unit>` spans EVERY invocation still inside the retention window,
    so the last ARTIFACT line in it can belong to a process that no longer exists.
    Measured on CBP 2026-08-26: retention held 1h46m while the ARTIFACT level line is
    emitted HOURLY — so for up to an hour after a restart, the unit-wide query returns
    the PREVIOUS invocation's startup hash. That is precisely the minute someone runs
    this tool to check whether their restart took, and the unbound version would have
    told them it did not. Bind to `_SYSTEMD_INVOCATION_ID` or say you did not.
    """
    if invocation_id:
        return _run(["journalctl", "--user", "-o", "short-iso",
                     f"_SYSTEMD_INVOCATION_ID={invocation_id}", "--no-pager"]), True
    return _run(["journalctl", "--user", "-o", "short-iso",
                 "-u", unit, "--no-pager"]), False


# ---------------------------------------------------------------------------
# WHY THERE IS NO LEVEL LINE. `cmd_units` used to answer that question with a
# reassurance: "wait for the next level line." Measured on CBP 2026-09-03, with
# #880's parser fix already merged, that reassurance was false on the only active
# watcher on the box. The level line is emitted by `announce_artifact`, which lives
# INSIDE the watcher's main `while true` loop. `retry_stale_primers` runs once
# BEFORE that loop, as a `for` over every retained primer, and each iteration fires
# a full synchronous wake (14-29 min observed). With 46 primers retained the loop is
# not reached for the better part of a day, and for that whole time the gauge is not
# late — it is UNREACHABLE CODE for that process.
#
# This is the same defect class the rest of this file is about, one level up: an
# absent artifact read as a property of the subject rather than of the path to it.
# "No level line yet" and "no level line ever, by construction" are opposite verdicts
# and the tool printed the reassuring one for both.
#
# The discriminator is already in the journal and needs nothing deployed: the sweep
# announces itself on every iteration, and the loop announces itself on every gauge
# period. Sweep lines present + zero loop lines, spanning longer than one gauge
# period, is starvation. The span is read from the journal's own timestamps, so it is
# a LOWER bound (retention truncates the left edge) - which is the conservative
# direction: it can only under-report how long the loop has been unreachable.
SWEEP_MARKS = ("[hestia-watch] STALE PRIMER", "[hestia-watch] RETRYING stale primer")
# Every line the main loop emits on its gauge tick. `announce_unanswered` is
# deliberately NOT here: it prints nothing when the member owes nothing, so its
# absence is not evidence.
LOOP_MARKS = ("[hestia-watch] ARTIFACT plugin=", "[hestia-watch] DAEMON ")
RETRY_RE = re.compile(r"RETRYING stale primer \(attempt \d+/\d+\): (?P<primer>\S+)")
# `-o short-iso` puts `2026-09-03T13:02:14-0700` first on every line.
STAMP_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})")
# Quotes optional on purpose: the watcher spells it `UNANSWERED_EVERY="${...:-3600}"`
# today and an unquoted form is equally valid shell. A reader that pins the QUOTING
# of the producer fails the same way a reader that pins field order does.
GAUGE_PERIOD_RE = re.compile(
    r"^UNANSWERED_EVERY=[\"']?\$\{UNANSWERED_EVERY:-(\d+)\}", re.M)
GAUGE_PERIOD_DEFAULT = 3600


def gauge_period(repo):
    """Seconds between level lines, read from the PRODUCER, not assumed.

    A constant copied into the reader is the failure #880 fixed in the parser: the
    watcher moved and the reader did not. Read it out of the watcher source; fall
    back only if the source cannot be read, and the caller says which it got.
    """
    try:
        with open(os.path.join(repo, WATCH_PATH)) as fh:
            m = GAUGE_PERIOD_RE.search(fh.read())
        if m:
            return int(m.group(1)), "watcher source"
    except OSError:
        pass
    return GAUGE_PERIOD_DEFAULT, "fallback default"


def _stamp_seconds(line):
    """Seconds-of-day for one journal line, or None. Day-of-month is carried so a
    span that crosses midnight is not silently folded into a negative number."""
    m = STAMP_RE.match(line or "")
    if not m:
        return None
    return (m.group(1),
            int(m.group(2)) * 3600 + int(m.group(3)) * 60 + int(m.group(4)))


def journal_span(lines):
    """Wall seconds between the first and last stamped line, or None."""
    stamps = [x for x in (_stamp_seconds(l) for l in lines) if x]
    if len(stamps) < 2:
        return None
    (d0, s0), (d1, s1) = stamps[0], stamps[-1]
    span = s1 - s0
    if d1 != d0:                      # one or more midnights; count them
        from datetime import date
        y0, m0, dd0 = (int(x) for x in d0.split("-"))
        y1, m1, dd1 = (int(x) for x in d1.split("-"))
        span += (date(y1, m1, dd1) - date(y0, m0, dd0)).days * 86400
    return span


def list_primers(directory):
    """The retained primers a restart would sweep, in the order bash's glob yields.

    Seam, not convenience: the tests stub this, and the ORDER is load-bearing. The
    watcher iterates `for stale in "$PRIMERS"/notice-*.json`, and bash expands that
    glob ONCE, under the unit's collation (no LANG is set by the unit, so C). Sorting
    any other way would report a sweep position that is not the sweep's position.
    """
    import glob
    return sorted(glob.glob(os.path.join(directory, "notice-*.json")))


def sweep_diagnosis(log, period):
    """Is this invocation starved inside the pre-loop stale-primer sweep?

    Returns None when the journal cannot tell (no sweep lines, or unstamped), so the
    caller keeps its old, honest "not due yet" wording rather than inventing a cause.
    A loop line present is decisive the other way: the loop HAS been reached, and the
    missing level line is then a real question this function is not the answer to.
    """
    lines = (log or "").splitlines()
    sweep = [l for l in lines if any(m in l for m in SWEEP_MARKS)]
    loop = [l for l in lines if any(m in l for m in LOOP_MARKS)]
    if loop or not sweep:
        return None
    span = journal_span(sweep)
    if span is None or span < period:
        return None
    d = {"span": span, "sweeps": len(sweep), "primer": None,
         "position": None, "pending": None, "directory": None}
    retries = [m.group("primer") for m in
               (RETRY_RE.search(l) for l in lines) if m]
    if retries:
        d["primer"] = retries[-1]
        d["directory"] = os.path.dirname(retries[-1])
        pending = list_primers(d["directory"])
        if d["primer"] in pending:
            d["position"] = pending.index(d["primer"]) + 1
            d["pending"] = len(pending)
    return d


def humanise(seconds):
    h, m = divmod(int(seconds) // 60, 60)
    return f"{h}h{m:02d}m" if h else f"{m}m"


def cmd_units(repo):
    versions = git_versions(repo, WATCH_PATH)
    print(f"{len(versions)} distinct committed versions of {WATCH_PATH}\n")
    for unit in WATCHER_UNITS:
        st = unit_state(unit)
        active = st.get("ActiveState")
        if active != "active":
            # A stopped unit has no vintage. Its last journal line dates the process
            # that EXITED, and reporting that as "in force" is the same shape as the
            # bug this whole file is about: an artifact outliving its producer.
            print(f"{unit}: unit is {active or 'not reported by systemd'} — vintage "
                  f"NOT MEASURED. Nothing is executing; the last journal line dates "
                  f"the process that exited, not one in force.\n")
            continue
        log, bound = invocation_log(unit, st.get("InvocationID"))
        art = None
        art_line = ""
        for line in log.splitlines():
            parsed = parse_artifact(line)
            if parsed:
                art, art_line = parsed, line   # keep the LAST — the level line, hourly
        if art and art["missing"]:
            # Do NOT fall through to "wait for the next level line". The line is here.
            print(f"{unit}: level line PRESENT but UNREADABLE by this tool — vintage "
                  f"NOT MEASURED, and the defect is in the READER. Missing field(s): "
                  f"{', '.join(art['missing'])}. The watcher emitted a level line this "
                  f"file does not know how to read, so add the field to "
                  f"ARTIFACT_FIELDS. This is NOT 'the restart has not reported yet'.")
            print(f"    line: {art_line.strip()[:200]}\n")
            continue
        if not art:
            if bound:
                period, source = gauge_period(repo)
                starved = sweep_diagnosis(log, period)
                if starved:
                    where = ""
                    if starved["position"]:
                        where = (f" Sweep position {starved['position']} of "
                                 f"{starved['pending']} in {starved['directory']}; "
                                 f"{starved['pending'] - starved['position']} primer(s) "
                                 f"still to fire.")
                    print(f"{unit}: active as pid {st.get('MainPID') or '?'} and "
                          f"STARVED — vintage NOT MEASURED, and the level line is not "
                          f"late, it is unreachable. This invocation has been inside "
                          f"the pre-loop stale-primer sweep for at least "
                          f"{humanise(starved['span'])} ({starved['sweeps']} sweep "
                          f"announcements, zero main-loop announcements, gauge period "
                          f"{period}s from {source}). Until the sweep ends the watcher "
                          f"also does not poll for live mail, does not check daemon "
                          f"drift, and does not run maybe_self_deploy — so it cannot "
                          f"adopt the merged fix for this.{where}\n")
                    continue
                print(f"{unit}: active as pid {st.get('MainPID') or '?'} but THIS "
                      f"invocation has emitted no ARTIFACT level line yet (it is "
                      f"emitted every {period}s, per the {source}) — vintage NOT "
                      f"MEASURED. No sweep starvation is visible in this invocation's "
                      f"journal, so this is NOT evidence the restart failed to take; "
                      f"wait for the next level line.\n")
            else:
                print(f"{unit}: no ARTIFACT level line in the journal window — "
                      f"vintage NOT MEASURED (not 'current')\n")
            continue
        if not bound:
            print(f"{unit}: WARNING — systemd gave no InvocationID, so the line below "
                  f"is unit-wide and may belong to a previous invocation.")
        state, reason = classify(art["startup"], art["disk"])
        got = versions.get(art["startup"])
        where = (f"{got[0]}  {got[1]}  {got[2][:58]}" if got
                 else "matches NO commit — an uncommitted working-tree state")
        print(f"{unit}  [{state}: {reason}]")
        print(f"    in force: {where}")
        if state == "drift":
            since = _run(["git", "-C", repo, "log", "--oneline",
                          f"{got[0]}..origin/main", "--", WATCH_PATH]) if got else ""
            n = len([x for x in since.splitlines() if x.strip()])
            print(f"    {n} commit(s) to this file merged to main since — NOT in force:")
            for line in since.splitlines():
                print(f"      {line}")
        print()


def cmd_fd(pid, path):
    disk = open(path, "rb").read()
    fd = f"/proc/{pid}/fd/255"
    st = os.stat(fd)                       # follows to the held inode
    readback = open(fd, "rb").read()
    verdict, why = fd_witnesses(st.st_size, sha256_bytes(readback),
                                len(disk), sha256_bytes(disk))
    print(f"pid {pid} fd 255 -> {path}")
    print(f"  stat -L size : {st.st_size}   (on disk: {len(disk)})")
    print(f"  cat readback : {sha256_bytes(readback)[:16]}   "
          f"(on disk: {sha256_bytes(disk)[:16]})")
    print(f"  VERDICT: {verdict} — {why}")


def main(argv):
    repo = os.environ.get("HESTIA_REPO") or os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))
    if len(argv) >= 2 and argv[1] == "units":
        cmd_units(repo)
        return 0
    if len(argv) >= 4 and argv[1] == "fd":
        cmd_fd(argv[2], argv[3])
        return 0
    print(__doc__.strip().splitlines()[0], file=sys.stderr)
    print("usage: process_vintage.py units | fd <pid> <path>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
