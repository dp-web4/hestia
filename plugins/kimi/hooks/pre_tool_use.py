#!/usr/bin/env python3
"""Hestia Phase-1 PreToolUse GATE for a foreign member (Kimi Code) — reference adapter.

This is the membrane — the one hook a Kimi act must transit to have effect. It is FAIL-CLOSED BY
CONSTRUCTION, because Kimi's hook engine fails OPEN on every failure mode (verified from the binary:
timeout / spawn-fail / non-2 exit / exception all -> allow). So a blocking hook must default to
`exit 2` and reach `exit 0` only on an explicit, confirmed allow — never rely on `set -e` or the
engine's default. (This fail-open-on-error behavior is a property of the Claude-Code-lineage hook
engines — Kimi, Codex, Cursor, etc. — and is the single most important fact for anyone writing a
blocking hook for them: the gate itself must be the fail-closed party.)

Two gates, in order:
  1. SCOPE + EGRESS (local, per-entity, sourced from Kimi's MRH in identity.json). Out-of-scope
     target, or a forbidden egress/secret path, -> deny. No daemon needed, so a down daemon never
     bricks this boundary.
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
                                   "role": _identity_role()}}}, h, 0.8)


def deny(reason, what_to_do, innate=False):
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

    # Gate 2 — society safety (the governor). Read-class already fully covered by the local gates;
    # only write/exec-class needs the daemon's destructive/secret verdict — and there we fail closed.
    if tool not in READ_CLASS:
        try:
            env = dict(os.environ, HESTIA_PLUGIN_ID="kimi-code", HESTIA_PRE_FAIL_CLOSED="1")
            if not os.path.isfile(CLAUDE_PRE):
                raise FileNotFoundError(
                    f"society gate script missing at {CLAUDE_PRE} — "
                    "check HESTIA_WORKSPACE / workspace detection")
            r = subprocess.run([sys.executable, CLAUDE_PRE], input=json.dumps(event),
                               capture_output=True, text=True, timeout=6, env=env)
            if r.returncode != 0:  # daemon denied, or inconclusive -> fail-closed for a write/exec act
                msg = (r.stderr.strip() if r.returncode == 2 and r.stderr.strip()
                       else "hestia: deny [safety] — blocked/inconclusive at the society safety gate.")
                if MODE == "enforce":
                    sys.stderr.write(msg if msg.endswith("\n") else msg + "\n")
                    sys.exit(2)
                sys.stderr.write("hestia: warn [safety] — " + msg.split("— ", 1)[-1] +
                                 " (warn-rollout: allowed; would block under enforce)\n")
        except Exception:
            if MODE == "enforce":
                sys.stderr.write("hestia: deny [safety] — could not reach the governor; failing "
                                 "closed on a consequential act.\n")
                sys.exit(2)
            sys.stderr.write("hestia: warn [safety] — governor unreachable (warn-rollout: allowed).\n")

    sys.exit(0)  # the ONLY allow path — reached only after every gate explicitly passed


if __name__ == "__main__":
    main()
