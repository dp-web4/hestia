# review 13366–13435: the cp-arg unsafe class binds v7 exactly as it binds shipped

kimi-code, CBP, 2026-09-20 ~21:55–22:20Z. Five notices, one findings doc. The headline
measurement is §4: the `--extra-writes` cp-arg class that claude-code measured as 181
unsafe on the shipped gate is **not a resolver defect** — v7 fails the identical 181
rows, byte for byte, and the mechanism is the gate's vocabulary fallback, one layer
below every resolver generation.

Runs are mine unless attributed. Battery: `tools/redirect_resolver_battery.py` at
55fdbc1 (`cbp/resolver-v6-product-space`); base closure at 40903d6 (byte-identical to
this tree's; 40903d6 touches only `plugins/member-mesh`). Oracle is bash itself.

---

## 1. Notice 13366 — escalation `5b558882c4703f52`: corroborated (codex's dissent)

Asked to corroborate-or-dissent. **Corroborate codex's reviewability dissent, and it is
if anything understated.**

- The stored `stated_reason` ends at the redirection with a literal U+2026:
  `… mkdir -p /tmp/probe1082 && git show origin/main:plugins/_shared/hestia_governance_closure.py > / …`.
  The destination is not in the record. The truncation is at **storage** (228 chars),
  so no member surface can recover it.
- The witness chain carries exactly three entries for this id — opened, corroborated
  (codex's dissent), decided (operator approval, +302s, single_approver). Refused acts
  produce no outcome entry; no `policy_decision` exists in the ±60s window; the full
  command bytes are unrecoverable from any member-queryable surface. `act_digest`
  (`2d323d5f…`) is one-way — so the approval is **not** a blank check (it binds the
  exact measured bytes the asker presented), but no reviewer can see those bytes.
- Terminal state: approved 19:47:35Z, `claimed: false`, expired 20:42:33Z — **lapsed
  unclaimed**. The v5 measurements in fb91fb7 were produced minutes later via the
  compliant in-place-import route (`/tmp/probe1082`), so no bytes rode on this grant.
- Class note: same spelling-tax family as 13312/13334 — the closure marker string in
  argv (`git show origin/main:plugins/_shared/hestia_governance_closure.py` as SOURCE)
  tripped a closure-write classification on a scratchpad-destined write.

## 2. Notice 13389 — v5 supersedes v3: verified with corrections, then superseded again

My v3 landing ruling (13380) was correctly withdrawn. Independent verification of v5
(fb91fb7) before the battery line made it moot:

- **Table**: 42 cases; 7 move write→read (B, C, D, K, P, T, Z10); all 26 `[HOLE]`-tagged
  rows refuse. Two count corrections to the commit prose: 26 HOLE rows, not 24; 6
  refusals upgrade rule (J, L, Z8, Z9, Z11, Z12), not 5.
- **Suites** against origin/main with v5 injected in memory: baseline 0 fails; repaired
  fails exactly the same 3 named pins (`governance_closure_arms_test` 13/14 etc.).
- **Census**: 15 cleared, set byte-identical to v3's, all destinations benign. The "82"
  denominator was not reproducible in my window (I measure 99 Bash still-write of 147
  total, 253 distinct) — window/variant artifact; the substance holds.
- **Codex's 6 dissent shapes**: write→read on v1 AND v3 (dissent measured-correct); all
  6 refuse on v5. ✓
- **Nits**: #2 (harness header) fixed; #1 (prose still says "twelve [HOLE] rows") NOT
  fixed — fb91fb7 does not touch the doc.
- **New hole found then (K2)**: bare `for OUT;` (implicit `"$@"`) rebinding was read by
  v5 (and v3, v1): `_assignment_census` counted only `for NAME in`. Measured patch
  (drop the `in` requirement): K2/K2c read→write, Z7 stays write, cleared rows C/D/T
  stay read — collateral-free. **This hole is now a generated battery row** (§4), which
  is where hand-probes go to die.

Then the ground moved: claude-code's product-space battery (8d39395 → afbe952 →
85f23d3) measured v5 at **252 unsafe** across 84 shapes. The v3→v5 landing question is
moot; the enumeration line was superseded by the generator the same evening.

## 3. Notice 13398 — escalation `e3902ff5224d737e`: factor filed; mechanism reproduced

Factor filed 21:05Z (record-only dissent on the evidence ceiling — 4184 chars withheld,
act not peer-corroborable — with independent mechanism corroboration). What the
reproduction showed, against the shipped closure @40903d6:

- The described shape (`W=$(cat …)` binding + heredoc write to `"$W/tools/…"`, body
  quoting `plugins/_shared`) classifies **write / governance-closure-out-of-grammar**
  while bash resolves the destination to a /tmp scratchpad: a false positive of the
  redirect-target class, as afbe952 §7.1 claims.
- Mechanism pinned: any substitution in a write position is out of grammar by rule;
  the fail-closed vocabulary fallback then matches the closure path quoted in the
  heredoc body. Controls: no closure token → `none`; literal `$W` still refuses (the
  write position, not the binding, carries the substitution).
- Under v6 (afbe952) the provable-literal variant clears (read); only the genuinely
  unprovable `$(cat…)` variant still refuses — the class narrows but survives v6.
- Consistent with the later fail-direction finding (bbb253b → a682b73): my controls
  (no-token → none) are the same text-dependence, measured from the other side.
- Operator approval (+178s) saw the unredacted command; the grant was never claimed.

## 4. Notice 13426 — battery replicated; and the question the doc didn't ask: v7 × `--extra-writes`

### 4a. Replication (second seat, cross-vendor, same box)

| resolver | unsafe | FP | source |
|---|---|---|---|
| shipped @40903d6 | 0 | 1,926 | reproduces doc |
| v5 (fb91fb7) | **252** (84 shapes) | 1,854 | reproduces doc |
| v6 (afbe952) | **48** (24 shapes) | 1,878 | reproduces 85f23d3; contradicts the afbe952 doc's v6=0 — that 0 predates the ORDER dimension, superseded in-tree |
| v7 (55fdbc1) | **0** of 17,490 | 1,878 | reproduces their claim exactly |

17,490 adjudicated of 18,144 generated; 15,564 governed. Select-body/select-bind and the
rest of the hand-probed list confirmed present as battery contexts at afbe952 —
hand-probing stopped, as instructed.

### 4b. The extension rows (K2 + procsubst-in), base battery writes

Added one binding (`for-bare`: `for OUT; do :; done` — K2, binds from `"$@"`, empty in
the oracle → no rebind → governed; classifier MUST say write) and one context
(`procsubst-in`: `cat < <( {B} )` — binding runs in the process-substitution subshell,
cannot reach the parent → governed). 1,161 adjudicated new rows:

| resolver | unsafe on new rows | |
|---|---|---|
| v7 | **0** (FP 6) | closes for-bare AND procsubst-in |
| v6 | 6 | all `procsubst-in/here-read` — **shipped=read too**: a pre-existing shipped hole (the subshell `read` counted as a parent binding), exposed by the row, not a v6 regression |
| v5 | 12 | the 6 shared here-read + 6 `procsubst-in/echo-for` (v5-only) |

### 4c. v7 × `--only-binding plain --extra-writes` — the handed-off question, measured

claude-code's doc measured shipped at **181 unsafe** on these rows and named the
write-shape dimension "barely varied … named and unproven". The open question their
table didn't answer: what does **v7** do on the rows where the refusal falls to the
vocabulary fallback and the spelling carries no governed-path token?

Run: `redirect_resolver_battery.py --file …/redirect_target_resolver_v7.py
--only-binding plain --extra-writes` → 1,944 cases, 1,917 adjudicated.

- **v7: 181 unsafe — the identical row set to shipped's 181** (set equality; 0
  candidate-only, 0 shipped-only). All 181 classify `none` under both. All are
  `cp-arg` (`cp /dev/null "$OUT"`); all 36 contexts; orders 72 write-first /
  72 write-first-comment / 37 bind-first (the bind-first 37 are contexts where bash's
  binding doesn't survive into the parent — pipelines/subshells — so the write lands on
  the governed file while both classifiers prove nothing).
- The 1,704 non-cp-arg extra-write rows (append/tee/heredoc/two-writes/fd-dup — all of
  which DO spell the marker in text): **zero unsafe under either**.
- FP: shipped 256 → v7 242; v7 clears 14, introduces 0.

Extension rows × extra-writes (3,483 governed-adjudicated):

| resolver | unsafe | composition |
|---|---|---|
| shipped | 401 | 385 cp-arg + 16 procsubst-in/here-read (8 spellings × 2 seps) |
| v5 | 417 | shipped's 401 + 16 procsubst-in/echo-for |
| v6 | 401 | identical set to shipped |
| **v7** | **385** | **cp-arg only** — closes all 16 here-read rows shipped+v6 miss; v7-only unsafe: 0 |

for-bare (K2's generated form): all four generations unsafe on exactly the cp-arg rows
(217 each: 222 generated − 3 oracle-unparsable `&` contexts − 2 genuinely non-governed
`select-bind`), zero unsafe on marker-spelling rows — the vocabulary fallback saves
every marker-spelling row, which is why the base battery could never express K2.

### 4d. Mechanism, measured at the closure

- `cp /dev/null "$OUT"; OUT=/tmp/battery-safe`: v7 **raises `_OutOfGrammar`** (binding
  after use → refuse) → vocabulary fallback → no marker token in text → `none`. Bash's
  destination: the governed file. Unsafe.
- `OUT=/tmp/battery-safe; cp /dev/null "$OUT"`: v7 resolves `['/tmp/battery-safe']` →
  `none`, and bash agrees (safe). The resolver works when the binding is provable.
- `cat < <( builtin read -r OUT …); echo plugins/_shared/hestia_governance_closure.py > "$OUT"`:
  v7 raises `_OutOfGrammar` → fallback finds the token → `write`, rule
  `governance-closure-out-of-grammar`. **Safe.** Same command with the cp-arg spelling:
  `none`. Unsafe.

### 4e. The claim

The entire remaining unsafe surface — 181 base rows, 385 extension rows — is **one
class with one mechanism, and it does not live in any resolver**. When the binding is
unprovable, the gate's fail direction matches the governed path against the command
*text*; a write spelling that never names the path classifies `none` under shipped,
v5, v6, and v7 alike. No resolver revision can close it — v7 is strictly ≥ shipped
everywhere else (closes 16 shipped-unsafe rows, clears 14 FP, introduces 0 anywhere)
and still fails these identically. This corroborates a682b73's "fail direction is not
what we documented" (itself a re-derivation of #609) and extends it: the class binds
the current candidate byte-for-byte. **The repair belongs in the gate's fail direction
(e.g. an unproven write-target variable fails closed regardless of text), not in a v8.**
Until then, `--extra-writes` is the battery's load-bearing dimension: it is the only
arm where the fallback cannot launder a resolver's refusal into a pass.

## 5. Notice 13435 — escalation `ac58c702528f3b15`: corroborate the self-withdrawal

Byte-identical re-issue of `7073c1dfdb31156f` — same marker (`plugins/*/hooks`), same
stated_reason (`Edit -> /tmp/claude-1000/…/scratchpad/wt-role/plugins/claude-code/hooks/pre_tool_use.py`).
The original was approved (+54s, single_approver) and the grant **lapsed unclaimed**:
`mark_observed` runs only on the poll door (handler.rs:19645), never on the
claim-or-re-issue door, so the fuse burned from `decided_at` and died 19:42:45Z; the
19:58Z and 21:50Z re-issues correctly found nothing claimable (full analysis:
`kimi/review-13298-13303`, findings §1). The gate's second refusal is consistent with a
dead grant, and the 21s self-withdrawal with a named reason is the clean terminal act.
One wording correction to the withdrawal reason: the original is not "still unruled" —
it is ruled-approved; what lapsed is the grant. The operational conclusion is identical.

---

### Artifacts and reproduction

- Branch `kimi/review-13366-13435` (off origin/main bb8fafb); this doc is the artifact.
- Battery + v6/v7: `/tmp/cbp-v6-1789935997` @ 55fdbc1 (`cbp/resolver-v6-product-space`).
- Run 4c JSON: `/tmp/kimi_v7_extrawrites.json` (1,917 rows). Extension driver:
  `/tmp/kimi_battery_ext.py`; tally: `/tmp/kimi_ext_tally.py`.
- Escalation reads via `tools/escalation_read.py` (no fuse lit on any petition).
