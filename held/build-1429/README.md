# held: #1429, a relative word landing inside the workspace after `cd` gets the in-workspace rule. **NOT applied.**

Patch: `held/278f76a6ffdbb26a90b7087bf8c6500dcca5406126caa493cccc755fd1a420f6.patch` (base `4a775cd1`): the gate core, plus the hooks-gt mirror and the 5 manifests.

| lineage | status |
|---|---|
| `held/lineage/a0619365…patch` | **superseded**: hub's review found that `normpath` cancels `link/..` on the text while the kernel follows the link first, so `cd membot && cat linkdir/../notgranted/data.txt` was judged as `membot` (today's core allows it too). Reference only |
| `held/lineage/79b60b56…patch` | **superseded**. nomad's review (GO on the change) found an adjacent gap that predates it: a `cd` **into** a directory link inside a granted repo was not judged where it lands, so `cd <granted>/linkdir && cat data.txt` (linkdir → an ungranted repo) was allowed, on today's core too. Reference only |

## The defect (measured offline on McNugget, 2026-10-30, against the gate's own `command_scope_reach`)
The same venv binary in a granted repo gets opposite verdicts, depending only on how it's spelled:

| command | today |
|---|---|
| `<ws>/membot/.venv/bin/python -c 1` | allowed (pass 1, #953's link allowance) |
| `membot/.venv/bin/python -c 1` (cwd = ws) | allowed |
| `cd <ws>/membot && .venv/bin/python -c 1` | **refused, `/usr/bin/python3`** |

That's HUB's report on #1429, where dp had to grant `/usr/bin/python3.14`.

**Mechanism.** In pass 3 of `_command_scope_reach_one`, a `dir` candidate (a relative word landing under a `cd` target) had **no inside-the-workspace branch**. It went straight to `_outside_reach_refused`, which realpaths the landing and judges the target as if it were outside the workspace. #953's link allowance never applied to that spelling.

## The rule
In the `kind == "dir"` branch, a landing **inside** the workspace is judged by pass 1's rule for an in-workspace token:
1. **Egress first:** `_symlink_target_forbidden`. A link into `.ssh/…` stays refused.
2. **The grant:** if the landing's repo segment is not granted, `_symlinked_reach_verdict` decides (and names the right repo).
3. **A link inside a granted repo is judged where it lands** (`_symlinked_reach_verdict`). A target in an ungranted repo is refused, as today's outside rule refused it. A target outside the workspace gets #953's allowance: that's the venv interpreter.

5. **The kernel's landing, not the text's** (hub's review): relative-after-`cd` candidates and `cd` destinations are built from the **raw** join (`_raw_dir_bases`, no `normpath`). The grant and egress are judged on `realpath` of that raw path whenever it differs from the lexical form. So `linkdir/..` is resolved after the link, as the kernel does.

4. **A `cd` destination that is a link inside the workspace is judged where it lands** (nomad's review), by the same #953 rule: egress first, then the target's repo. This applies to every literal `cd` destination, whether or not a relative word follows, because a bare word after `cd` (`cat data.txt`) is not a path candidate. This **tightens** today's core, which allows that read.

Landings **outside** the workspace keep today's rule (`cd /tmp && cat ../etc/x` is still judged at `/etc/x`).

## Evidence (revised core served as `hestia_gate_core`)
- **`held/build-1429/dir_landing_test.py`: PASS** (6 allow, 18 deny). On today's core it fails **exactly 8 rows**: the 3 relative-after-`cd` allow rows (refused as `/usr/bin/python3`), plus 5 link rows that today's core wrongly **allows**. Those are nomad's 2 `cd`-into-a-dir-link rows, hub's `linkdir/../notgranted`, and two `cd` targets containing `linkdir/../notgranted`.
  - Allow: the venv interpreter by absolute path (unchanged); `cd <repo> && .venv/bin/python`; `./.venv/bin/python`; a plain in-repo file after `cd`.
  - Deny:
    - a link to a forbidden `.ssh` target after `cd` (egress first);
    - a link from a granted repo into an ungranted one;
    - an ungranted repo after `cd`;
    - a `../..` escape out of the workspace.
  - Nomad's rows (deny):
    - a dir link mid-path into an ungranted repo;
    - a dir link mid-path to `.ssh`;
    - `cd` into a `.ssh` dir link, then a bare word;
    - `sub/../../notgranted`;
    - a second `cd` into an ungranted repo;
    - `cd ;`, `pushd`, and a subshell `cd`, each with a link;
    - **`cd` into a dir link to an ungranted repo, then a bare word**, and the same reached via a second `cd`.
  - Allow: `cd` into a real subdirectory, then a bare word; `sub/../sub/own.txt` (a `..` through a real dir stays in the granted repo).
  - Hub's rows (deny): `cd membot && cat linkdir/../notgranted/data.txt`, `cd membot/linkdir && cat ../notgranted/data.txt`; and the author's: `cd membot/linkdir/../notgranted` then `./data.txt` or a bare word.
- **Out of scope here, filed as #1455:** the same `link/..` misjudgement in **pass 1** (absolute paths). `cat <ws>/membot/linkdir/../notgranted/data.txt` is allowed on today's core and on this patch alike. It needs its own held patch.
  - The fixture is built beside the test, not under a temp root (temp roots are always reachable, which would make every row pass), and removed afterwards.
- **A first cut was wrong and the test caught it.** It skipped every check when the landing's own repo was granted, which let `cd <granted> && cat ./peek` (a link into an ungranted repo) through. Today's core refuses that. Step 3 above closes it.
- Shell-scope battery: **1431 / 3 on both cores**, with the same 3 rows (macOS `/var/folders` temp cases on this box).
- All 116 `plugins/_shared/*test*.py` + `tools/*_test.py` under both cores: **114 identical**. The 2 that differ are `hooks_gt_test` / `hooks_gt_candidate_test`, which report the core as *unpublished* under the overlay; this patch's own mirror satisfies them.

## Sequencing
#1453 (#1330's second half) and #1435 (Legion) are also held Gate 1a patches carrying the same mirror and manifests. Whichever lands later must be re-cut on the new main (`build_1429.py <worktree> <out>`). The core hunks don't overlap.

## Running it
- Cut / re-cut: `build_1429.py <worktree> <out>`. It reads `source-1429.diff`.
- Tests: `python3 held/build-1429/dir_landing_test.py <dir with core_rev.py>`; with no argument it loads the real module.
