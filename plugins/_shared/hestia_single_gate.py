"""The one Hestia gate orchestrator.

Harness shims translate syntax into GateEvent, call decide(), and translate GateDecision
back to the harness protocol. They do not sequence governance.

Two invariants are load-bearing here:

1. ONE INVOCATION, ONE DEADLINE. The shortest measured harness deadline is 4 s. The common
   gate owns a 3 s absolute deadline and clamps every daemon client/poll to it. Helper-local
   budgets and per-seat environment variables cannot mint fresh time.
2. EFFECT-PERMITTING DECISIONS NEED COMMITTED EVIDENCE. A write/exec allow or warn is not
   returned if the canonical decision witness cannot be committed. Denies still stand when
   the witness plane is unavailable, with explicit Plane-E fallback evidence. Read allows
   preserve the ratified degraded-read posture but surface evidence_committed=False.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field, replace
import hashlib
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Optional

import hestia_gate_core as core
import hestia_gate_mechanism as mechanism
import hestia_governance_closure as closure

GATE_API_VERSION = "decide/1"
GATE_DEADLINE_SECONDS = 3.0
_ACTION_CACHE_DIR = Path("/tmp/hestia-actions")


@dataclass(frozen=True)
class GateProfile:
    """Harness facts only. No law or enforcement posture belongs here."""

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
            # Deliberately empty. A seat-selectable mode is seat-selectable law.
            mode_env="",
            workspace_env=self.workspace_env,
            forbidden_extra_env=self.forbidden_extra_env,
            default_role=self.default_role,
        )


@dataclass
class GateEvent:
    """Canonical harness event. Shims translate names/keys, never judge them."""

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
    evidence_committed: bool = False

    @property
    def blocks(self) -> bool:
        return self.decision == "deny"


def gate_artifact_digest() -> str:
    """Diagnostic digest of the loaded law-bearing modules, never a certification oracle."""
    h = hashlib.sha256()
    modules = (core, mechanism, closure)
    for mod in modules:
        try:
            path = Path(mod.__file__).resolve()
            h.update(path.name.encode("utf-8")); h.update(b"\0")
            h.update(path.read_bytes()); h.update(b"\0")
        except Exception:
            h.update(b"UNREADABLE\0")
    try:
        h.update(Path(__file__).resolve().read_bytes())
    except Exception:
        h.update(b"UNREADABLE-ORCHESTRATOR")
    return h.hexdigest()


def _remaining(deadline: float) -> float:
    return max(0.0, deadline - time.monotonic())


@contextmanager
def _one_deadline(deadline: float):
    """Clamp every mechanism-created client/poll to one absolute invocation deadline.

    The older mechanism owns several useful operations, but historically each one minted a
    fresh TOTAL_BUDGET_MS window. A single hook could therefore consume that budget several
    times and lose the race to the harness's own timeout. We do not lower each helper's
    budget; we remove its authority to mint time.

    The mechanism is process-local in a short-lived hook. Restore everything anyway so the
    contract remains testable and nested callers do not inherit hidden state.
    """
    old_client = mechanism._McpHttp
    old_poll = getattr(mechanism, "_poll_policy", None)
    old_budget = mechanism.TOTAL_BUDGET_MS
    old_request_timeout = mechanism.REQUEST_TIMEOUT_S

    def bounded_client(endpoint, requested_deadline):
        return old_client(endpoint, min(float(requested_deadline), deadline))

    def bounded_poll(client, action_id, session_id, requested_deadline):
        return old_poll(client, action_id, session_id,
                        min(float(requested_deadline), deadline))

    mechanism._McpHttp = bounded_client
    if old_poll is not None:
        mechanism._poll_policy = bounded_poll
    # Ignore seat/env-selected transport posture while this decision is active. These are
    # mechanism limits, not law. The absolute deadline above remains the real authority.
    mechanism.TOTAL_BUDGET_MS = max(1, int(_remaining(deadline) * 1000))
    mechanism.REQUEST_TIMEOUT_S = max(0.05, _remaining(deadline))
    try:
        yield
    finally:
        mechanism._McpHttp = old_client
        if old_poll is not None:
            mechanism._poll_policy = old_poll
        mechanism.TOTAL_BUDGET_MS = old_budget
        mechanism.REQUEST_TIMEOUT_S = old_request_timeout


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
    """Bounded/scrubbed WHAT. Full act identity is a separate versioned binding problem."""
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
            out.append("***"); mask_next = False; continue
        if "=" in token:
            key, _, _value = token.partition("=")
            if any(s in key.lstrip("-").lower() for s in _CREDENTIAL_KEYS):
                out.append(key + "=***"); mask_next = False; continue
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


def _plane_e_path(plugin_id: str) -> Path:
    home = Path(os.path.expanduser(os.getenv("HESTIA_HOME", "~/.hestia")))
    safe = "".join(c if c.isalnum() or c in "-_." else "-" for c in (plugin_id or "unknown"))
    return home / "telemetry" / f"gate-decisions-{safe}.jsonl"


def _plane_e(profile: GateProfile, event: GateEvent, record: dict, error: str) -> None:
    """Durable local fallback when canonical witnessing is unavailable. Never raises."""
    try:
        row = dict(record)
        row["canonical_witness_committed"] = False
        row["witness_delivery_failed"] = error[:400]
        row["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        path = _plane_e_path(profile.member_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str, sort_keys=True) + "\n")
    except BaseException:
        pass


def _record(profile: GateProfile, event: GateEvent, *, decision: str, rule: str,
            verdict_available: bool, deadline: float,
            attempted: Optional[str] = None) -> bool:
    """Commit one canonical decision witness, or leave explicit Plane-E evidence.

    This is deliberately not the historical deny-only helper: allows use the same path.
    Returns True only when the daemon acknowledged the canonical witness.
    """
    record = {
        "plugin_id": profile.member_id,
        "decision": decision,
        "rule": (rule or "")[:300],
        "tool_name": event.tool or "",
        "target": _target(event),
        "session_id": event.session_id,
        "verdict_available": bool(verdict_available),
        "attempted": attempted if attempted is not None else attempted_summary(event),
        "gate_api_version": GATE_API_VERSION,
    }
    try:
        if _remaining(deadline) <= 0:
            raise TimeoutError("common gate deadline exhausted before witness")
        endpoint = mechanism._discover_endpoint()
        if endpoint is None:
            raise RuntimeError("no daemon endpoint discovered")
        client = mechanism._McpHttp(endpoint, deadline)
        if "result" not in client.initialize():
            raise RuntimeError("initialize failed")
        client.initialized()
        out = client.call_tool("hestia_witness_decision", {
            "plugin_id": profile.member_id,
            "decision": decision,
            "adjudicator": f"plugin-gate:{profile.member_id}",
            "reason": (rule or "")[:300],
            "verdict_available": bool(verdict_available),
            "tool_name": event.tool or "",
            "target": record["target"],
            "session_id": event.session_id,
            "attempted": record["attempted"],
            "gate_api_version": GATE_API_VERSION,
        })
        if not (isinstance(out, dict) and "result" in out):
            raise RuntimeError("witness call returned no result")
        return True
    except BaseException as exc:
        _plane_e(profile, event, record, f"{type(exc).__name__}: {exc}")
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


def _finalize(profile: GateProfile, event: GateEvent, decision: GateDecision,
              deadline: float, *, require_commit: bool = False,
              role: Optional[str] = None) -> GateDecision:
    committed = _record(
        profile, event,
        decision=decision.decision,
        rule=decision.rule,
        verdict_available=decision.verdict_available,
        deadline=deadline,
    )
    _tally(profile, decision.decision != "deny", role or _role(profile))

    if require_commit and decision.decision in ("allow", "warn") and not committed:
        # The effect has NOT been permitted yet. Convert the unrecordable permit into an
        # infrastructure denial instead of allowing state to outrun its evidence.
        denied = GateDecision(
            "deny",
            "gate.evidence_uncommitted",
            "the decision witness could not be committed before the common deadline",
            "Retry when the canonical witness path is healthy.",
            verdict_available=False,
            action_id=decision.action_id,
            anomaly=True,
            evidence_committed=False,
        )
        _plane_e(profile, event, {
            "plugin_id": profile.member_id,
            "decision": "deny",
            "rule": denied.rule,
            "tool_name": event.tool,
            "target": _target(event),
            "session_id": event.session_id,
            "verdict_available": False,
            "attempted": attempted_summary(event),
            "supersedes_uncommitted": decision.decision,
        }, "canonical evidence required before consequential effect")
        return denied

    if committed:
        return replace(decision, evidence_committed=True)
    # A fail-closed decision may have only Plane-E evidence when the daemon is unavailable.
    # Preserve the decision but make the evidence state explicit. Read allows preserve the
    # ratified degraded-read posture and surface the infrastructure anomaly.
    return replace(decision, evidence_committed=False,
                   anomaly=(decision.anomaly or decision.decision == "allow"))


def _egress_precheck(event: GateEvent, cprofile: core.HarnessProfile) -> Optional[core.Verdict]:
    forbidden = core.forbidden_tokens(cprofile)
    for blob in _extra_egress_strings(event):
        low = blob.lower()
        for token in forbidden:
            if token in low:
                return core._deny(
                    "egress.secret",
                    f"'{event.tool}' carries a forbidden secret/credential token through an egress surface: '{token}'",
                    innate=True,
                )
    return None


def _fetch_snapshot(profile: GateProfile, event: GateEvent, deadline: float) -> Optional[dict]:
    """At most two attempts, both inside the one common deadline."""
    snap = mechanism._fetch_policy_snapshot_once(
        profile.member_id,
        host_agent=profile.host_agent or profile.member_id,
        host_session_id=event.session_id,
    )
    if snap is not None:
        return snap
    remaining = _remaining(deadline)
    if remaining <= 0.30:
        return None
    time.sleep(min(0.25, max(0.0, remaining - 0.05)))
    if _remaining(deadline) <= 0.05:
        return None
    return mechanism._fetch_policy_snapshot_once(
        profile.member_id,
        host_agent=profile.host_agent or profile.member_id,
        host_session_id=event.session_id,
        use_cache=False,
    )


def decide(event: GateEvent, profile: GateProfile) -> GateDecision:
    """One law-bearing sequence for every harness."""
    deadline = time.monotonic() + GATE_DEADLINE_SECONDS
    try:
        if not isinstance(event, GateEvent):
            raise TypeError("decide requires GateEvent")
        cprofile = profile.core_profile()
        normalized = _normalized(event)
        attempted = attempted_summary(event)

        with _one_deadline(deadline):
            # Governance closure is evaluated before ordinary policy. Approval of the
            # closure write removes only the closure bar; ordinary law still runs below.
            cv = closure.classify(event.tool, event.tool_input, cwd=event.cwd)
            if cv.classification == "read":
                try:
                    mechanism.witness_gate_self(
                        "gate_self_read", cv.marker or cv.rule or "governance",
                        event.tool, cv.rule,
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
                        "unreachable", "no answer from daemon - refused", None, None)
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
                    d = GateDecision(
                        "deny", "gate.self_access",
                        f"'{event.tool}' would WRITE the governance surface "
                        f"({cv.resource or marker}; rule {cv.rule or 'gate-self'}; {detail}).{esc}",
                    )
                    return _finalize(profile, event, d, deadline)

            extra_egress = _egress_precheck(event, cprofile)
            if extra_egress is not None:
                d = GateDecision("deny", extra_egress.rule, extra_egress.reason,
                                 extra_egress.remedy, verdict_available=True)
                return _finalize(profile, event, d, deadline)

            snapshot = _fetch_snapshot(profile, event, deadline)
            if snapshot is None:
                degraded = core.degraded_verdict(normalized, cprofile)
                if degraded.blocks:
                    innate = bool(getattr(degraded, "innate", False))
                    d = GateDecision(
                        "deny", degraded.rule, degraded.reason, degraded.remedy,
                        verdict_available=innate, anomaly=not innate,
                    )
                    return _finalize(profile, event, d, deadline)
                try:
                    core.record_gate_unavailable(
                        profile.member_id, event.tool, "unknown",
                        "degraded: policy snapshot fetch failed (allow-read)")
                except Exception:
                    pass
                d = GateDecision(
                    "allow", "gate.degraded.allow_read",
                    "read permitted by the ratified degraded posture",
                    verdict_available=False, anomaly=True,
                )
                return _finalize(profile, event, d, deadline, require_commit=False)

            snapshot_role = snapshot.get("role") if isinstance(snapshot, dict) else None
            role = _role(profile, snapshot_role if isinstance(snapshot_role, str) else None)
            policy = core.resolve_agent_policy(cprofile, vault_reader=lambda _member: snapshot)
            local = core.evaluate(normalized, cprofile, core.detect_workspace(cprofile), policy=policy)
            if local.blocks:
                d = GateDecision("deny", local.rule, local.reason, local.remedy)
                return _finalize(profile, event, d, deadline, role=role)

            if normalized.tool in core.READ_CLASS:
                return _finalize(
                    profile, event, GateDecision("allow", "gate.allow"), deadline,
                    require_commit=False, role=role,
                )

            safety = mechanism.query_society_safety(
                normalized.raw,
                plugin_id=profile.member_id,
                host_agent=profile.host_agent or profile.member_id,
                host_session_id=event.session_id,
            )
            _cache_action(event, safety.action_id)
            if not safety.allow:
                if safety.decided:
                    d = GateDecision(
                        "deny", "society.safety",
                        safety.message or "society law refused the act",
                        action_id=safety.action_id,
                    )
                    return _finalize(profile, event, d, deadline, role=role)
                d = GateDecision(
                    "deny", "society.unreachable",
                    safety.message or "no usable society-safety verdict",
                    verdict_available=False, action_id=safety.action_id, anomaly=True,
                )
                return _finalize(profile, event, d, deadline, role=role)

            kind = safety.kind if safety.kind in ("allow", "warn") else "allow"
            rule = "society.safety.warn" if kind == "warn" else "gate.allow"
            d = GateDecision(
                kind, rule, safety.message or "", "",
                verdict_available=True, action_id=safety.action_id,
            )
            # This path permits a write/exec effect. Evidence must commit first.
            return _finalize(profile, event, d, deadline, require_commit=True, role=role)

    except BaseException as exc:
        detail = f"{type(exc).__name__}: {exc}"
        d = GateDecision(
            "deny", "gate.internal_error",
            "the common gate could not complete the decision: " + detail,
            "This is an infrastructure fault, not a judgement of the attempted act. "
            "The gate fails closed until the decision path is healthy.",
            verdict_available=False, anomaly=True,
        )
        try:
            with _one_deadline(deadline):
                return _finalize(profile, event, d, deadline)
        except BaseException:
            try:
                _plane_e(profile, event, {
                    "plugin_id": getattr(profile, "member_id", "unknown"),
                    "decision": "deny",
                    "rule": d.rule,
                    "tool_name": getattr(event, "tool", "unknown"),
                    "verdict_available": False,
                    "attempted": detail[:200],
                }, "common gate exception path could not reach canonical witness")
            except BaseException:
                pass
            return d
