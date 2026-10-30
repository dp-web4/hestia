# held: #1331 follow-ups, Gate 1a judges the links an act REACHES without naming them. **NOT applied.**

Patch: `held/67f6ba52d0f1525c95cf62ce0841c7e82a18640bbfe9214c3e8d9d1e41f6bb38.patch` (base main `5bc41374`, after #1433). **Re-cut 10-30 twice:** for nomad's review (`d24ad833`), then for Nova's (`67f6ba52`, bounded execution). `138e65d2…` and `d24ad833…` are kept beside it as superseded records. It covers the gate core, plus the hooks-gt mirror and the 5 manifests.

## The defect
#1433 judges a link's resolved target only when the act **names** the link. Measured on its applied core (10-28, posted on #1331), every *unnamed* shape still reached a secret-named target. The fixture is a fake `.ssh` file in a temp workspace. Shapes that still reached it:
- **globs and braces:** `cat *.txt`, `note?.txt`, `[n]otes.txt`, `keys/*` through a dir link, `sub/*`, `{notes,plain}.txt`;
- **a `cd`/`pushd` inside the line:** `cd sub && cat key.txt`, plus `;`, a subshell, and `pushd`;
- **readers that follow links while walking:** `grep -R`, `rg -L`, `find -L … -exec cat`, `cp -rL`, `tar -h`.

## The rule
`link_targets()` keeps its name and contract. It now returns `link_reach(event)[0]`:
- **Globs and braces:** an unquoted glob or brace word is expanded, and each match is judged as a named path. Braces are expanded by hand. Globs go through `_bounded_glob`: one component at a time, reading only the directories a wildcard component needs, matched with the core's `_GLOB_CHARS` and `_fnmatch`. Hidden names match only a dot-led component, as `glob` does.
- **Changing directory:** every relative word is judged against the cwd **and** every directory the line makes a cwd: `cd`/`pushd`, `env -C`/`--chdir`, `sudo -D`/`--chdir`.
- **Quoting:** only **unquoted** glob and brace words are expanded, as the shell does. A quoted pattern (`find clean -name '*.txt'`) is the program's, and is judged as written. Quoting is read by lexing the command twice, posix and raw. When the two don't align word-for-word, every word counts as unquoted, which only ever adds refusals.
- **Link-following readers:** the directories they read are walked by `_bounded_walk`, which never follows a link, and every link inside is judged. Flags were read from each tool's `--help`. The readers:
  - `grep -R`, `rg -L`, `find -L`, `cp -L`, `tar -h`, `bsdtar -L/-h`, `rsync -L/-k`, `cpio -L`;
  - **a `find` that `-exec`/`-execdir`/`-ok`s, with or without `-L`**: find lists links and the exec reader opens them;
  - **`zip` and `7z a`**, which follow by default unless `-y`/`--symlinks` (zip) or `-snl` (7z) store the link.

  find's start directories are the words before its first expression word.
- **Bounds, STRICT on the work, not only on the verdict (Nova's review):** every directory entry is read lazily through `os.scandir` and counted as it's read, so no act reads more than `LINK_WALK_LIMIT` (10,000) entries across its globs and walks, or collects more than `LINK_GLOB_LIMIT` (256) matches, before it stops. A directory it reaches that **cannot be read** stops it too, rather than being skipped. (`os.walk` skipped it silently, so that walk was allowed; measured below.) Past any of these, `egress_unsweepable_deny` refuses the act under the **existing `mrh.command.unenumerated` rule** with `UNENUMERATED_TARGET`, not judged in part. That's the same fail-closed shape as the scope pass's `SCOPE_JUDGE_BUDGET`. Labelled `egress.secret`, it had relabelled two battery rows that were already correctly refused as unenumerated (`cat /tmp/*/../../etc/hostname`, `S=/tmp/*; cat $S/x`).
- **Over-approximates by design.** The directories a line changes into apply to every word, not only those after the change. It can only *add* refusals, and only where a link really points at a secret-named target.
- **Not covered:** the `Grep`/`Glob` tools. Whether they read through links is the host's, and that's unmeasured (Q2 on #1331).

## Evidence (revised core served as `hestia_gate_core`)
- `held/build-1331f/link_reach_check.py` (39 rows) **PASS** on the revised core:
  - all 22 reach shapes are `egress.secret`, including nomad's `find sub -type l -exec cat`, `zip -r`, `7z a`, `env -C`, `env --chdir=` and `cd .. && cat hestia/notes.txt`;
  - 15 ordinary rows keep main's verdict, including nomad's quoted-pattern `find clean -name '*.txt' -exec cat`, `zip -ry`, `7z a -snl`, `git -C sub show HEAD:key.txt` (git prints the link text, not the target), and #1433's named link;
  - both overflow rows are `mrh.command.unenumerated`.
- On main's core it fails **exactly** the 22 reach and 2 overflow rows, and no ordinary row.
- **Bounded execution** (4 rows; every entry the gate reads is counted by wrapping `os.scandir` around `evaluate` only): a glob over one 12,000-entry directory, a `grep -R` over it, and a 300-match glob each read **at most 10,001** entries and are `mrh.command.unenumerated`. A `grep -R` over a directory holding an unreadable subdirectory is `mrh.command.unenumerated`.
  **On the previous cut `d24ad833`:** the glob and the walk each read **all 12,000** entries before refusing, and the unreadable subdirectory walk was **allowed** (`os.walk` swallows the error). That's the defect Nova named, measured.
- `test_gate_core` all pass. `tools/link_target_test.py` 6/3. `tools/egress_prose_test.py` 13/18. Shell-scope battery **1434 / 0**.
- **Latency** (median `evaluate` on ordinary commands over a 200-file repo; scratch fold, 10-29):
  - unchanged within noise without a glob, 0.1 to 0.3 ms;
  - a 200-match glob goes from 0.16 to 3.7 ms with the bounded glob (4.0 ms with `glob.glob` in the earlier cut), bounded by `LINK_GLOB_LIMIT`.
  - No wall-clock budget: the entry count is itself a strict work bound, since each entry costs constant work, and the core imports no clock.

The check is deliberately not test-shaped (`tools/ci_discovery.is_test_shaped`), so CI doesn't run it against the core it's written to fail on. It moves to `tools/link_reach_test.py` at the governed apply.

## Rebuild
```
python3 held/build-1331f/transform_1331f.py <worktree>         # source-1331f.diff from HEAD's core + new_block.py.txt
python3 held/build-1331f/build_1331f.py <worktree> <out dir>   # core_rev.py + <sha256>.patch, verified
python3 held/build-1331f/link_reach_check.py <out dir>         # PASS; with "" (main's core) it fails the reach/overflow rows
```
