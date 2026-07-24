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
  2. SOCIETY SAFETY (the governor): for exec-class tools, delegate to hestia's tested daemon caller
     so the decision reaches the governor and is witnessed; its deny (or fail-closed-on-unreachable)
     is honored.

Config (all env-overridable; defaults suit a generic install):
  HESTIA_WORKSPACE        root that contains the granted repos       (default: ~/ai-workspace)
  HESTIA_SOCIETY_GATE     path to the society-safety gate caller      (default: $WORKSPACE/hestia/plugins/claude-code/hooks/pre_tool_use.py)
  HESTIA_CODEX_IDENTITY   the member's live identity.json             (default: ~/.codex/hestia-instance/identity.json)
  HESTIA_CODEX_GATE_MODE  warn | enforce   (default: enforce — deny-tight, relax as trust accrues)
  HESTIA_CODEX_LAUNCH_CWD launch dir granted for the session          (default: os.getcwd())
  HESTIA_FORBIDDEN_EXTRA  comma-separated extra forbidden path tokens (e.g. your private repo names)
"""
import json
import os
import re
import sys
import subprocess

WORKSPACE = os.environ.get("HESTIA_WORKSPACE", os.path.expanduser("~/ai-workspace"))
IDENTITY = os.path.expanduser(
    os.environ.get("HESTIA_CODEX_IDENTITY", "~/.codex/hestia-instance/identity.json"))
CLAUDE_PRE = os.environ.get(
    "HESTIA_SOCIETY_GATE",
    os.path.join(WORKSPACE, "hestia/plugins/claude-code/hooks/pre_tool_use.py"))

# Innate egress/secret invariants — denied even inside a granted repo. Trust never relaxes these (S1).
FORBIDDEN = ("/.ssh", ".env", "credentials", "id_rsa", "id_ed25519", "/.git/config", "secrets") + tuple(
    t.strip() for t in os.environ.get("HESTIA_FORBIDDEN_EXTRA", "").split(",") if t.strip())
READ_CLASS = {"Read", "Glob", "Grep", "TodoWrite", "TodoList", "GetGoal"}

# The agent's own home is always in scope (state, identity, config).
CODEX_HOME = os.path.expanduser("~/.codex")


def load_in_scope():
    """Codex's granted MRH (repos it may touch), read from its identity — per-entity, role-sourced."""
    try:
        mrh = json.load(open(IDENTITY, encoding="utf-8")).get("mrh", {})
        scope = mrh.get("in_scope")
        if isinstance(scope, list) and scope:
            return [s.split(":", 1)[-1] for s in scope]  # "repo:web4" -> "web4"
    except Exception:
        pass
    return ["web4"]


def launch_cwd_repo():
    """The repo Codex is launched in is always in scope — a per-launch dynamic grant on top of the
    static allowlist, so a task-specific launch dir (even a private repo) is reachable for that
    session without widening the standing grant."""
    cwd = (os.environ.get("HESTIA_CODEX_LAUNCH_CWD") or os.getcwd()).replace("\\", "/")
    if WORKSPACE in cwd:
        rest = cwd.split(WORKSPACE, 1)[1].lstrip("/")
        seg = rest.split("/", 1)[0] if rest else ""
        return [seg] if seg else []
    return []


def path_targets(tool_input):
    out = []
    if isinstance(tool_input, dict):
        for k in ("path", "file_path", "notebook_path", "pattern"):
            v = tool_input.get(k)
            if isinstance(v, str):
                out.append(v)
    return out


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


def witness_decision(verb, reason, innate):
    """Witness a blocked/warned reach to the observation log. 'Reaching is witnessed' has to INCLUDE
    the reaches we deny — they are the boundary-tests the policy entity most needs (escalation
    triggers, precedent, trust calibration). Denied calls never reach PostToolUse, so observe.sh
    never sees them; this is the only record of a deny. Fail-safe: a log failure never changes the
    decision (the gate still exits 2)."""
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


def deny(reason, what_to_do, innate=False):
    """innate=True -> ALWAYS blocks (egress/secret is irreversible). Tunable rules honor MODE."""
    verb = "deny" if (innate or MODE == "enforce") else "warn"
    witness_decision(verb, reason, innate)   # a blocked reach is witnessed, not just shown to the agent
    sys.stderr.write(
        f"hestia: {verb} [scope] — {reason}. This is a boundary, not a failure: don't re-run the same "
        f"call. {what_to_do} Asking is a trust-building act; reaching is witnessed.\n")
    if innate or MODE == "enforce":
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

    _EVENT.clear(); _EVENT.update(event)   # so deny()/witness_decision can record the reach it blocks
    tool = event.get("tool_name") or "?"
    tinput = event.get("tool_input") or {}
    scopes = load_in_scope() + launch_cwd_repo()
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
            deny(f"'{tool}' touches a forbidden path (secret/credential or out-of-MRH private repo)",
                 "There is no in-scope way to do this; it is not yours to touch.", innate=True)

    # Gate 1b — MRH scope. File paths use path-scope; shell commands use command-scope.
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

    # Gate 2 — society safety (the governor). Only write/exec-class needs the daemon's verdict; fail closed.
    if tool not in READ_CLASS:
        try:
            env = dict(os.environ, HESTIA_PLUGIN_ID="codex-cli", HESTIA_PRE_FAIL_CLOSED="1")
            # Codex CLAMPS every hook to 3s. The whole gate must finish under that or Codex kills it
            # and FAILS OPEN — so the society-safety subprocess gets 2s, not 6s: a slow/hung daemon
            # then fails CLOSED here (enforce) at 2s instead of fail-open at the 3s clamp. (2026-07-23,
            # from Codex's first live session: "clamping SessionEnd hook timeout to 3s".)
            r = subprocess.run([sys.executable, CLAUDE_PRE], input=json.dumps(event),
                               capture_output=True, text=True, timeout=2, env=env)
            if r.returncode != 0:  # daemon denied, or inconclusive -> fail-closed for a write/exec act
                msg = (r.stderr.strip() if r.returncode == 2 and r.stderr.strip()
                       else "hestia: deny [safety] — blocked/inconclusive at the society safety gate.")
                witness_decision("deny" if MODE == "enforce" else "warn",
                                 "society-safety: " + msg.split("— ", 1)[-1].strip(), False)
                if MODE == "enforce":
                    sys.stderr.write(msg if msg.endswith("\n") else msg + "\n")
                    sys.exit(2)
                sys.stderr.write("hestia: warn [safety] — " + msg.split("— ", 1)[-1] +
                                 " (warn-rollout: allowed; would block under enforce)\n")
        except Exception:
            witness_decision("deny" if MODE == "enforce" else "warn",
                             "society-safety: governor unreachable, failing closed", False)
            if MODE == "enforce":
                sys.stderr.write("hestia: deny [safety] — could not reach the governor; failing "
                                 "closed on a consequential act.\n")
                sys.exit(2)
            sys.stderr.write("hestia: warn [safety] — governor unreachable (warn-rollout: allowed).\n")

    sys.exit(0)  # the ONLY allow path — reached only after every gate explicitly passed


if __name__ == "__main__":
    main()
