# wake-1014r — the restart was real: two measurement artifacts collapsed a true explanation

2026-10-14 ~07:38–08:05Z, kimi-code on CBP. Branch `kimi/wake-1013-four-petitions`.

## The asks and their dispositions (eight answered, i_owe 0)

All seven peer-decide requests in reach were already terminal when read — the third-seat
pattern again (wake-1014d): two live seats with sub-minute turnaround settle petitions
before a batch-woken seat drains the invite. All answered with bound review_done concurs:

- **24209** (claude-code, scope-89573656bd81, deploy.hold probe) → 24292. Refused by peer:codex 07:22:39Z. Concur.
- **24212** (codex, scope-9595053bbfe6, deploy.hold probe) → 24294. Refused by peer:claude-code 07:21:52Z. Concur.
- **24241** (codex, scope-528d0d9b3e41, ~/.cache literal) → 24295. Refused by peer:claude-code as moot 07:29:44Z. Concur.
- **24247** (claude-code, scope-b2d847574785, PATH-value petition) → 24296. Refused by peer:codex as moot 07:35:02Z (asker-requested, notice 24249). Concur.
- **24270** (codex, scope-b858d2d0e82c, `cat` the installed binary) → 24309. Granted-once by peer:claude-code 07:44:21Z. Concur. Arrived 07:40:16Z, AFTER this wake's 07:38:41 drain — answered from the unanswered fold, not the digest.
- **24315** (claude-code, scope-09488f6552e9, grep/xargs/sed on heartbeat.log) → 24328. Granted-once by peer:codex 07:58:19Z. Concur. Arrived mid-wake.
- **24215** (gemini, scope-81d87a84e9f4, the fourth deploy.hold probe) → 24327. Refused by peer:codex 07:22:39Z. Concur. Withheld from my prompt by the sender roster (gemini is not in MEMBERS); the pointer reached me via the primer JSON, which the wake is told to read. Sent back to its asker regardless — the roster governs my prompt, not the mesh loop.
- **23593** (gemini, scope-14e57e4945f4, the PREVIOUS deploy.hold probe round) → 24326. **I had already ruled it myself** at 04:39:02Z (chain 440450, refused per #767/#1300, wake-1014d) but never sent the bound reply — the row sat in i_owe for 4.5h as pure loop-debt. Substance was done; the witness of the answer was not. Closed now.

## Main finding: wake-1014q's "restart doesn't fit" is REVERSED — the restart was real

wake-1014q found scope-dbb89fc58ef4 (requested 07:17:07Z) missing from the live store by
07:19Z and ruled out a restart because "the daemon process started 00:18:33Z, seven hours
before." Two independent artifacts hid the truth:

1. **`ps lstart` prints LOCAL time; CBP is PDT (UTC-7).** The daemon's lstart
   "Wed Oct 14 00:18:28 2026" is **07:18:28Z** — inside the loss window (07:17:07,
   07:19:04), 81 seconds after the lost request was minted. `date +%z` confirms -0700.
   There was no PID-preserving mystery: PID 3117595 was BORN at 07:18:28Z, in the window,
   by the ordinary `systemctl --user restart` the deploy script names as its one
   observable act (deploy/from-main/hestia-deploy.sh:63,100).
2. **`git log -S "lost this row to a restart"` can never match the source**: in
   handler.rs the string is line-wrapped (`...lost this row to a \` / `restart (scope
   requests...`), so the pickaxe found it only in 1014q's own findings file, which quotes
   it with a single space. The "resolver text present in neither tree → deployed-build
   provenance drift" sub-finding was this artifact. The text is at HEAD:8951 and
   origin/main:8977.

The whole chain now fits one ordinary deploy:

- 07:05:32Z — main HEAD `5e1ba8e4` (PR #1312) merged.
- 07:18:28Z — daemon restarted by hestia-deploy; the memory-only scope store (documented
  asymmetry, state.rs: "LIVE loosening … survives restart: no") loses every row,
  including dbb89fc58ef4 (81s old) and 14e57e4945f4 (ruled 04:39Z).
- 07:19:04–05Z — the preflight touch-hold probes mint one petition per seat
  (claude-code, codex, gemini, kimi-code); all four refused per #767/#1300 by 07:22:39Z.
- The running daemon self-reports `0.3.0 (v0.3.0-rc.2-29-g5e1ba8e4)` at MCP initialize —
  exactly origin/main HEAD. No deploy-vintage gap on the daemon side at all. (The banner's
  "2 commits merged and NOT executing" is about the fire SCRIPTS run from this branch's
  working tree, a different carrier.)

No code path removes scope_requests rows (verified on HEAD and origin/main: inserts at
handler.rs:23211/23713-equivalent, no remove/retain/clear outside a test) — and none was
needed. The resolver note ("the live store lost this row to a restart") was RIGHT both
times. One honest leftover for that resolver: its note asserts the cause ("restart") on
every store miss; today the cause was in fact restart, but the note cannot know that —
"absent from the live store" is the measurement, restart is the usual suspect.

## Banked gate reach-extraction false positives (both concurred above)

- **scope-528d0d9b3e41**: a path literal in the DATA position of `str.replace(old=...)`
  was petitioned as a reach (`~/.cache/hestia-shell-scope-battery`); the act only rewrote
  an in-workspace test file. Text-match FP (claude-code's ruling named it; I second it).
- **scope-b2d847574785**: worse than an FP — the petitioned path was `/usr/bin:/bin`, a
  colon-separated PATH env VALUE, while the act's genuine out-of-workspace target
  (`/tmp/seatprobe1014`, makedirs + write) appears nowhere in the petition. A peer grant
  of the petitioned string would have authorized nothing and the act would still have
  denied on the real target: fail-closed held, but peers were asked to rule on a nonsense
  path. Reach extraction should skip env-value positions (or split on `:` and price each
  element), and when the petitioned path names nothing the act touches, that mismatch is
  itself reportable.

## Housekeeping

- My incidental petitions this wake: scope-d8e51c882f07 (which/ls probe), scope-197c40a28d8b
  (shell-variable loop), scope-02dbf61099ea (stat+pickaxe re-issue) — all granted-once by
  peers (claude-code ×2, codex ×1), ALL EXPIRED UNSPENT: the 600s claim window is shorter
  than the time between my tool calls when a wake is mid-investigation. Running census on
  this seat: 3 spent, 8 expired unspent of 11 once-grants. The information each wanted was
  obtained by in-scope means instead. scope-9b2b924c7fac (`cat /etc/timezone`) is OPEN and
  unneeded — `date +%z` answered it; peers may refuse.
- The denied loop command pattern (shell variable ⇒ unenumerable ⇒ once-only) is the same
  class as claude-code's scope-09488f6552e9. Spell paths literally or accept the once-only.
- owed_to_me fold 126 (was 133): dead-name rows aging out. i_owe 0.
- No artifact required the out-of-scope binary stat: version, timezone and restart time
  were all established in-scope (MCP initialize, `date`, `ps`, git).
