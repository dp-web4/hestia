"""Mock Hestia MCP server for Python SDK testing.

Parallels the TypeScript mock (`plugin-sdk/typescript/test/mock-hestia-server.ts`)
structurally — uses the raw `mcp.server.lowlevel.Server` (not FastMCP) so we
can preserve `data.code` for hestia.* errors on the wire (FastMCP catches
ToolError-derived exceptions and rewrites them, losing the structured data).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import socket
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator
from uuid import uuid4

import uvicorn
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.shared.exceptions import McpError
from mcp.types import (
    ErrorData,
    INVALID_PARAMS,
    INTERNAL_ERROR,
    TextContent,
    Tool,
    Resource,
    ReadResourceResult,
    TextResourceContents,
)
from starlette.applications import Starlette
from starlette.routing import Mount


@dataclass
class MockState:
    sessions: dict[str, dict[str, Any]] = field(default_factory=dict)
    actions: dict[str, dict[str, Any]] = field(default_factory=dict)
    vault: dict[str, dict[str, Any]] = field(default_factory=dict)
    chain: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class MockServerHandle:
    url: str
    state: MockState


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


_TOOL_INPUT_SCHEMA = {"type": "object"}

_TOOL_NAMES = [
    "hestia_connect",
    "hestia_begin_action",
    "hestia_record_outcome",
    "hestia_query_policy",
    "hestia_vault_get",
    "hestia_vault_set",
    "hestia_query_history",
    "hestia_request_witness",
]


def _make_server(state: MockState) -> Server:
    server: Server = Server("hestia-mock")

    @server.list_tools()
    async def _list_tools() -> list[Tool]:
        return [
            Tool(name=n, description=f"Hestia: {n}", inputSchema=_TOOL_INPUT_SCHEMA)
            for n in _TOOL_NAMES
        ]

    @server.list_resources()
    async def _list_resources() -> list[Resource]:
        return [
            Resource(
                uri="hestia://context/shared",  # type: ignore[arg-type]
                name="shared context",
                mimeType="application/json",
            ),
        ]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        result = _dispatch_tool(state, name, arguments)
        return [TextContent(type="text", text=json.dumps(result))]

    @server.read_resource()
    async def _read_resource(uri) -> str | bytes:  # type: ignore[no-untyped-def]
        uri_str = str(uri)
        if uri_str == "hestia://context/shared":
            return json.dumps({"currentProject": "hestia-smoke-test"})
        if uri_str.startswith("hestia://society/trust/"):
            return json.dumps(
                {
                    "t3": {"talent": 0.5, "training": 0.5, "temperament": 0.5},
                    "v3": {"valuation": 0.5, "veracity": 0.5, "validity": 0.5},
                    "level": "medium",
                    "actionCount": 0,
                    "daysSinceLast": 0,
                }
            )
        raise McpError(
            ErrorData(
                code=INVALID_PARAMS,
                message=f"Unknown resource {uri_str}",
            )
        )

    return server


def _dispatch_tool(state: MockState, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Dispatch a tool call against the in-memory state. Returns the result dict.

    Errors are raised as McpError with `data.code = 'hestia.*'` so the SDK
    can map them to typed errors on the client side.
    """
    if name == "hestia_connect":
        sid = str(uuid4())
        soft_lct = "lct:web4:session:" + hashlib.sha256(sid.encode()).hexdigest()[:16]
        plugin_id = args.get("plugin_id", "unknown")
        role = args.get("requested_role", "citizen")
        state.sessions[sid] = {"pluginId": plugin_id, "assignedRole": role, "softLct": soft_lct}
        return {
            "sessionId": sid,
            "softLct": soft_lct,
            "assignedRole": role,
            "protocolVersion": 0,
        }

    if name == "hestia_begin_action":
        aid = str(uuid4())
        chain_pos = len(state.chain)
        state.actions[aid] = {"toolName": args["tool_name"], "chainPosition": chain_pos}
        return {
            "actionId": aid,
            "startedAt": datetime.now(timezone.utc).isoformat(),
            "chainPosition": chain_pos,
        }

    if name == "hestia_record_outcome":
        aid = args["action_id"]
        action = state.actions.get(aid)
        if action is None:
            return _err("hestia.action_not_found", f"Action {aid} not found", {"action_id": aid})
        prev = state.chain[-1]["hash"] if state.chain else "0" * 64
        h = hashlib.sha256(
            f"{prev}|{action['toolName']}|{args['success']}|{args['magnitude']}".encode()
        ).hexdigest()
        state.chain.append(
            {"hash": h, "prevHash": prev, "eventType": "outcome", "chainPosition": len(state.chain)}
        )
        return {
            "witnessEntryHash": h,
            "updatedTrustState": {
                "t3": {"talent": 0.55, "training": 0.6, "temperament": 0.5},
                "v3": {"valuation": 0.5, "veracity": 0.55, "validity": 0.5},
                "level": "medium",
                "actionCount": len(state.chain),
                "daysSinceLast": 0,
            },
        }

    if name == "hestia_query_policy":
        return {"decision": "allow", "reason": "mock: default-allow", "enforced": True}

    if name == "hestia_vault_get":
        vname = args["name"]
        entry = state.vault.get(vname)
        if entry is None:
            return _err("hestia.vault_not_found", f"Credential '{vname}' not found", {"name": vname})
        return {"value": entry["value"]}

    if name == "hestia_vault_set":
        state.vault[args["name"]] = {
            "value": args["value"],
            "scope": args.get("scope", []),
            "allowedConsumers": args.get("allowed_consumers", []),
        }
        return {"stored": True, "entryId": str(uuid4())}

    if name == "hestia_query_history":
        entries = [
            {
                "hash": e["hash"],
                "prevHash": e["prevHash"],
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "eventType": e["eventType"],
                "eventData": {},
                "signerLct": "lct:web4:mock:sovereign",
                "chainPosition": e["chainPosition"],
            }
            for e in state.chain
        ]
        return {"entries": entries, "hasMore": False}

    if name == "hestia_request_witness":
        prev = state.chain[-1]["hash"] if state.chain else "0" * 64
        event_type = args.get("event_type", "custom")
        event_data = args.get("event_data", {})
        h = hashlib.sha256(
            f"{prev}|{event_type}|{json.dumps(event_data, sort_keys=True)}".encode()
        ).hexdigest()
        state.chain.append(
            {"hash": h, "prevHash": prev, "eventType": event_type, "chainPosition": len(state.chain)}
        )
        return {"witnessEntryHash": h}

    return _err("hestia.unknown_tool", f"Unknown tool: {name}", {"tool": name})


def _err(code: str, message: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a hestia error envelope. The SDK detects `_hestia_error` and maps."""
    return {"_hestia_error": {"code": code, "message": message, "data": data or {}}}


@asynccontextmanager
async def start_mock_hestia_server() -> AsyncIterator[MockServerHandle]:
    state = MockState()
    server = _make_server(state)

    # Stateless StreamableHTTP setup — each request creates a fresh session.
    session_manager = StreamableHTTPSessionManager(
        app=server, event_store=None, stateless=True, json_response=True
    )

    async def handle_http(scope, receive, send):
        await session_manager.handle_request(scope, receive, send)

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        async with session_manager.run():
            yield

    app = Starlette(
        routes=[Mount("/mcp", app=handle_http)],
        lifespan=lifespan,
    )

    port = _free_port()
    config = uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="error", lifespan="on"
    )
    uvi_server = uvicorn.Server(config)
    task = asyncio.create_task(uvi_server.serve())

    for _ in range(50):
        await asyncio.sleep(0.1)
        if uvi_server.started:
            break
    if not uvi_server.started:
        uvi_server.should_exit = True
        await task
        raise RuntimeError("mock server failed to start")

    try:
        yield MockServerHandle(url=f"http://127.0.0.1:{port}/mcp", state=state)
    finally:
        uvi_server.should_exit = True
        try:
            await asyncio.wait_for(task, timeout=5.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass
