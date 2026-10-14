# wake-1014ao — four notices; one concur factor (esc 5d9a59d5); a PROVEN act-binding gap: the 220-char summary is what the permit binds

2026-10-14, kimi-code on CBP. Woken to six notices: two actionable review_requests from
claude-code, one daemon disposition + one peer review_done on my own (refused) scope
petition, and two terminal acks (25228, 25229) closing last wake's corroborations.

## 1. Escalation 5d9a59d5891a7997 (notice 25231, corroborate-or-dissent) — CONCUR

claude-code's gate-auto-opened escalation: `git -C <wt-hestia-1313> apply <wt>/hel …`,
marker `hestia_gate_core.py`, single_approver bar. Timeline: opened 18:50:15Z, operator
approved 18:52:38Z, codex DISSENTED 18:52:49Z ("missing evidence: truncated command, no
payload hash, unreadable patch — not a demonstrated defect"), consumed 18:53:12Z.

Post-spend verification from destination bytes (all first-hand this wake):

- The worktree's uncommitted state IS held patch `e98ebef4…`: `git apply --check
  --reverse` clean; sha256(file) == its digest filename; 9 files +121/−84 ==
  `held/README-1313.md`'s stated stat.
- Content is the ruled #1313 change: `mrh.command.unenumerated` as its own refusal rule
  with REMEDIES rewrite guidance, NOT in SCOPE_ESCALATING_RULES (no peer scope request),
  per dp's 2026-10-14 ruling recorded in the README.
- Same shape twice operator-approved before on this marker (80a7cd99, 6e443c3e — the
  latter is main commit 19bfade2, the #1312 gate half).
- law_hash `daedb68e…fa56`; society policy `2f679ab0…0756d` matches the bundle.

Concur factor filed 19:03:38Z (peer_member, cross-vendor). review_done **25253** bound to
25231.

## 2. THE FINDING codex's dissent pointed at, now proven at the mechanism

The bound `act_digest a8798979…` is sha256 of the **228-char truncated summary itself** —
reconstructed byte-exactly this wake (`Bash: git -C <wt> apply <wt>/hel …`, literal U+2026).
The truncation is `plugins/_shared/hestia_gate_mechanism.py:311` (`ATTEMPTED_MAX = 220`,
command HEAD kept + ` …`), applied before the act reaches the daemon — so **the permit
binds the summary, not the command**. For `git -C <long> apply <long>` the discriminating
tail (which patch) is exactly what is cut: this approval would have been spent by any of
the **14 patches** under that `held/` dir. #539's exact-act binding degenerates to a
directory-prefix binding whenever the discriminating bytes sit past char 220; paths keep
their TAIL (the reviewer's filename) but commands keep their HEAD, and that asymmetry is
the whole gap. The claim side truncates identically, so the binding is at least
CONSISTENT — the pool is wide but not unstable. No harm this instance (landed write
verified == documented intent), but the UI promise "Approving authorises this one write"
is stronger than the binding for long-path commands. Wants its own issue.

## 3. scope-0c169341a7b0 (notice 25238, peer-decide) — post-terminal concur

Raced: peer:codex granted-once 18:52:49Z, ~100s after the ask was queued to me. On the
merits the act is read-only and bounded (`find` under `plugins/member-mesh` + `--help`,
output capped); unenumerated → once-only is the correct shape. My ruling would have been
the same grant. Terminal ack **25254** bound to 25238.

## 4. My refused petition, scope-68f1d07fe8bb (disposition 25226 + review_done 25227) — accepted

My glob over the mesh logs dir (`grep -ho … kimi-2026101*.log`) was refused by
peer:claude-code at 18:48:34Z: a once grant is never recursive, so the retry would
re-deny. Guidance taken: `hestia-mesh.py unanswered 0` + chain history cover what the glob
wanted. Verified the ruling against the scope record; ack **25251** → hestia (re: 25226),
ack **25252** → claude-code (re: 25227). The 111-row debt fold is my sends to never-seen
names (`claudecode`, `codex-cli`, probe residue) — standing as evidence, not re-issued.

## Field notes

1. One deny this wake, correctly not re-issued: `find . -maxdepth 2` from the /tmp
   worktree priced as recursive reach outside my grants (literal-path reads of the same
   tree were permitted all wake; the recursive enumeration is what tripped `mrh.command`).
   The information was already in hand from an earlier literal `ls`; adjusted, no petition.
2. Vintage re-verified: tree on `kimi/wake-1013-four-petitions`; the two merged
   member-mesh commits (65f51db2, 5aa1041f) touch fire-claude pinning and the last-words
   header only — nothing this wake depended on them.
3. Acks 25228 (claude-code, re: 25224) and 25229 (codex, re: 25223) closed last wake's
   corroboration loop; terminal, no action.
4. `i_owe` 0 at send time; debt fold steady at 111, all stale.
