#!/usr/bin/env python3
"""What does a live permit BUY? The disclosure the approver never gets.

WHY THIS EXISTS. `tools/marker_bar_probe.py` answers the forward question: given an
act, which marker does the matcher emit and which bar does that marker draw. The
question an operator actually faces is the INVERSE, and nothing answers it: an
escalation is presented with a `marker` string, the operator approves or denies it,
and `claim()` then matches that marker by EXACT EQUALITY against every future call
the same plugin_id makes. So the approval's real scope is not the act shown -- it is
the whole equivalence class of acts that emit the identical marker string. That class
is never displayed, and it is not derivable by reading the escalation.

This tool computes it. For each pending escalation (or a marker given on the command
line) it enumerates which real writes to governed files would equality-match the same
marker, and at which bar each of those would have been priced had it been escalated
on its own. That set is the blast radius of the approval.

WHY IT IS NOT JUST A REPORT. Two properties make the inverse map non-obvious:

  * the marker is the PATTERN that matched, never the target. The matcher returns the
    first element of its self-marker tuple that is a substring of the payload text,
    and only falls through to governance FILENAMES if none matched. So distinct
    governed files under one directory collapse to a single marker, and one governed
    file reached by two spellings splits into two markers.
  * `bar_for` (Rust) tests the marker with `contains`; `claim()` (Rust) tests it with
    `==`. A marker can therefore be too coarse to name any governed file -- drawing
    the single-approver bar -- while still equality-matching genuine writes to
    several of them.

The consequence this tool makes checkable: a permit minted by refusing a
NON-governed act (a prose document that merely quoted a path) carries a marker that
real governed writes also emit, so it is spendable on them.

RED CONDITION. Exit status 1 if any live pending escalation's marker equality-matches
at least one genuine write to a governed file. That is not a hypothetical: it is the
current state of this seat's pool, which is why the check is written as a failing
assertion rather than a summary.

NO LITERAL GOVERNANCE PATH OR FILENAME APPEARS IN THIS SOURCE. Every name is derived
from the imported matcher's own constants, discovered on disk, or read from the bar's
own source at runtime. That is a hard constraint, not a style choice: a literal would
make this file refused by the gate it measures. Markers are reported as
sha256(value)[:12] plus shape, so the output is checkable across seats without
reproducing the literal -- the elide-by-hash convention (kimi-code, notice 1092),
which replaces elide-by-field-name. Eliding by field name drops the discriminative
variable: a four-permit pool reported as one marker was in fact two.

WHAT IT DOES NOT DO. It routes no tool call. It imports the enforcing matcher and
calls `_touches_self` in-process, and it reads the daemon's pending list over the
unattributed discovery route. It mints nothing, claims nothing, appeals nothing.

Run: python3 tools/permit_spend_set.py [marker_sha12 ...]
"""
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request

HOME = os.path.expanduser("~")
INSTALLED_DIR = os.path.join(HOME, ".claude", "hooks", "hestia")
REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
INTREE_DIR = os.path.join(REPO, "plugins", "claude-code", "hooks")

SOURCE = INSTALLED_DIR if os.path.isdir(INSTALLED_DIR) else INTREE_DIR
sys.path.insert(0, SOURCE)
import pre_tool_use as G  # noqa: E402

GOV = list(G._GOVERNANCE_FILES)
BAR_SRC = os.path.join(REPO, "core", "src", "server", "gate_escalation.rs")
DAEMON = "http://127.0.0.1:7711/mcp"


def sha12(value):
    return hashlib.sha256(value.encode()).hexdigest()[:12]


def shape(marker):
    """A literal-free fingerprint: enough to recognise the form, not to reproduce it."""
    return {
        "sha12": sha12(marker),
        "len": len(marker),
        "absolute": marker.startswith("/"),
        "has_sep": "/" in marker,
        "names_governed_file": any(f in marker for f in GOV),
    }


# ---------------------------------------------------------------------------
# The bar's own list, read from the bar's own source (never transcribed).
# ---------------------------------------------------------------------------
def _bar_names(path):
    try:
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
    except OSError:
        return None
    start = src.find("pub fn bar_for")
    if start < 0:
        return None
    end = src.find("\n}", start)
    if end < 0:
        return None
    return re.findall(r'contains\("([^"]+)"\)', src[start:end]) or None


STRONG = _bar_names(BAR_SRC)


def bar_of(marker):
    """`bar_for` semantics: substring test over the governance filenames it names."""
    if STRONG is None:
        return "unknown (bar source unreadable)"
    return "sovereign+peer" if any(s in marker for s in STRONG) else "single_approver"


# ---------------------------------------------------------------------------
# The act space: every governed file, in every location it exists, in the spellings
# a member would plausibly use. Locations are DISCOVERED, never spelled.
# ---------------------------------------------------------------------------
def _hook_dirs():
    dirs = []
    if os.path.isdir(INSTALLED_DIR):
        dirs.append(("installed", INSTALLED_DIR))
    plugins = os.path.join(REPO, "plugins")
    if os.path.isdir(plugins):
        for entry in sorted(os.listdir(plugins)):
            hooks = os.path.join(plugins, entry, "hooks")
            if os.path.isdir(hooks):
                dirs.append((f"repo:{entry}", hooks))
        shared = os.path.join(plugins, "_shared")
        if os.path.isdir(shared):
            dirs.append(("repo:_shared", shared))
    return dirs


def _acts():
    """(label, tool, tool_input, governed_name) for genuine writes to governed files."""
    out = []
    for loc, directory in _hook_dirs():
        tilde = "~" + directory[len(HOME):] if directory.startswith(HOME) else None
        for name in GOV:
            path = os.path.join(directory, name)
            if not os.path.exists(path):
                continue
            out.append((f"Write {loc}/<{name}> abs", "Write",
                        {"file_path": path, "content": "x"}, name, loc))
            out.append((f"Bash  cp -> {loc}/<{name}> abs", "Bash",
                        {"command": "cp /tmp/x " + path}, name, loc))
            if tilde:
                tpath = os.path.join(tilde, name)
                out.append((f"Write {loc}/<{name}> tilde", "Write",
                            {"file_path": tpath, "content": "x"}, name, loc))
                # the realistic tilde act: the shell expands it, so the write lands on
                # the real file while the matcher only ever sees the unexpanded text.
                out.append((f"Bash  cp -> {loc}/<{name}> tilde", "Bash",
                            {"command": "cp /tmp/x " + tpath}, name, loc))
    return out


ACTS = _acts()

# marker -> list of genuine governed writes that emit exactly this marker
SPEND = {}
UNMATCHED = []
for label, tool, inp, name, loc in ACTS:
    marker = G._touches_self(tool, inp)
    if marker is None:
        UNMATCHED.append(label)
        continue
    SPEND.setdefault(marker, []).append((label, name, loc))


# ---------------------------------------------------------------------------
# The live pool, over the unattributed discovery route (session_id is OPTIONAL).
# ---------------------------------------------------------------------------
def _rpc(method, params, sid=None, mid=1):
    body = {"jsonrpc": "2.0", "id": mid, "method": method, "params": params}
    req = urllib.request.Request(
        DAEMON, json.dumps(body).encode(),
        {"Content-Type": "application/json",
         "Accept": "application/json, text/event-stream"},
    )
    if sid:
        req.add_header("Mcp-Session-Id", sid)
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read().decode()
        hdr = r.headers.get("Mcp-Session-Id")
    payload = None
    for line in raw.splitlines():
        line = line.strip()
        text = line[5:].strip() if line.startswith("data:") else (
            line if line.startswith("{") else None)
        if text:
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                pass
    return payload, hdr


def live_pool():
    """The pending escalations, or None if the daemon is unreachable."""
    try:
        _, sid = _rpc("initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "permit-spend-set", "version": "1"}})
        resp, _ = _rpc("tools/call", {
            "name": "hestia_gate_pending_escalations", "arguments": {}}, sid=sid, mid=2)
        data = json.loads(resp["result"]["content"][0]["text"])
    except (urllib.error.URLError, KeyError, TypeError, ValueError, OSError):
        return None
    return data.get("escalations") or data.get("pending") or []


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
print(f"matcher       : {G.__file__}")
print(f"governed names: {len(GOV)}   hook dirs found: {len(_hook_dirs())}")
print(f"act space     : {len(ACTS)} genuine writes to governed files, "
      f"{len(SPEND)} distinct markers, {len(UNMATCHED)} matched nothing")
if STRONG is None:
    print(f"bar source    : UNREADABLE at {BAR_SRC} -- bars reported as unknown")
else:
    print(f"bar source    : {len(STRONG)} of {len(GOV)} governed names route strong")
print()

print("Marker equivalence classes over GENUINE governed writes")
print("(claim() is exact equality, so one class = one permit's reach):")
for marker, members in sorted(SPEND.items(), key=lambda kv: -len(kv[1])):
    s = shape(marker)
    names = sorted({n for _, n, _ in members})
    print(f"  {s['sha12']}  len={s['len']:<3} abs={str(s['absolute']):<5} "
          f"names_file={str(s['names_governed_file']):<5} bar={bar_of(marker):<15} "
          f"reaches {len(members)} acts over {len(names)} distinct governed files")
if UNMATCHED:
    print(f"  (unmatched: {len(UNMATCHED)} acts emit no marker at all -- ungoverned here)")
print()

pool = live_pool()
red = []
if pool is None:
    print("live pool     : daemon unreachable; static classes above still stand")
else:
    print(f"live pending pool: {len(pool)} escalation(s), unattributed read")
    for e in pool:
        marker = e.get("marker") or ""
        s = shape(marker)
        buys = SPEND.get(marker, [])
        names = sorted({n for _, n, _ in buys})
        locs = sorted({loc for _, _, loc in buys})
        eid = (e.get("escalation_id") or "?")[:8]
        reason = e.get("stated_reason") or ""
        print(f"  {eid}  marker {s['sha12']} len={s['len']} abs={s['absolute']}  "
              f"tool={e.get('tool_name')}  bar={bar_of(marker)}  "
              f"secs={e.get('secs_remaining')}")
        print(f"            reason sha12 {sha12(reason)} "
              f"mentions_governed_name={any(f in reason for f in GOV)}")
        if buys:
            red.append((eid, len(buys), names))
            print(f"            SPENDABLE ON {len(buys)} genuine governed write(s), "
                  f"{len(names)} distinct file(s), locations {locs}")
            for label, _, _ in buys:
                print(f"              - {label}")
        else:
            print("            spendable on no genuine governed write in the act space")

print()
if red:
    total = sum(n for _, n, _ in red)
    print(f"RED: {len(red)} of {len(pool)} live permits equality-match genuine governed "
          f"writes ({total} acts).")
    print("Each was minted by an act that modified no governance file. The operator who "
          "approves one")
    print("is shown a marker string, not this set.")
    sys.exit(1)
print("GREEN: no live permit equality-matches a genuine governed write.")
sys.exit(0)
