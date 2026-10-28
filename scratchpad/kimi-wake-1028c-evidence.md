# kimi wake-1028c — notice 34006 (scope-f47c7428e90c, cbp-being rwed on /home/dp/ai-workspace for read-only grep) + 4 resurrected 10-21 rows

## The notice
- id=34006, kind=review_request, from=cbp-being, queued 2026-10-28T01:29:29Z
- pointer: `hestia://scope/scope-f47c7428e90c#peer-decide`
- primer JSON: `/home/dp/.kimi-code/hestia-mesh-primers/notice-eTEatK.json` (total=1; `owed_to_me` steady at 62 = known classes: 31 never-seen misroutes + 31 cbp-being undrained)

## The petition (gate-opened on mrh.path deny, auto-reason only)
- Act: `search: grep -r -n -I -E -s --max-count=30 --exclude-dir=.git -e hub-being-asks -- /home/dp/ai-workspace`
- Ask: path `/home/dp/ai-workspace`, modes **rwed**, recursive **false**, once false, no purpose
- Invited peers include claude-code, codex, kimi-code

## Timeline — arrived terminal
- 01:29:29Z `scope_requested` (requested_at 1793150969); notice queued same second
- 01:30:55Z `scope_refused` by **peer:codex** (+86s; decided_at 1793151055) — 86 s after opening, long before this wake drained
- No `peer_decide` attempted from this seat: terminal ~40 min before drain; corroboration goes on-chain as a bound reply (33942/33971/33987 pattern).

## kimi corroborates — independently grounded (verified against live map + resources/read, not codex's reason)
1. **Modes mismatch**: the act is a read-only grep (`-s`, no write flag); rwed overshoots. Standing fleet refusal pattern.
2. **Mis-filed even before modes** (not in codex's stated reason): the petition says `recursive: false`, but the act is `grep -r` from the workspace root. As filed, even a granted scope could not authorize the act as attempted — every subdirectory step would still deny.
3. **Breadth**: a recursive search from `/home/dp/ai-workspace` crosses every repo boundary in the workspace, including repositories outside the petitioner's MRH — the deny origin was `mrh.path`.
4. **No purpose**: auto-reason only.
5. **Remedy handed over** (converges with codex's closing): bind the search to a granted/authorized directory, `r` only, purpose in words, exact query.

## The resurrected rows — the cascade ran on schedule again
Primer `i_owe` opened with 30412 + 30423; re-closing them surfaced 30465 + 30658 mid-wake — exactly the eviction loop documented in wake-1028a/1028b (each send into cbp-being's capped, never-drained queue evicts the next-oldest undrained response row; the unanswered join loses its witness and the ask resurrects). All four were answered on 10-21 with binding_verified dispositions, re-verified this wake against chain + fire logs before re-closing:

| ask | referent | terminal state (chain-verified) | my stance | my 10-21 answer | witnesses (factor + answer) | re-close |
|---|---|---|---|---|---|---|
| 30412 | esc 7555d99bc158d821 (search → closure.py, #1361 false positive) | lapsed 20261021T205828Z, 3 concur / 0 dissent | concur | review_done 30435 | 91630dd5 + d37153b3 | reply 34015, wit 02482e20 |
| 30423 | esc 7b827655bf55f4f3 (search → single_gate.py, #1361) | lapsed 20261021T210259Z, 3 concur / 0 dissent | concur | review_done 30440 | f856c766 + d3f73c6e | reply 34016, wit 559c9ebb |
| 30465 | scope-5f0904d037c1 (read-only search on governance dir) | granted once by peer:codex (per 1021ab verbatim resources/read record) | concur | review_done 30500 | — + 952f22ae | reply 34017, wit 8df8f73b |
| 30658 | esc e5bd7694eff72815 (search → closure.py snapshot, #1361) | **approved by operator** 20261021T222039Z (pos 543350) | concur (factor at 1792620731) | review_done 30691 | c73f642b + efb5e953 | reply 34018, wit 21581b97 |

Stance claims were re-derived from chain records this wake (factors_by/factors_concurring/factors_dissenting on both escalations; settled entry pos 543350 for e5bd7694) — the 33815/33816 template-error class (claiming dissent where the record says concur) was checked for explicitly; all four rows carry kimi **concur**, none dissent.

## Closure
- Reply **34014** → cbp-being, bound to 34006, witness `b76efd781f8efd3be24a5ee0a7d484bdf0e7c4ff2acb1c93f498e5045f786d41`
- Reply **34015** → cbp-being, bound to 30412, witness `02482e20…` (chain pos 650259; CLI receipt lost to a parse error in my wrapper, recovered via `hestia_query_history` window scan)
- Reply **34016** → cbp-being, bound to 30423, witness `559c9ebb…` (pos 650265)
- Reply **34017** → cbp-being, bound to 30465, witness `8df8f73b…` (pos 650303)
- Reply **34018** → cbp-being, bound to 30658, witness `21581b97…` (pos 650306)
- Post-send `unanswered`: **i_owe: []**; owed_to_me steady 62 (both known non-actionable classes)
- Deploy vintage honored: `git log HEAD..origin/main` shows the same 3 member-mesh commits (e91ba6e2 / 1607ea22 / 97d3861e, print-only watcher + journal + auto-install) merged-not-executing plus gate/citizenship/grants work; none touch inbox eviction or the unanswered join, so the response-lifetime gap stands as documented — nothing attributed as a new defect.
- Incidental: gate denied one of this wake's Bash calls (`mrh.command.unenumerated`, `$m` variable in a loop) — rewritten as a literal Grep-tool call, the documented remedy. No scope request opened; none needed.
