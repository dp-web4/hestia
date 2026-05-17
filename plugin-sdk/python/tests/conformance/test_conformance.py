"""Conformance harness — Python.

Loads the canonical scenarios from
web4-standard/testing/conformance/presence-protocol-conformance.json
and exercises them against a live Hestia daemon. Pass/fail per scenario
is reported via pytest's normal output.

Requires:
  - A running Hestia daemon at $HESTIA_ENDPOINT (default
    http://127.0.0.1:7711/mcp).
  - $WEB4_STANDARD_CONFORMANCE pointing at the JSON vector file, or the
    default relative path resolves.

Skipped automatically if the daemon isn't reachable. Use
`RUN_CONFORMANCE=1 pytest` to require it.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hestia_plugin_sdk import (  # noqa: E402
    HestiaClientConfig,
    HistoryFilter,
    Outcome,
    R6Action,
    ToolCallSpec,
    VaultGetOptions,
    VaultSetOptions,
    create_hestia_client,
)
from hestia_plugin_sdk.errors import HestiaError  # noqa: E402

pytestmark = pytest.mark.asyncio

ENDPOINT = os.environ.get("HESTIA_ENDPOINT", "http://127.0.0.1:7711/mcp")
VECTORS_PATH = Path(
    os.environ.get(
        "WEB4_STANDARD_CONFORMANCE",
        str(
            # this file → conformance → tests → python → plugin-sdk → hestia → ai-agents
            Path(__file__).resolve().parents[5]
            / "web4"
            / "web4-standard"
            / "testing"
            / "conformance"
            / "presence-protocol-conformance.json"
        ),
    )
)


def daemon_reachable() -> bool:
    # Connect a TCP socket to the daemon's host:port. If it accepts, the
    # daemon is up; we don't care about the HTTP-layer response shape.
    import socket
    import urllib.parse

    parsed = urllib.parse.urlparse(ENDPOINT)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


def resolve_path(obj: Any, path: str) -> Any:
    parts = re.split(r"\.|\[(\d+|\*)\]", path)
    parts = [p for p in parts if p]
    current: Any = obj
    for part in parts:
        if current is None:
            return None
        if part == "*":
            return current  # caller handles
        if part.isdigit():
            try:
                current = current[int(part)]
            except (IndexError, TypeError):
                return None
        else:
            if isinstance(current, dict):
                current = current.get(part)
            else:
                current = getattr(current, part, None)
    return current


def interpolate(value: Any, captures: dict[str, dict[str, Any]]) -> Any:
    if isinstance(value, str):
        m = re.match(r"^\{\{([A-Z0-9-]+)\.([a-zA-Z_$]+)\}\}$", value)
        if m:
            scenario_id, field = m.groups()
            return captures.get(scenario_id, {}).get(field, value)
        return value
    if isinstance(value, list):
        return [interpolate(v, captures) for v in value]
    if isinstance(value, dict):
        return {k: interpolate(v, captures) for k, v in value.items()}
    return value


def check_field(value: Any, check: dict, scenario_id: str) -> None:
    ctx = f"[{scenario_id}] field {check['path']!r}"
    if "equals" in check:
        assert value == check["equals"], f"{ctx} != {check['equals']!r} (got {value!r})"
    if "matchesPattern" in check:
        assert isinstance(value, str) and re.search(check["matchesPattern"], value), f"{ctx} doesn't match {check['matchesPattern']}"
    if "startsWith" in check:
        assert isinstance(value, str) and value.startswith(check["startsWith"]), ctx
    if check.get("isInteger"):
        assert isinstance(value, int) and not isinstance(value, bool), ctx
    if check.get("isNumber"):
        assert isinstance(value, (int, float)) and not isinstance(value, bool), ctx
    if check.get("isBoolean"):
        assert isinstance(value, bool), ctx
    if check.get("isString"):
        assert isinstance(value, str), ctx
    if check.get("isNonEmptyString"):
        assert isinstance(value, str) and len(value) > 0, ctx
    if check.get("isArray"):
        assert isinstance(value, list), ctx
    if check.get("isIso8601"):
        assert isinstance(value, (str, datetime)) and (
            isinstance(value, datetime)
            or _is_iso8601(value)
        ), ctx
    if "isIn" in check:
        assert value in check["isIn"], f"{ctx} not in {check['isIn']}"
    if "min" in check and isinstance(value, (int, float)):
        assert value >= check["min"], f"{ctx} >= {check['min']}"
    if "max" in check and isinstance(value, (int, float)):
        assert value <= check["max"], f"{ctx} <= {check['max']}"
    if "minLength" in check and isinstance(value, list):
        assert len(value) >= check["minLength"], f"{ctx} length >= {check['minLength']}"


def _is_iso8601(s: str) -> bool:
    try:
        datetime.fromisoformat(s.replace("Z", "+00:00"))
        return True
    except (ValueError, TypeError):
        return False


async def invoke_step(client, step, captures):
    input_ = interpolate(step.get("input", {}), captures) or {}
    if "resource" in step:
        return await client._read_resource(step["resource"])  # private; used for harness only
    tool = step.get("tool")
    if tool == "hestia_connect":
        return None  # connect already done
    if tool == "hestia_begin_action":
        action = await client.begin_action(
            ToolCallSpec(
                tool_name=input_["tool_name"],
                target=input_.get("target"),
                parameters=input_.get("parameters"),
                atp_stake=input_.get("atp_stake"),
            )
        )
        return {
            "actionId": action.action_id,
            "toolName": action.tool_name,
            "startedAt": action.started_at,
            "chainPosition": action.chain_position,
        }
    if tool == "hestia_record_outcome":
        action = R6Action(
            action_id=input_["action_id"],
            tool_name="",
            started_at=datetime.now(),
            chain_position=0,
        )
        result = await client.record_outcome(
            action,
            Outcome(
                success=bool(input_["success"]),
                magnitude=float(input_.get("magnitude", 0.5)),
                error=input_.get("error"),
                result=input_.get("result") or {},
            ),
        )
        # Flatten for harness field checks (camelCase keys to match wire shape)
        ts = result.updated_trust_state
        return {
            "witnessEntryHash": result.witness_entry_hash,
            "updatedTrustState": {
                "entityId": ts.entity_id,
                "t3": {"talent": ts.t3_talent, "training": ts.t3_training, "temperament": ts.t3_temperament},
                "v3": {"valuation": ts.v3_valuation, "veracity": ts.v3_veracity, "validity": ts.v3_validity},
                "level": ts.level,
                "actionCount": ts.action_count,
                "successCount": ts.success_count,
                "successRate": ts.success_rate,
                "daysSinceLast": ts.days_since_last,
            },
        }
    if tool == "hestia_query_policy":
        action = R6Action(
            action_id=input_["action_id"],
            tool_name="",
            started_at=datetime.now(),
            chain_position=0,
        )
        result = await client.query_policy(action, input_.get("context"))
        return {
            "decision": result.decision,
            "reason": result.reason,
            "policyId": result.policy_id,
            "enforced": result.enforced,
        }
    if tool == "hestia_vault_get":
        try:
            value = await client.vault_get(
                input_["name"],
                VaultGetOptions(scope=input_.get("scope", []), reason=input_.get("reason")),
            )
            return {"value": value.value, "approvalToken": value.approval_token}
        except HestiaError as err:
            return {"_hestia_error": {"code": err.code, "message": err.args[0] if err.args else "", "data": getattr(err, "data", {}) or {}}}
    if tool == "hestia_vault_set":
        result = await client.vault_set(
            input_["name"],
            input_["value"],
            VaultSetOptions(
                scope=input_.get("scope", []),
                tags=input_.get("tags", []),
                allowed_consumers=input_.get("allowed_consumers", []),
            ),
        )
        return result
    if tool == "hestia_query_history":
        filt = input_.get("filter") or {}
        result = await client.query_history(
            HistoryFilter(
                tool_name=filt.get("tool_name"),
                target_pattern=filt.get("target_pattern"),
                since=filt.get("since"),
                limit=int(filt.get("limit", 50)),
                outcome=filt.get("outcome"),
            )
        )
        return {
            "entries": [
                {
                    "hash": e.hash,
                    "prevHash": e.prev_hash,
                    "timestamp": e.timestamp,
                    "eventType": e.event_type,
                    "eventData": e.event_data,
                    "signerLct": e.signer_lct,
                    "chainPosition": e.chain_position,
                }
                for e in result.entries
            ],
            "hasMore": result.has_more,
        }
    if tool == "hestia_request_witness":
        result = await client.request_witness(input_["event_type"], input_.get("event_data") or {})
        return {"witnessEntryHash": result.get("witnessEntryHash") if isinstance(result, dict) else result}
    raise NotImplementedError(f"Conformance harness: tool {tool} not implemented")


@pytest.fixture(scope="module")
def vectors():
    if not VECTORS_PATH.exists():
        pytest.skip(f"Vectors not found at {VECTORS_PATH}")
    with VECTORS_PATH.open() as f:
        return json.load(f)


async def test_conformance_scenarios(vectors):
    if not daemon_reachable():
        if os.environ.get("RUN_CONFORMANCE") == "1":
            pytest.fail(f"Daemon not reachable at {ENDPOINT}")
        pytest.skip(f"Daemon not reachable at {ENDPOINT}; set RUN_CONFORMANCE=1 to require it")

    client = create_hestia_client(
        HestiaClientConfig(
            plugin_id="conformance-runner-py",
            plugin_version="0.0.1",
            host_agent="conformance-runner-py",
            host_agent_version="0.0.1",
            hestia_endpoint=ENDPOINT,
        )
    )
    captures: dict[str, dict[str, Any]] = {}

    try:
        session = await client.connect()
        captures["P0-001"] = {"sessionId": session.session_id}

        for scenario in vectors["scenarios"]:
            if scenario["id"] == "P0-001":
                continue
            # Setup
            for step in scenario.get("setup", []):
                result = await invoke_step(client, step, captures)
                if step.get("capture") and result is not None:
                    cap = captures.setdefault(scenario["id"], {})
                    for k, jp in step["capture"].items():
                        cap[k] = resolve_path(result, jp.lstrip("$").lstrip("."))
            # Steps
            for step in scenario["steps"]:
                result = await invoke_step(client, step, captures)
                if step.get("capture") and result is not None:
                    cap = captures.setdefault(scenario["id"], {})
                    for k, jp in step["capture"].items():
                        cap[k] = resolve_path(result, jp.lstrip("$").lstrip("."))
                expect = step.get("expect")
                if expect:
                    for check in expect.get("fieldChecks", []):
                        v = resolve_path(result, check["path"])
                        check_field(v, check, scenario["id"])
                    ordering = expect.get("ordering")
                    if ordering:
                        field = ordering["field"]
                        # e.g. "entries[*].chainPosition"
                        base, _, trailing = field.partition("[*].")
                        arr = resolve_path(result, base) or []
                        values = [resolve_path(el, trailing) if trailing else el for el in arr]
                        for i in range(1, len(values)):
                            if ordering["monotonic"] == "descending":
                                assert values[i] <= values[i - 1], (
                                    f"[{scenario['id']}] not descending at {i}"
                                )
                            else:
                                assert values[i] >= values[i - 1], (
                                    f"[{scenario['id']}] not ascending at {i}"
                                )
    finally:
        await client.disconnect()
