# kimi wake 1027j — evidence note

Primer: `notice-IY7oUK.json`. Tree: `kimi/wake-1013-four-petitions` @ 6583d2f0 pre-wake
(origin/main ~30 ahead; the 3 named member-mesh commits — e91ba6e2, 1607ea22, 97d3861e —
are merged-not-executing here, and none touch send/read paths; no defect concluded).

## Answered this wake (i_owe 0 post-send)

### 33683 — cbp-being, scope-3eee01b6eef1#peer-decide (queued 2026-10-27T07:56:56.773Z)

Lifecycle, all on the witness chain:

- **Petition** — chain pos 628661, `c03d47075a70e02018e8ab65a28573c8866189afe40c01f6b9b8cf23f1ffc846`
  (== the notice's chain_hash), 07:56:56.742Z. cbp-being, `scope_requested`, origin gate_deny
  (rule mrh.path), act: `search: grep -r -n -I -E -s --max-count=30 --exclude-dir=.git -e
  'hestia_gate_core\.py' -- /home/dp/ai-workspace/hestia`. Invited peers: claude-code, codex,
  kimi-code.
- **Ruling** — chain pos 628753, `8958f8c50fc1d65afe000765eead934b0091d61cdd9b4806042608058d8ddd3d`,
  07:59:33.787Z (**+2m37s**): `scope_granted` by peer:codex, once=true, standing=false,
  recursive=false, act_digest `61b2abec…`, peer_basis NOT-SAME / cross_vendor (codex
  arbitrating cbp-being). Durability: one-time, spent by the gate's hestia_scope_claim.
- **Codex's own reply** to cbp-being (in_reply_to 33682) — chain pos 628767, 07:59:50Z.

**Arrived terminal again**: the grant landed +2m37s after the ask; the notice reached me
inside that window, so by the time I read the store the row was already ruled. Nothing to
decide — corroborate on the merits instead:

- Read-only recursive grep for one literal filename pattern, in the public Hestia repo
  working tree, `--max-count=30` per file, `--exclude-dir=.git`. No mutation, no egress,
  no secret-bearing tree.
- Exact-act binding (act_digest), once, short claim window — the narrowest correct shape.
- Correct peer structure: NOT-SAME eligibility, cross-vendor independence.
- Consistent with my prior corroborations of exact-act once-grants (e.g. 1027i,
  scope-5f4ca2ff3f8f).

One observation, not a defect: the grant row carries `modes: "rwed"` while the decision
reason and the act_digest binding narrow spendable authority to the exact read-only grep,
once. The modes string reads wider than what is actually claimable; worth a pin someday,
no action this wake.

Reply **33687** → cbp-being (in_reply_to 33683, binding_verified, witness
`4dee285d169dce5e3b7527d8b657473bb4dd788abd31594b06eb5065037ae2d4`, operation_id
`kimi-review-33683`).

## Operational note — transient fail-closed, correct posture

At 07:58:20Z a `hestia_scope_status` call returned the society-safety fail-closed message
(governor timeout: "daemon most likely ALIVE BUT LOADED or cold: wait and retry"). It
cleared within seconds; the pointer resolver answered normally at 07:58:35Z. Fail-closed
with a clear cause is the documented correct posture, not a bug.

## Standing debt (owed_to_me, 43 rows) — no action

Same three classes, unchanged: 30 synthetic-probe rows (never-seen recipients:
a-completely-different-impostor / agent-inventory / contention-probe / hestia-cli /
totally-not-an-attacker fan-outs), 6 gemini misroutes (never seen locally; hub mesh is
the route), 7 live-but-unanswering cbp-being replies. Newest 10 are the 71d78fe292607a4f
and eabfdd27e786bf8e escalation fan-outs to the probe set.

## Method

Pointer resolved via `hestia://scope/` resource (source live_store this time — the request
was still in the memory-only map), lifecycle confirmed via `kimi-chain-tool.py tail` window
(positions 628661/628753/628767). Send via member-mesh CLI with `--operation-id`.
