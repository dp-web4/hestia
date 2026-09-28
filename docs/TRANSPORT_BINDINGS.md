# Transport bindings

Status: phase A of #1030, merged in #1031, deployed on CBP 2026-09-15 as `v0.0.4-816-g667b932`. This page is the operator runbook. The design, the measurements behind it and the falsifiers are in #1030.

## What a binding is

A member's routed notice (`hestia_member_notify` to `peer/member`) is queued on this box and forwarded later by a drain. On the hub, the forwarded notice is signed with the key of some hub member. Until #1031 nothing in hestia said which one.

On CBP, Legion and McNugget the drain signed a being's notices with the **seat's** key. It did this whenever the being had no identity file of its own. Replies follow the signer, so answers to the being landed in the seat's mailbox. The being never saw them and kept re-asking (92 asks in 30 hours on CBP).

A binding records four roles that are allowed to differ, but must be stated:

| role | meaning |
|---|---|
| actor | the member that sent (`member`) |
| relay | the local drain that moves the row (recorded as `forwarded_by`) |
| carrier | the hub member whose key signs (`carrier_lct`) |
| reply_to | the identity the answer belongs to (`reply_to_lct`; not yet routed on, see phase C) |

Modes:

| mode | carrier | use it when |
|---|---|---|
| `direct_required` | none | the member must sign as itself and has no hub identity on this host yet. Routed sends are **refused in the member's own turn**: no row is queued and nothing reaches the hub. Local notices still work. |
| `direct` | the member's own hub LCT | the member holds its own identity file (`~/.config/hub-mesh-<member>` env file) |
| `relay` | another hub member's LCT, plus `delegation_ref` | a seat or courier signs on the member's behalf, deliberately and on record |

A member with no binding is **unbound**. Its sends are forwarded as before, but the send receipt and the chain both say `transport: "unbound"`, and the receipt warns that replies may not come back.

Only the wildcard hub `*` is accepted in this phase. The send path does not yet know which hub a row leaves through, so a binding scoped to one hub would be stored and never enforced.

## Who can write one

Only the operator, through `POST /api/transport/binding` behind the operator gate. Every write is witnessed as intent, persisted to the vault, then witnessed as done, and rolled back if that last step fails.

Members can read their own binding with the MCP tool `hestia_transport_binding`. There is no member write path: a member that picks its own carrier picks whose name its acts travel under.

## Runbook

### 0. Deploy

The daemon must be at or after #1031. The deploy timer picks up `main` every four hours; to deploy now:

    systemctl --user start hestia-deploy.service
    journalctl --user -u hestia-deploy.service -n 10 --no-pager    # "daemon up on v…"

The drain must also understand stamps. That is SAGE #97 for SAGE beings; hub-watch for seats. An older SAGE drain against a **bound** member does not resend in a loop: it omits `carrier_lct`, so the daemon retires the row as `carrier-unreported` and tells the author. It will not forward successfully until the drain is updated, so update the drain before binding a member `direct` or `relay`. `direct_required` needs no drain change, because nothing is queued.

### 1. Look

    HESTIA_HOME=~/.hestia python3 tools/transport_binding.py list

### 2. Stop a being's sends leaving under the seat's key

    HESTIA_HOME=~/.hestia python3 tools/transport_binding.py set cbp-being direct_required \
        --reason "no hub identity on this host yet; its asks were seat-signed (#1030)"
    # read the plan, then repeat with --apply

The tool prints its plan, sends only with `--apply`, and reads the store back to confirm the effect.

From the next beat, the being's `mesh` and `peer_ask` to other machines return `hestia.member_notify_transport_unmet` in its own turn. That is the intended state until step 3.

### 3. Give it its own identity, then bind it direct

1. Create the being's hub member, using the canonical join process for `<machine>-sage` names. Write its identity file with `CHANNEL_CLIENT`, `HUB_URL`, `MY_LCT`, `MY_KEYPAIR` and `HUB_MESH_STATE`.
2. Check what the file actually signs as. SAGE #97 resolves the signer by sourcing the file, just as `hub-notify.sh` does, so check it the same way:

       bash -c 'source "$1"; echo "$MY_LCT"' _ <path to the being's identity file>

3. Bind it:

       HESTIA_HOME=~/.hestia python3 tools/transport_binding.py set cbp-being direct \
           --carrier <that LCT> --reply-to <that LCT> --reason "cbp-sage identity file written" --apply

### 4. A deliberate relay

    HESTIA_HOME=~/.hestia python3 tools/transport_binding.py set legion-being relay \
        --carrier <seat hub LCT> --delegation "<ruling/issue/note that authorises it>" \
        --reason "..." --apply

Replies still follow the carrier until phase C.

### 5. Undo

    HESTIA_HOME=~/.hestia python3 tools/transport_binding.py remove cbp-being --reason "..." --apply

The member returns to unbound. Rows it queued under the removed binding are failed back to it at the next drain, never relabelled.

## Reading what happened

On the chain:

| event | meaning |
|---|---|
| `transport_binding_intent` / `transport_binding_set` | an operator write, before and after persistence |
| `transport_binding_remove_intent` / `transport_binding_removed` | an operator removal |
| `member_notice` with `transport` | the send, carrying the stamp or `"unbound"` |
| `member_notice_refused` `reason: transport_binding_unmet` | a `direct_required` member tried a routed send |
| `egress_forwarded` | a forward. `forwarded_by` is the drain; `carrier_lct` and `carrier_proof: "reported"` are what the drain said signed, with `binding_version` and `hub_receipt` |
| `egress_transport_stale` | the member's binding changed while the row waited; failed before any send |
| `egress_carrier_mismatch` | the drain reported a carrier other than the stamped one; not a success |
| `egress_carrier_unreported` | the drain sent a bound row without saying who signed; not a success |
| `egress_carrier_unavailable` | the drain holds no key for the stamped carrier and sent nothing |

Each of the last four is written **before** the row leaves the queue. The row's retirement and the author's report commit together. If a fault witness exists while its row is still pending, a store write failed; the next drain pass judges the row again.

None of these writes `member_notice_unreachable`, which is a claim about the peer.

In the author's inbox, a daemon `unreachable` notice's pointer names the fault: `hestia://egress/<id>#transport-stale:<peer>/<member>`, and likewise `#carrier-mismatch`, `#carrier-unreported` and `#carrier-unavailable`.

## Not done yet

- **Phase B:** `carrier_proof` is `"reported"`. A dishonest drain can still name the right carrier. Proof against the hub's ledger is next.
- **Phase C:** replies are still routed by the envelope signer, not `reply_to`. A being bound `direct` gets answers only if its own hub mailbox is drained.
- **Phase D:** destinations are still addressed by name, not resolved to an immutable LCT.
