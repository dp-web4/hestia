# Hestia Current-State Audit

**Audit date:** 2026-08-04 21:44 PDT  
**Repository:** `dp-web4/Hestia`  
**Audited main:** `3708bc86df035f1ec558a168b3bd4ba26c39fa5c`  
**Scope:** merged work since the prior GPT open-PR audit, current source state, CI, deployment/runtime boundaries, unresolved governance risks, and open questions.

---

## Executive assessment

The repository is materially stronger than it was during the prior audit. The response to review was substantive rather than cosmetic:

- symbolic checks were replaced with executable behavioral probes;
- unsafe stale-policy assumptions were explicitly retracted;
- the remote constellation path exposed and repaired two stacked identity failures;
- executable parity was separated from deployment-specific private authority;
- null-state greens were repeatedly challenged with mutation and negative controls;
- several PRs corrected their own earlier claims in the permanent record.

The open PR queue is empty at this cutoff. The latest merge on `main` is #188. Its PR-head CI was green. The push run on current `main` was still in progress at audit cutoff: Python hook and plugin jobs had passed, while `cargo test` remained active.

The dominant unresolved risk is no longer ordinary code quality. It is the separation between:

> reviewed source, packaged artifact, installed copy, running process, authority state, and externally mutated repository.

Hestia increasingly recognizes these as distinct surfaces, but it still lacks one fleet-level artifact proving what is actually running, under which authority, on each machine.

### Current risk summary

| Area | Assessment |
|---|---|
| Source quality and review depth | **Strong and improving** |
| Current `main` internal coherence | **Generally good; final push CI pending at cutoff** |
| Consolidated gate architecture | **Promising, not ready to wire** |
| Runtime and deployment certainty | **Weak** |
| Member identity and role authority | **Critical unresolved gap** |
| Mechanical governance enforcement | **Weak; partly social** |
| Appeal and escalation completeness | **Incomplete** |
| Constellation remote workflow | **Meaningful progress, insufficient live proof** |

---

# Work landed since the prior audit

## #185 — escalation payload legibility

The source-level repair is now credible:

- attempted summaries are bounded;
- credential-shaped material is redacted;
- the exact `reason` and `detail` wire keys are asserted;
- bare execution and pytest no longer disagree silently;
- the accountability block was added.

The PR itself records the remaining operational boundary: the enforcing Claude gate is a separately deployed copy. Merging repository source does not change the operator-visible result until that installed copy is updated.

### Assessment

**Source fixed; runtime deployment unverified.**

### Residual concerns

- Redaction still risks overmatching harmless vocabulary such as `tokenize`.
- Mention-based classification can make the test or its documentation trigger self-protection.
- A live post-deployment escalation should be captured as the acceptance artifact, proving the operator receives the attempted act and useful context.

---

## #187 — previous-wake final output

The prior blocking findings were addressed correctly:

- `O_NOFOLLOW | O_NONBLOCK`;
- `fstat()` on the opened descriptor, avoiding a check-then-open race;
- regular-file and same-UID checks;
- bounded 256 KiB tail read rather than whole-file loading;
- an external five-second timeout around every caller;
- correction of the boolean-precedence test;
- fire-template discovery widened to include hyphenated names;
- explicit data-not-instructions framing around the prior output.

The not-same review independently checked the implementation rather than accepting the commit narrative.

### Assessment

**Good implementation with bounded and honestly described residual risk.**

### Residual concerns

- The suite proves the FIFO behavior but does not isolate the `S_ISREG` guard; removing that guard was not caught by the negative control.
- The UID ownership guard is present but not independently exercised by a test.
- Verbatim previous-model output remains a persistent prompt-injection channel. The envelope is intent-signaling, not a security boundary.
- A structured cross-harness final-report artifact remains deferred.

---

## #175 — shared gate self-protection

The important correction eventually landed: the tests now invoke actual `_touches_self()` behavior instead of treating membership in a protected-name tuple as proof that the rule fires.

The design moved toward default-strong matching with a constrained hooks-directory-only exception set. The exemption ledger was itself added to the protected surface. The file also now behaves consistently under bare execution and pytest.

### Assessment

**The direct canonical-core bypass was repaired, but protection remains adapter-local and noisy.**

### Remaining limitations

1. **Claude-only enforcement.** Kimi, Codex, Gemini, and Cursor still do not have equivalent self-protection. A member running through another harness can modify the shared core while the Claude-specific test remains green.
2. **Mention rather than resolution.** The classifier still reasons over textual appearances in command payloads. Measured false denies included read-only `grep`, `ls`, diagnostic commands, MCP message content, and the issue report describing the classifier itself.
3. **Operational load sensitivity.** A not-same review observed intermittent fail-closed verdict RPC timeouts under ordinary load. The fail-closed posture is correct, but the member sees a busy daemon and a policy denial through nearly the same operational shape.
4. **Attention degradation.** False escalations pollute the operator queue and reputation evidence. A protection mechanism that repeatedly cries wolf trains the operator to approve without discrimination.

---

## #188 — common gate per-agent policy layer

This is the most important architectural work and the clearest remaining activation blocker.

The branch explicitly corrected the prior false premise that a stale replica must be narrower. Revocation makes stale policy potentially wider than current authority. The new model therefore adds:

- monotonic policy generation;
- policy expiry;
- refusal of replicas without certification metadata;
- refusal of stale wildcard/unscoped grants;
- fail-closed parsing of malformed authority payloads;
- rejection of unknown prefixes that could incidentally grant a workspace child.

That is real progress, and the code now states its limits more honestly.

### Critical unresolved fact

The local replica is still not cryptographically authenticated. A member-writable file can forge a generation and expiry as easily as it can forge scope. The source itself states that a MAC or signature issued by the authority is still required.

The common core also remains deliberately **NOT WIRED**. No production harness imports it and no adapter shim activates it.

### Wiring blockers recorded in the PR

- `evaluate(policy=None)` does not automatically consult the vault.
- Existing live identity files do not carry certified policy replicas.
- Switching shims before authority material is distributed would narrow members to launch-directory reach and could brick the fleet in the fail-closed direction.
- No authority component currently issues or logs policy generations.
- The legacy `load_in_scope()` fallback still grants a guessed scope on failure and should be deleted before migration.

### Assessment

**Correct direction, honest implementation, not ready for fleet activation.**

---

## #191 — remote constellation co-signing

This work found more than the original feature gap.

The remote path had two stacked identity failures:

1. it signed using a key the hub did not pin for the member;
2. it addressed the request under the wrong LCT, causing well-formed requests to be refused before the key failure was reached.

The branch corrected the signer source to the connected member identity and bound the returned key to the enrolled roster entry. The not-same review verified the actual on-disk and hub-pinned key relationship rather than relying on source claims.

### Assessment

**Strong diagnosis and repair; production confidence still below source-test confidence.**

### Remaining gaps

- The complete two-machine path had not completed an attended end-to-end round trip before merge.
- Owner-side operation opens the sealed vault, and unattended PolicyGate operation blocked the final live proof.
- Device-side consent needs an explicit lifecycle. The `serve-owner` relationship should be evaluated for expiry, roster-generation binding, challenge scope, or nonce binding.
- Member key-source rotation can invalidate existing roster pins. The new comparison detects this, but the operational repair path remains manual.

---

## #190 — dashboard witness-feed error display

The dashboard now distinguishes:

- a genuinely empty witness chain;
- a failed chain read.

The failure reason travels through serialization and is rendered ahead of any misleading “waiting for the first entry” message. The test asserts at the serialized browser payload, including that empty and unavailable states cannot be identical.

### Assessment

**The UI now tells the truth about failure. The storage failure itself remains unresolved.**

### Underlying engineering questions

- Why is the witness read performed under a broad state lock?
- Are access patterns appropriately indexed and paginated?
- Why is daemon RSS large relative to the witness store?
- What is the expected retention, compaction, and archival model?
- At what error rate should the operator be alerted?

---

## #151 — canonical, bundle, and deployment parity

The redesigned invariant is substantially better:

- executable gate behavior should match canonically;
- private deployment authority must not be copied into a public marketplace artifact;
- withheld scopes should be explicit rather than accidental;
- installed and generated behavior should carry provenance rather than relying on superficial equality.

This avoids the dangerous green path of publishing one operator’s private repository grants as a universal baseline.

### Remaining boundary

Prior measurement found three distinct trees:

1. canonical repository source;
2. marketplace bundle;
3. installed hooks.

One installed gate matched neither canonical nor bundle. An installed witness hook existed in a version present in neither source tree.

The merged comparator improves source-versus-bundle reasoning. It does not by itself prove installed or running parity.

### Assessment

**Correct source contract; deployment remains the missing third leg.**

---

## #157 — identity-field classification

The classification now reflects actual authority rather than field names.

**Core:**

- `mrh.in_scope`
- `role`

**Meta:**

- `entity` in the current implementation;
- substrate and lifecycle fields;
- descriptive boundaries and notes;
- policy-shaped prose fields not consumed by a decider;
- relationship, history, session, and T3 metadata.

The important conclusion is that `entity` is metadata today because no decider authenticates or consumes it. Making it core requires identity binding, not relabeling.

### Assessment

**Useful and honest governance contract. It exposes rather than resolves the identity-binding gap.**

---

## #159 replacement / #189 tracker

The original branch was closed as superseded, but its replacement is not on `main`.

The replacement exists in the inbox and requires an author-owned rebase before publication. Its accepted design separates observed presence for routing from durable registry presence, while exposing the size and quality of the pool.

The remaining acceptance condition is important: upstream eligibility must prove the identity quality of an observed member before that identifier is admitted to an independent arbiter pool.

### Assessment

**Accepted design, undelivered implementation.**

---

# Red flags

## P0 — caller identity and role are still asserted, not proven

At `hestia_connect`, the caller supplies both `plugin_id` and `role`.

Those values subsequently influence:

- attribution of acts;
- role-scoped policy selection;
- instance-scoped policy selection;
- reputation grain selection;
- member rendering and prompt admission decisions;
- durable member registration.

A new caller can invent a non-synthetic name, acquire durable presence, and select a published role. Changing either selector can shed a role or instance overlay.

This is more urgent after #188. A carefully designed per-agent policy is not safe if the subject selecting it is unproven.

### Required direction

Bind `plugin_id` and role to a cryptographic key or authority-issued connection credential. Policy selectors must be derived from the proven identity, not caller-supplied strings.

---

## P0 — runtime truth is still not established

Multiple merged changes explicitly require separate installation, restart, or attended operation before becoming true in the running system.

Examples:

- #185 changes a separately installed Claude gate;
- prior measurements found installed artifacts matching neither source nor marketplace bundle;
- long-running Bash watchers retain parsed code and cannot absorb file edits without restart;
- daemon source provenance and watcher source hashes now exist, but there is no consolidated fleet record.

### Missing artifact

A fleet deployment manifest should record, per host and member:

- running daemon build;
- installed hook digests;
- watcher startup digest;
- current on-disk digest;
- source checkout revision;
- drift state and reason;
- policy generation and authority signature status;
- last successful end-to-end behavioral smoke probe.

Current conclusion:

> `main` is auditable; the fleet is not yet auditable as one state.

---

## P0 — the common gate is unwired and its offline policy replica is unauthenticated

The common gate should not become authoritative until all of the following exist:

- authority-issued signed or MACed replica;
- verification key distribution;
- generation issuer;
- issuance and revocation log;
- defined expiry policy;
- authority material distributed before shim migration;
- online vault-reader wiring or equivalent authority lookup;
- deletion of legacy granting fallbacks;
- rollback and recovery procedure for a fleet-wide fail-closed migration.

Wiring before these steps risks either fleet-wide false denial or self-issued authority through forged local metadata.

---

## P0 — blocking not-same review remains a comment convention

The inbox publication model causes multiple agents’ work to appear under the same GitHub author. GitHub then refuses formal “request changes” reviews as self-review, so not-same verdicts frequently arrive as ordinary comments.

#173 records a PR merged five minutes and thirty-eight seconds after a changes-required comment. GitHub showed no blocking review and a green merge path.

Recent work still relies on comments stating “reviewed and merged by...” rather than a mechanical required status.

### Required direction

Use a machine-readable review ledger that branch protection can require, such as:

- a GitHub App status check;
- separate authenticated reviewer identities;
- a signed review artifact converted into a required commit status;
- a merge controller that refuses unresolved not-same findings.

---

## P0 — external connector mutations remain outside the gate and witness chain

Local hooks govern filesystem and CLI operations. A connector using the GitHub API can construct commits and update refs without touching the governed local process path.

That path currently provides:

- no local policy decision;
- no escalation;
- no witness record;
- no trust-chain entry.

Branch protection constrains some writes to `main`, but it does not provide act attribution, witness continuity, or governance of other refs.

This is not GitHub-specific. Any connector capable of mutating external state sits outside the current local gate boundary.

### Required direction

Enumerate every mutating connector and choose one explicit contract:

- prohibit mutation;
- allow read-only access;
- require a witnessed wrapper;
- or make connector-side mutations first-class governed acts with equivalent policy and chain evidence.

---

## P1 — four of five harnesses still lack equivalent escalation and appeal

Only the Claude adapter currently carries the full escalation path. Other adapters can deny operations without creating equivalent operator-visible governance traffic.

The dashboard can therefore make one member’s activity appear to represent the fleet.

This is blocked on common-core shim migration, which is itself blocked on authenticated per-agent policy and deployment sequencing.

---

## P1 — tool schemas still permit silent protocol drift

Hestia tools broadly accept arbitrary additional properties without declaring a meaningful property set.

A caller can send a misspelled or premature field, receive a successful response, and have the daemon ignore it silently. A sender-side change can therefore appear deployed while the sink remains unchanged.

### Minimum repair

- log unknown keys at the handler boundary;
- require every new argument to have a wire-to-sink behavioral test;
- merge receiver support before senders begin populating a field.

### Strong repair

Declare explicit schemas with appropriate `properties`, `required`, and `additionalProperties: false` after surveying current callers.

---

## P1 — appeal adjudication has no automatic return leg

Appeal filing wakes an arbiter. Arbitration does not automatically wake the appellant.

Once ruled, the appeal disappears from the open list. From the appellant’s view, absence can mean:

- ruled;
- expired and unrulable;
- still waiting;
- routing failure.

A verdict currently depends on manual notification or raw history scanning.

### Required direction

- enqueue a bound `review_done` notice when arbitration completes;
- report notification failure in the arbitration response;
- add an appellant-readable appeal-status lookup keyed by deny or appeal hash.

---

## P1 — witness success may misclassify refused Hestia calls

The daemon deliberately returns typed Hestia failures through the MCP success envelope so structured error codes survive SDK normalization.

Several witness hooks infer failure from `isError`, a field the daemon deliberately never sets. If raw Hestia results reach those hooks unchanged, a refused Hestia act can be witnessed as successful conduct.

The producer-consumer mismatch is measured. The full installed runtime path remains unproven.

### Required proof

Fire a refused Hestia call through the actual MCP host and installed witness hook, then assert the resulting chain record says failure and preserves the typed Hestia error code.

---

## P1 — self-protection remains noisy enough to degrade oversight

The mention-based classifier produces:

- false escalations;
- operator approval fatigue;
- polluted reputation evidence;
- difficulty documenting the gate itself;
- tests that can trigger their own protections.

The repair must preserve daemon-independent self-protection while distinguishing actual mutation targets from quoted prose, read-only operands, message bodies, and diagnostic commands.

---

## P1 — dashboard storage pressure remains unresolved

#190 corrected the rendered state, not the underlying system behavior.

Open engineering concerns include:

- SQLite busy failures under load;
- broad lock scope;
- database growth and retention;
- pagination and indexing;
- daemon memory use;
- operational alert thresholds.

---

## P1 — remote constellation operation lacks completed live acceptance evidence

Before treating remote co-signing as operationally ready, record an attended test covering:

1. `add-remote`;
2. enrollment;
3. explicit `serve-owner` consent;
4. remote challenge delivery;
5. remote co-signature;
6. roster-key comparison;
7. final hub acceptance;
8. member key rotation and expected refusal;
9. consent removal or expiry;
10. restart and recovery behavior.

This is especially important because the path previously existed in source while being unreachable in execution.

---

# Open questions

1. What exact daemon build, installed hook digest, watcher startup hash, and drift state is running on each host now?
2. Were the daemon and dashboard rebuilt and restarted after #186, #190, and #191?
3. Was the separately installed Claude gate redeployed after #185 and #175?
4. Has a live post-deployment escalation shown the attempted operation and useful context correctly?
5. Who issues the #188 policy replicas?
6. Where is the policy issuer key stored, how is it rotated, and where are issuance and revocation recorded?
7. What authenticates `plugin_id` and role at `hestia_connect`?
8. How will a cross-vendor changes-required verdict become a required GitHub status rather than an ordinary comment?
9. Are connector-mediated writes prohibited, permitted, or required to pass through a witnessed wrapper?
10. Has the complete two-machine constellation flow succeeded after #191?
11. Should `serve-owner` consent expire or bind to a roster generation, challenge scope, or nonce?
12. Has the refused-Hestia-call witness test from #168 been run through an actual installed MCP host?
13. Who owns the dashboard database contention and memory investigation?
14. When will the #159 replacement tracked by #189 be rebased and published by its author?
15. Which older open issues now describe historical rather than current source state, and should be closed or rewritten?
16. What recovery mechanism exists if common-gate migration causes fleet-wide fail-closed denial?
17. How is policy rollback distinguished from an attacker presenting an older but once-valid replica?
18. Which authority decides whether a role declaration is valid, and how is that decision witnessed?

---

# Recommended next sequence

## 1. Produce a fleet deployment manifest

This is the highest-leverage next artifact. It turns deployment claims into evidence and reveals which source fixes are actually active.

Minimum fields:

- host;
- member;
- daemon version and commit;
- installed hook hashes;
- watcher startup hashes;
- source checkout revision;
- drift direction;
- policy generation and signature state;
- last successful smoke probe.

## 2. Do not wire the common gate yet

Complete:

- signed policy replicas;
- issuer and issuance log;
- expiry and revocation semantics;
- online authority lookup;
- authority distribution before shim switch;
- deletion of granting fallbacks;
- migration and rollback playbook.

## 3. Bind member identity and role cryptographically

This should precede authoritative per-agent policy. The authority subject cannot remain a caller-supplied name and role.

## 4. Make not-same review mechanically blocking

A required commit status generated from a signed review record is the cleanest near-term shape.

## 5. Run the attended constellation acceptance test

Include consent removal and key-rotation failure behavior, not only the happy path.

## 6. Close the appeal loop and verify witness failure attribution

These are trust-accounting surfaces. A verdict that never reaches its subject and a denial recorded as success both corrupt the system’s understanding of conduct.

## 7. Publish the #159 replacement after author-owned rebase

Preserve the residual identity-quality test and receipt requirement.

## 8. Treat dashboard contention as an engineering issue

The truthful error display is complete. Storage concurrency, indexing, retention, and memory need a separate owner and acceptance criteria.

## 9. Triage stale issue and README claims

In particular, distinguish:

- source fixed;
- installed;
- process restarted;
- behavior live-probed;
- fleet-wide.

The shared-core documentation should say “protected by the Claude adapter” rather than implying universal protection until every harness is migrated.

---

# Bottom line

The previous audit produced real improvement. The repository did not merely paper over findings; it repeatedly changed tests, design assumptions, and architecture in response.

Hestia is currently strongest at finding discrepancies between claims and execution. It does not yet have one complete mechanism proving that the running fleet corresponds to the reviewed source and authority state.

> **Source `main` is increasingly trustworthy. Runtime authority and deployment provenance are not yet trustworthy enough to wire the consolidated gate fleet-wide.**

That is not a reason to stop the consolidation. It is the criterion for the next phase: make deployment, identity, authority, review, and external mutation first-class witnessed artifacts rather than environmental assumptions.
