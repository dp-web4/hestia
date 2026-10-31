# held: hestia #944, endpoint half — the gate never guesses the daemon's port

**Patch:** `423042d91f592e2de102e81dca549d1afbfa8ed1de13569c4eb024f6e920d613.patch`, cut by
`build-944e/build_944e.py` on main `242824cf`. It changes `plugins/_shared/hestia_gate_mechanism.py`, its
hooks-gt copy and the 5 manifests. **Not applied:** it needs an operator-approved escalation.

**Independent of the held stack** (#1407 → #1394 → #1406 → #1421): no source hunk overlaps theirs. The
manifests' digests do collide, so whichever lands second is re-cut by re-running its builder on the new
main. This builder applies the change by exact-once text replacement (`change.py`), so a re-cut is one
command:

    python3 held/build-944e/build_944e.py <hestia worktree at the new main> <out dir>

**Why.** `emit_attestation`, `gate_self_call` and `scope_call` read `HESTIA_ENDPOINT` and fell back to the
literal `http://127.0.0.1:7711/mcp`. On 2026-10-06 a CI harness ran gates with no projection; the decision
path refused, the side paths reached the live daemon, and four real escalations opened under codex's and
kimi-code's names (#1246). dp's #944 rule: no hardcoded configuration.

**What changes.** The three side paths use `_discover_endpoint()` (the env, then `$HESTIA_HOME/endpoint`),
which the decision path and the snapshot fetch already use, and return None when it finds nothing. Each
function's contract already reads None as "nothing was sent", so no caller changes. No `:7711` literal
remains in the mechanism.

**Fleet effect.** None on a configured seat: every seat whose decisions work already discovers an endpoint,
and the side paths now find the same one. A seat with no endpoint already has every decision refused; it now
also stops sending side traffic to whatever owns :7711.

**Tests**
- `build-944e/endpoint_fallback_test.py` (5 rows), run against a mechanism file named by
  `HESTIA_MECH_UNDER_TEST`. **Main: 1 passed, 4 failed** (all three side paths sent to :7711; the endpoint
  file was ignored; the literal is present). **Held result: 5 passed.**
- `build-944e/run_suites.py` runs existing suites with the held mechanism pre-loaded. Same results on held
  and on main: hestia_gate_mechanism (34), seat_gate_boundary (17 × 4 seats), sprintE (9), sprintF (10),
  claim_self_write (45/45), witness_receipt, witness_core, shim_structure (86/86), tools/attempted_summary.

**Not in this patch** (the rest of #944): `law_inject.py` and `hestia-mesh.py` in hooks-gt carry the same
env-or-:7711 default, and the plugin SDKs, CLI flags and deploy scripts carry `:7711` defaults. Those are
separate surfaces; the gate side paths were the ones that caused #1246.
