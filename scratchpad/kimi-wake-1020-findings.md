# wake-1020 findings — the five-day outage and the 276-row wall

Date: 2026-10-20 (CBT session, interactive with dp). Seat down 2026-10-15 → 10-20:
every fired wake died on `429 weekly usage limit` (fire log kimi-20261020-094117).

## The debt, measured

- Primer fold at wake: **148 i_owe** rows, all transient (145 `scope#peer-decide`,
  3 `escalation#corroborate-or-dissent`).
- Live census (`unanswered 0`) after clearing 134: **130 remained** — rows queued
  Oct 19–20 never entered any primer I saw (each fired wake drained its batch, died
  on the 429, retained the primer; nobody ever rendered those rows to a live session).
- Total outage debt ≈ **276 transient rows**. Non-transient rows: **zero**.

## The cleanup, measured

- v1: 134/148 ok, paced 21s. 14 refused `hestia.member_notify_rate_limited` — my
  flood matcher matched on "flood"; the guard's code says otherwise. Recorded.
- v2: 85/128 ok at 25s pace (no refusals), then the process **died silently at
  ~32 min** — no exception record in the JSONL; externally killed, cause unknown.
  Per-send op-ids made re-drive safe.
- v3: 44/44 ok, including one row that arrived mid-flight (live re-census, not the
  stale snapshot). `i_owe 0` verified at 12:1x.
- Peers acked the terminal replies as they landed (claude-code bound acks within
  minutes) — `owed_to_me` self-discharged 143 → falling.

## Live duty performed

- scope-92649ad791e8 (codex, readlink of installed hestia binary): granted-once,
  cross-vendor, race won.
- scope-019d03a55b0c (claude-code, Thunderbird ImapMail dir listing): granted-once,
  listing-only reasoning stated; personal-profile content paths belong to the operator.
- scope-4148fa647a1e (codex, ~/.local/bin glob): concur with peer:claude-code's
  refusal — the #1310 trap again (mesh CLI is the repo file; #1326 merged not deployed).
- escalation e1781889edbb726c: concur (operator-approved internal copy).
- escalation 78fcba4bcf3bc63f: abstained — patch bytes and target repo (hooks-gt)
  unreachable from my scope; codex's cross-vendor verification (reconstructed
  classifier, sha256 match, 57 tests run) stands; not a dissent.

## Lessons pinned

1. **6h default hid the wall from the dying seat.** MEMBER_UNANSWERED_DEFAULT_SECS=21600;
   wakes 1015–1019 truthfully measured `i_owe 0` under the default while the backlog
   grew. The primer fold (older_than_secs=0) was the only place the truth rendered.
2. **reply is a debt-bearing kind.** MEMBER_KINDS_AWAIT_RESPONSE = [review_request,
   reply]: each of my 276 terminal `reply`s entered my own owed_to_me until a peer
   acked. `ack` was the zero-debt kind for terminal notices. On a quieter mesh this
   manufactures standing self-debt.
3. **Self-inflicted deny repeated:** `$M` shell variable in a send command hit
   `mrh.command.unenumerated` — one wake after wake-1019's commit recorded the exact
   same lesson. Documented ≠ learned. Literal paths now.
4. dp's `/home/dp/.local/bin` once-grant (scope-e3c17c6c9383) claimed and spent on the
   original act; scope-a2bba523aa89 (~/.local/state/hestia-mesh, opened by a grep I
   didn't need) left to lapse.

## Artifact

Issue dp-web4/hestia#1354 (transient obligations outlive their targets) filed with the
measured case; implementation slice on branch `kimi/1354-moot-transient-debt`
(read-time moot derivation in `tool_member_unanswered`, no sweep, no schema change,
six-arm test + KINDS.md paragraph).
