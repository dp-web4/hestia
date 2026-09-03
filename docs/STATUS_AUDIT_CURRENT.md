# Hestia current readiness audit

**As of:** 2026-09-01  
**Source baseline:** `505b300af447a2d2ba407d376a6213b7512a64c2`  
**Authority:** `docs/readiness_status.json` (this file is generated)  
**Evidence rule:** source, merged, installed, restarted, live, observed, and publicly released are different claims. The rung says how far evidence reached; the assessment says whether that evidence satisfies the requirement. A high rung can therefore carry a failed assessment.

> This is a current coordination map, not a replacement for the linked issue records. An active PR is a candidate change, never implementation evidence. UNKNOWN is preserved where no durable measurement was found.

## Executive state

- Public daemon: v0.0.4 (2026-08-11; macOS arm64 and Linux arm64/x86_64 CLI archives with SHA-256 sidecars).
- Public app: app-v0.1.2 (2026-06-13; Android universal APK only).
- The source product is broad and actively used, but it does not yet meet the public-release bar: onboarding is unproven, the public app/daemon set is unmatched, gate execution is not one attested authority, and live governance evidence contains known unrecorded and unrecoverable decisions.

| PRD row | capability | assessment | highest evidence rung | blockers |
|---|---|---:|---|---:|
| 5.1 | Install and onboard | **FAILED** | publicly released | 6 |
| 5.2 | Find and connect hubs | **PARTIAL** | source | 2 |
| 5.3 | Manage local orchestrators | **PARTIAL** | source | 9 |
| 5.4 | Build a device constellation | **PARTIAL** | source | 1 |
| 5.5 | Vault | **PARTIAL** | source | 2 |
| 5.6 | Governance and conscience | **FAILED** | observed | 21 |
| 5.7 | Session coordination | **PARTIAL** | observed | 7 |
| 5.8 | Trust and identity | **PARTIAL** | source | 3 |
| non-functional | Non-functional requirements | **FAILED** | observed | 7 |
| public-release | Public release and distribution | **FAILED** | publicly released | 13 |
| demo-target | Public hub demo target | **UNKNOWN** | source | 3 |

## Capability evidence

### 5.1 - Install and onboard

**Assessment:** FAILED  
**Highest evidence rung:** publicly released - A daemon CLI is public, but no current public artifact has passed the PRD's nontechnical cold-run acceptance path.  
**Gap types:** product functionality, deployment truth, UX, evidence-only  
**Blocking issues:** [#315](https://github.com/dp-web4/hestia/issues/315), [#327](https://github.com/dp-web4/hestia/issues/327), [#342](https://github.com/dp-web4/hestia/issues/342), [#494](https://github.com/dp-web4/hestia/issues/494), [#520](https://github.com/dp-web4/hestia/issues/520), [#716](https://github.com/dp-web4/hestia/issues/716)  
**Related open evidence/issues:** none  
**Active candidate PRs:** [#636](https://github.com/dp-web4/hestia/pull/636)

Evidence:

- **release:** [https://github.com/dp-web4/hestia/releases/tag/v0.0.4](https://github.com/dp-web4/hestia/releases/tag/v0.0.4) - The current public daemon release provides three Unix CLI archives and checksums; it provides no Windows artifact or desktop app.
- **source:** `core/src/cli.rs` - The init surface exists and has an AI-owned identity mode, while its user-facing contract still describes initialization as an empty vault rather than a guided owner onboarding.
- **historical run:** `docs/PRD.md#9-success-criteria` - Criterion 1a contains a cold release run against v0.0.3 that stopped because join/add-device were absent; it has not been rerun against v0.0.4.

UNKNOWN / not demonstrated:

- Whether an uncontaminated nontechnical user can install v0.0.4 and complete onboarding without builder help.
- Whether a current-source desktop bundle can be produced and installed on each promised platform.

### 5.2 - Find and connect hubs

**Assessment:** PARTIAL  
**Highest evidence rung:** source - Connect, join, pair, notification, and sealed-secret paths exist in source; the current public newcomer path has no end-to-end receipt.  
**Gap types:** product functionality, security/governance correctness, UX, evidence-only  
**Blocking issues:** [#351](https://github.com/dp-web4/hestia/issues/351), [#563](https://github.com/dp-web4/hestia/issues/563)  
**Related open evidence/issues:** none  
**Active candidate PRs:** [#572](https://github.com/dp-web4/hestia/pull/572)

Evidence:

- **source:** `core/src/hub.rs` - Hub discovery, connection state, join, pairing, notifications, and sealed peer-message mechanics are implemented and unit tested in the core.
- **CLI contract:** `core/src/cli.rs` - The CLI exposes hub connect/join, member-key selection, pairing, notification, and secret-send/receive operations.

UNKNOWN / not demonstrated:

- No preserved clean-device receipt demonstrates discovery through join and first useful interaction against the intended public hub.
- No current artifact-to-hub compatibility run is recorded.

### 5.3 - Manage local orchestrators

**Assessment:** PARTIAL  
**Highest evidence rung:** source - Four adapters are present and source-tested, but the reviewed train still leaves 52.3% of gate law per-seat and does not prove resident execution parity.  
**Gap types:** security/governance correctness, deployment truth, evidence-only  
**Blocking issues:** [#225](https://github.com/dp-web4/hestia/issues/225), [#481](https://github.com/dp-web4/hestia/issues/481), [#586](https://github.com/dp-web4/hestia/issues/586), [#632](https://github.com/dp-web4/hestia/issues/632), [#647](https://github.com/dp-web4/hestia/issues/647), [#670](https://github.com/dp-web4/hestia/issues/670), [#695](https://github.com/dp-web4/hestia/issues/695), [#716](https://github.com/dp-web4/hestia/issues/716), [#741](https://github.com/dp-web4/hestia/issues/741)  
**Related open evidence/issues:** none  
**Active candidate PRs:** [#626](https://github.com/dp-web4/hestia/pull/626), [#733](https://github.com/dp-web4/hestia/pull/733)

Evidence:

- **ratchet:** `tools/gate_collapse_meter.py` - At this baseline the meter reports 2,471 per-seat law-bearing SLOC plus 2,250 shared, 52.3% still per-seat, four divergent Gemini forks, and only 3 of 10 extraction keys common to every seat.
- **test:** `tools/installed_engine_loader_test.py` - The Codex adapter is pinned to the installed shared engine and fails closed when that authority is absent.
- **deployment boundary:** `docs/PRD_HARNESS_AGNOSTIC_ADAPTERS.md` - The accepted architecture is zero adapter-local law and external verification of the actual resident hook closure; current adapters have not reached that acceptance state.

UNKNOWN / not demonstrated:

- Whether every registered harness currently executes the source-reviewed adapter and shared-engine bytes.
- Whether each harness blocks within its real timeout budget under daemon failure and load.

### 5.4 - Build a device constellation

**Assessment:** PARTIAL  
**Highest evidence rung:** source - The source contains local and remote-device enrollment, revocation, challenge, co-sign, and presentation flows; a real second-device run is not recorded.  
**Gap types:** product functionality, UX, evidence-only  
**Blocking issues:** [#351](https://github.com/dp-web4/hestia/issues/351)  
**Related open evidence/issues:** [#563](https://github.com/dp-web4/hestia/issues/563)  
**Active candidate PRs:** [#572](https://github.com/dp-web4/hestia/pull/572)

Evidence:

- **source and tests:** `core/src/constellation.rs` - Constellation state, proofs, enrolled-device verification, revocation, challenge freshness, and assurance derivation are implemented with unit coverage.
- **CLI contract:** `core/src/cli.rs` - The CLI exposes add-remote, enroll, revoke, present, owner consent, and remote co-sign service operations.

UNKNOWN / not demonstrated:

- No durable two-device run proves pairing, consent, remote co-sign, assurance resolution, and revocation across restart.
- No nontechnical app flow for device pairing has been demonstrated.

### 5.5 - Vault

**Assessment:** PARTIAL  
**Highest evidence rung:** source - New-entry containment and witnessed reads exist in source; issuance-bound release/presentation projections and safe process-secret handling remain open.  
**Gap types:** product functionality, security/governance correctness, deployment truth, evidence-only  
**Blocking issues:** [#356](https://github.com/dp-web4/hestia/issues/356), [#581](https://github.com/dp-web4/hestia/issues/581)  
**Related open evidence/issues:** none  
**Active candidate PRs:** none

Evidence:

- **source:** `core/src/vault/entry.rs` - Vault entries carry consumer containment and exposure state.
- **source:** `core/src/vault/rules.rs` - Rule types exist, but the PRD's recipient-dependent released-view projection is not yet the complete enforced model.
- **boundary tests:** `app/src-tauri/tests/identity_vault_guard.rs` - The app test surface pins identity/vault boundary behavior at source level.

UNKNOWN / not demonstrated:

- No full replay suite demonstrates release, presentation, and custody against transport-authenticated recipient identity.
- Legacy-entry migration and both-axis backfill have no completed artifact.

### 5.6 - Governance and conscience

**Assessment:** FAILED  
**Highest evidence rung:** observed - Consequential paths are governed and heavily witnessed, but live evidence records missing denials, portable or prematurely spent approvals, parser bypasses, and unreachable remedies.  
**Gap types:** security/governance correctness, deployment truth, UX, evidence-only  
**Blocking issues:** [#225](https://github.com/dp-web4/hestia/issues/225), [#389](https://github.com/dp-web4/hestia/issues/389), [#393](https://github.com/dp-web4/hestia/issues/393), [#481](https://github.com/dp-web4/hestia/issues/481), [#491](https://github.com/dp-web4/hestia/issues/491), [#529](https://github.com/dp-web4/hestia/issues/529), [#539](https://github.com/dp-web4/hestia/issues/539), [#595](https://github.com/dp-web4/hestia/issues/595), [#600](https://github.com/dp-web4/hestia/issues/600), [#601](https://github.com/dp-web4/hestia/issues/601), [#628](https://github.com/dp-web4/hestia/issues/628), [#631](https://github.com/dp-web4/hestia/issues/631), [#669](https://github.com/dp-web4/hestia/issues/669), [#670](https://github.com/dp-web4/hestia/issues/670), [#680](https://github.com/dp-web4/hestia/issues/680), [#685](https://github.com/dp-web4/hestia/issues/685), [#686](https://github.com/dp-web4/hestia/issues/686), [#695](https://github.com/dp-web4/hestia/issues/695), [#714](https://github.com/dp-web4/hestia/issues/714), [#741](https://github.com/dp-web4/hestia/issues/741), [#756](https://github.com/dp-web4/hestia/issues/756)  
**Related open evidence/issues:** [#242](https://github.com/dp-web4/hestia/issues/242), [#260](https://github.com/dp-web4/hestia/issues/260), [#261](https://github.com/dp-web4/hestia/issues/261), [#264](https://github.com/dp-web4/hestia/issues/264), [#301](https://github.com/dp-web4/hestia/issues/301), [#434](https://github.com/dp-web4/hestia/issues/434), [#509](https://github.com/dp-web4/hestia/issues/509), [#533](https://github.com/dp-web4/hestia/issues/533), [#537](https://github.com/dp-web4/hestia/issues/537), [#610](https://github.com/dp-web4/hestia/issues/610), [#616](https://github.com/dp-web4/hestia/issues/616), [#617](https://github.com/dp-web4/hestia/issues/617), [#622](https://github.com/dp-web4/hestia/issues/622), [#625](https://github.com/dp-web4/hestia/issues/625), [#639](https://github.com/dp-web4/hestia/issues/639), [#655](https://github.com/dp-web4/hestia/issues/655), [#658](https://github.com/dp-web4/hestia/issues/658), [#660](https://github.com/dp-web4/hestia/issues/660), [#661](https://github.com/dp-web4/hestia/issues/661), [#674](https://github.com/dp-web4/hestia/issues/674), [#676](https://github.com/dp-web4/hestia/issues/676), [#687](https://github.com/dp-web4/hestia/issues/687)  
**Active candidate PRs:** [#599](https://github.com/dp-web4/hestia/pull/599), [#613](https://github.com/dp-web4/hestia/pull/613), [#626](https://github.com/dp-web4/hestia/pull/626), [#704](https://github.com/dp-web4/hestia/pull/704), [#733](https://github.com/dp-web4/hestia/pull/733), [#735](https://github.com/dp-web4/hestia/pull/735), [#736](https://github.com/dp-web4/hestia/pull/736), [#750](https://github.com/dp-web4/hestia/pull/750), [#753](https://github.com/dp-web4/hestia/pull/753)

Evidence:

- **source test:** `core/tests/appeal_floor_window.rs` - The source pins appeal-window behavior, but the issue record shows the full denial-to-appeal-to-effect loop is not closed.
- **differential:** `tools/gate_differential.py` - The shared closure corpus is explicitly indeterminate with an undrivable seat and contains seven agreed-but-wrong or partial cases.
- **observed failures:** [https://github.com/dp-web4/hestia/issues/393](https://github.com/dp-web4/hestia/issues/393) - The live issue corpus demonstrates both false refusals that manufacture route-arounds and interpreter/indirection writes the text classifier misses.

UNKNOWN / not demonstrated:

- There is no current fleet-wide acceptance matrix proving one canonical act, one attributed appellant, one terminal appeal state, and verbatim re-evaluation.
- The false-negative rate remains unknowable where first-stage denials do not produce chain rows.

### 5.7 - Session coordination

**Assessment:** PARTIAL  
**Highest evidence rung:** observed - Session visibility and mesh delivery operate in the fleet, while work claiming, lifecycle cleanup, and reliable disposition delivery remain incomplete or contradicted by observations.  
**Gap types:** product functionality, security/governance correctness, deployment truth, UX, evidence-only  
**Blocking issues:** [#320](https://github.com/dp-web4/hestia/issues/320), [#361](https://github.com/dp-web4/hestia/issues/361), [#366](https://github.com/dp-web4/hestia/issues/366), [#523](https://github.com/dp-web4/hestia/issues/523), [#601](https://github.com/dp-web4/hestia/issues/601), [#603](https://github.com/dp-web4/hestia/issues/603), [#685](https://github.com/dp-web4/hestia/issues/685)  
**Related open evidence/issues:** [#434](https://github.com/dp-web4/hestia/issues/434), [#510](https://github.com/dp-web4/hestia/issues/510), [#513](https://github.com/dp-web4/hestia/issues/513), [#519](https://github.com/dp-web4/hestia/issues/519), [#536](https://github.com/dp-web4/hestia/issues/536), [#551](https://github.com/dp-web4/hestia/issues/551), [#645](https://github.com/dp-web4/hestia/issues/645), [#668](https://github.com/dp-web4/hestia/issues/668), [#707](https://github.com/dp-web4/hestia/issues/707), [#732](https://github.com/dp-web4/hestia/issues/732)  
**Active candidate PRs:** [#649](https://github.com/dp-web4/hestia/pull/649), [#735](https://github.com/dp-web4/hestia/pull/735), [#736](https://github.com/dp-web4/hestia/pull/736), [#748](https://github.com/dp-web4/hestia/pull/748), [#750](https://github.com/dp-web4/hestia/pull/750), [#755](https://github.com/dp-web4/hestia/pull/755)

Evidence:

- **source and tests:** `core/src/server/handler.rs` - Session own/siblings resources exist with bearer redaction and attribution tests.
- **observed delivery:** [https://github.com/dp-web4/hestia/issues/523](https://github.com/dp-web4/hestia/issues/523) - Mesh sends can commit before the client timeout and then be retried as duplicates.
- **observed lifecycle:** [https://github.com/dp-web4/hestia/issues/320](https://github.com/dp-web4/hestia/issues/320) - Session insertion has no corresponding remover, so reconnect churn accumulates state.

UNKNOWN / not demonstrated:

- No end-to-end work-claim and shared-worktree contract is accepted across all seats.
- No current delivery SLO proves that a routed request reaches a capable reader before its decision window closes.

### 5.8 - Trust and identity

**Assessment:** PARTIAL  
**Highest evidence rung:** source - LCT, witness, role, profile, and trust stores exist, but signed witness coordinates and subject-indexed trust derivation remain open.  
**Gap types:** product functionality, security/governance correctness, evidence-only  
**Blocking issues:** [#339](https://github.com/dp-web4/hestia/issues/339), [#578](https://github.com/dp-web4/hestia/issues/578), [#580](https://github.com/dp-web4/hestia/issues/580)  
**Related open evidence/issues:** [#328](https://github.com/dp-web4/hestia/issues/328), [#689](https://github.com/dp-web4/hestia/issues/689)  
**Active candidate PRs:** [#572](https://github.com/dp-web4/hestia/pull/572)

Evidence:

- **source:** `core/src/witness.rs` - Witness records and chain operations are implemented.
- **source:** `core/src/storage/trust.rs` - Trust state is durable, but current derivation lacks an indexed per-member evidence read.
- **source:** `core/src/lct_publish.rs` - LCT publication mechanics exist; complete public interoperability and signed-chain hardening are not demonstrated.

UNKNOWN / not demonstrated:

- No cross-implementation public verification transcript covers the current identity, witness, role, and reputation chain.
- No accepted derivation proves that each trust score is computed from complete subject-specific evidence.

### non-functional - Non-functional requirements

**Assessment:** FAILED  
**Highest evidence rung:** observed - The system runs continuously, but measured memory growth, cold-connect latency, bounded-history gaps, and adapter timeout behavior miss robustness and latency requirements.  
**Gap types:** product functionality, deployment truth, evidence-only  
**Blocking issues:** [#225](https://github.com/dp-web4/hestia/issues/225), [#342](https://github.com/dp-web4/hestia/issues/342), [#354](https://github.com/dp-web4/hestia/issues/354), [#423](https://github.com/dp-web4/hestia/issues/423), [#592](https://github.com/dp-web4/hestia/issues/592), [#647](https://github.com/dp-web4/hestia/issues/647), [#691](https://github.com/dp-web4/hestia/issues/691)  
**Related open evidence/issues:** [#304](https://github.com/dp-web4/hestia/issues/304), [#434](https://github.com/dp-web4/hestia/issues/434), [#488](https://github.com/dp-web4/hestia/issues/488), [#497](https://github.com/dp-web4/hestia/issues/497), [#629](https://github.com/dp-web4/hestia/issues/629)  
**Active candidate PRs:** [#634](https://github.com/dp-web4/hestia/pull/634), [#692](https://github.com/dp-web4/hestia/pull/692)

Evidence:

- **observed performance:** [https://github.com/dp-web4/hestia/issues/354](https://github.com/dp-web4/hestia/issues/354) - Resident memory growth was observed to drive swap pressure and gate timeouts.
- **observed latency:** [https://github.com/dp-web4/hestia/issues/423](https://github.com/dp-web4/hestia/issues/423) - Cold first-connect latency was measured at 5.7 seconds on the cited build.
- **source constraint:** [https://github.com/dp-web4/hestia/issues/488](https://github.com/dp-web4/hestia/issues/488) - Routine chain cognition still needs indexed time floors, capped cursors, and explicit deep reads.

UNKNOWN / not demonstrated:

- No current release report records binary size, steady-state RSS, cold/warm latency, and multi-day durability on each promised class of device.
- No full live app/daemon contract run is part of CI.

### public-release - Public release and distribution

**Assessment:** FAILED  
**Highest evidence rung:** publicly released - Public daemon and Android artifacts exist, but they are not a current, matched, cross-platform product set and lack the PRD's newcomer evidence.  
**Gap types:** product functionality, deployment truth, UX, evidence-only  
**Blocking issues:** [#315](https://github.com/dp-web4/hestia/issues/315), [#327](https://github.com/dp-web4/hestia/issues/327), [#342](https://github.com/dp-web4/hestia/issues/342), [#438](https://github.com/dp-web4/hestia/issues/438), [#481](https://github.com/dp-web4/hestia/issues/481), [#494](https://github.com/dp-web4/hestia/issues/494), [#520](https://github.com/dp-web4/hestia/issues/520), [#606](https://github.com/dp-web4/hestia/issues/606), [#607](https://github.com/dp-web4/hestia/issues/607), [#632](https://github.com/dp-web4/hestia/issues/632), [#654](https://github.com/dp-web4/hestia/issues/654), [#691](https://github.com/dp-web4/hestia/issues/691), [#716](https://github.com/dp-web4/hestia/issues/716)  
**Related open evidence/issues:** none  
**Active candidate PRs:** [#607](https://github.com/dp-web4/hestia/pull/607), [#634](https://github.com/dp-web4/hestia/pull/634), [#636](https://github.com/dp-web4/hestia/pull/636)

Evidence:

- **release:** [https://github.com/dp-web4/hestia/releases/tag/v0.0.4](https://github.com/dp-web4/hestia/releases/tag/v0.0.4) - v0.0.4 is public with macOS arm64 and Linux arm64/x86_64 CLI archives plus checksums.
- **release:** [https://github.com/dp-web4/hestia/releases/tag/app-v0.1.2](https://github.com/dp-web4/hestia/releases/tag/app-v0.1.2) - The newest public app is an older Android-only APK.
- **source boundary:** `tools/public_boundary_test.py` - The repository pins its public/private source boundary, but that is not an artifact compatibility or installation test.

UNKNOWN / not demonstrated:

- No signed, version-matched desktop app and daemon set is public.
- No clean-machine public install and hub-join transcript exists for the current release set.

### demo-target - Public hub demo target

**Assessment:** UNKNOWN  
**Highest evidence rung:** source - Hestia contains the client-side source needed for the intended hub flow; no current continuous public rehearsal receipt is stored here.  
**Gap types:** product functionality, deployment truth, UX, evidence-only  
**Blocking issues:** [#351](https://github.com/dp-web4/hestia/issues/351), [#494](https://github.com/dp-web4/hestia/issues/494), [#716](https://github.com/dp-web4/hestia/issues/716)  
**Related open evidence/issues:** [#563](https://github.com/dp-web4/hestia/issues/563)  
**Active candidate PRs:** [#572](https://github.com/dp-web4/hestia/pull/572)

Evidence:

- **source:** `core/src/hub.rs` - The Hestia side can discover, join, pair, notify, exchange sealed payloads, and participate in constellation flows.
- **historical audit:** `docs/STATUS_AUDIT_2026-08-08.md#demo-target-reconciliation` - The prior audit defined the missing six-step public rehearsal; no newer durable receipt supersedes it in this repository.

UNKNOWN / not demonstrated:

- Whether the intended public hub is running a client-compatible build now.
- Whether a new user can acquire Hestia, join, advertise presence, interact, and verify the resulting evidence in one uninterrupted run.

## Mechanical coordination index

The JSON ledger is the editable source for this section. Its drift test requires every normative capability row, validates the evidence vocabulary, and regenerates these links.

- Distinct blocking issues referenced: 50 - [#225](https://github.com/dp-web4/hestia/issues/225), [#315](https://github.com/dp-web4/hestia/issues/315), [#320](https://github.com/dp-web4/hestia/issues/320), [#327](https://github.com/dp-web4/hestia/issues/327), [#339](https://github.com/dp-web4/hestia/issues/339), [#342](https://github.com/dp-web4/hestia/issues/342), [#351](https://github.com/dp-web4/hestia/issues/351), [#354](https://github.com/dp-web4/hestia/issues/354), [#356](https://github.com/dp-web4/hestia/issues/356), [#361](https://github.com/dp-web4/hestia/issues/361), [#366](https://github.com/dp-web4/hestia/issues/366), [#389](https://github.com/dp-web4/hestia/issues/389), [#393](https://github.com/dp-web4/hestia/issues/393), [#423](https://github.com/dp-web4/hestia/issues/423), [#438](https://github.com/dp-web4/hestia/issues/438), [#481](https://github.com/dp-web4/hestia/issues/481), [#491](https://github.com/dp-web4/hestia/issues/491), [#494](https://github.com/dp-web4/hestia/issues/494), [#520](https://github.com/dp-web4/hestia/issues/520), [#523](https://github.com/dp-web4/hestia/issues/523), [#529](https://github.com/dp-web4/hestia/issues/529), [#539](https://github.com/dp-web4/hestia/issues/539), [#563](https://github.com/dp-web4/hestia/issues/563), [#578](https://github.com/dp-web4/hestia/issues/578), [#580](https://github.com/dp-web4/hestia/issues/580), [#581](https://github.com/dp-web4/hestia/issues/581), [#586](https://github.com/dp-web4/hestia/issues/586), [#592](https://github.com/dp-web4/hestia/issues/592), [#595](https://github.com/dp-web4/hestia/issues/595), [#600](https://github.com/dp-web4/hestia/issues/600), [#601](https://github.com/dp-web4/hestia/issues/601), [#603](https://github.com/dp-web4/hestia/issues/603), [#606](https://github.com/dp-web4/hestia/issues/606), [#607](https://github.com/dp-web4/hestia/issues/607), [#628](https://github.com/dp-web4/hestia/issues/628), [#631](https://github.com/dp-web4/hestia/issues/631), [#632](https://github.com/dp-web4/hestia/issues/632), [#647](https://github.com/dp-web4/hestia/issues/647), [#654](https://github.com/dp-web4/hestia/issues/654), [#669](https://github.com/dp-web4/hestia/issues/669), [#670](https://github.com/dp-web4/hestia/issues/670), [#680](https://github.com/dp-web4/hestia/issues/680), [#685](https://github.com/dp-web4/hestia/issues/685), [#686](https://github.com/dp-web4/hestia/issues/686), [#691](https://github.com/dp-web4/hestia/issues/691), [#695](https://github.com/dp-web4/hestia/issues/695), [#714](https://github.com/dp-web4/hestia/issues/714), [#716](https://github.com/dp-web4/hestia/issues/716), [#741](https://github.com/dp-web4/hestia/issues/741), [#756](https://github.com/dp-web4/hestia/issues/756).
- Additional related open issues referenced: 37 - [#242](https://github.com/dp-web4/hestia/issues/242), [#260](https://github.com/dp-web4/hestia/issues/260), [#261](https://github.com/dp-web4/hestia/issues/261), [#264](https://github.com/dp-web4/hestia/issues/264), [#301](https://github.com/dp-web4/hestia/issues/301), [#304](https://github.com/dp-web4/hestia/issues/304), [#328](https://github.com/dp-web4/hestia/issues/328), [#434](https://github.com/dp-web4/hestia/issues/434), [#488](https://github.com/dp-web4/hestia/issues/488), [#497](https://github.com/dp-web4/hestia/issues/497), [#509](https://github.com/dp-web4/hestia/issues/509), [#510](https://github.com/dp-web4/hestia/issues/510), [#513](https://github.com/dp-web4/hestia/issues/513), [#519](https://github.com/dp-web4/hestia/issues/519), [#533](https://github.com/dp-web4/hestia/issues/533), [#536](https://github.com/dp-web4/hestia/issues/536), [#537](https://github.com/dp-web4/hestia/issues/537), [#551](https://github.com/dp-web4/hestia/issues/551), [#610](https://github.com/dp-web4/hestia/issues/610), [#616](https://github.com/dp-web4/hestia/issues/616), [#617](https://github.com/dp-web4/hestia/issues/617), [#622](https://github.com/dp-web4/hestia/issues/622), [#625](https://github.com/dp-web4/hestia/issues/625), [#629](https://github.com/dp-web4/hestia/issues/629), [#639](https://github.com/dp-web4/hestia/issues/639), [#645](https://github.com/dp-web4/hestia/issues/645), [#655](https://github.com/dp-web4/hestia/issues/655), [#658](https://github.com/dp-web4/hestia/issues/658), [#660](https://github.com/dp-web4/hestia/issues/660), [#661](https://github.com/dp-web4/hestia/issues/661), [#668](https://github.com/dp-web4/hestia/issues/668), [#674](https://github.com/dp-web4/hestia/issues/674), [#676](https://github.com/dp-web4/hestia/issues/676), [#687](https://github.com/dp-web4/hestia/issues/687), [#689](https://github.com/dp-web4/hestia/issues/689), [#707](https://github.com/dp-web4/hestia/issues/707), [#732](https://github.com/dp-web4/hestia/issues/732).
- Distinct active candidate PRs referenced: 17 - [#572](https://github.com/dp-web4/hestia/pull/572), [#599](https://github.com/dp-web4/hestia/pull/599), [#607](https://github.com/dp-web4/hestia/pull/607), [#613](https://github.com/dp-web4/hestia/pull/613), [#626](https://github.com/dp-web4/hestia/pull/626), [#634](https://github.com/dp-web4/hestia/pull/634), [#636](https://github.com/dp-web4/hestia/pull/636), [#649](https://github.com/dp-web4/hestia/pull/649), [#692](https://github.com/dp-web4/hestia/pull/692), [#704](https://github.com/dp-web4/hestia/pull/704), [#733](https://github.com/dp-web4/hestia/pull/733), [#735](https://github.com/dp-web4/hestia/pull/735), [#736](https://github.com/dp-web4/hestia/pull/736), [#748](https://github.com/dp-web4/hestia/pull/748), [#750](https://github.com/dp-web4/hestia/pull/750), [#753](https://github.com/dp-web4/hestia/pull/753), [#755](https://github.com/dp-web4/hestia/pull/755).
- Scope warning: this is the PRD-readiness subset, not the complete research backlog or open-PR queue. GitHub remains authoritative for open/closed state.

## Update procedure

1. Fetch `origin/main` and record its exact full SHA in `docs/readiness_status.json`.
2. Re-run or cite the exact evidence for every row whose source, deployment, or issue state moved.
3. Update issue and PR numbers in the JSON ledger; do not close an evidence issue merely because it is indexed here.
4. Run `python3 tools/readiness_status.py --write` and `python3 tools/readiness_status_test.py`.
5. Publish the changed matrix through review, then update the release-readiness issue with the new baseline and review link.
