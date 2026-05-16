"""hestia-plugin-sdk — Python plugin authoring kit for Hestia.

See README.md and docs/PLUGIN_AUTHORING_GUIDE.md in the Hestia repo for
the plugin contract.

Quickstart::

    from hestia_plugin_sdk import (
        HestiaClient, HestiaClientConfig, ToolCallSpec, Outcome,
    )

    config = HestiaClientConfig(plugin_id="my-plugin", host_agent="my-agent")
    async with HestiaClient(config) as hestia:
        action = await hestia.begin_action(
            ToolCallSpec(tool_name="file_write", target="/tmp/x")
        )
        policy = await hestia.query_policy(action)
        if policy.decision == "deny":
            return {"error": policy.reason}
        # ... execute the tool ...
        await hestia.record_outcome(action, Outcome(success=True, magnitude=0.5))
"""

from __future__ import annotations

__version__ = "0.0.2"

from .client import HestiaClient, create_hestia_client
from .errors import (
    ActionNotFoundError,
    HestiaError,
    InvalidRoleError,
    NotConnectedError,
    PolicyDeniedError,
    SessionExpiredError,
    VaultDeniedError,
    VaultNotFoundError,
    VaultScopeMismatchError,
    map_hestia_error,
)
from .transport import DEFAULT_HESTIA_ENDPOINT, discover_hestia_endpoint
from .types import (
    HESTIA_PROTOCOL_VERSION,
    ConnectResult,
    HestiaClientConfig,
    HistoryFilter,
    HistoryResult,
    Outcome,
    OutcomeResult,
    PolicyDecision,
    PolicyResult,
    R6Action,
    ToolCallSpec,
    TrustState,
    VaultGetOptions,
    VaultSetOptions,
    VaultValue,
    WitnessEntry,
)

__all__ = [
    "__version__",
    # Client
    "HestiaClient",
    "create_hestia_client",
    # Config + lifecycle
    "HestiaClientConfig",
    "ConnectResult",
    "HESTIA_PROTOCOL_VERSION",
    # R6 lifecycle
    "ToolCallSpec",
    "R6Action",
    "Outcome",
    "OutcomeResult",
    # Policy
    "PolicyDecision",
    "PolicyResult",
    # Vault
    "VaultGetOptions",
    "VaultSetOptions",
    "VaultValue",
    # Trust + witness
    "TrustState",
    "WitnessEntry",
    "HistoryFilter",
    "HistoryResult",
    # Transport
    "DEFAULT_HESTIA_ENDPOINT",
    "discover_hestia_endpoint",
    # Errors
    "HestiaError",
    "NotConnectedError",
    "SessionExpiredError",
    "PolicyDeniedError",
    "VaultDeniedError",
    "VaultNotFoundError",
    "VaultScopeMismatchError",
    "ActionNotFoundError",
    "InvalidRoleError",
    "map_hestia_error",
]
