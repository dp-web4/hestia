"""Hestia plugin SDK error types.

Hestia-specific errors are raised by the SDK when the server returns a
JSON-RPC error whose `data.code` is in the `hestia.*` namespace.
"""

from __future__ import annotations

from typing import Any


class HestiaError(Exception):
    """Base class for Hestia SDK errors."""

    def __init__(self, code: str, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(code={self.code!r}, message={self.message!r})"


class NotConnectedError(HestiaError):
    def __init__(self) -> None:
        super().__init__(
            "hestia.not_connected",
            "Plugin must call connect() before invoking other methods.",
        )


class SessionExpiredError(HestiaError):
    def __init__(self) -> None:
        super().__init__(
            "hestia.session_expired",
            "Soft LCT expired. Call connect() again to renew the session.",
        )


class PolicyDeniedError(HestiaError):
    def __init__(self, reason: str, policy_id: str | None = None) -> None:
        super().__init__(
            "hestia.policy_denied",
            f"Action denied by policy: {reason}",
            {"policy_id": policy_id},
        )
        self.policy_id = policy_id


class VaultDeniedError(HestiaError):
    def __init__(self, reason: str | None = None) -> None:
        msg = "User declined credential request"
        if reason:
            msg = f"{msg}: {reason}"
        super().__init__("hestia.vault_denied", msg + ".")


class VaultNotFoundError(HestiaError):
    def __init__(self, name: str) -> None:
        super().__init__(
            "hestia.vault_not_found",
            f"Credential '{name}' not found in vault.",
            {"name": name},
        )
        self.name = name


class VaultScopeMismatchError(HestiaError):
    def __init__(self, name: str, requested_scope: list[str]) -> None:
        super().__init__(
            "hestia.vault_scope_mismatch",
            f"Credential '{name}' is not allowed under scope [{', '.join(requested_scope)}] for this plugin.",
            {"name": name, "requested_scope": requested_scope},
        )
        self.name = name
        self.requested_scope = requested_scope


class ActionNotFoundError(HestiaError):
    def __init__(self, action_id: str) -> None:
        super().__init__(
            "hestia.action_not_found",
            f"Action {action_id} not found (begin_action required first).",
            {"action_id": action_id},
        )
        self.action_id = action_id


class InvalidRoleError(HestiaError):
    def __init__(self, role: str) -> None:
        super().__init__(
            "hestia.invalid_role",
            f"Role '{role}' is not available to plugins.",
            {"role": role},
        )
        self.role = role


def map_hestia_error(code: str, message: str, data: Any = None) -> HestiaError:
    """Map a Hestia error code into a typed Python error."""
    if not isinstance(data, dict):
        data = {}
    if code == "hestia.not_connected":
        return NotConnectedError()
    if code == "hestia.session_expired":
        return SessionExpiredError()
    if code == "hestia.policy_denied":
        return PolicyDeniedError(message, data.get("policy_id"))
    if code == "hestia.vault_denied":
        return VaultDeniedError(message)
    if code == "hestia.vault_not_found":
        return VaultNotFoundError(data.get("name", "?"))
    if code == "hestia.vault_scope_mismatch":
        return VaultScopeMismatchError(data.get("name", "?"), data.get("requested_scope", []))
    if code == "hestia.action_not_found":
        return ActionNotFoundError(data.get("action_id", "?"))
    if code == "hestia.invalid_role":
        return InvalidRoleError(data.get("role", "?"))
    return HestiaError(code, message, data)
