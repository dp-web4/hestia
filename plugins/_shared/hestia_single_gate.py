#!/usr/bin/env python3
"""The ONE Hestia gate orchestrator.

Harness shims translate syntax into :class:`GateEvent`, call :func:`decide`, and translate
:class:`GateDecision` back to the harness blocking protocol.  They do not sequence policy.

This module deliberately sits above the transport-free law core (hestia_gate_core), the
daemon transport (hestia_gate_mechanism), and the governance-closure classifier.  Those
modules remain independently testable; this module owns their ORDER and therefore owns the
governance decision path.

There is no per-seat warn/enforce switch here.  Enforcement posture is law, not harness
configuration.  A seat environment cannot select which law applies to itself.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import hestia_gate_core as core
import hestia_gate_mechanism as mechanism
import hestia_governance_closure as closure

GATE_API_VERSION = "1"
_ACTION_CACHE_DIR = Path("/tmp/hestia-actions")


@dataclass(frozen=True)
class GateProfile:
    """Harness facts only.  No policy or enforcement posture belongs here."""

    member_id: str
    identity_path: str
    home_markers: tuple = ()
    launch_cwd_env: str = ""
    workspace_env: str = "HESTIA_WORKSPACE"
    forbidden_extra_env: str = "HESTIA_FORBIDDEN_EXTRA"
    default_role: str = "role:constellation:member"
    host_agent: str = ""
    client_name: str = ""
    gate_path: str = ""
    observe_dir: str = ""
    attest_every: int = 200

    def core_profile(self) -> core.HarnessProfile:
        return core.HarnessProfile(
            member_id=self.member_id,
            identity_path=self.identity_path,
            home_markers=self.home_markers,
            launch_cwd_env=self.launch_cwd_env,
            # Explicitly empty: a per-seat mode selector is per-seat law.
            mode_env="",
            workspace_env=self.workspace_env,
            forbidden_extra_env=self.forbidden_extra_env,
            default_role=self.default_role,
        )


@dataclass
class GateEvent:
    """Canonical harness event.  Shims may translate names/keys, never judge them."""

    tool: str
    tool_input: dict = field(default_factory=dict)
    cwd: Optional[str] = None
    session_id: Optional[str] = None
    tool_use_id: Optional[str] = None
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True)
class GateDecision:
    decision: str                 # allow | warn | deny
    rule: str = ""
    reason: str = ""
    remedy: str = ""
    verdict_available: bool = True
    action_id: Optional[str] = None
    anomaly: bool = False         # infrastructure/no-verdict, not member conduct

    @property
    def blocks(self) -> bool:
        return self.decision == "deny"


def gate_artifact_digest() -> str:
    """Digest the exact shared decision surface this shim certification depends on."""
    h = hashlib.sha256()
    for mod in (core, mechanism, closure):
        try:
            p = Path(mod.__file__).resolve()
            h.update(p.name.encode("utf-8"))
            h.update(b"\0")
            h.update(p.read_bytes())
            h.update(b"\0")
        except Exception:
            h.update(b"UNREADABLE\0")
    try:
        h.update(Path(__file__).resolve().read_bytes())
    except Exception:
        h.update(b"UNREADABLE-ORCHESTRATOR")
    return h.hexdigest()


def _strings(value: Any, depth: int = 0) -> list[str]:
    if isinstance(value, str):
        return [value]
    if depth > 4:
        return []
    if isinstance(value, (list, tuple)):
        return [s for item in value for s in _strings(item, depth + 1)]
    if isinstance(value, dict):
        return [s for item in value.values() for s in _strings(item, depth + 1)]
    return []


def _command_of(tool_input: dict) -> Optional[str]:
    value = tool_input.get("command") if isinstance(tool_input, dict) else None
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(str(x) for x in value)
    return None


def _apply_patch_targets(tool: str, tool_input: dict) -> list[str]:
    if tool.lower() != "apply_patch" or not isinstance(tool_input, dict):
        return []
    blob = next((tool_input.get(k) for k in ("input", "command", "patch")
                 if isinstance(tool_input.get(k), str)), "")
    return [m.group(1) for m in re.finditer(
        r"^\*\*\*\s+(?:Add|Update|Delete)\s+File:\s*(.+?)\s*$", blob, re.MULTILINE)]


def _mcp_repo_target(tool_input: dict) -> Optional[str]:
    if not isinstance(tool_input, dict):
        return None
    for key in ("repository_full_name", "repo_full_name", "repository", "repo"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().rstrip("/").split("/")[-1]
    return None


def _extra_egress_strings(event: GateEvent) -> list[str]:
    """Network/MCP strings that are egress evidence but are not filesystem paths."""
    ti = event.tool_input if isinstance(event.tool_input, dict) else {}
    out: list[str] = []
    low = event.tool.lower()
    if low in ("webfetch", "websearch", "web_fetch", "google_web_search"):
        for key in ("url", "urls", "prompt", "query"):
            out.extend(_strings(ti.get(key)))
    mcp = ti.get("_hestia_mcp_context")
    if isinstance(mcp, dict):
        out.extend(_strings(mcp.get("command")))
        out.extend(_strings(mcp.get("args")))
        out.extend(_strings(mcp.get("url")))
    return out


def _normalized(event: GateEvent) -> core.NormalizedEvent:
    paths = core.path_targets(event.tool, event.tool_input)
    paths.extend(_apply_patch_targets(event.tool, event.tool_input))
    # preserve order but remove duplicate targets produced by shape translation + key table
    paths = list(dict.fromkeys(str(p) for p in paths if isinstance(p, str) and p))
    repo = _mcp_repo_target(event.tool_input) if event.tool.startswith("mcp__") else None
    raw = dict(event.raw or {})
    raw.update({
        "tool_name": event.tool,
        "tool_input": event.tool_input,
        "cwd": event.cwd,
        "session_id": event.session_id,
    })
    if event.tool_use_id:
        raw["tool_use_id"] = event.tool_use_id
    return core.NormalizedEvent(
        tool=event.tool,
        paths=paths,
        repos=([repo] if repo else []),
        command=_command_of(event.tool_input),
        cwd=event.cwd,
        raw=raw,
    )


_CREDENTIAL_KEYS = (
    "password", "passwd", "secret", "token", "api_key", "apikey", "api-key", "auth",
    "authorization", "bearer", "credential", "private_key", "passphrase", "access_key",
    "client_secret",
)


def attempted_summary(event: GateEvent, limit: int = 400) -> str:
    """Bounded and scrubbed WHAT for witnesses/escalations; never copy an unbounded payload."""
    ti = event.tool_input if isinstance(event.tool_input, dict) else {}
    raw: Any = ti.get("command") or ti.get("file_path") or ti.get("path") or ""
    if not raw and ti:
        try:
            raw = json.dumps(ti, sort_keys=True, default=str)
        except Exception:
            raw = str(ti)
    text = " ".join(str(raw).split())
    out: list[str] = []
    mask_next = False
    for token in text.split(" "):
        low = token.lstrip("-").rstrip(":").lower()
        if mask_next and not token.startswith("-"):
            out.append("***")
            mask_next = False
            continue
        if "=" in token:
            key, _, _ = token.partition("=")
            if any(s in key.lstrip("-").lower() for s in _CREDENTIAL_KEYS):
                out.append(key + "=***")
                mask_next = False
                continue
        mask_next = low in _CREDENTIAL_KEYS
        out.append(token)
    scrubbed = " ".join(out)
    return scrubbed[:limit] + ("...[truncated]" if len(scrubbed) > limit else "")


def _target(event: GateEvent) -> Optional[str]:
    try:
        return mechanism._extract_target(event.tool_input, event.tool)
    except Exception:
        paths = core.path_targets(event.tool, event.tool_input)
        return paths[0] if paths else _command_of(event.tool_input)


def _role(profile: GateProfile, snapshot_role: Optional[str] = None) -> str:
    try:
        return mechanism.role_bridge(snapshot_role=snapshot_role,
                                     identity_path=profile.identity_path)
    except Exception:
        return profile.default_role


def _record(profile: GateProfile, event: GateEvent, *, decision: str, rule: str,
            verdict_available: bool, attempted: Optional[str] = None) -> bool:
    """Every final decision takes the same witness path.  Recording never changes the verdict."""
    try:
        return bool(mechanism.witness_decision_unified(
            None,
            plugin_id=profile.member_id,
            decision=decision,
            rule=rule,
            tool_name=event.tool,
            target=_target(event),
            session_id=event.session_id,
            verdict_available=verdict_available,
            attempted_summary=attempted if attempted is not None else attempted_summary(event),
        ))
    except Exception:
        return False


def _tally(profile: GateProfile, allowed: bool, role: str) -> None:
    if not profile.observe_dir:
        return
    try:
        tally_dir = os.path.expanduser(profile.observe_dir)
        mechanism.tally_scope(
            allowed,
            tally_dir=tally_dir,
            tally_path=os.path.join(tally_dir, "scope-tally.json"),
            attest_every=profile.attest_every,
            plugin_id=profile.member_id,
            role_lct=role,
        )
    except Exception:
        pass


def _cache_action(event: GateEvent, action_id: Optional[str]) -> None:
    if not action_id or not event.tool_use_id:
        return
    try:
        _ACTION_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = _ACTION_CACHE_DIR / (str(event.tool_use_id) + ".json")
        path.write_text(json.dumps({"action_id": action_id, "tool_name": event.tool}),
                        encoding="utf-8")
    except Exception:
        pass


def _deny_from_core(profile: GateProfile, event: GateEvent, verdict: core.Verdict,
                    *, verdict_available: bool = True, anomaly: bool = False) -> GateDecision:
    _record(profile, event, decision="deny", rule=verdict.rule,
            verdict_available=verdict_available)
    _tally(profile, False, _role(profile))
    return GateDecision("deny", verdict.rule, verdict.reason, verdict.remedy,
                        verdict_available=verdict_available, anomaly=anomaly)


def _egress_precheck(event: GateEvent, cprofile: core.HarnessProfile) -> Optional[core.Verdict]:
    forbidden = core.forbidden_tokens(cprofile)
    for blob in _extra_egress_strings(event):
        low = blob.lower()
        for token in forbidden:
            if token in low:
                return core._deny(
                    "egress.secret",
                    f"'{event.tool}' carries a forbidden secret/credential token through an "
                    f"egress surface: '{token}'",
                    innate=True,
                )
    return None


def decide(event: GateEvent, profile: GateProfile) -> GateDecision:
    """ONE decision sequence for every harness.

    Order is law-bearing and intentionally centralized:
      governance closure -> live policy/local scope+egress -> degraded posture OR society
      safety -> witness/tally -> return.

    Any unexpected exception becomes an infrastructure denial.  A broken gate never becomes
    a harness-specific allow path.
    """
    try:
        if not isinstance(event, GateEvent):
            raise TypeError("decide requires GateEvent")
        if os.environ.get("HESTIA_TEST_SABOTAGE"):
            raise RuntimeError("HESTIA_TEST_SABOTAGE: injected decision-time fault")

        cprofile = profile.core_profile()
        normalized = _normalized(event)
        attempted = attempted_summary(event)

        # Gate 1c: governance closure first, independent of daemon availability.
        cv = closure.classify(event.tool, event.tool_input, cwd=event.cwd)
        if cv.classification == "read":
            try:
                mechanism.witness_gate_self(
                    "gate_self_read", cv.marker or cv.rule or "governance", event.tool, cv.rule,
                    plugin_id=profile.member_id,
                    role=_role(profile),
                    gate_path=profile.gate_path or "",
                    client_name=profile.client_name or ("hestia-" + profile.member_id + "-gate"),
                    host_session_id=event.session_id,
                )
            except Exception:
                pass
        elif cv.classification == "write":
            marker = cv.marker or cv.rule or "governance"
            try:
                claimed, detail, esc_id, how = mechanism.claim_self_write(
                    marker, event.tool, attempted,
                    plugin_id=profile.member_id,
                    role=_role(profile),
                    client_name=profile.client_name or ("hestia-" + profile.member_id + "-gate"),
                    host_session_id=event.session_id,
                )
            except Exception:
                claimed, detail, esc_id, how = (
                    "unreachable", "no answer from the daemon - refused", None, None)
            if claimed != "approved":
                try:
                    mechanism.witness_gate_self(
                        "gate_self_access", marker, event.tool, cv.rule,
                        plugin_id=profile.member_id,
                        role=_role(profile),
                        gate_path=profile.gate_path or "",
                        client_name=profile.client_name or ("hestia-" + profile.member_id + "-gate"),
                        host_session_id=event.session_id,
                    )
                except Exception:
                    pass
                esc = (f" Escalation {esc_id} is open ({how}); re-issue after approval."
                       if esc_id else "")
                v = core._deny(
                    "gate.self_access",
                    f"'{event.tool}' would WRITE the governance surface "
                    f"({cv.resource or marker}; rule {cv.rule or 'gate-self'}; {detail}).{esc}",
                    innate=True,
                )
                return _deny_from_core(profile, event, v)

        # Network/MCP egress strings are not filesystem paths, so check them separately before
        # core.evaluate() rather than feeding URLs into path scope.
        extra_egress = _egress_precheck(event, cprofile)
        if extra_egress is not None:
            return _deny_from_core(profile, event, extra_egress)

        snapshot = mechanism.fetch_policy_snapshot(
            profile.member_id,
            host_agent=profile.host_agent or profile.member_id,
            host_session_id=event.session_id,
        )

        if snapshot is None:
            # The ratified common degraded posture.  There is no per-seat warn mode and no
            # member-writable replica on this path.
            degraded = core.degraded_verdict(normalized, cprofile)
            if degraded.blocks:
                return _deny_from_core(
                    profile, event, degraded,
                    verdict_available=bool(degraded.innate),
                    anomaly=not degraded.innate,
                )
            try:
                core.record_gate_unavailable(
                    profile.member_id, event.tool, "unknown",
                    "degraded: policy snapshot fetch failed (allow-read)")
            except Exception:
                pass
            _record(profile, event, decision="allow", rule="gate.degraded.allow_read",
                    verdict_available=False)
            _tally(profile, True, _role(profile))
            return GateDecision("allow", "gate.degraded.allow_read",
                                "read permitted by the ratified degraded posture",
                                verdict_available=False, anomaly=True)

        snapshot_role = snapshot.get("role") if isinstance(snapshot, dict) else None
        role = _role(profile, snapshot_role if isinstance(snapshot_role, str) else None)
        policy = core.resolve_agent_policy(cprofile, vault_reader=lambda _member: snapshot)
        local = core.evaluate(normalized, cprofile, core.detect_workspace(cprofile), policy=policy)
        if local.blocks:
            return _deny_from_core(profile, event, local)

        # Read-class acts are completely decided by the shared local law.  Consequential acts
        # additionally require a society-safety verdict.
        if normalized.tool in core.READ_CLASS:
            _record(profile, event, decision="allow", rule="gate.allow",
                    verdict_available=True)
            _tally(profile, True, role)
            return GateDecision("allow", "gate.allow")

        safety = mechanism.query_society_safety(
            normalized.raw,
            plugin_id=profile.member_id,
            host_agent=profile.host_agent or profile.member_id,
            host_session_id=event.session_id,
        )
        _cache_action(event, safety.action_id)
        if not safety.allow:
            if safety.decided:
                v = core._deny("society.safety",
                               safety.message or "society law refused the act")
                _record(profile, event, decision="deny", rule="society.safety",
                        verdict_available=True)
                _tally(profile, False, role)
                return GateDecision("deny", "society.safety", v.reason, v.remedy,
                                    verdict_available=True, action_id=safety.action_id)
            v = core._deny("society.unreachable",
                           safety.message or "no usable society-safety verdict")
            _record(profile, event, decision="deny", rule="society.unreachable",
                    verdict_available=False)
            _tally(profile, False, role)
            return GateDecision("deny", "society.unreachable", v.reason, v.remedy,
                                verdict_available=False, action_id=safety.action_id, anomaly=True)

        kind = safety.kind if safety.kind in ("allow", "warn") else "allow"
        rule = "society.safety.warn" if kind == "warn" else "gate.allow"
        _record(profile, event, decision=kind, rule=rule, verdict_available=True)
        _tally(profile, True, role)
        return GateDecision(kind, rule, safety.message or "", "",
                            verdict_available=True, action_id=safety.action_id)

    except BaseException as exc:
        # Catch SystemExit too: the shared gate is a value-returning API and must never let a
        # dependency terminate a fail-open harness process before the shim can emit a block.
        detail = f"{type(exc).__name__}: {exc}"
        try:
            _record(profile, event, decision="deny", rule="gate.internal_error",
                    verdict_available=False, attempted=detail[:200])
        except Exception:
            pass
        return GateDecision(
            "deny", "gate.internal_error",
            "the common gate could not complete the decision: " + detail,
            "This is an infrastructure fault, not a judgement of the attempted act. "
            "The gate fails closed until the decision path is healthy.",
            verdict_available=False,
            anomaly=True,
        )
