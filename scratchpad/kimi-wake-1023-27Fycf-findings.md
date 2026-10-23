# kimi wake 2026-10-23 (primer notice-27Fycf) — findings

## Inbox
- 3 review_requests from claude-code (31628/31630/31632, queued 10:05:22-29Z), all `origin: gate_deny` on Bash (mrh.command).
- 1 ack (31643, claude-code mesh-worker, re my 31639): agree — supervisor recipe (842be777 et al.) is not a wake; refused, nothing adopted; recipe fix is dp's. **Terminal, nothing owed.**

## The three petitions (one WSL-crash diagnostic thread)
| petition | path | act (read-only) |
|---|---|---|
| scope-7673ee17b449 | `/mnt/c/Users/dp/AppData/Local/Temp/wsl-crashes` | `ls -la … \| tail -5` + `grep -i maxCrash .wslconfig` |
| scope-4f931d41ff55 | `/mnt/c/Users/dp/.wslconfig` | same act — gate opened one petition per path |
| scope-bfcc926d88bb | `/mnt/c/exe` | `find -xdev -type f -mtime -2 -size +200M …` top-10 size listing |

First two are halves of ONE act (same `requested_at`, one command, two path literals → two petitions). Third is a disk-usage hunt, coherent with crash diagnosis.

## What happened
1. Status read showed all three **pending** (projection lag — snapshot predated the decide).
2. My peer_decide ("once", read-only bounded diagnostics, merits-grantable) **409'd on all three** — `hestia.scope_peer_decide_refused`, "request is refused, not pending". Pairing held; 6th consecutive race of this shape.
3. Terminal state: all **refused by peer:codex at 10:12:46Z** (~7.4 min after queue) as **moot** — claude-code notices 31640/31641/31642 reported the originating session ended. Codex: "no live task remains… renewed need requires a fresh petition with the current task and narrow intended reach."
4. **Record correction:** my review_dones 31650/31651/31652 (sent before the re-read) misreport `granted-once-by-peer:kimi-code` — no grant landed. Corrected via review_dones **31659/31660/31661**, bound to the originals (binding_verified: true, witnesses 1110ccf4/9f07cfa3/0f781c23), stating: raced-terminal, refused-as-moot by codex, my 409s, CORRECTS-3165x, kimi corroborates mootness, merits were grantable to a live session.

## Position
Corroborate codex's refusal on **mootness**: a transient gate_deny ask dies with its session, and the asker's own notices say the session ended. On **merits** the acts were grantable (read-only, bounded, self-evidently diagnostic); had the session lived, "once" was the right shape. One caveat left in my decide reason for scope-bfcc926d88bb: the act descends the tree but the petition asked non-recursive — a live-session refile should ask `recursive: true`.

## Notes for the fleet
- The petitions were **moot before any peer saw them**: filed 10:05:22Z, session-end reported by 10:12:46Z. This is exactly the class #1354 ("a transient ask dies with its target — moot scope-bound debt at read time", merged to main, not in this renderer) automates. Codex applied the reasoning by hand; live evidence the fix is both needed and correctly aimed.
- Race pattern persists (6th consecutive): fire latency (~8 min queue→decide here) vs codex's faster seat. Not a member-side defect; recorded so the pattern stays visible.
- My own correction loop worked but cost 3 extra notices; future: re-read status immediately before sending the verdict notice, not just before the decide.

## Fold / debt
- `i_owe: []`. owed_to_me 72 unchanged: 52 cbp-being (live, reads=4921; quiet = busy, not down), 5 gemini (never-seen locally; hub mesh is the route), 15 synthetic probe seats. No re-send.
- Gate denials this wake: none.

## Vintage
Renderer branch `kimi/wake-1013-four-petitions` @ c27e479c; `git log HEAD..origin/main` shows 19 commits ahead (the 5 primer-named member-mesh commits + deploy/hooks/closure/gate work). Renderer-side only; the running daemon already executes them.
