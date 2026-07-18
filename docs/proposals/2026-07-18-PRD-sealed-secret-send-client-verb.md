# PRD: Sealed-Secret-Send — the missing send-side client verb

**Status:** PRD for **Legion** (implementer) · dp-requested 2026-07-18 · author CBP (Claude Fable 5)
**Owner:** Legion (gate/membrane + prior sealed-channel client work). HUB consulted on the hub-side
mailbox/registry seam.
**Thread:** `hestia-role-orchestration` / sealed-channel.
**Motivation:** dogfood — dp asked to send a Kaggle auth token CBP→Thor over the sealed channel. Audit
found the **receive half is live and correctly law-gated, but there is no send-side client verb** to
push a recipient-sealed secret. This PRD cuts that last gear. The Kaggle token is the intended
low-consequence first production payload *after* a dummy proves the path.

## 1. The gap (audited state, 2026-07-18)

**Built and correct — do NOT rebuild:**
- **Recipient-sealed bodies** are a delivery primitive on the daemon's `SealedNotice` mailbox
  envelope (`web4/hub/hub-lib/src/events.rs` — "recipient-sealed body is a delivery concern carried on
  the mailbox envelope, never duplicated onto the act").
- **`hestia_inbox`** drains sealed notices, opens each with the member identity keypair, and is
  **law-gated `credential_access` under spec §7.8.2 "deliver only to the authenticated LCT"**
  (`hestia/core/src/server/handler.rs` ~1133). It correctly denies the unattended `mesh-worker` /
  `autonomous-timer` roles by ratified law, and a denied drain leaves the mailbox bit-identical (O).
- **Sealing primitives** exist: `hestia/core/src/hub.rs` — `seal_request`, `open_response`,
  `open_notification`, `seal_ack`.

**Missing — this PRD:**
- **No send-side client verb** constructs a recipient-sealed body and pushes it. `hub-notify.sh` emits
  only `referenced_act` (a pointer: URI + content-hash — which for a secret would just relocate it into
  git). `KINDS` has no `secret`/sealed-body kind. Nothing seals a payload *to a peer's key* and sends it.

## 2. Goal / non-goals

**Goal:** a client verb — `hub-sendsecret <peer> <payload>` (or a `channel_client` tool + a
`hub-notify` sibling) — that seals an arbitrary small secret to the **recipient LCT's** key, wraps it
as a `SealedNotice`, and delivers it to the peer's hub mailbox, such that only that peer's authenticated
identity can open it via `hestia_inbox`. The secret never touches git, a pointer, or plaintext transport.

**Non-goals:** rebuilding the mailbox/transport/receive/law-gate (all exist); a general large-file
transfer (secrets are small — cap e.g. 8 KB); key management beyond using the already-pinned member keys.

## 3. Functional requirements

1. **Seal to the recipient, not the hub.** The payload is encrypted to the **recipient's** sealing
   public key (resolved from the hub member registry / roster — the same pinned-key source
   `hub-notify` uses for LCT resolution). Confirm whether the existing `seal_*` primitives seal to an
   arbitrary peer pubkey or only to the hub; if only-hub, add `seal_to_peer(recipient_pubkey, body)`.
   *(Open crypto detail for Legion: Ed25519 identity vs X25519 sealing key — derive or require an
   X25519 key per member.)*
2. **New kind `secret`** added to `private-context/hub-mesh/KINDS` (single source; both send gate and
   `hub-watch` receive allowlist read it — do not edit the scripts). Without this, the drain is
   consume-once and would silently destroy the notice (the 2026-07-15 drop incident).
3. **Delivery as `SealedNotice`.** The sealed body rides the mailbox envelope, not a `referenced_act`
   pointer and not the act/ledger payload. `hestia_inbox` already drains + opens it — verify unchanged.
4. **Receive-side surfacing.** Because §7.8.2 denies unattended roles, the recipient must drain from an
   **attended/interactive** identity session. Specify how Thor's operator/interactive agent is prompted
   to drain (a `hub-watch` variant that, for kind=`secret`, notifies "sealed secret waiting — drain
   interactively" rather than auto-firing an unattended worker that would be denied).
5. **Sender ergonomics.** `hub-sendsecret thor <token>` — reads payload from stdin or a file path (never
   an argv that lands in shell history), resolves Thor's LCT + sealing key, seals, sends, prints the
   delivery ACK (`ackSealed`) + ledger index. No plaintext echo.

## 4. Security requirements — RWOA self-audit (this IS a secret-release surface)

```
surface: hub-sendsecret (send)    act: deliver a secret sealed to a peer LCT
S: high / irreversible  [construct: a leaked/mis-sent secret has no undo — must be rotated; V applies]
R: n/a (send side; reachability not the basis)   W: pass [construct: sender signs with pinned member key; recipient resolved from pinned registry key — seal to that key only]
O: pass [construct: seal + resolve BEFORE send; a failed seal/unknown-key/unauth recipient must DENY, never fall back to plaintext or pointer]
A: pass [construct: the delivery ACT is witnessed on the ledger with a content-HASH only — never the payload; the sealed body lives only on the mailbox envelope]
V: present [construct: high-stakes send should require attended/authorized sender role — mirror operator_auth's secret-release V veto; unattended roles deny]
verdict: PASS if the above hold; the receive side is already §7.8.2-gated (deliver-only-to-authenticated-LCT).
```

Hard rules: **never** fall back to the pointer path for a `secret` kind (that relocates the secret into
git). **Never** log/echo the payload. Fail-closed on any seal/resolve/auth failure. Sender must be an
attended/authorized role (not `mesh-worker`/`timer`).

## 5. Test plan (dogfood, in order)

1. **Dummy first.** `hub-sendsecret thor "DUMMY-not-a-secret-<ts>"` from CBP. Thor drains via
   `hestia_inbox` (interactive), opens it, content matches. **Grep git + the hub store + logs — the
   dummy must appear NOWHERE in plaintext.**
2. **Negative gates.** An unattended `mesh-worker` drain is DENIED (§7.8.2). A wrong-LCT open fails.
   Omitting the `KINDS` entry drops the notice (confirms the vocabulary wiring).
3. **Real payload.** Only after 1–2 pass: CBP sends the **Kaggle token** to Thor as the first real
   secret. Thor provisions its `~/.kaggle/kaggle.json` from the drained body. Rotate-on-doubt available
   since Kaggle is low-consequence — the deliberate choice of first artifact.

## 6. Acceptance criteria

- `hub-sendsecret <peer> <payload>` seals to the peer's key, delivers via `SealedNotice`, prints ACK.
- Only the peer's authenticated identity opens it; unattended roles denied; wrong LCT fails.
- Payload never in git / pointers / logs / ledger (hash-only on the ledger).
- `secret` kind in `KINDS`; receive path surfaces it for interactive drain.
- Dummy dogfood green before any real secret; Kaggle token delivered CBP→Thor as the closing test.

## 7. Why Legion

Legion owns the gate/membrane, did the OQ1 fail-open/fail-closed analysis and the first sealed-channel
client (CBP→hub `find_members`), and reviewed the `path_scope` gate — this is the send-side sibling of
the receive gate it already reasons about. HUB owns the hub-side mailbox/registry; coordinate there if
`SealedNotice` acceptance or the peer-sealing-key surface needs a hub change. CBP is the send-side
first caller and will run the dogfood. — for dp
