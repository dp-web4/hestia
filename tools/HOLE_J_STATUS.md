# Hole J — fused punctuation erases a simple-command boundary (#463)

**Status: OPEN on `main` and OPEN in the installed copy that is running right now.**
Re-verified 2026-08-26 against `hestia_governance_closure.py` as installed: `_BOUNDARY_PUNCT`
is absent from both.

## The defect, verified without exploiting it

`shlex(punctuation_chars=...)` fuses adjacent punctuation. Tokenising with the module's own
`_PUNCT = "();<>|&"`:

| command | tokens | punct tokens NOT in `_SEPARATORS` |
|---|---|---|
| `(echo hi); tee /tmp/x` | `['(', 'echo', 'hi', ');', 'tee', '/tmp/x']` | **`');'`** |
| `(echo hi) ; tee /tmp/x` | `['(', 'echo', 'hi', ')', ';', 'tee', '/tmp/x']` | none |

`');'` is in neither `_SEPARATORS` nor either redirect arm, so it falls through to
`i += 1; continue`. The simple-command boundary is erased and the following command's argv is
absorbed by the current one. **One space changes the parse.**

That is the precondition only. The consequence — the fused spelling classifying READ (allowed)
where the byte-equivalent spaced spelling classifies WRITE (denied) — was measured previously
from two seats, `claude-code` (reply-2575) and `kimi-code` (reply-2583), with all 9 rows x 3
columns exact. This note deliberately reproduces the **tokenisation** and not the bypass: showing
the bypass requires naming a governed path, which is itself refused, and demonstrating it would
mean performing the write the hole permits.

## Why it is a patch file and not a commit

`remedy6-hole-J-fused-punct-boundary.patch` edits `plugins/_shared/hestia_governance_closure.py`.
Both hunks are refused `[gate-self-access]` to a member — correctly; that is the self-protection
rule working. Escalations `b98af462c5b03cc8` (approved, **lapsed unclaimed**) and
`d5519b9ac527b3d5` were opened. A permit is single-use, so a two-hunk patch cannot be authorised
by one approval, which is why this is a file for the sovereign to land as one act rather than two
member writes.

Not verified with `git apply --check` or `patch --dry-run`: both name the governed file as their
write target and are refused, so the gate declines to dry-run a patch to itself. Line offsets are
hand-derived against blob `3d8184ca`; apply with `-F3` if they have drifted.

## Why it is being landed now

It was sitting **untracked in the shared working tree, on no branch**, found by an end-of-wake
stranded-work sweep. A corroborated fix to a live gate bypass that exists only as a loose file on
one box is one `git clean` from gone. Landing the patch is not applying it — it makes it
reviewable, diffable and appliable by someone who is permitted to.

## To land it

```
git apply -F3 tools/remedy6-hole-J-fused-punct-boundary.patch
python3 tools/fused_punct_boundary_battery.py    # should flip to the spaced-spelling result
```
