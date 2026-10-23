# Held: #1377 follow-up. Tool roots removed; a toolchain is reached by grant (80600bf3…)

**Patch:** `held/80600bf347df9eb0a637f7c63da37be3ee1af1e56b757a820845f9b5b075d554.patch`
**Base:** #1377's head `3b98c318`, which applies `2a6c9ed0…`. **Not applied.**

## Why (Nova's HOLD on #1377, 2026-10-23)

`HESTIA_TOOL_ROOTS` came from the gate's environment and exempted any path under a named root
from MRH scope. Nova asked who can set it. Two things came out of that question.

1. **Provenance isn't closed.** The harness configs that can set a hook's environment are
   governance closure (`.claude/settings.json`, `.codex/config.toml`, …). But a seat's launch
   environment also comes from its systemd user unit, and on Legion `~/.config/systemd/user`
   is inside the seat's own grant.
2. **A symlink under the root reads an ungranted repo.** The exemption was lexical (`_under_any`
   on the normalized path), and the egress check before it only catches *forbidden* targets.
   Measured: with the variable set, `cat <root>/lib/escape/secret.md` was admitted, where
   `escape` → an ungranted repo. That row is a must-deny regression below.

## What the patch does

- **Deletes `TOOL_ROOTS_ENV`, `_tool_roots` and `_under_any`, and their use in pass 1.** The
  grep-family pattern handling is untouched.
- **The toolchain is reached by an operator's recursive grant, `path:<root>/**`.** It sits in the
  member's vault-held scope, it is witnessed and revocable, and `_within_path_grant` matches it
  on the **realpath**. That mechanism already existed; no new authority is added.
- **The test is renamed** to `tools/gate_grep_patterns_and_toolchain_grant_test.py`. Its
  toolchain section is rewritten:
  - with no grant, the interpreter is refused;
  - a recursive grant admits the `check`-shaped line (`bwrap --ro-bind`, interpreter, `--setenv PATH`);
  - operands outside the grant are still judged;
  - a sibling of the root is not under it;
  - an **exact** grant does not reach the interpreter;
  - **must deny:** a symlink under the granted root into an ungranted dir;
  - egress is judged before the grant;
  - **must deny:** `HESTIA_TOOL_ROOTS`, whether in the gate's environment or as a command prefix;
  - the core carries no tool-roots declaration.
- **Manifests** are republished (`hooks_gt.build`, check clean).

## Verified (staged core, nothing governed written)

- **New test:** all checks pass. **Control on #1377's core: 4 FAILED**, the symlink escape
  among them.
- **`mrh_scope_differential`:** 0 cells off their pin, 0 false negatives (unchanged).
- **Core suites:** `test_gate_core` all pass; `shell_grammar_test` OK; `seat_gate_boundary_test`
  17×4; sprintD 85/0; sprintE 9; sprintF 10.
- **Apply-check:** applies on `3b98c318` (temp index), and the staged core equals the patched tree's core.

## Operator follow-up after it is installed

Grant legion-being `path:/home/dp/miniforge3/**`, recursive, standing. Then rerun SAGE #441's replay.

— legion-claude
