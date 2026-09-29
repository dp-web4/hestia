#!/usr/bin/env python3
"""How long does `main` stay red, and whose commit added each failure?

#124 (2026-07-30) established that `main` had no merge gate and closed by enabling
branch protection: three required checks, `enforce_admins: false`, reviews not
required (they would deadlock a single-account org). The door was deliberate --
"a *visible* door rather than ... no wall".

This tool measures what came through it. It reads the `ci` workflow's own run
history for `main` and answers three questions the GitHub UI cannot:

  census    Where were the RED SPELLS -- maximal runs of consecutive failing
            commits on main -- how long did each last, how many commits landed
            *into* an already-red main, and at which commit did the failing
            TEST-FILE set grow? A spell's later breaks are the expensive ones:
            the job name was already red, so nobody could see a second cause
            arrive under the first.

  baseline  Which test files are failing on main RIGHT NOW. This is the number a
            seat needs before debugging its own PR.

  mine      Given a PR, split its failures into `inherited` (also failing on
            main), `yours` (only on the PR) and `you_fixed` (failing on main,
            green on the PR). A red PR check is not evidence of a red PR.

Why an instrument and not a note: the cost of a red baseline is not the red
itself, it is that every later author reads a red job as somebody else's. That
is unfalsifiable by eye and trivial to compute -- the plugin-tests job prints
`FAILED k of n: <files>`, so the failing set is in the log of every run.

Offline/tested path: every function that does arithmetic takes plain data. Only
`gh_*` touches the network, and the test file never calls it.

Usage:
    tools/ci_red_spell_census.py census [--pages N] [--json]
    tools/ci_red_spell_census.py baseline
    tools/ci_red_spell_census.py mine <pr-number>
"""
import datetime as dt
import json
import re
import subprocess
import sys

REPO = "dp-web4/hestia"
CI_WORKFLOW = "ci.yml"
# The plugin-tests job's own summary line. `tools/ci_discovery.py` decides which
# files run, so this list is whatever CI discovered that day -- not a constant.
FAILED_RE = re.compile(r"FAILED (\d+) of (\d+): (.+)$")


# ---------------------------------------------------------------- pure functions

def red_spells(runs):
    """Maximal runs of consecutive `failure` commits, oldest first.

    `runs` is [{"created_at", "sha", "conclusion"}], one entry per main commit,
    already deduplicated (latest attempt wins) and sorted ascending.

    A spell is closed by the first non-failure that follows it -- `cancelled` and
    a still-running `None` close it too, deliberately: neither is evidence that
    main is red, and treating "unknown" as red would manufacture spells out of
    infrastructure noise. The last spell may be open (`repaired_by: None`).
    """
    spells, cur = [], []
    for r in runs:
        if r.get("conclusion") == "failure":
            cur.append(r)
        elif cur:
            spells.append(_spell(cur, r))
            cur = []
    if cur:
        spells.append(_spell(cur, None))
    return spells


def _spell(commits, repair):
    return {
        "breaker": commits[0]["sha"],
        "started_at": commits[0]["created_at"],
        "commits": [c["sha"] for c in commits],
        "landed_into_red": len(commits) - 1,
        "repaired_by": repair["sha"] if repair else None,
        "repaired_at": repair["created_at"] if repair else None,
        "hours": _hours(commits[0]["created_at"],
                        repair["created_at"] if repair else None),
    }


def _hours(start, end):
    if not end:
        return None
    p = lambda t: dt.datetime.fromisoformat(t.replace("Z", "+00:00"))
    return round((p(end) - p(start)).total_seconds() / 3600, 1)


def parse_failed_files(log_text):
    """The failing test files named by a job log, or [] if the line is absent.

    The log contains the line twice -- once as the echoed shell source of the
    workflow step, once as its output. Only the second carries filenames after
    the colon, and the echoed copy still contains `${#failed[@]}`, so a `$` in
    the count field is the discriminator. Reading the first copy as data is how
    an earlier hand-rolled version of this reported `FAILED ${#failed[@]}` as a
    test file name.
    """
    out = []
    for line in log_text.splitlines():
        m = FAILED_RE.search(line.rstrip())
        if not m or "$" in m.group(1):
            continue
        out = sorted(set(m.group(3).split()))
    return out


def growth(series):
    """Where a failing set GREW, walking a spell in order.

    `series` is [(sha, [files])]. Returns one row per commit that added or
    dropped a file, naming what changed. A commit that adds a file while main is
    already red is a break that no reviewer could distinguish from the baseline:
    the job name in the UI does not change.
    """
    rows, prev = [], None
    for sha, files in series:
        cur = set(files)
        if prev is not None:
            added, fixed = sorted(cur - prev), sorted(prev - cur)
            if added or fixed:
                rows.append({"sha": sha, "added": added, "fixed": fixed})
        prev = cur
    return rows


def attribute(pr_files, main_files):
    """Split a PR's failures against main's baseline.

    `you_fixed` matters as much as `yours`: a PR that repairs one of main's
    failures while adding none of its own still shows a red check, and that is
    the case most likely to be read as "my PR is broken".
    """
    pr, base = set(pr_files), set(main_files)
    return {
        "yours": sorted(pr - base),
        "inherited": sorted(pr & base),
        "you_fixed": sorted(base - pr),
    }


def verdict(att):
    """One line a seat can act on."""
    if att["yours"]:
        return "YOURS: " + " ".join(att["yours"]) + (
            "  (inherited: %s)" % " ".join(att["inherited"]) if att["inherited"] else "")
    if att["inherited"]:
        return ("INHERITED -- every failure on this PR is already failing on main: "
                + " ".join(att["inherited"]))
    return "CLEAN against main's baseline"


# ------------------------------------------------------------------- network I/O

def gh_json(path, *params):
    argv = ["gh", "api", "-X", "GET", path]
    for p in params:
        argv += ["-f", p]
    out = subprocess.run(argv, capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit("gh api %s failed: %s" % (path, out.stderr.strip()[:400]))
    return json.loads(out.stdout)


def gh_main_runs(pages=6):
    """One row per main commit that has a `ci` run, oldest first, latest attempt."""
    latest = {}
    for page in range(1, pages + 1):
        d = gh_json("repos/%s/actions/workflows/%s/runs" % (REPO, CI_WORKFLOW),
                    "branch=main", "per_page=100", "page=%d" % page)
        runs = d.get("workflow_runs", [])
        for r in runs:
            sha = r["head_sha"][:8]
            prev = latest.get(sha)
            if not prev or r["created_at"] > prev["created_at"]:
                latest[sha] = {"sha": sha, "created_at": r["created_at"],
                               "conclusion": r["conclusion"], "run_id": r["id"]}
        if len(runs) < 100:
            break
    return sorted(latest.values(), key=lambda r: r["created_at"])


def gh_failed_files(run_id):
    out = subprocess.run(["gh", "run", "view", str(run_id), "--log-failed"],
                         capture_output=True, text=True)
    return parse_failed_files(out.stdout)


def gh_pr_head_run(pr):
    d = gh_json("repos/%s/pulls/%s" % (REPO, pr))
    sha = d["head"]["sha"]
    runs = gh_json("repos/%s/actions/workflows/%s/runs" % (REPO, CI_WORKFLOW),
                   "head_sha=%s" % sha, "per_page=20").get("workflow_runs", [])
    if not runs:
        raise SystemExit("no ci run for PR %s head %s" % (pr, sha[:8]))
    return sha, max(runs, key=lambda r: r["created_at"])


# ------------------------------------------------------------------------- modes

def mode_census(pages, as_json):
    runs = gh_main_runs(pages)
    spells = red_spells(runs)
    red = sum(len(s["commits"]) for s in spells)
    for s in spells:
        series = []
        for sha in s["commits"]:
            run = next(r for r in runs if r["sha"] == sha)
            series.append((sha, gh_failed_files(run["run_id"])))
        s["failing_at_breaker"] = series[0][1]
        s["growth"] = growth(series)
    if as_json:
        print(json.dumps({"commits": len(runs), "red": red, "spells": spells}, indent=1))
        return 0
    print("main commits with a ci run: %d  (%s .. %s)"
          % (len(runs), runs[0]["created_at"][:10], runs[-1]["created_at"][:10]))
    print("red: %d (%.1f%%) in %d spell(s); %d commit(s) landed INTO an already-red main"
          % (red, red / len(runs) * 100, len(spells),
             sum(s["landed_into_red"] for s in spells)))
    for s in spells:
        print("\n%s  %s  %d commit(s), %s h, repaired by %s"
              % (s["started_at"], s["breaker"], len(s["commits"]),
                 s["hours"] if s["hours"] is not None else "OPEN",
                 s["repaired_by"] or "-- still red"))
        print("    broke: %s" % (" ".join(s["failing_at_breaker"]) or "(job-level only)"))
        for g in s["growth"]:
            bits = []
            if g["added"]:
                bits.append("+%s" % " ".join(g["added"]))
            if g["fixed"]:
                bits.append("-%s" % " ".join(g["fixed"]))
            print("    %s  %s   <-- under cover of the existing red"
                  % (g["sha"], "  ".join(bits)))
    return 0


def failing_files_of(run):
    """(files, state) for a run. An unfinished run has NO baseline -- saying "none
    failing" about a run that has not reported is the absence-read-as-pass failure
    this repo keeps paying for, so the state is returned and the caller must print
    it."""
    if run["conclusion"] == "failure":
        return gh_failed_files(run["run_id"]), "failure"
    if run["conclusion"] in (None, "in_progress", "queued"):
        return [], "unknown"
    return [], run["conclusion"]


def mode_baseline():
    runs = gh_main_runs(1)
    last = runs[-1]
    files, state = failing_files_of(last)
    if state == "unknown":
        print("main %s: ci has not reported yet -- NO baseline, not a green one"
              % last["sha"])
        return 0
    print("main %s (%s): %s" % (last["sha"], state,
                                " ".join(files) or "no failing test files"))
    return 0


def mode_mine(pr):
    runs = gh_main_runs(1)
    main_run = runs[-1]
    main_files, main_state = failing_files_of(main_run)
    sha, pr_run = gh_pr_head_run(pr)
    pr_files, pr_state = failing_files_of({"conclusion": pr_run["conclusion"],
                                           "run_id": pr_run["id"]})
    print("main     %s %-11s %s" % (main_run["sha"], main_state,
                                    " ".join(main_files) or "-"))
    print("PR %-5s %s %-11s %s" % (pr, sha[:8], pr_state,
                                   " ".join(pr_files) or "-"))
    if "unknown" in (main_state, pr_state):
        print("NO VERDICT: %s has not reported. Re-run when it has -- an unreported "
              "run is not a green one." % ("main" if main_state == "unknown" else "the PR"))
        return 0
    print(verdict(attribute(pr_files, main_files)))
    return 0


def main(argv):
    mode = argv[1] if len(argv) > 1 else "census"
    if mode == "census":
        pages = int(argv[argv.index("--pages") + 1]) if "--pages" in argv else 6
        return mode_census(pages, "--json" in argv)
    if mode == "baseline":
        return mode_baseline()
    if mode == "mine":
        if len(argv) < 3:
            raise SystemExit("usage: ci_red_spell_census.py mine <pr-number>")
        return mode_mine(argv[2])
    raise SystemExit(__doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
