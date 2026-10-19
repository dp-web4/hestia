# held/: a first-class `egress` field, swept by Gate 1a, never scoped by Gate 1b (#1201), NOT applied

| file | sha256 |
|---|---|
| `7d2566b39572740f600516825aefb960d65e58846e75fe251028dda5a7a35093.patch` | `7d2566b39572740f600516825aefb960d65e58846e75fe251028dda5a7a35093` (base main `ee7f00d8`) **current** |
| `6641c071…patch` (base `9b4147bc`) | superseded: NOVA HOLD at 7a6e410b, and its manifest hunks no longer apply after #1343 |

**Files:** the gate core and the single gate, their hooks-gt copies and manifests, and the decide contract test. 10 files, +336 −37.

## v2: the NOVA HOLD at 7a6e410b

**The hold:** `egress_surfaces()` / `egress_blobs()` ran `list(...)` over the declared value. A bare string naming an ssh
key became one-character blobs that match no token, so the act was **allowed**.

**The fix: one normalizer, in the core, used by both files.**
- `hestia_gate_core.egress_items(value)`: a string is ONE blob. A list or tuple contributes its strings, flattened
  through nested lists and tuples, and `None` entries are skipped. Anything else (a dict, bytes, a number, a set, a
  generator, or a list holding one) returns `None`: it cannot be swept.
- **Fail closed:** `egress_unsweepable_deny(event)` returns the innate `egress.secret` deny for unsweepable egress,
  with its type named in the reason. It runs before the token sweep at both Gate 1a sites (`evaluate`,
  `degraded_verdict`) and in the single gate's `_egress_precheck`.
- **The single gate** takes its declared part from `core.egress_items`. Unsweepable egress is handed to the core
  **whole**, so the core refuses it on its own, in degraded mode too.

**New contract cells (in `test_declared_egress_is_swept_and_never_scoped`):**
- A secret as a bare `str`, as a nested list and as a tuple, run through 4 seats' `decide`, through the handoff to the
  core (which must receive it whole), and through the core's `evaluate` and `degraded_verdict`. Every case is denied.
- A benign bare `str`: allowed and never scoped, in 4 seats and in both core sites.
- Unsweepable, with benign text inside (dict, bytes, int, set, generator, list-with-dict): fails closed in 4 seats'
  `decide`, in both core sites, and in the core alone after the single gate's handoff.

**v2 evidence (on main `ee7f00d8`, scratch copies through `HESTIA_CONTRACT_OVERLAY`):**

| check | result |
|---|---|
| decide contract test | every cell passes except `scope-sinks-allowed`/`-open-nothing`, which **unpatched main fails identically in the same `/tmp` worktree** (the test treats `/tmp/x` as an outside path, and the worktree is itself under `/tmp`) |
| M4: a string is iterated by character (the original bug) | 43 red |
| M5: unsweepable egress is dropped instead of refused | 42 red |
| M6: `degraded_verdict` skips the fail-closed check | 6 red (all the degraded unsweepable cells) |
| M7: the single gate keeps `_leaves(list(...))` | 11 red + the test raises TypeError |
| `tools/shell_scope_reach_battery_test.py` | 1434 passed, 0 failed |
| `plugins/_shared/test_gate_core.py` (scratch core preloaded) | all checks pass |
| `tools/hooks_gt.py check` on the post-patch tree (in memory) | no findings |
| `git apply --check` on a pristine `ee7f00d8` worktree | clean |

The sections below describe v1 and still hold, apart from the normalizer above.
The hooks-gt half was emitted by `tools/hooks_gt.emit_patch`, which read the two scratch sources through
`Path.read_bytes`. The scratch copies lived under `/tmp` with names that match no governed marker, so no governed file was written.
Nothing here is applied.

## The problem

Text that leaves the machine had no field of its own:

- **A SAGE being's `web_search` query** (SAGE #335):
  - Composed as a command, its words were read as paths ("'models' is not granted").
  - Uncomposed, it rides in `tool_input`, and nothing sweeps it: the single gate's `egress_surfaces` finds web tools **by
    name**, and `web_search` is not one of the names.
  - **Measured on main `9b4147bc`, this test's first cell:** a `web_search` whose declared query names an ssh key is
    **allowed** (`gate.allow`).
  - SAGE #335 sweeps the query itself, as a stopgap, with a client-local copy of `forbidden_tokens()`. dp and NOVA parked it on this issue rather than keep that fork.
- **A remote model's prompt** (#1338) is the same contract: text that leaves the machine. #1338 adds destination, classification and receipt around it.

## The change

**`hestia_gate_core.NormalizedEvent.egress: list = []`**
- Text that leaves the machine.
- `egress_blobs(event)` is the one list Gate 1a sweeps: paths + repos + egress + command. Both Gate 1a sites use it, `evaluate()` and `degraded_verdict()`, so the degraded mode sweeps egress too.
- Gate 1b never reads the field.

**`hestia_single_gate.GateEvent.egress: list = []`**
- The invoker's declaration, for acts no harness tool name describes.
- `egress_surfaces()` puts the declared list first, before the web-tool and MCP-context surfaces it already finds.
- `normalized_event()` hands that same list to the core as `NormalizedEvent.egress`.

**Properties:**
- **It can only add a deny.** Declaring egress never lifts anything, and an event that declares none is judged exactly as before.
- `getattr` defaults keep callers whose event shapes predate the field, such as SAGE's test fakes, working.

**Not changed:**
- `_egress_precheck` still runs. The migration cells below show the core now denies the web-tool surfaces **on its own**, so deleting the precheck later moves no verdict. That deletion is left for its own reviewed change.
- `web_search` is not added to the name list: the declared field is the contract.

## Evidence

All checks ran from the live repo, with `HESTIA_CONTRACT_OVERLAY` / `HESTIA_SCOPE_BATTERY_CORE` pointing at the scratch copies.

| check | result |
|---|---|
| `tools/one_gate_decide_contract_test.py` (new `test_declared_egress_is_swept_and_never_scoped`) | **PASS** (24 + shim parity 29x4) |
| the same test on main's gate (control) | **FAIL**: claude-code's declared secret query is *allowed*, then `NormalizedEvent` has no `egress` |
| M1: the core stops sweeping `egress` | 5 red: core evaluate + degraded, the three migration cells |
| M2: the single gate stops handing egress to the core | 7 red: reaches-the-core x4 seats, the three migration cells. The decide cells stay green, because the precheck still denies; that is why the handoff has its own cells. |
| M3: Gate 1b scopes egress as paths | 4 red: benign-never-scoped x4 seats (`mrh.path`) |
| `tools/shell_scope_reach_battery_test.py` | 1434 passed, 0 failed |
| `plugins/_shared/test_gate_core.py` (scratch core preloaded) | all checks pass |
| `tools/hooks_gt.py check` on the post-patch tree (in memory) | no findings |
| `git apply --check` on main `9b4147bc` | clean |

**About M3:** the first benign query (`"qwen models weights /etc/ollama ..."`) let M3 survive. Read as one path, it resolves *inside* the repo and is in scope. The fixture now starts with an absolute path outside every scope, so any stage that reads egress as a path is refused visibly.

`plugins/gemini/tests/gate_holes_test.py` fails 2 cells (`read_file ../private-context`, `read_many_files include=../private-context/**`). It fails them identically on unpatched main, so this is the Legion seat's own grants, not this change.

**Not run here:** CI's full Python set. CI runs it on the apply PR.

## After applying

- **SAGE #335:** pass `egress=[query]` on the `GateEvent` (or on `NormalizedEvent` in the local-law path), then delete the client-local `forbidden_tokens()` sweep and its `egress.unswept` refusal.
- **#1338:** build the remote-cognition pre-egress gate on this field.
- **Housekeeping:** delete `held/7d2566b3…patch` and this README in the commit that applies it.

— legion-claude
