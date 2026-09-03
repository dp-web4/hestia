# Review 9789: two independent paths make the disposition deliverer inert or lossy

Disposition: **DISSENT on correctness; no scope-safety objection to the copy itself.**

Notice 9789 asks for review of escalation `1bce91a7dc4cbe4a`.  The witness chain records
the exact act at open position 220053: copy `disposition_deliver.py` and its test into
`plugins/claude-code/hooks/` in the isolated `cbp/disposition-lane` worktree.  The operator
approved at 220056 and the asker claimed the grant at 220081.  The copied source and target
bytes match (`sha256` `767e696c...1076` for the hook and `06e47d6d...7d5` for the test).
The mutation is contained.  The artifact nevertheless does not provide the delivery it
claims, for two independent reasons.

## 1. A bystander session consumes the asker's ruling

`disposition_deliver.py:39-40` defines one cursor for the whole seat.  `deliverable()`
correctly skips a row whose `for_session` names another session (`:90-110`), but `main()`
then advances that shared cursor to end-of-file even when every row was skipped (`:120-129`).
The source comment at `:125-126` makes this deliberate.

Consequently the first hook event from *any* live session of `claude-code` consumes every
new row.  If session B fires before the addressed asker A, B prints nothing and moves the
cursor; A then sees no unread bytes and also prints nothing.  This defeats the mechanism's
central invariant: a same-seat bystander must not prevent delivery to the asker.

The supplied eight-arm test passes, but arm 3 constructs a fresh seat, lets the bystander
consume the row, asserts only that the bystander stayed silent, and destroys the seat.  It
never fires the intended asker afterward.  Reusing that exact harness exposes the loss:

```text
seat.write(line("APPROVED intended for asker"))
seat.context(session=OTHER)   -> (0, None)
seat.context(session=SESSION) -> (0, None)
```

I ran both checks against staged bytes `767e696c...1076`: the published test reports all
arms green, while this two-event sequence reports silence for the intended asker.

Minimal repair: key cursor state by `session_id` (using a stable digest in the filename),
so every session advances only its own view of the shared lane.  Add the two-event sequence
above as the sabotage arm.  A daemon-side per-session lane would also work, but is a larger
protocol change.  Merely declining to advance on foreign rows would preserve delivery but
would rescan the same prefix on every bystander event forever.

## 2. Nothing registers the new hook

The staged set contains only:

- `plugins/claude-code/hooks/disposition_deliver.py`;
- `plugins/claude-code/hooks/disposition_deliver_test.py`; and
- one new `install.files` entry in `plugins/claude-code/expects.json`.

There is no command referencing `disposition_deliver.py`.  The Claude plugin manifest still
registers only `pre_tool_use.py` for `PreToolUse` and `witness.py` for `PostToolUse`.
`expects.json` is not a registration surface: `deploy/install-members.sh:392-399` derives
registered basenames from the harness configuration and explicitly **skips** a declared file
whose basename is not already registered.  Therefore this branch can merge and deploy with
the hook absent from every event stream.  Its unit test executes the file directly, so it
cannot detect this integration failure.

Minimal repair: register the deliverer on at least one mid-turn event in the canonical
Claude hook manifest/configuration, and add a structural test proving the command is present
on the event(s) whose `additionalContext` shape the hook emits.  The intended three-event
coverage (`PreToolUse`, `PostToolUse`, `UserPromptSubmit`) should be declared and tested if it
is a requirement rather than a comment.

## Secondary bounded-backlog loss

`deliverable()` selects `lines[-MAX_LINES:]`, after which `main()` advances to end-of-file.
More than 20 unread rulings therefore discards the oldest rows permanently; it does not
deliver a backlog in bounded batches.  The supplied arm 8 expressly locks in that loss by
checking that row 59 survives without checking rows 0-39 on a later event.  Once cursors are
session-scoped, process the first bounded batch and advance only through the bytes actually
processed, then let the next event continue.

These are correctness failures in the refusal-channel itself.  The approved copy was safe
to perform, but the resulting artifact should not be represented as satisfying disposition
delivery until the registration and consumption invariants are repaired.
