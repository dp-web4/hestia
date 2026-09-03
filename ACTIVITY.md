# Repository Activity

This file exists for humans and automated due-diligence readers that may receive a stale or partially cached GitHub repository page. GitHub's rendered **N commits** counter is convenient UI, but it is not the authority for project activity. The block below is plain committed text derived from Git history and tied to exact default-branch HEADs.

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

## Why plain text

Automated retrieval systems can cache GitHub's rendered repository page independently from repository file contents. A stale dynamic counter can therefore look authoritative while contradicting the actual history. This file makes the important claim explicit, dated, reproducible, and available as ordinary repository content.

Refresh from sibling full-history checkouts with:

```bash
python3 tools/update_activity_snapshot.py \
  --repo Hestia=. \
  --repo Web4=../web4 \
  --target ACTIVITY.md \
  --target STATUS.md
```
