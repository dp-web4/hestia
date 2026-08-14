#!/usr/bin/env python3
"""Hestia Phase-1 PreToolUse GATE for a foreign member (OpenAI Codex CLI) — reference adapter.

Adapted from the Kimi reference gate. Codex's hook engine is genuine Claude-Code lineage:
same event names (PreToolUse/PostToolUse/SessionStart/SessionEnd/Stop/UserPromptSubmit/...),
same event JSON on stdin (`hook_event_name`, `tool_name`, `tool_input`, `cwd`, `session_id`),
same deny contract (exit code 2 + stderr reason, or a `permissionDecision: "deny"` JSON), and —
verified from OpenAI's hooks docs — it **FAILS OPEN**: a hook that errors, times out, or exits
non-zero "is marked failed... and the tool call continues." So this gate is FAIL-CLOSED BY
CONSTRUCTION: default `exit 2`, reach `exit 0` only on an explicit, confirmed allow.

CODEX-SPECIFIC DESIGN NOTE — READ THIS (verified 2026-07-22 from the codex-rs source).
`PreToolUse` dispatches CENTRALLY and fires for every Function-payload tool: the **shell** tool
(tool_name `"bash"`), **`apply_patch`** (file create/edit/delete), and **MCP** calls
(`mcp__<server>__<tool>`). It does NOT fire for `tool_search`, custom/freeform-grammar tools, or a
server-side `web_search`. So this gate sees shell commands AND file edits AND MCP calls.

Defense-in-depth, because no single layer covers everything on Codex:
  - WRITES to out-of-scope repos: the **sandbox** (`sandbox_mode = "workspace-write"`) structurally
    confines writes to the launch workspace — the boundary string-parsing can't give. apply_patch
    also fires this gate (belt + suspenders).
  - NETWORK egress: the sandbox (`[sandbox_workspace_write] network_access = false`).
  - READS of out-of-scope repos: the sandbox does NOT help (verified: under workspace-write the whole
    FS is ro-bind readable). So read-scope rests on THIS gate's command-scope check for shell reads
    (`cat`/`sed` go through the shell tool) — which catches explicit reaches but NOT relative-recursive
    traversal (`grep -r .` from a broad cwd), the same string-parse limit as the Kimi gate. Mitigation
    is operational: launch Codex in the specific task repo, not the workspace root. A bind-mount /
    container that exposes only granted repos is the real read-confinement fix (future).
This gate is the shell/edit/MCP-command layer: scope + egress + society-safety, fail-closed.

Three gates, in order (Sprint F: self-protection first, then the ONE decision, then society):
  1c. SELF-PROTECTION (Sprint B): a write whose DESTINATION is the governance closure is
     refused and escalated pre-daemon; reads are allowed and witnessed.
  1. SCOPE + EGRESS — the §6.F cutover: decided by the shared core's evaluate() from a policy
     snapshot fetched LIVE from the daemon (hestia_gate_mechanism.fetch_policy_snapshot).
     Daemon unreachable in enforce mode -> the RATIFIED DEGRADED MODE
     (deny-writes-allow-reads, computed by the core; every degraded deny recorded with
     verdict_available=False) — never a silent policy=None / local-replica fallback
     (§7.1 criterion 5).
  2. SOCIETY SAFETY (the governor): for exec-class tools, query the daemon IN-PROCESS via the
     shared mechanism module (plugins/_shared, PRD gate-consolidation §6.E) so the decision
     reaches the governor and is witnessed; its deny (or fail-closed-on-no-verdict) is honored.

Config (all env-overridable; defaults suit a generic install):
  HESTIA_WORKSPACE        root that contains the granted repos       (default: ~/ai-workspace)
  HESTIA_CODEX_IDENTITY   the member's live identity.json             (default: ~/.codex/hestia-instance/identity.json)
  HESTIA_CODEX_GATE_MODE  warn | enforce   (default: enforce — deny-tight, relax as trust accrues)
  HESTIA_CODEX_LAUNCH_CWD launch dir granted for the session          (default: os.getcwd())
  HESTIA_FORBIDDEN_EXTRA  comma-separated extra forbidden path tokens (e.g. your private repo names)
"""
import json
import os
import re
import sys

def _detect_workspace():
    """WORKSPACE resolution that survives a wrong or absent env (2026-07-23, live: a session
    launched before HESTIA_WORKSPACE landed in its hook config ran the gate against the
    default ~/ai-workspace — every real-workspace path then read as 'outside the workspace'
    (deny-everything) and the society-gate script resolved to a nonexistent file. A gate's
    own config must not be able to poison its verdicts). Priority:
      1. HESTIA_WORKSPACE env (explicit wins);
      2. walk up from cwd to a dir that contains >=2 marker repos;
      3. the historical default."""
    env = os.environ.get("HESTIA_WORKSPACE")
    if env and os.path.isdir(env):
        return env
    markers = ("hestia", "shared-context", "web4", "private-context")
    d = os.getcwd()
    for _ in range(8):
        if sum(os.path.isdir(os.path.join(d, m)) for m in markers) >= 2:
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return os.path.expanduser("~/ai-workspace")


WORKSPACE = _detect_workspace()
IDENTITY = os.path.expanduser(
    os.environ.get("HESTIA_CODEX_IDENTITY", "~/.codex/hestia-instance/identity.json"))


def _load_mechanism():
    """Import the SHARED society-safety mechanism (Sprint E — PRD §6.E, one transport).

    HISTORY (why there is no subprocess here). Gate 2 used to spawn the claude-code gate as a
    subprocess (a 2760-line cold import, usually off the 9p /mnt/c mount) with a 2s budget under
    codex's 3s hook clamp. Warm it answered in 194-336ms; cold 9p reads blew the budget, so codex
    was repeatedly blocked with `no policy verdict (daemon path failed)` while the daemon was up
    the whole time (2026-07-26, NRestarts=0). That subprocess spawn was the structural cost
    criterion 10 (§7.4) deletes: the timeout asymmetry cannot close while any harness reaches
    the verdict through a fork + cold interpreter start. The shared mechanism runs the same
    connect/begin/poll protocol IN-PROCESS — the identical lean round-trip claude makes.

    Raises on failure — each CALLER decides the fail posture (Gate 2 fails closed on a
    consequential act; the witness path falls back to the diagnostic log)."""
    for cand in (os.path.join(WORKSPACE, "hestia", "plugins", "_shared"),
                 os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "_shared")):
        if os.path.isdir(cand) and cand not in sys.path:
            sys.path.insert(0, cand)
    import hestia_gate_mechanism
    return hestia_gate_mechanism


# The agent's own home is always in scope (state, identity, config).
CODEX_HOME = os.path.expanduser("~/.codex")


# ---- Gate 1c (Sprint B, gate-consolidation §6.B): governance-closure protection -------
# codex had NO self-protection layer at all (PRD §5). The import below + the Gate 1c
# block in main() add it, mirroring kimi's position (pre-daemon, never conditional on
# it). GUARDED: this engine fails OPEN on a hook error, so a missing/broken module must
# not disarm the layer — _CLOSURE_FLOOR is the Tier-2 fallback (deny writes touching the
# literal floor, allow reads), per the ratified degraded-mode semantics.
for _shared_cand in (
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "_shared"),
    os.path.join(WORKSPACE, "hestia", "plugins", "_shared"),
):
    if os.path.isdir(_shared_cand) and _shared_cand not in sys.path:
        sys.path.insert(0, _shared_cand)
try:
    from hestia_governance_closure import classify as _closure_classify
except Exception:
    _closure_classify = None

# Tier-2 literal floor — consulted ONLY when the classifier is unavailable, as plain
# substrings against destination paths and command text. It over-denies (text mention)
# by design in the degraded mode: the FP costs a rephrase; the hole costs the
# governance model.
_CLOSURE_FLOOR = (
    "plugins/claude-code/hooks", "plugins/kimi/hooks", "plugins/codex/hooks",
    "hestia/hooks", "hestia_gate_core.py", "hestia_gate_mechanism.py",
    "hestia_governance_closure.py", "gate_self_protection_test.py",
    "deploy/install-members.sh", ".claude/settings.json", ".codex/config.toml",
)

# ---- Shared gate core (gate-consolidation PRD §6.D) -----------------------------------
# Sprint D centralizes for this harness: FORBIDDEN / READ_CLASS, the member-address list,
# and the remedy table (deny() renders _deny(rule) from the core's REMEDIES — no sentence
# is authored at a call site). The scope PREDICATES stay LOCAL until the §6.F cutover —
# codex is deliberately pre-hardening until then (GPT 2nd-pass #2). GUARDED, deliberately:
# on this engine an import failure IS a fail-open, so a missing/broken core must surface
# as the explicit fail-closed deny in main() (`_core is None`), never as a module-level
# crash. sys.path already carries _shared via the Gate-1c block above.
try:
    import hestia_gate_core as _core
except Exception:
    _core = None

_CORE_PROFILE = (_core.HarnessProfile(
    member_id="codex",
    identity_path=IDENTITY,
    home_markers=("~/.codex",),
    launch_cwd_env="HESTIA_CODEX_LAUNCH_CWD",
) if _core is not None else None)

# Read-class — ONE list, in the core (§7.1(1)). Inert placeholder when the core is
# missing: main() fails closed on `_core is None` before it is consulted, and an empty
# READ_CLASS reads as "everything is write-class", which is the tighter direction.
# (FORBIDDEN has no shim-side copy at all since the F cutover — Gate 1a runs inside
# evaluate()/degraded_verdict.)
READ_CLASS = _core.READ_CLASS if _core is not None else frozenset()



# ---- Sprint D (§6.D) -> Sprint F (§6.F): law lives in the core; the shim only renders ----
#
# The legacy trio — `load_in_scope` (permissive `["web4"]`-on-any-failure fallback),
# `_identity_role`, `launch_cwd_repo` — is DELETED, not shared. Sprint F completes the
# cutover: standing scope, egress, and command/path scoping are ALL decided inside the
# core's evaluate(), from a policy snapshot fetched LIVE from the daemon (the mechanism's
# fetch_policy_snapshot) — or by the core's ratified degraded_verdict when the daemon is
# unreachable. The only bridge left shim-side is _role_bridge (attribution only), fed from
# the snapshot when the daemon answers. READ_CLASS stays core-sourced (§7.1(1)).

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


def mcp_repo_target(tool_input):
    """An MCP connector call (GitHub et al.) names its repository in its OWN argument and
    carries a REPO-RELATIVE `path`. Scoping that path is a category error: resolved against
    the workspace cwd, its first segment reads as a repo claim, so
    `arc-agi-3/experiments/x.py` INSIDE a granted dev-SAGE was denied as a claim on a repo
    named 'arc-agi-3' (Codex live, 2026-07-26 — it complied and reported rather than routing
    around it via the same connector). Same family as the command-scope false-denies: judge
    by what the argument RESOLVES to, not by what its text mentions.

    Returns the repo name when the input names one, else None."""
    if not isinstance(tool_input, dict):
        return None
    for k in ("repository_full_name", "repo_full_name", "repository", "repo"):
        v = tool_input.get(k)
        if isinstance(v, str) and v.strip():
            # "owner/name" -> "name"; a bare "name" is already the repo.
            return v.strip().rstrip("/").split("/")[-1]
    return None


def command_of(tool_input):
    """Codex passes the shell command under tool_input.command (list or str depending on tool)."""
    if isinstance(tool_input, dict):
        c = tool_input.get("command")
        if isinstance(c, str):
            return c
        if isinstance(c, list):  # Codex shell tool may pass argv as a list
            return " ".join(str(x) for x in c)
    return None


def apply_patch_targets(tool_input):
    """Extract the TARGET file paths from an apply_patch payload (Codex '*** Add|Update|Delete File:
    <path>' format). We scope/egress-check the TARGET path, NOT the patch body — an act that *touches*
    a secret path is not the same as content that *mentions* '.env'/'credentials'. (2026-07-23: Codex's
    hub/hestia security REVIEW was false-denied because the forbidden-token scan hit words in the report
    body, which apply_patch delivers under tool_input.command.) Writing to a real secret path (e.g.
    '*** Add File: ~/.ssh/authorized_keys') is still caught — the target path is what we check."""
    out = []
    if isinstance(tool_input, dict):
        blob = ""
        for k in ("input", "command", "patch"):
            v = tool_input.get(k)
            if isinstance(v, str):
                blob = v
                break
        for m in re.finditer(r'^\*\*\*\s+(?:Add|Update|Delete)\s+File:\s*(.+?)\s*$', blob, re.MULTILINE):
            out.append(m.group(1))
        for k in ("path", "file_path"):        # explicit target keys, if present
            v = tool_input.get(k)
            if isinstance(v, str):
                out.append(v)
    return out


# ── Sprint F (§6.F): the local scope predicates (path_in_scope / command_in_scope /
# _all_repos) are DELETED — codex was deliberately pre-hardening until this cutover
# (GPT 2nd-pass #2); the hardened predicates now reach this gate only through
# core.evaluate(). test_gate_core's duplication inventory shrinks accordingly.


# Rollout mode: DENY-TIGHT by default — a foreign agent starts enforced and RELAXES as role-scoped
# trust accrues (defensive trust: start at zero, earn the widening). Egress/secret is `innate` —
# always blocks regardless of mode. Set warn via HESTIA_CODEX_GATE_MODE=warn only while shaking down.
MODE = os.environ.get("HESTIA_CODEX_GATE_MODE", "enforce").lower()

# Where to witness blocked reaches — the SAME observe log observe.sh appends to, so denies land in the
# one witness stream alongside allows. Default matches observe.sh (~/.codex/hestia-observe).
OBSERVE_DIR = os.path.expanduser(os.environ.get("HESTIA_OBSERVE_DIR", "~/.codex/hestia-observe"))
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
HESTIA_PLUGIN_ID = os.environ.get("HESTIA_PLUGIN_ID", "codex")
SCOPE_ATTEST_EVERY = 200
_TALLY = os.path.join(OBSERVE_DIR, "scope-tally.json")


def _tally_scope(allowed: bool):
    """Count this decision; emit an attestation when the window closes."""
    try:
        os.makedirs(OBSERVE_DIR, exist_ok=True)
        try:
            t = json.load(open(_TALLY))
        except Exception:
            t = {"allows": 0, "denies": 0}
        t["allows" if allowed else "denies"] += 1
        if t["allows"] + t["denies"] >= SCOPE_ATTEST_EVERY:
            _emit_attestation(t["allows"], t["denies"])
            t = {"allows": 0, "denies": 0}
        json.dump(t, open(_TALLY, "w"))
    except Exception:
        pass  # accounting must never change a decision


def _emit_attestation(allows, denies):
    import urllib.request
    endpoint = os.environ.get("HESTIA_ENDPOINT", "http://127.0.0.1:7711/mcp")

    def post(payload, timeout, hdrs=None):
        req = urllib.request.Request(
            endpoint, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json",
                     "Accept": "application/json, text/event-stream", **(hdrs or {})})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(), r.headers.get("mcp-session-id")

    _, sid = post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                   "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                              "clientInfo": {"name": "hestia-gate-attest", "version": "1"}}}, 1.0)
    h = {"mcp-session-id": sid} if sid else {}
    post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}, 0.4, h)
    # `hestia_request_witness` is an ATTRIBUTED append: it refuses an unconnected caller,
    # because what lands on the chain must carry a proven WHO and not only caller-supplied
    # data. Connect first and pass the session, or the attestation is silently refused —
    # which is exactly how the first cut of this failed.
    raw, _ = post({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                   "params": {"name": "hestia_connect",
                              "arguments": {"plugin_id": HESTIA_PLUGIN_ID,
                                            "host_agent": HESTIA_PLUGIN_ID,
                                            # DECLARE THE ROLE ON CONNECT (dp, 2026-07-28:
                                            # "kimi's member alias still shows unmeasured
                                            # with over 3k actions"). This gate has always
                                            # KNOWN its role — it writes `_role_bridge()`
                                            # into the attestation payload below — and never
                                            # told the daemon on connect, so the session
                                            # defaulted to role:constellation:member and the
                                            # attestation landed on a grain the member does
                                            # not act under. Acts on one grain, the decisions
                                            # governing them on another, and NEITHER can score
                                            # conduct. The capability to declare arrived with
                                            # the connect-echoes-role work; this is the caller
                                            # that never started using it.
                                            "role": _role_bridge(),
                                            "instance_name": "gate-attest"}}}, 1.5, h)
    sess = None
    for line in raw.decode("utf-8", "replace").splitlines():
        if line.startswith("data: {"):
            try:
                pl = json.loads(line[6:])
                if "result" in pl:
                    sess = json.loads(pl["result"]["content"][0]["text"]).get("sessionId")
            except Exception:
                pass
    if not sess:
        return
    post({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
          "params": {"name": "hestia_request_witness",
                     "arguments": {"session_id": sess,
                                   "event_type": "scope_attestation",
                                   "event_data": {
                                       "plugin_id": HESTIA_PLUGIN_ID,
                                       "role_lct": _role_bridge(),
                                       "allows": allows,
                                       "denies": denies,
                                       "attested_by": "plugin-gate:" + HESTIA_PLUGIN_ID,
                                   }}}}, 1.5, h)


def _attempted_summary(ev, limit=400):
    """The bounded, scrubbed command this gate refused — the WHAT behind the verdict.

    dp, 2026-07-26: denies carried a verdict and no action, so the chain recorded
    permitted work verbatim and blocked work not at all. That is backwards for the
    entries most worth reviewing: a deny you cannot reconstruct cannot be audited,
    exonerated with confidence, or mined for a false positive. Kimi's `'$d' is not
    granted` denial was only diagnosable because the offending token happened to be
    quoted into the reason string.

    The original REDACTED-receipt rule was right about the risk and wrong about the
    remedy. Keep its intent — never ship an unbounded payload to a less-protected
    surface — by bounding here and masking credential-shaped values. The daemon scrubs
    and clamps again on receipt; neither side trusts the other to have done it.
    """
    ti = ev.get("tool_input") or {}
    raw = ti.get("command") or ti.get("file_path") or ti.get("path") or ""
    if not raw and ti:
        try:
            raw = json.dumps(ti, sort_keys=True, default=str)
        except Exception:
            raw = str(ti)
    raw = " ".join(str(raw).split())          # collapse newlines/heredocs to one line
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
    return s[:limit] + ("\u2026[truncated]" if len(s) > limit else "")


def witness_decision(verb, reason, innate, verdict_available=True):
    """Witness a blocked/warned reach to the observation log. 'Reaching is witnessed' has to INCLUDE
    the reaches we deny — they are the boundary-tests the policy entity most needs (escalation
    triggers, precedent, trust calibration). Denied calls never reach PostToolUse, so observe.sh
    never sees them; this is the only record of a deny. Fail-safe: a log failure never changes the
    decision (the gate still exits 2)."""
    if not verdict_available:
        try:
            shared = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_shared")
            if shared not in sys.path:
                sys.path.insert(0, shared)
            from hestia_gate_core import record_gate_unavailable  # type: ignore
            cause = "timeout" if "timeout" in reason.lower() else "unknown"
            record_gate_unavailable("codex", _EVENT.get("tool_name") or "unknown", cause, reason)
        except Exception:
            pass
    try:
        import datetime, hashlib
        # REDACTED receipt — never copy the rejected payload into this (less-protected) log. A deny
        # fires precisely because the target is sensitive/out-of-scope, so the raw tool_input is the
        # LAST thing to persist here. Keep: the (already-bounded) reason, tool_name, decision, and a
        # correlation hash of the payload — NOT the command/patch body. (Codex review, 2026-07-23.)
        ti = _EVENT.get("tool_input")
        ti_hash = None
        if ti is not None:
            ti_hash = hashlib.sha256(
                json.dumps(ti, sort_keys=True, default=str).encode("utf-8", "replace")).hexdigest()[:16]
        rec = {
            "hook_event_name": "PreToolUse",
            "hestia_decision": verb,          # deny | warn
            "innate": bool(innate),
            "mode": MODE,
            "reason": reason,                 # already bounded (no raw payload)
            "tool_name": _EVENT.get("tool_name"),
            "tool_input_sha256": ti_hash,     # correlate without persisting the (sensitive) payload
            "session_id": _EVENT.get("session_id"),
            "cwd": _EVENT.get("cwd"),
            "plugin": "codex",
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        }
        os.makedirs(OBSERVE_DIR, exist_ok=True)
        with open(os.path.join(OBSERVE_DIR, "observe.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass  # witnessing must never break the gate
    # ALSO report to the daemon's witness chain — via the ONE deny recorder in the shared
    # mechanism (Sprint E, PRD §3.3 bullets 4-6): every harness now writes the same refusal
    # record, ALWAYS carrying `target` (previously no plugin's deny record named what was
    # refused) and `verdict_available` (real deny vs infra fail-close). The recorder never
    # raises and never changes the decision; if the daemon is unreachable it appends the full
    # record to ~/.hestia/telemetry/gate-denies-codex.jsonl (criterion 9(c) fallback witness)
    # instead of dropping it. The local observe log above stays: it is codex's own telemetry,
    # not the society's refusal record.
    try:
        m = _load_mechanism()
        ev_tool = _EVENT.get("tool_name") or ""
        delivered = m.witness_decision_unified(
            None,
            plugin_id="codex",   # ONE member, one identity — `codex` holds the scope grant
            decision=verb,
            rule=reason,
            tool_name=ev_tool,
            target=m._extract_target(_EVENT.get("tool_input"), ev_tool),
            session_id=_EVENT.get("session_id"),
            verdict_available=verdict_available,
            attempted_summary=_attempted_summary(_EVENT),
        )
        if not delivered:
            sys.stderr.write("hestia: WARNING - deny receipt not delivered to daemon; "
                             "recorded to the fallback deny log instead.\n")
    except Exception as e:
        # Still fail-safe: the deny stands regardless (the caller exits 2 either way).
        # But no longer SILENT — an import failure here must not drop the receipt invisibly.
        try:
            sys.stderr.write("hestia: WARNING - deny receipt not delivered to daemon: "
                             f"{type(e).__name__}: {e}\n")
            with open(os.path.join(OBSERVE_DIR, "observe.jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps({"hook_event_name": "PreToolUse",
                                    "hestia_decision": verb,
                                    "witness_delivery_failed": f"{type(e).__name__}: {e}",
                                    "plugin": "codex"}) + "\n")
        except Exception:
            pass


def deny(rule, reason, innate=False):
    """Takes a RULE ID, not a sentence (§6.D): the remedy is rendered from the core's one
    REMEDIES table via _deny(rule), never authored at a call site — which is what makes a
    refusal naming a door nobody built (the request_scope phantom) unwriteable here rather
    than merely discouraged. innate=True -> ALWAYS blocks (egress/secret is irreversible).
    Tunable rules honor MODE."""
    _tally_scope(False)   # a denied reach still closes part of the window
    v = _core._deny(rule, reason, innate=innate)
    verb = "deny" if (v.innate or MODE == "enforce") else "warn"
    witness_decision(verb, v.reason, v.innate)   # a blocked reach is witnessed, not just shown to the agent
    sys.stderr.write(
        f"hestia: {verb} [scope] — {v.reason}. This is a boundary, not a failure: don't re-run the same "
        f"call. {v.remedy} Asking is a trust-building act; reaching is witnessed.\n")
    if v.innate or MODE == "enforce":
        sys.exit(2)


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
    tool = (event or {}).get("tool_name") or "?"
    tinput = (event or {}).get("tool_input") or {}
    detail = f"{type(exc).__name__}: {exc}"
    try:
        m = _load_mechanism()
        m.witness_decision_unified(
            None, plugin_id="codex",
            decision="deny" if MODE == "enforce" else "warn",
            rule="gate-internal-error", tool_name=tool,
            target=m._extract_target(tinput, tool),
            session_id=(event or {}).get("session_id"),
            verdict_available=False,   # infra posture — never member conduct
            attempted_summary=detail[:200])
    except Exception:
        pass  # recording must never turn a fail-close into a crash (this engine fails open)
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

        # Tier-2 backstop (gate-consolidation PRD §7.1 criterion 9): FORBIDDEN/READ_CLASS, the
        # member-address list, scope resolution and the remedy table now live in the shared
        # core, so a core that failed to import leaves this gate unable to decide. Letting it
        # raise instead would be read by this engine as ALLOW (it fails open on hook error).
        # Deny outright, like the parse deny above: this is the gate unable to decide, not a
        # policy verdict, so warn-rollout does not apply. (This TIGHTENS the ratified degraded
        # posture — deny-writes-allow-reads; per-shim tighten-only is explicitly allowed.)
        if _core is None:
            sys.stderr.write("hestia: deny [gate] — the shared gate core could not be loaded; "
                             "failing closed.\n")
            sys.exit(2)

        _EVENT.clear(); _EVENT.update(event)   # so deny()/witness_decision can record the reach it blocks
        tool = event.get("tool_name") or "?"
        tinput = event.get("tool_input") or {}
        if tool == "apply_patch":
            # apply_patch's payload is FILE CONTENT, not a shell command. The TARGET paths are
            # what evaluate() scopes/egress-checks; the patch body is never scanned for
            # forbidden tokens (else a security review that mentions '.env'/'credentials' is
            # false-denied — Codex, 2026-07-23). The sandbox confines the write.
            paths = apply_patch_targets(tinput)
            cmd = None
        else:
            paths = path_targets(tinput)
            cmd = command_of(tinput)
        # An MCP connector call names its repository in its OWN argument; evaluate() scopes
        # that NAME (NormalizedEvent.repos) and treats the call's repo-relative `path` keys as
        # content, not a reach (mcp_repo_target docstring — the 2026-07-26 false-deny class).
        mcp_repo = mcp_repo_target(tinput)

        # Gate 1c runs FIRST now (Sprint F reorder, matching kimi and the claude adapter): the
        # governance surface is classified before any policy fetch, so a gate write is refused
        # AS gate-self even when the daemon is down. Gates 1a/1b live INSIDE evaluate(), below.

        # Gate 1c — LOCAL SELF-PROTECTION (the governance closure; Sprint B, §6.B). BEFORE
        # the daemon and never conditional on it, mirroring kimi's position: if this check
        # needed a verdict, "stop the daemon, then edit the gate" would be the same evasion
        # one layer down. ALWAYS enforced (innate — not subject to warn-rollout): a
        # governance write that warns and proceeds is not a boundary. Refuse-and-witness is
        # strictly better than the previous nothing; the escalate/claim flow arrives with
        # the shared mechanism (§6.E).
        if _closure_classify is not None:
            if tool == "apply_patch":
                # CALL-SITE ADAPTATION (the module stays codex-agnostic): apply_patch's
                # targets live in the patch body and were already extracted above
                # (destination, not content — the same judge-the-target rule as Gate
                # 1a/1b). Each extracted path is classified as a Write destination.
                _cv = None
                for _p in paths:
                    _c = _closure_classify("Write", {"file_path": _p}, cwd=event.get("cwd"))
                    if _c.classification == "write":
                        _cv = _c
                        break
                    if _c.classification == "read" and _cv is None:
                        _cv = _c
            elif tool in ("bash", "shell", "Bash", "Shell"):
                # CALL-SITE ADAPTATION: codex's shell tool is named "bash" and may pass
                # argv as a LIST; the module's Bash arm wants the joined string under
                # "command" (command_of above already joined it).
                _tin = tinput if isinstance(tinput.get("command"), str) else dict(
                    tinput, command=cmd or "")
                _cv = _closure_classify("Bash", _tin, cwd=event.get("cwd"))
            else:
                _cv = _closure_classify(tool, tinput, cwd=event.get("cwd"))
            if _cv is not None and _cv.classification == "read":
                # Publish-the-law: reads pass and are witnessed (existing witness path; a
                # witness failure never changes the decision).
                witness_decision("gate_self_read",
                                 f"read of governance surface: {_cv.resource or _cv.marker}",
                                 False)
            elif _cv is not None and _cv.classification == "write":
                witness_decision("gate_self_access",
                                 f"{tool} -> {_cv.resource} [rule {_cv.rule}]", True)
                deny(f"'{tool}' would WRITE to the governance surface [gate-self]: "
                     f"{_cv.resource} (matched {_cv.marker!r}, rule {_cv.rule})",
                     "Legitimate gate work goes through escalation — a human approves out "
                     "of band — not around it.", innate=True)
        elif tool not in READ_CLASS:
            # Tier-2 degraded mode (ratified deny-writes-allow-reads): the classifier
            # failed to import — deny write-class acts that touch the literal floor. This
            # engine fails OPEN on hook errors, so the layer must not vanish with the
            # import.
            _floor_hit = None
            for _blob in paths + ([cmd] if cmd else []):
                _low = str(_blob).replace("\\", "/")
                _floor_hit = next((_t for _t in _CLOSURE_FLOOR if _t in _low), None)
                if _floor_hit:
                    break
            if _floor_hit:
                deny(f"'{tool}' touches the governance floor [gate-self]: {_floor_hit!r}, "
                     f"and the shared closure classifier is unavailable — failing closed",
                     "Restore plugins/_shared (hestia_governance_closure) or escalate.",
                     innate=True)

        # ── Sprint F (§6.F): THE decision — core evaluate() from an AUTHENTICATED policy path,
        # or the ratified degraded mode. No silent policy=None / local-replica fallback exists
        # on this path (§7.1 criterion 5).
        ev = _core.NormalizedEvent(tool=tool, paths=paths, command=cmd,
                                   cwd=event.get("cwd"), raw=event,
                                   repos=([mcp_repo] if mcp_repo else []))
        snapshot = None
        try:
            m = _load_mechanism()
            snapshot = m.fetch_policy_snapshot(HESTIA_PLUGIN_ID, host_agent=HESTIA_PLUGIN_ID,
                                               host_session_id=event.get("session_id"))
        except Exception:
            snapshot = None   # an unimportable mechanism == an unreachable daemon: degrade below
        if snapshot is not None:
            global _SNAPSHOT_ROLE
            _SNAPSHOT_ROLE = snapshot.get("role")
            # The core's seam as built: resolve_agent_policy(vault_reader=...) — the reader is
            # the LIVE daemon snapshot, which ALWAYS carries an `in_scope` list, so resolution
            # can never fall through to the local replica on this path.
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
                # verdict_available=False routes this through record_gate_unavailable AND the
                # unified recorder's diagnostic-log fallback (criterion 9(c)) — an infra
                # posture, never member conduct.
                witness_decision("deny", verdict.reason, False, verdict_available=False)
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

        # Gate 2 — society safety (the governor). Only write/exec-class needs the daemon's verdict;
        # fail closed. Reached IN-PROCESS via the shared mechanism (Sprint E, PRD §6.E) — the same
        # lean connect/begin/poll round-trip claude makes, mirroring kimi's integration. The old
        # subprocess spawn (fork + cold 2760-line import off 9p, 2s budget under codex's 3s clamp)
        # was the structural cost §7.4 criterion 10 deletes: it manufactured fail-closed denies
        # while the daemon was up and answering. query_society_safety() never raises and never
        # allows on error; a down/slow daemon or malformed verdict returns a no-verdict
        # (decided=False) that fails closed here, exactly as the old returncode!=0 path did.
        # NOTE apply_patch still classifies on its EXTRACTED target paths at Gates 1a/1b above —
        # the patch BODY is content, not a reach; the daemon sees the same event codex saw.
        if tool not in READ_CLASS:
            verdict = None
            try:
                m = _load_mechanism()
                verdict = m.query_society_safety(
                    event, plugin_id="codex", host_agent="codex",
                    host_session_id=event.get("session_id"))
            except Exception:
                # Loading the mechanism must itself fail closed on a consequential act: a missing
                # or unimportable module is not a reason to allow a write on a fail-open harness.
                witness_decision("deny" if MODE == "enforce" else "warn",
                                 "society-safety: mechanism unavailable, failing closed", False,
                                 verdict_available=False)
                if MODE == "enforce":
                    sys.stderr.write("hestia: deny [safety] — the society-safety mechanism could "
                                     "not be loaded; failing closed on a consequential act.\n")
                    sys.exit(2)
                sys.stderr.write("hestia: warn [safety] — society-safety mechanism unavailable "
                                 "(warn-rollout: allowed).\n")
            if verdict is not None and not verdict.allow:  # enforced deny OR no-verdict -> fail closed
                msg = (verdict.message
                       or "hestia: deny [safety] — blocked/inconclusive at the society safety gate.")
                # verdict.decided is the discrimination the old path reconstructed from stderr
                # marker text: True = the governor really ruled (counts as conduct); False = the
                # gate could not obtain a verdict (infra — never scored as member conduct).
                witness_decision("deny" if MODE == "enforce" else "warn",
                                 "society-safety: " + msg.split("— ", 1)[-1].strip(), False,
                                 verdict_available=verdict.decided)
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
