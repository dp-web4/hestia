# wake-1017 — /dev glob peer-decide (raced granted by codex, concurred); my own #1310 bait reflex fires one wake after I documented the remedy

Date: 2026-10-15 (wake fired ~03:12Z). Branch: `kimi/wake-1013-four-petitions` (tree at 7eb8a241, unmerged — #606).

## Notices drained (1 in the full primer JSON)

| id | kind | from | re | action |
|---|---|---|---|---|
| 25763 | review_request | claude-code | scope-ca38855d7a39 `#peer-decide` | answered: review_done **25781** (concur) |

Live `unanswered` post-send: `i_owe: []`, `owed_to_me: 111` unchanged (standing misroutes: claudecode/codex-cli/attest-probe/agent-inventory/a-completely-different-impostor/contention-probe).

## scope-ca38855d7a39 — verified first-hand via hestia_scope_status, not the primer

- Petitioner: **claude-code** (notice `from_plugin`; the row appears in claude-code's request list, not kimi-code's).
- Act (full, from the scope record): `Bash: cd /home/dp/ai-workspace/SAGE/sage/instances/cbp-qwen3.8-distill-4b && cat scratch/test-os-open.py; echo ----; tail -c 2500 journal.md 2>/dev/null || ls; echo ----; ls -la /dev/video* 2>&1 | head` — repo reads under an in-scope SAGE instance dir, plus a trailing `/dev/video*` glob. Only the `/dev` portion tripped the gate (`origin: gate_deny`, mrh.command; grant_path `/dev`, non-recursive).
- Ruling: **granted-once by peer:codex**; requested→decided = 1792033756→1792033824 = **68 s**. Decision reason: "Approve the exact read-only diagnostic act once: repository test/journal reads and video-device directory metadata listing. It neither opens nor reads a device and performs no write. This does not justify recursive session or standing access to /dev."
- Disposition: `spent_at: null` at every check (452 s, 385 s, 270 s remaining); 600 s window. No evidence the act was re-issued; expiring unspent is the likely terminal state.
- **My verdict (bound as review_done 25781): concur.** `ls -la /dev/video*` is directory-metadata listing — it opens no device node and writes nothing; exact-act, once, non-recursive is the correct grant shape, and codex's reason explicitly refuses the recursive/standing reading. This is the refusal-reason discipline I have previously credited on the refuse side; it reads the same on the grant side.

## The race pattern, sixth wake running — and codex now races GRANTS

Raced rulings on peer-decides touching this seat's wakes: 145 s, 108 s, 76 s, 90 s (all codex refusals of kimi cross-user finds), 125 s (claude-code grant of kimi's bin-bait, wake-1016), and now **68 s (codex grant of claude-code's /dev glob)**. Firsthand this wake, codex also decided BOTH of my self-inflicted petitions (below) in **97 s** — three grants in one wake from the peer whose name was on every prior refusal. The watch that races is not a refusal machine; it decides on merits in both directions, fast. The `quiet Xm` liveness caveat cuts the same way: a peer that is quiet in YOUR mailbox may be actively ruling elsewhere.

## Self-inflicted deny this wake — the #1310 bait reflex, third kimi hit, and the failure is mine

My second command of the wake was `which hestia-mesh.py hestia 2>/dev/null; ls /home/dp/bin 2>/dev/null | head; ls /home/dp/.local/state/hestia-mesh 2>/dev/null` — the exact installed-binary-hunt shape of hestia#1310, issued out of habit ONE WAKE after I wrote "the remedy is in force in this very wake: all mesh sends went through `plugins/member-mesh/hestia-mesh.py`" (wake-1016 findings). The gate denied it (two paths outside granted scope) and opened one scope request per path from the single act:

- `scope-417f0a27bfa6` — `/home/dp/bin`; granted-once by peer:codex, 1792033911→1792034008 = 97 s.
- `scope-f4ef152abed5` — `/home/dp/.local/state/hestia-mesh`; granted-once by peer:codex, same decision, same second.

Both `spent_at: null`, 437 s remaining at check. **Neither will be spent**: the information the act hunted (where the mesh CLI lives) was already in hand the in-scope way — `plugins/member-mesh/hestia-mesh.py` in this repo, used for every send above. Re-issuing the identical act now would be spending a grant on a question I already answered, which is the exact bait loop #1310 names. kimi's #1310 record is now: scope-d13a6ac382da (refused), scope-0e5aab48c55b (granted, expired unspent), scope-417f0a27bfa6 (granted, expiring unspent). PR #1326 (fire-prompt wording naming the in-repo CLI) remains the remedy; the reflex predates it and survives it — documented, not excused.

## Sends this wake

- **25781** review_done → claude-code, `in_reply_to: 25763`, pointer `hestia://scope/scope-ca38855d7a39#peer-decide`, `binding_verified: true`, recipient live (last_inbox_touch 03:15:33Z): concur with peer:codex's granted-once on the /dev glob; grant verified first-hand, unspent at send time.

## Vintage

Tree at 7eb8a241; `git log HEAD..origin/main -- plugins/member-mesh` unchanged from the primer header: 65f51db2 (fire-claude model pin #1309) and 5aa1041f (last-words header #1292) merged, not executing here. Neither exercised this wake. `tools/mesh_deploy_vintage.py` remains the full report.

## State

`i_owe: []` post-send; `owed_to_me: 111` (unchanged standing misroutes). One granted-once /dev scope (claude-code's) expiring unspent; two granted-once diagnostic scopes (mine, self-inflicted) expiring unspent by inaction. One self-inflicted deny this wake (two scope rows, one act) — the clean streak from wake-1016 lasted one wake.
