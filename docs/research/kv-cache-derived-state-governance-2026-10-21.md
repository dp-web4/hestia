# Derived KV-cache state: governance considerations
Date: 2026-10-21 | Status: security design note, not implemented
Context: evaluation of LMCache (https://lmcache.ai/en/) in SAGE; umbrella: dp-web4/private-context/research/lmcache-kv-persistence-evaluation-2026-10-21.md

Persistent KV blobs are computationally derived from potentially private or privileged source context. Treat their storage, transfer, retrieval and reuse as scoped data actions with provenance, not as inert harmless performance artifacts.

Proposed evidence/metadata: owning LCT/being, tenant, resident/visitor source, source context and access classification, checkpoint/tokenizer/adapter/runtime fingerprint, exact prefix/positions fingerprint, permitted audience/use, creation and expiry time, revocation epoch, integrity evidence, storage location and witnessed decision references. Fields are proposed, not necessarily supported natively by LMCache.

Adjudication:
- Enforce tenant and being separation; deny unknown/ambiguous ownership and mismatched model/context.
- Bind admission to current effective law, delegation, source privileges and revocation status; do not infer permission from possession or a cache hit.
- Cache reuse never grants permission for any subsequent tool execution. Adjudicate each proposed act independently at action time under current authority.
- Prevent visitor-derived, potentially externally observed context from silently entering a resident's trusted context; enforce explicit transfer policy.
- On mismatch, revocation, expiry, corruption or denial, invalidate/fall back to canonical reconstruction. Record deny receipts without leaking cached content.
- Consider cache eviction and deletion propagation on delegated authority revocation; ensure stale cache cannot resurrect stale authority.

This note proposes the governance boundary, not interception of model execution. The gate decides whether the proposed action is compliant; after authorization execution is between agent and recipient, which may verify the accompanying evidence.
