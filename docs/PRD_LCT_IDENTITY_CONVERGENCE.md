# PRD — Hestia LCT Identity Convergence

**Status:** Proposed  
**Date:** 2026-10-03  
**Issue:** [hestia#1202](https://github.com/dp-web4/hestia/issues/1202)  
**Canonical umbrella:** [web4#874](https://github.com/dp-web4/web4/issues/874)

## 1. Current state

Hestia already has the correct migration mechanism.

Historical member identity:

```text
member_lct(plugin_id) -> lct:web4:member:<hex>
```

This value is a deterministic legacy label. It has no keypair or presence by itself.

Current `member_registry.rs`:
- mints a persistent `web4_core::Lct` for a real member;
- signs its binding;
- stores the binding key in the vault;
- derives a canonical `lct:web4:mb32:b...` id;
- preserves the old label as a verifiable `LegacyAlias::HestiaMember`;
- can vouch an operational witnessing key from the binding key.

This is the desired bridge. The remaining work is to stop treating the alias as the preferred outward identity.

## 2. Target model

```text
plugin_id
   |
   v
canonical LctId (mb32)
   +-- binding proof
   +-- MRH
   +-- citizenship references
   +-- operational keys
   +-- lifecycle
   |
   +-- legacy_alias: lct:web4:member:<hex>
```

The legacy alias remains permanently useful for continuity and old-chain lookup.

## 3. Requirements

### FR1 — one canonical resolver

Resolve:
- plugin id;
- canonical LctId;
- verified Hestia legacy alias.

Return canonical member LCT + evidence.

Absence remains absence. A legacy label with no corresponding registry member must not fabricate presence.

### FR2 — prefer canonical identity on new records

Where schemas support an LCT identity, new action/witness/trust records should prefer the canonical `mb32` id.

Where a legacy field cannot change:
- retain it as compatibility metadata;
- add/resolvably expose canonical identity;
- do not rewrite historical chain entries.

### FR3 — trust continuity

Existing trust grains keyed by `lct:web4:member:<hex>` remain valid evidence.

Migration must preserve:
- entity continuity;
- role context;
- chronology;
- old queryability.

New trust surfaces should make canonical subject identity explicit while keeping legacy key provenance available.

### FR4 — operational key evidence

The canonical member LCT's binding-key-vouched operational key is the preferred verifier.

Names, plugin ids and legacy aliases identify the candidate; they do not prove the operational signer.

### FR5 — rotation/lifecycle

On key rotation:
- new canonical LctId;
- old LCT preserved;
- lineage/continuity recorded;
- legacy alias resolves according to explicit current/history policy;
- no silent alias mapping to two simultaneously active canonical presences.

Copied-seed/concurrent-presence detection remains [#840](https://github.com/dp-web4/hestia/issues/840), a separate evidence-integrity track.

### FR6 — vocabulary cleanup

Use distinct terms:
- plugin/member id;
- legacy member label;
- canonical LCT id.

Avoid new `*_lct` names when the value may contain a plugin id or legacy label.

## 4. Compatibility constraints

- no historical chain rewrite;
- no trust reset;
- no mandatory hardware binding;
- no refusal solely because presence is self-issued/low assurance;
- no hidden global trust threshold in the resolver.

## 5. Tests

Pin independently:
1. canonical member lookup;
2. legacy alias -> same canonical member;
3. plugin id -> same canonical member;
4. forged alias fails;
5. old trust grain remains attributable after canonical migration;
6. operational key verifies through LCT voucher;
7. rotation preserves old history and yields one current mapping;
8. absent canonical presence remains explicitly absent.

## 6. Dependencies

- Web4 public-key-derived ID correction: web4#819 or successor.
- Web4 lifecycle ruling: web4#874.
- Hardware-assurance evidence: web4#730.
- Hub member/reference convergence: web4#875.
