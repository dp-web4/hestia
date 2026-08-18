#!/usr/bin/env python3
"""fleet_manifest.py — one artifact saying what is actually running, and where it drifts.

WHY THIS EXISTS (GPT open-PR audit, 2026-08-04, P0 + recommended sequence #1:
"`main` is auditable; the fleet is not yet auditable as one state"). Reviewed
source, installed copy, running process, and authority state are different
surfaces, and this fleet has been bitten by every seam between them: a merged
fix whose enforcing copy was never redeployed, a watcher running code edited
after it started, a daemon whose build tag nobody mapped back to a commit.
The audit's missing artifact is a per-host record that makes those seams
measurable instead of forensic.

WHAT IT MEASURES (per host, per component):

  daemon       binary path + sha256 + build tag (mapped back to a repo commit),
               process start + RSS, and a LIVE PROBE: does the governance
               ledger route answer mounted-but-gated (401/403 — the new build)
               or missing (404 — an old one) or nothing (down)?
  checkout     the shared source checkout this tool runs from: revision,
               == origin/main?, dirty files.
  watchers     every watch-member.sh process: script digest, and STALE-CODE —
               the script's mtime is after the process started, so the watcher
               is running code that no longer exists on disk.
  hooks        per member, each installed hook file vs its canonical source in
               plugins/<member>/hooks/: MATCH / DIVERGED / MISSING /
               INSTALLED-ONLY / UNREADABLE. Unreadable is a first-class answer,
               not a failure: which seat measured is part of the evidence
               (a member reading another member's home SHOULD be refused, and
               the manifest must show its own sight lines).

STATES (claude-code's fleet vocabulary, forum 2026-08-04/05 — the five rungs a
fix climbs): source fixed / installed / restarted / live-probed / fleet-wide.
Every row reports its rungs; "fleet-wide" is out of scope for a single-host
manifest and says so, because pretending one host is the fleet is the failure
this file exists against.

RULES IT LIVES BY:
  * stdlib only; no network beyond the local daemon probe; read-only.
  * measurement, not a gate: exit 0 always. Drift is data, not an exit code.
  * nothing it cannot verify is asserted. Unknown is a value.
  * privacy: no hostnames, no usernames beyond $HOME-relative paths (presence
    over privacy — substance, not topology). measured_by is the mesh plugin id
    or "unknown", never $USER: a file that makes a point of this rule does not
    get to break it.

Usage:
  python3 tools/fleet_manifest.py [--out PATH] [--probe URL] [--member-dir NAME=PATH ...]

  --out        also write the JSON manifest here (else stdout only)
  --probe      daemon base URL (default http://127.0.0.1:7711; empty disables)
  --member-dir member hook install dir override, e.g. codex=/home/x/.codex/hooks
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import urllib.error

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
HOME = os.path.expanduser("~")
NOW = time.time()

MEMBERS = {  # member -> (installed hooks dir under $HOME, plugins/ dir name)
    "kimi-code":   (".kimi-code/hooks", "kimi"),
    "claude-code": (".claude/hooks",    "claude-code"),
    "codex":       (".codex/hooks",     "codex"),
    "gemini":      (".gemini/hooks",    "gemini"),
}
WATCH_GLOB = "plugins/member-mesh/hestia-watch-member.sh"
FIRE_GLOB_PREFIX = "plugins/member-mesh/fire-"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_or(path):
    """Digest, or a state string. UNREADABLE is an answer, not an exception."""
    try:
        return sha256(path)
    except (OSError, PermissionError) as e:
        return f"UNREADABLE:{type(e).__name__}"


def parse_build_tag(version_string):
    """`hestia 0.0.3 (app-v0.1.2-503-gf3abeda)` -> `f3abeda`, else None."""
    m = re.search(r"-g([0-9a-f]{7,})\)?$", version_string or "")
    return m.group(1) if m else None


def classify_probe(code_or_none):
    """HTTP status (or None for unreachable) -> the live_probed state string."""
    if code_or_none is None:
        return "daemon unreachable"
    if code_or_none in (401, 403):
        return "mounted, operator-gated (current build)"
    if code_or_none == 404:
        return "NOT MOUNTED — running build predates the ledger"
    if code_or_none == 200:
        return "mounted, UNGATED — investigate"
    return f"HTTP {code_or_none}"


def stale_by_time(mtime, started_epoch):
    """Tri-state: True = script changed after process start (STALE-CODE),
    False = current, None = unverifiable."""
    if started_epoch is None:
        return None
    return mtime > started_epoch


def compare_member_hooks(canon, plugin_dir, inst, digest):
    """Pure comparison of one member's installed hooks against the canonical
    index. `canon`: basename -> {plugin_dir: path}; `inst`: basename -> rel
    installed path; `digest`: path -> digest-or-state-string. Returns the
    per-file rows. Kept pure so the test drives it with synthetic trees."""
    files = []
    seen_sources = set()
    for base in sorted(inst):
        rel_installed = inst[base]
        candidates = canon.get(base, {})
        src = candidates.get(plugin_dir) or candidates.get(SHARED_DIR)
        if src is None and len(candidates) == 1:
            src = next(iter(candidates.values()))
        if src is None:
            state = ("AMBIGUOUS (multiple canonical sources)" if candidates
                     else "INSTALLED-ONLY (no canonical source in this repo)")
            files.append({"file": rel_installed, "state": state})
            continue
        seen_sources.add(src)
        sd, idd = digest(src), digest(rel_installed)
        # UNREADABLE first, on BOTH sides: two failing reads compare EQUAL, and
        # equality must never manufacture a MATCH out of two refusals — and an
        # unreadable SOURCE against a readable install must not manufacture a
        # DIVERGED either (PR #199 review finding 3: that false positive costs
        # a redeploy of a file nobody could read). Same guard, both directions,
        # and the state names which side is blind.
        state = ("UNREADABLE (installed)" if str(idd).startswith("UNREADABLE") else
                 "UNREADABLE (source)" if str(sd).startswith("UNREADABLE") else
                 "MATCH" if sd == idd else "DIVERGED")
        files.append({"file": rel_installed, "state": state})
    for base, candidates in sorted(canon.items()):
        if plugin_dir not in candidates:
            continue
        if candidates[plugin_dir] not in seen_sources and base not in inst:
            files.append({"file": base, "state": "MISSING (in source, not installed)"})
    return files


def git(*args):
    r = subprocess.run(["git", "-C", REPO, *args], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def is_wsl():
    """WSL reports a Microsoft kernel; there, process start time (ps lstart and
    /proc/<pid> btime alike) jitters across reads of an UNRESTARTED process
    (measured by claude-code, PR #199 review: three different lstart values for
    the same PIDs across three runs). A staleness check built on that basis
    asserts what the platform cannot support — so on WSL the check must say
    unverifiable, not guess."""
    try:
        with open("/proc/sys/kernel/osrelease") as fh:
            return "microsoft" in fh.read().lower() or "wsl" in fh.read().lower()
    except OSError:
        return False


def collect_findings(rows):
    """The drift summary, built from the rows' STRUCTURE — never by
    substring-matching their prose.

    The first version token-matched display strings, and silently dropped the
    daemon's "behind main" finding because that phrase matched no token (the
    one finding the whole artifact existed to surface, invisible in its own
    summary — claude-code's blocking review, PR #199). Findings are stated
    here, per component, in one place, deliberately.
    """
    findings = []
    for r in rows:
        comp = r.get("component", "?")
        st = r.get("states", {})
        if comp == "daemon":
            src = st.get("source", "")
            if src in ("behind main", "DRIFT"):
                findings.append(f"daemon: build is {src} (running {r.get('version_string', '?')})")
            if st.get("restarted") == "NOT RUNNING":
                findings.append("daemon: NOT RUNNING")
            rst = st.get("restarted", "")
            if rst.endswith("PROCESSES"):
                findings.append(f"daemon: {rst} — expected exactly one")
            lp = st.get("live_probed", "")
            if lp.startswith("NOT MOUNTED") or lp == "daemon unreachable" or "UNGATED" in lp:
                findings.append(f"daemon: probe = {lp}")
        elif comp == "source checkout":
            if st.get("source", "") != "current":
                findings.append(f"source checkout: {st.get('source')}")
            # Dirty-at-main is a finding on this fleet BY POLICY (claude-code
            # ruling, PR #199): watchers run from the shared checkout, so
            # uncommitted WIP there is exactly "what is running is not what
            # is in main". It is its own field so the policy is one line,
            # stated — not an equality test on a composite prose string.
            if st.get("dirty"):
                findings.append(f"source checkout: {st['dirty']} dirty "
                                f"(running checkout diverges from main)")
        elif comp.startswith("watcher ("):
            rst = st.get("restarted", "")
            if rst.startswith("STALE-CODE") or rst == "script not found":
                findings.append(f"{comp}: {rst}")
        elif comp.startswith("hooks ("):
            n = st.get("_drift")
            if n is None:
                # The row never reached per-file comparison (canonical index
                # failed, or the install dir was unreadable from this seat).
                # That is BLIND, not clean — the row IS the finding, and it
                # must not fall through to silence (claude-code re-review,
                # PR #199: an empty drift_summary reads as "nothing is
                # wrong", never as "I could not look").
                findings.append(f"{comp}: {st.get('installed')}")
            else:
                if n:
                    findings.append(f"{comp}: {st.get('installed')}")
                u = st.get("_unverifiable", 0)
                if u:
                    findings.append(f"{comp}: {u} unverifiable "
                                    f"({st.get('_unverifiable_detail', 'unreadable')})")
    return findings


def daemon_facts(probe_base):
    row = {"component": "daemon", "states": {}}
    # Resolve the binary from the RUNNING PROCESS first, then PATH, then the
    # historical default. This tool's thesis is "what is actually running", and a
    # hardcoded path breaks that on two counts: on any host whose daemon lives
    # elsewhere (macOS/Homebrew puts it at /opt/homebrew/bin) the sha/version/
    # build_commit either read MISSING/UNKNOWN or — worse — describe a DIFFERENT
    # file than the live process, confidently. Fallback-safe: if the process scan
    # yields nothing, behaviour is exactly as before.
    exe = None
    try:
        _ps = subprocess.run(["ps", "-eo", "command"], capture_output=True, text=True).stdout
        for _l in _ps.splitlines():
            if "hestia serve" in _l and "grep" not in _l:
                _c = _l.strip().split()[0]
                if os.path.isabs(_c) and os.path.exists(_c):
                    exe = _c
                    break
    except (OSError, subprocess.SubprocessError):
        pass
    if not exe:
        exe = shutil.which("hestia")
    if not exe:
        exe = os.path.join(HOME, ".local", "bin", "hestia")
    row["binary"] = os.path.relpath(exe, HOME) if exe.startswith(HOME) else exe
    row["binary_sha256"] = sha256_or(exe) if os.path.exists(exe) else "MISSING"

    ver = ""
    try:
        ver = subprocess.run([exe, "--version"], capture_output=True, text=True,
                             timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    row["version_string"] = ver or "UNKNOWN"
    row["build_commit"] = parse_build_tag(ver)

    # Map the build tag back into the repo: does the claimed commit exist, and
    # is it an ancestor of main (current) or off it (drift)?
    main = git("rev-parse", "origin/main")
    row["main_commit"] = main[:12] if main else None
    if row["build_commit"] and main:
        contains = subprocess.run(
            ["git", "-C", REPO, "merge-base", "--is-ancestor", row["build_commit"], main])
        row["build_is_ancestor_of_main"] = contains.returncode == 0
        exact = main.startswith(row["build_commit"])
        tree_same = False
        if not exact and contains.returncode == 0:
            t1 = git("rev-parse", f"{row['build_commit']}^{{tree}}")
            t2 = git("rev-parse", f"{main}^{{tree}}")
            tree_same = bool(t1 and t1 == t2)
        row["states"]["source"] = ("current" if exact else
                                   "content-current (build == tree of main)" if tree_same else
                                   "behind main" if row["build_is_ancestor_of_main"] else "DRIFT")
    else:
        row["states"]["source"] = "unverifiable"

    # Process: start time, RSS, and whether it predates the latest source change.
    # POSIX "command", not procps-only "cmd": BSD/macOS ps REJECTS "cmd", writes
    # "ps: cmd: keyword not found" to stderr, emits a listing with no command
    # column, and still EXITS 0 — so nothing matches and the daemon reads
    # "NOT RUNNING" while the tool has actually failed to look. Fail-open.
    ps = subprocess.run(["ps", "-eo", "pid,lstart,rss,command"], capture_output=True, text=True).stdout
    # ALL of them, not first-match-wins: two daemons are exactly the surprise
    # this tool exists to catch, and first-match would report them as one
    # (PR #199 review, minor finding). Multiplicity is a finding, not a tiebreak.
    procs = [line.strip() for line in ps.splitlines()
             if "hestia serve" in line and "grep" not in line]
    row["processes"] = []
    for proc in procs:
        parts = proc.split(None, 7)
        row["processes"].append({"pid": parts[0], "started": " ".join(parts[1:6]),
                                 "rss_mb": round(int(parts[6]) / 1024)})
    if procs:
        row["states"]["restarted"] = "running" if len(procs) == 1 else f"{len(procs)} PROCESSES"
    else:
        row["states"]["restarted"] = "NOT RUNNING"

    # Live probe: is the governance ledger route MOUNTED? 401/403 = mounted and
    # gated (the new build); 404 = an old build; nothing = down. This is the
    # smallest behavioural proof that a reviewed change is live.
    if probe_base:
        url = probe_base.rstrip("/") + "/api/governance/ledger"
        try:
            urllib.request.urlopen(url, timeout=5)
            row["probe"] = {"url_route": "/api/governance/ledger", "result": "HTTP 200"}
            row["states"]["live_probed"] = classify_probe(200)
        except urllib.error.HTTPError as e:
            row["probe"] = {"url_route": "/api/governance/ledger", "result": f"HTTP {e.code}"}
            row["states"]["live_probed"] = classify_probe(e.code)
        except (urllib.error.URLError, OSError) as e:
            row["probe"] = {"url_route": "/api/governance/ledger", "result": f"unreachable: {type(e).__name__}"}
            row["states"]["live_probed"] = classify_probe(None)
    return row


def checkout_facts():
    row = {"component": "source checkout", "path": os.path.basename(REPO)}
    head = git("rev-parse", "HEAD")
    main = git("rev-parse", "origin/main")
    row["head"] = head[:12]
    row["origin_main"] = main[:12]
    row["detached"] = not git("symbolic-ref", "-q", "HEAD")
    dirty = git("status", "--porcelain")
    row["dirty_files"] = [l[3:] for l in dirty.splitlines() if l and not l.startswith("??")]
    row["untracked"] = sum(1 for l in dirty.splitlines() if l.startswith("??"))
    row["states"] = {"source": "current" if head == main else "NOT at origin/main",
                     "dirty": len(row["dirty_files"])}
    # at-origin/main? and dirty? are orthogonal facts and stay in their own
    # fields; joining them into one prose string makes every consumer an
    # equality test on composite text (the substring-match defect this tool
    # was rewritten to stop, one field over — claude-code re-review, PR #199).
    return row


def watcher_facts():
    rows = []
    # "command" not "cmd" — same BSD/macOS portability trap as the daemon row above.
    ps = subprocess.run(["ps", "-eo", "pid,lstart,command"], capture_output=True, text=True).stdout
    seen_procs = []
    for line in ps.splitlines():
        if "hestia-watch-member.sh" in line and "grep" not in line:
            seen_procs.append(line.strip())
    for proc in seen_procs:
        parts = proc.split(None, 7)
        started = " ".join(parts[1:6])
        toks = parts[-1].split()
        script = next((w for w in toks if w.endswith("hestia-watch-member.sh")), None)
        # The member is the token AFTER the script, however the watcher was
        # invoked. The first cut assumed the `bash <script> <member>` form and
        # indexed [1] — exec'd directly (shebang), that yields the watch-name
        # instead of the member (PR #199 review, minor finding).
        member = "?"
        if script is not None:
            i = toks.index(script)
            if i + 1 < len(toks):
                member = toks[i + 1]
        row = {"component": f"watcher ({member})", "pid": parts[0], "started": started}
        if script and os.path.exists(script):
            row["script"] = os.path.relpath(script, HOME) if script.startswith(HOME) else \
                            os.path.relpath(script, os.path.dirname(REPO))
            row["script_sha256"] = sha256_or(script)
            started_epoch = subprocess.run(
                ["stat", "-c", "%Y", f"/proc/{parts[0]}"], capture_output=True, text=True).stdout.strip()
            mtime = os.path.getmtime(script)
            try:
                started_epoch = float(started_epoch)
            except ValueError:
                started_epoch = None
            if is_wsl():
                # No reliable process-start basis exists here — see is_wsl().
                # The durable fix is watcher self-hashing at startup (record
                # sha256($0) when the watcher boots); until then, honesty.
                row["states"] = {"restarted": "unverifiable on WSL (btime jitter)"}
            else:
                stale = stale_by_time(mtime, started_epoch)
                row["states"]["restarted"] = ("STALE-CODE: script changed after watcher started"
                                              if stale else "current" if stale is False else "unverifiable")
        else:
            row["states"] = {"restarted": "script not found"}
        rows.append(row)
    # Fire templates: read at fire time, so current digest IS what the next fire runs.
    fires = sorted(f for f in os.listdir(os.path.join(REPO, "plugins/member-mesh"))
                   if re.fullmatch(r"fire-[a-z0-9-]+\.sh", f))
    for f in fires:
        p = os.path.join(REPO, "plugins/member-mesh", f)
        rows.append({"component": f"fire template ({f})", "script": f"plugins/member-mesh/{f}",
                     "script_sha256": sha256_or(p),
                     "states": {"installed": "in checkout (read at fire time)"}})
    return rows


def canonical_index():
    """basename -> canonical source path, built from `git ls-files` so a hook
    added tomorrow is indexed without editing this file. None when git fails:
    exit-0-always binds failure paths too, and an empty index is not an honest
    fallback — it would misreport every installed file as INSTALLED-ONLY
    (the first cut used check=True, so a git error RAISED and exited non-zero
    against the measurement-not-a-gate rule — PR #199 review, minor finding).

    Resolution order when a basename is ambiguous (codex's hydrate exists in
    the marketplace copy too): the member's own hooks dir wins, then the
    member-mesh shared dir. Anything still ambiguous is recorded AMBIGUOUS
    rather than guessed — a guessed comparison is the muted-gauge failure.
    Test files, caches, backups, and non-hook files (hooks.json et al.) are
    excluded: this compares enforcing artifacts, not their scaffolding.
    """
    r = subprocess.run(["git", "-C", REPO, "ls-files",
                        "plugins/*/hooks/*.py", "plugins/*/hooks/*.sh",
                        "plugins/member-mesh/hestia-mesh.py",
                        "plugins/member-mesh/session-mesh-inbox.sh"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None
    index = {}
    for rel in r.stdout.split():
        if any(t in rel for t in ("__pycache__", ".pytest_cache", "test_", ".bak", ".pre-")):
            continue
        base = os.path.basename(rel)
        member_dir = rel.split("/")[1] if rel.startswith("plugins/") else ""
        # The marketplace bundle is a SEPARATE artifact from the member's
        # canonical hooks, not another candidate for them (#151's comparator is
        # its judge). Keying it under the member's name would let the bundle's
        # copy win the canonical slot and report correct installs as diverged.
        if rel.startswith("plugins/codex/marketplace/"):
            member_dir = "codex(marketplace)"
        index.setdefault(base, {})[member_dir] = os.path.join(REPO, rel)
    return index


SHARED_DIR = "member-mesh"  # canonical home of cross-member mesh tools


def hook_facts(member_overrides):
    rows = []
    canon = canonical_index()
    for member, (home_rel, plugin_dir) in MEMBERS.items():
        inst_dir = member_overrides.get(member, os.path.join(HOME, home_rel))
        row = {"component": f"hooks ({member})",
               "installed_dir": home_rel if not member_overrides.get(member) else inst_dir,
               "files": [], "states": {}}
        if canon is None:
            row["states"]["installed"] = "unverifiable — canonical index failed (git ls-files)"
            rows.append(row)
            continue
        if not os.path.isdir(inst_dir):
            row["states"]["installed"] = "UNREADABLE or absent from this seat"
            rows.append(row)
            continue

        inst = {}  # basename -> installed rel path (install layouts vary: kimi
        # and codex are flat, claude nests by topic; the rel path is evidence,
        # the basename is the join key)
        for root, _dirs, files in os.walk(inst_dir):
            if "__pycache__" in root or ".pytest_cache" in root:
                continue
            for f in files:
                if f.endswith((".py", ".sh")) and not f.startswith("test_"):
                    inst[f] = os.path.relpath(os.path.join(root, f), inst_dir)

        def digest(path):
            if not os.path.isabs(path):
                path = os.path.join(inst_dir, path)
            return sha256_or(path)

        for f in compare_member_hooks(canon, plugin_dir, inst, digest):
            if "source" not in f:
                cand = canon.get(f["file"].split("/")[-1], {})
                src = cand.get(plugin_dir) or cand.get(SHARED_DIR)
                if src:
                    f["source"] = os.path.relpath(src, REPO)
            row["files"].append(f)

        n = {}
        unver_sides = {}
        for f in row["files"]:
            key = f["state"].split(" ")[0]
            n[key] = n.get(key, 0) + 1
            if key == "UNREADABLE":
                side = "source" if "(source)" in f["state"] else "installed"
                unver_sides[side] = unver_sides.get(side, 0) + 1
        row["states"]["installed"] = ", ".join(f"{v} {k.lower()}" for k, v in sorted(n.items())) \
            or "no hook files"
        row["states"]["_drift"] = n.get("DIVERGED", 0) + n.get("MISSING", 0)
        # Unverifiable is its own class beside _drift, never folded into it:
        # an unreadable file is a blind gauge, not a measured difference, and
        # drift_summary must say "I could not look" distinctly from "clean".
        row["states"]["_unverifiable"] = sum(unver_sides.values())
        row["states"]["_unverifiable_detail"] = " + ".join(
            f"{v} {k} unreadable" for k, v in sorted(unver_sides.items()))
        rows.append(row)
    return rows


def main():
    out_path = None
    probe = "http://127.0.0.1:7711"
    member_overrides = {}
    args = sys.argv[1:]
    while args:
        a = args.pop(0)
        if a == "--out":
            out_path = args.pop(0)
        elif a == "--probe":
            probe = args.pop(0)
        elif a == "--member-dir":
            kv = args.pop(0)
            member_overrides[kv.split("=", 1)[0]] = kv.split("=", 1)[1]

    rows = [daemon_facts(probe), checkout_facts()]
    rows += watcher_facts()
    rows += hook_facts(member_overrides)

    drift = collect_findings(rows)

    manifest = {
        "schema": "fleet-manifest/1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW)),
        "measured_by": os.environ.get("HESTIA_MESH_PLUGIN") or "unknown",
        "note": "single-host measurement. fleet-wide is out of scope for this artifact "
                "and pretending otherwise is the failure it exists against.",
        "states_vocabulary": ["source fixed", "installed", "restarted", "live-probed", "fleet-wide"],
        "rows": rows,
        "drift_summary": drift or ["no drift detected from this seat"],
    }

    text = json.dumps(manifest, indent=2)
    print(text)
    if out_path:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        with open(out_path, "w") as fh:
            fh.write(text + "\n")
        print(f"\nwrote {out_path}", file=sys.stderr)

    # Human summary on stderr: the digest, not the data.
    print(f"\n--- drift summary ({len(drift)} finding(s)) ---", file=sys.stderr)
    for d in drift or ["no drift detected from this seat"]:
        print(f"  {d}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
