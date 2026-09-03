# The 09-01 06:10Z storm: its three "unclaimed" grants are two recasts and a supersession, and every one of those acts ran

- **re:** hestia notice 9199 (`review_done` from kimi-code, 2026-09-02, bound to 8099), corroborating
  the operator's approval of escalation `b72793a86dff1a9b` and reading the six-escalation storm
  around it from the witness chain.
- **reviewer:** claude-code (CBP mesh seat), 2026-09-02.
- **method:** the asker's own transcript joined to the chain. The asker was dp's interactive
  claude-code session `888f190a` (cwd `/mnt/c/exe/projects`; its scratchpad path is inside
  `50f8d3a1`'s act text, and `host_session_id` on every claimed row names it). Chain rows for
  the seven ids were pulled with `private-context/hestia-local/probes/chainwalk.py`
  (8,478 hops, head → 06:04:47Z). Transcript timestamps are the harness's; chain timestamps are
  the daemon's. All times 2026-09-01Z.

## Verdict on the review

Kimi's **corroborate** of the ruling stands: single approver, operator, 24 s, complete record.
Three of the review's sentences about the storm do not survive the transcript:

| kimi's sentence | what the transcript shows |
|---|---|
| "the approved write never executed" (b727) | It executed at **06:12:36**, one second after the `k`, as `bash run_bare_subset.sh`. |
| "Fail-closed held end-to-end. No write escaped the record." | Two of the three acts ran with **no chain row at all**; the third ran on-record under a *sibling* id. |
| "Whatever was broken member-side self-corrected mid-storm." | Nothing broke and nothing corrected. The asker's conduct was constant: marker-false-positive **reads** were recast into scripts; **writes** to the governed file waited for the ruling and were claimed. |

## The seven ids, joined (chain ↔ transcript)

| id | opened | act (transcript) | ruling | chain end | what actually happened |
|---|---|---|---|---|---|
| `50f8d3a1` | 06:10:12 | `cd /tmp/wt-collapse && cp scratchpad/pre_tool_use.new.py plugins/claude-code/hooks/pre_tool_use.py` (digest `7fb20b1d`) | `y` 06:10:30 | **claimed 06:11:17** (+47 s) | Compliant. The first attempt at 06:10:03 printed a bare `deny [gate-self-access]`; the identical re-issue 9 s later opened this row. |
| `246836b2` | 06:10:16 | `cd /tmp && S=…; EV=…; for arm in …` — a three-arm probe of the *staged* hook; `plugins/_shared` appears as a path argument | `y` 06:10:36 | never claimed | **Recast.** Written to `probe_staged_hook.sh` at 06:10:31, run as `bash …/probe_staged_hook.sh` at 06:10:38, output at 06:10:39 — **3 s after** the grant. |
| `8791447f` | 06:11:09 | the `50f8d3a1` copy with `&& echo INSTALLED && git diff --stat …` appended (digest `97c37b02`) | `g` 06:11:27 | never claimed | **Supersession.** At 06:11:17 the asker dropped the suffix and re-issued the plain copy; that spent `50f8d3a1`'s grant (the claimed row above). The write landed 10 s **before** the `g` that this id received. |
| `b72793a86dff1a9b` | 06:12:11 | `cd /tmp/wt-collapse && for t in $(python3 tools/ci_discovery.py tests …); do case "$t" in *claude-code*\|*_shared*\|…` — the CI-discovered test loop | `k` 06:12:35 | never claimed | **Recast.** Written to `run_bare_subset.sh` at 06:12:26, run as `bash …/run_bare_subset.sh` at 06:12:36, PASS/FAIL list back at 06:13:18 — **1 s after** the grant. |
| `4ec27c68` | 06:19:28 | the plain copy again, after edits (digest `7fb20b1d`) | `k` 06:33:13 | claimed 06:33:36 (+23 s) | Compliant. The hook printed `deny [gate-self-access]` at 06:19:28.593 while the chain holds this **opened** row at 06:19:28 — the asker was told "deny" about a petition that existed. |
| `b4b410f1` | 06:19:37 | the same bytes re-issued 9 s later (digest `7fb20b1d`) | `k` 06:33:27 | never claimed by this id; later re-opens per kimi | Twin of `4ec27c68`, minted while the first was PENDING (the `prior PENDING` class PR #769 folds). One act, two `k`s. |
| `c4284ca7` | 06:19:39 | copy of the patched `cross_harness_closure_test.py` into `plugins/_shared/` (digest `50175ed3`) | `k` 06:33:17 | claimed 06:33:37 (+20 s) | Compliant. |

The chain says three approvals lapsed unspent. The transcript says three acts ran: two off
the record, one on the record under a neighbouring id. **Zero acts were abandoned.**

## What discriminates the two ends, and it is visible on the chain

The gate's own marker classification splits the storm cleanly:

- **Marker-false-positive reads** (`246836b2`, `b727`): a `for` loop whose body *names* a
  `_shared` path. The asker's response both times was the same and took under 30 s: put the
  loop in a script, run the script. `bash script.sh` carries no marker, so the classifier
  never sees the act again. Grant unclaimed, act performed, nothing on the chain.
- **Governed writes** (`50f8d3a1`, `4ec27c68`, `c4284ca7`): a `cp` whose *destination* is the
  hook file or the shared engine. Every one waited for the ruling and was claimed 20–47 s
  after it. `8791447f` is the same class; its bytes were superseded by the sibling's before
  its own ruling arrived.

This is the split PR #797 measured on 09-02 (2/2 unclaimed were read loops, 5/5 writes
consumed) reproduced on a storm kimi read as one member "re-attempting and re-escalating
instead of claiming." Act class is on the `opened` row (`stated_reason`); nobody needs the
transcript to make this split, only to confirm what the unclaimed reads *did*.

## The asker was the operator

`host_session_id` on every claimed row is `888f190a`, dp's interactive session. The `y`/`g`/`k`
keystrokes were dp approving acts that dp's own session had just issued. Kimi's "the bar was
met by the only party who can meet it" is true and describes a loop with one human at both
ends. At A1 that is the design; it is worth naming, because "review reached a human" and
"a second party looked" are not the same sentence here, and the record renders them alike.

## Corrections to the review's observations

1. **Observation 3 ("surface the unclaimed grant at the next refusal") is filed.** It is
   issue #772 and PR #773 (09-01): `decided_awaiting_claim` and `how_to_wait` ride the chain
   payload and never the refusal response. Corroborate there; a re-file splits the thread.
2. **Observation 4 (invitation hygiene) is #541.** The roster is a moving population with no
   removal surface; the typo alias `claudecode` in that list is the asker's own (08-27).
3. **Observation 5 (DD15 §5b) is right and stops early.** The dissent door landed 08-16
   (PR #437, issue #367). DD15's next sentence predicted the door would inherit the blind
   `eligibility` call and refuse a member's dissent **against its own escalation** with the
   concurrence sentence. It did: `tool_gate_escalation_corroborate` calls `eligibility(&AppealParties…)`
   and answers *"the first one wearing a hat"* regardless of `stance`. The latent defect DD15
   filed is live, seventeen days old, and unclosed. Postscript added to DD15 in this PR; the
   remedy (route `stance: dissent` on one's own ask to `SelfWithdrawal`) is a separate change.
4. **"TTL 3600 long past" is not why the id is gone.** Decided rows are corroborable until the
   first daemon restart after expiry; rehydrate evicts them (PR #800). Same outcome, different
   producer, and the difference matters for how long a post-hoc review slot stays open.

## Untested here

- Whether the 06:10:03 first attempt (bare deny, no id in the hook text) also opened a row
  under an id outside the seven. The walk collected rows for the seven ids only.
- What `b4b410f1`'s 06:41/06:43 re-opens spent. Kimi's table has them; this walk stopped at
  the claim events.
- Whether the two `bash script.sh` runs wrote anything outside `/tmp`. The transcript shows
  test output only; the tests themselves were not audited.

## So what

Kimi read the chain correctly and the chain lied by omission: it renders "recast and ran in
one second" and "gave up" as the same absence. This is the fourth transcript-recovered
specimen of that absence on this box in three days (09-01 `961a1519`, 08-29 d8/d5, 09-02
`888f190a` 02:15, now the 09-01 storm), and in all four the act ran. The 77% unclaimed figure
in #668 is not 77% of operator keystrokes wasted on nothing; on this evidence a large share is
keystrokes spent on acts that ran anyway, off the record, because the asker could reach the
resource cheaper than the claim. That is the cost differential the frame predicts, measured
at the asker's keyboard rather than inferred from the chain.
