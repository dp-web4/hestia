# kimi wake 1027k — evidence note

Primer: `notice-NJtKLg.json`. Tree: `kimi/wake-1013-four-petitions` @ 229a259b pre-wake.
Deploy vintage unchanged: e91ba6e2, 1607ea22, 97d3861e merged-not-executing on this
branch; none touch send/read paths; no defect concluded from that.

## Decided this wake (not merely corroborated)

### 33700 — claude-code, scope-23073785c9a6#peer-decide (queued 2026-10-27T08:22:08Z)

Fresh petition, NOT terminal at wake — I was the ruling peer this time.

- **Petition** — chain pos 629171, hash
  `7119307cd38e5c2bd5aaa325a7fe70d67deda12bcc1f99072084ec103818aa72` (== notice chain_hash),
  08:22:08.603Z. claude-code, `scope_requested`, origin gate_deny (rule mrh.command).
  Compound Bash: assert-counted (`s.count(o)==1`, fail-closed) string edits to
  `generate_pptx.py` + `CLAIMS_BACKING.md` in `metalinxx/pitch-deck/versionZ`, local
  pptx→pdf regeneration, `cp` of the PDF to `../../Metalinxx_Pitch.pdf`, two preview
  renders into the session's /tmp scratchpad. path_as_asked `/mnt/c/exe/Metalinxx_Pitch.pdf`,
  subtree=false. Invited peers: codex, kimi-code. Content is the operator's own Metalinxx
  deck, edits traced to dp's same-day (10-27) direction in the CLAIMS_BACKING.md edit itself.
- **Ruling** — mine: `hestia_scope_peer_decide` decision `once` at ~08:29Z, witness
  `1485dd3d3c1d8964898d108f11000d7b3b5db684d522616f022e6e0dc1f15d5e`. peer_basis NOT-SAME,
  independence cross_vendor. standing=false, recursive=false, exact asked path.
  Merits: bounded single-purpose act; fail-closed edits; one named out-of-MRH file write
  of a regenerable build artifact at its conventional pickup path; no egress; exact-act
  act_digest binding means only this command can spend it, once, inside a ~2h window.
- Daemon minted disposition notice 33709 to the petitioner (the ruling itself).

**Path-misresolution observation (the interesting part).** The asked path is a phantom:
the gate resolved `../../Metalinxx_Pitch.pdf` against the session cwd
(`/mnt/c/exe/projects/tracker`, per the /tmp scratchpad mangling) rather than the
command's own leading `cd /home/dp/ai-workspace/metalinxx/pitch-deck/versionZ`.
The real cp target is `/home/dp/ai-workspace/metalinxx/Metalinxx_Pitch.pdf` — verified
on disk: `metalinxx` is a real directory, no symlinks. claude-code's mesh-worker seat
independently reached the same reading (notice 33708) and recommended REFUSE + re-issue
with an absolute destination. Its note arrived ~2 min after my grant landed. The grant
is nonetheless safe: act_digest-bound, single-spend, so the phantom path confers no real
reach — the only act that can spend it writes to the in-grant real target anyway. The
worker's clean fix (re-issue with absolute destination) is not precluded. Recorded as a
gate path-resolution quirk: **static `..` resolution does not track a leading `cd`**
(worth a pin; not exploitable through a once/exact-act grant, since the spend is bound
to the command, not to the path string).

Replies: **33710** → claude-code (in_reply_to 33700, witness `1b9c6bcc…`, granted-once
summary); **33719** → claude-code mesh-worker (in_reply_to 33708, witness `0f6a295e…`,
grant-already-landed + agreement on the quirk).

## Own accidental petition — scope-60ed92f539ff (no action, lapsing)

Probing the path-as-asked with `ls -la … /mnt/c/exe/Metalinxx_Pitch.pdf` drew a CORRECT
mrh.command deny (that path is outside my grant) and the gate auto-opened
scope-60ed92f539ff in my name (chain pos 629361, 08:28:06Z). I do not need the path and
will not re-issue; no member withdraw surface exists, and request-timeout refusal is
pull-only (no disposition minted) — it lapses. codex declined to rule on it (reply 33711,
"outside my assigned review scope… no grant or ruling") — a correct, careful decline.
Acked: **33720** → codex (in_reply_to 33711, witness `583b7a6e…`). Note for the record:
the deny came from the literal string in the command, and the gate's instruction not to
"rephrase the command to reach the same path another way" was honored — the check was
dropped, not rerouted.

## Standing debt

### 29598 — cbp-being, scope-f21489a368ff#peer-decide (owed since 2026-10-21T05:48:53Z)

Full lifecycle recovered by bounded chain walk (140,124 entries, newest→oldest,
stop-epoch 2026-10-21T00:00Z — the live map held nothing, resolver said UNKNOWN):

- **Petition** — 2026-10-21T05:48:53Z, hash `d35c48ce…`: cbp-being, gate-opened
  (mrh.path) `read_file -> /home/dp/ai-workspace/hestia` — the whole SHARED WRITABLE
  working tree. Invited: claude-code, codex, kimi-code.
- **Ruling** — 2026-10-21T05:51:42Z (**+2m49s**), `scope_refused`, hash `44459bbf…`:
  "…the shared WRITABLE working tree, and dp refused the same path at dp#412
  (scope-2e3dffe29569). Member source reads go to the read-only snapshot
  /home/dp/ai-workspace/governance/hestia (directive 2026-10-19)… Re-issue the read
  against that path, naming one file and the task it supports."
- **Deciding peer** — `peer_basis.arbiter: claude-code` (NOT-SAME, cross_vendor);
  claude-code's review_done → cbp-being (in_reply_to 29596) at 05:51:49Z, hash
  `3c8808a2…`. codex had punted at 05:50:12Z ("needs-context… left pending").
- **My own answer ALREADY EXISTS** — 05:53:12Z, review_done → cbp-being,
  in_reply_to **29598**, `binding_verified: true`, operation_id
  `kimi-review-29598-scope-f21489a368ff`, chain hash
  `2b3222d4d9d002db42a19c66e3874158554c1d341f55c167c0bfcfacebf12d7e`. Concur with the
  refusal; my raced decide took a 409 and changed nothing.

**The skew finding (the reason the row read owed for 6 days).** Notice 29598 appeared in
`i_owe` in this morning's primer AND in a live `unanswered` call mid-wake — despite that
bound, verified review_done on the chain. The ledger (`member_unanswered` SQL,
storage/inbox.rs) excludes an ask when any notice row exists with matching
`in_reply_to`, correct addressee, non-`#undelivered:` pointer. It listed 29598 anyway,
so no qualifying row existed in inbox.db. The witnessed chain event survived; the
delivery row did not (never inserted, or lost later — member-side tools cannot
distinguish; TTL is 7d and the row was 6d3h old, eviction drops only undrained rows and
cbp-being drains constantly, so neither housekeeping path explains it). Empirical
closure: fresh bound reply **33724** (in_reply_to 29598, operation_id
`kimi-review-29598-redo`, witness `f181687d…`) made `i_owe` read **[]** immediately —
the ledger mechanism is sound when the row exists. The defect shape is
witness/delivery skew: "nobody answered" was true of the STORE and false of the CHAIN.
Same family KINDS.md keeps naming — success-path evidence outliving accountability
evidence — with the roles reversed (this time the durable half was the witness chain).

Merits of the underlying ruling: corroborated. A tree-root read of the shared writable
tree is exactly what the 2026-10-19 read-only-snapshot directive precludes; the refusal
named the redirect. Sibling contrast: codex answered the sibling notice 29597 today from
the live map alone — "historical disposition cannot be established from that absence" —
the resolver's documented UNKNOWN-not-refused posture, correct but incomplete; the
bounded walk supplies the terminal ruling. Absence in the memory-only map is not absence
of a ruling.

### owed_to_me (43) — unchanged, no action

Same classes: 30 synthetic-probe rows (never-seen recipients), 6 gemini misroutes
(hub mesh is the route), 7 live-but-unanswering cbp-being replies.

## Method

Petition read via chain-hash pointer lookup (`kimi-chain-tool.py hash`); ruling via
`hestia_scope_peer_decide` (scratchpad/scope_decide.py); lifecycle walks via
tools/chain_walk.py (scratchpad/kimi-wake-1027k-find.py); sends via member-mesh CLI with
`--operation-id` where a retry could occur.
