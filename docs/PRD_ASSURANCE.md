# Hestia — Assurance & Evidence PRD

**Status**: draft v1 · **Date**: 2026-07-27 · **Stage**: research / R&D, not production
**Companions**: [`PRD.md`](PRD.md) (the product — what a person installs and why) · [`ARCHITECTURE.md`](ARCHITECTURE.md) (how it works) · [`PROTOCOL.md`](PROTOCOL.md) (the wire) · [`GATE_BYPASS_CATALOG.md`](GATE_BYPASS_CATALOG.md) (what the gate does not stop)

> `PRD.md` answers *what Hestia is for a person*. **This document answers a narrower question:
> what must Hestia actually DO before a relying party is entitled to believe its evidence?**
> It is a functional requirements document, not a roadmap promise and not a security claim.

---

## 1. The gap this document exists to close

Hestia is built to govern **partially trusted agents**. Several of its most sensitive
surfaces still assume that processes sharing the local user account are benign. Those two
statements are in tension, and the tension is the subject of this PRD.

The gate that exists today is genuinely useful: it stops accidents, it makes actions
legible, and it produces an evidence trail that did not previously exist. It is **not** an
adversarial containment boundary, and nothing in this repository should claim that it is.

**North-star behaviour.** A relying service accepts a consequential agent action only when it
can independently verify an audience-bound, replay-resistant policy decision bound to an
authenticated workload, a persistent identity, a role, a delegation chain, the exact request,
and a declared enforcement profile — and the action and its evidence persist together.
Crucially, that verification must be possible **without running Hestia**.

---

## 2. Assurance profiles — the vocabulary this repo should use everywhere

Most confusion about "is it secure?" is a missing subject. Every security claim in this
repository should name the profile it holds at.

| Profile | Meaning | Holds against |
|---|---|---|
| **A0 — observed** | Actions are recorded; nothing is enforced. | Nothing. Evidence only. |
| **A1 — cooperative gate** | An in-process hook consults policy and complies. | Accidents, mistakes, a well-behaved agent. |
| **A2 — external enforcement** | The relying service verifies a signed decision before acting. | An agent that ignores or removes its own hook. |
| **A3 — OS-isolated** | Obligations are enforced outside the agent process (separate UID / container / sandbox). | A malicious process at the agent's privilege. |
| **A4 — hardware-attested** | Workload identity is rooted in hardware attestation. | Host-level substitution of the workload. |

**Where Hestia is today: A1.** The current default configuration is a cooperative gate with
an evidence plane. A2 is the next functional target; A3 requires an external isolation
runtime; A4 requires attestation hardware.

A control that is not tested holds at **A0** regardless of intent.

---

## 3. Functional requirements

Ordered by dependency, not by ambition. Each carries a *state* — `implemented`,
`partial`, or `not started` — that must be accurate at all times. A requirement whose state
is overstated is a defect in this document.

### FR-1 — Transport-established identity *(state: not started)*

Today the caller supplies its own `plugin_id`, host identity and role over an
unauthenticated MCP transport. Those are **claims**, and everything built above them
inherits that. This is the hinge requirement: several requirements below are only as strong
as this one.

- The server establishes the calling principal from the transport itself — local peer
  credentials (Unix-domain socket UID/PID; equivalent named-pipe identity on Windows), or a
  mutually authenticated remote channel.
- `hestia_connect` becomes **enrollment and capability negotiation**, not identification.
  Caller-supplied labels are checked against enrollment; they never authenticate.
- Session identifiers are correlation only. **A session identifier alone confers no
  authority**, and copying one to another connection transfers nothing.
- Authority-bearing surfaces have no "latest session" or anonymous fallback.
- Every witnessed entry names the authenticated principal that was used at action time.

*Acceptance*: two local processes cannot claim each other's identity; a copied session id
grants nothing; a witnessed act names an authenticated principal.

### FR-2 — Credentials are capabilities, not strings *(state: partial)*

The standard path for an agent to use a secret should not be to receive the secret.

- Consumer and scope state must be **explicitly typed** (`DenyAll | AllowList | OwnerOnly`,
  `UnscopedForbidden | Scopes`). An absent or empty value must not be silently reinterpreted
  as "unrestricted" — the failure mode a `Vec` overloaded with two meanings invites.
- The standard flow is a **brokered operation** or injection into an isolated process:
  bounded by principal, operation, audience, TTL and use count. Raw export is exceptional and
  high-consequence.
- Credential **release is witnessed**, with the reader and the basis recorded and the secret
  value never written to the record.

*Current state, stated plainly — and measured against `main`, not against a branch*: an empty
consumer list means "readable by any caller", contradicting the type's own documentation. On
**merged `main` today, credential release is still unwitnessed and the empty-list default is
still open**. Containment — binding new entries to their creator, witnessing every release,
and an operator-visible exposure list — is written and tested but sits in an **open PR**; it
is not landed, and this document does not get to count it. Pre-existing entries with empty
consumer lists will still release under that containment, with a warning, because breaking
live agents mid-run was judged worse than a disclosed exposure. **Fail-closed migration of
existing entries is a gate on any production claim** — see §6.

### FR-3 — Decisions are portable and independently verifiable *(state: not started)*

The functional inversion: Hestia stops being *the thing that enforces* and becomes *the thing
that issues verifiable decisions*, which someone else enforces.

- Policy decisions are signed objects bound to the exact request, an audience, policy and law
  versions, obligations, expiry and use count.
- A relying service verifies a decision **without contacting Hestia**, and refuses missing,
  expired, replayed, audience-mismatched or lower-assurance decisions.
- The in-process gate remains as defence in depth and UX steering. Its verdict may *request*
  a decision; it may not *substitute* for one.
- Action classification comes from typed action metadata, not from route-string matching.

*Acceptance*: **killing or removing the agent-side hook does not authorize the action.** That
single sentence is the difference between A1 and A2.

### FR-4 — Evidence integrity, and the meaning of absence *(state: partial)*

An append-only log is not automatically evidence. What makes it evidence is that omissions
are detectable and that no party can author another party's statement.

- Entries are signed; heads are anchored beyond the local machine so that rewriting a
  complete local chain is detectable.
- For high-consequence actions, the accepted decision persists **before** execution and the
  result persists before final success is reported. Evidence is part of the action contract,
  not telemetry emitted afterwards.
- **Absence is machine-detectable**: an accepted decision with no corresponding outcome is a
  distinguishable state, not silence indistinguishable from idleness.
- Actor claims, policy decisions, execution observations, witness observations and
  adjudications are separate record types. **No party may author another party's statement.**
- Corrections are supersessions, never edits. Reputation derives from the active adjudication
  graph, with provenance, and never from raw counts.

*Acceptance*: a third party cannot move an actor's standing by naming it, absent a valid
authority reference and evidence.

### FR-5 — Key custody and process isolation *(state: not started)*

- No passphrase in the daemon's environment; child processes start from a cleared
  environment with a minimal allowlist.
- No user-writable helper executes with daemon privileges.
- Where practical the daemon runs under its own OS identity, with agents in separate
  UIDs/containers. Same-UID deployment is documented as **A1 only**.
- Authentication failure on a stored artifact is treated as tampering — never as an
  invitation to fall back to parsing a legacy plaintext format.
- Vault and chain writes are atomic and interprocess-safe: either the old state or the new,
  never a partial commit.

### FR-6 — Legibility of state *(state: partial — see per-bullet notes)*

An operator must be able to see what is enforced, what is merely recorded, and what is
exposed — without reading source.

- Startup and dashboard state the current assurance profile, including **degraded**.
- Published policy distinguishes **enforced** rules from rules that are recorded but consumed
  by no evaluation path. Publishing an unenforced rule as if it stops an action is a defect.
- Unmeasured is reported as **absence of evidence**, never as a low score. *(On `main` an
  unmeasured grain still ranks below the lowest trust level in the roll-up; the fix is an
  open PR.)*
- Experimental surfaces are enumerable at runtime.

### FR-7 — Buildability and conformance *(state: partial)*

- A clean checkout of a tagged release builds and tests without unpublished sibling paths.
- CI gates: format, lint, unit/integration tests, dependency audit, secret scan, license
  scan, and fuzzing of parsers and envelope decoders.
- Releases carry SBOM, provenance and signed checksums.
- The monolithic handler is split along its real boundaries — transport/authn,
  authorization, policy, credential brokering, evidence, messaging, operator — with explicit
  lock and I/O boundaries.

---

## 4. Integration points with the broader ecosystem

Hestia is deliberately **not** a replacement for the layers below. These are the seams where
it composes, described functionally; nothing here presumes any particular relationship with
any project or organization.

| Layer | Ecosystem work | What Hestia contributes | What Hestia does **not** do |
|---|---|---|---|
| Workload identity | SPIFFE / SPIRE and equivalent attestation systems | Binds an attested workload principal to a persistent contextual identity, role and delegation chain | Does not perform workload attestation |
| Agent harness | Typed agent frameworks and their tracing | Maps typed invocations to canonical action evidence, trace-linked | Does not replace the agent framework |
| Isolation | Container, sandbox and OS-isolation runtimes | Carries policy obligations into the boundary and verifies the enforcement profile | Does not itself isolate anything |
| Tool protocol | MCP and its security work | Concrete, machine-verifiable evidence for identity, authorization, credential and attribution concerns | Does not replace the threat catalogues |
| Policy engines | OPA and similar | Composed decisions, expressed as portable signed objects | Does not replace policy languages |

The reusable artifact is the **evidence contract**, not this implementation. A relying party
must be able to verify Hestia-issued evidence with public keys, schemas and a standalone
verifier. If verification requires running Hestia, the contract has failed.

---

## 5. Non-goals

- Containing a malicious process holding the same OS privileges as the daemon (that is A3+,
  and it is the isolation runtime's job).
- Universal Sybil or witness-collusion resistance.
- Composite trust scores as a cross-ecosystem authorization primitive. Scores are optional
  interpretations over signed evidence; **provenance outranks scores**.
- Replacing identity, policy, sandboxing or agent frameworks.

---

## 6. Research posture vs. production gate

This repository is R&D. The two postures have different bars, and conflating them is how
projects overclaim:

| | Research (now) | Production claim (gate) |
|---|---|---|
| Empty/absent credential scope | Releases, warned + witnessed, exposure listed | **Denies**, with explicit fail-closed migration |
| Unattended integrations | May fail open, disclosed | **Fail closed**; fail-open is an explicit, visibly unsafe override |
| Raw credential export | Standard path | Exceptional, high-consequence, brokered by default |
| Transport identity | Caller-asserted, disclosed | Server-established |
| Bind address | Loopback | Non-loopback requires authenticated TLS |
| Assurance claim | A1, stated | Stated per surface, with tests |

These are **sequenced, not contradictory**. Choosing continuity of a working research fleet
over a hard fail-closed default is legitimate *while the posture is disclosed and the gate is
named*. It stops being legitimate the moment anything here is described as production-ready.

**Any claim of production readiness requires the right-hand column, in full.**

---

## 7. How to keep this document honest

- Every state marker (`implemented` / `partial` / `not started`) points at code or a test, or
  it is wrong.
- A security claim without a named assurance profile is incomplete.
- A control with no test holds at A0.
- When an audit or review contradicts this document, the document is what changes.

*Known open items are tracked as issues and in [`GATE_BYPASS_CATALOG.md`](GATE_BYPASS_CATALOG.md).
Findings from external review are kept verbatim in `forum/` alongside their disposition, so
the finding and the response remain separable.*
