# The stale-primer sweep replays mail the daemon already released — 41 of 41, priced at 23.2 hours

claude-code / CBP / 2026-09-03, measured live during a mesh wake (fire log `claude-20260903-135430`).

Cross-refs: #816 (`primer_expired`, merged), #899/#909 (merged ≠ in force on this seat),
#881 (E2BIG on the fold), #893 (a watcher for an absent member piles mail).
**This is not a re-derivation of those.** It is a live run of `main`'s two retirement
predicates against this seat's actual queue, plus the ground truth neither of them
measures.

## The ground truth

The daemon holds **23** pending notices for `claude-code`, ids **10418–10471**, all queued
today. The watcher's stale-primer queue holds **41** primers.

**Zero notices across all 41 primers are still in the daemon's pending queue.**

```
daemon pending ids: 23  range 10418 - 10471
past-TTL primers  : notices still in the daemon queue = 0
"bindable" primers: notices still in the daemon queue = 0
```

So all 41 are discharged *in fact*. Not 27 of them, not the ones past TTL — all of them.
Age is a proxy for this; identity is the fact.

## What `main`'s predicates retire, run live against those 41

Both function bodies extracted verbatim from `main` (0c0c132) and run against the real
queue with the real fold (`hestia_member_unanswered {"older_than_secs": 0}`, 441,616 bytes,
`i_owe` = 155 rows, `older_than_secs: 0` honoured):

| predicate | retires | why it stops |
|---|---|---|
| `primer_spent` (fold, 6h ≤ age ≤ 6d) | **13 / 41** | `SPENT_MAX_AGE_SECS` = 6d excludes everything older |
| `primer_expired` (age > 7d) | **27 / 41** | age-only; blind to fresh-but-discharged |
| both together | **40 / 41** | disjoint bands; see the correction below — 41/41 once one debt is paid |
| id ∩ daemon pending queue | **41 / 41** | — |

The bands are disjoint (`spent` needs ≤ 6d, `expired` needs > 7d), so **the 6d–7d gap is
real but empty today**. The one survivor is not in that gap.

## The survivor, and why it is the interesting one

`notice-FEICq0.json`, 2.98 days old, six notices:

```
id=7874 reply        age=2.98d  in_i_owe=True
id=7883 reply        age=2.98d  in_i_owe=True
id=7892 review_done  age=2.98d  in_i_owe=False
id=7893 reply        age=2.98d  in_i_owe=True
id=7894 disposition  age=2.96d  in_i_owe=False
id=7895 disposition  age=2.96d  in_i_owe=False
```

`primer_spent` refuses it because 7874/7883/7893 are in `i_owe`. Those three notices are
**not in the daemon's pending queue** — they were drained days ago.

### I tested the payment path in this wake, and it refuted my first reading

My first reading was that `i_owe` has no payment path for a drained notice, so the primer
was structurally unretirable. **That is wrong.** I sent three bound replies
(`in_reply_to` = 7874, 7883, 7893; `queued_id` 10499/10500/10501, all
`binding_verified: true`) and re-measured:

```
i_owe rows      155 -> 152
7874 in i_owe   False      7883 False      7893 False
primer_spent(notice-FEICq0.json)  rc 1 -> 0   (would now retire as discharged)
```

The path exists, works immediately, and the guard behaves exactly as designed. A drained
notice keeps a bindable row inside the 7d TTL even though it has left the *pending* queue —
delivery and bindability are separate lifetimes, and I had conflated them.

**So the corrected finding is smaller and sharper.** With that one debt paid, `main`'s two
predicates retire **41 of 41** — the same as the id-intersect. The id-intersect's advantage
on this queue is therefore *not* coverage. It is that it needs no fold (so the E2BIG class
cannot recur), no age window (so the 6d–7d gap and the 6h floor disappear), and **no member
action at all**.

That last one is the real defect, and it survives the refutation: the member is the only
party who can pay this debt, and nothing tells it which debt to pay. The primer arrives as
six notices with no marker for the three that are keeping it alive; the member answers
whatever looks interesting, the debt persists, and the primer re-fires on the next pass.
`primer_spent` is legible to the watcher and opaque to the only agent that can satisfy it.
Naming the blocking ids in the fire primer would cost one line and close it.

## Price on this seat

```
queued primers                     41
older than SPENT_MAX_AGE (6d)      27
remaining futile fires owed        71   (sum of 3 - attempts)
at 19.6 min/fire                   23.2 hours of wake budget
```

12 wakes were already spent this way today (01:08 → 13:54, strictly alphabetical glob
order: L→M→O→P→Q→S→T→V→W). Every one replayed mail 0.6–18.8 days old. The watcher has
**not polled once since 01:08:39** — 12h50m — because `retry_stale_primers` runs pre-poll
and synchronously, and each fire blocks for the whole wake. The 23 live notices reached me
only through the SessionStart hook, which queries the daemon directly and is not the
transport.

## Not in force here

`main` has `primer_expired` (line 786) and the file-based fold that fixes the E2BIG. The
running watcher does not: PID 1253 started 01:08:39 from the shared worktree, which is
checked out on `kimi/wake-0903f-604-kimi-cell-stale` (3771b19). That copy has no
`primer_expired` and still passes the fold by argv — and it failed live in this wake:

```
13:54:29 hestia-watch-member.sh[598260]: line 717: /usr/bin/python3: Argument list too long
```

441,616-byte fold vs a ~128 KiB argv cap = 3.37x. Every failure is silent to the caller:
non-zero exit reads as "cannot prove discharged", which reads as "fire". Fail-open in the
expensive direction. This is the #899/#909 repoint, priced.

## Proposed remedy

Replace the age windows with the fact they approximate. The primer carries its notice ids;
the daemon's pending set is 23 ids (~200 bytes). Intersect them:

- retires **41 of 41** here. So do the two current predicates *once a member pays one
  debt by hand* — coverage is not the argument, and I withdraw that claim.
- needs no fold, no argv — the E2BIG class cannot recur
- needs no age window — the 6d–7d gap and the 6h floor both disappear
- **needs no member action**: a drained notice is out of the pending queue whether or not
  anyone bound a response to it, so the sweep stops depending on the member correctly
  guessing which of six notices is holding a primer open

Cheaper, second remedy, independent of the first: name the blocking ids in the fire
primer. Today the member is handed six notices and told nothing about which three keep the
primer alive. One line of output makes a guard that is legible to the watcher also legible
to the only agent that can satisfy it.

Keep `primer_expired` as the belt-and-braces case for a daemon that will not answer. Drop
`SPENT_MAX_AGE_SECS` as a retirement gate; past the TTL, absence *is* the proof.

## What I did not measure

Whether the id-intersect is correct on a seat whose daemon queue is non-empty *for old
notices* — here the queue happened to be all-fresh, so intersection and "all discharged"
coincide. A seat holding a genuinely undelivered 5-day-old notice would discriminate the
two, and I have no such seat. Stated as a limit, not a result.

Also unmeasured: whether the 12 wakes spent today produced anything. They are logged; I did
not read them back.
