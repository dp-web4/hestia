# ADR-0003: License — AGPL-3.0-or-later

**Date:** 2026-05-15
**Status:** Accepted
**Authors:** dp + CBP-Claude (Opus 4.7)

## Context

Hestia needs an open-source license. The dp-web4 family of projects has a documented preference for AGPL-3.0-or-later, with a brief MIT detour in February 2026 (for ARIA grant compatibility) that was reverted to AGPL after the ARIA decision was no-submit and the patent grant in PATENTS.md (AGPL-bounded) created a license trap with MIT.

## Decision

**AGPL-3.0-or-later** for all open-source components of Hestia (the Tauri app, the Rust core, the Plugin Authoring Kit in all three language editions, the reference plugins).

A commercial license tier (TBD pricing) grants proprietary use rights for companies that need to integrate Hestia into closed-source products.

## Rationale

- **Matches existing pattern.** web4-core, web4-trust-core, web4-sdk are all AGPL. Hestia is part of the same family.
- **Forces commercial users to engage.** AGPL's network-use clause means a SaaS company integrating Hestia must either publish their modifications or buy the commercial license. This is the upsell path that funds development.
- **Doesn't constrain individual users.** Individual end-users running Hestia for themselves (the free tier's primary audience) face no obligation. AGPL only matters when distribution or network service happens.
- **Premium individual tier is unaffected.** Hardware binding, cloud backup, recovery flow — all of these are AGPL software that we sell as a service / convenience. Users on the premium tier can still see all the code; they pay for the service of hardware integration and the cloud backup endpoint.

## Trade-offs accepted

- **AGPL is stricter than MIT.** Some companies will refuse to use AGPL software due to internal policy. They become candidates for the commercial license tier.
- **Some open-source contributors may avoid AGPL.** Counter: AGPL is widely used (GitLab Community, MongoDB Community Server, Element, Nextcloud). The AGPL ecosystem is healthy.

## Alternatives rejected

- **MIT** — maximizes adoption, but lets commercial integrators free-ride forever. Inconsistent with the upsell strategy. Documented prior reversion (Feb 2026).
- **GPL-3.0** — similar to AGPL but lacks the network-use clause. For a piece of software that's expected to be integrated into SaaS products, this matters.
- **BSL (Business Source License)** — time-bombed license that converts to OSS after N years. Currently uncommon and confusing for users.
- **Dual MIT/Apache-2.0** (Rust ecosystem default) — maximally permissive, gives no commercial leverage.

## Consequences

- `LICENSE` file at repo root contains the full AGPL-3.0 text.
- All Rust crates declare `license = "AGPL-3.0-or-later"`.
- The Python and TypeScript packages declare the same.
- Plugin authors writing AGPL-compatible plugins can submit to this repo freely.
- Plugin authors with a closed-source agent host must obtain the commercial license (or write an AGPL adapter that meets the AGPL terms).
- Contribution policy: contributions are under AGPL by default; no CLA required.

## What this does NOT do

- It does NOT prevent open-source plugins under other compatible licenses from being submitted (subject to AGPL compatibility analysis per contribution).
- It does NOT mean enterprise users can't use Hestia — they just need the commercial tier if they want to wrap it in a closed-source product.
- It does NOT lock the project into AGPL forever — the maintainers may dual-license to a permissive license in the future if the strategy changes (subject to contribution agreements; this is why we don't require a CLA — we want contributors to retain their copyrights so the project can't be re-licensed against their will).
