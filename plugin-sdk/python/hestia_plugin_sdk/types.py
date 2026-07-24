"""Type definitions for the Hestia plugin SDK (Python).

Mirrors the TypeScript reference. See ADR-0005 in the repo root for the
canonical MCP surface specification.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

#: Protocol version this SDK targets.
HESTIA_PROTOCOL_VERSION: int = 1

#: Policy decision returned by `query_policy`.
PolicyDecision = Literal["allow", "deny", "warn"]


@dataclass(frozen=True)
class HestiaClientConfig:
    """Configuration when creating a HestiaClient."""

    #: Stable identifier for this plugin (e.g. "claude-code", "openclaw").
    plugin_id: str
    #: Which agent client this plugin is for ("claude-code", "openclaw", ...).
    host_agent: str
    #: Optional semver of the plugin's own code.
    plugin_version: str | None = None
    #: Optional semver of the host agent.
    host_agent_version: str | None = None
    #: Society role this plugin wants. Defaults to "citizen".
    requested_role: str = "citizen"
    #: Override Hestia's MCP endpoint. If None, auto-discover.
    hestia_endpoint: str | None = None
    #: Declare this client as a test harness or other non-orchestrator
    #: workload. The daemon still witnesses every action, but excludes
    #: synthetic plugins from operator-facing aggregations (dashboards,
    #: trust roll-ups). See presence-protocol §3.1.
    synthetic: bool = False


@dataclass(frozen=True)
class ConnectResult:
    session_id: str
    soft_lct: str
    assigned_role: str
    protocol_version: int


@dataclass(frozen=True)
class ToolCallSpec:
    tool_name: str
    target: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    atp_stake: float | None = None


@dataclass(frozen=True)
class R6Action:
    """Handle for an in-flight R6/R7 action."""

    action_id: str
    tool_name: str
    started_at: datetime
    chain_position: int


@dataclass(frozen=True)
class ClosureClaim:
    """Explicit, scoped claim authored when closing an action."""

    claim_id: str
    statement: str
    scope: str
    confidence: float
    evidence: list[str]
    known_limitations: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Outcome:
    success: bool
    magnitude: float  # in [0..1]
    error: str | None = None
    result: dict[str, Any] = field(default_factory=dict)
    closure_claims: list[ClosureClaim] = field(default_factory=list)


@dataclass(frozen=True)
class TrustState:
    """Trust state for a single agent — flat-shape for Python ergonomics.

    The wire format is nested (`{t3: {talent, training, temperament}, v3: ...}`,
    see presence-protocol.md §5.5). The SDK flattens on deserialization.
    """
    # entity_id is `plugin:<id>` or similar — carries the Web4 entity-type prefix.
    entity_id: str
    t3_talent: float
    t3_training: float
    t3_temperament: float
    v3_valuation: float
    v3_veracity: float
    v3_validity: float
    level: str
    action_count: int
    success_count: int
    success_rate: float
    days_since_last: float


@dataclass(frozen=True)
class OutcomeResult:
    witness_entry_hash: str
    updated_trust_state: TrustState


@dataclass(frozen=True)
class PolicyResult:
    decision: PolicyDecision
    reason: str
    rule_id: str | None = None
    rule_name: str | None = None
    #: v0 alias of `rule_id`. New code should read `rule_id`.
    policy_id: str | None = None
    enforced: bool = True
    constraints: list[str] = field(default_factory=list)
    #: "decided" (default) = verdict is final.
    #: "evaluating" = engine is still working; orchestrator should wait
    #: `next_poll_ms` and re-query with the same action_id.
    #: See spec §3.4.1.
    status: Literal["decided", "evaluating"] = "decided"
    #: Suggested wait (ms) before re-querying. Only set when status == "evaluating".
    next_poll_ms: int | None = None


@dataclass(frozen=True)
class VaultGetOptions:
    scope: list[str]
    reason: str | None = None


@dataclass(frozen=True)
class VaultValue:
    value: str
    approval_token: str | None = None


@dataclass(frozen=True)
class VaultSetOptions:
    scope: list[str]
    allowed_consumers: list[str]
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WitnessEntry:
    hash: str
    prev_hash: str
    timestamp: str
    event_type: str
    event_data: dict[str, Any]
    signer_lct: str
    chain_position: int


@dataclass(frozen=True)
class HistoryFilter:
    tool_name: str | None = None
    target_pattern: str | None = None
    since: str | None = None  # ISO-8601 or relative ("1h", "30m", "2d")
    limit: int = 50
    outcome: Literal["success", "failure", "abandoned"] | None = None


@dataclass(frozen=True)
class HistoryResult:
    entries: list[WitnessEntry]
    has_more: bool
