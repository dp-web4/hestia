# PR #1280 polling fix recheck

**PASS at `71d7733cfffd7b1eb38d089f9cdb032402538cad`: the outstanding
slow-poll blocker is resolved.** No new blocking finding in the two-file delta
from `16a1d500`. This answers notice 20632 and the author's
[fix report](https://github.com/dp-web4/hestia/pull/1280#issuecomment-6117059578).

`useDashboard` now orders results against the latest applied response, so a
later request starting does not suppress an earlier successful response. The
2.5-second response / 2-second polling reproduction passes. A separate floor
invalidates requests started before an auth or URL-change event, even if the
new context has not answered. Both asynchronous status continuations repeat
the stale check, preventing an older status success or failure from overwriting
newer state. The applied counter advances in both dashboard success and failure
branches, preserving ordering across opposite outcomes.

## Validation

- Submitted app suite: **68/68 pass**.
- With eight independent ordering checks in
  `app/src/hooks/useDashboard.ordering-review.test.tsx`: **76/76 pass**.
  They cover status resolution and rejection after a newer success, after an
  auth event, and after a URL event; pre-auth successful-response invalidation;
  and successful responses arriving in reverse request order.
- TypeScript and Vite production build pass with Node 22.22.0.
- Three temporary mutations run against the 13 focused hook tests establish
  sensitivity:

| Mutation | Result |
| --- | --- |
| Replace stale predicate with latest-start ordering | 1 failure: 2.5-second polling reproduction |
| Remove the context floor from the predicate | 6 failures: both events' status continuations and pre-event successful responses |
| Remove only the two status-continuation guards | 6 failures: old status resolution/rejection across all three boundaries |

The production hook was restored byte-for-byte after mutation checks. The
independent tests and this report are the only committed review additions.

## Scope and carried limits

This is a focused recheck of the only production change since the
[previous review](https://github.com/dp-web4/hestia/blob/13fe46c6/docs/reviews/pr-1280-recheck-codex.md).
The earlier endpoint/session, recovery and Android-version findings remain
resolved on that evidence. Rust, workflows and manifests did not change in this
delta; their earlier checks were not rerun. This run does not establish a full
Tauri build or live-daemon behavior.

The previously documented 15-second compatibility-cache tradeoff and captured
endpoint authentication-exchange limitation remain. This review does not claim
per-send cancellation of all in-flight authentication traffic. No merge,
release or deployment was performed.

Reproduce from this review branch with a supported Node version:

```sh
cd app
npm ci
npm test
npm run build
```
