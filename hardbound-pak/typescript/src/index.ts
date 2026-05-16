/**
 * hardbound — public interface surface for the hardware-bound enterprise
 * trust tier of Web4.
 *
 * This package is the *contract*, not the implementation. Implementations
 * that anchor trust in TPM 2.0 / YubiKey / Secure Enclave / HSM satisfy
 * these interfaces. The reference closed-source implementation lives at
 * metalinxx.io.
 *
 * Four primitives:
 *
 * - `TrustedKeyProvider` — hardware-bound signer
 * - `SealedVault`        — hardware-sealed AEAD storage
 * - `AttestationSigner`  — TPM-quote-style attestation envelope
 * - `OversightPolicy`    — real policy engine (replaces default-allow)
 *
 * See https://github.com/dp-web4/hestia/blob/main/demo/enterprise/README.md
 * for the architectural map.
 */

export const VERSION = "0.0.1";

// =========================================================================
// Errors
// =========================================================================

/**
 * Categories of failure an implementation may report. The contract avoids
 * being prescriptive about the underlying hardware error — callers mostly
 * care about which class of failure happened.
 */
export type HardboundErrorKind =
  | "anchor_unavailable"
  | "verification_failed"
  | "unsupported"
  | "other";

/** Error thrown by Hardbound implementations. */
export class HardboundError extends Error {
  readonly kind: HardboundErrorKind;
  constructor(kind: HardboundErrorKind, message?: string) {
    super(message ?? kind);
    this.kind = kind;
    this.name = "HardboundError";
  }
}

// =========================================================================
// TrustedKeyProvider
// =========================================================================

/**
 * Handle to key material that lives inside hardware.
 *
 * The private key bytes never leave the bound device; implementations
 * MUST refuse any extraction primitive. Only the public key, an opaque
 * anchor identifier, sign, and verify are exposed.
 *
 * Implementations are typically backed by:
 * - TPM 2.0 with a non-migratable key under a sealing policy
 * - YubiKey PIV slot or PGP card
 * - Secure Enclave on Apple silicon
 * - HSM for datacenter deployments
 */
export interface TrustedKeyProvider {
  /**
   * Stable identifier for this hardware-bound key. Survives reboots;
   * changes only if the hardware is rebound.
   * Recommended format: `"tpm:sha256:<digest>"`, `"yubikey:serial:<n>"`,
   * `"se:keyid:<base64>"`.
   */
  anchorId(): string;

  /**
   * Public key bytes. Format is implementation-defined; recommend
   * DER-encoded SubjectPublicKeyInfo for interoperability.
   */
  publicKey(): Uint8Array;

  /**
   * Sign `message`. Returns the raw signature bytes (DER-encoded for
   * ECDSA, or whatever the underlying scheme produces).
   */
  sign(message: Uint8Array): Promise<Uint8Array>;

  /**
   * Verify `signature` over `message` against this anchor's public key.
   */
  verify(message: Uint8Array, signature: Uint8Array): Promise<boolean>;
}

// =========================================================================
// SealedVault
// =========================================================================

/**
 * Vault whose AEAD key is unsealed only on the originally-bound hardware.
 *
 * Replaces consumer Hestia's passphrase-derived AEAD with a TPM-unseal /
 * YubiKey-HMAC-derived / SE-attested-key unwrap so the ciphertext cannot
 * be decrypted on a different device.
 */
export interface SealedVault {
  /** Seal `plaintext` into a blob this anchor can unseal. */
  seal(plaintext: Uint8Array): Promise<Uint8Array>;

  /**
   * Unseal a previously-sealed blob. Throws `HardboundError("verification_failed")`
   * if the ciphertext was produced by a different anchor or has been tampered with.
   */
  unseal(ciphertext: Uint8Array): Promise<Uint8Array>;
}

// =========================================================================
// AttestationSigner
// =========================================================================

/**
 * One attested signature over a payload, signed by a hardware anchor.
 *
 * The daemon co-locates an `Attestation` with each witness chain entry;
 * verifiers reconstruct the payload and validate the signature against
 * the public key embedded in the anchor's `TrustedKeyProvider.publicKey()`.
 */
export interface Attestation {
  /** Anchor that produced this signature. See `TrustedKeyProvider.anchorId()`. */
  anchorId: string;

  /**
   * Optional platform quote / firmware measurement bundle.
   * For TPM: a TPM2B_ATTEST quote over the requested PCRs.
   * For YubiKey: empty (the device itself is the attestation surface).
   */
  quote: Uint8Array;

  /** Signature bytes from `TrustedKeyProvider.sign()`. */
  signature: Uint8Array;

  /** Unix epoch milliseconds when the anchor produced this attestation. */
  timestampMs: number;
}

/**
 * Produces `Attestation`s over arbitrary payloads.
 *
 * Split from `TrustedKeyProvider` because the latter is a bare signer;
 * an `AttestationSigner` adds the platform-attestation envelope (PCR
 * quote for TPM, factory cert chain for YubiKey).
 */
export interface AttestationSigner {
  /**
   * Produce an attestation over `payload`. `nonce` is supplied by the
   * caller to defeat replay; implementations MUST incorporate it into
   * the signed bytes.
   */
  signAttestation(payload: Uint8Array, nonce: Uint8Array): Promise<Attestation>;
}

// =========================================================================
// OversightPolicy
// =========================================================================

/**
 * A pending action to be evaluated against policy.
 *
 * Mirrors the shape of a Hestia R6 action begin record, but intentionally
 * generic so non-Hestia consumers can use the same interface.
 */
export interface PolicyAction {
  toolName: string;
  target?: string;
  pluginId: string;
  /** Magnitude in [0..1] — how consequential is this call? */
  magnitude: number;
}

/** Policy verdict for a `PolicyAction`. */
export type PolicyDecision =
  | { kind: "allow" }
  | { kind: "deny"; reason: string; policyId?: string }
  | { kind: "warn"; reason: string; policyId?: string };

/**
 * A policy engine. Implementations may be rule-based, model-based, or hybrid.
 *
 * Consumer Hestia's default returns `{ kind: "allow" }` for every action.
 * Hardbound replaces it with a real engine.
 */
export interface OversightPolicy {
  /** Evaluate `action` and return a verdict. */
  evaluate(action: PolicyAction): Promise<PolicyDecision>;
}
