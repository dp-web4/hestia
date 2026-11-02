# 13 handlers can change governed state with no record of it

> **Status 2026-09-29: fixed.** `orchestrator_connect` in PR 1164; the other 12 (and a sibling the
> `let _` sweep missed, `policy_instance_grant`, which kept a failed append as an empty hash) in the
> class-A PR, each with an injected-failure test. `tools/discarded_chain_records_test.py` is the
> ratchet. Classes B–D are unchanged, deliberately (see below).

**Found:** 2026-09-27, by hub-claude, building the app's gate-integrity surface on
`POST /api/gates/ratify` and then checking whether the defect found there was local.
**Related:** the ratify fix (PR `hub/gate-integrity-surface`, `apply_ratification`), the RWOA
self-audit in `CLAUDE.md` (clause **A**), `operator_gate_escalation` (the sibling that does it right).

## The shape

```rust
do_the_act()?;                                   // vault write / hook install / law edit
let _ = s.append_chain("event", record);         // result discarded
Ok(success)
```

If the append fails, the act stands and nothing records it: no who, no why, no evidence. RWOA
clause A — *the act, its stakes assessment, and the evidence relied upon commit together in the
signed hash-chained record* — is violated exactly when it matters, and each of these handlers'
own accountability blocks claims `A: pass`.

The correct order already exists in the codebase. `operator_gate_escalation` decides, appends,
and on a failed append calls `undo_decide` and returns 500. `agent_retire` / `agent_reinstate`
witness their intent **before** acting. `gates_ratify` now installs, records, and restores the
previous expectations if the record fails.

## The sweep — `let _ = <state>.append_chain(` in `core/src/server/`

33 sites. Classified by what is lost when the append fails.

### A. Consequential acts that complete unrecorded — 13

| handler | event | the act |
|---|---|---|
| `vci_credential` | `credential_issued` | **issues a credential** |
| `policy_set_preset` | `policy_edit` | changes the law |
| `policy_set_override` | `policy_edit` | changes the law |
| `policy_clear_override` | `policy_edit` | changes the law |
| `policy_upsert_rule` | `policy_edit` | changes the law |
| `policy_delete_rule` | `policy_edit` | changes the law |
| `policy_revoke_instance_grant` | `policy_instance_grant_revoked` | revokes a grant |
| `config_seed_seats` | `config_seeded` | writes every seat's config |
| `config_put_seat` | `config_seat_written` | writes a seat's config |
| `orchestrator_connect` | `orchestrator_connect` | installs governance hooks |
| `agent_ungovern` | `agent_ungovern` | **removes an agent's gate** — and takes no reason |
| `tool_vault_get` | `vault_get` | **reads a secret** (a consequential act per `CLAUDE.md`) |
| `bootstrap_operator_if_genesis` | `operator_bootstrap` | mints the genesis operator |

`gates_ratify` was a fourteenth; fixed in the gate-integrity PR.

### B. Records of a refusal or failure — lost audit, no unwitnessed act — 11

`gate_escalation_refused` ×4, `gate_escalation_arbiter_refused`, `policy_unevaluable`,
`config_seed_failed`, `deployment_update_publish_failed` ×2, `deployment_update_trigger_failed`,
`retired_member_connected` (an observation that a retired id acted).

### C. Observations — 6

`operator_session_opened`, `operator_gate`, `config_seat_inspected`,
`deployment_update_triggered`, `egress_forwarded`, `scope_attestation`.

### D. Per-call gate decisions — a design question, not a defect — 2

`policy_decision` in `tool_query_policy` and `gate_direct_tool`. These run on every governed tool
call. Failing the call on a chain error would make a chain outage a governance outage for every
member at once; best-effort may be the right call here. It should be a stated choice rather than
an inherited `let _`.

(`tool_query_policy` also discards `scope_attestation` and `policy_unevaluable`, counted above.)

## What the fix looks like

Not one pattern for all 13, because the side effects differ:

- **vault-backed state** (law edits, config writes, grant revocation, credential issuance, genesis):
  take the previous value, write, append; on a failed append restore the previous value and
  return 500. The `apply_ratification` shape.
- **filesystem side effects** (`orchestrator_connect`, `agent_ungovern`): witness the intent
  **first**, as `agent_retire` does — a hook install cannot always be cleanly undone, so the record
  must precede it. `agent_ungovern` should also require a reason: it is the one route that removes
  enforcement, and it asks for less justification than approving an escalation does.
- **reads** (`vault_get`): witness before releasing the value; if the record cannot be written,
  do not release.

## What this is not

- Not evidence that any record was actually lost. The chain store rarely fails; this is about what
  happens when it does, which is when the record matters most.
- Not a patch. Most of these routes belong to other members' work. This PR is the finding; the
  gate-integrity PR fixes the one route this seat built on. The app will not offer a control over
  `agent_ungovern` until its record is reliable and it takes a reason.
