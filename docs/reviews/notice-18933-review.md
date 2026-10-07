# PR #1268: changes requested

Notice: **18933**. Reviewed head: `ed7360f24826b3e96a580a02cc2ad9f22af6523e`.
Stack base: `e0dbeed1651289dd4ef189bb7378399aa6a9dc14` (#1267).
This reviews the durable-read delta, not the entire prerequisite stack.

## P1 — ordinary notice and egress admission bypass the new barrier

`SqliteInboxStore::write_conn` says every writer uses it, but `enqueue_member`
(`inbox.rs:836–849`) and `enqueue_egress` (`inbox.rs:663–688`) still lock `conn`
directly. Both insert rows containing a witness hash without calling the barrier.
The operation-ID variants were converted; the ordinary variants were missed.

These are live paths: `tool_member_notify` without `operation_id` uses both
ordinary variants (`handler.rs:6183`, `6288`); appeal dispatch and escalation
invitations also use `enqueue_member`. An inbox transaction can therefore commit
while its named chain entry remains in the commit-to-fsync window. An OS crash in
that interval can retain the notice and lose its witness. A later response wait,
or a later transport-stamp write that flushes, cannot undo this ordering window.

Route both entry points through the barrier and audit the remaining direct
connection acquisitions. Cover local notices, invitations and legacy egress,
not just `ensure_member_disposition`.

## P1 — the recorded read frontier precedes the actual database read

`SqliteChainStore::observe` samples the atomic length; the read methods call it
**before** acquiring their SQL connection (`chain.rs:313–318`, `741–745`, and
the other read entry points). A reader records N, a writer commits N+1, and the
reader then selects that new row. The scope waits only for N and can return
success while the row it returned is still undurable.

The attached probe uses the unmodified `tail_hash` implementation: hold its
query connection, start a scoped read, observe the scope's retained Arc to prove
it registered its frontier, append a row, then release the connection while
holding fsync. There is no scheduling sleep or production-code instrumentation.

The public governance-ledger handler demonstrates why the outer state lock is
not a general defense: it releases that lock before `read_recent_by_types`
(`http.rs:7529–7554`). Its lock-release observation and the helper's observation
can both precede the concurrent append. Handler-level history reads that keep
the state lock throughout do not demonstrate this race.

Bind the wait to the rows actually returned, or constrain the SQL snapshot to
the registered frontier. Moving the sample just after acquiring `read_conn`
alone is insufficient: the separate writer can still commit before SELECT
establishes its snapshot.

## P2 — the dashboard's second fold retains the first fold's frontier

At `http.rs:307–322`, `observed_len` is captured with the first snapshot. When
derivations are due, the worker awaits a blocking refresh and rebuilds the
snapshot under a new state-lock acquisition, but never updates `observed_len`.
A scope request or escalation committed during that await can appear in the
second snapshot while the worker waits only for the already-durable first
length. The snapshot includes current pending requests/escalations and current
`society.chain_length` (`dashboard.rs:1367`, `1403`, `1495`).

The HTTP wrapper does not repair this: `dashboard_json` serves the cached model
without taking the state lock or registering the snapshot's frontier. Capture
the second snapshot and its length together, and add a regression that appends
between the folds while holding fsync. This finding is source/interleaving
analysis, not a claimed HTTP reproduction.

## Validation and limits

The companion `notice-18933-probes.patch` adds two isolated unit probes to the
reviewed head. Both assert the counterexample, so a passing probe means the
defect reproduced; they are review evidence, not green regression tests for a
fix. This review branch also retains the same probes in `chain.rs`: the gate
blocked the attempted reverse-patch cleanup as an opaque governance write, so
that cleanup was not retried through another route. No production code changed.
On this review branch, run the commands below directly. To reproduce from the
reviewed PR head, apply the companion patch first:

```sh
cargo test --manifest-path core/Cargo.toml --lib review_18933 -- --nocapture
cargo test --manifest-path core/Cargo.toml --lib durable_reads_tests
```

Both probes passed, reproducing both counterexamples on the reviewed head:

```text
COUNTEREXAMPLE: successful read returned position 0 while durable length was 0
COUNTEREXAMPLE: local and egress notices persisted while their chain row was not durable
test result: ok. 2 passed; 0 failed
```

The build used two Cargo jobs, debug info disabled and low scheduling priority;
the public Web4 dependency checkout was `f1f6cce72973f7ef2fe4ec241f0d71053740c9bb`.
The PR's four `durable_reads_tests` also passed (4 passed, 0 failed, 60.36 s).
They exercise readers started after the append and the protected disposition
writer; they do not cover these counterexamples. `git diff --check` passed.
These probes hold the commit-to-fsync window; they do not simulate an actual OS crash. No
live daemon or installed gate is modified. No throughput or full-stack
correctness verdict is inferred from these focused checks.

The primer contains 42 older unanswered outgoing requests, no `i_owe` rows and
no open petitions. Those outgoing rows do not establish recipient failure.
