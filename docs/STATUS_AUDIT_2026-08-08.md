# Hestia current-state audit — 2026-08-08

**Baseline:** `origin/main` at `9a6a5c2`
**Purpose:** reconcile source, deployment, public artifacts, open issues, the product PRD,
the governance PRD, and the public-hub demo target.
**Rule:** *source*, *merged*, *installed*, *restarted*, *live*, *observed*, and *released*
are different claims. This document does not use one as evidence for another.

## Executive state

Hestia's active source is substantially ahead of its public releases. The reference daemon is
now built from and running the current `origin/main`, with a supervisor manifest naming the same
build. The governance architecture is well specified and heavily instrumented, but its shared gate
core is not wired into the harnesses and the current appeal grant remains portable across acts.
The Tauri application exists as a meaningful prototype; the only public app artifact is an older
Android APK. The public-release and demo blockers are therefore distribution and demonstrated
newcomer operation, not an absence of core source code.

| plane | state on 2026-08-08 | evidence |
|---|---|---|
| source | **current** | `origin/main` = `9a6a5c2`; no open Hestia PRs at audit time |
| reference daemon | **current and restarted** | `hestia --version` = `app-v0.1.2-761-g9a6a5c2` |
| deployment authority | **present and matching** | `current-build.json` names the identical build id |
| harness installation | **not fully re-proven** | the daemon and manifest match; a per-harness installed-file census is still owed |
| public daemon release | **stale** | latest is `v0.0.3` (2026-05-17), 324 `core/` commits behind this baseline |
| public app release | **Android only and stale** | latest is `app-v0.1.2` (2026-06-13), one APK asset |
| desktop installer | **not publicly released** | source is bundle-configured; no desktop app asset is attached to a release |
| product PRD | **requirements remain sound; old source findings corrected below** | `docs/PRD.md` amendment v5 |
| governance PRD | **design-current; implementation incomplete** | decision 0013 and sprint dependency graph in `docs/PRD_GOVERNANCE.md` |
| demo hub source | **discussion path merged and hardened** | web4 Track H and production follow-ups are on `origin/main` |
| deployed public demo | **not demonstrated by durable evidence** | clean-device install, current `/discuss`, second-device join, and full rehearsal remain owed |

## Product PRD reconciliation

### Corrected source findings

Two severe findings in the 2026-07-25 product PRD have since been contained in source:

1. **Vault default exposure is no longer manufactured for new entries.** Vault writes require an
   attributed live session. A new entry with no explicit consumer list is bound to its creator.
   Reads also require an attributed live session and are witnessed. Existing legacy entries with an
   empty consumer list remain readable for compatibility, but are marked exposed, warned, and shown
   to the operator. This is containment, not the final entitlement model: the transport still accepts
   caller-asserted identity, legacy exposed entries remain, and release/presentation rules are not yet
   represented as the two issuance-bound axes required by the PRD.
2. **OID4VCI credential issuance is now operator-gated and witnessed.** `/credential` moved behind
   the challenge-signed operator surface and appends `credential_issued`. The full wallet-delegation
   authorization model remains separate work; this repair prevents an arbitrary local caller from
   minting an owner-signed presentation.

The following product gaps remain unchanged:

- the public `v0.0.3` first-run path does not provide the promised nontechnical onboarding;
- the live app contract tests remain explicitly ignored and are absent from CI;
- there is no clean-machine, nontechnical-user success artifact;
- there is no owner-seat correct-deny/recovery transcript;
- there is no public desktop app release paired with the current daemon;
- device-constellation and wallet flows remain thinly exercised rather than user-demonstrated.

## Governance PRD reconciliation

The governance PRD's target model is current. The most important settled change is decision 0013:
an appeal is a state transition on one recorded act, not a capability minted for a future act.
That target is **not implemented yet**.

| capability | current source state | next dependency |
|---|---|---|
| one shared policy gate | core exists, but its own README says **NOT WIRED**; harnesses retain decision logic | Sprint 5 consolidation |
| deployment freshness | daemon build id + supervisor manifest implemented and current on the reference installation | prove installed adapter parity across every harness |
| Plane E availability record | producer code merged | wire and induce one durable row per installed harness |
| actor identity | session-bound in several sensitive paths, but the initial plugin identity is still asserted | Sprint 2 key-bound identity/signing |
| escalation link | schema has `answers_deny`; historical opens do not populate it | Sprint 1 observation, then Sprint 2.5 act link |
| exact act digest | specified as versioned `ActEnvelope` + RFC 8785 JCS + domain-separated SHA-256 | shared canonicalizer and plugin-to-daemon wire |
| current grant | still joined through member/marker compatibility machinery | replace with act-bound append-only verdict state |
| timeout terminal state | specified, not implemented | Sprint 2.5 compare-and-swap transition |
| peer arbitration | daemon verb and NOT-SAME checks exist | do not add an autonomous driver before Sprint 2.5 and NOT-BENEFICIARY |
| third verdict | `Escalate` still collapses into deny in the heuristic rung | Sprint 3, after act binding |

### Sprint order after the deploy

1. Finish Sprint 0 evidence: installed-harness parity, induced Plane E rows, availability baseline,
   configuration drift result, and construct-pointer conversion. The reference daemon deploy is now
   green; fleet-wide proof is not implied.
2. Sprint 5: consolidate the gate into one installed decision core with syntax-only shims.
3. Sprint 0.5: make unresolved grain loud rather than substituting a default.
4. Sprint 2: key-bound identity, signatures, and composed actor/instructor/beneficiary provenance.
5. Sprint 1: observe evidence class, occupancy, delegation effect, and act-link readiness.
6. Sprint 2.5: bind every appeal and ruling to one canonical recorded act.
7. Sprint 3: restore `Escalate` and only then introduce a resolver driver.
8. Sprint 4 onward: authority/occupancy, operator surface, and hub projections.

## Open issue reconciliation

Nine issues were open at the audit baseline.

| issue | current disposition |
|---|---|
| #224 | **refresh** — the index names the previous, now-closed generation and omits the current issue set |
| #225 | **valid release blocker** — fail-closed behavior is not an equivalent recovery contract across harnesses |
| #242 | **valid and reproduced** — unanchored deletion patterns still match token-internal text in read-only acts |
| #244 | **partially fixed** — interactive Claude attribution now falls back to its process identity; final repair is decision 0013 + signed origin |
| #259 | **narrow** — mismatch refusal and witness tests landed; a live positive claim still must prove `claimed` and `permits_write` together |
| #260 | **source-fixed; deployment verification owed** — quoted-heredoc handling and regression coverage landed |
| #261 | **valid / superseded in design** — the old appeal route remains incoherent; Sprint 2.5 is the repair, not another portable identifier |
| #263 | **partially fixed** — content carve-outs improved; the member-facing probe and gate-self-reporting path still need a usable contract |
| #264 | **valid but blocked deliberately** — the driver must not automate the current portable-grant defect |

During this audit, a compound read that named an installed governance adapter was classified as a
write and opened an escalation. Nothing was modified and the refused command was not retried. That
is fresh evidence for #225/#263 and for consolidation: ordinary source verification still depends
on which harness parser receives it. A later `GATE_PROFILE.md` correction that quoted the same
existing reference was also refused. The operator approved that exact escalation, and the identical
patch was then applied once; no alternate spelling or write path was used. The approval path worked,
while the classifier still imposed a human decision on documentation rather than gate code.

## App and release reality

`app/` contains a real React/Tauri client with dashboard, vault, policy, chain, fleet, hubs,
delegation, settings, operator-session, and remote-client code. The package and Tauri crate report
version `0.2.0`, and the bundle configuration targets desktop packages. Those facts prove a source
implementation, not a distributable product.

The release automation currently has two independent lanes:

- daemon tags build Linux, Windows CLI, and macOS CLI archives;
- app tags build and attach an Android APK only.

There is no workflow that publishes a Windows MSI, macOS bundle, or Linux desktop app, and no CI
job boots a daemon and runs `operator_live --ignored`. Documentation must therefore say
**prototype built; Android artifact released; desktop packaging/release and contract CI open**.

## Demo target reconciliation

The canonical demo target is a public governance-discussion hub with discoverable law, member join,
fillable roles, witnessed discussion, and Hestia acquisition. External-chain anchoring was
explicitly cut; the honest statement remains: **the ledger is local, signed/hash-linked, and
verifiable; external anchoring is not wired**.

The hub source is ready for this shape:

- Track H provides public topic/post reads and a minimal `/discuss` view;
- topic and post writes travel through signed events, law evaluation, and the ledger;
- tests cover law separability, public reads, invalid topics, input limits, escaping, and ledger
  verification;
- subsequent changes repaired the production container context, ignition/law ordering, and law
  parse-error behavior.

What is not yet evidenced as one continuous public demonstration:

1. the intended public endpoint is running that current hub source;
2. a second device discovers, connects, joins, and receives a role;
3. a newcomer acquires the currently advertised Hestia artifact and completes the path;
4. topic/post/readback and ledger verification are run against the deployed target;
5. the five-minute script is rehearsed twice, including a correct refusal and recovery;
6. the download claim matches the artifact actually published.

Until those six steps have receipts, the accurate demo status is **source-ready,
deployment/distribution unproven**.

## Immediate next actions

1. Complete the current deployment proof with an installed-adapter census and one induced Plane E
   event per harness; do not infer hook freshness from daemon freshness.
2. Deploy and unlock the current hub build, then run the complete discussion + ledger smoke path.
3. Decide the audience artifact: publish a signed desktop installer or explicitly scope the demo to
   Android/CLI.
4. Run the clean-device newcomer script twice and preserve the transcripts.
5. Fix #242; it is small, live, and degrades the credibility of governance prompts.
6. Refresh #224 and narrow/close issues only against deployed acceptance evidence.
7. After the demo, consolidate the gate before implementing the identity and appeal sprints.

## Reproduction notes

The source and release claims above were checked from a clean worktree at `9a6a5c2`. The deployed
build and manifest were read after the operator reported the restart complete. GitHub release and
issue state were fetched during the same audit. Hub source status was checked against the public
web4 mainline and its standalone public mirror. No source repository was modified during the audit;
this document and its companion corrections are the resulting editorial change.
