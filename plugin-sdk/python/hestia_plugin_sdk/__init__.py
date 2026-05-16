"""hestia-plugin-sdk — Phase 0 skeleton.

Authoring kit for Hestia plugins written in Python. A plugin hooks into the
host agent's tool-call lifecycle, builds R6/R7 records via this SDK, emits
them to the user's local Hestia instance over MCP, and optionally queries
for policy decisions and credentials.

Status: Phase 0 (skeleton). API will change as Phase 1 implementation lands.
Do not depend on this for production yet.

See docs/PLUGIN_AUTHORING_GUIDE.md in the repo root for the contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol

__version__ = "0.0.1"

PolicyDecision = Literal["allow", "deny", "warn"]


@dataclass(frozen=True)
class HestiaClientConfig:
    """Configuration for a HestiaClient instance."""

    plugin_id: str
    hestia_endpoint: str | None = None
    protocol_version: int = 0


@dataclass(frozen=True)
class ToolCallSpec:
    tool_name: str
    target: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    atp_stake: float | None = None


@dataclass(frozen=True)
class R6Action:
    """Opaque handle for an in-flight R6 action.

    Returned by HestiaClient.begin_action(); pass to record_outcome().
    """

    id: str
    tool_name: str
    started_at: datetime


@dataclass(frozen=True)
class Outcome:
    success: bool
    magnitude: float  # in [0..1]
    error: str | None = None
    result: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PolicyResult:
    decision: PolicyDecision
    reason: str
    policy_id: str | None = None


@dataclass(frozen=True)
class VaultGetOptions:
    scope: list[str]
    reason: str | None = None


@dataclass(frozen=True)
class TrustState:
    t3_talent: float
    t3_training: float
    t3_temperament: float
    v3_valuation: float
    v3_veracity: float
    v3_validity: float
    level: str
    action_count: int
    days_since_last: float


class HestiaClient(Protocol):
    """Protocol defining the Hestia plugin client interface.

    Implementations connect to the user's local Hestia instance over MCP.
    """

    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def begin_action(self, spec: ToolCallSpec) -> R6Action: ...
    async def record_outcome(self, action: R6Action, outcome: Outcome) -> None: ...
    async def query_policy(self, action: R6Action) -> PolicyResult: ...
    async def vault_get(self, name: str, options: VaultGetOptions) -> str: ...
    async def get_shared_context(self) -> dict[str, Any]: ...
    async def get_own_trust_state(self) -> TrustState: ...


def create_hestia_client(_config: HestiaClientConfig) -> HestiaClient:
    """Create a Hestia client.

    Phase 0: raises NotImplementedError.
    Phase 1: returns a real MCP-backed client.
    """
    raise NotImplementedError(
        "hestia-plugin-sdk: Phase 0 skeleton — implementation lands in Phase 1. "
        "See https://github.com/dp-web4/hestia for status."
    )


__all__ = [
    "HestiaClient",
    "HestiaClientConfig",
    "ToolCallSpec",
    "R6Action",
    "Outcome",
    "PolicyDecision",
    "PolicyResult",
    "VaultGetOptions",
    "TrustState",
    "create_hestia_client",
    "__version__",
]
