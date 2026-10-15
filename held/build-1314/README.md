# Rebuild scripts for the #1314 held patch (68e951fc round)

These scripts are kept here because the scratch copies of earlier rounds were wiped. All of them work in `/tmp/s1314e`.

1. `apply.py`: extracts the previous held patch (saved as `held.txt`) and applies it in memory to `2d79644f` text, writing `core_held.py`, `battery_held.py`, `contract_held.py` and the `*_main.py` copies.
2. `edit_core.py` and `edit_battery.py`: this round's edits, as exact-once replaces on the held copies, producing `core_rev.py` and `battery_rev.py`.
3. `sep.sh`: runs the revised battery against the rev, held and main cores, using `HESTIA_SCOPE_BATTERY_CORE`.
4. `contract.sh`: runs the decide contract from a clean base worktree, with the core given as `HESTIA_CONTRACT_OVERLAY`.
5. `emit.py`: runs `hooks_gt.emit_patch` with `read_bytes` serving the core from /tmp, adds difflib diffs, and names the file by its sha256.
6. `verify.py`: applies the new patch in memory and checks that every file reproduces.

None of these writes a governed path.
