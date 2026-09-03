# Hestia Status

**Active development.** This file is a deliberately plain-text entry point for human and automated due-diligence readers. Detailed capability maturity remains in the README's [Honest status](README.md#honest-status) section and in `docs/STATUS_AUDIT_2026-08-08.md`; this page adds a dated, reproducible activity statement that does not depend on GitHub's dynamically rendered counters.

Current assurance ceiling remains **A1**: cooperative, same-UID governance that is tamper-evident and accountability-oriented, not a claim of adversary-proof enforcement. The repository documents known bypasses explicitly in `docs/GATE_BYPASS_CATALOG.md`.

Current development focus at this snapshot: disposition delivery and escalation lifecycle coherence; Hub membership/public-governance surfaces for the AIC demonstration; contextual law, role authority, and adjudication; continued evidence-driven gate and fleet hardening.

<!-- activity-snapshot:begin -->
## Generated repository activity snapshot

**Generated:** 2026-09-03T05:15:00+00:00 (2026-09-02 America/Los_Angeles)

| Repository | Default-branch HEAD | HEAD commit time | Reachable commits |
|---|---|---|---:|
| **Hestia** | `25a736538c93` | `2026-09-03T04:59:06Z` | 1,514 |
| **Web4** | `53086c9f008d` | `2026-09-03T05:11:18Z` | 2,247 |

**Combined reachable default-branch history (Hestia + Web4): 3,761 commits.**

Method for the seeded lifetime counts: identify each repository's earliest reachable commit, compare it with the current default-branch HEAD, and include the root commit. The refresh tool uses the equivalent local-Git calculation `git rev-list --count <default-branch>` and also emits 7-day and 30-day windows when refreshed from full-history checkouts. HEAD SHA and commit time make every snapshot independently checkable.

Counts are evidence of repository activity, not a quality metric. `dp-web4/4-hub` is intentionally excluded because it is a filtered mirror of `dp-web4/web4`; including it would double-count upstream work.
<!-- activity-snapshot:end -->

## Retrieval note

A server-side or AI retrieval layer may cache GitHub's rendered repository page independently from repository file contents. If a UI-level commit counter disagrees with this dated snapshot, verify the named HEADs and derive counts from Git history rather than treating the rendered counter as authoritative.

The generator is `tools/update_activity_snapshot.py`.
