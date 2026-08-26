#!/usr/bin/env python3
"""Hestia Phase-1 PreToolUse GATE for a foreign member (Kimi Code) — reference adapter.


This is the membrane — the one hook a Kimi act must transit to have effect. It is FAIL-CLOSED BY
CONSTRUCTION, because Kimi's hook engine fails OPEN on every failure mode (verified from the binary:
timeout / spawn-fail / non-2 exit / exception all -> allow). So a blocking hook must default to
`exit 2` and reach `exit 0` only on an explicit, confirmed allow — never rely on `set -e` or the
engine's default. (This fail-open-on-error behavior is a property of the Claude-Code-lineage hook
engines — Kimi, Codex, Cursor, etc. — and is the single most important fact for anyone writing a
blocking hook for them: the gate itself must be the fail-closed party.)

Three gates, in order (Sprint F reordered: self-protection FIRST, matching the claude
adapter, so a gate-file write is classified as gate-self even when the daemon is down):
  1c. SELF-PROTECTION (local, pre-daemon, ALWAYS enforced): a write-class act whose DESTINATION is
     this plugin's own hook files or the fleet's governance markers is refused and escalated (a
     pre-existing human approval is claimed and spent); reads are allowed and witnessed. Restored
     2026-08-12 after the in-process rewire (PR #372) silently dropped the layer the spawned
     claude gate used to carry — see the marker block below.
  1. SCOPE + EGRESS — the §6.F cutover: decided by the shared core's evaluate() from a policy
     snapshot fetched LIVE from the daemon (hestia_gate_mechanism.fetch_policy_snapshot). When
     the daemon is unreachable in enforce mode the gate takes the RATIFIED DEGRADED MODE
     (deny-writes-allow-reads, computed by the core; every degraded deny recorded with
     verdict_available=False) — never a silent policy=None / local-replica fallback
     (§7.1 criterion 5).
  2. SOCIETY SAFETY (the governor): for write/exec-class tools, delegate to hestia's tested daemon
     caller so the decision reaches the governor and is witnessed. Its deny (or fail-closed-on-
     unreachable) is honored.

A deny is STEERING, not just a block: the stderr reason says why + what to do (adjust in-scope, or
ask via hestia_request_scope). The remedy sentence is rendered from the core's REMEDIES table
(§6.D) — never authored here — so it can only name doors that exist.

Exit codes (Kimi engine contract): 2 = block (stderr = reason); 0 = allow. Default is 2.

Config (all env-overridable; defaults suit a generic install):
  HESTIA_WORKSPACE       root that contains the granted repos      (set explicitly at install)
  HESTIA_SOCIETY_GATE    path to the society-safety gate caller     (default: $WORKSPACE/hestia/plugins/claude-code/hooks/pre_tool_use.py)
  HESTIA_KIMI_IDENTITY   the member's live identity.json            (default: ~/.kimi-code/hestia-instance/identity.json)
  HESTIA_KIMI_GATE_MODE  warn | enforce   (default: enforce — deny-tight, relax as trust accrues)
  HESTIA_FORBIDDEN_EXTRA comma-separated extra forbidden path tokens (e.g. your private repo names)
"""
import json
import os
import re
import sys
import subprocess

def _detect_workspace():
    """Resolve explicit install scope and otherwise fail narrow.

    A public adapter cannot infer an operator's repository names or home layout. An
    installer should set HESTIA_WORKSPACE. A .hestia-workspace marker is the portable
    fallback; without either signal, cwd keeps sibling-repository grants inert.
    """
    env = os.environ.get("HESTIA_WORKSPACE")
    if env and os.path.isdir(env):
        return env
    d = os.getcwd()
    for _ in range(8):
        if os.path.isfile(os.path.join(d, ".hestia-workspace")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return os.getcwd()


WORKSPACE = _detect_workspace()
IDENTITY = os.path.expanduser(
    os.environ.get("HESTIA_KIMI_IDENTITY", "~/.kimi-code/hestia-instance/identity.json"))
# Delegate the society-safety check to hestia's tested daemon caller (the safety preset is global, so
# plugin_id doesn't change its verdict — we set it anyway for when it's parametrized).
CLAUDE_PRE = os.environ.get(
    "HESTIA_SOCIETY_GATE",
    os.path.join(WORKSPACE, "hestia/plugins/claude-code/hooks/pre_tool_use.py"))

# ---- Shared gate core (gate-consolidation PRD §6.C — the consented pilot) -------------
# The hardened scope predicates live ONCE, in the shared core module under
# plugins/_shared/: path-boundary containment (compare at the separator, not
# substring/prefix) and resolve-before-segment traversal (normpath first, containment
# decides). Same sys.path pattern as the Gate 2 mechanism import in main(). GUARDED,
# deliberately: on this engine an import failure IS a fail-open (see the attestation block
# below for the measured class), so a missing/broken core must surface as an explicit
# fail-closed deny inside main() — the `_core is None` check there — never as a
# module-level crash.
# FLEET-CANONICAL SHARED ENGINE (dp, 2026-08-23): "the read should be from fleet generic
# ./hestia not ./claude".
#
# This resolved into the repo WORKING TREE, which means kimi's enforcing gate was whatever
# the checkout happened to be on — measured 2026-08-23, that checkout sat on a branch
# deleted from origin, 62 commits behind main. A gate whose version is decided by someone
# else's `git checkout` is not deployed, it is coincidental. Codex corroborated the same
# shape from its own live registration on 2026-08-24.
#
# `$HESTIA_HOME/shared` is the same path the installer writes and claude-code now reads.
_HESTIA_HOME = os.environ.get("HESTIA_HOME") or os.path.join(
    os.path.expanduser("~"), ".hestia")
_SHARED_DIR = os.environ.get("HESTIA_SHARED_DIR") or os.path.join(_HESTIA_HOME, "shared")
# One-directional fallback: an un-cut-over host keeps its working-tree engine rather than
# losing the closure. On this engine an import failure IS a fail-open (see above), so the
# fallback is the conservative branch, not a convenience.
_LEGACY_SHARED_DIR = os.path.join(WORKSPACE, "hestia", "plugins", "_shared")
if not os.path.isdir(_SHARED_DIR) and os.path.isdir(_LEGACY_SHARED_DIR):
    _SHARED_DIR = _LEGACY_SHARED_DIR
if _SHARED_DIR not in sys.path:
    sys.path.insert(0, _SHARED_DIR)
try:
    import hestia_gate_core as _core
except Exception:
    _core = None
# Sprint B (gate-consolidation §6.B): the shared governance-closure classifier — ONE
# write-position-keyed, accessor-agnostic predicate for every harness. GUARDED like the
# core above: on this engine an import failure IS a fail-open, so a missing module must
# not disarm Gate 1c — the Tier-2 fallback (_fallback_touches_self below, the pre-B local
# predicate, moved not deleted) stays in force when this is None.
try:
    from hestia_governance_closure import classify as _closure_classify
except Exception:
    _closure_classify = None

# ---- Sprint D (§6.D) -> Sprint F (§6.F): law lives in the core; the shim only renders ----
#
# The legacy trio — `load_in_scope` (permissive `["web4"]`-on-any-failure fallback),
# `_identity_role`, `launch_cwd_repo` — is DELETED, not shared. Sprint F completes the
# cutover: standing scope, egress, and command/path scoping are ALL decided inside the
# core's evaluate(), from a policy snapshot fetched LIVE from the daemon (the mechanism's
# fetch_policy_snapshot) — or by the core's ratified degraded_verdict when the daemon is
# unreachable. The only bridge left shim-side is _role_bridge (attribution only), fed from
# the snapshot when the daemon answers. READ_CLASS stays core-sourced (§7.1(1)).


def path_targets(tool_input):
    out = []
    if isinstance(tool_input, dict):
        # NOTE: "pattern" (Glob/Grep) is deliberately NOT here — it is a matcher
        # ('*.md', a regex), not a filesystem reach; the "path" key carries the
        # location. Checking the pattern as a path false-denied every Glob whose
        # pattern didn't look like a granted repo (Kimi live, 2026-07-23).
        for k in ("path", "file_path", "notebook_path"):
            v = tool_input.get(k)
            if isinstance(v, str):
                out.append(v)
    return out


def command_of(tool_input):
    if isinstance(tool_input, dict):
        c = tool_input.get("command")
        if isinstance(c, str):
            return c
    return None


# The core's predicates are parameterized by a HarnessProfile; kimi's harness facts live
# here ONCE (identity location + home marker — of these only home_markers moves a scope
# verdict). Built at import so a broken core is caught by the one `_core is None` check in
# main() rather than per call.
_CORE_PROFILE = (_core.HarnessProfile(
    member_id="kimi-code",
    identity_path=IDENTITY,
    home_markers=("~/.kimi-code",),
    launch_cwd_env="HESTIA_KIMI_LAUNCH_CWD",
) if _core is not None else None)

# Read-class — ONE list, in the core (§7.1(1)). Inert placeholder when the core is
# missing: main() fails closed on `_core is None` before it is consulted, and an empty
# READ_CLASS reads as "everything is write-class", which is the tighter direction.
# (FORBIDDEN has no shim-side copy at all since the F cutover — Gate 1a runs inside
# evaluate()/degraded_verdict.)
READ_CLASS = _core.READ_CLASS if _core is not None else frozenset()


# ── Sprint F (§6.F): _agent_scopes deleted — standing scope now arrives inside
# evaluate()'s policy argument, resolved from the LIVE daemon snapshot in main(); nothing
# shim-side computes scope any more.
# SPRINT-F: replace with certified snapshot — PARTIAL: the daemon exposes NO standing
# `in_scope` surface (only live path grants via hestia_scope_status), so a snapshot
# carries live grants plus the core's launch-cwd bridge and nothing else. Declared RED in
# F_NOTES.md; the local replica is OFF the enforce path entirely (§7.1 criterion 5).


_SNAPSHOT_ROLE = None  # set by main() from the live daemon snapshot (identity.role)


def _role_bridge():
    """Attribution-only: the role string that witnesses/connects carry. Never used to widen
    reach. Sprint F: RESOLVED from the live snapshot when the daemon answered — the
    daemon's session-resolved role (hestia_operating_law identity.role) wins over the
    member-writable identity.json; the file read remains ONLY as the daemon-absent
    fallback for witness attribution, where the alternative is silently changing the
    witness grain mid-train.
    # SPRINT-F: replace with certified snapshot — PARTIAL: resolved when the daemon
    # answers; the identity.json fallback stays for the unreachable case (F_NOTES.md)."""
    if isinstance(_SNAPSHOT_ROLE, str) and _SNAPSHOT_ROLE.startswith("role:"):
        return _SNAPSHOT_ROLE
    try:
        r = json.load(open(IDENTITY, encoding="utf-8")).get("role")
        if isinstance(r, str) and r.startswith("role:"):
            return r
    except Exception:
        pass
    return "role:constellation:member"


# ── Sprint F (§6.F): _launch_scope_bridge deleted — the per-launch cwd grant is computed
# inside evaluate() (the core's marked launch_cwd_repo bridge, parameterised by
# HarnessProfile.launch_cwd_env below), so the shim no longer holds a scope computation.
# The grant itself is still env/cwd-derived pending a daemon surface:
# SPRINT-F: replace with certified snapshot (explicit launch-cwd grant) — the daemon has
# no such surface yet; the core-side bridge stays, declared RED in F_NOTES.md.


def path_in_scope(path, scopes, cwd=None):
    """Call-site adapter to the core's hardened predicate (shim adapts to law, never law to
    shim): supplies WORKSPACE and this harness's profile, keeps the local call shape. The
    hardened semantics — home/tmp/workspace judged by PATH BOUNDARY, every spelling
    normalised BEFORE a segment is read — now come from the one shared implementation."""
    return _core.path_in_scope(path, scopes, WORKSPACE, _CORE_PROFILE, cwd)


def command_in_scope(cmd, scopes, cwd=None):
    """Call-site adapter to the core's hardened predicate. Same (ok, offending_token)
    contract as the deleted local copy; the hardened semantics — every workspace token
    RESOLVED (normpath) before a segment is read off it, traversal out of the workspace
    denied at the boundary — now come from the one shared implementation, along with the
    existence-voting pass for relative tokens and the member-address carve-out."""
    return _core.command_in_scope(cmd, scopes, WORKSPACE, cwd)


# Rollout mode: DENY-TIGHT by default (dp 2026-07-21) — a foreign agent starts enforced and RELAXES
# as role-scoped trust accrues (defensive trust: start at zero, earn the widening). `enforce` blocks
# out-of-scope/unsafe acts; `warn` (opt-in, for a fresh integration's audit shakedown) surfaces the
# verdict but allows. Egress/secret is `innate` — always blocks regardless of mode. Set warn via
# HESTIA_KIMI_GATE_MODE=warn only while shaking down new plumbing.
MODE = os.environ.get("HESTIA_KIMI_GATE_MODE", "enforce").lower()


_EVENT = {}  # set by main() so deny() can witness the reach it blocks


# ---- Scope attestation: report the ALLOWS too, not only the denies ------------------
#
# This gate decides locally, so the daemon never sees what it PERMITS — only what it
# blocks. That made every plugin-gated member permanently unmeasurable: trust could be
# earned only by being denied and complying, or by peer adjudication, so quiet in-scope
# competence produced no evidence at all. kimi-code/member sat at `unmeasured` on 2,214
# actions and 99.5% success while its sibling grain read `high` off 25 denials
# (dp, 2026-07-26: "why is it unmeasured?").
#
# The window is the unit, not the action: one attestation per SCOPE_ATTEST_EVERY
# decisions, so a landslide of trivial in-scope calls cannot farm trust. One extra MCP
# call per 200 tool calls — the per-call hot path is untouched, which was the original
# reason allows went unreported.
#
# `attested_by` names THIS gate rather than claiming to be the daemon. A plugin-gate
# attestation is computed in the member's own process and is forgeable in principle; it
# is admissible because we already trust this same gate to report its denies honestly,
# and a member that could forge allows could equally suppress denies. Same trust level,
# named honestly so a reader can weight it.
# This gate's ONE identity. Previously spelled as a bare literal at each witness
# site; naming it once stops the two from drifting (codex spent days reporting as
# both "codex" and "codex-cli" for exactly that reason).
HESTIA_PLUGIN_ID = os.environ.get("HESTIA_PLUGIN_ID", "kimi-code")
SCOPE_ATTEST_EVERY = 200
# Self-contained: this gate has no OBSERVE_DIR of its own, and the first cut of this
# patch borrowed that name from the CODEX gate — a module-level NameError that would have
# made the whole gate fail to import. On a Claude-lineage engine an import failure IS a
# fail-open, so it would have silently removed this member's governance while it worked.
# Caught pre-flight only because the patched file was executed before being deployed.
_TALLY_DIR = os.path.expanduser(
    os.environ.get("HESTIA_OBSERVE_DIR", "~/.kimi-code/hestia-observe"))
_TALLY = os.path.join(_TALLY_DIR, "scope-tally.json")


def _tally_scope(allowed: bool):
    """Count this decision; emit an attestation when the window closes."""
    try:
        os.makedirs(_TALLY_DIR, exist_ok=True)
        try:
            t = json.load(open(_TALLY))
        except Exception:
            t = {"allows": 0, "denies": 0}
        t["allows" if allowed else "denies"] += 1
        if t["allows"] + t["denies"] >= SCOPE_ATTEST_EVERY:
            from hestia_gate_mechanism import emit_attestation
            emit_attestation(
                t["allows"], t["denies"],
                plugin_id=HESTIA_PLUGIN_ID, role_lct=_role_bridge())
            t = {"allows": 0, "denies": 0}
        json.dump(t, open(_TALLY, "w"))
    except Exception:
        pass  # accounting must never change a decision



def _attempted_summary(ev, limit=400):
    """The bounded, scrubbed command this gate refused — the WHAT behind the verdict.

    dp, 2026-07-26: denies carried a verdict and no action, so the chain recorded
    permitted work verbatim and blocked work not at all — backwards for the entries most
    worth reviewing. Kimi's own `'$d' is not granted` denial was only diagnosable because
    the offending token happened to be quoted into the reason string.

    Keeps the REDACTED-receipt intent (never ship an unbounded payload to a
    less-protected surface) by bounding here and masking credential-shaped values. The
    daemon scrubs and clamps again on receipt; neither side trusts the other to have.
    """
    ti = ev.get("tool_input") or {}
    raw = ti.get("command") or ti.get("file_path") or ti.get("path") or ""
    if not raw and ti:
        try:
            raw = json.dumps(ti, sort_keys=True, default=str)
        except Exception:
            raw = str(ti)
    raw = " ".join(str(raw).split())
    KEYS = ("password","passwd","secret","token","api_key","apikey","api-key","auth",
            "authorization","bearer","credential","private_key","passphrase",
            "access_key","client_secret")
    out, mask_next = [], False
    for tok in raw.split(" "):
        low = tok.lstrip("-").rstrip(":").lower()
        if mask_next and not tok.startswith("-"):
            out.append("***"); mask_next = False; continue
        if "=" in tok:
            k, _, _ = tok.partition("=")
            if any(s in k.lstrip("-").lower() for s in KEYS):
                out.append(k + "=***"); mask_next = False; continue
        mask_next = low in KEYS
        out.append(tok)
    s = " ".join(out)
    return s[:limit] + ("…[truncated]" if len(s) > limit else "")


# ── REPAIR 4 (GPT fleet-review blocker 4): ONE deny recorder, literally. ──────────────
# The private `_daemon_witness` client this gate carried (its own initialize/connect/
# witness round-trip with its own timeouts and its own argument shape) is DELETED — every
# refusal seam in this shim now routes through the shared mechanism's
# witness_decision_unified: same record shape, always carrying target +
# verdict_available (real rule-based deny = True; infra/degraded/internal = False), never
# raising, never changing the decision, and falling back to the per-shim diagnostic log
# when the daemon is unreachable (criterion 9(c)). stderr rendering is unchanged at every
# seam.
def _record_refusal(decision, rule, verdict_available, event=None, attempted=None):
    """Best-effort: route ONE refusal record through the unified recorder. `event` defaults
    to the module _EVENT (set by main()); a failure here never changes the decision."""
    ev = event if event is not None else _EVENT
    try:
        if _SHARED_DIR not in sys.path:
            sys.path.insert(0, _SHARED_DIR)
        from hestia_gate_mechanism import witness_decision_unified, _extract_target
        tool = ev.get("tool_name") or "?"
        witness_decision_unified(
            None, plugin_id=HESTIA_PLUGIN_ID,
            decision=decision,
            rule=rule,
            tool_name=tool,
            target=_extract_target(ev.get("tool_input") or {}, tool),
            session_id=ev.get("session_id"),
            verdict_available=verdict_available,
            attempted_summary=attempted if attempted is not None else _attempted_summary(ev))
    except Exception:
        pass  # recording must never turn a deny into a crash (this engine fails open)


def deny(rule, reason, innate=False):
    """Takes a RULE ID, not a sentence (§6.D): the remedy is rendered from the core's one
    REMEDIES table via _deny(rule), never authored at a call site — which is what makes a
    refusal naming a door nobody built (the request_scope phantom) unwriteable here rather
    than merely discouraged. innate=True -> ALWAYS blocks (egress/secret is irreversible: a
    leaked read has no undo, so it is enforced even in warn-rollout). Tunable scope rules
    honor MODE: warn surfaces + allows, enforce blocks."""
    _tally_scope(False)   # a denied reach still closes part of the window
    v = _core._deny(rule, reason, innate=innate)
    verb = "deny" if (v.innate or MODE == "enforce") else "warn"
    sys.stderr.write(
        f"hestia: {verb} [scope] — {v.reason}. This is a boundary, not a failure: don't re-run the same "
        f"call. {v.remedy} Asking is a trust-building act; reaching is witnessed.\n")
    # REPAIR 4: the evaluate-path refusal rides the ONE deny recorder (it previously used
    # this shim's private client, with a different record shape and no target). A real
    # rule-based verdict is CONDUCT: verdict_available=True.
    _record_refusal(verb, v.rule or v.reason, True)
    if v.innate or MODE == "enforce":
        sys.exit(2)
    # warn mode, tunable rule: surfaced but allowed — return so evaluation continues to allow.


# ---- Gate 1c: LOCAL SELF-PROTECTION (the governance surface) -------------------------
#
# Restored 2026-08-12 (PR #372 blocking note, remedy option (a), with operator approval). Before
# a7cfb6c this gate reached the society verdict by SPAWNING the claude gate, whose main() runs a
# local self-touch layer "before the daemon, and never conditional on it" — so a kimi act at the
# governance surface was classified locally and its deny/escalation propagated through
# returncode != 0. The in-process rewire dropped that layer silently: query_society_safety is
# pure daemon transport with no local classification, and the daemon holds no gate-self RULE —
# it knows gate_self_access only as an appealable RECORD the harness gate mints. Net hole: under
# the default enforce mode, kimi could edit its own hook files with only the daemon's global
# destructive/secret preset in the way and no escalation minted. This block is the layer,
# restored in-process.
#
# Scope is deliberately option (a), tight: PATH/realpath match on the destination keys only.
# Disclosed limit: a Bash command that writes the gate names its destination in the command TEXT,
# which this does not scan — raw text scanning is where the FP8/heredoc complexity lives (the
# claude gate carries ~200 lines of heredoc-blanking for it). Bash writes to the surface keep the
# daemon's global preset behind them until option (b) extracts the shared predicate into
# plugins/_shared/ (gate-consolidation PRD f0fd025).

# Marker set mirrors the claude gate's _SELF_MARKERS/_GOVERNANCE_FILES at a7cfb6c: this plugin's
# own hook directory, the fleet's hook directories, and the governance filenames. A filename
# matched ANYWHERE governs a peer's copy too — editing another member's gate is not a lesser act.
# Common filenames govern only under a hooks/ path (they appear in vendor trees and docs); the
# distinctive names govern wherever they live. Adding a name STRENGTHENS the gate; moving one
# into _SELF_HOOKS_DIR_ONLY weakens it — that direction is the visible, deliberate second edit.
_SELF_DIR_MARKERS = ("plugins/kimi/hooks", "plugins/claude-code/hooks", "hestia/hooks",
                     # GPT 2nd pass: Tier-2 mirrors the CANONICAL closure, not the pre-B set
                     "plugins/_shared", "hub/target/release")
_SELF_GOVERNANCE_FILES = (
    "pre_tool_use.py", "society_pre_tool_use.py", "post_tool_use.py", "witness.py",
    "law_inject.py", "hestia_gate_core.py", "hestia_gate_mechanism.py",
    "gate_self_protection_test.py",
    # GPT 2nd pass: canonical-closure names the pre-B tuple lacked
    "hestia_governance_closure.py", "web4-hub.service", "ratified-build.json",
    "ratify-build.sh", "install-members.sh",
)
_SELF_HOOKS_DIR_ONLY = ("pre_tool_use.py", "society_pre_tool_use.py", "post_tool_use.py",
                        "witness.py", "law_inject.py")


def _fallback_touches_self(tool_input):  # Tier-2 fallback; live path is classify()
    """(marker, resource) if this call's DESTINATION reaches the governance surface, else None.

    Two haystacks:
      * destination PATH keys (`file_path`/`path`/`notebook_path`) — matched raw AND realpath'd,
        so `../hooks/...` and a symlinked alias resolve to the same file;
      * the Bash `command` and Edit `new_string` TEXT — matched raw. A shell write names its
        destination in the command text (`> <gate>`, `cp x <gate>`, `sed -i <gate>`, `tee <gate>`),
        and the pre-a7cfb6c path — which spawned the claude gate — scanned it. Dropping that scan
        (PR #372) let a Bash write to the surface pass with only the daemon preset behind it; this
        restores parity (GPT #372 review, hold #2).

    NO-REGRESSION BRIDGE, stated honestly: the text is matched RAW, without the claude gate's
    heredoc-blanking. Raw over-matches a command that merely NAMES a marker (the marker-in-command
    FP) — a spurious refusal, which costs a rephrase, not a security hole. The correct fix — parse
    the actual write TARGET, and blank inert heredoc bodies — is #370's shared governance-access
    predicate, which both gates will call. `content` STAYS OUT of the haystack: a Write's payload
    is not its destination (the FP8 document-about-the-gate class — eight recorded instances on the
    claude gate). `resource` is the matched string — the escalation record is a human's entire
    basis for approving, so it names the ACT, with the marker as the REASON."""
    if not isinstance(tool_input, dict):
        return None

    def _match(text, realpath_ok):
        cands = [text]
        if realpath_ok:
            try:
                rp = os.path.realpath(text)
                if rp != text:
                    cands.append(rp)
            except (OSError, ValueError):
                pass
        for cand in cands:
            low = cand.replace("\\", "/")
            for d in _SELF_DIR_MARKERS:
                if d in low:
                    return (d, cand)
            in_hooks = "hooks/" in low
            for fname in _SELF_GOVERNANCE_FILES:
                if fname in low and (fname not in _SELF_HOOKS_DIR_ONLY or in_hooks):
                    return (fname, cand)
        return None

    # Destination PATHS: raw + realpath'd.
    for key in ("file_path", "path", "notebook_path"):
        v = tool_input.get(key)
        if isinstance(v, str) and v:
            hit = _match(v, realpath_ok=True)
            if hit:
                return hit
    # Bash command + Edit new_string: destination lives IN the text; matched raw (realpath is
    # meaningless on a command/replacement string).
    for key in ("command", "new_string"):
        v = tool_input.get(key)
        if isinstance(v, str) and v:
            hit = _match(v, realpath_ok=False)
            if hit:
                return hit
    return None


def _gate_self_call(tool, args, host_session_id=None):
    """One short daemon round trip for a gate-self event: initialize, connect (session-bound),
    one tools/call. Returns the unwrapped result dict, or None on ANY failure.

    Never raises and stays inside a ~2.5s budget: the harness kills this hook at 5s, and a killed
    hook yields neither exit 2 nor a JSON deny — the engine reads it as a non-blocking error and
    runs the tool anyway. A gate-self exchange that hangs therefore fails OPEN, which is strictly
    worse than a refusal. Callers treat None as refusal (writes) or best-effort loss (witnesses).

    `host_session_id`, when the caller has one, is threaded into the connect so the gate-self
    session this call mints joins to the per-wake session the outcome rows carry (same join the
    main daemon path makes at the Gate 2 call below).
    """
    import urllib.request
    endpoint = os.environ.get("HESTIA_ENDPOINT", "http://127.0.0.1:7711/mcp")

    def post(payload, hdrs, timeout):
        req = urllib.request.Request(
            endpoint, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json",
                     "Accept": "application/json, text/event-stream", **hdrs})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(), r.headers.get("mcp-session-id")

    def unwrap(raw):
        """The result payload of a tools/call: structuredContent, or the content[0] text JSON —
        and the body may be plain JSON or SSE-framed (`data: {...}` lines)."""
        for line in raw.decode("utf-8", "replace").splitlines():
            line = line.strip()
            if not (line.startswith("{") or line.startswith("data: {")):
                continue
            try:
                pl = json.loads(line[line.index("{"):])
            except Exception:
                continue
            res = pl.get("result")
            if not isinstance(res, dict):
                continue
            sc = res.get("structuredContent")
            if isinstance(sc, dict):
                return sc
            content = res.get("content") or []
            if content and isinstance(content[0], dict):
                try:
                    d = json.loads(content[0].get("text") or "{}")
                    return d if isinstance(d, dict) else None
                except Exception:
                    return None
        return None

    try:
        _, sid_hdr = post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                           "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                                      "clientInfo": {"name": "hestia-kimi-gate-self",
                                                     "version": "1"}}}, {}, 0.8)
        h = {"mcp-session-id": sid_hdr} if sid_hdr else {}
        post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}, h, 0.4)
        connect_args = {"plugin_id": HESTIA_PLUGIN_ID,
                        "host_agent": HESTIA_PLUGIN_ID,
                        "role": _role_bridge(),
                        "instance_name": "gate-self"}
        if host_session_id:
            connect_args["host_session_id"] = host_session_id
        raw, _ = post({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                       "params": {"name": "hestia_connect",
                                  "arguments": connect_args}}, h, 0.8)
        conn = unwrap(raw)
        sess = conn.get("sessionId") if conn else None
        if not sess:
            return None  # an unconnected witness/claim is refused by the daemon anyway
        args = dict(args)
        args.setdefault("session_id", sess)
        raw, _ = post({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                       "params": {"name": tool, "arguments": args}}, h, 0.9)
        return unwrap(raw)
    except Exception:
        return None


def _witness_gate_self(event_type, marker, tool_name, rule=None):
    """Record a governance-surface event as its OWN class — `gate_self_read` for a permitted
    read, `gate_self_access` (appealable) for a refused write. The two stay distinct so an alert
    on the refusal keeps its meaning. Best effort: a failed record never changes the decision —
    the daemon's health is not a precondition for reading one's own law, and the deny already
    happened locally."""
    return _gate_self_call("hestia_request_witness", {
        "event_type": event_type,
        "event_data": {"plugin_id": HESTIA_PLUGIN_ID,
                       "tool_name": tool_name,
                       "marker": marker,
                       "rule": rule,
                       "gate_path": os.path.abspath(__file__),
                       "severity": "record" if event_type == "gate_self_read" else "escalate",
                       "role_lct": _role_bridge()}},
        host_session_id=_EVENT.get("session_id")) is not None


def _claim_self_write(marker, tool_name, attempted):
    """Ask ONCE whether a human has already approved this exact (member, marker) write.
    Returns (verdict, detail, escalation_id, how_to_decide); only 'approved' permits.

    Mirrored from the claude gate's request_self_write: never waits. The first attempt is refused
    and the refusal opens an escalation; a human decides out of band; the member RE-ISSUES the
    write and the second attempt claims the approval. Every failure — unreachable, malformed, a
    daemon with no escalation channel — is a refusal: a daemon that cannot answer must not be a
    way to get a governance write through."""
    claim_args = {
        "plugin_id": HESTIA_PLUGIN_ID,
        "role": _role_bridge(),
        "tool_name": tool_name,
        "marker": marker,
        # `reason` carries the ATTEMPTED ACT, not a rationale: an auto-opened escalation HAS no
        # stated why — the member did not choose to escalate; the gate opened it on a refused
        # write. Presenting the act as though it were a rationale would look like the member had
        # explained itself. A member that wants to state a why opens the escalation itself.
        "reason": attempted or f"{tool_name} -> {marker}",
        "detail": ("Auto-opened by the gate on a refused write; the member stated no rationale "
                   "because it did not choose to escalate. Approving authorises this one write."),
    }
    # The claimed-row join key (reply-2005/reply-2006, 2026-08-12): of the three session-id
    # namespaces in a claim window, only the per-wake host session appears on the outcome rows
    # an auditor joins from — the gate-self connect session above joins only to gate witnesses.
    # Sent only when in hand: the daemon writes explicit null, and a fabricated placeholder
    # would be a lie in the exact record used to argue about who authorised what.
    host_session_id = _EVENT.get("session_id")
    if host_session_id:
        claim_args["host_session_id"] = host_session_id
    r = _gate_self_call("hestia_gate_escalation_claim", claim_args,
                        host_session_id=host_session_id)
    if not isinstance(r, dict):
        return "unreachable", "no answer from the daemon — refused", None, None
    # BOTH flags, and the daemon owns both — two places deciding what "approved" means is how
    # they come to disagree, so the hook re-derives nothing.
    if r.get("claimed") is True and r.get("permits_write") is True:
        who = r.get("decided_by") or "a human"
        via = r.get("decided_via") or "unknown-channel"
        return ("approved",
                f"claimed an approval from {who} via {via} (single use, now spent)", None, None)
    esc_id = r.get("escalation_id")
    if not esc_id:
        # An old daemon answers {} to a tool it does not know — which must not permit a write by
        # failing to understand the question, but also cannot open an escalation. Say which.
        why = r.get("error") or "this daemon has no escalation channel (is it upgraded?)"
        return "no-channel", f"refused, and NO escalation was opened — {why}", None, None
    return ("escalated", "refused; escalation opened for out-of-band decision",
            esc_id, r.get("how_to_decide") or f"hestia gate approve {esc_id}")


def _fail_closed_internal_error(event, exc):
    """REPAIR 1 (GPT fleet-review blocker 2): the WHOLE decision path failed with an
    UNEXPECTED error. On a Claude-lineage engine a hook that raises exits rc=1 and the
    engine reads that as ALLOW — a fail-OPEN. Before this, only stdin parsing was guarded,
    so an exception from closure classification, target extraction, the snapshot fetch, or
    evaluate() escaped and this member failed open. Every such error now lands here.

    This is NOT the ratified degraded posture (deny-writes-allow-reads): a degraded gate
    still KNOWS the act's class; an internally-broken gate does not, so it cannot safely
    allow even a read. In enforce, any unexpected error therefore DENIES (exit 2);
    warn-rollout still only warns (exit 0). The record is best-effort and marks this INFRA,
    never member conduct (verdict_available=False, rule 'gate-internal-error'); the unified
    recorder already guarantees it never raises."""
    detail = f"{type(exc).__name__}: {exc}"
    _record_refusal("deny" if MODE == "enforce" else "warn",
                    "gate-internal-error", False,
                    event=(event or {}), attempted=detail[:200])
    if MODE == "enforce":
        sys.stderr.write(
            "hestia: deny [gate-internal-error] — the gate hit an unexpected internal error "
            f"and cannot decide the act, so it is FAILING CLOSED ({detail}). This is an "
            "infrastructure fault in the gate, not a judgement of your act — please report "
            "it. A gate that cannot decide must not allow.\n")
        sys.exit(2)
    sys.stderr.write(
        "hestia: warn [gate-internal-error] — the gate hit an unexpected internal error "
        f"({detail}); warn-rollout allows, but this would FAIL CLOSED under enforce.\n")
    sys.exit(0)


def main():
    # Fail-closed skeleton: any unexpected error -> deny (never fall through to allow).
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except Exception:
        sys.stderr.write("hestia: deny [gate] — could not parse the tool event; failing closed.\n")
        sys.exit(2)

    if event.get("hook_event_name") != "PreToolUse":
        sys.exit(0)  # not our event

    # REPAIR 1 (GPT fleet-review blocker 2): WHOLE-DECISION-PATH fail-closed boundary.
    # Everything from here down — core guard, closure classification, target
    # extraction, the policy snapshot fetch, evaluate(), and society safety — runs
    # inside ONE outer guard. On a Claude-lineage engine an uncaught exception exits
    # rc=1, which the engine reads as ALLOW (fail-OPEN); before this only stdin parsing
    # was guarded, so a fault in closure classification / target extraction / evaluate()
    # escaped and this member failed open. `except Exception` deliberately does NOT catch
    # SystemExit, so every legitimate allow (exit 0) / deny (exit 2) below passes through
    # untouched — the guard can only ADD a fail-close, never turn an allow into a deny.
    try:
        # TEST-ONLY decision-time fault injector (REPAIR 1 scaffold; INERT without the
        # env var). Raises AFTER all imports have already succeeded, so the boundary can
        # be exercised by a REAL subprocess with the fault at DECISION time, not import
        # time. It fires for every event class (before the read-class skip) so a
        # sabotaged READ fails closed too. Never fires on a normal run.
        if os.environ.get("HESTIA_TEST_SABOTAGE"):
            raise RuntimeError("HESTIA_TEST_SABOTAGE: injected decision-time fault")

        # Tier-2 backstop (gate-consolidation PRD §7.1 criterion 9): Gate 1b's scope predicates
        # now live in the shared core, so a core that failed to import leaves this gate unable
        # to decide scope at all. Letting Gate 1b raise instead would exit 1, which this engine
        # reads as ALLOW — the import-failure fail-open documented at the attestation block.
        # Deny outright, like the parse deny above: this is the gate unable to decide, not a
        # policy verdict, so warn-rollout does not apply. (This TIGHTENS the ratified degraded
        # posture — deny-writes-allow-reads; per-shim tighten-only is explicitly allowed — the
        # rare shim-level import-failure path carries no READ_CLASS carve-out.)
        if _core is None:
            # REPAIR 4: this Tier-2 refusal previously left NO record at all — route it
            # through the ONE deny recorder (best-effort: with the core gone the mechanism
            # may be gone too; the deny stands regardless). Infra posture, never conduct.
            _record_refusal("deny", "gate-core-unavailable", False, event=event,
                            attempted="the shared gate core could not be loaded")
            sys.stderr.write("hestia: deny [gate] — the shared gate core could not be loaded; "
                             "failing closed.\n")
            sys.exit(2)

        _EVENT.clear(); _EVENT.update(event)
        tool = event.get("tool_name") or "?"
        tinput = event.get("tool_input") or {}
        paths = path_targets(tinput)
        cmd = command_of(tinput)

        # Gate 1c runs FIRST now (Sprint F reorder, matching the claude adapter): the
        # governance surface is classified before any policy fetch, so a gate write is refused
        # AS gate-self — with its escalation — even when the daemon is down (a degraded deny
        # would otherwise mask the class). Gates 1a/1b live INSIDE the core's evaluate(), below.

        # Gate 1c — local self-protection. BEFORE the daemon and never conditional on it: if this
        # check needed a verdict, "stop the daemon, then edit the gate" would be the same evasion one
        # layer down. ALWAYS enforced — it does not honor warn-rollout, because a governance write
        # that warns and proceeds is not a boundary.
        # Sprint B: classification comes from the shared governance-closure module (write-
        # position keyed, accessor-agnostic — the raw text-match bridge and its disclosed
        # marker-in-command FP retire with it); this shim only renders and escalates.
        self_rule = None
        if _closure_classify is not None:
            _cv = _closure_classify(tool, tinput, cwd=event.get("cwd"))
            self_hit = ((_cv.marker or _cv.rule, _cv.resource or _cv.marker or _cv.rule)
                        if _cv.classification in ("read", "write") else None)
            self_is_read = _cv.classification == "read"
            self_rule = _cv.rule
        else:
            # Tier-2 degraded mode (ratified): import failed — the pre-B local predicate
            # decides, unchanged. The layer must not silently vanish with the import.
            self_hit = _fallback_touches_self(tinput)
            self_is_read = tool in READ_CLASS
        if self_hit:
            self_marker, self_resource = self_hit
            if self_is_read:
                # Publish-the-law: a member may read what governs it — refusing would make a member
                # unable to check its own law. The read is RECORDED so reconnaissance stays visible
                # as a pattern; a failed witness never blocks the read.
                _witness_gate_self("gate_self_read", self_marker, tool, rule=self_rule)
            else:
                verdict, detail, esc_id, how = _claim_self_write(
                    self_marker, tool, _attempted_summary(_EVENT))
                if verdict != "approved":
                    _witness_gate_self("gate_self_access", self_marker, tool, rule=self_rule)
                    _tally_scope(False)   # a refused reach still closes part of the window
                    esc = (f" Escalation {esc_id} is open — a human decides out of band ({how}); "
                           f"re-issue the write afterwards to claim the approval." if esc_id else "")
                    sys.stderr.write(
                        f"hestia: deny [gate-self] — '{tool}' would WRITE to the governance surface: "
                        f"{self_resource} (matched marker {self_marker!r}; "
                        f"rule {self_rule or 'gate-self-local'}; {detail}).{esc} This is not "
                        f"an ordinary boundary — the target is what draws the boundaries. Legitimate "
                        f"gate work goes through the escalation, not around it.\n")
                    # REPAIR 4: the gate-self refusal previously left only its
                    # hestia_request_witness EVENT (gate_self_access) — no refusal record at
                    # all on the deny feed. ONE unified record, alongside (not instead of)
                    # that event class. A rule-based local verdict is CONDUCT:
                    # verdict_available=True.
                    _record_refusal("deny", self_rule or "gate.self_access", True)
                    sys.exit(2)
                # APPROVED lifts self-protection for THIS call only — the ordinary gates below still
                # run; approving a gate edit is not approving everything else the call might do.
                sys.stderr.write(f"hestia: gate write APPROVED — {detail}\n")

        # ── Sprint F (§6.F): THE decision — core evaluate() from an AUTHENTICATED policy path,
        # or the ratified degraded mode. No silent policy=None / local-replica fallback exists
        # on this path (§7.1 criterion 5): a snapshot is fetched LIVE from the daemon; when
        # that fails in enforce mode the core's degraded_verdict decides
        # (deny-writes-allow-reads), and every degraded deny is recorded with
        # verdict_available=False.
        ev = _core.NormalizedEvent(tool=tool, paths=paths, command=cmd,
                                   cwd=event.get("cwd"), raw=event)
        snapshot = None
        try:
            from hestia_gate_mechanism import fetch_policy_snapshot
            snapshot = fetch_policy_snapshot(HESTIA_PLUGIN_ID, host_agent=HESTIA_PLUGIN_ID,
                                             host_session_id=event.get("session_id"))
        except Exception:
            snapshot = None   # an unimportable mechanism == an unreachable daemon: degrade below
        if snapshot is not None:
            global _SNAPSHOT_ROLE
            _SNAPSHOT_ROLE = snapshot.get("role")
            # The core's seam as built: resolve_agent_policy(vault_reader=...) — the reader
            # returns this member's policy dict; here that dict is the LIVE daemon snapshot,
            # which ALWAYS carries an `in_scope` list, so resolution can never fall through to
            # the local replica on this path.
            # SPRINT-F: replace with certified snapshot — PARTIAL: `in_scope` carries only the
            # daemon's live path grants; standing repo scope has NO daemon surface (RED,
            # F_NOTES.md). The launch-cwd grant rides the core's marked bridge in evaluate().
            policy = _core.resolve_agent_policy(_CORE_PROFILE,
                                                vault_reader=lambda _member: snapshot)
            verdict = _core.evaluate(ev, _CORE_PROFILE, WORKSPACE, policy=policy)
            if verdict.blocks:
                deny(verdict.rule, verdict.reason, innate=verdict.innate)
        elif MODE == "enforce":
            verdict = _core.degraded_verdict(ev, _CORE_PROFILE)
            if verdict.blocks and verdict.innate:
                # The innate egress invariant is a REAL verdict — the transport-free core
                # decided it without the daemon — so it renders and records as conduct.
                deny(verdict.rule, verdict.reason, innate=True)
            elif verdict.blocks:
                _core.record_gate_unavailable(HESTIA_PLUGIN_ID, tool, "unknown",
                                              "degraded: policy snapshot fetch failed (deny)")
                # verdict_available=False routes this through the unified recorder's
                # diagnostic-log fallback (criterion 9(c)) — an infra posture, never
                # member conduct.
                _record_refusal("deny", verdict.rule, False)
                _tally_scope(False)
                sys.stderr.write(
                    f"hestia: deny [degraded] — {verdict.reason}. {verdict.remedy}\n")
                sys.exit(2)
            else:
                # allow-read in degraded mode: recorded on the availability telemetry (an infra
                # series); Gate 2 below is read-class-skipped anyway.
                _core.record_gate_unavailable(HESTIA_PLUGIN_ID, tool, "unknown",
                                              "degraded: policy snapshot fetch failed "
                                              "(allow-read)")
        else:
            # warn-rollout shakedown with the daemon unreachable: evaluate against a policy
            # that grants NOTHING (never the replica), so every boundary surfaces as a warn.
            policy = _core.AgentPolicy(member_id=HESTIA_PLUGIN_ID, scope=(),
                                       source="daemon-unreachable", stale=True)
            verdict = _core.evaluate(ev, _CORE_PROFILE, WORKSPACE, policy=policy)
            if verdict.blocks:
                deny(verdict.rule, verdict.reason, innate=verdict.innate)

        # Gate 2 — society safety (the governor). Read-class already fully covered by the core;
        # only write/exec-class needs the daemon's destructive/secret verdict — reached IN-PROCESS via
        # the shared mechanism (PR #371), NOT by spawning the claude gate as a subprocess off /mnt/c,
        # cold, every call. That subprocess path was the structural cause of kimi's idle-box timeouts
        # (criterion 10): fork + interpreter startup + a 2760-line cold import could not finish inside
        # budget. query_society_safety() never raises and never allows on error; a down/slow daemon or
        # a malformed verdict returns a no-verdict that fails closed here, exactly as the old
        # returncode!=0 path did — but in one lean in-process round-trip, the same one claude makes.
        if tool not in READ_CLASS:
            verdict = None
            try:
                shared = os.path.join(WORKSPACE, "hestia", "plugins", "_shared")
                if shared not in sys.path:
                    sys.path.insert(0, shared)
                from hestia_gate_mechanism import query_society_safety
                verdict = query_society_safety(
                    event, plugin_id="kimi-code", host_agent="kimi-code",
                    host_session_id=event.get("session_id"))
            except Exception:
                # Loading the mechanism must itself fail closed on a consequential act: a missing or
                # unimportable module is not a reason to allow a write on a fail-open harness.
                # REPAIR 4: this refusal previously left NO record — route it (best-effort:
                # if the mechanism is the unimportable thing the record is lost with it, and
                # the deny still stands). Infra posture, never conduct.
                _record_refusal("deny" if MODE == "enforce" else "warn",
                                "society-safety-unavailable", False,
                                attempted="society-safety mechanism could not be loaded")
                if MODE == "enforce":
                    sys.stderr.write("hestia: deny [safety] — the society-safety mechanism could not "
                                     "be loaded; failing closed on a consequential act.\n")
                    sys.exit(2)
                sys.stderr.write("hestia: warn [safety] — society-safety mechanism unavailable "
                                 "(warn-rollout: allowed).\n")
            if verdict is not None and not verdict.allow:  # enforced deny OR no-verdict -> fail closed
                msg = (verdict.message
                       or "hestia: deny [safety] — blocked/inconclusive at the society safety gate.")
                # ONE deny recorder (Sprint E, §3.3 bullet 4): kimi's society refusal previously
                # left no record at all — the chain's denominator differed by harness. The unified
                # recorder always carries target + verdict_available (real deny vs infra
                # fail-close), never raises, and falls back to the per-shim diagnostic log when
                # the witness itself is the unreachable thing (criterion 9(c)).
                _record_refusal("deny" if MODE == "enforce" else "warn",
                                "society-safety", verdict.decided,
                                attempted=(verdict.cause or "")[:200])
                if MODE == "enforce":
                    sys.stderr.write(msg if msg.endswith("\n") else msg + "\n")
                    sys.exit(2)
                sys.stderr.write("hestia: warn [safety] — " + msg.split("— ", 1)[-1] +
                                 " (warn-rollout: allowed; would block under enforce)\n")

        # Count the allow before exiting: this is the gate attesting that the reach was
        # inside the grant, which is the only not-self-reported evidence of competent work
        # the system can get.
        _tally_scope(True)
        sys.exit(0)  # the ONLY allow path — reached only after every gate explicitly passed
    except SystemExit:
        raise  # legitimate allow/deny exits pass through untouched (never a fail-close)
    except Exception as _exc:  # noqa: BLE001 — ANY unexpected error → fail closed
        _fail_closed_internal_error(event, _exc)


if __name__ == "__main__":
    main()
