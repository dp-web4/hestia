# held: hestia #1398, the write half — a narrowed floor entry serves the modes it holds

**Patch:** `070fa17f30645eb0b27ebfcbf0ce43a9e8af3c947fb90082f872f73aaefc41b9.patch`, cut by
`build-1398w/build_1398w.py` on main `2b3d0ca2` **plus part C (#1394, `source-1386.diff`) plus the read
half (#1406, `source-1398.diff`)**: it is the FOURTH patch in the held stack (#1407 → #1394 → #1406 → this)
and applies to the tree after those have landed. It changes the gate core and the mechanism, plus their
hooks-gt copies and the 5 manifests, every section a diff from that base. **Not applied:** it needs an
operator-approved escalation, after the three before it.

**Why.** On 2026-10-25 dp put `shared-context/forum` on the society floor as `rw`. The daemon served it
read-only (`society_floor_read`, the narrower-than-rwed rule), its `w` was never served, and dp had to give
cbp-being a live rwed grant to get it writing. The daemon already serves every floor entry with its modes
(`floor_by_mode`); no gate read it (gap 2 of #1398).

**What changes.**
- **Mechanism:** the snapshot reads `floor_by_mode` into `in_scope_floor_modes` — only NARROWED rows, by the
  same parsing rule as `grants_by_mode` (a row whose modes are not a non-empty proper subset of `rwed` is
  dropped whole). An all-modes entry is reach only when the daemon serves it as such (`society_floor`), or
  withheld for a reason this gate honours by not re-admitting it. Absent on an older daemon: a no-op.
- **Core, `AgentPolicy.floor_mode_scope`** (the `mode_scope` shape), and in `evaluate()`: the narrowed floor
  entries are grant nodes of their own, consulted **only for a path no node of the member's own covers**
  (part C's `_nearest_grant` over the member's full and narrowed nodes answers first — dp 10-23 on #1386:
  the floor fills only beyond the member's own grants). The nearest floor entry covering the path decides,
  in its modes: `rw` on the forum admits `Write`/`Edit`/`write_note`/`Read`/`Grep`, refuses `git_clean`
  (`d`), with a refusal that names the floor's modes (`_floor_hint`). An act that can reach below the path
  it names (part C v2's `SINGLE_TARGET_TOOLS` rule) still answers to every narrowed grant of the member's
  beneath it. For a shell line, the floor entries holding every mode the command needs are tried only after
  the member's own grants and the read floor did not admit it, and only for a command whose need can be
  named (a read, today); a line admitted that way then takes part C's reached-path walk, so a path under a
  grant of the member's own is decided by that grant, never by the floor.

**One deviation from the design comment on #1398** ("the union of the modes of the floor entries covering
the path"): the NEAREST floor entry decides, with the union only among entries at one depth — part C's rule
applied to the floor. Two floor entries nested at different depths with different modes is the same shape
as two grants nested, and should answer the same way.

**Tests**
- `held/build-1398w/floor_write_gate_test.py` (9): the row reaches the policy as `floor_mode_scope` only;
  `rw` admits writes/edits and refuses delete (and the shell: read line admitted, write lines refused); the
  floor fills only where no own grant reaches (own `r` on `forum/sub` decides its subtree, the floor serves
  `forum/z.md`); an own grant ABOVE the floor entry is not widened by it; a `Grep` on the forum is capped by
  an own `w`-only child, and so is a recursive shell read; an exact entry does not reach its children;
  malformed and all-mode rows admit nothing; an older daemon admits nothing extra; an `r` entry served both
  as `society_floor_read` and in `floor_by_mode` gives one answer. Passes on the stacked result; on part C
  alone 5 of 9 fail (the ones that need the change).
- On the stacked result (main + C + read half + this): #1394's `grant_precedence_gate_test` 11/11, #1406's
  `floor_composed_read_test` 1/1 (8 verdicts), #1394's own `tools/grant_modes_gate_test.py` 17/17 (main's
  copy shows its one canary flipped, `test_an_all_modes_floor_never_widens_a_narrowed_child_grant`, which
  is part C's doing and part C's branch updates), nonexistent_path 8, floor read-only 8, sprintD 91/0,
  sprintF 10, mechanism 34, seat boundary 17x4, closure 39, battery 1434/0, decide contract 25 (+29x4).

**Not in this change:** the daemon's `floor_for` withholding stays as it is (it protects mode-blind gates);
whether it can be relaxed once every gate applies #1386 is #1385's question. SAGE's dispatcher parity for
written floor paths (it sees read-floor roots as `r` since SAGE #533) is a follow-up on the SAGE side.
