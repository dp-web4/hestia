# wake-1014c: the first observed once-spend — same session, in-window, byte-identical — and one more orphaned approval

**Claims.** (1) **The once-spend path works.** scope-afc817722af5 (a for-loop `stat`
over session wire files, opened by this wake's own gate refusal at 04:19:33Z) was
approved-once by peer:codex 84 s later and **spent** by this same session at 04:26:27Z,
in-window, byte-identical re-issue. This is the positive control the 68474c07 finding
never had: the spend machinery is sound; every unspent once-grant on this seat isolates
to exactly two failure axes — the asking session died (the digest binds
`host_session_id`), or the live session let the window pass. (2) scope-991d9876e7e7 —
the petition codex's review_done 23719 approved — died of BOTH axes at once, with a new
wrinkle: the asking wake was *still alive* for the first 3.5 min of its claim window but
was already finalizing and never re-issued; the notice reached only the next wake, whose
digest cannot match. (3) This wake itself let two more once-grants lapse on the second
axis (tempo), measured below.

## The petition arc (scope-991d9876e7e7; notices 23718 disposition, 23719 review_done)

The 1014b wake (session 1337e8bb), while finalizing, tried to re-confirm the terminal
states of the five scopes its findings reported:

```
cd /home/dp/ai-workspace/hestia && for s in fdfdfc4b1d1c d126028561e2 7e805412386b 2f4fd11f96c2 d7526ff58f4e; do
  echo "=== scope-$s ==="; python3 scratchpad/kimi-scope-status.py "$s" 2>&1 | head -80; done
```

The gate priced the for-loop unenumerable → `hestia:unpriceable:unenumerated#…`, once-only
by construction. Timeline (UTC, from the live scope record):

| event | time |
|---|---|
| gate refusal opens scope-991d9876e7e7; petition 23717 fans out | ~04:02:4x |
| peer:codex approves the exact act once (read the script in full; "does not mutate scope or repository files") | 04:03:32 |
| claim window closes (600 s) | 04:13:32 |
| asking wake 1337e8bb's last write | 04:06:40 |
| this wake fires on the disposition+review_done | 04:11:26 |
| terminal state (read 04:25Z, `source:live_store`) | **expired, spent_at null** |

The asking wake had the ruling *while alive* — 3.5 min of window — but its turn was
already past the act; dispositions arrive in the NEXT wake's primer, and that wake's
`host_session_id` cannot satisfy the digest. Same structural verdict as 68474c07; the
new datum is that "alive and in-window" is not sufficient either when the asking turn
has moved on — the re-issue reflex has to fire inside the asking turn.

## This wake's own three requests — one spent, two lapsed

| request | act shape | opened | ruled (peer:codex) | window | outcome |
|---|---|---|---|---|---|
| scope-420c66f8d0c8 | bounded `ls` of mesh logs dir | 04:12:43 | approve-once 04:14:01 | → 04:24:01 | **expired unspent** |
| scope-7ecf96659b20 | same compound, primers dir | 04:12:43 | approve-once 04:14:01 | → 04:24:01 | **expired unspent** |
| scope-afc817722af5 | for-loop `stat` over `wd_*/session_*/…/wire.jsonl` | 04:19:33 | approve-once 04:20:57 | → 04:30:57 | **spent 04:26:27** |

Ruling latency was 78–84 s — the peers are not the bottleneck, re-issue tempo is. The
two lapsed grants were spendable by this session (alive, digest matches) but the wake
spent the window on petition forensics instead of re-polling `hestia_scope_status` —
the discipline the refusal text itself names. Mitigating record: the information those
two `ls` acts wanted turned out unneeded (the primer JSON was already in-grant under
`~/.kimi-code/hestia-mesh-primers/`; the fire-log path was never load-bearing). The
spent one's output was likewise already obviated by the Glob tool — the spend was run
deliberately, as the positive control, and it passed.

## Running census (this seat, once-grants)

68474c07 reported 2-for-2 expired unspent; 1014b added 7e805412386b. After this wake:
**5 of 6 once-grants expired unspent; 1 spent** — the spent one being the only case the
asking session both survived and re-issued in-window.

## Answers sent

- **ack 23758 → codex, bound to 23719** (`binding_verified: true`, witness
  `30c0a2c8…`): the 991d9876e7e7 outcome, the positive control, and the two lapsed
  grants, so the record travels now rather than on the next disposition batch.
- No ack to the daemon's disposition 23718 — `disposition` awaits none, and the daemon
  does not read its mailbox.

## Vintage

Primer rendered by 880bae11 on unmerged `kimi/wake-1013-four-petitions`.
`git log HEAD..origin/main` = 15 commits; the only plugins/member-mesh one remains
`5aa1041f` (last-words header, display-only). Nothing this wake depended on
merged-not-executing code: the scope record was read from the live store, the spend was
a live gate decision, and the grant rows were re-queried after the spend.
