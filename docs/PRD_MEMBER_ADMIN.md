# PRD — governed member-mesh administration

**Status:** proposed design for review, not implemented and not an enforcement claim.
**Tracker:** #1332. This is slice 1 of the issue's implementation plan.
**Read with:** `PRD_ALLOWLISTS.md`, `PRD_APP_GOVERNING_SURFACES.md`,
`PRD_DISPOSITION_DELIVERY.md`, and `plugins/member-mesh/KINDS.md`.

## 0. The decision this design makes

Membership in `plugins/member-mesh/MEMBERS` currently means three different things: a claimed
`plugin_id`, permission to deliver a notice, and distribution of that permission to each receiving
seat. They must become separate objects.

1. **Identity** is a key-bound LCT and its witnessed evidence. A caller-supplied `plugin_id` is a
   routing label, never identity proof (#63/#128).
2. **Authority** is an operator-granted, narrowly scoped sender grant. Knowing an LCT does not
   entitle its holder to deliver anything.
3. **Distribution** is one daemon-owned, vault-backed policy generation consumed by every delivery
   path. A Git checkout, fire template, primer, or hub transport is never a second authority.

The receiving operator controls admission. An upstream repository, sender, hub, or identity proof
cannot grant itself delivery.

## 1. What exists, and what must not be reused as a shortcut

- `MEMBERS` feeds the fire templates' sender allowlists. Unknown senders are announced and
  withheld; `ack` is terminal; `review_request` and `reply` carry response obligations; kind
  specializations are prefix paths, not new roots.
- `("hestia", "unreachable")` and `("hestia", "disposition")` are admitted specially because only
  the daemon can mint those kinds. They are not ordinary member identities and cannot be admitted
  through the new grant editor.
- `PolicyList` supplies vault-backed schema, bindings, and permissions, but its own module says the
  lists are not yet enforced. This PRD must not present a `PolicyList` edit as a delivery control.
- The daemon already has an operator LCT challenge/session channel, a witness chain, vault-held
  policy, notice storage, and a `drained_at` delivery mark. These are the reuse points.
- A `drained_at` mark is not proof that a person read or accepted a notice. It must not be used as
  an admission or replay decision by itself.

## 2. Terms and stored objects

### 2.1 Member identity

```jsonc
{
  "lct": "lct:web4:member:<canonical-id>",
  "member_id": "claude-code",             // stable routing label, not evidence
  "public_key": "<ed25519-key>",
  "evidence_hash": "<witnessed-registration-or-attestation>",
  "status": "known | suspended | revoked",
  "reason": "<operator-supplied text>",
  "updated_at": "<rfc3339>"
}
```

An LCT and a `member_id` are separate keys. A second LCT claiming an occupied `member_id`, or a
second `member_id` claiming an occupied LCT, is a conflict, not an alias. `codex` and `codex-cli`
remain distinct grant targets until an operator explicitly maps them to one LCT; migration must not
collapse them by string similarity.

### 2.2 Sender grant

```jsonc
{
  "grant_id": "<uuid>",
  "member_lct": "lct:web4:member:<canonical-id>",
  "recipient": "kimi-code",              // no wildcard in the initial implementation
  "kind": "review_request",             // prefix path, matching kind_under's rule
  "mrh": { "paths": [], "repos": [], "hosts": ["local"] },
  "not_before": "<rfc3339>",
  "expires_at": null,                    // null means no calendar expiry, never a stale snapshot
  "reason": "<required operator rationale>",
  "origin": "operator-edit | migration | escalation",
  "generation": 42
}
```

The initial value space is deliberately small: one LCT, one recipient, one kind prefix, local MRH.
There is no `*`, no role grant, and no recipient-group expansion. Those need separate evidence and
review. `kind` accepts the same non-empty lowercase segments and 64-byte bound as the daemon's
existing `kind_under`; `review` matches `review` and `review.done`, never `review_request`.

### 2.3 Policy document and generation

Add a `member_mesh` object to the existing vault-backed standing-policy document, not a sibling
admin database or a file editable by members. The existing document's monotonic `generation`
increases on every mutation and only on a real mutation. An empty or pre-schema document has no
`member_mesh` object and is in **migration pending** state, never migration-complete.

The daemon projects an immutable read snapshot `{generation, snapshot_expires_at, grants,
identities}`. Every fire template, CLI reader, and future transport receives that snapshot through
the same policy-fetch path. There is no direct-file fallback, environment override, or hub mirror
that can outrank it. Snapshot fetch failure withholds delivery; it does not fall back to `MEMBERS`.

Every mutation writes the policy update and its `member_mesh_policy_changed` witness entry with
actor, authority, reason, previous/new value, and generation in one vault transaction. A failed
witness rolls the mutation back. A failed delivery projection is repaired from the committed
policy; no cross-store atomicity is claimed.

### 2.4 Withheld notice and replay receipt

A withheld notice keeps its original `notice_id`, claimed sender, kind, pointer, queue time, and
routing data. Its lifecycle is `withheld -> eligible -> replayed | expired | rejected`.
`eligible` requires a matching live grant; it does not assert that the original sender was proven.

A replay receipt records `{notice_id, recipient, grant_id, replay_generation, replayed_at,
replayed_by}` with uniqueness on `(notice_id, recipient)`. A replayed notice is a projection of the
original with `replay_of=notice_id`, not a new sender act and not a second original notice.

## 3. Decision rules

1. **Default deny.** No matching live grant means withheld, with an operator-visible reason.
2. **Identity is required, not sufficient.** A grant can only name a witnessed LCT. The delivery
   path separately verifies that the current act is bound to that LCT; `plugin_id` alone never
   satisfies it. Spoofed labels, role substitution, and forwarding do not inherit authority.
3. **Most specific live grant decides.** An exact LCT + recipient + kind-prefix + MRH grant is
   required. Suspension or revocation at any matching scope wins over admission. Expiry is checked
   at decision time, not at snapshot publication.
4. **Preflight dominates effects.** Authority is evaluated before sanitization, file creation, or
   fire. It is evaluated again immediately before the outward act. If revocation lands between
   those checks, nothing fires.
5. **Revocation is a tombstone, not deletion.** The previous grant and its witness history remain
   inspectable. Already running CLI sessions are not claimed to stop retroactively; the outcome is
   recorded as `revoked_after_fire` if revocation landed after the final preflight.
6. **Admission is not replay.** Admission creates eligibility only. Withheld content requires a
   separate operator replay act after the pointer has been inspected outside a model prompt.
7. **Replay is idempotent.** A duplicate replay, watcher retry, restart, or daemon recovery cannot
   create a second delivered copy. Replayed content does not reset `drained_at`, answer bindings,
   or `in_reply_to`; it must not manufacture a second open review debt.
8. **Daemon kinds are structural.** `unreachable` and `disposition` remain admitted only by their
   daemon-minting construction, never by a member-editable sender grant.

## 4. Administration surfaces

### 4.1 Authority

All mutations use the daemon's authenticated operator LCT challenge/session channel. There is no
member-reachable MCP mutation, no `MEMBERS` write API, and no sender self-admission. The daemon's
web console, the app, and the CLI call the same endpoints and see the same generation; the strong
channel is named in every receipt. Filesystem access to `HESTIA_HOME` is not presented as the
strong operator channel.

The initial administration tier is **operator-only**. A future peer-required tier can be raised by
policy, but lowering a tier must satisfy the tier being lowered from. Migration's first grant
cannot be approved by the member being admitted.

### 4.2 API and CLI

| operation | surface |
|---|---|
| list identities, grants, withheld notices, replay receipts | `GET /api/member-admin/state` |
| inspect one identity/grant and its provenance | `GET /api/member-admin/grants/{grant_id}` |
| register an identity or issue a grant | `POST /api/member-admin/grants` |
| narrow an existing grant | `POST /api/member-admin/grants/{grant_id}/narrow` |
| suspend temporarily | `POST /api/member-admin/grants/{grant_id}/suspend` |
| revoke permanently | `POST /api/member-admin/grants/{grant_id}/revoke` |
| replay one eligible withheld notice | `POST /api/member-admin/withheld/{notice_id}/replay` |

The CLI equivalents are `hestia member admin list|show|grant|narrow|suspend|revoke|replay`.
Every write returns the actual daemon result and new generation. There is no optimistic local
success. Every editor re-reads before offering an edit and again after acting. A narrowing cannot
widen recipient, kind, MRH, identity, or expiry; create a new grant for those changes.

Read-only views may expose an LCT's effective grants to that member. Withheld pointers and other
members' policy details remain operator-only. A read API never returns private key material or
secret-bearing notice content.

### 4.3 Console

The member-administration view shows identity evidence separately from delivery authority, current
generation, grant scope, expiry, provenance, and reason. Withheld notices show sender, kind, queue
time, and why delivery was refused, not an uninspected "admit and fire" button. Replay is a second,
explicit action after pointer inspection. Suspension and revocation are visually distinct, and a
stale view cannot offer a write.

## 5. Bootstrap and migration

1. **External bootstrap is independent and empty.** A new installation starts with only its local
   operator identity and `migration=pending`. No upstream example member, roster, or hub grant is
   imported by default.
2. **Import is one-time and witnessed.** The operator selects entries from this checkout's
   `MEMBERS`, attaches verified LCT evidence to each, chooses recipient/kind scope, and confirms the
   resulting generation. The file is an input to a review, never a live fallback.
3. **No silent broadening.** Until confirmation, existing installations keep their previous
   behavior. Activation sets `migration=complete`; from then on unknown senders default to withheld
   even if the import is empty or partial. Static `MEMBERS` is never read again for decisions.
4. **Aliases are decisions, not inference.** `codex` and `codex-cli`, beings without fire templates,
   and daemon-only kinds require explicit rows. Absence from `MEMBERS` is not evidence of absence;
   observed senders are accusations for review, never auto-admitted.
5. **Queued notices are preserved without auto-replay.** Admission after import changes only future
   eligibility. The operator replays selected withheld notices under the idempotency rules above.
6. **Migration is reversible only by a new witnessed decision.** A rollback restores a named prior
   generation; it does not delete the history or silently reactivate the static roster.

## 6. Failure and race behavior

- **Unknown sender:** withhold and emit a bounded, deduplicated operator observation with sender,
  kind, first/last seen, and count. Do not mint a chain entry or wake for every repeated notice.
- **Spoofed sender:** refuse before any delivery and record the evidence mismatch, without telling
  the claimed member that it was admitted.
- **Stale policy:** a snapshot older than its stated expiry cannot authorize delivery.
- **Revoke during delivery:** the second preflight refuses; no partial primer or fire is reported
  as success. If the outward act already won, report that honestly instead of claiming rollback.
- **Replay after restart:** receipts and grants reconstruct from vault and witness history. A lost
  projection is repaired, never redelivered.
- **Forwarded notice:** authority is checked against the originating sender and original notice;
  the forwarder cannot upgrade it.

## 7. Acceptance evidence for the implementation slices

1. **Unauthorized administration:** member MCP, a different LCT, an expired operator session, and
   a filesystem-only caller cannot mutate policy. No member can admit or widen itself.
2. **Scoped delivery:** recipient, kind prefix, MRH, and expiry are each enforced in both
   directions, including `review` versus `review_request` and a second seat receiving nothing.
3. **Spoofing:** an asserted `plugin_id` without matching LCT evidence is withheld even when a grant
   with that label exists.
4. **Revocation race:** admission succeeds, revocation lands between the two preflights, and no
   notice fires. A completed act is reported `revoked_after_fire`, never rolled back in prose.
5. **Stale policy:** an expired snapshot, stale grant, and failed vault read each withhold rather
   than falling back to `MEMBERS`.
6. **Replay:** admission does not replay automatically; the first explicit replay delivers once;
   retries, watcher polls, and daemon restart create no duplicate delivery or response debt.
7. **External independence:** a fresh instance imports nothing by default, and two instances with
   different operator keys and grants cannot broaden one another.
8. **Migration:** old documents load as `migration=pending`; explicit import produces the expected
   generation and no unselected identity is admitted. `MEMBERS` changes afterwards have no effect.
9. **Live acceptance:** all supported harnesses enforce the same grant, with a measured propagation
   bound from mutation to every delivery path. No claim is made from store-only tests alone.

## 8. Slices after this PRD

1. **Backend:** schema migration, vault transaction/witness, policy snapshots, authorization,
   delivery preflights, withheld/replay stores, and the tests above.
2. **Console and CLI/API:** operator workflows, visibility, reason/provenance display, and the same
   authorization tests through every mutation surface.
3. **Migration and external smoke:** one-time import, external independence, measured propagation,
   replay/idempotency, and removal of routine `MEMBERS` edits.

Each slice keeps the previous behavior until its explicit migration switch is activated. No slice
claims external-release readiness without the external smoke and live acceptance evidence.

## 9. Design decisions requested from reviewers

- Confirm operator-only administration initially, with a stored path to a peer-required tier.
- Confirm no wildcards or role grants in the first backend slice.
- Confirm manual, inspected replay rather than replay-on-admission.
- Confirm one shared standing-policy generation, with `MEMBERS` used only during explicit migration.
- Confirm that revocation and suspension are tombstones and that a completed outward act is never
  described as rolled back.

These are review questions, not silent defaults. If any is rejected, the corresponding data model
and acceptance tests must change before the backend slice starts.
