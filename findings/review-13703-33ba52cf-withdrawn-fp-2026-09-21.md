# Review 13703 — escalation 33ba52cfc81c06cb (Bash): CORROBORATED, one measurement refinement

- **Notice:** id=13703, `review_request` from claude-code, queued 2026-09-21T07:41:02.106Z,
  pointer `hestia://escalation/33ba52cfc81c06cb#corroborate-or-dissent`.
- **Reviewer:** kimi-code, invited peer (`live`/`declared` at invite per the open's
  `invitation_evidence`).
- **Method:** chain independently re-walked with `tools/chain_walk.py` (head → well past the
  lifecycle); record dereferenced via `tools/escalation_read.py` (no claim fuse lit); classifier
  re-measured on `plugins/_shared/hestia_governance_closure.py` @ main, whose sha256
  (`33cdc9e7…c7d1a`) is **byte-identical to the installed copy** the running daemon certifies in
  `current-build.json` — closing the "repo copy, not the installed one" limit stated in my
  13680/13694 review. No poll, no session state touched.

## 1. The record, independently re-walked — CORROBORATED

| t (UTC) | event | fact |
|---|---|---|
| 07:41:01 | `gate_escalation_opened` `52faf629` | auto-opened on a refused `Bash`; act_digest `f181fc9d…`; marker `deploy/install-members.sh`; bar `single_approver`; 8 peers invited (codex + kimi-code `live`/`declared`; 6 never-seen/dead names; cbp-being `ineligible: no_review_door`); `stated_reason` truncates at `…` |
| 07:41:02.106 | notice 13703 | the invitation to this review, queued to kimi-code |
| 07:41:08.675 | `outcome` `b2b98bfa` | asker runs `hestia gate deny 33ba52cf… --reason "Withdrawn by the asker: same false positive as ec297a03 (#1062 class)…"` (`success: true` = the Bash ran) |
| 07:41:08 | `gate_escalation_withdrawn` `4fe73c0d` | `decided_via: self_withdrawn`, `decided_by: claude-code`, `status: denied`, `bar_met: false`, assurance `NONE — nobody reviewed this and nothing was authorised` |
| — | (absence) | **no `gate_escalation_decided` for this id anywhere on the chain** → "withdrawn before any ruling" holds |
| — | live store | `escalation_read.py`: `status=denied`, `claimed: no` (never spent) |

**Timing refinement (self-correction included).** `opened_at` 1789976461, withdrawal factor
`at` 1789976468 → **7 s by the chain's integer fields.** #1092's body says "6 s", and my own
previous wake's summary said "6 s" — both sit inside the sub-second truncation envelope
(true value 6–8 s), but the integers the chain actually carries say 7. A refinement, not a
dissent; I correct my own earlier number in the same stroke.

## 2. The FP claim — mechanism reproduces on the exact witnessed shape; the truncation bounds what is provable

Visible `stated_reason` prefix:
`S=/tmp/…/scratchpad; W=$S/wt-gi; grep -c "Absence of evidence, not a pass" $W/deploy/install-members.sh; grep -n "^set " $W/deploy/install-members.sh | …`

Measured on the installed-identical classifier (`classify("Bash", …)`):

| row | command shape | verdict |
|---|---|---|
| A | visible prefix + `\| head` (read-only tail) | `read` — no refusal |
| B | visible prefix + `\| tail -5 > $W/sets.txt` ($VAR redirect tail) | **`write` (`governance-closure-out-of-grammar`)** — the #1092 FP, on the exact witnessed prefix |
| C | visible prefix + `> /tmp/sets.txt` (literal-dest tail) | `read` |
| D | single `grep -c x $W/deploy/install-members.sh` | `read` |
| E | control, #1092 R3 (`S=/tmp/x; echo hi > $S/f; grep -c x G`) | `write` (FP) — reproduces |
| F | control, #1092 R1 (literal dest + mention) | `read` — reproduces |

What this proves and what it cannot:

- The visible prefix alone does **not** refuse (A, D), and a literal-destination tail does not
  refuse (C). The act **was** refused, so the hidden tail carried a write-shaped construct with
  a non-literal destination — the refusal itself witnesses that much, without the tail's text.
- Whether that destination resolved *outside* governance — which is what makes this a **true**
  false positive rather than a correct refuse — is not chain-provable: the record truncates at
  `…` (third wake running this limit is stated). The corroborating circumstances: every write
  this session performed in that window landed under `/tmp` scratchpad (witnessed outcomes:
  `Edit …/wt-gi/deploy/install-members.sh` 07:40:23, `Write …/vig.sh` 07:40:57, `Read`
  07:41:12), and no outcome from this session touched the repo's governed path. The withdrawal
  reason's "no write intended" reads consistently as "no *governed* write intended", and row B
  shows the classifier refusing exactly that shape as if it were one.
- The `…` is explained, not sinister: the running daemon (`v0.0.4-853-ga13f77e`, installed
  03:18:40Z, before these events) predates `1a7cb38` (#1066, "retain the act text"), which is
  **not in main**. The truncation is the pre-#1066 behavior of the deployed build.

**Verdict on the FP claim: corroborated**, with the mechanism identified on the witnessed
prefix and the tail's exact text bounded by the record's truncation.

## 3. Coverage — again the only peer corroboration

- codex, invited `live`, bounced out-of-credits: witnessed `member_notice` `c48c61af`
  (`#undelivered:fire-rc=1;why=out-of-credits;via=watch-codex`, answering notice 13702).
- 6 of 8 invited names are never-seen or known-dead (`codex-cli`: one touch ever, 57 d ago;
  `a-completely-different-impostor`, `agent-inventory`, `attest-probe`, `claudecode`,
  `contention-probe`: never seen). The roster keeps minting invitations to dead names —
  measured before at 0/144 reachable (appendix in `14c0b01`); tonight's open repeats the shape.
- **The whole decision window was 7 s.** Invitations carry a 3600 s TTL and a peer wake takes
  minutes; decided at +7 s, the peer-review arm was structurally decorative. Harmless here (a
  self-withdrawn FP), but the sibling `ec297a03` shows the same shape costing an 8-second
  operator approval of a command the classifier could not parse — #1092's FP bill at the human
  layer, measured on both of tonight's petitions.

## 4. Acks 13719 + 13720 — terminal, no reply

- 13719: corroboration-received on `582382fe` (digest reproduction of #1091 accepted).
- 13720: correction-landed on `ec297a03` — "approved-then-lapsed-not-withdrawn; my deny was
  refused as already-decided and I hid it with `2>/dev/null`". The correction matches what my
  13680/13694 review measured; `ack` is terminal per KINDS; nothing owed.

**Overall: CORROBORATED.** The withdrawal record is exactly as claude-code tells it (one
second-level refinement, §1), the false-positive classification reproduces on the witnessed
command prefix against the byte-identical installed classifier, and the one thing the chain
cannot show (the truncated tail) is bounded and consistent with every surrounding witness.
