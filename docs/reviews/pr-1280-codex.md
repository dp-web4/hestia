# Hestia 1280 independent review

Codex review for the release author and integrators. **HOLD** at
`479d92fb538d04f6b01dfecab5a48bc54995a922`: fix the endpoint-binding race, dashboard
recovery, and Android publication guard before merging. No implementation, deployment,
or held-patch application is included in this review.

## P1 Bind compatibility evidence to the dispatched endpoint

In `app/src-tauri/src/daemon.rs:134`, `ensure_compatible(state)` snapshots the URL
and awaits its version response. At line 138, `request_status` reads the URL again.
Changing Settings while the probe is pending lets a response from compatible daemon A
authorize an operator request to unprobed daemon B. The new URL might be incompatible;
the cache being keyed by URL does not protect this in-flight request.

The attached `url_switch_must_not_dispatch_to_unprobed_daemon` test holds A's response,
switches the production AppState to B, then releases A's compatible response. B's first
request is **POST /api/scope/grant**, including a synthetic bearer, not GET /api/version.
The transport returns success against the test responder. This demonstrates dispatch,
not a grant accepted by a real daemon. The initially incompatible control refuses the
operator request correctly.

Capture an endpoint/configuration generation for the operation and bind the compatibility
result, session and request to it. Abort if selection changes, or consistently complete
against the captured endpoint. Apply the same rule to sign-in and 401 reauthentication:
those paths also reread `state.daemon_url()` after an await, and a late sign-in can publish
a session into state after the selected endpoint changes. Add delayed-response regression
tests, including a 401 followed by an endpoint switch.

The pre-existing transport already lacked endpoint-bound sessions; this PR introduces a
compatibility preflight that does not dominate dispatch to the endpoint it purports to check.
This is not evidence of a new daemon-side authentication bypass.

## P2 Clear the dashboard incompatibility state after recovery

`app/src/hooks/useDashboard.ts:18-22` refreshes data, online state and errors after success
but never refreshes or clears `handshake`. Once a failure stores `incompatible`,
`no_version_endpoint` or `malformed`, subsequent successful polls leave that state intact.
`Dashboard.tsx:34` checks it before rendering the recovered data, so the dashboard continues
to show the blocking panel until it remounts. The independent banner's polling does not
update this hook's state.

The dependency-free hook probe executes the production callback with minimal state-hook
stubs. After incompatible then successful responses it records:

```json
{"data":{"recovered":true},"online":true,"error":null,"handshake":{"state":"incompatible"}}
```

Update or invalidate the compatibility state on successful recovery, preferably with one
shared endpoint-bound status source. Add a real React test for incompatible to compatible
recovery without navigation, including the malformed and missing-endpoint states.

## P2 Guard Android publication with the same version check

`.github/workflows/app-android.yml:22` now runs on release tags and lines 115-119 attach
the APK to that release, independently of `release.yml`. Unlike the daemon workflow,
it never executes `tools/version_sync.py --tag ...` or depends on an equivalent check.

A tag such as `v9.9.9` on this 0.3.0 tree is rejected by the daemon's version job but
still reaches Android build/publication if that build succeeds. This would publish an
APK containing version 0.3.0 under a 9.9.9 release. The tag need not be published to
establish the workflow gap; this is a source-level finding, not an executed release.

Run the version-site check before every Android build and require tag equality for tag
publication, while allowing branch-dispatched artifacts. Test a matching tag, a mismatched
tag, and a branch dispatch. Desktop packaging remains a separately declared non-goal of
this PR and is not counted as a defect here.

## Cached compatibility is bounded evidence rather than an execution guarantee

The 15-second cache also permits a mutation after a same-URL daemon replacement without
querying the replacement. The attached cache probe demonstrates that dispatch with a
synthetic compatible cache entry and a responder that would report a different API
generation if queried. This is the documented TTL tradeoff, recorded separately rather
than presented as a surprise fourth blocker.

Do not describe this as an absolute guarantee that no incompatible daemon receives an
operator route. Recheck on session invalidation and consider uncached checks before
consequential operations. Even a fresh HTTP preflight cannot atomically bind a subsequent
request to a server generation; a strict guarantee needs a request/session protocol that
the server enforces.

## Evidence and limits

The lightweight Rust probe compiles the production `daemon.rs`, `handshake.rs`, and the
AppState definitions and implementation extracted verbatim from `lib.rs` (excluding the
Tauri import). Vault and authentication interfaces are stubs; tests use only synthetic
tokens and disposable listeners. It is not a full desktop or live-daemon test.

- Rust probe: **11 passed, 2 failed**. Ten existing handshake tests and the initially
  incompatible control pass; endpoint switching and cached replacement assertions fail.
  The existing optional root-VERSION file assertion is not exercised from this probe's
  different manifest directory; the separate version-sync suite checks the real version sites.
- Dashboard hook probe: **fails**, retaining the blocking handshake after success. This
  tests callback state transitions, not React rendering.
- Passed locally: `version_sync_test.py` (17 sites), `build_tag_match_test.py`,
  `deploy/from-main/build_identity_test.py`, `upgrade_path_plumbing_test.py`, and
  `plugins/member-mesh/tests/daemon_drift_check_test.py`.
- Latest observed CI passes include app build/tests, live app-daemon contract, upgrade
  path, SDK conformance, pinned Web4 build, hook tests, plugin-Python tests and gate ratchet.
  The full cargo job was still running at the last check.
- Full core/Tauri builds and a live contract run were not repeated locally. The review
  build used two jobs, disabled debug information and incremental compilation, and occupied
  approximately 223 MB. No live credentials or services were touched.
- Build-id producer/consumer changes pass the named tests. The installer change remains
  held and unapplied; its digest-backed exception is not deployment evidence.

Reproduce from the repository root, using a writable target directory:

```sh
cargo test --offline --manifest-path docs/reviews/pr1280-probe/Cargo.toml --target-dir /tmp/pr1280-review-target -j 2 -- --nocapture
node docs/reviews/pr1280-dashboard-probe.cjs
```

Both commands intentionally return nonzero at the reviewed head. The probe has its own
Cargo.lock and does not alter production manifests or locks. The live contract currently
tests classification and authentication separately; it does not exercise the shared
`request_status` transport's endpoint/cache transitions, which is why green contract CI
does not settle the findings above.
