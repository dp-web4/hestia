"""Protocol declarations for Hardbound implementations.

Uses :class:`typing.Protocol` for structural typing — an implementation
satisfies the contract by implementing the methods, without having to
inherit from these classes explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal, Optional, Protocol, Union, runtime_checkable

__all__ = [
    "Attestation",
    "AttestationSigner",
    "HardboundError",
    "OversightPolicy",
    "PolicyAction",
    "PolicyDecision",
    "SealedVault",
    "TrustedKeyProvider",
]


class HardboundError(Exception):
    """Categories of failure an implementation may report.

    The contract avoids being prescriptive about the underlying hardware
    error — callers mostly care about which *class* of failure happened.
    Subclass for finer-grained errors if needed.
    """

    KIND_ANCHOR_UNAVAILABLE: Literal["anchor_unavailable"] = "anchor_unavailable"
    KIND_VERIFICATION_FAILED: Literal["verification_failed"] = "verification_failed"
    KIND_UNSUPPORTED: Literal["unsupported"] = "unsupported"
    KIND_OTHER: Literal["other"] = "other"

    def __init__(self, kind: str, message: str = "") -> None:
        super().__init__(message or kind)
        self.kind = kind


@runtime_checkable
class TrustedKeyProvider(Protocol):
    """Handle to key material that lives inside hardware.

    The private key bytes never leave the bound device; implementations
    MUST refuse any extraction primitive. Only the public key, an opaque
    anchor identifier, sign, and verify are exposed.
    """

    def anchor_id(self) -> str:
        """Stable identifier for this hardware-bound key.

        Recommended format: ``tpm:sha256:<digest>`` /
        ``yubikey:serial:<n>`` / ``se:keyid:<base64>``.
        """

    def public_key(self) -> bytes:
        """Public key bytes (recommend DER-encoded SubjectPublicKeyInfo)."""

    def sign(self, message: bytes) -> bytes:
        """Sign ``message`` and return raw signature bytes."""

    def verify(self, message: bytes, signature: bytes) -> bool:
        """Verify ``signature`` over ``message`` against this anchor's public key."""


@runtime_checkable
class SealedVault(Protocol):
    """Vault whose AEAD key is unsealed only on the originally-bound hardware.

    Replaces consumer Hestia's passphrase-derived AEAD with a TPM-unseal
    / YubiKey-HMAC-derived / SE-attested-key unwrap so the ciphertext
    cannot be decrypted on a different device.
    """

    def seal(self, plaintext: bytes) -> bytes:
        """Seal ``plaintext`` into a ciphertext blob that this anchor can unseal."""

    def unseal(self, ciphertext: bytes) -> bytes:
        """Unseal a previously-sealed blob.

        Raises :class:`HardboundError` with kind ``verification_failed``
        if the ciphertext was produced by a different anchor or has
        been tampered with.
        """


@dataclass(frozen=True)
class Attestation:
    """One attested signature over a payload, signed by a hardware anchor.

    The daemon co-locates an :class:`Attestation` with each witness
    chain entry; verifiers reconstruct the payload and validate the
    signature against the public key embedded in the anchor's
    :meth:`TrustedKeyProvider.public_key`.
    """

    anchor_id: str
    """Anchor that produced this signature."""

    quote: bytes
    """Optional platform quote / firmware measurement bundle.

    For TPM: ``TPM2B_ATTEST`` quote over the requested PCRs.
    For YubiKey: empty (the device itself is the attestation surface).
    """

    signature: bytes
    """Signature bytes from :meth:`TrustedKeyProvider.sign`."""

    timestamp_ms: int
    """Unix epoch milliseconds when the anchor produced this attestation."""


@runtime_checkable
class AttestationSigner(Protocol):
    """Produces :class:`Attestation`\\ s over arbitrary payloads.

    Split from :class:`TrustedKeyProvider` because the latter is a bare
    signer; an ``AttestationSigner`` adds the platform-attestation
    envelope (PCR quote for TPM, factory cert chain for YubiKey).
    """

    def sign_attestation(self, payload: bytes, nonce: bytes) -> Attestation:
        """Produce an attestation over ``payload``.

        ``nonce`` is supplied by the caller to defeat replay;
        implementations MUST incorporate it into the signed bytes.
        """


@dataclass(frozen=True)
class PolicyAction:
    """A pending action to be evaluated against policy.

    Mirrors the shape of a Hestia R6 action begin record, but
    intentionally generic so non-Hestia consumers can use the same
    Protocol.
    """

    tool_name: str
    target: Optional[str]
    plugin_id: str
    magnitude: float


@dataclass(frozen=True)
class PolicyAllow:
    """Caller should proceed."""

    kind: Literal["allow"] = "allow"


@dataclass(frozen=True)
class PolicyDeny:
    """Caller should NOT proceed.

    As of presence-protocol v1, `rule_id` is the stable rule identifier
    and `rule_name` the human-readable name. `policy_id` is an alias
    of `rule_id` kept for v0 callers.
    """

    reason: str
    rule_id: Optional[str] = None
    rule_name: Optional[str] = None
    policy_id: Optional[str] = None
    constraints: List[str] = field(default_factory=list)
    kind: Literal["deny"] = "deny"


@dataclass(frozen=True)
class PolicyWarn:
    """Caller may proceed but the user should see a warning first.

    In CRISIS mode this can be promoted to a hard deny.
    """

    reason: str
    rule_id: Optional[str] = None
    rule_name: Optional[str] = None
    policy_id: Optional[str] = None
    constraints: List[str] = field(default_factory=list)
    kind: Literal["warn"] = "warn"


PolicyDecision = Union[PolicyAllow, PolicyDeny, PolicyWarn]


@runtime_checkable
class OversightPolicy(Protocol):
    """A policy engine. Implementations may be rule-based, model-based, or hybrid.

    Consumer Hestia's default returns :class:`PolicyAllow` for every
    action. Hardbound replaces it with a real engine.
    """

    def evaluate(self, action: PolicyAction) -> PolicyDecision:
        """Evaluate ``action`` and return a verdict."""
