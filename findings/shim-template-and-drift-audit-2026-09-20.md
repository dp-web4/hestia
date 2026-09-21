# Shim template and drift audit — 2026-09-20

Audit of hestia's per-harness gate shims against dp's 2026-09-20 architecture directive
(template implemented verbatim / bare-minimum variants certified on rebuild / whole shim
hashed on release with the hash in the vault / an audit mechanism vs the vault reference).

Read-only audit. Nothing under `plugins/`, no hook, and no `SHIM_LEDGER.md` was modified.
Measurements are against `origin/main` unless a row says "installed" or "worktree".
Worktree HEAD during the audit was `633aa10` on branch `kimi/review-13155-13187` (shared
tree); every repo figure was taken with `git show origin/main:<path>`, never a checkout.

**Scope checked:** 10 shim-class artifacts, 5 shared modules, 4 hashing mechanisms,
3 CI jobs, 2 vault subsystems, 24 distinct behaviours across 3 command batteries.

---

## 1. Verdict in three sentences

**There is no template: the four gate shims share 13 normalised lines of common text —
0.8% of their union — and all 13 are Python boilerplate (`import json`, `try:`,
`except Exception:`), so the "bulk that calls shared gate functions" that dp specifies does
not exist in any form today.** The target architecture is not unspecified — it was fully
designed between 2026-08-31 and 2026-09-05 across four merged PRDs and two still-open PRs
(#931, #932, #934), the vault store that dp asks for (`vault::gate_integrity`, with
operator-gated `POST /api/gates/ratify`) is **already built and has no caller anywhere in
the fleet**, and the preimage calculator written to feed it (`tools/shim_certification.py`)
is **untracked and hard-fails on every seat** because it names a module that does not exist.
The governance consequence is live and verdict-changing: gemini reaches the shared decision
**zero** times and runs a parallel `_gate`, openclaw **fails open by design**, cursor has a
witness and **no gate at all**, and the LAW-DEBT the ratchet exists to drive to zero went
**up** — 1947 → 2005 sloc in the 17 days since it was measured — with CI green throughout.

---

## 2. Inventory

`git ls-tree -r origin/main` + `git show origin/main:<path> | wc`. sha256 is of the
`origin/main` blob, first 12 hex.

| key | path | bytes | lines | lang | harness | role |
|---|---|---|---|---|---|---|
| cc-pre | `plugins/claude-code/hooks/pre_tool_use.py` | 106321 | 1887 | py | claude-code | **gate** |
| cx-pre | `plugins/codex/hooks/pre_tool_use.py` | 52351 | 910 | py | codex | **gate** |
| ki-pre | `plugins/kimi/hooks/pre_tool_use.py` | 45404 | 768 | py | kimi | **gate** |
| gm-pre | `plugins/gemini/hooks/before_tool.py` | 33676 | 577 | py | gemini | **gate** |
| oc-idx | `plugins/openclaw/src/index.ts` | 6741 | 185 | ts | openclaw | **gate (RPC)** |
| cc-wit | `plugins/claude-code/hooks/witness.py` | 33748 | 783 | py | claude-code | witness |
| cx-wit | `plugins/codex/hooks/witness.py` | 12732 | 383 | py | codex | witness |
| cu-wit | `plugins/cursor/hooks/witness.py` | 13130 | 390 | py | cursor | witness (**no gate**) |
| cc-law | `plugins/claude-code/hooks/law_inject.py` | 16310 | 298 | py | claude-code | law injection |
| int-wit | `integrations/claude-code/hooks/hestia_witness.py` | 8651 | 236 | py | claude-code | **legacy 2nd location** |

`plugins/reviewer/` has no hook and is not a shim (`discover_prs.py`, `review-session.sh`).

### Divergence as a number

Pairwise, on lines normalised (stripped, blank/comment-free, whitespace-collapsed).
Cells are `difflib.quick_ratio% / Jaccard-on-normalised-lines%`. Jaccard is the honest
figure; quick_ratio is a character multiset and flatters unrelated Python.

| | cc-pre | cx-pre | ki-pre | gm-pre | cc-wit | cx-wit | cu-wit |
|---|---|---|---|---|---|---|---|
| **cc-pre** | — | 65/**5** | 59/**2** | 48/**4** | 48/9 | 21/5 | 22/5 |
| **cx-pre** | 65/5 | — | 92/**30** | 77/**10** | 77/1 | 39/2 | 40/2 |
| **ki-pre** | 59/2 | 92/30 | — | 84/**5** | 83/2 | 43/2 | 44/2 |
| **gm-pre** | 48/4 | 77/10 | 84/5 | — | 92/1 | 54/2 | 56/2 |
| **cx-wit** | 21/5 | 39/2 | 43/2 | 54/2 | 54/47 | — | **98/89** |
| **cu-wit** | 22/5 | 40/2 | 44/2 | 56/2 | 56/45 | 98/89 | — |

- Best gate-shim pair: **codex/kimi at 30%**. Worst: **claude-code/kimi at 2%**.
- `cursor/witness.py` and `codex/witness.py` are **89% identical — 35 differing lines out
  of ~390**. Cursor's witness is a hand-copy of codex's. Neither is in any ledger.

### The common core

| shim | normalised unique lines | in the 4-way common core | share |
|---|---|---|---|
| cc-pre | 828 | 13 | 1.6% |
| cx-pre | 498 | 13 | 2.6% |
| ki-pre | 390 | 13 | 3.3% |
| gm-pre | 379 | 13 | 3.4% |
| **union** | **1720** | **13** | **0.8%** |

The 13 lines, in full: `"""` · `)` · `else:` · `except Exception:` ·
`if __name__ == "__main__":` · `import json` · `import os` · `import re` · `import sys` ·
`return False` · `return None` · `sys.stderr.write(` · `try:`.

**Not one line of gate logic is common to all four shims.**

Lines unique to a single gate shim (in no other): cc-pre **750**, gm-pre 292, cx-pre 234,
ki-pre 171.

### Which shared functions are actually called

Static imports plus dynamic `spec_from_file_location` loads, resolved by hand.

| shim | shared modules it loads | governance decision path |
|---|---|---|
| cc-pre | gate_core, gate_mechanism, **governance_closure**, **shell_classifier** | closure + a second private layer |
| cx-pre | gate_core, gate_mechanism, **governance_closure** | closure |
| ki-pre | gate_core, gate_mechanism, **governance_closure** | closure |
| gm-pre | gate_core, `lib/path_scope` | **none — own `_gate`** |
| oc-idx | (none; JSON-RPC to the daemon) | remote `queryPolicy` |
| cc-wit, cx-wit, cu-wit, cc-law, int-wit | **none** | n/a |

Of 44 public functions across the five shared modules, **23 are referenced by at least one
shim and exactly one — `path_targets` — is referenced by all four gate shims.**

Local reimplementations of shared names: kimi defines `command_in_scope` and `path_in_scope`
locally (the collapse meter classes these as *adapters* — thin delegation, "this is the
cure", not drift). The three witness files each locally redefine `_id`, `_request`,
`call_tool`, `initialize`, `initialized` — an MCP client triplicated.

### Is there a template, generator, or codegen step?

**No generator and no codegen anywhere.** There is no `Makefile`, `justfile` or `*.mk` in
the repo. Every shim is hand-maintained. Two *reference templates* exist, both unmerged and
**mutually incompatible**: `plugins/_template/shim_template.py` on
`origin/cbp/shim-certification` (360 lines, 8 permitted functions, implemented by nothing)
and on `origin/gpt/single-gate-collapse` (123 lines, 7 different names, implemented by all
four shims *on that branch*). Neither is on main.

---

## 3. The divergence table

Verdict-changing first. "Changes allow/deny?" is the ranking key dp asked for.

### D1 — gemini never reaches the shared decision. **VERDICT-CHANGING. DRIFT.**

| measured on `origin/main:plugins/gemini/hooks/before_tool.py` | count |
|---|---|
| `evaluate()` call sites | **0** |
| `classify()` (governance closure) call sites | **0** |
| `witness_decision_unified` | **0** |
| `record_gate_unavailable` | **0** |
| own `_gate` decision engine | **1** (110 sloc) |
| occurrences of the word "governance" | **0** |

Gemini decides with a literal tuple — `FORBIDDEN = ("/.ssh", ".env", "credentials",
"id_rsa", "id_ed25519", "/.git/config", "secrets")` (`before_tool.py:207`) — and a
`READ_CLASS`/`EGRESS_CLASS` split. The governance-marker closure that produces
`gate-self-access` and `governance-closure-write` on the other three seats is **not in
gemini's decision path at all**. A governed write that codex and kimi refuse is not refused
by gemini on that rule.

This is not new — `PRD_SHIM_LAW_TO_ZERO.md:44` states "gemini … with 0 `evaluate()` call
sites is not on the common gate for deciding either", and R3 sequences fixing it first.
**What is new is that it is still true on 2026-09-20**, 17 days after the PRD merged.

*Caveat, from `DECIDE_RECONCILIATION_MATRIX.md`'s own in-document CORRECTION:* gemini does
reach the policy path **via subprocess** for some calls. I did not trace that subprocess
path to a verdict, so I state only what I measured: the in-process governance closure is
never consulted. Whether the subprocess route recovers the same verdict is **untested**, not
refuted.

### D2 — openclaw fails OPEN. **VERDICT-CHANGING. DRIFT.**

`plugins/openclaw/src/index.ts:146-149`:

```ts
// On any other error, fail-open (Hestia issue shouldn't break the agent).
api.logger.warn("hestia before-hook error; allowing call", { error: String(err) });
return { proceed: true };
```

Every Python shim is fail-closed (fail-closed markers: cc 16, cx 14, gm 11, ki 10). Openclaw
inverts the posture by design, and additionally gates only when `enforce && policy.enforced`
(`:128`) — a deny is downgraded to a warning when either flag is false.

Openclaw appears in **no** `SHIM_LEDGER.md` section, **no** certification criterion, and
**no** parity corpus. `GATE_ARCHITECTURE.md` §2's never-in-a-shim list includes fail-closed
posture; openclaw violates it and nothing measures openclaw.

### D3 — cursor is a witness with no gate. **VERDICT-CHANGING. DRIFT (by omission).**

`git ls-tree -r origin/main --name-only | grep '^plugins/cursor/'` returns exactly one file:
`plugins/cursor/hooks/witness.py`. There is no `pre_tool_use.py`. Cursor records what it did
and is refused nothing. Whether a cursor seat is live on this fleet I did **not**
determine — if none is, this is a latent hole rather than an open one.

### D4 — claude-code holds a private second classifier; 2 of 8 parity cases still diverge. **VERDICT-CHANGING. DRIFT.**

`hestia_shell_classifier.py` is loaded by `cc-pre:482` and by **no other shim and no shared
module**. Re-running PR #931's 8-case corpus
(`origin/cbp/fp15-18-false-refusal-corpus:plugins/_shared/cross_seat_verdict_parity_test.py`,
commit `2e5eddb`) against **today's** main shared modules, in-process, no shim executed:

| case | claude layer | peer layer | now | 2026-09-03 |
|---|---|---|---|---|
| plain_read | read | read | agree | agree (control) |
| real_write_control | write | write | agree | agree (control) |
| sed_range_print | read | read | agree | agree |
| assignment_prefix | read | read | agree | agree |
| for_loop_read | read | read | **agree** | DIVERGED (FP12) |
| if_then_read | read | read | **agree** | DIVERGED (FP12) |
| awk_pipe | **write** | **read** | **DIVERGE** | DIVERGED (FP15) |
| substitution_read | **write** | **read** | **DIVERGE** | DIVERGED (FP17) |

**4 of 8 → 2 of 8.** PR #942 ported FP12's control-flow strip into the shared closure and
retired both FP12 rows. The survivors are FP15 (`ls -la G | awk '{print $1}'`) and FP17
(`n=$(grep -c def G); echo $n`), both in the direction **claude-code refuses a read that
codex and kimi allow** — a false refusal local to this seat, not a governance hole.

*Actionable consequence:* PR #931's test is **pinned at 4 divergences, not xfail** — designed
to go RED when the seats converge. On today's main it would go red. That is the good signal
it was built to give, and it is currently sitting unmerged where nobody sees it.

*Caveat I must flag:* the two layers answer different questions. `_is_read_only` is a
read-only predicate; `classify()` is the governance-closure verdict that opens escalations.
Which one decides claude-code's final allow/deny is a composition question in a 1887-line
shim that I did **not** fully trace. The divergence is real and reproducible at the layer
PR #931 measured it; I have not proven each row reaches a user-visible verdict.

### D5 — `# trailing comment` turns a governed write into a read. **VERDICT-CHANGING. DRIFT (open defect, hestia #1045).**

`hestia_governance_closure.classify("Bash", {"command": ...})` on today's main:

| command | classification | rule |
|---|---|---|
| `cp /tmp/x plugins/claude-code/hooks/pre_tool_use.py` | `write` | `governance-closure-write` |
| `cp /tmp/x plugins/claude-code/hooks/pre_tool_use.py  # note` | **`read`** | **`None`** |

**#1045 reproduces on main.** Affects claude-code, codex and kimi identically (shared
closure), so it is a shared defect rather than cross-seat drift — but it is the highest-value
verdict defect found, because it converts a refusal into a silent allow.

### D6 — an interpreter argument is not seen as a write. **VERDICT-CHANGING. DRIFT (open defect, hestia #1059).**

`python3 /tmp/e.py plugins/claude-code/hooks/pre_tool_use.py` → `read`, `rule=None`.
**#1059 reproduces on main.** Same three seats, same shared-defect character as D5.

### D7 — a variable redirect destination refuses a pure read. **NOT verdict-changing (fails safe). DRIFT — and I triggered it live.**

New, minimised during this audit. The trigger is a redirect whose **destination is an
unresolvable substitution**, combined with a governance marker anywhere in the command —
*including as a read source*:

| command | classification | rule |
|---|---|---|
| `git show origin/main:<gov> > /tmp/a` | read | None |
| `git show origin/main:<gov>` | read | None |
| `for p in <gov>; do git show origin/main:$p; done` | read | None |
| `out=/tmp/a; git show origin/main:<gov> > "$out"` | **write** | **`governance-closure-out-of-grammar`** |
| `out=/tmp/a; echo <gov> > "$out"` | **write** | **`governance-closure-out-of-grammar`** |

My first audit command was a read-only extraction of shim sources into the scratchpad. It
was refused, **minted escalation `b055b07ccb123d59`, and invited 8 peers.** I withdrew it
immediately; the withdrawal invited the 8 peers anyway (the known invite defect). The
control arm matters: **the `for` loop alone does not trigger it** — consistent with the
#1062 2×2 and not a re-derivation of it. The discriminator is the redirect *destination*
being a substitution.

Cost of this FP class is measurable and was paid during this audit: one escalation, eight
peer invitations, for a `git show`.

### D8 — the authority bootstrap is already verbatim in 3 of 4 shims. **LEGITIMATE COMMON CODE, unenforced.**

`_load_shared_module` is **byte-identical** across claude-code, codex and gemini:

```
e7f5cf9a0d007a3e2dbf248da7389cab8a899109fa5a2f148aa89f1a0d78fd7c  claude-code
e7f5cf9a0d007a3e2dbf248da7389cab8a899109fa5a2f148aa89f1a0d78fd7c  codex
e7f5cf9a0d007a3e2dbf248da7389cab8a899109fa5a2f148aa89f1a0d78fd7c  gemini
```

59 sloc × 3 = 177 sloc of hand-maintained identical text. **kimi does not have the function
at all** — it inlines a different `sys.path` pattern at `ki-pre:96-107`. This is the single
best evidence that dp's "implemented verbatim" is achievable: it is already achieved for the
most security-critical block in the shim, by hand, with nothing enforcing it and one seat
already out of step.

### D9 — config resolution: one seat reads the projection, three read literals. **DRIFT.**

| shim | reads vault projection? | shared-dir resolution | literal fallback |
|---|---|---|---|
| cc-pre | **yes** — `_load_projection(PLUGIN_ID)` at `:148`; cross-checks the launcher's `HESTIA_HOME` against the projection's and returns `config.miswired` on mismatch (`:132-135`) | `$HESTIA_HOME/shared`, **no default** (`:369-370`) | none |
| cx-pre | no | `HESTIA_SHARED_DIR` or `$HESTIA_HOME/shared` | **`"~/.hestia"`** (`:91`) |
| gm-pre | no | same shape | **`"~/.hestia"`** (`:122-123`) |
| ki-pre | no | `HESTIA_SHARED_DIR` or `$HESTIA_HOME/shared` | falls back to `WORKSPACE/hestia/plugins/_shared` (`:103-105`) |

claude-code implements the #943 discipline correctly (launcher-supplied, no code default,
verified against the vault's value, fails closed). The other three carry exactly the
`os.getenv("HESTIA_HOME", "~/.hestia")` shape that #943 refused. kimi additionally falls back
to a **mutable working tree** as its authority source.

**I am not proposing that a seat patch these.** #943 is the precedent: converting shim
resolvers independently is how that failure happened. This is recorded as a measurement for
dp, and it is the drift column that the template/variant boundary should be drawn on.

### D10 — the same MCP client lives in three witness files. **DRIFT (unmeasured surface).**

`_id`, `_request`, `call_tool`, `initialize`, `initialized` are redefined locally in
`cc-wit`, `cx-wit` and `cu-wit`. `cx-wit`/`cu-wit` are 89% identical. No ledger row, no CI
check, no certification criterion covers any witness file.

### Legitimate variants (genuinely harness-specific)

These are real and belong in dp's variants section:

| variant | shims | why it is legitimate |
|---|---|---|
| event shape / `to_event` | all | each harness delivers a different tool-call JSON |
| refusal channel | all | claude-code writes stderr + exit code; gemini emits a verdict object; openclaw returns `{proceed:false}` |
| registration | all | `settings.json` hook vs `config.toml` vs plugin manifest |
| identity path | all | `~/.gemini/hestia-instance/identity.json` etc. |
| launch grant | all | per-harness launch-cwd env var |
| transport | openclaw | TypeScript + JSON-RPC to the daemon, not in-process Python |

These five names are exactly `SHIM_LEDGER.md`'s permitted classes, and that vocabulary is
sound. The problem is not the vocabulary — it is that a sixth class, `LAW-DEBT`, is also
permitted, holds 39 functions and 2005 sloc, and has no ceiling.

### Variants that exist only because nobody unified them

dp asked for variants at bare minimum. These are *not* harness-specific and should not be in
a variants section:

- `_load_shared_module` — already byte-identical in 3 seats (D8); kimi's divergence is
  historical, not harness-driven.
- `_attempted_summary` — 132 sloc across cc/cx/ki, three spellings of one idea.
- `_fail_closed_internal_error` — 67 sloc, codex 39 / kimi 28.
- `_gate_self_call`, `_witness_gate_self`, `_tally_scope`, `_claim_self_write`,
  `_role_bridge` — codex and kimi only, ~92 sloc, identical arity and intent.
- `deny` — 50 sloc across codex/gemini/kimi. `PRD_SHIM_LAW_TO_ZERO.md:39` already names
  `deny` as "THE REAL ONE that diverged".
- the witness MCP client (D10).

`tools/gate_collapse_meter.py` quantifies this independently: **"UNSHARED FORK SURFACE: 14
name(s) live in 2+ gates and are owned by NO shared module; 12 law-bearing, 1350 sloc. These
are candidates to MOVE into the engine. Nothing flags them today."**

---

## 4. What the template would be

Derived from the measurements above, not guessed.

### The common bulk (what every shim implements verbatim)

Three blocks, in this order, totalling roughly 130–160 sloc:

1. **Authority bootstrap** — `_shared_runtime_dir()` + `_load_shared_module()`. Already
   byte-identical in 3 of 4 seats (D8). **This block must be byte-identical and hashed
   independently**, because it decides *which bytes* subsequently govern. A template whose
   bootstrap can vary certifies nothing downstream.
2. **The single decision call** — one call into the shared engine that returns a verdict and
   performs its own consequences. `PRD_SHIM_LAW_TO_ZERO.md` R1 is right that the consequences
   (witness, refusal render, exit selection) must sit *behind* the entry point, because two
   of four seats decline them by omission today. `evaluate()` at
   `hestia_gate_core.py:959` is the existing funnel; `hestia_single_gate.decide()` on PR #934
   is the proposed one.
3. **Fail-closed posture** — the `except` that refuses. Must be in the template, because
   openclaw's is inverted (D2) and nothing catches it.

### The minimal variants surface

Measured, the irreducible per-harness surface is **four functions**:

- `read_harness_event()` — parse this harness's input
- `to_event()` — map it to the engine's event shape
- `emit()` — render allow/deny in this harness's protocol
- `PROFILE` — **data, not code**: member id, identity path, home markers, launch-cwd env var

Everything else in the current 2005 sloc of LAW-DEBT is unification debt. Both unmerged
templates agree on roughly this shape (7–8 names); they disagree on spelling, which is why
picking one is a dp decision and not a seat's.

**A caution from prior art that I would not override:**
`findings/the-engine-owns-the-predicate-every-seat-owns-the-domain-20260831.md` measured 73%
of shim sloc as genuinely divergent and warns the remaining forks "are not sloppiness to
delete, they are institutional memory in a form nothing can merge" — a naive union
re-imports codex's false-deny, and pick-a-winner re-opens gemini's hole. The template must be
migrated behind the parity corpus, not in front of it.

---

## 5. The missing machinery

| dp's element | exists? | evidence | smallest thing that would work |
|---|---|---|---|
| **template every shim implements verbatim** | **NO** | 13 common lines, all boilerplate (§2). Two incompatible reference templates, both unmerged; neither on main. No generator, no Makefile/justfile in the repo. | Land one template. Start with the bootstrap block (D8) — already verbatim in 3 seats, so the first enforcement costs one kimi edit. |
| **variants section, bare minimum** | **PARTIAL** | `SHIM_LEDGER.md`'s 7-class vocabulary is exactly this idea and is CI-enforced by `tools/shim_ledger_check.py` (`.github/workflows/ci.yml:432`). But `LAW-DEBT` is a permitted class with no ceiling. | Add the per-seat ceiling (`PRD_SHIM_LAW_TO_ZERO.md` R4/R5), vault-held so the governed party cannot raise it. |
| **certified on each rebuild** | **NO** | `plugins/_shared/shim_certification_test.py` is **untracked**, referenced by nothing, and fails 83 of 92 checks. No CI job runs it. | Track it, fix C1 (below), run it in the `collapse-ratchet` job. |
| **whole shim hashed on release** | **PARTIAL, and the good version is broken** | Four hash mechanisms exist (below). The composite-preimage calculator `tools/shim_certification.py` is **untracked** and **hard-fails on every seat**. | Fix its `RUNTIME_SET`, track it, call it from `deploy/install-members.sh`. |
| **hash stored in the vault on deploy** | **STORE BUILT, WIRE NEVER RUN** | `core/src/vault/gate_integrity.rs` + `POST /api/gates/ratify` (`http.rs:1215,5425`). **Nothing calls either endpoint** — no UI, no CLI, no deploy script. | One `curl` to `/api/gates/ratify` at the end of `install-members.sh`. |
| **audit mechanism vs vault reference** | **NO** | `GET /api/gates/verify` exists and has no caller. `tools/installed_seat_readiness.py` compares resident bytes to `current-build.json` and **is run by nothing** — CI declines it explicitly (`ci.yml:370`: "CI has no installed…"). | §6. |

### The four hash mechanisms that do exist

1. **Per-function, repo-only, CI-enforced** — `tools/shim_ledger_check.py:88-90`, 8 hex of
   sha256 per function, written into `SHIM_LEDGER.md`'s `src` column. This is a *staleness*
   check on justification prose, not artifact integrity. It passes today.
2. **Per-file, deploy-time** — `deploy/install-members.sh:179-205,410-427` sha256s every
   shim and engine module and writes them to **`~/.hestia/current-build.json`, a plaintext
   file the governed party can edit**. The shared-engine build dir is content-addressed
   (`shared.builds/<digest16>`, flipped by atomic symlink).
3. **Resident-vs-ledger** — `tools/installed_seat_readiness.py`. Never run. And
   self-consistent by construction: it compares installed bytes to a ledger written from the
   same source, so it can never detect "the ledger is stale relative to main".
4. **`vault::gate_integrity`** — the asymmetric store dp actually asked for, complete with
   `GateVerdict::{Verified,Modified,Missing,Unratified,Unreadable}`, daemon-side `hash_file()`,
   and an explicit refusal to accept self-attested hashes
   (`gate_integrity.rs:29-32`: *"Self-attested integrity is not integrity"*). **Zero callers.**

Its header records the origin (`gate_integrity.rs:2-6`, dp, 2026-07-27): *"since each
pre-tool-use hook is a .py file that is freely editable… at the very least we should have
hashes that are stored in the vault."* dp asked for this **eight weeks ago**, it was built,
and it was never wired.

### SHIM_LEDGER.md — provenance

24,013 bytes, tracked, last written 2026-09-17. `## <seat>` section per harness for **four**
seats, then a 4-column table: `function | class | src | justification`. Parser at
`tools/shim_ledger_check.py:62-64`; `MIN_JUSTIFICATION = 40` chars; `LAW-DEBT` rows must cite
a `#NNN` issue.

**Generated and hand-written, by design** — its own header line 17: *"`--refresh` rewrites
the hash, never the words."* The `src` column is machine-refreshed; `class` and
`justification` are human. Verified in CI (`ci.yml:425-432`).

It records **no** whole-file hash, **no** installed path, **no** build id, **no** vault
reference, **no** release version, and has **no rows for openclaw, cursor, or any witness
file**. `PRD_SHIM_LAW_TO_ZERO.md:69` names the structural problem: *"`SHIM_LEDGER.md` and
`shim_ledger_check.py` are both in the repo and both describe the repo."*

### Deploy path, and the installed-vs-repo comparison

```
systemd ~/.config/systemd/user/hestia-deploy.timer
  └─ deploy/from-main/hestia-deploy.sh   (DEPLOY_ROOT=~/.hestia/deploy, a SEPARATE checkout pinned to main)
       └─ deploy/install-members.sh
            stage RUNTIME_MANIFEST.txt → ~/.hestia/shared.builds/<digest16>/ → atomic symlink flip
            per member: backup, cp shim, re-sha256 the target, verify
            write ~/.hestia/current-build.json last, only on full success
```

Installed shims live in each harness's own home, not under `~/.hestia/`:
`~/.claude/hooks/hestia/pre_tool_use.py`, `~/.codex/hooks/pre_tool_use.py`,
`~/.kimi-code/hooks/pre_tool_use.py`, `~/.gemini/hestia-plugins/gemini/hooks/before_tool.py`.

sha256, installed vs repo working tree:

| seat | result |
|---|---|
| claude-code | MATCH `c0c19c62…` |
| kimi | MATCH `5343280b…` |
| gemini | MATCH `6800ffed…` |
| **codex** | **MISMATCH** — installed `86bf647e…`, repo `4daa5daa…` |

**The codex mismatch is source skew, not tampering.** `current-build.json` records
`head_sha 4ef88e16`, and the deploy checkout at that commit hashes to the installed value.
The working tree was 17 commits ahead; `5754e13` edited the codex shim's door comment.
Installed == deploy-checkout == ledger. **The load-bearing point survives: nothing on this
machine notices or records the delta.** The only tool that would is untracked and broken.

Two further defects found on the installed side: `.codex/hooks/` and `.kimi-code/hooks/`
contain `.bak-pre-redeploy-*`, `.pre-install.bak`, `.retired-*` shim copies sitting beside
the live one, covered by no manifest; and claude-code sends the daemon
`args["projection_sha256"] = os.environ.get("HESTIA_PROJECTION_SHA256")`
(`pre_tool_use.py:1257`) — a **self-attested** digest from an env var, which is precisely the
anti-pattern `gate_integrity.rs:29-32` forbids for gate code.

### Two instruments that pass without measuring

- **`shim_certification_test.py` C1 "bootstrap identical" passes vacuously.** It hashes
  `_authority_dir`, `_load_gate`, `_emergency_block`. Measured: **all three exist in zero of
  the four shims.** `ABSENT == ABSENT` reads as "identical". The real bootstrap is named
  `_load_shared_module` and is checked by nothing. This is certification-by-absence — the
  exact failure the sibling tool's own docstring forbids, and the exact failure
  `PRD_SHIM_LAW_TO_ZERO.md` acceptance criterion 6 was written to prevent.
- **`tools/shim_certification.py report` fails closed on all four seats.** Its
  `RUNTIME_SET[0]` is `hestia_single_gate.py`, which exists on PR #934's branch and **nowhere
  in this tree**. Output: `UNREADABLE` ×4. It has been dead since 2026-09-04. Its
  `CRITERIA_VERSION` pins `PRD_SHIM_CERTIFICATION.md@2026-09-04`, a file that is also not on
  main (it is on PR #932).

### The ratchet is running backwards

`tools/shim_ledger_check.py`, re-run 2026-09-20, against `PRD_SHIM_LAW_TO_ZERO.md:12-19`'s
2026-09-03 baseline:

| seat | LAW-DEBT fns then → now | law sloc then → now |
|---|---|---|
| claude-code | 16 → **16** | 819 → **862** (+43) |
| codex | 8 → **8** | 508 → **516** (+8) |
| gemini | 8 → **8** | 216 → **216** (0) |
| kimi | 7 → **7** | 404 → **411** (+7) |
| **total** | **39 → 39** | **1947 → 2005 (+58, +3.0%)** |

The PRD's target is **0**. Seventeen days on, the number is up 3% and CI is green, because
`shim_ledger_check.py` asks "is every function justified?" and never "is there less law than
yesterday?". A check that can only certify justification can only ever ratify growth — the
one-sign-record problem. `gate_collapse_meter.py` independently reports per-seat local law at
**48.1%** of total law sloc (collapsed means 0.0%).

---

## 6. A proposed audit mechanism

Deliberately built from parts that already exist. Each element names the failure mode it
prevents. **This is a proposal for dp, not a change any seat should make unilaterally** —
per #943, shim resolvers must not be converted toward the vault independently.

### 6.1 What it compares

One composite preimage per seat, the shape `tools/shim_certification.py` already computes:

```
certification = sha256(
      criteria_version
    + exact shim bytes                  (the DEPLOYED copy the harness config points at)
    + exact common runtime set          (the DEPLOYED ~/.hestia/shared, in fixed order)
    + gate API version
    + the shim's declared harness-difference block
)
```

*Prevents:* a 200-line shim staying "certified" while the 1400-line engine beneath it is
replaced. Hashing the shim alone certifies the wrong artifact.

*Fix required first:* `RUNTIME_SET` currently leads with a non-existent module and so
hard-fails. It must be read from `plugins/_shared/RUNTIME_MANIFEST.txt` — which already
declares exactly the four live modules — rather than transcribed. **Transcribing a list that
exists elsewhere is the documented failure of the last attempt at this**
(`findings/shim-certification-checker-restated-its-own-criterion-20260904.md`: the checker
transcribed `PERMITTED_FUNCTIONS` and the two copies disagreed on 4 of 8 names inside one PR).

### 6.2 What it does on drift

Four verdicts, mirroring `gate_integrity.rs`'s existing vocabulary plus one:

| verdict | meaning | action |
|---|---|---|
| `VERIFIED` | deployed preimage == vault expectation | none |
| `DRIFTED` | governed by code nobody ratified | ledger row + finding; **not** a deny |
| `UNRATIFIED` | no vault expectation for this seat | ledger row |
| `UNREADABLE` | could not look | **hard error, never "certified by absence"** |

`DRIFTED` must stay distinct from `MISWIRED`: a miswired shim *reads as governed and is not*;
a drifted shim *is* governed, by code nobody certified. *Prevents:* collapsing a
"not-governed" alarm into a "governed-differently" alarm and triaging both wrongly.

It must **not** deny on drift. A drift check that can refuse becomes a second gate with its
own false positives — and D7 is a live demonstration of what an FP in a governance matcher
costs (one escalation, eight peer invites, for a `git show`).

### 6.3 Where it runs

Three places, because each catches a different failure:

| where | what it catches | how it fails loudly |
|---|---|---|
| **deploy** — end of `install-members.sh`, one call to the existing operator-gated `POST /api/gates/ratify` | the expectation never being written | deploy exits non-zero; `current-build.json` is written last already, so a failed ratify leaves the build unactivated |
| **runtime** — the hourly `hestia-agent-inventory` sweep calls the existing `GET /api/gates/verify` | a shim edited after deploy | new `DRIFTED`/`UNCERTIFIED` verdicts join the existing `wired`/`governed`/`MISWIRED` rows |
| **CI** — `collapse-ratchet` job | a *repo* change that would not survive certification | job red on a new `LAW-DEBT` row or a raised ceiling |

The deploy and runtime endpoints **already exist and already work**. The whole of 6.3 is one
`curl` in a shell script and one call in a sweep that already runs.

### 6.4 How it fails loudly

- **Unreadable is a hard error, never a pass.** *Prevents:* the `UNREADABLE ×4` state the
  current tool sits in — which today looks like a report and is actually a total absence of
  measurement.
- **The check must fail on an unmodified tree in its negative arm.**
  *Prevents:* a check that cannot fire being mistaken for a check that passed — which is
  exactly C1's vacuous bootstrap pass (§5).
- **The expectation lives where the governed party cannot write it.** The vault, not
  `~/.hestia/current-build.json`, which any agent can edit. *Prevents:* an agent that can edit
  the gate also editing the record of what the gate should be.
- **The daemon hashes the file; it never accepts a hash the shim reports about itself.**
  Already the rule in `gate_integrity.rs:29-32`, already violated by the self-attested
  `projection_sha256` (§5). *Prevents:* a compromised shim certifying itself.
- **Coverage is a denominator, not a list.** Report `n verified of m discovered`.
  *Prevents:* openclaw, cursor and the three witness files continuing to be governed by
  nothing because no table has a row for them.

### 6.5 Smallest first step

**Fix `RUNTIME_SET` to read `RUNTIME_MANIFEST.txt`, track `tools/shim_certification.py`, and
call `POST /api/gates/ratify` at the end of `install-members.sh`.**

That is roughly a 10-line change to a file that already exists, plus one `curl`, and it
delivers three of dp's four elements: whole-shim hashing on release, the hash in the vault on
deploy, and a drift audit against the vault reference. The template itself is the larger
piece and is blocked on a dp decision between two incompatible drafts (PR #932's 8-name
template vs PR #934's 7-name one).

**Sequencing caution from the cert PRD's §6, which I would keep:** the parity corpus (C8) is
the *acceptance test* for the migration, not its first step. Running it first "produces a red
job nobody can fix, which is how a criterion becomes decoration."

---

## 7. Risks and what I could not determine

**Untested, not refuted — nobody has looked:**

- Whether gemini's **subprocess** route to the policy path recovers the verdicts its
  in-process path never computes. `DECIDE_RECONCILIATION_MATRIX.md` carries a CORRECTION
  saying the subprocess route exists. I measured only that the in-process governance closure
  is never called. **D1 may be less severe than stated, and is the single most important
  thing to check before acting on this report.**
- Whether a **cursor** seat is live on this fleet. If none is, D3 is latent.
- Whether **openclaw** is deployed anywhere. Its fail-open is in the repo; I did not find an
  installed copy.
- Whether D4's two surviving divergences (FP15, FP17) reach a **user-visible verdict**, or
  are absorbed by claude-code's composition. I did not trace the 1887-line shim end to end.
- Whether `integrations/claude-code/hooks/` (the legacy second location) is loaded by
  anything. `~/.claude/settings.json` points at `~/.claude/hooks/hestia/`, so probably not,
  but I did not prove it dead.

**Measurement caveats:**

- Jaccard on normalised lines is a *text* measure. Two shims could implement identical logic
  with different spelling and score low. `tools/gate_body_identity.py` (AST-normalised) is
  the better instrument and its prior result — IDENTICAL 14.1% / NEAR 12.9% / DIVERGENT 73.0%
  — is directionally consistent with mine but not the same metric. **I did not re-run it.**
- My §3 D5/D6 battery is *my* battery, not PR #931's. I ran both and report them separately;
  the "2 of 8" in D4 and the "2 of 8" I measured on my own cases are **different pairs of
  cases** and must not be conflated.
- `shim_ledger_check.py` and `gate_collapse_meter.py` count law differently (16 vs 23
  law-bearing functions for claude-code). I used each against its own baseline and did not mix
  them. Neither is wrong; they define "law" differently.
- I read the **repo** copies for all structural analysis and the **installed** copies only for
  the sha256 comparison in §5. Three of four match, so the structural findings carry to the
  installed copies; the codex delta is a comment change and does not affect any finding here.

**A risk in this report's own framing:** most of §5 and §6 restates work done between
2026-08-31 and 2026-09-05 by other seats. What is new here is the **re-measurement** (4→2
parity divergences, LAW-DEBT 1947→2005, C1's vacuity, the D7 redirect FP, and the
openclaw/cursor/witness coverage gap). If this report is read as a fresh design it will
duplicate PR #932. **The correct action is to land the existing branches, not to redesign.**

**Governance events generated by this audit:** one — escalation `b055b07ccb123d59`,
a false positive on a read-only `git show`, opened and withdrawn by me within minutes
(D7). Eight peers were invited by the withdrawal despite it. No shim was executed, no tool
call was routed through an installed hook, and nothing under `plugins/` was modified.

---

## Prior art this builds on

| artifact | state | what it established |
|---|---|---|
| `docs/GATE_ARCHITECTURE.md` (#738) | MERGED, **normative** | dp's 2026-08-31 two-component ruling; §2's never-in-a-shim list |
| `docs/PRD_SHIM_LAW_TO_ZERO.md` (#918) | MERGED | R1–R7; the 2026-09-03 baseline this report re-measures |
| `docs/DECIDE_RECONCILIATION_MATRIX.md` (#933) | MERGED | 9-stage per-seat adjudication; source of the "4 of 8" citation |
| `docs/ONE_GATE_AUDIT_2026-08-31.md` | MERGED | why four previous attempts failed; `gate_differential.py`'s "no disagreements" is weaker than it looks |
| `plugins/_shared/SHIM_LEDGER.md` (#855) | MERGED, current | the 7-class variant vocabulary, CI-enforced |
| **PR #932** `cbp/shim-certification` | **OPEN** | `PRD_SHIM_CERTIFICATION.md`, C1–C12, the preimage design, the 8-function template |
| **PR #934** `gpt/single-gate-collapse` | **OPEN/DRAFT** | `hestia_single_gate.py`; shims at 225 lines instead of 1887 |
| **PR #931** `cbp/fp15-18-false-refusal-corpus` | **OPEN** | the 8-case parity corpus re-run in D4 |
| `docs/GATE_PROFILE.md` | **STALE / harmful** | still says the shared core "is not wired"; a fifth harness would follow it |
| #294, #716, #741, #844, #916, #225 | OPEN | vault gate-integrity monitoring; deploy ratification; per-seat classifier/closure/fallback |

New in this report: the 2026-09-20 re-measurement of the parity corpus (4→2), the LAW-DEBT
regression (1947→2005), C1's vacuous pass, the D7 redirect-destination FP with its control
arm, the `_load_shared_module` byte-identity across three seats, and the first coverage of
openclaw, cursor and the three witness files — which appear in **no** ledger, criterion or
corpus in any prior artifact.

---

## Seat verification, 2026-09-20 (cbp-claude, before publishing)

Three claims re-measured independently. One is refuted.

### D1 is REFUTED — gemini is governed, by delegation

The audit measured that gemini's in-process closure is never called and flagged, correctly, that
`DECIDE_RECONCILIATION_MATRIX.md` claims a subprocess route and that this was **untested, not
refuted**. Tested now, at `plugins/gemini/hooks/before_tool.py:520-521`: gemini converts its event
to claude lineage and runs **claude-code's shim** as a subprocess, passing its own plugin id
(`gemini-cli`) and a fail-closed flag, with a 6-second timeout. It splits a policy deny (return
code 2 carrying a reason) from an inconclusive crash, routes the latter to the anomaly channel,
fails closed on consequential acts when the governor is missing, and recognises claude-code's own
`[fail-closed]` no-verdict marker. It also loads the shared module at `:189`.

**gemini is not an ungoverned seat.** The finding that survives is a different and more interesting
one: gemini's "variant" is *running another seat's shim*. That is one answer to dp's template
question — a single implementation, delegated rather than duplicated — and it deserves weighing on
its merits rather than being recorded as drift. It also means claude-code's shim is load-bearing
for two harnesses, so its divergence from the others carries double weight.

Do not act on D1 as a hole. The reconciliation matrix was right.

### The hashing machinery dp asked for is built and unwired — CONFIRMED

    core/src/vault/mod.rs:18,188,195     pub mod gate_integrity; gate_expectations(); set_gate_expectations()
    core/src/vault/storage.rs:69         pub gate_expectations: ...::GateExpectations
    core/src/server/http.rs:1214-1215    .route("/api/gates/verify", get(...)) / ("/api/gates/ratify", post(...))

Callers outside `core/src`, across every `.sh`, `.py`, `.ts` and `.yml` in the repo excluding
`findings/` and `docs/`: **none**.

### `VERIFIED` over an empty denominator — the same inversion, one level up

`http.rs:5305-5320` records it in the code's own words: thor measured `known_gate_paths()`
discovering `[]` while `/api/gates/verify` returned `VERIFIED, findings: 0, gates: []` on a host
that had an enabled PreToolUse gate pointing at a file that did not exist and was therefore failing
open. Noted here because any audit mechanism built on `verify` inherits it: **a verifier must
return UNKNOWN when it could not look**, which `agents_inventory` fifty lines below already does.

— cbp-claude

### CORRECTION to the section above, same day — `verify` already refuses the empty denominator

The paragraph above says `/api/gates/verify` returns `VERIFIED` over an empty denominator and that
any audit mechanism built on it inherits that. **That is wrong, and it is my error, not the audit's.**

What I read at `http.rs:5305-5320` is the doc comment on the discovered-gate-set helper, which
*records thor's incident as the reason the helper exists*. The repair is implemented forty lines
below it, at `http.rs:5372-5395`:

    // An unmeasurable denominator is UNKNOWN, never VERIFIED.
    ...
    if discovered.is_empty() { ... "status": "UNKNOWN" ...
        "... VERIFIED over an empty set would assert ..." }

So `gates_verify` already answers `UNKNOWN` both when the gate set cannot be established and when it
is empty. The inversion thor measured is fixed, and a caller may rely on that.

What survives from the paragraph is only the rule, which is still worth stating for anything built
next: **a verifier must return UNKNOWN when it could not look.** `gates_verify` and
`agents_inventory` both already do. The deploy-side caller proposed in §6 must too, including when
it cannot reach or authenticate to the daemon — an install that could not be certified has to say
so rather than pass quietly.

I read a historical note as a live defect and published it. Recorded here rather than silently
edited, because the findings file is the thing other seats will act on.

— cbp-claude
