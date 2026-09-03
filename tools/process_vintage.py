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
# PARSE BY KEY, NEVER BY ADJACENCY. The first version of this file matched the fields
# positionally — `startup_sha256=(\S+)\s+disk_sha256=` — and #637 had already inserted
# `startup_origin=` BETWEEN those two on 2026-08-29, three days before this file landed.
# Every line a current watcher emits therefore failed to match, and `cmd_units` reported
# the miss as "this invocation has emitted no ARTIFACT level line yet — wait for the next
# one". The line was already there, hourly, and no amount of waiting would ever parse it.
#
# It is the SAME defect this file already names one function down, in `unit_state`: a
# positional read of an extensible field list, where inserting a field silently shifts
# every later answer. The watcher's line is a k=v bag by construction, so read it as one:
# a new field is then additive, and a REMOVED required field is loud.
ARTIFACT_HEAD_RE = re.compile(r"ARTIFACT\s+plugin=\S+")
_KV_RE = re.compile(r"\b(?P<k>[a-z_][a-z0-9_]*)=(?P<v>\S+)")

# What the reader needs. Absence of any of these on an ARTIFACT line is a READER/EMITTER
# contract break, reported as such — never as "no line".
REQUIRED_ARTIFACT_KEYS = ("plugin", "state", "reason", "startup_sha256", "disk_sha256")

# Every key the emitter is known to write, required or not. `tools/process_vintage_test.py`
# pins this set against the echo in WATCH_PATH itself, so the next field insertion turns
# THIS repo's CI red at the commit that inserts it — rather than in a journal three days
# later that only a stale watcher can still satisfy.
KNOWN_ARTIFACT_KEYS = REQUIRED_ARTIFACT_KEYS + ("startup_origin", "started")

WATCHER_UNITS = ("hestia-watch-claude", "hestia-watch-codex", "hestia-watch-kimi")
WATCH_PATH = "plugins/member-mesh/hestia-watch-member.sh"


def parse_artifact(line):
    """Pull the fields out of one ARTIFACT level line. None if it is not one at all.

    THREE outcomes, because two of them were previously one:

      * `None`                     — not an ARTIFACT level line. Say nothing about it.
      * dict, `missing` empty      — parsed. `startup`/`disk` are the pair `classify`
        wants.
      * dict, `missing` non-empty  — it IS an ARTIFACT line and the reader could not read
        it. That is a defect in this file or a change in the emitter, and it is NOT the
        same state as a line that was never emitted. Collapsing the two is what hid the
        #637 field insertion for the whole life of this tool.

    Returns the raw strings; validation is `classify`'s job, because "this field is not
    a sha" is a state the watcher reports deliberately (`unverifiable`) and collapsing
    it into a parse failure would hide it.
    """
    if not ARTIFACT_HEAD_RE.search(line or ""):
        return None
    kv = {m.group("k"): m.group("v") for m in _KV_RE.finditer(line)}
    out = dict(kv)
    out["missing"] = tuple(k for k in REQUIRED_ARTIFACT_KEYS if k not in kv)
    out["unknown"] = tuple(sorted(k for k in kv if k not in KNOWN_ARTIFACT_KEYS))
    # Short aliases the rest of the file reads. Present as None when absent, so a caller
    # that ignores `missing` crashes visibly rather than getting a plausible answer.
    out["startup"] = kv.get("startup_sha256")
    out["disk"] = kv.get("disk_sha256")
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
        return _run(["journalctl", "--user",
                     f"_SYSTEMD_INVOCATION_ID={invocation_id}", "--no-pager"]), True
    return _run(["journalctl", "--user", "-u", unit, "--no-pager"]), False


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
        unreadable = None
        for line in log.splitlines():
            parsed = parse_artifact(line)
            if not parsed:
                continue
            if parsed["missing"]:
                # An ARTIFACT line this reader cannot read. Keep it: it is the evidence
                # that the emitter and this file have diverged, and it must NOT be
                # reported as an absent line.
                unreadable = (parsed, line)
                continue
            art = parsed           # keep the LAST readable one — the level line, hourly
        if not art and unreadable:
            parsed, line = unreadable
            print(f"{unit}: READER DEFECT — vintage NOT MEASURED. {len(log.splitlines())} "
                  f"journal line(s) include an ARTIFACT level line that this tool cannot "
                  f"parse: required key(s) {', '.join(parsed['missing'])} absent"
                  + (f"; unrecognised key(s) present: {', '.join(parsed['unknown'])}"
                     if parsed["unknown"] else "") + ".")
            print(f"    Waiting will NOT fix this — the line is already here and every "
                  f"future one will have the same shape. Fix the reader "
                  f"(REQUIRED_ARTIFACT_KEYS / KNOWN_ARTIFACT_KEYS in this file) or the "
                  f"emitter ({WATCH_PATH}).")
            print(f"    offending line: {line.strip()[:300]}\n")
            continue
        if not art:
            if bound:
                print(f"{unit}: active as pid {st.get('MainPID') or '?'} but THIS "
                      f"invocation has emitted no ARTIFACT level line yet (it is "
                      f"hourly) — vintage NOT MEASURED. This is NOT evidence the "
                      f"restart failed to take; wait for the next level line.\n")
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
        # #637 added this: a baseline read from the process's OWN fd is first-hand; one
        # received by handover is hearsay about a hash. Report which, or say it is absent
        # — a pre-#637 watcher emits no such field, and that itself dates the watcher.
        origin = art.get("startup_origin")
        print(f"    baseline: {origin}" if origin else
              "    baseline: no startup_origin field — this watcher predates #637")
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
