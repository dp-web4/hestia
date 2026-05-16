"""HestiaClient — Python plugin SDK for talking to the Hestia daemon.

Async client backed by the Python `mcp` package's StreamableHTTP transport.
Mirrors the TypeScript reference. See ADR-0005 for the MCP surface spec.

Usage::

    from hestia_plugin_sdk import HestiaClient, HestiaClientConfig

    config = HestiaClientConfig(plugin_id="my-plugin", host_agent="my-agent")
    async with HestiaClient(config) as hestia:
        action = await hestia.begin_action(ToolCallSpec(tool_name="file_write"))
        policy = await hestia.query_policy(action)
        if policy.decision == "deny":
            ...
        await hestia.record_outcome(action, Outcome(success=True, magnitude=0.5))
"""

from __future__ import annotations

import json
from contextlib import AsyncExitStack
from datetime import datetime
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import McpError

from .errors import (
    HestiaError,
    NotConnectedError,
    map_hestia_error,
)
from .transport import discover_hestia_endpoint
from .types import (
    HESTIA_PROTOCOL_VERSION,
    ConnectResult,
    HestiaClientConfig,
    HistoryFilter,
    HistoryResult,
    Outcome,
    OutcomeResult,
    PolicyResult,
    R6Action,
    ToolCallSpec,
    TrustState,
    VaultGetOptions,
    VaultSetOptions,
    VaultValue,
    WitnessEntry,
)


class HestiaClient:
    """The MCP client wrapper that plugins use to talk to Hestia."""

    def __init__(self, config: HestiaClientConfig) -> None:
        self.config = config
        self._exit_stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._connect_result: ConnectResult | None = None

    async def __aenter__(self) -> HestiaClient:
        await self.connect()
        return self

    async def __aexit__(self, *_args: Any) -> None:
        await self.disconnect()

    # ---------------------------------------------------------- lifecycle ----

    async def connect(self) -> ConnectResult:
        """Establish the MCP connection and the Hestia session."""
        endpoint = discover_hestia_endpoint(self.config.hestia_endpoint)

        stack = AsyncExitStack()
        try:
            read, write, _get_sid = await stack.enter_async_context(
                streamable_http_client(endpoint)
            )
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
        except BaseException:
            await stack.aclose()
            raise

        self._exit_stack = stack
        self._session = session

        result = await self._call_tool_raw(
            "hestia_connect",
            {
                "plugin_id": self.config.plugin_id,
                "plugin_version": self.config.plugin_version,
                "host_agent": self.config.host_agent,
                "host_agent_version": self.config.host_agent_version,
                "requested_role": self.config.requested_role,
                "protocol_version": HESTIA_PROTOCOL_VERSION,
            },
        )

        connect_result = ConnectResult(
            session_id=result["sessionId"],
            soft_lct=result["softLct"],
            assigned_role=result["assignedRole"],
            protocol_version=int(result["protocolVersion"]),
        )
        self._connect_result = connect_result
        return connect_result

    async def disconnect(self) -> None:
        """Close the MCP connection and clean up streams."""
        if self._exit_stack is not None:
            try:
                await self._exit_stack.aclose()
            except (RuntimeError, OSError):
                # Tolerate cleanup races (e.g. transport already shut down by peer)
                pass
            self._exit_stack = None
            self._session = None
            self._connect_result = None

    # ----------------------------------------------------------- R6 flow ----

    async def begin_action(self, spec: ToolCallSpec) -> R6Action:
        result = await self._call_tool(
            "hestia_begin_action",
            {
                "tool_name": spec.tool_name,
                "target": spec.target,
                "parameters": spec.parameters,
                "atp_stake": spec.atp_stake,
            },
        )
        return R6Action(
            action_id=result["actionId"],
            tool_name=spec.tool_name,
            started_at=datetime.fromisoformat(result["startedAt"].replace("Z", "+00:00")),
            chain_position=int(result["chainPosition"]),
        )

    async def record_outcome(self, action: R6Action, outcome: Outcome) -> OutcomeResult:
        result = await self._call_tool(
            "hestia_record_outcome",
            {
                "action_id": action.action_id,
                "success": outcome.success,
                "magnitude": outcome.magnitude,
                "error": outcome.error,
                "result": outcome.result,
            },
        )
        ts = result["updatedTrustState"]
        trust = TrustState(
            t3_talent=ts["t3"]["talent"],
            t3_training=ts["t3"]["training"],
            t3_temperament=ts["t3"]["temperament"],
            v3_valuation=ts["v3"]["valuation"],
            v3_veracity=ts["v3"]["veracity"],
            v3_validity=ts["v3"]["validity"],
            level=ts["level"],
            action_count=int(ts["actionCount"]),
            days_since_last=float(ts["daysSinceLast"]),
        )
        return OutcomeResult(witness_entry_hash=result["witnessEntryHash"], updated_trust_state=trust)

    async def query_policy(
        self, action: R6Action, context: dict[str, Any] | None = None
    ) -> PolicyResult:
        result = await self._call_tool(
            "hestia_query_policy",
            {"action_id": action.action_id, "context": context},
        )
        return PolicyResult(
            decision=result["decision"],
            reason=result["reason"],
            policy_id=result.get("policyId"),
            enforced=bool(result.get("enforced", True)),
        )

    # ----------------------------------------------------------- vault ----

    async def vault_get(self, name: str, options: VaultGetOptions) -> VaultValue:
        result = await self._call_tool(
            "hestia_vault_get",
            {"name": name, "scope": options.scope, "reason": options.reason},
        )
        return VaultValue(value=result["value"], approval_token=result.get("approvalToken"))

    async def vault_set(
        self, name: str, value: str, options: VaultSetOptions
    ) -> dict[str, Any]:
        return await self._call_tool(
            "hestia_vault_set",
            {
                "name": name,
                "value": value,
                "scope": options.scope,
                "tags": options.tags,
                "allowed_consumers": options.allowed_consumers,
            },
        )

    # ---------------------------------------------------------- history ----

    async def query_history(self, filter: HistoryFilter) -> HistoryResult:
        result = await self._call_tool(
            "hestia_query_history",
            {
                "filter": {
                    "tool_name": filter.tool_name,
                    "target_pattern": filter.target_pattern,
                    "since": filter.since,
                    "limit": filter.limit,
                    "outcome": filter.outcome,
                }
            },
        )
        entries = [
            WitnessEntry(
                hash=e["hash"],
                prev_hash=e["prevHash"],
                timestamp=e["timestamp"],
                event_type=e["eventType"],
                event_data=e.get("eventData", {}),
                signer_lct=e["signerLct"],
                chain_position=int(e["chainPosition"]),
            )
            for e in result["entries"]
        ]
        return HistoryResult(entries=entries, has_more=bool(result.get("hasMore", False)))

    async def request_witness(
        self, event_type: str, event_data: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._call_tool(
            "hestia_request_witness",
            {"event_type": event_type, "event_data": event_data},
        )

    # --------------------------------------------------------- resources ----

    async def get_shared_context(self) -> dict[str, Any]:
        return await self._read_resource("hestia://context/shared")

    async def get_own_trust_state(self) -> TrustState:
        result = await self._read_resource(
            f"hestia://society/trust/{self.config.plugin_id}"
        )
        return TrustState(
            t3_talent=result["t3"]["talent"],
            t3_training=result["t3"]["training"],
            t3_temperament=result["t3"]["temperament"],
            v3_valuation=result["v3"]["valuation"],
            v3_veracity=result["v3"]["veracity"],
            v3_validity=result["v3"]["validity"],
            level=result["level"],
            action_count=int(result["actionCount"]),
            days_since_last=float(result["daysSinceLast"]),
        )

    # ---------------------------------------------------------- internals ----

    def _require_session(self) -> ClientSession:
        if self._session is None or self._connect_result is None:
            raise NotConnectedError()
        return self._session

    async def _call_tool_raw(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Call a tool; used during connect (before _connect_result is set)."""
        if self._session is None:
            raise NotConnectedError()
        return await _invoke_tool(self._session, name, args)

    async def _call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        session = self._require_session()
        # Stamp the session_id so the daemon can authoritatively resolve the
        # caller. _call_tool_raw is used for hestia_connect (pre-session) and
        # does NOT stamp.
        stamped = dict(args)
        if self._connect_result and "session_id" not in stamped:
            stamped["session_id"] = self._connect_result.session_id
        return await _invoke_tool(session, name, stamped)

    async def _read_resource(self, uri: str) -> dict[str, Any]:
        session = self._require_session()
        result = await session.read_resource(uri)
        if not result.contents:
            raise HestiaError("hestia.invalid_resource", f"Resource {uri} empty")
        content = result.contents[0]
        text = getattr(content, "text", None)
        if not text:
            raise HestiaError(
                "hestia.invalid_resource", f"Resource {uri} has no text content"
            )
        return json.loads(text)


async def _invoke_tool(session: ClientSession, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Invoke an MCP tool and unwrap the structured result.

    Hestia error encoding: MCP normalizes tool exceptions into `isError=True`
    results without preserving the original `data` field. To preserve typed
    errors, Hestia tools (mock and real) return a JSON envelope of the form
    `{"_hestia_error": {"code": "hestia.*", "message": "...", "data": {...}}}`
    on the success path when they want to signal a typed error. The SDK
    detects this envelope and raises the appropriate typed error.

    Plus, if MCP-level JSON-RPC errors arrive (rare for tool calls), they're
    also mapped if their `data.code` starts with `hestia.`.
    """
    try:
        result = await session.call_tool(name, arguments=args)
    except McpError as err:
        data = getattr(err.error, "data", None) if hasattr(err, "error") else None
        if isinstance(data, dict):
            code = data.get("code")
            if isinstance(code, str) and code.startswith("hestia."):
                raise map_hestia_error(
                    code, getattr(err.error, "message", str(err)), data
                ) from err
        raise

    # Prefer structuredContent if present (newer MCP versions populate it).
    parsed: dict[str, Any] | None = None
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        if isinstance(structured, str):
            parsed = json.loads(structured)
        elif isinstance(structured, dict):
            parsed = structured
    if parsed is None:
        content = result.content
        if content and getattr(content[0], "type", None) == "text":
            parsed = json.loads(content[0].text)

    if parsed is None:
        raise HestiaError(
            "hestia.invalid_response", f"Tool {name} returned no parseable content"
        )

    # Check for the hestia error envelope
    if isinstance(parsed, dict) and "_hestia_error" in parsed:
        env = parsed["_hestia_error"]
        if isinstance(env, dict):
            raise map_hestia_error(
                env.get("code", "hestia.unknown"),
                env.get("message", ""),
                env.get("data"),
            )

    return parsed


def create_hestia_client(config: HestiaClientConfig) -> HestiaClient:
    """Factory function — the canonical way to construct a HestiaClient."""
    return HestiaClient(config)
