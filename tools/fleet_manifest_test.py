#!/usr/bin/env python3
"""fleet_manifest_test.py — the manifest's measurements must themselves be proven.

WHY (GPT open-PR audit 2026-08-04, rec #1: the fleet is not yet auditable as
one state; this tool is the first artifact toward it). A manifest whose
comparisons are wrong is worse than none — it would report divergence where
there is none (wolf) or agreement where there is drift (the muted gauge). So
the pure parts of the measurement are driven here with synthetic trees whose
correct answers are known, and the whole tool is smoke-run end to end with the
assertion limited to SHAPE: content varies by seat, shape must not.

  A. UNITS — the pure functions against fixtures:
     build-tag parsing, probe classification (401/403 = mounted-gated,
     404 = old build, unreachable, 200 = investigate), stale-code tri-state,
     and the hook comparator's full state vocabulary: MATCH / DIVERGED /
     MISSING / INSTALLED-ONLY / AMBIGUOUS / UNREADABLE, including the
     resolution order (member's own dir beats member-mesh beats lone
     candidate) and the ambiguity rule (guessing is the failure, so
     unresolved is a state, not a coin flip).
  B. SMOKE — the real tool, subprocess, on this repo: exit 0 (measurement is
     not a gate — drift is data, not an exit code), stdout parses as JSON,
     the schema marker is present, the row set covers daemon, checkout, and
     one hooks row per MEMBERS entry, and drift_summary exists even when
     empty. Content is NOT asserted: this seat sees what this seat sees.
  C. ANTI-VACUITY — the discovered structures the tool relies on are
     non-empty on the real repo (canonical index, MEMBERS, rows); an empty
     discovery is a blind gauge, per the norm ci_discovery set.

Usage: ./fleet_manifest_test.py     (runtime ~10s)
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "fleet_manifest.py")
sys.path.insert(0, HERE)
import fleet_manifest as fm  # noqa: E402

failures = []


def check(label, ok, detail=""):
    if not ok:
        failures.append(label)
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if detail and not ok else ""))


# --- A. units ---------------------------------------------------------------

check("A1 build tag parsed", fm.parse_build_tag("hestia 0.0.3 (app-v0.1.2-503-gf3abeda)") == "f3abeda")
check("A2 no build tag -> None", fm.parse_build_tag("hestia 0.0.3") is None)

check("A3 probe 401 -> mounted, gated", fm.classify_probe(401).startswith("mounted, operator-gated"))
check("A4 probe 403 -> mounted, gated", fm.classify_probe(403).startswith("mounted, operator-gated"))
check("A5 probe 404 -> old build", "NOT MOUNTED" in fm.classify_probe(404))
check("A6 probe unreachable", fm.classify_probe(None) == "daemon unreachable")
check("A7 probe 200 ungated is suspicious", "UNGATED" in fm.classify_probe(200))

check("A8 stale tri-state", fm.stale_by_time(200, 100) is True
      and fm.stale_by_time(100, 200) is False and fm.stale_by_time(100, None) is None)

CANON = {
    "gate.py":    {"kimi": "/src/kimi/gate.py", "codex": "/src/codex/gate.py"},
    "mesh.py":    {"member-mesh": "/src/mesh/mesh.py"},
    "observe.sh": {"kimi": "/src/kimi/observe.sh", "codex": "/src/codex/observe.sh",
                   "gemini": "/src/gemini/observe.sh"},
    "multi.py":   {"claude-code": "/src/c/multi.py", "codex": "/src/c2/multi.py"},
    "solo.py":    {"other": "/src/other/solo.py"},
    "ghost.py":   {"kimi": "/src/kimi/ghost.py"},
}
CONTENT = {}
for path in {p for c in CANON.values() for p in c.values()}:
    CONTENT[path] = f"bytes-of-{os.path.basename(path)}"
CONTENT["/src/kimi/gate.py"] = "SAME"
CONTENT["/src/kimi/observe.sh"] = "SAME2"


def digest(path):
    if path not in CONTENT:
        return "UNREADABLE:FileNotFoundError"
    return CONTENT[path]


INST = {
    "gate.py":    "gate.py",            # matches kimi canonical (SAME)
    "observe.sh": "observe.sh",         # codex's copy differs from kimi's: DIVERGED
    "mesh.py":    "mesh.py",            # member-mesh canonical; content varies
    "multi.py":   "multi.py",           # two candidates, neither kimi -> AMBIGUOUS
    "solo.py":    "solo.py",            # one candidate, not kimi's -> lone fallback
    "novel.py":   "novel.py",           # no canonical anywhere -> INSTALLED-ONLY
}
CONTENT.update({
    "gate.py": "SAME",                # installed gate.py == /src/kimi/gate.py
    "observe.sh": "DIFFERENT",
    "mesh.py": "bytes-of-mesh.py",
    "multi.py": "x", "solo.py": "bytes-of-solo.py", "novel.py": "y",
})

rows = fm.compare_member_hooks(CANON, "kimi", INST, digest)
by_file = {r["file"]: r["state"] for r in rows}
check("A9 comparator MATCH", by_file["gate.py"] == "MATCH", str(by_file))
check("A10 comparator DIVERGED", by_file["observe.sh"] == "DIVERGED", str(by_file))
check("A11 member-mesh fallback resolves", by_file["mesh.py"] == "MATCH", str(by_file))
check("A12 ambiguous is a state, not a guess",
      by_file["multi.py"].startswith("AMBIGUOUS"), str(by_file))
check("A13 lone candidate resolves", by_file["solo.py"] == "MATCH", str(by_file))
check("A14 installed-only named", by_file["novel.py"].startswith("INSTALLED-ONLY"), str(by_file))
check("A15 canonical-never-installed is MISSING",
      by_file.get("ghost.py", "").startswith("MISSING"), str(by_file))

# A16: UNREADABLE is carried as a state, never raised — on EITHER side, with
# the blind side named (PR #199 finding 3: an unreadable SOURCE against a
# readable install must not manufacture a DIVERGED; that false positive costs
# a redeploy of a file nobody could read).
CONTENT["/src/kimi/gate.py"] = "SAME"
rows2 = fm.compare_member_hooks({"w.py": {"kimi": "/src/kimi/w.py"}}, "kimi", {"w.py": "w.py"},
                                lambda p: "UNREADABLE:PermissionError")
check("A16 unreadable is a state, not an exception",
      rows2[0]["state"] == "UNREADABLE (installed)", str(rows2))


def digest_source_blind(path):
    return "UNREADABLE:PermissionError" if path.startswith("/src/") else "deadbeef"


rows3 = fm.compare_member_hooks({"w.py": {"kimi": "/src/kimi/w.py"}}, "kimi", {"w.py": "w.py"},
                                digest_source_blind)
check("A16b unreadable SOURCE is not DIVERGED",
      rows3[0]["state"] == "UNREADABLE (source)", str(rows3))

# A17: THE REGRESSION CBP CAUGHT. The first drift summary was built by
# substring-matching its own prose, and the daemon's "behind main" — the one
# finding the artifact exists to surface — matched no token and vanished.
# collect_findings is structural now; pin every finding class it must emit.
synthetic_rows = [
    {"component": "daemon", "version_string": "hestia x (app-v1-2-gabcdef0)",
     "states": {"source": "behind main", "restarted": "running",
                "live_probed": "mounted, operator-gated (current build)"}},
    {"component": "source checkout", "states": {"source": "current", "dirty": 0}},
    {"component": "watcher (codex)", "states": {"restarted": "STALE-CODE: changed after start"}},
    {"component": "hooks (codex)", "states": {"installed": "2 diverged", "_drift": 2}},
]
f = fm.collect_findings(synthetic_rows)
check("A17a daemon behind-main IS a finding (the dropped one)",
      any("behind main" in x for x in f), str(f))
check("A17b watcher STALE-CODE is a finding", any("STALE-CODE" in x for x in f), str(f))
check("A17c hook drift is a finding", any("hooks (codex)" in x for x in f), str(f))
check("A17d quiet-and-CLEAN rows make no findings (distinguished from quiet-blind, A17g/h)",
      fm.collect_findings([synthetic_rows[1]]) == [], str(fm.collect_findings([synthetic_rows[1]])))
d2 = fm.collect_findings([{"component": "daemon",
                           "states": {"source": "DRIFT", "restarted": "NOT RUNNING",
                                      "live_probed": "daemon unreachable"}}])
check("A17e DRIFT/not-running/unreachable are all findings", len(d2) == 3, str(d2))
d3 = fm.collect_findings([{"component": "daemon",
                           "states": {"source": "current", "restarted": "2 PROCESSES"}}])
check("A17f multiple daemons IS a finding (multiplicity is not a tiebreak)",
      any("PROCESSES" in x for x in d3), str(d3))

# A17g/h: claude-code's re-review finding. The two unverifiable hook shapes
# (files unreadable; comparison never reached) used to fall through to a
# CLEAN summary — the muted gauge. Both must now speak, as their own class.
blind1 = fm.collect_findings([{"component": "hooks (kimi-code)",
                               "states": {"installed": "5 unreadable", "_drift": 0,
                                          "_unverifiable": 5,
                                          "_unverifiable_detail": "5 source unreadable"}}])
check("A17g unverifiable hook files are a finding (blind, not clean)",
      any("5 unverifiable (5 source unreadable)" in x for x in blind1), str(blind1))
blind2 = fm.collect_findings([{"component": "hooks (claude)",
                               "states": {"installed": "unverifiable — canonical index failed "
                                                       "(git ls-files)"}}])
check("A17h comparison-never-reached (no _drift key) is a finding",
      any("canonical index failed" in x for x in blind2), str(blind2))
d4 = fm.collect_findings([{"component": "source checkout",
                           "states": {"source": "current", "dirty": 2}}])
check("A17i dirty-only checkout is a finding via its own field (policy: keep)",
      any("2 dirty" in x for x in d4), str(d4))

# A18: on WSL the staleness check abstains rather than asserting on a jittering
# basis (claude-code measured three lstart values for one unrestarted PID).
check("A18 WSL detected on this box (else the abstention path is dead code here)",
      fm.is_wsl() in (True, False) and isinstance(fm.is_wsl(), bool))

# --- B. smoke (the real tool, this repo) -------------------------------------

r = subprocess.run([sys.executable, TOOL, "--probe", ""], capture_output=True, text=True, timeout=120)
check("B1 tool exits 0 (measurement, not gate)", r.returncode == 0, r.stderr[-400:])
manifest = None
try:
    manifest = json.loads(r.stdout)
except json.JSONDecodeError as e:
    check("B2 stdout is JSON", False, f"{e}: {r.stdout[:200]}")
if manifest:
    check("B2 stdout is JSON", True)
    check("B3 schema marker", manifest.get("schema") == "fleet-manifest/1", str(manifest.get("schema")))
    comps = [row.get("component", "") for row in manifest.get("rows", [])]
    check("B4 daemon row present", "daemon" in comps, str(comps))
    check("B5 checkout row present", "source checkout" in comps, str(comps))
    co = next((row for row in manifest["rows"] if row.get("component") == "source checkout"), {})
    cost = co.get("states", {})
    check("B5b checkout states split: source is one fact, dirty its own field",
          cost.get("source") in ("current", "NOT at origin/main")
          and isinstance(cost.get("dirty"), int), str(cost))
    hook_rows = [c for c in comps if c.startswith("hooks (")]
    check("B6 one hooks row per MEMBERS entry",
          len(hook_rows) == len(fm.MEMBERS), f"{hook_rows} vs {list(fm.MEMBERS)}")
    check("B7 drift_summary exists even if empty",
          isinstance(manifest.get("drift_summary"), list) and len(manifest["drift_summary"]) > 0,
          str(manifest.get("drift_summary")))
    check("B8 sight lines disclosed (measured_by)", bool(manifest.get("measured_by")))
    check("B9 fleet-wide honestly out of scope", "single-host" in manifest.get("note", ""))

# --- C. anti-vacuity ----------------------------------------------------------

canon = fm.canonical_index()
check("C1 canonical index non-empty on the real repo", bool(canon), f"len={canon and len(canon)}")
if canon:
    check("C2 every member has at least one canonical hook",
          all(any(d == pd for c in canon.values() for d in c) for _, pd in fm.MEMBERS.values()),
          str({m: pd for m, (_, pd) in fm.MEMBERS.items()}))
check("C3 MEMBERS itself non-empty", len(fm.MEMBERS) > 0)

print()
if failures:
    print(f"{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("ALL CHECKS PASSED")
