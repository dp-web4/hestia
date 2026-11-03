**Independent source review — kimi-code, current `9b42800750b8596dd64f606ec825ef0474efe11d`. HOLD on ordinary-release/new-hold ordering.**

The ledger-based absent-release reconciliation addresses the earlier delete-without-witness gap in the right direction: do not witness before deleting, and use the last hold as the pending evidence. The absent-path tests and all four hosted cargo jobs are green. I found a distinct interleaving in the ordinary `release_held` path, however.

At `hub/hub-daemon/src/rest.rs:1485-1503`, `release_held` deletes the old file and only then calls `witness_release(reason, false)`. `witness_release` defines `owed` as `ledger_holds(...) && !(absent_only && path.exists())`. With `absent_only=false`, a new file does not matter, and `ledger_holds` says only that the latest ignition event is *some* hold—not that it is the same hold whose file this operation deleted.

Therefore this interleaving appears possible unless an external serialization rule excludes it:

1. the ledger contains `Held(old)` and `release_held` deletes the old copy;
2. a concurrent human unlock seals a new copy and appends `Held(new)`;
3. the first operation enters `witness_release(reason, false)`;
4. both `owed` checks still pass because `Held(new)` is a hold, and it appends `Released(old)` **after** `Held(new)`.

The result is a new file on disk while the ledger's latest ignition event says released. It also contradicts the doc comment's statement that a release cannot land after a newer `IgnitionHeld`: `append_signed` rejects a stale tail, but this release is authorized against the *new* tail, so that check does not establish hold identity. I found no unlock/seal mutex that excludes the law-amendment versus human-unlock interleaving. The existing race tests exercise `reconcile_absent`/`absent_only=true`, not this ordinary-release arm.

Please bind a normal release to the exact prior hold (for example an expected ledger/hold generation captured before deletion) and refuse or reconcile if a newer hold arrives first, or prove and test an equivalent serialization rule. Add a deterministic control that pauses `release_held` after deletion, lands a real new seal plus `IgnitionHeld`, then resumes the old release and requires that no old release follows the new hold. Check daemon and offline law changes as applicable. This is a source-level counterexample, not a claimed live credential event; no live law or credential was touched.
