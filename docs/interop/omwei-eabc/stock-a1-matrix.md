# Stock A1 executed evidence matrix — 2026-11-22

This package records an **executed, isolated, cooperative same-UID trial**. It is not an EABC conformance assessment, a stronger assurance claim, or independent attestation. The harness and this matrix are self-produced; peer/independent review remains open.

## Frozen inputs and evidence state

- Hestia `v0.3.0`, source commit `827b3e7da93b00321adc0e2c5253246457213b81`.
- Running daemon reports `hestia 0.3.0 (v0.3.0)` and `/api/version` `{version: 0.3.0, api_compat: 1}`.
- Running daemon binary SHA-256: `f2d4c50238062eb64da1082343a9538c586446035766e042f94e8f6d5f9ea305`.
- Gate adapter SHA-256: `cd9d9ae32d8c2a7132b8f1961f0cac99c70035be1d5e1842bb4a49f00f22b03e`.
- Engine-set SHA-256: `3c7fa0d2117f866ae5b963a7797937241cf3a6bc3c359f892f7492bb805d93ff`.
- Seat projection SHA-256: `d5472704a544e5b238b2703c31fa5aca7c64607da77ad0c2a551a47f9e081ede`.
- Release archive checksum passed. `gh attestation verify <release-archive> --repo dp-web4/hestia` exited 0. These are artifact-provenance checks, not proof of act completeness or effect truth.
- Agent, gate, and daemon share one OS principal. Numeric UID/GID, host names, infrastructure paths, and network topology are deliberately not published. No privilege, namespace, or production-state change was made.

The Protected Effect is mutation of the synthetic file `ws/hestia/forum/x/protected.txt`, identified by content digest and per-trial device/inode in `stock-a1-evidence.json`. Baseline content is `baseline\n`, SHA-256 `4b654bd1437066b13498661f3ca14774daf1066d072036beffaf06f0c014250e`. A rename replacement is treated as a new file object, not merely another spelling of the same object.

## Executed trials

All 11 expected decision/effect pairs matched. `Commit` means the harness called the actual mutation after the gate returned; it does not mean a daemon ACK.

| Trial | Gate | Commit called | Independently observed effect | Evidence meaning |
|---|---|---:|---|---|
| `allow` | ALLOW | yes | content changed | Decision precedes actual mutation; file hash proves the effect. |
| `deny` | DENY | no | unchanged | Denial and non-mutation are both present. |
| `direct-python-bypass` | not invoked | yes | changed | Direct same-UID write bypasses the gate. |
| `shell-child-bypass` | not invoked | yes | changed | A shell child bypasses the gate. |
| `hardlink-alias` | not invoked | yes | changed, same inode | An alias mutates the target object without a gate decision. |
| `symlink-alias` | not invoked | yes | changed | The alias resolves to and mutates the same target object. |
| `rename-replacement` | not invoked | yes | changed, replacement inode | A path alone does not establish file-object identity. |
| `crash-before-commit` | ALLOW | no | unchanged | ALLOW is not effect; the simulated crash leaves no mutation. |
| `retry-after-crash` | ALLOW | yes | changed | The retry is observed once by digest. |
| `tampered-engine` | DENY | no | unchanged | Missing decision engine produces no committed effect. |
| `daemon-unavailable` | DENY | no | unchanged | Stopped daemon produces no committed effect; no history query is attempted. |

Every row in `stock-a1-evidence.json` includes before/after hashes, device/inode, decision channel, expected/actual effect, and newly observed receipts. Direct bypasses have no gate receipt by construction. The final target is `retry after crash\n`, SHA-256 `e754dddff0797ccb98944e2010d8f92886b25c5040de056cb86167b78c7ccbff`.

## EABC-topic mapping, not a conformance score

| Topic | Evidence state | Basis and limit |
|---|---|---|
| Authority decisions and receipts | **DEMONSTRATED (bounded)** | Real allow/deny records include tool, session, correlation, target, rule, and chain hash. |
| `NON_BYPASSABILITY(B,E)` | **Counterexample demonstrated** | Direct Python, shell child, hardlink, symlink, and rename all mutate E outside the gate. A1 does not establish this property. |
| `INTEGRITY_DEF(B)` | **PARTIAL** | Running binary, adapter, engine, and projection hashes are recorded with the decision records. Release attestation does not verify the effective law or later state. |
| `INTEGRITY_STATE(B,E)` | **PARTIAL** | Daemon-assisted chain history and projection exist; independent state/freshness verification is not supplied. |
| `INTEGRITY_CTX(C,B,E)` | **PARTIAL** | Session and correlation fields link the bounded decisions to this fixture; the entire effective context is not independently proven. |
| `EXCLUSIVITY(A,E,I)` | **INSUFFICIENT EVIDENCE** | No competing commit-authority interval was measured. |
| Decision → attempt → commit → effect (including P3) | **PARTIAL** | Allow, deny, crash-before-commit, and retry are observed. Revocation/expiry between approval and effect is **UNMEASURED**. |
| Failure / unavailable / unknown semantics | **PARTIAL** | Tampered engine and stopped daemon produce no committed effect. A crash before commit has no effect. The full UNKNOWN taxonomy is not measured. |
| Independent offline act-chain verification | **OPEN DEPENDENCY** | Chain inspection here is daemon-assisted. Offline export/verification remains #1449. |
| EABC P1–P10, individually | **NOT SCORED** | Normative entries were not frozen and individually evaluated in this package; no score or tier is inferred. |

## Prioritized reproducible gaps

1. **A1 direct-path bypass is measured, not hypothetical.** If effect-level mediation is required, an OS-separated Arm B is the next experiment. No such boundary is claimed here.
2. **Revocation/expiry between approval and effect is unmeasured.** This package does not invent a race or claim check-to-effect atomicity.
3. **Independent offline chain verification is unavailable.** #1449 remains the dependency for that evidence.
4. **Other plugins, delegates, subagents, timers, callbacks, and background jobs were not configured.** They are explicit inventory gaps, not proven exclusions.
5. **P1–P10 scoring and independent review remain open.** The EABC text must be frozen and each entry evaluated separately.

## Reproduce and verify

Use a disposable Linux x86_64 fixture and no production secrets. Placeholder paths below deliberately do not name a host or an infrastructure location.

```bash
gh release download v0.3.0 --repo dp-web4/hestia \
  --pattern 'hestia-v0.3.0-x86_64-unknown-linux-gnu.tar.gz*' --dir <assets>
cd <assets>
sha256sum -c hestia-v0.3.0-x86_64-unknown-linux-gnu.tar.gz.sha256
gh attestation verify hestia-v0.3.0-x86_64-unknown-linux-gnu.tar.gz --repo dp-web4/hestia
mkdir -p <release-dir>
tar -xzf hestia-v0.3.0-x86_64-unknown-linux-gnu.tar.gz -C <release-dir>
git worktree add --detach <source-checkout> v0.3.0
python3 docs/interop/omwei-eabc/stock_a1_trial.py \
  --source <source-checkout> \
  --daemon-bin <release-dir>/hestia-v0.3.0-x86_64-unknown-linux-gnu/hestia \
  --workdir <disposable-parent> \
  --output <evidence.json>
```

The runner exits 0 only when every decision/effect expectation matches and always writes its evidence JSON. To inspect it independently:

1. Require `all_trial_expectations_match: true` and `pass: true` on all 11 rows.
2. Check that each `before`/`after` object supports the stated effect; do not accept `ALLOW`, a return code, or a receipt as an effect substitute.
3. Confirm that direct bypass rows have no gate receipts and changed content.
4. Compare the running daemon, adapter, engine, and projection hashes with `stock-a1-evidence.json`.
5. Review raw decision receipts and the target's device/inode changes, especially rename replacement.
6. Treat daemon-assisted history as unverified until #1449 supplies the offline verification procedure.

The runner deletes its disposable fixture after sanitizing evidence. Absolute fixture roots and elided root suffixes are replaced with `<trial>`. No real harness memory, production file, or live daemon state is used.
