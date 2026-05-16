"""End-to-end smoke test for the Python Hestia SDK.

Mirrors the TypeScript SDK smoke test (`plugin-sdk/typescript/test/smoke.test.ts`).
Spins up the Python mock Hestia server, runs a HestiaClient through its full
lifecycle, asserts the round-trip works.
"""

from __future__ import annotations

import pytest

from hestia_plugin_sdk import (
    HESTIA_PROTOCOL_VERSION,
    HestiaClient,
    HestiaClientConfig,
    NotConnectedError,
    Outcome,
    ToolCallSpec,
    VaultGetOptions,
    VaultNotFoundError,
    VaultSetOptions,
    HistoryFilter,
)

from .mock_hestia_server import start_mock_hestia_server


pytestmark = pytest.mark.asyncio


@pytest.fixture
async def hestia_url():
    """Start the mock server, yield its URL, then shut down cleanly."""
    async with start_mock_hestia_server() as handle:
        yield handle


async def test_rejects_calls_before_connect(hestia_url):
    fresh = HestiaClient(
        HestiaClientConfig(
            plugin_id="no-connect-test",
            host_agent="test",
            hestia_endpoint=hestia_url.url,
        )
    )
    with pytest.raises(NotConnectedError):
        await fresh.begin_action(ToolCallSpec(tool_name="noop"))


async def test_full_lifecycle(hestia_url):
    """Run the full plugin lifecycle against the mock server."""
    config = HestiaClientConfig(
        plugin_id="smoke-test-plugin",
        plugin_version="0.0.1",
        host_agent="smoke-test-agent",
        requested_role="citizen",
        hestia_endpoint=hestia_url.url,
    )

    async with HestiaClient(config) as hestia:
        # connect returns Soft LCT
        # (the async-with already called connect; access via the stored result)
        # Verify by reading own session indirectly: query our trust state
        own_trust = await hestia.get_own_trust_state()
        assert own_trust.level == "medium"

        # begin_action returns a handle
        action = await hestia.begin_action(
            ToolCallSpec(
                tool_name="file_write",
                target="/tmp/smoke.txt",
                parameters={"content": "hello"},
                atp_stake=1.0,
            )
        )
        assert action.action_id
        assert action.tool_name == "file_write"
        assert action.chain_position >= 0

        # query_policy returns allow
        policy = await hestia.query_policy(action)
        assert policy.decision == "allow"
        assert policy.enforced is True

        # record_outcome appends to chain + returns updated trust state
        outcome_result = await hestia.record_outcome(
            action, Outcome(success=True, magnitude=0.5)
        )
        assert len(outcome_result.witness_entry_hash) == 64
        assert outcome_result.updated_trust_state.level == "medium"
        assert outcome_result.updated_trust_state.action_count >= 1

        # vault set then get
        set_result = await hestia.vault_set(
            "test_key",
            "secret-value-abc",
            VaultSetOptions(scope=["test"], allowed_consumers=["smoke-test-plugin"]),
        )
        assert set_result["stored"] is True

        got = await hestia.vault_get("test_key", VaultGetOptions(scope=["test"]))
        assert got.value == "secret-value-abc"

        # vault miss raises typed error
        with pytest.raises(VaultNotFoundError) as excinfo:
            await hestia.vault_get("missing_key", VaultGetOptions(scope=["test"]))
        assert excinfo.value.name == "missing_key"

        # shared context resource
        ctx = await hestia.get_shared_context()
        assert ctx == {"currentProject": "hestia-smoke-test"}

        # history query
        history = await hestia.query_history(HistoryFilter(limit=10))
        assert len(history.entries) >= 1
        assert len(history.entries[0].hash) == 64

        # custom witness event
        wit = await hestia.request_witness("config_change", {"setting": "x"})
        assert "witnessEntryHash" in wit


async def test_protocol_version_constant():
    """Sanity: SDK exports the protocol version it targets."""
    assert HESTIA_PROTOCOL_VERSION == 0
