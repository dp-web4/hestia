# Hestia 1280 re-review

**HOLD at `16a1d50051dd0abc366a8ccfdb17a5b01078ee76`: one new P2 dashboard
polling regression.** The three findings at `479d92fb` are resolved. This review
answers notice 20626 and the author's
[fix report](https://github.com/dp-web4/hestia/pull/1280#issuecomment-6116981216).

## P2: successful slow polls never update the dashboard

`app/src/hooks/useDashboard.ts:20-24` increments `latest` whenever a request
starts, then discards a response unless no newer request has started. The effect
still starts a request every two seconds (`:54-56`; `Dashboard.tsx:10`).

For a reachable, compatible daemon whose dashboard calls consistently take 2.5
seconds, request 2 starts before request 1 answers, request 3 starts before
request 2 answers, and so on. Every successful result is discarded indefinitely.
On initial mount the page remains at “Connecting to Hestia daemon...”; an already
loaded page retains old data. The same rule can prevent clearing a previous
incompatibility panel when the recovered daemon is slow.

The committed real React hook test uses fake timers and successful promises:
after ten seconds, six requests have started and four have completed successfully,
but `data` is still `null` and `online` is still false. A 1.5-second latency
control passes. Removing just the four `mine !== latest.current` guards makes
the 2.5-second test pass; the production file was restored afterward.

Prevent older results from overwriting newer accepted results without requiring
each response to beat the polling interval. For example, serialize/coalesce polls,
or track the latest applied response separately from request starts. Preserve
invalidation on endpoint/auth changes and the older-failure/newer-success guard.
Keep a regression test with latency greater than the polling interval.

## Earlier findings resolved

- **Endpoint/session binding:** production transport captures one endpoint;
  compatibility checks refuse a changed selection and the session's generation
  controls token reuse and publication. All six new socket/state regression tests
  pass in the review harness, including delayed probe, cross-endpoint token use,
  delayed reauthentication and a 401 followed by incompatible replacement. The old
  probe's expectation that B must receive a version request is intentionally not
  reused: aborting the operation, with neither daemon receiving the mutation,
  satisfies the original finding.
- **Recovery in place:** the successful-refresh branch clears the stale handshake.
  All three author-supplied React recovery tests pass, for incompatible, missing
  version endpoint and malformed states. The new finding above concerns the
  scheduling guard added alongside that fix.
- **Android version guard:** the build depends on the `version` job. Executing its
  exact shell body locally gives exit 0 for tag `v0.3.0`, exit 1 for tag `v9.9.9`,
  and exit 0 for branch `release/lockstep-0.3.0`. The release attachment remains
  tag-only. No release was attempted.

## Evidence and limits

- Rust recheck: **16 passed**, comprising the six transport/state tests and ten
  handshake tests. It compiles production `daemon.rs`, `handshake.rs`,
  `operator.rs`, and AppState extracted from `lib.rs`. Only vault/signing are
  synthetic; raw test listeners accept synthetic authentication. This is not a
  full Tauri build, cryptographic validation or live-daemon run. As with the prior
  harness, its relocated manifest does not exercise the optional root-VERSION
  assertion; the version-sync check covers the real manifests separately.
- React suite: **65 passed, 1 failed**: all 63 existing tests pass; independent
  fast-poll and stale-failure controls pass; the slow-success test fails as above.
- TypeScript check and Vite production build pass under Node 22.22.0.
- `tools/version_sync_test.py` passes all 17 version-site checks. The exact Android
  version step passes/refuses/passes the three cases listed above.
- The 15-second compatibility cache remains bounded evidence, as previously
  documented. Re-probing on 401 improves replacement detection; it does not make
  preflight and dispatch atomic with a server generation.
- Endpoint capture prevents sending A's token or mutation to unprobed B. The
  stronger prose promise of stopping before *every* subsequent send is not fully
  implemented: `operator::authenticate` can finish its challenge/session exchange
  against captured A after a selection change, then discard the late session.
  This does not reopen the original cross-endpoint finding; avoid describing it
  as per-request cancellation of all in-flight authentication traffic.
- No installer change or deployment is part of this review.

Reproduce from this review branch:

```sh
cargo test --offline --manifest-path docs/reviews/pr1280-recheck/Cargo.toml --target-dir /tmp/pr1280-review-target -j 2
cd app
npm ci
npm test
npm run build
```

Use a Node version supported by the app dependencies. `npm test` intentionally
returns nonzero until the polling regression is fixed; the added evidence is
`app/src/hooks/useDashboard.review.test.tsx`. The Rust harness owns its manifest
and lockfile and changes no production dependency declarations.
