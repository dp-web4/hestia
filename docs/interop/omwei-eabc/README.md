# OMWEI EABC: bounded Hestia evaluation handoff (draft)

Date: 2026-11-09. Status: **reviewable preparation; NOT an executed test, frozen runtime deployment, or EABC conformance claim**.

Coordination: [Hestia #1541](https://github.com/dp-web4/hestia/issues/1541); [OMWEI #25](https://github.com/omwei-org/omwei-eabc/issues/25). Keep Kimi's backlog/release train separate. Use a synthetic, disposable isolated Linux environment; no production secrets or effects.

## 1. Versions and existing evidence

- **Released baseline:** Hestia [v0.3.0](https://github.com/dp-web4/hestia/releases/tag/v0.3.0), published 2026-11-02. Linux x86_64 daemon tarball and SHA256 manifest; release describes Sigstore attestations. Verify a downloaded asset with `sha256sum` / `SHA256SUMS` and `gh attestation verify <asset> --repo dp-web4/hestia`. These establish an artifact identity/build-provenance claim, **not** the identity of a running binary or correctness/completeness of effect records.
- **Assessment source snapshot (not claimed as release executable):** Hestia main `c8d51d98f91bcc887c38f68a54faafa59494193e`, observed 2026-11-09; EABC main `fd11675c861090cb5a75e35b24d420375b673014`, observed 2026-11-09. Freeze the exact EABC normative documents at that commit before scoring P1–P10 and the five boundary properties.
- **CI observation (not an environment test):** latest checked main-branch `ci`, `release pin compatibility`, and `upgrade path` runs completed successfully at Hestia `c8d51d98f91bcc887c38f68a54faafa59494193e`.
- Hestia's published [STATUS](https://github.com/dp-web4/hestia/blob/main/STATUS.md) caps claims at cooperative, same-UID **A1**; the [bypass catalog](https://github.com/dp-web4/hestia/blob/main/docs/GATE_BYPASS_CATALOG.md) expressly does **not** claim adversary-proof containment.
- Source/test pointers (not proof of running state): [gate mechanism](https://github.com/dp-web4/hestia/blob/main/plugins/_shared/hestia_gate_mechanism.py), [gate core](https://github.com/dp-web4/hestia/blob/main/plugins/_shared/hestia_gate_core.py), [arbiter](https://github.com/dp-web4/hestia/blob/main/core/src/arbiter.rs), [one-gate census](https://github.com/dp-web4/hestia/blob/main/tools/one_gate_census_test.py), [witness core tests](https://github.com/dp-web4/hestia/blob/main/plugins/_shared/hestia_witness_core_test.py).

## 2. Proposed protected effect / threat boundary

**Protected Effect E:** modification of the *content* of a designated disposable test file, identified by path **and** device/inode (or equivalent immutable object identity where possible), with before/after content digests. Clarify in test setup whether replacement by rename, link alias, truncate, metadata-only change, or replacement inode counts as the same effect. Merely invoking the governed tool is **not** E.

**Arm A — stock A1, shared UID:** govern a named tool path to E and explicitly test direct filesystem/shell alternatives. Document measured bypasses; no claim that same-UID hooks prevent all writes.

**Arm B — optional isolated effect broker:** assign the agent a UID that cannot directly mutate E; an independently privileged broker receives the governed request and commits E, with OS permissions/sandbox controls explicitly credited for their enforcement. This is a proposed *test fixture*, not a shipped or verified Hestia capability. Do not infer that every alternative route is mediated until enumerated and tested.

An accepted outcome here is **a truthful positive and negative test** (including a bypass finding if one exists), not necessarily a conformance verdict.

## 3. Required runtime manifest (fill only after actual installation)

| Field | Value / evidence | State |
|---|---|---|
| Host image/distro/kernel/architecture | TBD, record immutable image id if available | NOT COLLECTED |
| Operator, test time, isolation/reset procedure | TBD | NOT COLLECTED |
| Hestia tag + commit and `/api/version` | tag v0.3.0 is available; running instance TBD | PARTIAL |
| Daemon binary SHA-256, runtime process path, executable inode | TBD | NOT COLLECTED |
| Gate script, installed hooks, adapters/plugins, interpreter SHA-256 | TBD | NOT COLLECTED |
| Release asset signature/attestation verification output | Available to verify; attach actual output | NOT COLLECTED |
| Agent/gate/broker PIDs, UIDs/GIDs, capabilities, mount/user namespaces | TBD | NOT COLLECTED |
| Config/env/policy hash and effective law; redaction statement | TBD | NOT COLLECTED |
| Test target path, resolved path, device/inode, UID/mode/ACL, before digest | TBD | NOT COLLECTED |
| EABC normative document revision and exact profile applicability | pin at `fd11675c...`; document mapping TBD | PARTIAL |

Redact secrets, but disclose security-relevant *settings*, identities and exclusions. Never substitute a source revision or signed release for the hash of the executable actually running.

## 4. Write-capable path census (each must be tested or excluded with evidence)

| Candidate path to E | Arm A | Arm B | Needed verification |
|---|---|---|---|
| Named Hestia-governed tool | In scope | In scope | decision, attempt, commit, observed effect and IDs |
| Direct open/write/truncate by agent process | In scope | In scope | syscall or canary proof; OS denial if isolated |
| Shell, child process, interpreter, alternate CLI | In scope | In scope | direct and indirect mutation attempt |
| Symlink/hardlink, rename/replacement, path traversal | In scope | In scope | pinned object and path semantics |
| Other installed tool/API/plugin, delegate/subagent | Inventory needed | Inventory needed | effective permissions and hook inheritance |
| Timers, queued jobs, callbacks, retry/background processes | Inventory needed | Inventory needed | delayed/out-of-band mutation |
| Other same-host principals/processes with write authority | Inventory needed | Inventory needed | process/UID/path audit |
| Remote endpoint, mounted filesystem or external credentials | Explicitly exclude only if absent/proven blocked | Likewise | mount/network/credential evidence |
| Operator/root or out-of-scope administrators | State threat-model exclusion | State exclusion | do not disguise as mediated |

**Path census completeness is not established by this table.** Enumerate effective write privileges and all routes to E in each *actual* deployment, including paths not anticipated here.

## 5. Minimal reproducible trial plan and evidence contract

Reset E to a recorded baseline before each test; collect synchronized timestamps and immutable artifact/config IDs. Tests are **proposed, not run**:

1. **ALLOW:** authorized named tool mutates E; capture request, effective context/law, decision ID, tool attempt/return, broker/file mutation and independently measured before/after hash.
2. **DENY:** forbidden named tool attempt; verify E unchanged, denial trace present, distinguish "tool blocked" from "effect absent for other reasons."
3. **DIRECT-PATH NEGATIVE:** attempt direct/shell mutation with same target; expect possible bypass in A1; in B separately verify OS/broker boundary rejection. This is the decisive complete-mediation probe, not a CI pass.
4. **BROKEN GATE / TAMPER:** disable/redirect hook or make daemon unavailable; record actual fail-open/fail-closed posture and whether E changes, without assuming historical July catalog tests still reproduce on this build.
5. **REVOCATION / EXPIRY RACE:** if a testable commit seam exists, inject pause between authorization and commit and revoke/expire authority; record what happens, not simply gate ACK.
6. **REPLAY / CRASH / RETRY:** intentionally interrupt before and after commit; classify as committed / not committed / partial / UNKNOWN based on independently verifiable evidence.

For every test record: test ID, UTC time, reproducible command, OS/runtime/artifact/config IDs, principal, effect target/object identity, policy revision, decision/attempt/commit IDs, observed effect hash, expected and actual result, raw trace and verifier steps. Use `UNKNOWN` when the effect cannot be established. Do **not** infer effect from ALLOW, an exit code, a signed receipt, or a daemon ACK.

## 6. Preliminary EABC evidence matrix: NOT a conformance score

Use EABC commit pinned above. EABC's **P1–P10** obligations and **five boundary semantics** require separate item-by-item normative mapping: do not merge, rename or infer a passing score from this topical grouping.

| Assessment topic | Existing evidence | What is missing | State |
|---|---|---|---|
| Authority/gate decisions and attributed receipts | gate/arbiter and chain code/test pointers | running request-context-decision trace with exact policy/config | SOURCE POINTER ONLY |
| `NON_BYPASSABILITY(B,E)` | A1 bypass catalog acknowledges same-UID paths | complete effect-specific path inventory, negative attempts, independently enforced isolation (if B) | NOT DEMONSTRATED |
| `INTEGRITY_DEF(B)` | signed release artifacts are available | effective running policy/config + binary binding | INSUFFICIENT EVIDENCE |
| `INTEGRITY_STATE(B,E)` | witnessed chain design | authoritative runtime state used in exact decision, integrity/freshness verification | INSUFFICIENT EVIDENCE |
| `INTEGRITY_CTX(C,B,E)` | gate input mechanisms | prove observed context bound to the deciding instance and effect | INSUFFICIENT EVIDENCE |
| `EXCLUSIVITY(A,E,I)` | no deployment proof collected | competing principals/authorities and overlapping commit intervals | INSUFFICIENT EVIDENCE |
| Decision → attempt → commit → observed E (including P3) | issue #1471 explicitly tracks truthful-outcome gaps | actual correlated raw trace, revocation race, effect observer | INSUFFICIENT EVIDENCE |
| Failure/unavailable/unknown semantics | catalog has historical redirect/timeout tests | current build/runtime trials; refusal vs unavailable vs unknown | INSUFFICIENT EVIDENCE |
| Independent chain export/verification | [#1449](https://github.com/dp-web4/hestia/issues/1449) open | standalone offline export/verifier; release attestations are not act/effect proofs | OPEN DEPENDENCY |

Track EABC's exact P1–P10 entries individually in a follow-on matrix only after reading and freezing their normative text and clarifying applicability to the chosen boundary. `DECLARED`, `REPORTED`, `DEMONSTRATED`, `INSUFFICIENT EVIDENCE` are **evidence states**, not conformance verdicts.

## 7. Issues / status and handoff exit criteria

- [#1471](https://github.com/dp-web4/hestia/issues/1471): **open**, truthful outcome witnessing / recoverability; source-level risk, not proof of a live failure.
- [#1449](https://github.com/dp-web4/hestia/issues/1449): **open**, export + offline verification, not a v0.3.0 blocker but relevant for external audit.
- [#491](https://github.com/dp-web4/hestia/issues/491), [#756](https://github.com/dp-web4/hestia/issues/756): **closed** historical approval-finality findings; useful regression scenarios, not presently asserted unresolved.
- [#1541](https://github.com/dp-web4/hestia/issues/1541) holds the assessment; [OMWEI #25](https://github.com/omwei-org/omwei-eabc/issues/25) holds external coordination.

**Ready to invite review of scope/docs now. Ready for independent reproducible trial only once:** (a) environment, manifests and E are frozen, (b) effect-level path census and explicit exclusions are reviewed, (c) commands/reset and raw sample traces are attached, and (d) verifier instructions and uncertainty reporting are present. No production gate changes, no broad EABC compliance claim, and no interruption to Kimi's backlog work are authorized by this document.
