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

Two gates, in order:
  1. SCOPE + EGRESS (local, per-entity, from Codex's MRH in identity.json). Forbidden egress/secret
     path or out-of-scope target -> deny. No daemon needed, so a down daemon never bricks this.
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
) if _core is not None else None)

# Innate egress/secret invariants + read-class — ONE list each, in the core (§7.1(1)).
# Inert placeholders when the core is missing: main() fails closed on `_core is None`
# before either is consulted, and an empty READ_CLASS reads as "everything is
# write-class", which is the tighter direction.
FORBIDDEN = _core.forbidden_tokens(_CORE_PROFILE) if _core is not None else ()
READ_CLASS = _core.READ_CLASS if _core is not None else frozenset()



# ---- Sprint D (§6.D): authority resolves, not guesses ---------------------------------
#
# The legacy trio — `load_in_scope` (permissive `["web4"]`-on-any-failure fallback),
# `_identity_role`, `launch_cwd_repo` — is DELETED, not shared: each derived authority
# from harness/cwd/identity-file incidentals. Standing scope now comes from the core's
# authenticated path; the two fields AgentPolicy cannot yet supply are bridged by the
# marked TEMPORARY functions below. The permissive fallback is NOT bridged — absent data
# grants nothing, which is the tighter direction.

def _agent_scopes():
    """Standing scope via the core's authenticated path (resolve_agent_policy -> AgentPolicy).
    No vault_reader is wired yet, so this resolves from the CERTIFIED local replica or grants
    NOTHING ('unresolved' / 'replica-uncertified' / 'replica-expired' all -> empty scope).
    Strictly tighter than the deleted load_in_scope, which returned a fixed one-repo guess on
    ANY failure — a guess that GRANTS. The wildcard is dropped for the same reason evaluate()
    drops it on a stale policy: without a vault_reader every resolution here is stale, and
    '*' from a member-writable replica must never widen.
    # SPRINT-F: replace with certified snapshot (vault_reader wired; evaluate() cutover)."""
    pol = _core.resolve_agent_policy(_CORE_PROFILE)
    return [s for s in pol.scope if s != _core.AgentPolicy.UNSCOPED]


def _role_bridge():
    """TEMPORARY, attribution-only: the role string that witnesses/connects carry. Never used
    to widen reach — deriving authority from this member-writable file is exactly what §6.D
    deleted. Same read and same constellation-member fallback the deleted _identity_role had,
    kept so the witness grain does not silently change mid-train.
    # SPRINT-F: replace with certified snapshot (role from the vault policy, not identity.json)."""
    try:
        r = json.load(open(IDENTITY, encoding="utf-8")).get("role")
        if isinstance(r, str) and r.startswith("role:"):
            return r
    except Exception:
        pass
    return "role:constellation:member"


def _launch_scope_bridge():
    """TEMPORARY: the per-launch cwd grant (dp 2026-07-21: 'whatever cwd we launch it in').
    The ratified target sources this as an EXPLICIT launch-cwd grant in the certified policy
    snapshot; until that lands this carries the same single-segment grant the deleted
    launch_cwd_repo computed — no weaker, no wider (one workspace child, never '*').
    # SPRINT-F: replace with certified snapshot (explicit launch-cwd grant)."""
    cwd = (os.environ.get("HESTIA_CODEX_LAUNCH_CWD") or os.getcwd()).replace("\\", "/")
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


def _all_repos():
    try:
        return [d for d in os.listdir(WORKSPACE)
                if os.path.isdir(os.path.join(WORKSPACE, d)) and not d.startswith(".")]
    except Exception:
        return []


def path_in_scope(path, scopes, cwd=None):
    """A file path is in-scope if it's the agent's home, /tmp, or under a granted repo.
    Relative paths resolve against the event cwd — 'scripts/x' inside a granted repo is that
    repo's subdir, not the workspace-root 'scripts' dir (same class as the command-scope
    false-deny, 2026-07-23)."""
    p = path.replace("\\", "/")
    low = p.lower()
    if CODEX_HOME.lower() in low or "~/.codex" in low:
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
    lexically mentions. Two passes:

      1. absolute workspace references (ALL occurrences) — the path component right after the
         root must be a granted repo; bare root (glob-the-root antipattern) denies;
      2. relative path tokens, resolved against the event cwd — 'scripts/foo.py' inside a
         granted repo is that repo's subdir, NOT the workspace-root 'scripts' dir.

    History (2026-07-23, both found live by Codex): (a) the oos scan matched the workspace
    root's own path component ('ai-agents' dir inside .../ai-agents), denying every absolute
    path; (b) it matched generic dir names ('scripts', 'logs', ...) that exist both at the
    workspace root and inside granted repos, denying in-repo relative paths. Lexical mention-
    scanning was the wrong primitive; cwd-resolution replaces it. (Relative traversal that
    never names a path — `grep -r .` — still escapes string parsing; Codex's sandbox, not this
    check, is the fs boundary.)"""
    ws = WORKSPACE.rstrip("/")
    # Pass 1 — absolute references.
    parts = cmd.split(WORKSPACE)
    for after in parts[1:]:
        head = after.lstrip("/")
        head = re.split(r"""[\s"'`);&|<>]""", head, 1)[0]  # cut at shell metachars
        head = head.split("/", 1)[0]
        if head not in scopes:
            return False, (head or "<workspace root>")
    # Pass 2 — relative tokens. The event cwd is NOT reliable for these: Codex runs each
    # command with a per-command workdir the hook event does not carry (observed live: event
    # cwd = the session launch dir, e.g. the workspace root, while the command actually ran
    # inside a granted repo — 'scripts'/'Research'/'simulations'/branch-prefix 'agent/' all
    # false-denied, 2026-07-23). So a relative token is judged by its PLAUSIBLE
    # interpretations — the event cwd plus every granted repo root — voting by what EXISTS:
    #   * an existing in-scope interpretation -> pass (the work is plausibly granted);
    #   * an existing out-of-scope interpretation with NO in-scope alternative -> deny;
    #   * a token that exists nowhere -> not a reach (branch names, heredoc fragments).
    # Residual (documented, accepted): a root-workdir command naming a dir that ALSO exists
    # in a granted repo passes — the sandbox, not this string check, is the fs boundary.
    cwd = (cwd or os.getcwd()).replace("\\", "/")
    bases = [cwd] + [f"{ws}/{s}" for s in scopes]
    oos_names = {r for r in _all_repos() if r not in scopes}
    probes = 0
    for raw in re.split(r"""[\s;|&<>()'"`]+""", cmd):
        for tok in raw.split("="):
            tok = tok.strip()
            # Skip: empty, flags, absolute (pass 1's job), URLs/remotes (':'), pure dots.
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
            # §6.D: ONE list, in the core — the local literal missed gemini-cli
            # and cursor, so this centralization only retires a false-deny class.
            # Safe to reference here: main() fails closed on `_core is None`
            # before any command is scoped.
            if "/" not in tok and tok in _core.MEMBER_ADDRESSES:
                continue  # bare word that isn't a workspace-dir name
            if probes >= 40:
                break     # bound fs probing under the engine's 3s hook clamp
            probes += 1
            # Probe = leading '..'s plus the first real component ('../synchronism-site',
            # 'scripts', ...) — enough to know WHERE the token lands, cheap to exists-check.
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


def main():
    # Fail-closed skeleton: any unexpected error -> deny (never fall through to allow).
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except Exception:
        sys.stderr.write("hestia: deny [gate] — could not parse the tool event; failing closed.\n")
        sys.exit(2)

    if event.get("hook_event_name") != "PreToolUse":
        sys.exit(0)  # not our event

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
    # §6.D: standing scope resolves through the core's authenticated path (grants NOTHING
    # when nothing certifiable resolves); the launch-cwd grant rides the marked bridge.
    scopes = _agent_scopes() + _launch_scope_bridge()
    if tool == "apply_patch":
        # apply_patch's payload is FILE CONTENT, not a shell command. Check the TARGET paths for
        # scope/egress; do NOT scan the patch body for forbidden tokens (else a security review that
        # mentions '.env'/'credentials' is false-denied — Codex, 2026-07-23). Sandbox confines the write.
        paths = apply_patch_targets(tinput)
        cmd = None
    else:
        paths = path_targets(tinput)
        cmd = command_of(tinput)

    # Gate 1a — egress/secret innate invariant (denied even inside a granted repo). ALWAYS enforced.
    for blob in paths + ([cmd] if cmd else []):
        if any(f in blob.lower() for f in FORBIDDEN):
            deny("egress.secret",
                 f"'{tool}' touches a forbidden path (secret/credential or out-of-MRH private repo)",
                 innate=True)

    # Gate 1b — MRH scope. File paths use path-scope; shell commands use command-scope.
    # An MCP call that names its repo separately is scoped on THAT name; its `path` is
    # repo-relative and must not be re-scoped (see mcp_repo_target). The forbidden-token
    # check above still ran over those paths, so egress/secret protection is unaffected.
    mcp_repo = mcp_repo_target(tinput)
    if mcp_repo is not None:
        if mcp_repo not in scopes:
            deny("mrh.repo",
                 f"'{tool}' targets repository '{mcp_repo}' outside your granted scope "
                 f"({'+'.join(scopes)})")
        paths = []
    for p in paths:
        if not path_in_scope(p, scopes, event.get("cwd")):
            deny("mrh.path",
                 f"'{tool}' targets '{p[:60]}' outside your granted scope ({'+'.join(scopes)})")
    if cmd is not None:
        ok, offending = command_in_scope(cmd, scopes, event.get("cwd"))
        if not ok:
            # Name WHAT tripped the gate — a deny that hides its trigger sends the agent
            # debugging blind (Codex live session, 2026-07-23).
            deny("mrh.command",
                 f"'{tool}' command reaches outside your granted scope: '{offending}' is not granted "
                 f"(granted: {'+'.join(scopes)})")

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


if __name__ == "__main__":
    main()
