#!/usr/bin/env python3
"""Hestia Phase-1 PreToolUse GATE for a foreign member (Kimi Code) — reference adapter.

This is the membrane — the one hook a Kimi act must transit to have effect. It is FAIL-CLOSED BY
CONSTRUCTION, because Kimi's hook engine fails OPEN on every failure mode (verified from the binary:
timeout / spawn-fail / non-2 exit / exception all -> allow). So a blocking hook must default to
`exit 2` and reach `exit 0` only on an explicit, confirmed allow — never rely on `set -e` or the
engine's default. (This fail-open-on-error behavior is a property of the Claude-Code-lineage hook
engines — Kimi, Codex, Cursor, etc. — and is the single most important fact for anyone writing a
blocking hook for them: the gate itself must be the fail-closed party.)

Three gates, in order:
  1. SCOPE + EGRESS (local, per-entity, sourced from Kimi's MRH in identity.json). Out-of-scope
     target, or a forbidden egress/secret path, -> deny. No daemon needed, so a down daemon never
     bricks this boundary.
  1c. SELF-PROTECTION (local, pre-daemon, ALWAYS enforced): a write-class act whose DESTINATION is
     this plugin's own hook files or the fleet's governance markers is refused and escalated (a
     pre-existing human approval is claimed and spent); reads are allowed and witnessed. Restored
     2026-08-12 after the in-process rewire (PR #372) silently dropped the layer the spawned
     claude gate used to carry — see the marker block below.
  2. SOCIETY SAFETY (the governor): for write/exec-class tools, delegate to hestia's tested daemon
     caller so the decision reaches the governor and is witnessed. Its deny (or fail-closed-on-
     unreachable) is honored.

A deny is STEERING, not just a block: the stderr reason says why + what to do (adjust in-scope, or
ask via request_scope).

Exit codes (Kimi engine contract): 2 = block (stderr = reason); 0 = allow. Default is 2.

Config (all env-overridable; defaults suit a generic install):
  HESTIA_WORKSPACE       root that contains the granted repos      (default: ~/ai-workspace)
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
    os.environ.get("HESTIA_KIMI_IDENTITY", "~/.kimi-code/hestia-instance/identity.json"))
# Delegate the society-safety check to hestia's tested daemon caller (the safety preset is global, so
# plugin_id doesn't change its verdict — we set it anyway for when it's parametrized).
CLAUDE_PRE = os.environ.get(
    "HESTIA_SOCIETY_GATE",
    os.path.join(WORKSPACE, "hestia/plugins/claude-code/hooks/pre_tool_use.py"))

# Innate egress/secret invariants — denied even inside a granted repo. Trust never relaxes these (S1).
# Universal secret/credential patterns here; add your own private-repo names via HESTIA_FORBIDDEN_EXTRA.
FORBIDDEN = ("/.ssh", ".env", "credentials", "id_rsa", "id_ed25519", "/.git/config", "secrets") + tuple(
    t.strip() for t in os.environ.get("HESTIA_FORBIDDEN_EXTRA", "").split(",") if t.strip())
READ_CLASS = {"Read", "Glob", "Grep", "TodoWrite", "TodoList", "GetGoal"}


def load_in_scope():
    """Kimi's granted MRH (repos it may touch), read from its identity — per-entity, role-sourced.
    Scope grants become entries here. Default reflects an example grant."""
    try:
        mrh = json.load(open(IDENTITY, encoding="utf-8")).get("mrh", {})
        scope = mrh.get("in_scope")
        if isinstance(scope, list) and scope:
            return [s.split(":", 1)[-1] for s in scope]  # "repo:web4" -> "web4"
    except Exception:
        pass
    return ["web4"]


def _identity_role():
    """The member's declared LOCAL role (dp 2026-07-24: roles are always local; occupancy
    attributes carry the 'foreign' dimension). Falls back to the safe default."""
    try:
        r = json.load(open(IDENTITY, encoding="utf-8")).get("role")
        if isinstance(r, str) and r.startswith("role:"):
            return r
    except Exception:
        pass
    return "role:constellation:member"


def launch_cwd_repo():
    """The repo Kimi is launched in is always in scope (dp 2026-07-21: 'whatever cwd we launch it
    in') — a per-launch dynamic grant on top of the static allowlist, so a task-specific launch dir
    (even a private repo) is reachable for that session without widening the standing grant."""
    cwd = (os.environ.get("HESTIA_KIMI_LAUNCH_CWD") or os.getcwd()).replace("\\", "/")
    if WORKSPACE in cwd:
        rest = cwd.split(WORKSPACE, 1)[1].lstrip("/")
        seg = rest.split("/", 1)[0] if rest else ""
        return [seg] if seg else []
    return []


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


def _all_repos():
    try:
        return [d for d in os.listdir(WORKSPACE)
                if os.path.isdir(os.path.join(WORKSPACE, d)) and not d.startswith(".")]
    except Exception:
        # If the workspace listing fails, degrade to root-glob detection only (no static inventory in
        # the generic adapter — set HESTIA_WORKSPACE so the live listing works). deny-known-out is
        # better than allow-all, but we don't ship a hardcoded repo list here.
        return []


def path_in_scope(path, scopes, cwd=None):
    """A file path is in-scope if it's the agent's home, /tmp, or under a granted repo.
    Relative paths resolve against the event cwd — 'scripts/x' inside a granted repo is that
    repo's subdir, not the workspace-root 'scripts' dir (same class as the command-scope
    false-deny, 2026-07-23)."""
    p = path.replace("\\", "/")
    low = p.lower()
    if "~/.kimi-code" in low or low.startswith(os.path.expanduser("~/.kimi-code").lower()):
        return True
    if not p.startswith("/") and not p.startswith("~"):
        cwd = (cwd or os.getcwd()).replace("\\", "/")
        p = os.path.normpath(os.path.join(cwd, p)).replace("\\", "/")
    if p.startswith(("/tmp", "/var/tmp")):
        return True
    if WORKSPACE in p:
        rest = p.split(WORKSPACE, 1)[1].lstrip("/")
        seg = rest.split("/", 1)[0] if rest else ""
        if seg == "":
            return False       # bare workspace root (the glob-the-root antipattern) -> out of scope
        return seg in scopes
    # Absolute path outside the workspace (and not home/tmp): conservative deny, as before.
    return False


def command_in_scope(cmd, scopes, cwd=None):
    """Returns (ok, offending_token). A reach is judged by WHERE IT RESOLVES, not what it
    lexically mentions: (1) absolute workspace references (ALL occurrences) must land in a
    granted repo (bare root denies); (2) relative path tokens resolve against the event cwd —
    'scripts/foo.py' inside a granted repo is that repo's subdir, NOT the workspace-root
    'scripts' dir. Lexical mention-scanning false-denied both classes (found live via the
    Codex gate, 2026-07-23; same matcher). Relative traversal that never names a path
    (`grep -r .`) still escapes string parsing — the engine sandbox is the fs boundary."""
    ws = WORKSPACE.rstrip("/")
    parts = cmd.split(WORKSPACE)
    for after in parts[1:]:
        head = after.lstrip("/")
        head = re.split(r"""[\s"'`);&|<>]""", head, 1)[0]
        head = head.split("/", 1)[0]
        if head not in scopes:
            return False, (head or "<workspace root>")
    # Pass 2 — relative tokens. The event cwd is NOT reliable for these: the engine may run
    # each command with a per-command workdir the hook event does not carry (observed live via
    # the Codex gate: event cwd = session launch dir while the command ran inside a granted
    # repo — 'scripts'/'Research'/'simulations'/branch-prefix 'agent/' all false-denied,
    # 2026-07-23). A relative token is judged by its PLAUSIBLE interpretations — the event cwd
    # plus every granted repo root — voting by what EXISTS: an existing in-scope
    # interpretation passes; an existing out-of-scope interpretation with NO in-scope
    # alternative denies; a token that exists nowhere is not a reach. Residual (documented,
    # accepted): a root-workdir command naming a dir that ALSO exists in a granted repo
    # passes — the engine sandbox, not this string check, is the fs boundary.
    cwd = (cwd or os.getcwd()).replace("\\", "/")
    bases = [cwd] + [f"{ws}/{s2}" for s2 in scopes]
    oos_names = {r for r in _all_repos() if r not in scopes}
    probes = 0
    for raw in re.split(r"""[\s;|&<>()'"`]+""", cmd):
        for tok in raw.split("="):
            tok = tok.strip()
            if (not tok or tok.startswith(("-", "/")) or ":" in tok
                    or tok.strip(".") == ""):
                continue
            first = tok.split("/", 1)[0]
            if "/" not in tok and first not in oos_names:
                continue
            # A bare member plugin-id is an ADDRESS (mesh notify targets, tool
            # args), not a filesystem reach — even when a same-named directory
            # exists at the workspace root (live false-deny: kimi's mesh ack
            # 'send claude-code ack <ptr>' denied on the claude-code DIR,
            # 2026-07-24). With a slash it is a path again and votes normally.
            if "/" not in tok and tok in ("claude-code", "kimi-code", "codex-cli"):
                continue
            if probes >= 40:
                break     # bound fs probing under the engine hook clamp
            probes += 1
            comps = tok.split("/")
            k = 0
            while k < len(comps) and comps[k] == "..":
                k += 1
            probe = "/".join(comps[:k + 1]) if k < len(comps) else "/".join(comps)
            in_scope_vote, oos_vote = False, None
            for base in bases:
                cand = os.path.normpath(os.path.join(base, probe)).replace("\\", "/")
                if not os.path.exists(cand):
                    continue
                if cand == ws:
                    oos_vote = oos_vote or "<workspace root>"
                    continue
                if cand.startswith(ws + "/"):
                    seg = cand[len(ws) + 1:].split("/", 1)[0]
                    if seg in scopes:
                        in_scope_vote = True
                        break
                    oos_vote = seg
            if not in_scope_vote and oos_vote:
                return False, oos_vote
    return True, None


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
                                            # KNOWN its role — it writes `_identity_role()`
                                            # into the attestation payload below — and never
                                            # told the daemon on connect, so the session
                                            # defaulted to role:constellation:member and the
                                            # attestation landed on a grain the member does
                                            # not act under. Acts on one grain, the decisions
                                            # governing them on another, and NEITHER can score
                                            # conduct. The capability to declare arrived with
                                            # the connect-echoes-role work; this is the caller
                                            # that never started using it.
                                            "role": _identity_role(),
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
                                       "role_lct": _identity_role(),
                                       "allows": allows,
                                       "denies": denies,
                                       "attested_by": "plugin-gate:" + HESTIA_PLUGIN_ID,
                                   }}}}, 1.5, h)


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
    return s[:limit] + ("\u2026[truncated]" if len(s) > limit else "")


def _daemon_witness(verb, reason):
    """Report an enforced deny/warn to the daemon's witness chain (hestia_witness_decision MCP
    tool) so it shows on the dashboard's warn/deny feed and feeds gate-risk trust. Local-gate
    denies were otherwise invisible to the dashboard (dp, 2026-07-23). Fire-and-forget: short
    timeouts, every failure swallowed — a down daemon never changes the decision."""
    import urllib.request, hashlib
    endpoint = os.environ.get("HESTIA_ENDPOINT", "http://127.0.0.1:7711/mcp")
    ti = _EVENT.get("tool_input")
    ti_hash = None
    if ti is not None:
        ti_hash = hashlib.sha256(
            json.dumps(ti, sort_keys=True, default=str).encode("utf-8", "replace")).hexdigest()[:16]

    def post(payload, hdrs, timeout):
        req = urllib.request.Request(
            endpoint, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json",
                     "Accept": "application/json, text/event-stream", **hdrs})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read(), resp.headers.get("mcp-session-id")

    _, sid = post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                   "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                              "clientInfo": {"name": "hestia-kimi-gate", "version": "1"}}}, {}, 0.5)
    h = {"mcp-session-id": sid} if sid else {}
    post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}, h, 0.4)
    post({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
          "params": {"name": "hestia_witness_decision",
                     "arguments": {"plugin_id": "kimi-code",
                                   "decision": verb,
                                   "adjudicator": "plugin-gate:kimi(scope/egress)",
                                   "reason": reason[:300],
                                   "tool_name": _EVENT.get("tool_name") or "",
                                   "session_id": _EVENT.get("session_id"),
                                   "payload_sha256": ti_hash,
                                   "attempted": _attempted_summary(_EVENT),
                                   "role": _identity_role()}}}, h, 0.8)


def deny(reason, what_to_do, innate=False):
    _tally_scope(False)   # a denied reach still closes part of the window
    """innate=True -> ALWAYS blocks (egress/secret is irreversible: a leaked read has no undo, so it
    is enforced even in warn-rollout). Tunable scope/safety rules honor MODE: warn surfaces + allows,
    enforce blocks."""
    verb = "deny" if (innate or MODE == "enforce") else "warn"
    sys.stderr.write(
        f"hestia: {verb} [scope] — {reason}. This is a boundary, not a failure: don't re-run the same "
        f"call. {what_to_do} Asking is a trust-building act; reaching is witnessed.\n")
    try:
        _daemon_witness(verb, reason)
    except Exception:
        pass  # witnessing must never change the decision
    if innate or MODE == "enforce":
        sys.exit(2)
    # warn mode, tunable rule: surfaced but allowed — return so evaluation continues to allow.


# ---- Gate 1c: LOCAL SELF-PROTECTION (the governance surface) -------------------------
#
# Restored 2026-08-12 (PR #372 blocking note, remedy option (a); asked on-record by the branch
# owner in forum/claude-code/reply-2001-option-a-go-ahead-kimi-authorized-2026-08-12.md). Before
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
_SELF_DIR_MARKERS = ("plugins/kimi/hooks", "plugins/claude-code/hooks", "hestia/hooks")
_SELF_GOVERNANCE_FILES = (
    "pre_tool_use.py", "society_pre_tool_use.py", "post_tool_use.py", "witness.py",
    "law_inject.py", "hestia_gate_core.py", "hestia_gate_mechanism.py",
    "gate_self_protection_test.py",
)
_SELF_HOOKS_DIR_ONLY = ("pre_tool_use.py", "society_pre_tool_use.py", "post_tool_use.py",
                        "witness.py", "law_inject.py")


def _touches_self(tool_input):
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
                        "role": _identity_role(),
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


def _witness_gate_self(event_type, marker, tool_name):
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
                       "gate_path": os.path.abspath(__file__),
                       "severity": "record" if event_type == "gate_self_read" else "escalate",
                       "role_lct": _identity_role()}},
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
        "role": _identity_role(),
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


def main():
    # Fail-closed skeleton: any unexpected error -> deny (never fall through to allow).
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except Exception:
        sys.stderr.write("hestia: deny [gate] — could not parse the tool event; failing closed.\n")
        sys.exit(2)

    if event.get("hook_event_name") != "PreToolUse":
        sys.exit(0)  # not our event

    _EVENT.clear(); _EVENT.update(event)
    tool = event.get("tool_name") or "?"
    tinput = event.get("tool_input") or {}
    scopes = load_in_scope() + launch_cwd_repo()
    paths = path_targets(tinput)
    cmd = command_of(tinput)

    # Gate 1a — egress/secret innate invariant (denied even inside a granted repo). ALWAYS enforced
    # (innate): a leaked read is irreversible egress, so it is not subject to warn-rollout.
    for blob in paths + ([cmd] if cmd else []):
        if any(f in blob.lower() for f in FORBIDDEN):
            deny(f"'{tool}' touches a forbidden path (secret/credential or out-of-MRH private repo)",
                 "There is no in-scope way to do this; it is not yours to touch.", innate=True)

    # Gate 1b — MRH scope (per-entity, from Kimi's identity). File paths use path-scope; shell
    # commands use command-scope (out-of-scope repo tokens + root-glob).
    for p in paths:
        if not path_in_scope(p, scopes, event.get("cwd")):
            deny(f"'{tool}' targets '{p[:60]}' outside your granted scope ({'+'.join(scopes)})",
                 "Adjust to work within scope, or if legitimately needed, request it (request_scope).")
    if cmd is not None:
        ok, offending = command_in_scope(cmd, scopes, event.get("cwd"))
        if not ok:
            # Name WHAT tripped the gate — a deny that hides its trigger sends the agent
            # debugging blind (Codex live session, 2026-07-23).
            deny(f"'{tool}' command reaches outside your granted scope: '{offending}' is not granted "
                 f"(granted: {'+'.join(scopes)})",
                 "Scope the command to a granted repo, or if legitimately needed, request it (request_scope).")

    # Gate 1c — local self-protection. BEFORE the daemon and never conditional on it: if this
    # check needed a verdict, "stop the daemon, then edit the gate" would be the same evasion one
    # layer down. ALWAYS enforced — it does not honor warn-rollout, because a governance write
    # that warns and proceeds is not a boundary.
    self_hit = _touches_self(tinput)
    if self_hit:
        self_marker, self_resource = self_hit
        if tool in READ_CLASS:
            # Publish-the-law: a member may read what governs it — refusing would make a member
            # unable to check its own law. The read is RECORDED so reconnaissance stays visible
            # as a pattern; a failed witness never blocks the read.
            _witness_gate_self("gate_self_read", self_marker, tool)
        else:
            verdict, detail, esc_id, how = _claim_self_write(
                self_marker, tool, _attempted_summary(_EVENT))
            if verdict != "approved":
                _witness_gate_self("gate_self_access", self_marker, tool)
                _tally_scope(False)   # a refused reach still closes part of the window
                esc = (f" Escalation {esc_id} is open — a human decides out of band ({how}); "
                       f"re-issue the write afterwards to claim the approval." if esc_id else "")
                sys.stderr.write(
                    f"hestia: deny [gate-self] — '{tool}' would WRITE to the governance surface: "
                    f"{self_resource} (matched marker {self_marker!r}; {detail}).{esc} This is not "
                    f"an ordinary boundary — the target is what draws the boundaries. Legitimate "
                    f"gate work goes through the escalation, not around it.\n")
                sys.exit(2)
            # APPROVED lifts self-protection for THIS call only — the ordinary gates below still
            # run; approving a gate edit is not approving everything else the call might do.
            sys.stderr.write(f"hestia: gate write APPROVED — {detail}\n")

    # Gate 2 — society safety (the governor). Read-class already fully covered by the local gates;
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
            if MODE == "enforce":
                sys.stderr.write("hestia: deny [safety] — the society-safety mechanism could not "
                                 "be loaded; failing closed on a consequential act.\n")
                sys.exit(2)
            sys.stderr.write("hestia: warn [safety] — society-safety mechanism unavailable "
                             "(warn-rollout: allowed).\n")
        if verdict is not None and not verdict.allow:  # enforced deny OR no-verdict -> fail closed
            msg = (verdict.message
                   or "hestia: deny [safety] — blocked/inconclusive at the society safety gate.")
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


if __name__ == "__main__":
    main()
