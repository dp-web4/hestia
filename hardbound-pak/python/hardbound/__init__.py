"""hardbound — public Protocol surface for the hardware-bound enterprise
trust tier of Web4.

This package is the *contract*, not the implementation. Implementations
that anchor trust in TPM 2.0 / YubiKey / Secure Enclave / HSM satisfy
these Protocols. The reference closed-source implementation lives at
metalinxx.io.

Four primitives:

- :class:`TrustedKeyProvider` — hardware-bound signer
- :class:`SealedVault`        — hardware-sealed AEAD storage
- :class:`AttestationSigner`  — TPM-quote-style attestation envelope
- :class:`OversightPolicy`    — real policy engine (replaces default-allow)

See https://github.com/dp-web4/hestia/blob/main/demo/enterprise/README.md
for the architectural map.
"""

from .protocols import (
    Attestation,
    AttestationSigner,
    HardboundError,
    OversightPolicy,
    PolicyAction,
    PolicyDecision,
    SealedVault,
    TrustedKeyProvider,
)

__version__ = "0.0.1"

__all__ = [
    "Attestation",
    "AttestationSigner",
    "HardboundError",
    "OversightPolicy",
    "PolicyAction",
    "PolicyDecision",
    "SealedVault",
    "TrustedKeyProvider",
    "__version__",
]
