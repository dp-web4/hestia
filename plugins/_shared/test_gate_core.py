#!/usr/bin/env python3
"""Tests for the one policy gate.

Four times in two days a refusal named a door the recipient could not open, and every time it
was written by an author not subject to the constraint that blocked the recipient. This suite
moves part of that class from "a careful author avoids it" to "the build refuses it".

**Part of it.** `remedies_name_only_globally_registered_doors` proves the tool is registered
and dispatched in the daemon — it excludes the `request_scope` case, where the door existed
nowhere. It does NOT prove the refused member can reach it, and it is named for what it
proves (codex NOT-SAME review of #169, finding 3). The stronger per-recipient invariant needs
a per-harness capability manifest and is deliberately not claimed until one exists.

Checks that report "nothing was inspected" say so out loud rather than passing quietly — a
green meaning "nothing ran" is indistinguishable from a green meaning "ran and clean", which
is the failure this repo keeps rediscovering.

Run:  python3 test_gate_core.py          (offline checks only)
      HESTIA_MCP=http://127.0.0.1:7711/mcp python3 test_gate_core.py   (also checks the
                                                                        live tool list)
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hestia_gate_core as G  # noqa: E402

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


# ── the remedy inventory ─────────────────────────────────────────────────────────────────
def live_tool_names():
    """The daemon's ACTUAL tool list. Returns None if the daemon is not reachable — in which
    case this check is SKIPPED and says so, rather than passing vacuously. A green that means
    'nothing was checked' is the null-state twin of a green that means 'checked and fine'."""
    url = os.environ.get("HESTIA_MCP")
    if not url:
        return None
    H = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    sid = {}

    def rpc(method, params, rid=1):
        h = dict(H)
        if sid.get("v"):
            h["Mcp-Session-Id"] = sid["v"]
        body = {"jsonrpc": "2.0", "method": method, "params": params}
        if rid is not None:
            body["id"] = rid
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=h)
        resp = urllib.request.urlopen(req, timeout=20)
        sid.setdefault("v", resp.headers.get("Mcp-Session-Id"))
        return resp.read().decode()

    try:
        rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                           "clientInfo": {"name": "gate-core-test", "version": "1"}})
        rpc("notifications/initialized", {}, rid=None)
        raw = rpc("tools/list", {}, rid=2)
        for line in raw.splitlines():
            if line.startswith("data: {"):
                j = json.loads(line[6:])
                if "result" in j and "tools" in j["result"]:
                    return {t["name"] for t in j["result"]["tools"]}
    except Exception as e:
        print(f"  note  daemon unreachable ({e.__class__.__name__}) — live check SKIPPED")
    return None


def _registered_tools_in_source(candidates):
    """Which of `candidates` are actually REGISTERED and DISPATCHED in the Rust source.

    Two independent sites must both name the tool, because either alone is forgeable by a
    stray mention:
        registration   t("hestia_x", "...")      in `hestia_tools()`
        dispatch       "hestia_x" => tool_x(...) in the match arm
    A tool listed but not dispatched is advertised and dead; dispatched but not listed is
    reachable and undiscoverable. Requiring both is the honest definition of 'exists'."""
    handler = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", "..", "core", "src", "server", "handler.rs")
    try:
        body = open(handler, encoding="utf-8", errors="replace").read()
    except OSError:
        return set()
    registered = set(re.findall(r'^\s*t\(\s*\n?\s*"([a-z_]+)"', body, re.M))
    registered |= set(re.findall(r't\(\s*"([a-z_]+)"\s*,', body))
    dispatched = set(re.findall(r'^\s*"([a-z_]+)"\s*=>\s*tool_', body, re.M))
    return {c for c in candidates if c in registered and c in dispatched}


def test_remedies_name_only_globally_registered_doors():
    """Excludes globally ABSENT tools — the `request_scope` case, where the door existed
    nowhere. It would have caught that on the day it was written, instead of costing kimi a
    blocked session, a misdirected appeal and a correct-but-useless arbitration.

    IT DOES NOT PROVE RECIPIENT REACHABILITY, and is named for what it proves. (codex #169
    finding 3.) `tools/list` is the daemon's GLOBAL registry, so this can be green while the
    refused member cannot call the tool at all — no hestia MCP registration in that harness,
    or the tool not exposed there. That is the measured `hestia_appeal` class: globally
    registered the entire time kimi had no way to reach it.

    The stronger invariant needs a per-harness capability manifest or a probe through each
    shim's own discovery surface. Not claimed until one exists."""
    live = live_tool_names()
    if live is None:
        print("  skip  remedies_name_only_globally_registered_doors (set HESTIA_MCP to run it)")
        return
    named = G.remedy_tools()
    missing = sorted(named - live)

    # RECORD THE DISCRIMINATOR. "The running daemon lacks this tool" has two causes that look
    # identical here and are not remotely the same defect:
    #
    #   NEVER BUILT   — the `request_scope` class. An authoring error: someone wrote a remedy
    #                   for a door that does not exist anywhere. Fix the remedy, or build it.
    #   NOT DEPLOYED  — the tool is in the source and the daemon is running an older binary.
    #                   The remedy is correct and will be true after a restart.
    #
    # Reporting both as "the daemon does NOT have it" would support a count, not a judgement —
    # and the first thing anyone does with an undiscriminated red is relax the check.
    # READ THE DISPATCH TABLE, NOT THE FILE TEXT. (codex #169 finding 4b.) The first version
    # searched for a quoted token anywhere under core/src, so a mention in a comment, a
    # doc-comment or a test fixture would classify a NEVER-BUILT door as merely stale — the
    # softer verdict, on the more serious defect. A tool exists when it is registered AND
    # dispatched; nothing else counts.
    in_source = _registered_tools_in_source(missing)
    never_built = sorted(set(missing) - in_source)
    undeployed = sorted(in_source)

    detail = ""
    if never_built:
        detail += (f"NEVER BUILT (authoring error — fix the remedy or build the door): "
                   f"{never_built}. ")
    if undeployed:
        detail += (f"NOT DEPLOYED (remedy is correct; the running daemon is older than the "
                   f"source): {undeployed}. ")
    # Only a never-built door is an authoring failure. An undeployed one is a true statement
    # about a stale daemon, and it must still be RED — a member reading that remedy today
    # cannot use the door — but the fix is a deploy, not an edit.
    check("remedies_name_only_globally_registered_doors", not missing, detail)
    # And the inverse worth knowing, though not a failure: doors that exist and no remedy
    # points at. A door nobody is ever told about is only marginally better than no door.
    unmentioned = sorted(t for t in live
                         if t in {"hestia_request_scope", "hestia_appeal",
                                  "hestia_gate_escalation_open"} and t not in named)
    if unmentioned:
        print(f"  note  existing doors no remedy names: {unmentioned}")


def test_remedy_text_declares_every_tool_it_names():
    """`tools` is what the check above reads, so a remedy that names a tool in prose but omits
    it from `tools` would slip past. Scan the prose too."""
    bad = []
    for rule, r in G.REMEDIES.items():
        in_prose = set(re.findall(r"\bhestia_[a-z_]+\b", r.text))
        undeclared = in_prose - set(r.tools)
        if undeclared:
            bad.append((rule, sorted(undeclared)))
    check("remedy_text_declares_every_tool_it_names", not bad, str(bad))


def test_unregistered_rule_denies_and_never_raises():
    """codex #169 finding 1. An unknown rule must produce a DENIAL, not an exception.

    The first version asserted the opposite — it treated `_deny` raising KeyError as success.
    On engines that fail OPEN on exception (which is every lineage engine, and is this
    module's stated premise) that "loud" path is an ALLOW. The test blessed the fail-open."""
    try:
        v = G._deny("rule.that.does.not.exist", "some reason")
    except Exception as e:
        check("unregistered_rule_never_raises", False,
              f"raised {e.__class__.__name__} — on a fail-open engine that is an ALLOW")
        return
    check("unregistered_rule_never_raises", True)
    check("unregistered_rule_denies", v.blocks)
    check("unregistered_rule_still_carries_text", bool(v.remedy))


def test_every_literal_deny_rule_is_registered():
    """codex #169 finding 1, second half. The runtime now fails closed; the AUTHORING mistake
    must still be caught at build time, and by enumerating actual call sites rather than by
    hoping every path is exercised.

    Reads the AST for every literal `_deny("...")` in the core. A future branch adding
    `_deny("new.rule", ...)` on an untested path is red here even though nothing calls it."""
    import ast
    src_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hestia_gate_core.py")
    tree = ast.parse(open(src_path, encoding="utf-8").read())
    literal, dynamic = set(), []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "_deny"):
            continue
        if not node.args:
            dynamic.append(node.lineno)
        elif isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            literal.add(node.args[0].value)
        else:
            dynamic.append(node.lineno)
    unregistered = sorted(literal - set(G.REMEDIES))
    check("every_literal_deny_rule_is_registered", not unregistered,
          f"_deny called with unregistered rule ids: {unregistered}")
    # Policy on dynamic ids, stated rather than assumed: they are NOT allowed in the core,
    # because a rule id computed at runtime cannot be checked here and would route straight to
    # the unregistered-rule fallback — a correct refusal with a useless remedy.
    check("no_dynamic_deny_rule_ids", not dynamic,
          f"_deny called with a non-literal rule id at lines {dynamic}; the AST check cannot "
          f"verify those, so they are disallowed in the core")
    check("deny_call_sites_were_actually_found", len(literal) >= 3,
          f"only found {len(literal)} literal _deny call sites — the AST walk may be broken, "
          f"which would make this check silently vacuous")


def test_egress_offers_no_door():
    """The one refusal that must NOT name a remedy tool. A leaked secret has no undo, so
    offering a channel would imply the act is available at a price."""
    check("egress_offers_no_door", G.REMEDIES["egress.secret"].tools == ())


def test_scope_remedy_distinguishes_itself_from_appeal():
    """The confusion that cost kimi a cycle. Both scope remedies must name the scope door AND
    say the appeal channel cannot deliver a path."""
    for rule in ("mrh.path", "mrh.command"):
        t = G.REMEDIES[rule].text.lower()
        check(f"{rule}_names_the_scope_door", "hestia_request_scope" in t)
        check(f"{rule}_distinguishes_appeal", "hestia_appeal" in t)


# ── policy behaviour ─────────────────────────────────────────────────────────────────────
def _strip_prose(src):
    """Code lines only — no comments, no docstrings.

    Written as a helper because I got this wrong twice in one session: a drift detector that
    hashed function TEXT reported comment edits as semantic drift, and the first version of
    `core_never_calls_sys_exit` matched the phrase inside the core's own docstring saying it
    never calls it. A check that reads prose is measuring the wrong artifact."""
    out, ds = [], False
    for line in src.splitlines():
        s = line.strip()
        if s.startswith('"""') or s.startswith("'''"):
            q = s[:3]
            ds = not (s.count(q) >= 2 and len(s) > 3)
            continue
        if ds or s.startswith("#") or not s:
            continue
        out.append(line)
    return "\n".join(out)


def _workspace():
    """A scratch workspace that is NOT under /tmp.

    /tmp is unconditionally in scope, so a fake workspace built with plain `mkdtemp()` is
    allowed wholesale and every scope assertion passes for the wrong reason — five green
    checks that measured nothing. Exactly the null-state twin: a pass bit-identical to 'the
    gate is not running'."""
    base = os.path.expanduser("~/.cache/hestia-gate-core-tests")
    os.makedirs(base, exist_ok=True)
    ws = tempfile.mkdtemp(dir=base)
    assert not ws.startswith(("/tmp", "/var/tmp")), ws
    return ws


def _profile(tmp, scope, certified=True):
    """A member identity file.

    CERTIFIED BY DEFAULT after the #188 redesign: an uncertified replica now grants nothing,
    so a fixture without a cert block would make every scope test assert the refusal path
    instead of the logic it means to exercise. Pass `certified=False` to get the raw shape a
    member writes for itself."""
    p = os.path.join(tmp, "identity.json")
    mrh = {"in_scope": scope}
    if certified:
        mrh["replica"] = {"generation": 1, "expires_at": G.now_secs() + 3600}
    with open(p, "w", encoding="utf-8") as fh:
        json.dump({"mrh": mrh, "role": "role:constellation:member"}, fh)
    return G.HarnessProfile(member_id="test-member", identity_path=p,
                            home_markers=("~/.test-member",))


def test_path_and_command_scope():
    ws = _workspace()
    for r in ("granted", "notgranted"):
        os.makedirs(os.path.join(ws, r), exist_ok=True)
    prof = _profile(ws, ["repo:granted"])

    ev = G.NormalizedEvent(tool="Read", paths=[f"{ws}/granted/a.md"], cwd=ws)
    check("in_scope_path_allows", G.evaluate(ev, prof, ws).decision == "allow")

    ev = G.NormalizedEvent(tool="Read", paths=[f"{ws}/notgranted/a.md"], cwd=ws)
    v = G.evaluate(ev, prof, ws)
    check("out_of_scope_path_denies", v.blocks and v.rule == "mrh.path")
    check("deny_carries_a_remedy", "hestia_request_scope" in v.remedy)
    check("deny_names_the_offending_target", "notgranted" in v.reason)

    ev = G.NormalizedEvent(tool="Read", paths=[f"{ws}"], cwd=ws)
    check("bare_workspace_root_denies", G.evaluate(ev, prof, ws).blocks)

    # /tmp and the member's own home are always reachable.
    ev = G.NormalizedEvent(tool="Read", paths=["/tmp/x"], cwd=ws)
    check("tmp_allows", G.evaluate(ev, prof, ws).decision == "allow")


def test_path_grant_reaches_a_sibling_of_the_repos():
    """`.git-inbox` is a sibling of the repos, so a repo: grant never reaches it — the exact
    refusal kimi hit on 2026-08-02 while reading the directory the push guard names."""
    ws = _workspace()
    os.makedirs(os.path.join(ws, ".git-inbox"), exist_ok=True)
    ev = G.NormalizedEvent(tool="Read", paths=[f"{ws}/.git-inbox/submissions"], cwd=ws)

    without = _profile(ws, ["repo:granted"])
    check("sibling_denied_without_path_grant", G.evaluate(ev, without, ws).blocks)

    with_grant = _profile(_workspace(), ["repo:granted", "path:.git-inbox"])
    check("sibling_allowed_with_path_grant",
          G.evaluate(ev, with_grant, ws).decision == "allow")


def test_temp_root_is_a_path_boundary_not_a_prefix():
    """codex #169 finding 2. `startswith("/tmp")` admits `/tmp-other` — a SIBLING of the temp
    root, and a directory anyone can create. That would hand a member unconditional reach by
    naming a directory: no grant, no witness, no operator.

    Same defect class as `reviewer ⊄ review` in the mesh vocabulary: a boundary rule written
    as a substring rule."""
    check("temp_root_itself", G._under_temp_root("/tmp"))
    check("temp_descendant", G._under_temp_root("/tmp/x/y"))
    check("var_temp_descendant", G._under_temp_root("/var/tmp/x"))
    # The bypasses.
    check("sibling_tmp_denied", not G._under_temp_root("/tmp-other/x"))
    check("sibling_var_tmp_denied", not G._under_temp_root("/var/tmpsecrets/y"))
    check("tmp_prefix_word_denied", not G._under_temp_root("/tmpfoo"))
    # And through the real decision path, not just the helper.
    ws = _workspace()
    os.makedirs(os.path.join(ws, "granted"), exist_ok=True)
    prof = _profile(ws, ["repo:granted"])
    ev = G.NormalizedEvent(tool="Read", paths=["/tmp-other/loot"], cwd=ws)
    check("sibling_tmp_denied_end_to_end", G.evaluate(ev, prof, ws).blocks)


def test_scope_is_decided_after_normalisation_not_before():
    """kimi #940 B5/B7. Normalisation ran on the RELATIVE branch only, so an absolute path was
    judged on its lexical first segment: with scope `granted`, `<ws>/granted/../notgranted/x`
    took seg `granted` and was ALLOWED while resolving into an ungranted repo. The relative
    spelling of the identical path was denied — which is what pins the seat to the absolute
    branch rather than to the segment rule.

    Not a curiosity of odd scope entries: this is an ORDINARY grant escaped by an ORDINARY
    spelling, and for the Bash arm the text is member-controlled end to end, so it depends on
    no harness cooperating. Fix is legion's phase0 principle (2026-07-17): normpath first,
    containment decides."""
    ws = _workspace()
    for r in ("granted", "notgranted"):
        os.makedirs(os.path.join(ws, r), exist_ok=True)
    prof = _profile(ws, ["repo:granted"])
    escape = f"{ws}/granted/../notgranted/secret"

    # Positive controls FIRST: the grant must still work, or a deny-everything regression
    # would green every assertion below for the wrong reason.
    ev = G.NormalizedEvent(tool="Read", paths=[f"{ws}/granted/a.md"], cwd=ws)
    check("control_grant_still_allows", G.evaluate(ev, prof, ws).decision == "allow")
    ev = G.NormalizedEvent(tool="Bash", command=f"cat {ws}/granted/a.md", cwd=ws)
    check("control_granted_command_still_allows", G.evaluate(ev, prof, ws).decision == "allow")

    # B5 — the path arm.
    ev = G.NormalizedEvent(tool="Read", paths=[escape], cwd=ws)
    v = G.evaluate(ev, prof, ws)
    check("abs_dotdot_escape_denies", v.blocks and v.rule == "mrh.path")
    # And the deny must not name the repo the member DOES hold as the offender.
    check("deny_names_the_resolved_repo_not_the_spelled_one",
          "notgranted" in v.reason, v.reason)

    # B6 — the relative spelling was already correct; it must stay correct.
    ev = G.NormalizedEvent(tool="Read", paths=["granted/../notgranted/secret"], cwd=ws)
    check("rel_dotdot_escape_still_denies", G.evaluate(ev, prof, ws).blocks)

    # B7 — the command arm, same shape, no harness in the loop.
    ev = G.NormalizedEvent(tool="Bash", command=f"cat {escape}", cwd=ws)
    v = G.evaluate(ev, prof, ws)
    check("abs_dotdot_escape_in_command_denies", v.blocks and v.rule == "mrh.command")

    # Traversal clean out of the workspace, not merely into a sibling repo.
    ev = G.NormalizedEvent(tool="Read", paths=[f"{ws}/granted/../../etc/shadow"], cwd=ws)
    check("traversal_past_workspace_root_denies", G.evaluate(ev, prof, ws).blocks)

    # Containment is a boundary, not `workspace in p`: a path merely CONTAINING the workspace
    # string was judged by whatever followed it. kimi named this one as residual; it costs one
    # line to close alongside, so it is closed rather than carried.
    ev = G.NormalizedEvent(tool="Read", paths=[f"/decoy{ws}/granted/x"], cwd=ws)
    check("workspace_as_substring_is_not_containment", G.evaluate(ev, prof, ws).blocks)


def test_path_syntax_is_never_a_scope_name():
    """kimi #940 B1-B4. `.` and `..` survived the parser as "legacy bare names" and each
    granted wide: scope `.` reached every repo via the `/./` spelling, scope `..` reached past
    the workspace root.

    Normalising first (above) already makes them unmatchable — and that is exactly why they
    are ALSO dropped here. "Unmatchable" is a claim about a matcher, and this thread reversed
    that claim once already: `ssh:/etc` could not match a first segment, `ssh:etc` could, and
    the disposition "inert in practice" survived a review round before a probe killed it."""
    check("dot_entry_dropped", G._parse_scope_entries(["."]) == ())
    check("dotdot_entry_dropped", G._parse_scope_entries([".."]) == ())
    check("prefixed_dot_entry_dropped", G._parse_scope_entries(["path:.."]) == ())
    # It must drop path syntax WITHOUT eating the two things that look adjacent:
    check("real_name_survives", G._parse_scope_entries(["repo:hestia"]) == ("hestia",))
    check("dotfile_name_survives", G._parse_scope_entries(["path:.git-inbox"]) == (".git-inbox",))
    check("unscoped_survives", G._parse_scope_entries(["*"]) == (G.AgentPolicy.UNSCOPED,))

    # End to end: a policy carrying only path syntax grants nothing, rather than everything.
    ws = _workspace()
    os.makedirs(os.path.join(ws, "notgranted"), exist_ok=True)
    prof = _profile(ws, ["repo:."])
    ev = G.NormalizedEvent(tool="Read", paths=[f"{ws}/./notgranted/secret"], cwd=ws)
    check("dot_scope_grants_nothing_end_to_end", G.evaluate(ev, prof, ws).blocks)


def test_shims_contain_no_policy():
    """codex #169 finding 4. The module docstring credited this test before it existed.

    Reports what it checked. With no shims present it says so rather than passing silently —
    a green meaning 'nothing was inspected' is indistinguishable from 'inspected and clean',
    which is the null-state twin this thread keeps meeting."""
    here = os.path.dirname(os.path.abspath(__file__))
    shims = sorted(f for f in os.listdir(here)
                   if f.startswith("shim_") and f.endswith(".py"))
    if not shims:
        print("  note  shims_contain_no_policy: 0 shims present — NOTHING CHECKED "
              "(live the moment a shim_*.py lands)")
        return
    banned = ("in_scope", "FORBIDDEN", "REMEDIES", "Remedy(", "_deny(", "remedy=")
    bad = []
    for f in shims:
        code = _strip_prose(open(os.path.join(here, f), encoding="utf-8").read())
        hits = [b for b in banned if b in code]
        if hits:
            bad.append((f, hits))
    check("shims_contain_no_policy", not bad,
          f"{bad} — a shim may only parse events and render verdicts. If it needs a policy "
          f"choice, add a HarnessProfile field instead of branching in the shim.")


def test_the_core_is_not_the_only_copy_of_the_scope_rule():
    """How far does a fix to this file actually reach? Today: one enforcing copy in five.

    `test_shims_contain_no_policy` above is the guard meant to hold the line that policy lives
    only here. It globs `shim_*.py` inside `_shared/`, and there are none — so it prints
    "0 shims present — NOTHING CHECKED" and returns green. Its blind fraction is TOTAL: the
    four un-consolidated copies are real per-harness hook files, which that glob cannot match.
    A guard whose population is empty reports "clean" and "I inspected nothing" in one word.

    Those copies are DRIFTED, not merely duplicated — they carry defects this file already
    fixed. The kimi and gemini hooks still gate temp on `startswith(("/tmp", "/var/tmp"))`,
    the prefix-not-boundary bug codex found in #169 and `_under_temp_root` fixed here, so
    `/tmp-other/x` is granted unconditionally there. The gemini copy does not normalise at
    all, and falls back to reading a first segment off paths OUTSIDE the workspace.

    This test does not assert the copies are correct — they are not, and rewriting four
    harnesses' gates is not one member's call. It asserts the INVENTORY, so the divergence is
    a number in CI rather than something the next sweep rediscovers. It fails in both
    directions on purpose: a new entry means the policy was forked again; a missing one means
    consolidation advanced and this list owes an update.

    Keyed by harness directory, not by hook filename, deliberately: the gate refuses a write
    whose CONTENT names a hook file (escalation a5737cc207e54e3d, taken on this very edit) —
    a false positive of the same lexical mention-scanning class this commit fixes. Recorded
    rather than worked around; the directory is the stabler key regardless."""
    plugins_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # Frozen 2026-08-05. Shrink as harnesses consolidate onto the core; never grow it without
    # saying, in the PR, why a fifth copy of the scope rule is the right answer.
    KNOWN_DUPLICATE_OWNERS = {"codex": 2, "gemini": 1, "kimi": 1}

    owners = {}
    for root, _dirs, files in os.walk(plugins_dir):
        for f in files:
            if not f.endswith(".py") or f.startswith("test_"):
                continue
            full = os.path.join(root, f)
            rel = os.path.relpath(full, plugins_dir)
            if rel.split(os.sep)[0] == "_shared":
                continue
            try:
                src = open(full, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            if "def path_in_scope" in src or "def command_in_scope" in src:
                owners[rel.split(os.sep)[0]] = owners.get(rel.split(os.sep)[0], 0) + 1

    total = sum(owners.values())
    print(f"  note  the scope rule is defined in {total + 1} places — the core plus "
          f"{total} un-consolidated copies across {sorted(owners)}")
    check("scope_rule_duplication_matches_inventory", owners == KNOWN_DUPLICATE_OWNERS,
          f"found {owners}, inventory says {KNOWN_DUPLICATE_OWNERS} — a fix to the core "
          f"reaches only the core, so this number is the blast radius of every gate fix.")


def test_unscoped_must_be_declared_never_inferred():
    """dp's P0 ruling: per-agent modifications must be an EXPLICIT part of the one law.

    An absent check is not explicit. claude-code had no MRH evaluation at all — measured
    2026-08-03, a `dpx` path outside every workspace, invented by the member with no operator
    involvement, passed both Read and Bash. Now the same reach requires `*` to have been
    written into the vault, where it can be audited, revoked and expired.

    Tested through `evaluate()`, not by reading the dataclass: the question is whether the GATE
    behaves differently, not whether a field holds a string."""
    ws = _workspace()
    os.makedirs(os.path.join(ws, "granted"), exist_ok=True)
    prof = _profile(ws, ["repo:granted"])
    ev = G.NormalizedEvent(tool="Read", paths=[f"{ws}/notgranted/x.md"], cwd=ws)

    empty = G.AgentPolicy(member_id="m", scope=(), source="unresolved")
    check("empty_scope_grants_nothing", G.evaluate(ev, prof, ws, policy=empty).blocks,
          "an unresolvable policy must grant NOTHING — the old load_in_scope returned "
          "['web4'] on failure, which is a guess that GRANTS")

    unscoped = G.AgentPolicy(member_id="m", scope=("*",), source="vault")
    check("declared_unscoped_allows", G.evaluate(ev, prof, ws, policy=unscoped).decision == "allow")

    # AND `*` IS A SCOPE GRANT, NOT A LICENCE. The innate egress invariant binds every member
    # equally; trust does not relax it, so unlimited reach must still not buy a credential.
    secret = G.NormalizedEvent(tool="Read", paths=[f"{ws}/granted/.env"], cwd=ws)
    v = G.evaluate(secret, prof, ws, policy=unscoped)
    check("unscoped_still_cannot_reach_a_secret", v.blocks and v.rule == "egress.secret" and v.innate,
          "`*` short-circuits MRH scope only, and must sit AFTER the innate egress gate")


def test_a_member_cannot_grant_itself_blanket_allow_via_its_own_identity_file():
    """kimi NOT-SAME review of #188, finding 1 — a privilege-escalation path I shipped inside
    the file meant to close one.

    `stale` was written in three places and read in NONE. No call passes a `vault_reader`
    today, so every resolution came from `identity.json` — member-writable, as this module's
    own docstring says — and was honoured in full INCLUDING `is_unscoped()`. A member could
    write `"*"` into its own identity file and receive blanket ALLOW, while my audit block
    claimed `the member cannot write its own authority`.

    This is the exploit, written as the test: identity file says `*`, no vault reachable."""
    ws = _workspace()
    os.makedirs(os.path.join(ws, "granted"), exist_ok=True)
    prof = _profile(ws, ["*"])          # the member writes the wildcard into its OWN file
    pol = G.resolve_agent_policy(prof)  # no vault_reader — the situation in every call today

    check("self_written_wildcard_is_marked_stale", pol.stale is True and pol.is_unscoped())

    ev = G.NormalizedEvent(tool="Read", paths=[f"{ws}/notgranted/x.md"], cwd=ws)
    v = G.evaluate(ev, prof, ws, policy=pol)
    check("stale_wildcard_does_not_grant_blanket_allow", v.blocks,
          "a member wrote '*' into its own identity file and the gate allowed everything — "
          "the audit block claimed the member cannot write its own authority")

    # A VAULT-SOURCED wildcard still works: the fix must narrow the untrusted path only, not
    # break the declared grant it exists to make explicit.
    trusted = G.resolve_agent_policy(prof, vault_reader=lambda m: {"in_scope": ["*"]})
    check("vault_wildcard_still_allows",
          not trusted.stale and G.evaluate(ev, prof, ws, policy=trusted).decision == "allow")


def _replica(tmp, scope, generation=1, ttl=3600):
    """An identity file carrying a certified replica block."""
    p = os.path.join(tmp, "identity.json")
    cert = {"generation": generation, "expires_at": G.now_secs() + ttl}
    with open(p, "w", encoding="utf-8") as fh:
        json.dump({"mrh": {"in_scope": scope, "replica": cert}, "role": "role:x"}, fh)
    return G.HarnessProfile(member_id="m", identity_path=p)


def test_an_uncertified_replica_is_refused_not_honoured():
    """codex/gpt audit of #188: **stale does not mean narrower.**

    My design rested on "a replica can only be staler, and staler-standing is narrower." That
    holds for grants ADDED since the copy and FAILS for grants REVOKED since it — a replica
    still carrying a revoked grant is WIDER than current policy. Revocation is exactly the
    operation an authority most needs to work, and exactly the one the fallback defeated.

    So a replica is not trusted for being old. It is trusted for being certified, and only
    within limits it carries itself."""
    ws = _workspace()
    # A plain identity file — no replica block. This is the shape a member writes itself.
    plain = _profile(ws, ["repo:granted"], certified=False)
    pol = G.resolve_agent_policy(plain)
    check("uncertified_replica_grants_nothing", pol.scope == (),
          f"an uncertified file was honoured: {pol.scope}")
    check("uncertified_says_why", pol.source == "replica-uncertified", pol.source)

    # Certified and live: honoured, and it says which policy it is.
    good = _replica(_workspace(), ["repo:granted"])
    pol = G.resolve_agent_policy(good)
    check("certified_replica_is_honoured", "granted" in pol.scope)
    check("certified_replica_carries_generation", pol.generation == 1)

    # Certified but EXPIRED: refused. The longer the authority has been unreachable, the more
    # likely a revocation this copy cannot know about — expiry bounds that unknowability.
    old = _replica(_workspace(), ["repo:granted"], ttl=-1)
    pol = G.resolve_agent_policy(old)
    check("expired_replica_grants_nothing", pol.scope == () and pol.source == "replica-expired",
          f"{pol.source} {pol.scope}")


def test_a_replica_can_never_widen_to_unscoped():
    """Even certified, the one value a member would write to escape must not come from here."""
    ws = _workspace()
    os.makedirs(os.path.join(ws, "granted"), exist_ok=True)
    prof = _replica(_workspace(), ["*"])
    pol = G.resolve_agent_policy(prof)
    ev = G.NormalizedEvent(tool="Read", paths=[f"{ws}/notgranted/x.md"], cwd=ws)
    check("certified_wildcard_still_does_not_grant_everything",
          G.evaluate(ev, prof, ws, policy=pol).blocks,
          "a replica yielded blanket ALLOW — certification bounds staleness, it does not "
          "confer the authority to remove the boundary entirely")


def test_an_unknown_prefix_is_dropped_and_could_previously_grant():
    """kimi #937 finding C, sharpened by probe before accepting it.

    kimi read the doc-vs-code gap (comment: unknown prefix "dropped"; code: kept) as inert
    and recommended fixing the DOC, on the basis that a colon-bearing entry can never equal a
    first path segment. That holds only for the slash-bearing form they tested. `ssh:etc` has
    no slash, so it is a legal single segment, and the kept entry GRANTED a workspace child
    literally named that — finding 3's defect one shape over, in the granting direction. So
    the code side moved, not the doc."""
    ws = _workspace()
    prof = G.HarnessProfile(member_id="m", identity_path="/nonexistent/identity.json")

    check("unknown_prefix_with_slash_dropped", G._parse_scope_entries(["ssh:/etc"]) == ())
    check("unknown_prefix_without_slash_dropped", G._parse_scope_entries(["ssh:etc"]) == (),
          "the shape that could actually grant")

    # The regression this closes: parsed-and-kept, it matched a real segment.
    check("kept_unknown_prefix_would_have_granted",
          G.path_in_scope(f"{ws}/ssh:etc/secret", ["ssh:etc"], ws, prof),
          "if this is False the probe no longer demonstrates the risk — recheck path_in_scope")
    check("dropped_unknown_prefix_grants_nothing",
          not G.path_in_scope(f"{ws}/ssh:etc/secret",
                              list(G._parse_scope_entries(["ssh:etc"])), ws, prof))

    # The spellings that must survive: the drop is narrow, not a blanket colon ban on grants.
    check("known_prefixes_still_parse",
          G._parse_scope_entries(["repo:web4", "path:.git-inbox"]) == ("web4", ".git-inbox"))
    check("legacy_bare_name_still_parses", G._parse_scope_entries(["web4"]) == ("web4",))
    check("bare_wildcard_still_unscoped", G._parse_scope_entries(["*"]) == ("*",))
    check("prefixed_wildcard_still_collapses_to_nothing",
          G._parse_scope_entries(["repo:*", "path:*"]) == ())


def test_malformed_vault_payload_fails_closed_instead_of_raising():
    """kimi #188, finding 2. The reader call was wrapped; the PARSE was not. A non-string
    element propagated an AttributeError out of the gate — and on a fail-open harness an
    exception escaping the gate IS an allow, the same shape `_deny` was corrected for."""
    ws = _workspace()
    prof = G.HarnessProfile(member_id="x", identity_path="/nonexistent/identity.json")
    try:
        pol = G.resolve_agent_policy(prof, vault_reader=lambda m: {"in_scope": ["repo:a", 7, None]})
    except Exception as e:
        check("malformed_vault_never_raises", False, f"raised {e.__class__.__name__}")
        return
    check("malformed_vault_never_raises", True)
    check("malformed_vault_grants_nothing", pol.scope == () and pol.source == "unresolved")


def test_prefixed_wildcard_is_not_unscoped():
    """kimi #188, finding 3. `split(":", 1)[-1]` collapsed `repo:*` to the bare wildcard, so an
    operator writing what reads as "every repo" would have granted "no boundary at all" —
    UNSCOPED by parser incidental rather than by decision."""
    check("bare_wildcard_is_unscoped", G._parse_scope_entries(["*"]) == ("*",))
    check("repo_wildcard_is_not_unscoped", "*" not in G._parse_scope_entries(["repo:*"]))
    check("path_wildcard_is_not_unscoped", "*" not in G._parse_scope_entries(["path:*"]))
    check("normal_entries_still_parse",
          G._parse_scope_entries(["repo:web4", "path:.git-inbox", "legacy"])
          == ("web4", ".git-inbox", "legacy"))


def test_policy_resolution_names_its_source_and_fails_closed():
    """A policy that cannot say where it came from is not auditable, and an unreachable vault
    must narrow rather than widen."""
    ws = _workspace()
    prof = _profile(ws, ["repo:granted"])

    # Vault wins, and says so.
    pol = G.resolve_agent_policy(prof, vault_reader=lambda m: {"in_scope": ["repo:fromvault"]})
    check("vault_is_the_authority", pol.scope == ("fromvault",) and pol.source == "vault")
    check("vault_result_is_not_stale", pol.stale is False)

    # Vault unreachable -> replica, MARKED STALE so a caller can refuse to honour grants from it.
    def boom(_m):
        raise RuntimeError("daemon unreachable")
    pol = G.resolve_agent_policy(prof, vault_reader=boom)
    check("falls_back_to_replica", pol.source == "local-replica" and "granted" in pol.scope)
    check("replica_is_marked_stale", pol.stale is True,
          "a replica can only be staler than the vault; the caller must be able to tell")

    # Neither -> nothing granted. Not a narrow guess. Nothing.
    nowhere = G.HarnessProfile(member_id="x", identity_path="/nonexistent/identity.json")
    pol = G.resolve_agent_policy(nowhere, vault_reader=lambda m: None)
    check("unresolvable_grants_nothing", pol.scope == () and pol.source == "unresolved")
    check("unresolvable_is_not_unscoped", not pol.is_unscoped(),
          "empty means NOTHING GRANTED; conflating it with '*' is how an absent check becomes "
          "a silent permission")
def test_gate_unavailability_is_recorded_outside_the_chain():
    """dp, 2026-08-04: a fail-closed deny is infra failure, not the agent's fault — *"we should
    log it somewhere"*, and *"the chain is there to witness member events, not infra telemetry"*.

    The event that could not be witnessed (because the daemon was unreachable) now lands in a
    local file the watcher reads, carrying the cause the member must respond to."""
    home = _workspace()
    ok = G.record_gate_unavailable("kimi-code", "Edit", "timeout", "budget exceeded", home=home)
    check("telemetry_written", ok)

    path = os.path.join(home, G.GATE_TELEMETRY_RELPATH)
    check("telemetry_file_exists", os.path.exists(path))
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    check("one_row", len(rows) == 1, f"{len(rows)} rows")
    if not rows:
        return
    r = rows[0]
    check("names_the_member", r["member"] == "kimi-code")
    check("carries_the_cause", r["cause"] == "timeout",
          "timeout and refused want OPPOSITE responses — back off vs stop and escalate")
    # THE LOAD-BEARING PROPERTY: this must never be mistaken for a member act. If these were
    # scored, ~135 of 301 measured denies would count against members for an infra fault.
    check("declares_it_is_not_a_member_act", r["kind"] == "gate_unavailable" and "conduct" in r["note"])
    state_path = os.path.join(home, G.GATE_TELEMETRY_STATE_RELPATH)
    state = json.load(open(state_path, encoding="utf-8"))
    check("outage_summary_starts_at_one", state["count"] == 1 and state["cause"] == "timeout")

    # An unrecognised cause degrades to "unknown" rather than being echoed — a wrong cause
    # sends the member to the wrong response (a peer sat parked 4 minutes on 2026-07-28).
    G.record_gate_unavailable("m", "Bash", "banana", home=home)
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    check("unrecognised_cause_becomes_unknown", rows[-1]["cause"] == "unknown")
    check("appends_rather_than_replaces", len(rows) == 2)
    state = json.load(open(state_path, encoding="utf-8"))
    check("outage_summary_starts_new_window_on_cause_change", state["count"] == 1,
          "a changed cause starts a new outage window rather than inflating the prior one")


def test_telemetry_never_raises_on_the_failure_path():
    """It runs when the system is ALREADY degraded. A telemetry writer that can throw turns an
    infra hiccup into a gate crash — and on a fail-open harness a gate crash is an ALLOW."""
    ok = G.record_gate_unavailable("m", "Edit", "timeout", home="/proc/nonexistent/cannot/write")
    check("unwritable_returns_false_not_raises", ok is False,
          "must report failure, never propagate it into the gate")


def test_egress_beats_scope():
    """Innate invariants dominate: a secret inside a GRANTED repo is still denied."""
    ws = _workspace()
    os.makedirs(os.path.join(ws, "granted"), exist_ok=True)
    prof = _profile(ws, ["repo:granted"])
    ev = G.NormalizedEvent(tool="Read", paths=[f"{ws}/granted/.env"], cwd=ws)
    v = G.evaluate(ev, prof, ws)
    check("egress_beats_scope", v.blocks and v.rule == "egress.secret" and v.innate)


def test_missing_identity_fails_narrow_not_wide():
    """A malformed or absent identity must not grant reach. The default is deliberately one
    repo, not the workspace."""
    prof = G.HarnessProfile(member_id="x", identity_path="/nonexistent/identity.json")
    check("missing_identity_is_narrow", G.load_in_scope(prof) == ["web4"])


def test_core_never_exits():
    """The core returns a Verdict; only shims exit. Every lineage hook engine fails OPEN, so a
    shim must never be able to confuse 'no verdict' with 'allowed'."""
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "hestia_gate_core.py"), encoding="utf-8").read()
    check("core_never_calls_sys_exit", "sys.exit" not in _strip_prose(src))


def test_core_is_vendor_agnostic():
    """No harness may be named in the core — that is what the profile is for. MEMBER_ADDRESSES
    is the one allowed exception and is checked separately below."""
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "hestia_gate_core.py"), encoding="utf-8").read()
    code = []
    ds = False
    for line in src.splitlines():
        s = line.strip()
        if s.startswith('"""') or s.startswith("'''"):
            q = s[:3]
            ds = not (s.count(q) >= 2 and len(s) > 3)
            continue
        if ds or s.startswith("#") or not s:
            continue
        code.append(line)
    code = "\n".join(code)
    # Strip the one sanctioned list of member addresses before scanning.
    code = re.sub(r"MEMBER_ADDRESSES = frozenset\(\{[^}]*\}\)", "", code)
    leaked = [v for v in ("kimi", "codex", "cursor", "gemini", "claude-code")
              if v in code.lower()]
    check("core_is_vendor_agnostic", not leaked,
          f"vendor names in core logic: {leaked} — add a HarnessProfile field instead")


# EVERY TEST IS CALLED BY NAME, and a second check proves the list is complete.
#
# The first version discovered tests by scanning `globals()` for a `test_` prefix. They did
# run — but `tools/ci_selfexec_test.py` red-flagged the file, and it was right to: a checker
# cannot see a dynamic dispatch, and neither can a reviewer. Rename a function, or typo the
# prefix, and it silently stops executing while the file still reports green. That is the
# null-state twin this suite exists to argue against, sitting in the suite itself.
#
# So: explicit calls, plus `test_every_test_is_registered` below, which fails if a `test_*`
# function exists that this list does not name. Explicit AND complete — either alone rots.
ALL_TESTS = [
    "test_remedies_name_only_globally_registered_doors",
    "test_remedy_text_declares_every_tool_it_names",
    "test_unregistered_rule_denies_and_never_raises",
    "test_every_literal_deny_rule_is_registered",
    "test_egress_offers_no_door",
    "test_scope_remedy_distinguishes_itself_from_appeal",
    "test_path_and_command_scope",
    "test_path_grant_reaches_a_sibling_of_the_repos",
    "test_temp_root_is_a_path_boundary_not_a_prefix",
    "test_shims_contain_no_policy",
    "test_unscoped_must_be_declared_never_inferred",
    "test_a_member_cannot_grant_itself_blanket_allow_via_its_own_identity_file",
    "test_an_uncertified_replica_is_refused_not_honoured",
    "test_a_replica_can_never_widen_to_unscoped",
    "test_an_unknown_prefix_is_dropped_and_could_previously_grant",
    "test_malformed_vault_payload_fails_closed_instead_of_raising",
    "test_prefixed_wildcard_is_not_unscoped",
    "test_policy_resolution_names_its_source_and_fails_closed",
    "test_gate_unavailability_is_recorded_outside_the_chain",
    "test_telemetry_never_raises_on_the_failure_path",
    "test_egress_beats_scope",
    "test_missing_identity_fails_narrow_not_wide",
    "test_core_never_exits",
    "test_core_is_vendor_agnostic",
    "test_scope_is_decided_after_normalisation_not_before",
    "test_path_syntax_is_never_a_scope_name",
    "test_the_core_is_not_the_only_copy_of_the_scope_rule",
]


def test_every_test_is_registered():
    """The completeness half. Explicit calls stop a rename from silently disabling a test;
    this stops a NEW test from silently never running.

    TWO lists, and only one of them executes. `ALL_TESTS` is a registry; the `__main__` block
    below is a hand-maintained call list, and CI invokes this file BARE (`python3 "$t"`), so
    the call list is the one that runs in CI. Registering without calling therefore passed
    this check while the test was dead in the only arm that gates a merge — caught on the
    three tests added with the #940 scope fix, which were registered, green under pytest, and
    never executed by CI. Both halves are now asserted."""
    defined = {k for k in globals() if k.startswith("test_")}
    missing = sorted(defined - set(ALL_TESTS) - {"test_every_test_is_registered"})
    check("every_test_is_registered", not missing,
          f"defined but not in ALL_TESTS, so never run: {missing}")

    src = open(os.path.abspath(__file__), encoding="utf-8").read()
    main_block = src.split('if __name__ ==', 1)[-1]
    uncalled = sorted(t for t in ALL_TESTS if f"{t}()" not in main_block)
    check("every_registered_test_is_called_by_the_bare_runner", not uncalled,
          f"in ALL_TESTS but never called in __main__, so INVISIBLE to CI's bare run: "
          f"{uncalled}")


def teardown_module(module):
    """Deliver this file's accumulated failures to a harness that reads exceptions.

    `check()` records into `FAILURES`, read only by the `__main__` block below. That is how
    CI invokes this file, so its exit code always held -- but under `python3 -m pytest` every
    `test_*` recorded its failures and returned normally, and real reds were reported as
    PASSED. pytest calls this after the module's tests; bare `python3` never calls it.

    Sharpest here of the four: this is the test of `hestia_gate_core.py`, the policy core all
    five harnesses are to consolidate onto. A local pytest run of the gate core's own tests
    could not have told anyone it was broken.

    See `tools/ci_selfexec_test.py::test_no_pytest_blind_files` for the guard that now makes
    the absence of this channel a failure rather than a thing someone has to notice.
    """
    assert not FAILURES, (
        f"{len(FAILURES)} check(s) failed -- see the FAIL lines in captured stdout: {FAILURES}")


if __name__ == "__main__":
    print("hestia_gate_core")
    test_every_test_is_registered()
    test_remedies_name_only_globally_registered_doors()
    test_remedy_text_declares_every_tool_it_names()
    test_unregistered_rule_denies_and_never_raises()
    test_every_literal_deny_rule_is_registered()
    test_egress_offers_no_door()
    test_scope_remedy_distinguishes_itself_from_appeal()
    test_path_and_command_scope()
    test_path_grant_reaches_a_sibling_of_the_repos()
    test_temp_root_is_a_path_boundary_not_a_prefix()
    test_shims_contain_no_policy()
    test_unscoped_must_be_declared_never_inferred()
    test_a_member_cannot_grant_itself_blanket_allow_via_its_own_identity_file()
    test_an_uncertified_replica_is_refused_not_honoured()
    test_a_replica_can_never_widen_to_unscoped()
    test_an_unknown_prefix_is_dropped_and_could_previously_grant()
    test_malformed_vault_payload_fails_closed_instead_of_raising()
    test_prefixed_wildcard_is_not_unscoped()
    test_policy_resolution_names_its_source_and_fails_closed()
    test_gate_unavailability_is_recorded_outside_the_chain()
    test_telemetry_never_raises_on_the_failure_path()
    test_egress_beats_scope()
    test_missing_identity_fails_narrow_not_wide()
    test_core_never_exits()
    test_core_is_vendor_agnostic()
    test_scope_is_decided_after_normalisation_not_before()
    test_path_syntax_is_never_a_scope_name()
    test_the_core_is_not_the_only_copy_of_the_scope_rule()
    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} — {FAILURES}")
        sys.exit(1)
    print("all checks pass")
