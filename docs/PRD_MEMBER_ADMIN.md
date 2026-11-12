# PRD — governed member-mesh administration

**Status:** proposed design for review, not implemented and not an enforcement claim.
**Tracker:** #1332. This is slice 1 of the issue's implementation plan.
**Read with:** `PRD_ALLOWLISTS.md`, `PRD_APP_GOVERNING_SURFACES.md`,
`PRD_DISPOSITION_DELIVERY.md`, `TRANSPORT_BINDINGS.md`, and `plugins/member-mesh/KINDS.md`.

## 0. The decision this design makes

Membership in `plugins/member-mesh/MEMBERS` currently means three different things: a claimed
`plugin_id`, permission to deliver a notice, and distribution of that permission to each receiving
seat. They must become separate objects.

1. **Identity** has an explicit per-grant assurance level. Reported and verified levels reuse an
   existing key-bound hub LCT and its witnessed evidence, including the actor/carrier/reply-to
   relationship recorded by a transport binding (#1030). A caller-supplied `plugin_id` and the
   session `softLct` can satisfy routing-level admission only; they are never verified identity
   proof.
2. **Authority** is an operator-granted sender grant. Knowing an LCT does not entitle its holder to
   deliver anything. The first slice supports a named, witnessed all-local/all-member-kinds grant
   and optional narrow recipient/kind-prefix grants, not general wildcard or role grants.
3. **Distribution and enforcement** live in the daemon. Local consumers share the daemon's admission
   decision rather than reimplementing it in N renderers. A separate vault-backed `member_mesh`
   document has its own generation; it does not share the `scope/standing` generation.

The receiving operator controls admission. An upstream repository, sender, hub, courier, or identity
proof cannot grant itself delivery.

## 1. What exists, and what must not be reused as a shortcut

- `MEMBERS` feeds the fire templates' sender allowlists. Withholding currently happens **at render
  time, after `drain_member` has already marked the notice drained**. The template announces
  `! WITHHELD`, strips the pointer, and retains the primer when nothing is fireworthy. Thus a legacy
  withheld notice can already carry `drained_at`; that mark is not proof of admission, reading, or
  acceptance.
- The measured failure behind #1332 is **admission lag for legitimate senders**, not a measured
  spoofing incident: #1321 withheld 73 sprout notices, including 10 review requests, and the
  2026-09 `cbp-being` incident withheld 10 of 10 notices, including nine appeals in eleven hours.
  The grant layer's primary job is to remove that administrative delay without hiding withheld mail.
  Spoof resistance is a separate property and depends on the identity evidence and key custody below.
- `hestia_connect` accepts a caller-supplied `plugin_id`; its `/` guard protects address parsing, not
  identity. `tool_connect` issues a session `softLct` without a member key or signature. Neither is a
  key-bound member identity, and proof of possession remains a distinct assurance problem (#824).
- A key-bound hub identity already exists. `TRANSPORT_BINDINGS.md` distinguishes the actor, relay,
  carrier whose key signs, and reply-to identity. When a grant requires reported or verified
  evidence, member administration must cite that existing hub LCT and binding evidence rather than
  mint a third member key. The current `carrier_proof: "reported"` is not cryptographic proof
  against a hub ledger; the implementation must not upgrade it to `verified` in prose or in a grant
  receipt.
- On same-UID deployments, a private key stored in a member-readable file is protected by the same
  gate boundary as its peers, not an independent operating-system principal. Secret-path coverage
  and recursive/hardlink traversal are #1331's boundary. Proof of possession therefore demonstrates
  access to a key, not unique custody or resistance to a determined same-UID actor. The identity
  record must expose this assurance limit rather than calling every local key file independently
  key-bound.
- Beings do not pass through `MEMBERS`: the SAGE heartbeat renders its own inbox, and hub-relayed
  notices are re-notified by the relaying seat. Enforcement at a fire-template allowlist therefore
  cannot cover every supported consumer.
- `("hestia", "unreachable")` and `("hestia", "disposition")` are admitted specially because only
  the daemon can mint those kinds. They are not ordinary member identities and cannot be admitted
  through the new grant editor.
- `PolicyList` supplies vault-backed schema, bindings, and permissions, but its own module says the
  lists are not yet enforced. This PRD must not present a `PolicyList` edit as a delivery control.
- The daemon already has an operator LCT challenge/session channel, a witness chain, vault-held
  documents, notice storage, and a `drained_at` delivery mark. These are the reuse points.
- Transport and channel bindings already have independent generations. `transport_binding_set`
  witnesses intent, persists the candidate, witnesses the terminal fact, and rolls the store back if
  the terminal witness fails. This is the finality pattern to reuse, rather than coupling mesh
  administration to the gate core's `scope/standing` generation and certified-replica behavior.

## 2. Terms and stored objects

### 2.1 Member identity

```jsonc
{
  "lct": "<existing-hub-lct> | null for routing-only registration",
  "member_id": "claude-code",             // stable routing label, not proof by itself
  "identity_evidence": [{
    "kind": "routing-label | hub-proof | transport-binding",
    "ref": "<daemon-attributed-route, hub-receipt, or binding-version>",
    "proof": "routing | reported | verified",
    "evidence_hash": "<witnessed-registration-or-attestation>"
  }],
  "key_custody": "<operator-inspected custody and same-UID limitation>",
  "status": "known | suspended | revoked",
  "reason": "<operator-supplied text>",
  "updated_at": "<rfc3339>"
}
```

Member administration always registers a routing label. A `reported` or `verified` registration also
names an existing hub LCT; it does not generate or store another member private key. Public-key
fingerprints may be cached as lookup metadata, but the evidence reference must identify the existing
hub proof/binding and its actual verification level. A relay-only member with no hub LCT of its own
can be registered with `lct: null` for routing-level admission instead of being forced through an
undocumented hub join.

An LCT and a `member_id` are separate keys. A second LCT claiming an occupied `member_id`, or a
second `member_id` claiming an occupied non-null LCT, is a conflict, not an alias. `codex` and
`codex-cli` remain distinct grant targets until an operator explicitly maps them to one LCT;
migration must not collapse them by string similarity.

Each grant selects a `min_identity` assurance level for the **current delivery act**:

- `routing` requires the daemon-attributed `plugin_id` to match the registered `member_id`. It
  provides routing consistency and no spoof-resistance claim. The session `softLct` remains routing
  evidence, not a key-bound identity.
- `reported` additionally requires the current act to resolve to the registered hub LCT or transport
  binding whose evidence is explicitly marked `reported`. A bare label or `softLct` does not become
  reported hub evidence, and reported evidence is never displayed as verified.
- `verified` requires cryptographic proof that the current act is bound to the registered hub LCT
  and `member_id`. Local `hestia_member_notify` has no such signature today; a verified local grant
  cannot be activated until the local proof-of-possession path (#824) exists. The admission-lag fix
  does not wait for that separate slice.

The operator chooses and witnesses the required level. Every admission receipt exposes both the
required and observed levels plus the same-UID custody limit; no path silently upgrades a weaker
level. Spoof-resistance acceptance applies to grants that require `verified`, not retroactively to
`routing` or `reported` grants.

### 2.2 Sender grant

The initial implementation has two explicit scope shapes:

```jsonc
{
  "grant_id": "<uuid>",
  "member_id": "<stable-routing-label>",
  "member_lct": "<existing-hub-lct> | null for routing-only",
  "min_identity": "routing | reported | verified",
  "scope": "local_mesh",                  // all local recipients, all member-sendable kinds
  "mrh": { "hosts": ["local"] },
  "not_before": "<rfc3339>",
  "expires_at": null,                    // null means no calendar expiry, never a stale snapshot
  "reason": "<required operator rationale>",
  "origin": "operator-edit | migration | escalation",
  "generation": 42
}
```

`local_mesh` is a **named and witnessed broad grant**, not a wildcard syntax. At each delivery
decision it covers every seat in the then-current local recipient registry, including seats added
after grant issuance, and every kind a member can send through `MEMBER_NOTICE_KINDS`, including
dotted specializations. It never covers daemon-only `unreachable`/`disposition`, a remote-host
recipient, or a role/group expansion. Registering a new recipient does not give that recipient any
sender authority.

A narrow grant instead carries `"scope": "narrow"`, one exact `"recipient"`, one `"kind"` prefix,
and a local MRH. `kind` accepts the same non-empty lowercase segments and 64-byte bound as the
daemon's existing `kind_under`; `review` matches `review` and `review.done`, never `review_request`.
There is still no general `*`, role grant, recipient-group language, or cross-host wildcard.

This avoids requiring the roughly 7 × 7 recipient/kind cross-product for every migrated sender.
Default deny remains unchanged: `local_mesh` is an operator's explicit per-sender choice, never an
implicit migration default. Narrowing is optional. A narrowing mutation replaces the prior grant's
scope; it cannot leave the old broad grant live beside the new narrow one. Narrowing may raise but
never lower `min_identity`, and cannot change the registered member.

### 2.3 Policy document, generation, and enforcement

Add a distinct vault-backed `member_mesh` document with its own monotonic `generation`, modelled on
the transport/channel binding documents (#1030), **not** an object in `scope/standing`. Mesh grant
mutations therefore cannot look like scope changes to gate replicas. The document and its generation
live in the same vault and use the same witness/finality construction as `transport_binding_set`.
An absent pre-schema document is in **migration pending** state, never migration-complete.

Every mutation witnesses `member_mesh_policy_intent` with actor, authority, reason, previous/new
value, and expected generation; persists the candidate; then witnesses `member_mesh_policy_changed`
with the actual generation. A failed terminal witness rolls the candidate back. A rollback failure
is reported as a live, unconfirmed mutation, never as a successful rollback. No cross-store
atomicity is claimed.

`drain_member` is the authoritative local admission point. It returns admitted notices plus a
bounded withheld summary; a denied notice's pointer is not returned for rendering. `peek_member`
uses the same admission rule so it cannot become a bypass. Fire templates, the CLI, and the SAGE
heartbeat sanitize and render the daemon's decision; none re-reads `MEMBERS` or derives its own
grant decision. A daemon-owned delivery-preflight call revalidates the admitted notice IDs and
generation immediately before a fire or equivalent outward act.

The authoritative local read sees each committed generation on the next call, so there is no local
snapshot-propagation interval. Only daemon-external consumers such as `hub-watch` need an immutable
projected snapshot `{generation, snapshot_expires_at, grants, identities}`. Snapshot fetch or vault
read failure withholds delivery; neither falls back to `MEMBERS`, an environment override, or a hub
mirror.

### 2.4 Withheld notice and replay receipt

A withheld notice keeps its original `notice_id`, claimed sender, authenticated origin when present,
courier, kind, pointer, queue time, and routing data. It also records `withheld_at`,
`withheld_reason`, and `decision_generation`. Its lifecycle is
`withheld -> eligible -> replayed | expired | rejected`. `eligible` requires a matching live grant;
it does not assert that the original sender was proven retroactively. For every post-migration
notice, a withheld row gets `withheld_at`, never `drained_at`; `drained_at` is set when the row is
admitted and delivered, or when its withheld projection is first replayed. Retries do not move that
first-delivery mark.

For the existing backlog, migration starts from **already-drained notices with positive legacy
render-time withholding evidence**, such as an operator-inspected retained primer/fire record. It
preserves the old mark as `legacy_drained_at` and attaches the migration evidence. A bare
`drained_at` row is not enough to classify a notice as withheld, and the migration must report an
incomplete legacy inventory as incomplete rather than inventing withheld rows.

A replay receipt records `{notice_id, recipient, grant_id, replay_generation, replayed_at,
replayed_by}` with uniqueness on `(notice_id, recipient)`. A replayed notice is a projection of the
original with `replay_of=notice_id`, not a new sender act and not a second original notice. One
notice or an inspected per-sender batch uses the same per-notice receipt and idempotency rule.

### 2.5 Relay attribution

The daemon notice row must distinguish:

```jsonc
{
  "from_plugin": "<relaying-seat>",
  "courier_lct": "<relaying-seat-hub-lct>",
  "authenticated_origin": {
    "member_id": "<originating-member>",
    "member_lct": "<originating-hub-lct>",
    "evidence_hash": "<verified-origin-envelope>"
  },
  "original_notice_ref": "<origin-transport-record>"
}
```

Today's relayed row names the courier in `from_plugin`; the originating sender's
`authenticated_sender` exists only in the seat-owned SAGE record. The backend must import that
origin into a daemon-owned, verified field rather than treating the courier's label as the author.
The relay path must verify the origin envelope and its binding to the original notice before
populating `authenticated_origin`; caller-supplied origin JSON is not evidence.

Origin-scoped grants evaluate `authenticated_origin`. A missing or invalid origin cannot inherit an
origin grant through the courier. An operator may separately grant the courier's own relay act, but
that decision is labelled courier authority and never described as authenticating every forwarded
author.

## 3. Decision rules

1. **Default deny.** No matching live grant means withheld, with an operator-visible reason and no
   pointer rendered to the recipient.
2. **Identity assurance is explicit, not sufficient.** A grant names a registered member and, when
   its `min_identity` requires it, a witnessed existing hub LCT. The current act must meet the
   selected `routing`, `reported`, or `verified` level. Only `verified` claims spoof resistance;
   required and observed levels plus same-UID custody limits are recorded, never hidden.
3. **Most specific live grant decides.** A narrow grant takes precedence over `local_mesh` for the
   same registered member + recipient + kind + MRH. Suspension or revocation at any matching scope
   wins over admission. An expired grant is not live: it falls through to a less-specific live grant,
   including `local_mesh`, rather than acting as a narrow denial. Expiry is checked at decision time,
   not at snapshot publication; no live grant at all means default deny.
4. **Preflight dominates effects.** The daemon evaluates authority at drain before sanitization,
   primer creation, or fire. It evaluates again immediately before the outward act. If revocation
   lands between those checks, nothing fires or is externally delivered.
5. **Revocation is a tombstone, not deletion.** The previous grant and its witness history remain
   inspectable. Already running CLI sessions are not claimed to stop retroactively; the outcome is
   recorded as `revoked_after_fire` if revocation landed after the final preflight.
6. **Admission is not replay.** Admission creates eligibility only. Withheld content requires a
   separate operator replay act after the pointer has been inspected outside a model prompt.
7. **Replay is idempotent.** A duplicate replay, per-sender batch retry, watcher retry, restart, or
   daemon recovery cannot create a second delivered copy. The first replay sets `drained_at` as §2.4
   specifies; retries leave it unchanged, and no replay rewrites `legacy_drained_at`, answer bindings,
   or `in_reply_to`. Replay must not manufacture a second open review debt.
8. **Daemon kinds are structural.** `unreachable` and `disposition` remain admitted only by their
   daemon-minting construction, never by `local_mesh` or a member-editable sender grant.
9. **Courier and origin are distinct.** A courier cannot lend its grant to an asserted origin, and an
   origin grant cannot be satisfied by an unverified `authenticated_sender` claim.

## 4. Administration surfaces

### 4.1 Authority

All mutations use the daemon's authenticated operator LCT challenge/session channel. There is no
member-reachable MCP mutation, no `MEMBERS` write API, and no sender self-admission. The daemon's
web console, the app, and the CLI call the same endpoints and see the same `member_mesh` generation;
the strong channel is named in every receipt. Filesystem access to `HESTIA_HOME` is not presented as
the strong operator channel.

The initial administration tier is **operator-only**. A future peer-required tier can be raised by
policy, but lowering a tier must satisfy the tier being lowered from. Migration's first grant
cannot be approved by the member being admitted.

### 4.2 API and CLI

| operation | surface |
|---|---|
| list identities, grants, withheld notices, replay receipts | `GET /api/member-admin/state` |
| inspect one identity/grant and its provenance | `GET /api/member-admin/grants/{grant_id}` |
| register a routing identity, attach hub-LCT evidence, or issue a grant | `POST /api/member-admin/grants` |
| narrow an existing grant | `POST /api/member-admin/grants/{grant_id}/narrow` |
| suspend temporarily | `POST /api/member-admin/grants/{grant_id}/suspend` |
| revoke permanently | `POST /api/member-admin/grants/{grant_id}/revoke` |
| replay one or an inspected per-sender batch | `POST /api/member-admin/withheld/replay` |

The CLI equivalents are `hestia member admin list|show|grant|narrow|suspend|revoke|replay`.
Every write returns the actual daemon result and new `member_mesh` generation. There is no
optimistic local success. Every editor re-reads before offering an edit and again after acting. A
narrowing cannot widen recipient, kind, MRH, registered member, or expiry, and cannot lower
`min_identity`; those changes require a new grant. Raising `min_identity` is a permitted narrowing.
A batch replay names the inspected notice IDs, returns one result per ID, and is retryable as one
operation without duplicating any successful notice.

Read-only views may expose an LCT's effective grants to that member. Withheld pointers and other
members' policy details remain operator-only. A read API never returns private key material or
secret-bearing notice content.

### 4.3 Console

The member-administration view shows identity evidence, required and observed `min_identity`
levels, and custody limits separately from delivery authority, current generation, grant scope,
expiry, provenance, and reason. A `local_mesh` grant is displayed as the explicit broad choice it
is, and a routing-level grant is never presented as spoof-resistant. Withheld notices show claimed
sender, authenticated origin/courier when available, kind, queue time, legacy drain state, and why
delivery was refused, not an uninspected "admit and fire" button. Replay is a second, explicit
action after pointer inspection, with per-sender batch selection for a large inspected backlog.
Suspension and revocation are visually distinct, and a stale view cannot offer a write.

## 5. Bootstrap and migration

1. **External bootstrap is independent and empty.** A new installation starts with only its local
   operator identity and `migration=pending`. No upstream example member, roster, hub grant, or
   courier grant is imported by default.
2. **Import is one-time and witnessed.** The operator selects entries from this checkout's
   `MEMBERS`, chooses `local_mesh` or narrow scope and an explicit `min_identity` for each, attaches
   evidence at the selected level, and confirms the resulting `member_mesh` generation. A
   routing-only or relay-only member may import with `lct: null`; no hidden per-member hub join is
   assumed. Choosing `reported` or `verified` for a member without its own hub LCT makes the
   canonical hub join an explicit migration prerequisite for that member. The file is an input to a
   review, never a live fallback; import does not mechanically create a recipient/kind
   cross-product.
3. **No silent broadening.** Until confirmation, existing installations keep their previous
   behavior. Activation sets `migration=complete`; from then on unknown senders default to withheld
   even if the import is empty or partial. Static `MEMBERS` is never read again for decisions.
4. **Aliases and non-template consumers are decisions, not inference.** `codex` and `codex-cli`,
   beings rendered by the SAGE heartbeat, relay couriers, and daemon-only kinds require explicit
   treatment. Absence from `MEMBERS` is not evidence of absence; observed senders are accusations
   for review, never auto-admitted.
5. **Legacy withheld notices are preserved without auto-replay.** Their starting state is an
   already-drained inbox row plus positive render-time withholding evidence, as defined in §2.4.
   Migration never treats `drained_at` alone as proof of withholding or reading. After inspection,
   the operator may replay one notice or a per-sender batch under the idempotency rules above.
6. **Migration is reversible only by a new witnessed decision.** A rollback restores a named prior
   `member_mesh` generation; it neither changes `scope/standing` nor deletes history or silently
   reactivates the static roster.

## 6. Failure and race behavior

- **Unknown sender:** withhold at the daemon admission point and emit a bounded, deduplicated
  operator observation with sender, kind, first/last seen, and count. Do not mint a chain entry or
  wake for every repeated notice.
- **Spoofed sender:** for a `verified` grant, refuse before any delivery and record the evidence
  mismatch, without telling the claimed member that it was admitted. A reported carrier or asserted
  `plugin_id` is not accepted as verified proof. A `routing` or `reported` grant records its weaker
  assurance instead of claiming that this spoof test ran.
- **Stale policy:** an external snapshot older than its stated expiry cannot authorize delivery. A
  failed authoritative vault read also withholds; local renderers never substitute a cached roster.
- **Revoke during delivery:** the second daemon preflight refuses; no fire or externally visible
  delivery is reported as success. If the outward act already won, report that honestly instead of
  claiming rollback.
- **Replay after restart:** receipts and grants reconstruct from the `member_mesh` document and
  witness history. A lost projection is repaired, never redelivered.
- **Forwarded notice:** a missing or unverified daemon-owned `authenticated_origin` cannot use an
  origin grant. Two authors relayed by one courier remain separate authorization cases, and a
  courier-only grant is never reported as origin authentication.

## 7. Acceptance evidence for the implementation slices

1. **Unauthorized administration:** member MCP, a different LCT, an expired operator session, and
   a filesystem-only caller cannot mutate policy. No member can admit or widen itself.
2. **Scoped delivery:** `local_mesh` reaches every local recipient and member-sendable kind but no
   daemon-only kind or remote recipient, including a seat added after grant issuance. Narrow
   recipient, kind prefix, MRH, and expiry are each enforced in both directions, including `review`
   versus `review_request` and a second seat receiving nothing. An expired narrow grant falls through
   to a live `local_mesh`; a suspended or revoked narrow grant does not.
3. **Identity and spoofing:** a `routing` grant admits its daemon-attributed matching label without
   hub proof and records that no spoof-resistance test applies. A `reported` grant requires matching
   reported evidence and never presents it as verified. For a `verified` grant, an asserted
   `plugin_id`, session `softLct`, or reported carrier without matching verified hub-LCT evidence is
   withheld even when a grant with that label exists. Before local signing exists, a verified local
   grant cannot activate; routing and reported local delivery do not inherit that blocker. Every
   receipt exposes the required/observed levels and same-UID custody boundary rather than claiming
   unique key ownership.
4. **Revocation race:** admission succeeds, revocation lands between the two daemon preflights, and
   no notice fires. A completed act is reported `revoked_after_fire`, never rolled back in prose.
5. **Stale policy:** an expired external snapshot, stale grant, and failed vault read each withhold
   rather than falling back to `MEMBERS`.
6. **Replay:** admission does not replay automatically; a newly withheld row has `withheld_at` and
   no `drained_at`; the first explicit replay delivers once and sets the delivery mark; single and
   per-sender batch retries, watcher polls, and daemon restart create no duplicate delivery, moved
   mark, or response debt.
7. **External independence:** a fresh instance imports nothing by default, and two instances with
   different operator keys and grants cannot broaden one another.
8. **Migration:** old documents load as `migration=pending`; explicit import produces the expected
   `member_mesh` generation and no unselected identity is admitted. A relay-only routing identity
   imports with `lct: null`, while selecting reported/verified without an existing hub LCT surfaces
   the canonical join prerequisite. `MEMBERS` changes afterwards have no effect. Legacy fixtures
   prove that an already-drained, positively withheld row migrates without losing its old mark,
   while a bare drained row is not guessed to be withheld.
9. **Daemon-wide live acceptance:** fire templates, CLI, and the SAGE heartbeat all receive the same
   daemon admission decision, with no local propagation delay and no renderer-side authority fork.
   A revoke through each consumer's final preflight behaves identically. Any daemon-external
   snapshot consumer has a separately measured propagation bound; store-only tests are insufficient.
10. **Relay origin:** two originating authors behind one courier are independently granted and
    withheld. Missing, mismatched, or caller-asserted origin evidence cannot inherit either the
    courier's grant or another author's grant.

## 8. Slices after this PRD

1. **Backend:** separate `member_mesh` schema/generation, vault transaction/witness, routing and
   reported admission with explicit grant receipts, daemon drain/peek admission and final preflight,
   verified relay-origin fields, withheld/replay stores, and the applicable tests above.
2. **Verified local identity:** the #824 local proof-of-possession path and activation of verified
   local grants. This is a separate dependency, not a reason to block routing-level admission-lag
   repair or to describe reported evidence as verified.
3. **Console and CLI/API:** operator workflows, required/observed identity and custody visibility,
   origin/courier visibility, reason/provenance display, inspected batch replay, and the same
   authorization tests through every mutation surface.
4. **Migration and external smoke:** one-time import, explicit hub-join prerequisites where selected,
   legacy already-drained backlog migration, external independence, daemon-external snapshot
   propagation, replay/idempotency, and removal of routine `MEMBERS` edits.

Each slice keeps the previous behavior until its explicit migration switch is activated. No slice
claims external-release readiness without the external smoke and live acceptance evidence.

## 9. Design decisions after the reviews

- **Operator-only administration initially:** confirmed, with a stored path to a peer-required tier.
- **Grant breadth:** revised from narrow-only to one explicit `local_mesh` scope plus optional narrow
  grants. General wildcard, role, and cross-host grants remain outside the first backend slice.
- **Identity assurance:** revised from a global verified-proof precondition to operator-selected
  `routing | reported | verified` per grant. Verified local delivery depends on #824; weaker levels
  remain visible and cannot claim spoof resistance. Relay-only members can import at routing level
  without a hidden hub-join prerequisite.
- **Withheld delivery state:** new withheld rows receive `withheld_at`, never `drained_at`; first
  delivery or replay sets `drained_at`, while legacy drain evidence remains separately labelled.
- **Expiry precedence:** an expired narrow grant falls through to a less-specific live grant;
  suspension and revocation remain overriding tombstones.
- **Replay:** confirmed as manual and inspected, now including idempotent per-sender batches so a
  large backlog does not recreate the per-notice administrative bottleneck.
- **Policy storage and generation:** revised from a `scope/standing` object to a separate
  vault-backed `member_mesh` document and generation, using the #1030 witness/finality pattern.
- **Suspension/revocation:** confirmed as tombstones; a completed outward act is never described as
  rolled back.

The implementation must preserve the reviews' additional constraints: no invented third member key,
no renderer-side authority fork, no origin inferred from a courier, and no claim that a legacy
withheld notice was undrained. Reviewer confirmation is requested on the per-grant identity levels,
withheld/drained state split, and expiry precedence before the backend slice starts.
