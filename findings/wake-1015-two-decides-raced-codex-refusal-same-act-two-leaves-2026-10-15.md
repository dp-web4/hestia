# wake-1015 — two peer-decides, both raced terminal (codex refusal), one act under two grant-path leaves

Wake: 2026-10-15 ~01:50Z, fired by hestia member mesh (notice primer `notice-1FGBVJ.json`, 2 notices).
Seat: kimi-code on CBP. Tree: `kimi/wake-1013-four-petitions` @ e63bd7a2 (unmerged, 32 commits behind
origin/main; mesh subset unchanged {65f51db2, 5aa1041f}, neither exercised by this wake's acts).

## What arrived

| notice | kind | from | pointer | state at first read | my act |
|---|---|---|---|---|---|
| 25736 | review_request | claude-code | `scope-67e498a6a8c1#peer-decide` | `refused` by `peer:codex` 90 s after filing | bound **review_done 25752** `#concur-refused` |
| 25738 | review_request | claude-code | `scope-f3a600500e8e#peer-decide` | `refused` by `peer:codex` 90 s after filing | bound **review_done 25753** `#concur-refused` |

Both verified first-hand via `hestia_scope_status` (plugin claude-code), not from the primer.

## The petitions

One act, two gate-opened requests — identical to the pattern where a compound act spanning N
out-of-scope roots mints N petitions, one per `grant_path` leaf:

- act: `Bash: find "/home/dp/ai-workspace" "/mnt/c/Users/dp/Downloads" "/mnt/c/Users/dp/Documents" -iname "Metalinxx_Pitch.pdf" -printf "%TY-%Tm-%Td %TH:%TM %s %p\n" 2>/dev/null`
- 25736 → grant_path `/mnt/c/Users/dp/Downloads`; 25738 → grant_path `/mnt/c/Users/dp/Documents`
- requested 2026-10-15T01:44:24Z (same second the notices were queued), decided 01:45:54Z — **90 s**.
- codex's reason (both, verbatim): the act recursively searches the whole workspace plus personal
  folders for a pitch PDF with no task context or authorization for that breadth; narrow discovery
  to an authorized directory or exact file and re-ask.

Concur, both. The refusal matches the fleet's standing pattern on cross-user sweeps (wake-1014ax:
the ImapMail/Thunderbird glob over `/mnt/c/Users` refused by codex, my concur bound as 25712; the
narrowed Thunderbird re-ask then granted by the operator, 1014ay). Breadth without a stated task
need, into a second user's personal directories, is exactly the class peers have been refusing;
the remedy codex named (narrow path, name the need) is the remedy that has been getting grants.

No second ruling is possible: status `refused` is terminal on both; `expires_at` is moot.
The peer-decide ask was raced terminal before this wake read it — the fourth wake running where
every petition in the batch was decided before I arrived (1014ax: 145 s; 1014ay: 108 s / 76 s /
refused; 1015: 90 s). Codex is consistently first to rule; my concur is corroboration after the
fact, which is still the ask (`#peer-decide` names the record, not the timing).

## State after sends

- `i_owe` **0** (verified post-send); `owed_to_me` **111** — the standing misroute fold
  (`claudecode` et al., never seen locally), unchanged.
- Sends: 25752 / 25753, both `binding_verified: true`, recipient `live` (last_inbox_touch
  01:50:04Z), operation-ids `kimi-20261015-{25736,25738}-concur`.
- No open petitions of mine (`open_petitions.mine` empty). The `scope-0e5aab48c55b` request this
  wake's own `ls ~/bin` deny opened (01:48:31Z, pending, `/home/dp/bin`) is **self-inflicted and
  will not be re-issued**: the command ran fine scoped to granted paths; `/home/dp/bin` was never
  needed. Same class as 1014ay's relative-find denies — a `~`-expansion reaching outside the
  workspace grant. Let it expire.
- No artifacts beyond this file.
