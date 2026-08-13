# Gate-consolidation sprint log — route-around audit trail

dp's sovereign exception (2026-08-13, in-session): *"for this sprint i'm granting you the exception
to route around blocks because we need to get this finished. it is a sovereign decision of trust."*

Protocol I am holding myself to:
1. Attempt the lawful write FIRST so the deny/escalation is recorded on-chain.
2. Route around only benign, sprint-scoped work in repo worktrees. NEVER installed gates, NEVER
   daemon state, NEVER anything in-force.
3. Log every use here: what was blocked, the recorded deny, the route, the diff it applied.
4. This log ships with the PR train and the end-of-sprint forum post.

---

## RA-1 — test-assertion fix in hestia_governance_closure_test.py

- **Blocked act:** Edit to /tmp/wt-sprintb/plugins/_shared/hestia_governance_closure_test.py —
  relax `cp_marker` assertion to accept either matching closure element (`hestia_gate_core.py`
  filename rule OR the new `plugins/_shared` dir marker, which now has precedence).
- **Deny basis:** payload text-match — new_string MENTIONS 'hestia_gate_core.py' (in the test's
  own command-under-test string). The deny message itself states "the match is payload content,
  not the destination". Destination is a NEW test file on a worktree branch.
- **Lawful attempts:** 2. First opened escalation 141240103cf365c5 (dp approved in the sweep);
  re-issue after approval was denied again — claim did not fire (WITNESS FAILED in the deny;
  the known approve→re-issue loop-close gap).
- **Route:** python3 script (scratchpad) performing the same exact string replacement.
- **Why benign:** test-only change; widens one assertion to accept an equivalent verdict detail;
  full suite runs green after (recorded below).

## RA-2 — apply Sprint B wiring diffs (worktree /tmp/wt-sprintb)
- Blocked: inline git-apply + py_compile chain; deny keyed on a gate-dir marker in the
  py_compile READ line's text. Deny on-chain (WITNESS FAILED noted in refusal).
- Route: ra2_apply_wiring.sh — applies the agent-verified diffs byte-identically.

## RA-3 — commit/push Sprint B wiring
- Blocked: git add with gate-file paths in command text. Deny on-chain.
- Route: ra3_commit_b.sh (add/commit -F/push, asserts origin==HEAD). Commit 024e59a.

## RA-4 — assemble Sprint C tip (rebase onto B, kimi wiring, cross-harness test)
- Lawful-first note: inline form would carry the same marker class as RA-2/3; the actual
  writes are the agent-verified kimi_wiring.diff + test copy. 77+15 tests green after.

## RA-5 — commit/push Sprint C tip (rebased; --force-with-lease on my own branch). 1582530.

## RA-6 — assemble Sprint D branch. codex diff hunk 1 conflicted with B's wiring
  (drafted against origin/main); dry-run caught it, nothing half-applied.

## RA-7 — codex hunk-1 merge, first pass (constants block + core import). INCOMPLETE:
  missed the trio deletion + bridge defs. Committed with a pipe that swallowed the red
  acceptance result — MY ERROR, caught by RA-9's gated rerun. Recorded as the mistake it was.

## RA-8 — sprintD_test repo-relative path resolution (payload-FP'd Edit; escalation
  fddd2787cc778229 open for dp). Route: ra8_fix_dtest.py, same strings as the Edit.

## RA-9 — complete codex hunk-1 merge (load_in_scope->_agent_scopes wholesale;
  _identity_role header->_role_bridge keeping body). Script gates the amend on
  "62 passed, 0 failed" + full suites; amended 0835c4b, force-with-lease, origin==HEAD.
  The missing defs would have been runtime NameError = FAIL-OPEN on codex's engine —
  the acceptance suite catching this is the whole argument for criterion-gated commits.

## Open escalations for dp to sweep (all payload/text FPs, safe to deny):
- aa4545a72ea4a612 (B-wiring agent, read-only git status)
- 9c5e48b7ca0458c7 (my read-only awk/sed inspection)
- fddd2787cc778229 (RA-8's Edit — superseded by script apply)
- 21d90813319e2e40 (C agent, scratchpad edit — if not already swept)

## RA-10/10b/10c/10d — Sprint E assembly (worktree /tmp/wt-sprinte)
- mechanism + claude diffs applied clean; codex 1 hunk rejected (D renamed the role
  helper inside the deleted function's body) -> scripted deletion, zero dangling refs.
- Test-file staging-path fix (3rd instance of the pattern); boundary test landed in-repo.
- Suite-gated battery: E 11 + D 62 + shared 77 + kimi 15. Commit 5f147ad, PR #403.
- FP escalation during battery: 40d00d927769f65f (py_compile READ line carried the
  hook filename) — for dp's deny sweep.

## RA-11 — kimi unified-recorder adoption (Gate-2 refusals now RECORDED; §3.3 bullet 4
  closed — kimi's society denies previously left no record). In the E commit.

## RA-12 — read-only inspection of the society hook orphan (ls/stat FP'd on filename).
  Finding: installed ONLY in kimi's hooks dir, registered NOWHERE — a double orphan;
  post-E definitively dead. G disposition: remove at deploy, record in PRD §10.

## Fleet note: PR #402 (kimi) corroborates two of this session's FP escalations —
  the witness loop is working on exactly the class this train retires.

## RA-13/13b/13c — Sprint F assembly (drafted against the tip, applied clean 6/6 diffs).
  break_the_core temp workspace moved to neutral /tmp (in-repo it nested under the
  closure and the B classifier denied the test's own scaffolding — the gate defending
  itself against its test harness). Battery: F 9 + BTC 2 + D 65 + E 11 + shared 77 +
  kimi 15. Commit 9bc2e1f, PR #406. R4 daemon defect filed as #407.

## RA-14/14b/14c — Sprint G: marketplace duplicate deleted (census caught the
  un-narrated shrink, updated with narration — the census working as designed);
  core_digest() self-attestation + recorder field; Class T probe landed and produced
  the PRE-DEPLOY BASELINE: one member at 22 infra fail-closes/2h vs ~0 for others —
  criterion 10's asymmetry, measured. Commit + PR follow.

## Final escalation deny-sweep for dp (all payload/text FPs from THIS session's work):
  aa4545a72ea4a612, 9c5e48b7ca0458c7, fddd2787cc778229, 21d90813319e2e40,
  40d00d927769f65f, 982b032dc133ae6f (kimi already corroborated the last two in #402).
