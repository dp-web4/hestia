#!/usr/bin/env python3
"""gate_evaluate — a side-effect-free dry run of the gate (#1450 `evaluate`, v0).

A member learns its territory today by acting and being refused, and a refusal files a scope
request, costs a peer a decision and adds a chain entry. This asks the same question without
the act: "what would the gate say to THIS act, and what are my lawful routes?"

THE SAME GATE, NOT A MODEL OF IT. `evaluate()` runs the gate's own `decide()` (the one sequence
every seat runs: launch role, governance closure, egress, snapshot, local law, society, record)
with every mechanism call that WRITES replaced by a recorder:

  claim_self_write   -> no escalation is opened; the closure write is reported with its route
  witness_gate_self  -> no gate_self_read / gate_self_access witness
  claim_scope        -> no scope request is opened or peeked (a peek can open one)
  query_society_safety -> NOT ASKED: the daemon's society check writes the action cache and the
                        chain, and it has no dry-run form yet. Reported as `society: unchecked`.
  record_decision, scope_batch, tally_scope -> nothing recorded, reserved or counted

and the wire is belted: any request other than the MCP handshake and the three tools the snapshot read uses
(dry-run connect, operating_law, scope_status) raises, so a new write path in the gate fails this
loudly instead of acting.

THE SNAPSHOT IS THE SESSION THE GATE WOULD REUSE. The hook's connect becomes the daemon's read-only
`hestia_connect_dry_run`, which returns the member's EXISTING session for (member, --session) with
the role it was minted with, or refuses when there is none. The law and scope reads then go out on
that session through the daemon's ordinary resolved-session checks: no synthetic identity, nothing
counted as an unbound read. A daemon without the RPC answers "unknown tool", never a mutating
connect. With no live session the answer is an `error` naming why, not a guess.

THE BOUNDARY (dp chose #1450 option (a), 2026-11-03): the answer is scoped to the CLAIMED
member and session. The claim is not authenticated — proof of caller ownership is #824 (and
#954 under it). The dry-run reuse lookup returns the existing daemon session id and soft LCT,
so the daemon admits it only on a loopback listener; a non-loopback listener refuses it without
disclosing either value. Do not expose the ordinary member surface off-host before #824.

What v0 does NOT answer: society law (above), and anything the daemon decides at claim time
(an approved one-time scope grant, a closure approval). `would_allow` is LOCAL/CONDITIONAL:
local law and the closure permit it; society law was not asked.

Usage:
    python3 tools/gate_evaluate.py --member claude-code --tool Bash --input '{"command":"ls /etc"}'
    python3 tools/gate_evaluate.py --tool Read --input '{"file_path":"/home/x/y"}' --cwd /home/x
    python3 tools/gate_evaluate.py --tool Bash --input-file /tmp/act.json   # text your gate judges
Prints one JSON object. Exit 0 always for an answer (the answer may be a deny); 2 on bad usage.
"""
from __future__ import annotations

import argparse
import ast
import importlib
import json
import os
import pathlib
import sys
import time
import urllib.request
from contextlib import contextmanager

REPO = pathlib.Path(__file__).resolve().parents[1]

#: The daemon tools a snapshot read uses. Anything else is a side effect this dry run refuses.
READ_TOOLS = frozenset({"hestia_connect_dry_run", "hestia_operating_law", "hestia_scope_status"})


class SideEffectRefused(RuntimeError):
    """A gate path tried to reach the daemon with a tool that is not a snapshot read."""


def load_gate(shared_dir=None):
    """(single_gate, mechanism, core) from the installed engine the seat runs — HESTIA_SHARED_DIR
    when the projection names it, else this checkout's plugins/_shared."""
    shared = shared_dir or os.environ.get("HESTIA_SHARED_DIR") or str(REPO / "plugins" / "_shared")
    if shared not in sys.path:
        sys.path.insert(0, shared)
    gate = importlib.import_module("hestia_single_gate")
    return gate, gate.mechanism, gate.core


def seat_harness(shim_path):
    """The HARNESS literal a seat's shim declares (data, per the shim template), parsed without
    importing the shim — importing it would run its projection loader."""
    tree = ast.parse(pathlib.Path(shim_path).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "HARNESS" for t in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError(f"{shim_path} declares no HARNESS literal")


@contextmanager
def _dry(mechanism, gate, snapshot=None):
    """Replace every writing mechanism call for the duration; yield the recorder."""
    rec = {"closure_write": None, "closure_read": None, "scope": None, "society_asked": False,
           "final": None, "refused_calls": [], "evaluated_as": None, "snapshot_error": None}
    saved = {}

    def put(mod, name, fn):
        saved[(mod, name)] = getattr(mod, name)
        setattr(mod, name, fn)

    def claim_self_write(marker, tool_name, attempted, **kw):
        rec["closure_write"] = {"marker": marker,
                                "targets": list(kw.get("resolved_targets") or ())}
        return ("dry_run", "dry run: no escalation was opened", None, None)

    def witness_gate_self(event_type, marker, tool_name, rule=None, **kw):
        if event_type == "gate_self_read":
            rec["closure_read"] = {"marker": marker, "rule": rule}
        return "0" * 64  # Synthetic dry-run receipt; no chain write lets the closure reach its route.

    def claim_scope(path, tool_name, attempted, rule, **kw):
        return ("not_opened", "dry run", None)

    real_scope_escalation = gate._scope_escalation

    def scope_escalation(inv, nev, cprofile, policy, v):
        d = real_scope_escalation(inv, nev, cprofile, policy, v)
        targets = []
        if d is not None and d.rule == v.rule:
            # The real collection loop ran; its targets are the refused paths it would ask for.
            # Re-derive them the same way the gate does, from its own helpers.
            import dataclasses
            ws = gate.core.detect_workspace(cprofile)
            cur = v
            while (cur.blocks and cur.rule in mechanism.SCOPE_ESCALATING_RULES
                   and getattr(cur, "target", "") and cur.target not in targets
                   and len(targets) < gate.SCOPE_CLAIM_MAX_PATHS):
                targets.append(cur.target)
                trial = dataclasses.replace(policy, scope=tuple(policy.scope) + tuple(
                    gate._claimed_scope_entry(t) for t in targets))
                cur = gate.core.evaluate(nev, cprofile, ws, policy=trial)
        rec["scope"] = {"rule": v.rule, "law_reason": v.reason, "targets": targets,
                        "decision_rule": getattr(d, "rule", None)}
        return d

    def query_society_safety(event, **kw):
        rec["society_asked"] = True
        return mechanism.SafetyVerdict(allow=True, decided=True, kind="allow",
                                       message="", action_id=None)

    def record_decision(client_or_none, **kw):
        rec["final"] = {k: kw.get(k) for k in ("decision", "rule")}
        return mechanism.DecisionReceipt("committed", entry_hash="0" * 64)

    def refuse(name):
        def f(*a, **kw):
            rec["refused_calls"].append(name)
            raise SideEffectRefused(name)
        return f

    real_fetch = mechanism.fetch_policy_snapshot

    def fetch(plugin_id, **kw):
        if snapshot is not None:
            return snapshot
        kw["use_cache"] = False
        return real_fetch(plugin_id, **kw)

    # THE BELT, at the one place every engine request leaves the process: `urllib.request.
    # urlopen` (the mechanism's `_McpHttp`, `gate_self_call`, `scope_call` and the witness core
    # all post through it). A JSON-RPC body that is not the MCP handshake or a snapshot-read
    # tool call is refused BEFORE it is sent, so a write path this module failed to stub fails
    # loudly here instead of acting on the daemon.
    real_urlopen = urllib.request.urlopen

    def urlopen(req, *a, **kw):
        name, body = None, {}
        try:
            body = json.loads(getattr(req, "data", None) or b"{}")
            method = body.get("method")
            if method == "tools/call":
                name = (body.get("params") or {}).get("name")
            elif method in ("initialize", "notifications/initialized"):
                name = method
        except Exception:  # noqa: BLE001 — an unreadable request is not a read
            name = None
        arguments = (((body.get("params") or {}).get("arguments") or {})
                     if isinstance(body, dict) else {})
        # The law and scope reads ride the session the dry-run connect FOUND, and no other: an
        # absent or different session would be an unbound read (counted against the step C rollout
        # signal) or someone else's, so it is refused before it is sent.
        if (name in ("hestia_operating_law", "hestia_scope_status")
                and (not found.get("session") or arguments.get("session_id") != found["session"])):
            rec["refused_calls"].append(name + " without the found session")
            raise SideEffectRefused(name + " without the found session")
        if name not in READ_TOOLS and name not in ("initialize", "notifications/initialized"):
            rec["refused_calls"].append(name or "<unreadable request>")
            raise SideEffectRefused(str(name))
        return real_urlopen(req, *a, **kw)

    # THE SNAPSHOT IS THE SESSION THE GATE WOULD REUSE (#1490 review). A real connect for a known
    # (member, host session) reuses that session and keeps the role it was MINTED with, whatever
    # HESTIA_ROLE says now; the law and grants follow that role. So the connect becomes the
    # daemon's read-only `hestia_connect_dry_run`, which returns that same session or refuses
    # (no live session: a real connect would mint one, and there is nothing to evaluate as), and
    # the law and scope reads go out unchanged on the session it found, through the daemon's
    # ordinary resolved-session checks. A daemon without the RPC answers "unknown tool", never a
    # mutating connect.
    real_call_tool = mechanism._McpHttp.call_tool
    found = {}

    def call_tool(client, name, arguments):
        if name == "hestia_connect":
            found.clear()
            found["member"] = arguments.get("plugin_id")
            name = "hestia_connect_dry_run"
        reply = real_call_tool(client, name, arguments)
        payload = mechanism._unwrap_tool_result(reply)
        problem = None
        if not isinstance(payload, dict):
            problem = f"{name}: unreadable reply"
        elif "_hestia_error" in payload:
            err = payload.get("_hestia_error") or {}
            problem = f"{name}: {err.get('code', '?')}: {err.get('message', '')}".rstrip(": ")
        elif name == "hestia_connect_dry_run":
            if (payload.get("dryRun") is not True or payload.get("dryRunSnapshotContract") != 2
                    or not isinstance(payload.get("sessionId"), str)
                    or not isinstance(payload.get("constellationRole"), str)):
                problem = "hestia_connect_dry_run: the daemon does not offer the dry-run contract (v2)"
            else:
                found["session"] = payload["sessionId"]
                found["role"] = payload["constellationRole"]
                rec["evaluated_as"] = {"session": found["session"], "role": found["role"],
                                       "declared_role_honored": payload.get("roleDeclarationHonored")}
        elif name == "hestia_operating_law":
            identity = payload.get("identity") or {}
            if (identity.get("plugin_id") != found.get("member")
                    or identity.get("role") != found.get("role")
                    or not isinstance(payload.get("law_hash"), str)
                    or "operator_grant" not in payload):
                problem = "hestia_operating_law: law unavailable, incomplete or not the found session's"
        elif name == "hestia_scope_status":
            if (payload.get("plugin_id") != found.get("member")
                    or payload.get("caller_bound") is not True):
                problem = "hestia_scope_status: not a bound read for the found session"
        if problem:
            rec["snapshot_error"] = problem
            raise SideEffectRefused(problem)
        return reply

    # A failed snapshot is telemetry in the real gate (a gate-unavailable record in the seat's
    # home). Here it is part of the answer, and nothing is written.
    def snapshot_unavailable(plugin_id, detail, cause="unknown"):
        rec["snapshot_error"] = rec["snapshot_error"] or f"{detail} ({cause})"

    try:
        put(mechanism._McpHttp, "call_tool", call_tool)
        put(mechanism, "_snapshot_unavailable", snapshot_unavailable)
        put(mechanism, "claim_self_write", claim_self_write)
        put(mechanism, "witness_gate_self", witness_gate_self)
        put(mechanism, "claim_scope", claim_scope)
        put(mechanism, "query_society_safety", query_society_safety)
        put(mechanism, "record_decision", record_decision)
        put(mechanism, "scope_batch", refuse("scope_batch"))
        put(mechanism, "tally_scope", lambda *a, **kw: None)
        put(mechanism, "emit_attestation", refuse("emit_attestation"))
        put(mechanism, "fetch_policy_snapshot", fetch)
        put(urllib.request, "urlopen", urlopen)
        put(gate, "_scope_escalation", scope_escalation)
        yield rec
    finally:
        for (mod, name), fn in saved.items():
            setattr(mod, name, fn)


def _routes(d, rec):
    """The lawful next steps for this answer. Never a rephrase that reaches the same resource."""
    routes = []
    if rec["closure_write"] is not None and d.rule == "gate.self_access":
        routes.append({"route": "escalation",
                       "what": "issue the act; the gate opens an escalation a human rules out of "
                               "band, and you re-issue the identical act to claim the approval",
                       "marker": rec["closure_write"]["marker"]})
    sc = rec["scope"]
    if sc and sc["targets"] and d.rule == sc["rule"]:
        for t in sc["targets"]:
            if t.startswith(gate_core().UNPRICEABLE_PREFIX):
                routes.append({"route": "rewrite", "target": t,
                               "what": "spell every path out literally; an act the gate cannot "
                                       "enumerate can only be approved once, as written"})
            else:
                routes.append({"route": "scope_request", "target": t,
                               "what": "issuing the act opens a scope request a NOT-SAME peer "
                                       "decides (once, session or standing; exact or recursive); "
                                       "or ask first with hestia_request_scope (one path, a reason)"})
    if d.blocks and not routes and not d.rule.endswith(".nonexistent") and d.verdict_available:
        # A dry run has no chain hash to appeal with: the appeal is of the REAL deny, if you
        # issue the act and are refused. Infrastructure and not-there answers are not conduct.
        routes.append({"route": "appeal",
                       "what": "if you believe this rule is wrong here, issue the act and appeal "
                               "its deny with hestia_appeal (that deny's chain hash and your "
                               "reason) — never a rephrase that reaches the same resource"})
    return routes


_CORE = []


def gate_core():
    return _CORE[0]


def evaluate(tool, tool_input, *, member="claude-code", host_agent=None, cwd=None,
             session_id=None, shim_path=None, shared_dir=None, snapshot=None,
             rollout=None, budget_seconds=8.0):
    """The gate's answer to one act, with nothing filed. Returns a JSON-ready dict."""
    gate, mechanism, core = load_gate(shared_dir)
    _CORE[:] = [core]
    profile = gate.GateProfile(
        member_id=member, host_agent=host_agent or member,
        identity_path=os.environ.get("HESTIA_CLAUDE_IDENTITY") if member == "claude-code" else None,
        home_markers=(os.environ.get("HESTIA_HARNESS_HOME"),),
        client_name=f"hestia-{member}-gate-evaluate",
        gate_path=os.path.realpath(shim_path) if shim_path else "",
        observe_dir=None, declares_review_door=False)
    raw = {"tool_name": tool, "tool_input": tool_input, "cwd": cwd, "session_id": session_id,
           "hook_event_name": "PreToolUse", "gate_evaluate": True}
    event = gate.GateEvent(tool=tool, tool_input=tool_input, cwd=cwd, session_id=session_id,
                           raw=raw)
    kw = {"budget_seconds": budget_seconds}
    registered_checked = False
    if shim_path:
        kw = {"bound": gate.harness_bound(seat_harness(shim_path), os.path.realpath(shim_path),
                                          time.monotonic(), cwd=cwd)}
        registered_checked = True
    with _dry(mechanism, gate, snapshot=snapshot) as rec:
        d = gate.decide(event, profile, rollout=rollout, **kw)
    # Not "no evaluated_as": an act the closure decides never reaches the snapshot, and its
    # answer stands without one.
    if rec["refused_calls"] or rec["snapshot_error"]:
        answer = "error"
    elif d.blocks:
        answer = "would_deny"
    elif rec["society_asked"]:
        answer = "would_allow" if d.decision == "allow" else "would_warn"
    else:
        answer = "would_" + d.decision
    return {
        "answer": answer,
        "decision": d.decision,
        "rule": d.rule,
        "reason": (rec["scope"]["law_reason"] if rec["scope"] and d.rule == rec["scope"]["rule"]
                   and rec["scope"]["targets"] else d.reason),
        "remedy": d.remedy,
        "innate": d.innate,
        "infrastructure": not d.verdict_available,
        "routes": _routes(d, rec),
        "society": ("unchecked: not dry-runnable yet (#1450)" if rec["society_asked"]
                    else "not reached"),
        "closure": ("write" if rec["closure_write"] else "read" if rec["closure_read"] else "none"),
        "registered_surface": "checked" if registered_checked else "not checked (no --shim)",
        "refused_side_effects": rec["refused_calls"],
        "boundary": (("LOCAL/CONDITIONAL would_allow: local law and closure only; society unchecked. "
                       if rec["society_asked"] else "Local answer. ")
                     + "Dry-run session lookup is loopback-only; the claimed member is not "
                       "authenticated (#824). Nothing was filed, opened, witnessed or recorded."),
        "member": member,
        # The session and role the snapshot was read as: the one the gate would reuse, with the
        # role it was minted with (not necessarily the one HESTIA_ROLE declares now).
        "evaluated_as": rec["evaluated_as"],
        # Why there is no answer when there is none: no live session to evaluate as, a daemon
        # without the dry-run contract, or a law/scope read that was not the found session's.
        "snapshot_error": rec["snapshot_error"],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--member", default="claude-code")
    ap.add_argument("--host-agent")
    ap.add_argument("--tool", required=True)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--input", help="the tool input as a JSON object")
    # An act whose TEXT the seat's own gate would judge (a destructive command, a secret-shaped
    # token) cannot travel in argv: the gate reads the command line of this very call. A file
    # carries it as data.
    src.add_argument("--input-file", help="a file holding the tool input as a JSON object")
    ap.add_argument("--cwd", default=os.getcwd())
    ap.add_argument("--session", help="the harness session id, as the hook would send it")
    ap.add_argument("--shim", help="the seat's installed shim, to check its registered surface")
    ap.add_argument("--shared-dir")
    a = ap.parse_args(argv)
    try:
        ti = json.loads(a.input if a.input is not None
                        else pathlib.Path(a.input_file).read_text(encoding="utf-8"))
        if not isinstance(ti, dict):
            raise ValueError("not an object")
    except (ValueError, OSError) as e:
        print(f"--input must be a JSON object ({e})", file=sys.stderr)
        return 2
    print(json.dumps(evaluate(a.tool, ti, member=a.member, host_agent=a.host_agent, cwd=a.cwd,
                              session_id=a.session, shim_path=a.shim, shared_dir=a.shared_dir),
                     indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
