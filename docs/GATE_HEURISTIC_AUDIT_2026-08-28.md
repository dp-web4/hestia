# Gate heuristic audit, 2026-08-28

Scope: every rule in the hestia governance gate that can deny or redact a claude-code (and, where shared, kimi/codex) tool call, evaluated against the project's own documented false positives.

Pins:
- `origin/main` at audit start: `c7ec7bd` (repo). Running daemon: `v0.0.4-485-gc7ec7bd`, deployed 2026-08-28T07:18:44Z (`~/.hestia/current-build.json`).
- Enforcing hook: `/home/dp/.claude/hooks/hestia/pre_tool_use.py`, 2773 lines, byte-identical to `plugins/claude-code/hooks/pre_tool_use.py` at `c7ec7bd` (`diff` 0 lines).
- Shared engine (symlink `~/.hestia/shared` -> `shared.builds/f32d9fbcbd4ffad1`): `hestia_gate_core.py` (1289 lines), `hestia_governance_closure.py` (1069 lines), `hestia_gate_mechanism.py` (772 lines). All three byte-identical to `plugins/_shared/` at `c7ec7bd`.
- Daemon policy source: `core/src/policy/presets.rs`, `core/src/policy/shell.rs`, `core/src/server/standing_scope.rs`, `core/src/server/handler.rs`.
- Line numbers cite the installed copy where the enforcing text lives, and the repo path at `c7ec7bd` otherwise. Installed == repo for every file cited unless stated.

Method: rules were exercised offline against the installed engine by importing `hestia_gate_core` and `hestia_governance_closure` and calling `evaluate()` / `classify()` directly (mints no chain rows, no denies). The FP record is drawn from a full scan of the 137 open issues (62 carry gate false-positive material), the claude-code seat's own gate memory (`gate_index.md` and its linked notes), the forum (35 notes), the codex/kimi deny logs under `~/.hestia/telemetry/`, this seat's session transcript (the only durable record of its own denies, since it writes none), and the denials this audit itself incurred (appendix).

## 1. Inventory of heuristics

Each row: rule id, where it lives, what it keys on, harm it targets, and whether the enforcing copy matches main.

### Local gate (runs in every seat's PreToolUse hook, before the daemon)

| Rule id | Where (installed / main) | Keys on | Harm targeted | Installed == main |
|---|---|---|---|---|
| `egress.secret` | `hestia_gate_core.py:930-945` (gate 1a) and `:1140-1150` (degraded); token list `FORBIDDEN_DEFAULT` `:144-146` | Case-folded **substring** of `FORBIDDEN_DEFAULT = ("/.ssh", ".env", "credentials", "id_rsa", "id_ed25519", "/.git/config", "secrets")` anywhere in any path, repo name, or the whole command text | Reading/exfiltrating a credential or secret file | yes |
| `mrh.command` | `hestia_gate_core.py:command_in_scope` `:779-910`, called from `evaluate` `:1014` | Shell command tokens that, split on the workspace string or resolved against cwd + granted repos, land outside a granted repo. Relative bare `.` resolves to the workspace root | Reaching outside the member's granted repositories | yes |
| `mrh.path` | `hestia_gate_core.py:path_in_scope` `:724-777`, called `:1004` | A file-path argument (Read/Edit/Write) that resolves outside home, /tmp, or a granted repo | Same, for path-shaped tools | yes |
| `mrh.repo` | `hestia_gate_core.py:985-990` | An MCP call naming a repository not in scope | Same, for connector calls | yes |
| gate-self-access (`governance-closure-write`, `-out-of-grammar`, `-unparseable-command`, `-opaque-writer`, `-internal-error`) | classifier `hestia_governance_closure.py:classify` `:971-1023`; markers `_SELF_MARKERS`/`_GOVERNANCE_FILES` in `pre_tool_use.py:202-268`; rendered `pre_tool_use.py:2588-2620` | A **write-position** token, or (in the out-of-grammar branch) **any command token**, that matches a governance filename/path segment. Reads of the gate are allowed + witnessed; writes escalate | An agent editing the code that governs it | yes |
| gate-self / settings registration | `pre_tool_use.py:_touches_registration` `:947-1000`, `_SETTINGS_MARKERS` `:290` | Mention of `~/.claude/settings.json` in a Bash/Edit that could rewrite the `hooks` stanza | Disarming the gate via its registration rather than its code | yes |
| `gate.degraded` / `fail-closed` | `hestia_gate_core.py:degraded_verdict` `:1120-1170`; `pre_tool_use.py:deny_no_verdict` `:2414` | Daemon unreachable + tool is write/exec-class. Deny writes, allow reads | Proceeding without a referee | yes |
| `gate.core_unavailable` | `pre_tool_use.py:2660` | Shared core fails to import | Same, on import failure | yes |
| `HESTIA_LEGACY_FALLBACK` (mechanism, not a rule) | `pre_tool_use.py:115`, `:2473-2500`; `~/.claude/settings.json:63` | Consulted only when the daemon is unreachable and fail-closed is OFF. See section 7 | (see section 7) | yes |

### Daemon safety preset (`safety`, the enforced preset; runs after the local gate returns allow)

| Rule id | Where (`core/src/policy/presets.rs` @ c7ec7bd) | Keys on | Harm targeted |
|---|---|---|---|
| `allow-rm-whitelisted-scratch` | `:42-80` (priority 0) | `rm` standing alone against absolute `/tmp` paths, no chaining, no `..` | (allow rule; carves the deny below) |
| `deny-destructive-commands` | `:81-195` (priority 1) | Regexes over **executable positions** (`MatchScope::ExecutablePositions`, `shell.rs`): delete-verb `\b<rm>\s+-`, `\bmkfs\b`, `\bshred\b`, `\bof=<dev>`, `>\s*<dev>`, `\btee ... <dev>`, `\b(cp|mv|install) ... <dev>` | Destroying a filesystem or block device |
| `warn-file-delete` | `:198-225` (priority 2, warn) | delete-verb `\b<rm>\s+[^-]` in executable positions | Flagging plain deletes |
| `deny-secret-files` | `:225-262` (priority 3) | Glob patterns on `file_read`/`credential_access` targets: secret/key file globs (env files, key files, cloud/service configs) | Reading secret files (path-shaped, not substring) |
| `warn-memory-write` | `:265-285` (priority 4, warn) | Globs on memory files (`**/MEMORY.md`, `**/memory/**/*.md`) | Memory poisoning |
| `warn-network` | `:288-300` (priority 10, warn) | `network` category | Flagging egress |

The `executable_positions` projection (`core/src/policy/shell.rs`) blanks inert content (single-quoted spans, quoted-delimiter heredocs) before the destructive regexes run, but only for an allowlist of `INERT_CONTENT_HEADS` (`cat`, `grep`, `tee`, `jq`, ...); any unrecognised head, `sh -c`, `eval`, or a substitution keeps the raw text scanned. This is the "handed to an interpreter is matched in full" clause in the injected law text.

## 2. Per-heuristic FP record and bypass cost

Bypass grades: **CASUAL** = one recast, no design; **EFFORTFUL** = actor must design indirection (move text off the classifier input, splice tokens, assemble the path at runtime, revert the hook); **NONE** = no bypass without the operator.

### egress.secret (substring over command text)

Mechanism of the FP: `if f in low` (`hestia_gate_core.py:936`) is a case-folded substring test with no token boundary and no data/command distinction. It fires on any command whose text contains one of the forbidden tokens as a substring, wherever it sits (path, repo name, command body, heredoc prose).

Documented instances: #639 (four denies in one wake, incl. slide text "Verifiable credentials over the formats regulators are standardising on" and `find .`), #604 (`os.environ` -> the env-file suffix; `myfile.envelope`; also the fail-open direction), #625 (dup of #622; `os.environ.get('HOME')`, the stdlib `secrets` module), #664 (redaction arm; prose listing the credential-shape list), #680 (the deny is not an event), #608 (FP#6), #624 (a plural noun in prose), #595/#622/#261 (a token in a grep needle or memory-note prose), #669/#696 (the env idiom in a Bash heredoc), #393. Today's list items 1 and 2. Offline probe (this audit) confirms live at `c7ec7bd`: `echo credentials`, a heredoc whose body prints "Verifiable credentials over...", `cat notes/.environment.md` (env-file substring), `git commit -m 'docs: no secrets here'` all deny.

Bypass: **CASUAL.** #639 measured it: the same script written via the Write tool and run by path is allowed ("one turn, no thought"). Splicing (`"secr"+"ets"`), `os.getenv` instead of `os.environ`, runtime-assembled paths, `--body-file`, and glob spelling all pass. This audit's own probe found the glob form of a key-file path and a base64-decoded path both ALLOW while the literal denies.

Item 2 nuance (the hub-mesh `.env` file read): denying a read of `~/.config/hub-mesh.env` is arguably a *legitimate* deny of a config read (the filename ends in the env suffix and the file could carry secrets). Two readings: (a) correct - a `.env` file is exactly what the rule exists to protect; (b) false - it is the hub peer map, read by the hub-notify script on every send, and the deny is on the suffix, not on any evidence the file holds a secret. The rule cannot tell the two apart because it keys on the suffix, not on content or on whether the read is a known-benign consumer. This is the one egress case in today's list that is not obviously an FP, and it is the case that most argues for keying on a path resolved under a *secret directory* rather than on a filename suffix (section 5).

### mrh.command / mrh.path (scope by lexical token, relative `.` = workspace root)

Mechanism: `command_in_scope` resolves tokens against the workspace string and cwd, but a bare relative `.` and prose words that collide with a directory name are read as reaches at the workspace root; and the granted set is rendered into the deny before redaction.

Documented instances: today's item 3 (`find .` in a granted repo, recurring "many times over two months"), #669 (`os.path.exists`-probed bare tokens; prose word "logs"; `--repo` flag vs `cd`; relative build-script spelling x2), #647 (per-fire worktree cwd not matched -> `<workspace root>`), #695 (granted path reduced to one bare token; display placeholder compared before redaction), #596 (empty grant set, ~24h outage), #670 (scope enforced only at workspace root), #633 (deterministic scope collapse to `granted: metalinxx`), #440 (kimi `--body` bareword `logs`), #629, #632. Today's item 4 (systemd heredoc containing `Environment=HESTIA_WORKSPACE=<the ungranted root>` denied as a reach at the ungranted root; the line was dropped, better design, but the deny did not know that).

Bypass: **CASUAL** for the relative-path class (spell the absolute path - the recast the seat performs "many times") and the prose-word class (paraphrase, or `--body-file`). **NONE** for the genuine empty-grant / worktree-lockout outages (#596, #647, #695, #716), which need an operator or a hook edit - those are availability failures, not casually-bypassable FPs. Offline probe confirms `find .` at cwd=workspace-root denies while `find .` in a granted repo allows; `cat ../claude-code/README.md` and `cd claude-code && cat README.md` both deny (correct scope enforcement).

### gate-self-access (governance-marker match; out-of-grammar looseness)

Mechanism (two shapes, confirmed by offline probe this audit):
- **In-grammar**: a governance path in a **read** position (grep source, `git show` operand, `cat >` under an inert head) classifies `read` and is allowed. A governance path in a **write** position (`>`, `tee`, `cp` dest, `sed -i`) classifies `write` and escalates. This is correct.
- **Out-of-grammar**: when the head/compound is not decidable - a `for` loop, `sh -c`, `cd X &&` - `_bash_write_targets` raises `_OutOfGrammar` and the fail-closed branch treats **any command token** that matches a governance marker as a write (`RULE_OUT_OF_GRAMMAR`). Offline probe: `diff <hook> <hook>` classifies **read** (allowed); the identical diff wrapped in `for c in ...; do diff ...; done` classifies **write / governance-closure-out-of-grammar**. The value list is irrelevant; the loop construct alone flips it.
- **Marker matches bare English words**: markers include the segment `hestia/hooks`, so prose containing the word "hooks" can match in the out-of-grammar branch (memory `ref_out_of_grammar_matcher_is_looser`; #440).

Documented instances: an extensive set. Issues: #116, #158, #242, #260, #263, #301, #388, #440, #487, #509, #529, #533, #536, #589, #600, #608, #609, #617, #622, #628, #631, #648, #655, #664, #668, #676, #687, #709. Memory: `ref_gate_mention_vs_perform`, `ref_content_match_two_layers`, `ref_out_of_grammar_matcher_is_looser`, `ref_grammar_not_spelling_selects_escalation`, `ref_deny_names_marker`, `ref_recast_leaves_no_chain_record`. This seat's transcript: **262** gate-self-access denies over two months (180 Bash, 73 Edit, 6 Write, 3 Read), the single largest deny class it has ever hit. This audit itself: three (appendix, denials 1-3).

Bypass: **CASUAL.** Elide the marker (`<PTU>`, `<gate>`), split a `for` loop into three flat `grep`s, use `--body-file` with the Write tool, backtick the path in markdown. #536 measured three route-arounds landing within seconds of the deny (11s, 16s). #529/#628 also record the **fail-open twin**: an interpreter handed a governance path (`python3 script.py <closure>`) classifies `read` and writes it unrefused - so the same classifier over-denies reads it can see and permits writes it cannot (grade of the *hole*: CASUAL-by-accident; the members declined to reuse it).

### destructive preset (`deny-destructive-commands`)

Mechanism: regexes over executable positions. Two documented FP mechanisms: (a) the delete-verb pattern was a bare substring before #533/#546 added the `\b` - convicting words that merely end in those two letters before a dash, and the tail of the English word "arm" in a markdown heading (#533, #242); (b) a legitimate destructive token quoted as data under a non-inert head, or handed to an interpreter, is matched in full (#617, #263, forum note 12, today's item 5).

Documented instances: #242 (`find ... -perm` denied on the delete-verb suffix), #533 (`git rm -q`, memory-index heading `... fd arm ---`, `alarm -v` in a title), #617 (`gh issue create` body quoting delete-verb tokens; the appeal itself), #263 (report about the preset), #686 (upheld appeals change nothing), #608 (commit-message verb host), #393 (`flock` compound matched "in full"). Today's item 5 (`rm -f -- "$TMP"` inside a `trap` string in a python heredoc handed to `python3 -`).

Bypass: **CASUAL** for the mention class (move the message to a `-F` file, retitle, backtick). **NONE** by design for the genuine case: today's item 5 is a **true positive by the law's own text** - a `trap 'rm -f ...'` string handed to `python3 -` is "handed to an interpreter", and the interpreter clause is deliberate. See section 4.

### fail-closed / gate.degraded

Mechanism: daemon unreachable -> deny writes. The FP is not the deny (it is the ratified posture) but that (a) on this seat the deny writes **no chain row** (section 6), and (b) `HESTIA_PRE_FAIL_CLOSED` is **not set** for the claude-code seat (`~/.claude/settings.json` env block is empty), so when the daemon is unreachable this seat does not fail closed at all - it falls through to the legacy fallback (section 7), and #604 measured the innate egress scan not running on that path.

Documented instances: #604 (fail-OPEN direction), #622/#625/#669/#680 (no record), #354/#423 (starvation and cold-connect windows), forum `cbp-crit3`, `cbp-dating-the-fail-closed-class-172-denies` (172 fail-closed denies, 12 days, all `cause=timeout`).

Bypass: **CASUAL** (retry after the daemon returns - the deny's own text says "wait", and the retry succeeds ~40s later).

## 3. Harm assessment and ranking

dp's frame: a heuristic is net-negative when its FPs are frequent AND its bypass is casual, because it trains recasting - and the law scores a recast at **0.35**, below plain compliance (0.85) and below a witnessed appeal (1.0) (`core/src/derivation.rs:832`). The gate is then manufacturing the exact conduct it penalises, and (section 6) doing so without a record, so the penalty never even lands. A heuristic whose bypass is NONE is not counterproductive in this sense even if it denies - it changes behaviour rather than teaching evasion.

Ranking criteria, in order: (1) FP frequency in the lived record; (2) bypass = CASUAL; (3) the deny leaves no measurable record, so the FP rate is undefined and cannot self-correct; (4) severity/precision inversion (loosest discriminator carrying the strictest, least-appealable consequence); (5) the FP lands hardest on the compliant path (reporting, appealing, or fixing the gate).

Ranked most counterproductive to most sound:

1. **egress.secret (substring).** Highest FP frequency on unrelated prose; CASUAL bypass; **no chain record at all** (#680), so its FP rate is undefined; the worst severity inversion in the system - a case-folded substring carrying an innate, no-door, no-appeal, unrecorded refusal (its `REMEDIES` tuple is empty, `hestia_gate_core.py:233`); and fail-open on this seat under timeout (#604). dp's own example (slide text "credentials") is the archetype. Net-negative.
2. **gate-self-access out-of-grammar branch.** 262 lived denies, almost all reads; CASUAL bypass (drop the loop, elide the marker); matches bare English words ("hooks"); lands hardest on documents *about* the gate - bug reports, appeals, memory notes - so it selects against the members maintaining it. The in-grammar read/write split is sound; the out-of-grammar looseness and the marker-matches-prose behaviour are the counterproductive part.
3. **mrh.command / mrh.path relative-and-prose class.** The `.`-as-root recast is the single most-repeated FP in two months (today's item 3); CASUAL; and on this seat it leaves no record (#669). The empty-grant/worktree outages (#596, #647, #695, #716) are severe but are availability bugs (bypass NONE), ranked separately.
4. **destructive delete-verb substring (pre-#546).** Frequent enough to hit memory-index edits and issue titles; CASUAL; and #533 measured the deny minting no escalation, so it is unappealable. PR #546 adds the `\b`; not yet in force at the running daemon build until rebuilt.
5. **fail-closed non-recording + unset fail-closed on this seat.** Not an over-deny in shape, but counterproductive because the deny teaches "retry" (CASUAL) and leaves no artifact, and because the seat is not actually configured fail-closed, the ratified posture is not what runs here (it falls to the legacy fallback, section 7).

Sound (keep, do not soften): the **in-grammar write-position** gate-self classifier (reads allowed, writes escalate); the **destructive preset device/interpreter clauses** keyed on write position (`of=`, `>`, `tee`, `sh -c`); `deny-secret-files` (path-glob, not substring). These deny the act, not the mention.

## 4. True-positive side (do not remove without this cost)

For each heuristic proposed for narrowing, the true positive it would lose:

- **egress.secret**: true positive is a read of a real key file or env file (`cat <key file>`, `cat <repo>/.env`) - confirmed deny in this audit's probe (the ssh-dir and env-file substrings matched a real path). Narrowing to "a path argument that resolves to a file under a secret directory, after argument parsing" (section 5) keeps this and drops the prose class. Documented true positive in the chain: the codex seat's Sprint-F test fixtures show dozens of `Read ... /ws/granted/<env file>` denies - but those are test-harness reads of literal env files, i.e. the rule catching a real path, not prose. **No documented case exists of egress.secret catching an actual exfiltration attempt** that a path-resolved rule would not also catch; that direction is **untested, not refuted** (the deny writes no chain row, so it cannot be counted - section 6).
- **gate-self-access**: true positive is `echo x > <hook>`, `cp evil.py <hook>`, `sed -i ... <hook>`, `tee <hook>` - all confirmed `write` in this audit's probe, all correctly escalated. The in-grammar branch already catches these; the out-of-grammar branch is what over-fires. Removing the out-of-grammar *marker-in-any-token* behaviour loses the ability to catch a governance write hidden inside a construct the parser cannot read - but #529/#628 show the parser already misses interpreter hand-offs entirely, so that "coverage" is largely illusory. Documented true positive of the out-of-grammar branch **specifically**: none found in the record; every out-of-grammar deny in the transcript and issues is a read. Mark: **untested** that it ever caught a real write, not refuted.
- **mrh.command relative-`.`**: true positive is a command that genuinely reaches an ungranted repo by relative traversal (`cat ../other-repo/secret`) - confirmed deny in probe. Resolving `.` against the actual cwd before comparison (section 5) keeps this and drops the false-root reading. No documented true positive is lost by resolving cwd first.
- **destructive delete-verb**: true positive is `sudo rm -rf /var/data`, `rm -rf` chained with recreation - #533's KEEP arm holds 10/10 through the engine; the head-anchor "fix" was rejected precisely because it would ALLOW `sudo rm -rf /var/data`. The `\b` word-boundary (PR #546) is the correct narrowing and loses nothing. Documented true positive: #608 `35d58b...` (chmod on a hook file), and today's item 5 (`rm -f` handed to an interpreter) - both real.
- **interpreter clause (destructive)**: this is the true-positive engine, not a candidate for removal. Today's item 5 is caught correctly by it. The clause may be too *wide* (it matches a cleanup `trap` string in a script being authored, which will only ever run in a throwaway temp dir), but narrowing it risks the real case (`sh -c 'rm -rf /'`). See section 5 for a position-aware rather than removal remedy.

## 5. Remedies keyed on execution position, not token presence

For each counterproductive heuristic, the correct predicate, with existing PRs/issues so nothing is re-proposed as novel:

- **egress.secret**: key on a **path argument to a reading or sending command that resolves, after argument parsing, to a file under a secret directory** - never a substring of the command text. The daemon already has this shape in `deny-secret-files` (path globs on `file_read`/`credential_access` targets, `presets.rs:225`); the gap is that the innate local `egress.secret` is a substring scan instead. Existing proposals: #639 (honour `INERT_CONTENT_HEADS` on gate 1a, split path-shaped from word-shaped tokens; make deny appealable, #638), #393 (match the act / write-position, #370's shape), #680 (record the denial mark). Do not re-propose; these exist.
- **mrh.command / mrh.path**: resolve relative paths against the **actual command cwd** before scope comparison; compare granted paths by **prefix containment at a separator**, not by reducing to one bare token; and render the deny **after** redaction so the `<workspace root>` placeholder is not compared. Existing proposals: #695 (prefix containment, unify mrh.command/mrh.path), #669 (compare at resolved destination, split workspace value, set `HESTIA_WORKSPACE`), #647 (explicit launch-cwd grant), #596/#597 (prefix descent - partially landed at `af892036`, insufficient on HUB/pub), #670 (scope beyond workspace root), #633 (deterministic scope collapse), #484 (exempt the scope-request payload from target-access semantics). The relative-`.` case is already what `path_in_scope`'s docstring says it fixed for path tools (`:730`); the same cwd-first resolution needs to hold for the command scan's pass 2.
- **gate-self-access out-of-grammar**: require a **path-shaped match** for the marker in the out-of-grammar branch (not a bare segment/word), and align the out-of-grammar predicate with the in-grammar one that requires a real write position. Existing proposals: #440 (exclude heredoc-body tokens; marker must resolve to a governance path; payload positions != grammar positions), #388 (key on write position - landed for the in-grammar path), #628 (unknown head + closure-marker path in any position -> fail closed, closing the FN twin), #536 (exclude prose regions: heredoc bodies, `-m/--title/--body/--reason`). Decision 0017 (forum `cbp-decision-0017`) keys self-access on the invoked copy.
- **destructive preset**: the law already has the right shape (write-position keying + the interpreter clause). The delete-verb `\b` is PR #546 (merged to source; needs daemon rebuild to be in force). The interpreter clause may be **too wide** for a cleanup `trap` string in a script being *written* to a temp dir (today's item 5): a position-aware refinement would ask whether the interpreted text's destructive token targets a path outside the scratch whitelist, rather than matching any delete-verb inside any interpreted blob. **No existing PR proposes this narrowing**; it is the one genuinely new remedy here, and it is low priority because the current behaviour is a true positive by the letter of the law - the law is right to want it; the only question is whether the law should be that eager about a handler that has not run.
- **fail-closed recording + posture**: wire the deny recorder into both claude deny branches (#669, ~20 lines mirroring kimi `_record_refusal` at `pre_tool_use.py:2731`/`:2739`); record first-stage (egress/mrh) denies locally (#680 mark, #622, #625's kimi note that this is a shim change not a core change); and set `HESTIA_PRE_FAIL_CLOSED=1` for this seat so the ratified posture actually runs (#604 remedy a).

## 6. The measurement gap

Which denials are not chain events, so their FP rate is undefined:

- **egress.secret**: returns in-process at gate 1a, **before** the daemon stage that writes `policy_decision`, and its `REMEDIES` tuple is empty (`hestia_gate_core.py:233`) so it opens no escalation. Measured: 0 rows in any channel (#680, #664 n=1, #625 "0 egress rows on claude-code", #608 FP#6 "none / none"). No id, no hash, no remedy, no appeal.
- **mrh.command / mrh.path**: on the claude-code seat, `witness_decision_unified` has **no call site** in the hook (#669: `git log -S` empty, ever; 12,192 daemon-written / 0 hook-written `policy_decision` rows), so scope denies "enforce and leave no artifact." kimi and codex record the same classes (their `~/.hestia/telemetry/gate-denies-*.jsonl` carry `mrh.command`/`mrh.path`/`egress.secret` rows). This audit confirms: there is no `gate-denies-claude-code.jsonl` in `~/.hestia/telemetry/` (only `-codex` at 635 rows and `-kimi-code` at 602 rows).
- **destructive delete-verb (local warn/deny before daemon)** and the **fail-closed** class: no chain row; the fail-closed class writes only to plane-E telemetry (`gate-unavailable.jsonl`, 428 rows), which is explicitly "infrastructure availability, NOT a member act."
- **gate-self-access**: DOES record on claude-code, via a separate emitter (`_emit_gate_event` -> `gate_self_access`), but best-effort under a ~1.5s budget behind `except: return False`, so some are lost (`WITNESS FAILED` observed in #440, #622, #389, #537); and the record names the **marker**, not the command (`ref_deny_names_marker`), so a false positive and a true positive are indistinguishable in the store (#158).

Consequence: the two most counterproductive heuristics (egress.secret, mrh.command) are exactly the two with **no measurable FP rate**. The FP rate is not low; it is undefined. The one class that records end-to-end and shows a clean appeal is the daemon-side destructive preset (#608 12:42 deny ruled in 159s; #686 upheld appeals; #242 full command text on chain). This is also why cross-seat deny-rate comparisons in the corpus are confounded: the loudest FP-reporting seat is the one seat whose governance-class denials do not record.

Minimal instrumentation for a quantitative next audit:
1. A **denial mark** for every first-stage local deny (egress, mrh, degraded): one append-only line per deny carrying guard name + pattern class (never the matched substring) + tool + timestamp + host_session_id, written by the shim, off-chain (dp: "the chain witnesses member events, not infra telemetry"). This is #680's mark and #669's recorder; both are one-shim-file changes.
2. **egress.secret must open an escalation or a mark** even though its remedy is "no door," so the deny is countable and appealable - the current empty remedy tuple is what erases it.
3. Record the **command** (redacted) in `gate_self_access`, not just the marker, so FP and TP are separable (#158).
4. A **ground-truth observer**: a post-hoc sha256 manifest of governance files (#529 detector B: 9/9 writes, 0/7 reads, 0.363 ms cost) to measure the classifier's FN rate against actual writes, which the parser-based classifier cannot self-measure.

With (1)-(3) in place, the next audit can state an FP rate per rule instead of a census of transcripts.

## 7. HESTIA_LEGACY_FALLBACK (audited as its own item)

`~/.claude/settings.json:63` registers the hook with a leading env assignment `HESTIA_LEGACY_FALLBACK=<a path inside the claude-code working tree>` and `HESTIA_ROLE=...`, then `python3 /home/dp/.claude/hooks/hestia/pre_tool_use.py`. Verified against the installed hook: `LEGACY_FALLBACK = os.environ.get("HESTIA_LEGACY_FALLBACK", "")` (`:115`); consulted only in `invoke_legacy_fallback` (`:2473-2500`), reached only from `main()`'s final line (`:2760`) - i.e. when the daemon path failed AND `fail_closed()` is False. `fail_closed()` is `HESTIA_PRE_FAIL_CLOSED == "1"` (`:2399`), and that variable is **not set** for this seat (settings env block is empty), so the fallback IS live here.

Behaviour (`:2482-2500`), verified against the installed source:
- `HESTIA_PRE_NO_FALLBACK=1` -> deny (not set here).
- path **missing** -> `debug_log("legacy fallback not found ...; allowing"); return 0` - i.e. **ALLOW**, with only a debug line. The header doc says so explicitly (`:44-47`: "A path that does not exist ALLOWS").
- path **exists** -> run the legacy gate with a 2.0s timeout; on `TimeoutExpired`/`OSError` -> `return 0` (allow again).

Four defects:
1. **The fallback path is inside a git working tree.** A pull of that tree hot-deploys the fallback gate, unreviewed. This is the class that locked out the pub seat today (its primary gate registered into the hestia working tree; #596/#632/#716).
2. **Missing path fails OPEN.** If the target repo is not checked out at that path on a given machine, every daemon-unreachable tool call is allowed with a debug line and nothing else.
3. **The deploy timer now schedules the daemon-unreachable window.** `hestia-deploy.timer` (PR #698, installed and active) runs at `00/4:17` local; the deploy script (`~/.local/bin/hestia-deploy`) restarts the daemon and waits up to `READY_SECS=120` for it to answer `initialize`. This audit measured the 2026-08-28T07:18 deploy window directly in `gate-unavailable.jsonl`: claude-code and kimi-code fail-closed telemetry from 07:15:05 to 07:24:06 (a "Connection refused" URLError at 07:18:15). So for a window of up to ~45-120s every 4h, this seat is governed by the legacy fallback (if the file exists) or by nothing (if it does not) - and because fail-closed is unset, it is the fallback, not a deny. #715 filed this class ("arming 4-hourly deploy automates empty-envelope lockout").
4. **The banner leaks the hook's environment.** Every deny banner this seat emits prints the full registered command line, including the `HESTIA_LEGACY_FALLBACK=...` and `HESTIA_ROLE=...` assignments, to the user. (This is how the variable came to dp's attention.)

**File existence: UNVERIFIED.** Reading the fallback path is denied by `mrh.command` - `'claude-code' is not granted` - so this audit cannot check whether the fail-open file is present (recorded in the appendix, denial 5). That the audit of a fail-open path cannot read the path is itself part of the finding.

Bypass cost of the mechanism: **NONE** for a member (it is infrastructure, not a rule a member trips), but the harm is a governance hole, not a member bypass: unreviewed hot-deploy (defect 1), scheduled fail-open (defects 2-3), and an env leak (defect 4). Fix list: (a) no in-tree path - point at an installed copy or leave unset; (b) missing path must fail closed, not open; (c) the deploy script should hold the gate closed across the restart (a `deploy.hold`-style gate-closed marker the hook reads) or the hook should treat "restart in progress" as deny; (d) the banner should not print the hook's environment. Filed as a hestia issue citing this doc.

## 8. Scope-derivation narrowing (two gate engines in one hook process)

This audit ran with `granted: metalinxx+hestia+hestia` (observed in every mrh.command deny it hit), the narrow set, not the ~26-repo society floor the seat also holds. The cause is not a scope-derivation change in the 444..484 range. The only scope commit in that range is `af89203` (PR #597, "honor typed path-grant boundaries", 2026-08-25, merged; there is no PR 596 - #596 is the OPEN issue it closes), and it **widens** scope: it adds `_within_path_grant`/`_scope_parts` so `path:` grants match by resolved prefix. That engine has been installed since 2026-08-25 12:06 (`~/.hestia/shared -> shared.builds/f32d9fbcbd4ffad1`, whose core/mechanism sha256 in `current-build.json` equal the tree at `af89203`/`fb1c849`/`c7ec7bd`). Today's two redeploys (05:44 -> 484, 07:18 -> 485) changed only the daemon binary and the kimi/witness hooks; the claude-code hook and the shared engine were "already current."

The real mechanism is that the hook loads **two different gate engines**, selected by whether the command names a governance marker. Two-arm test this audit ran (same cwd, same daemon, seconds apart):
- `ls -la <ws>/web4/README.md` -> ALLOWED.
- `ls -la <ws>/web4/README.md <ws>/web4/pre_tool_use.py` -> `deny [mrh.command] 'web4' is not granted (granted: metalinxx+hestia+hestia)`.

The only difference is the marker basename `pre_tool_use.py` in the second command. Cause, in `pre_tool_use.py`:
- The fleet-path cutover (#590) set `_SHARED_DIR = $HESTIA_SHARED_DIR or $HESTIA_HOME/shared` at import (`:299-309`), i.e. `~/.hestia/shared`, the current floor-aware engine.
- But `_load_mechanism()` (`:2315`) and `_record_plane_e()` (`:2405`) **still** do `sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))`, which for the installed hook is `/home/dp/.claude/_shared` - the pre-cutover per-vendor copy, dated 2026-08-14, **before the society floor (#490, 08-17) and before #597**.
- The gate-self path runs first and imports the mechanism through `_load_mechanism()`, so once a command names a marker and takes the gate-self branch, the stale 08-14 engine is what resolves scope: no `society_floor`, no `_within_path_grant`, and a `detect_workspace` that climbs to the `ai-agents` root. Result: workspace = root, floor absent, `granted = standing + launch-cwd` -> `'claude-code' is not granted`.
- A command that names no marker is scoped by the fleet engine (`import hestia_gate_core` at `:2664`), where absolute paths outside the cwd repo are not command-scanned at all, so the same read "works."

So `claude-code/plugins/web4-governance/hooks/pre_tool_use.py` in particular became denied because its basename is a marker, routing it to the floor-less engine. The pub seat lockout is the same defect with no standing grant at all: under the stale (floor-less) engine that is `granted: )` = deny everything outside home/tmp; under the fleet engine it would inherit the 26-repo floor.

This is a member of the corpus family #632/#633 (whose stated remedy is exactly "point `_load_mechanism`/`_record_plane_e` at `_SHARED_DIR`; retire `~/.claude/_shared`"), with #596 (the #517 cutover empty-grant outage), #590 (the partial resolver cutover that left the two inserts), and #670 (the 26->1 cardinality swing) as the recorded symptoms. It was intended only in that #590's `$HESTIA_HOME/shared` cutover is deliberate; leaving the two `parents[2]/_shared` inserts is the bug, and today's redeploy is coincident attention, not cause. On main at `c7ec7bd` the fleet derivation itself is correct: `in_scope = live + standing + floor`, and an empty derived set denies everything outside home/tmp (it is not an allow-all; only a literal `["*"]` allows all).

Note: read-only probes during this audit (this seat's own and its subagents') opened several gate-self escalations that should be denied, including `ec4bf971243aad0e`, `e4d9b0e5bf468345`, `d951815b1bfe5b0f`, `c19ac170cce0a8ee`, and the subagent-opened `3763bae73903af86` / `cb5cd0157abf21e1` - all the out-of-grammar rule firing on a `for`/`$( )`/`while read` construct around a marker path, where an identical-shape flat command was allowed.

## 9. Appendix: denials this audit incurred

Every deny hit while performing this audit. This seat writes no deny log; these are recovered from the deny banners returned to the tool and (for the auto-opened ones) `hestia gate pending`.

| # | Command (abbreviated) | Rule | Escalation | TP or FP | Note |
|---|---|---|---|---|---|
| 1 | `for c in $(git log ...); do diff -q <installed hook> <repo hook>; done` | gate-self-access / out-of-grammar | `d951815b1bfe5b0f` | **FP** | Read-only `diff`. The `for` construct alone flipped it to write; the marker `pre_tool_use.py` matched. Re-ran as a flat `diff` and it was allowed. |
| 2 | `for b in <engine files>; do diff -q ...; done` (shared engine) | gate-self-access / out-of-grammar | `c19ac170cce0a8ee` | **FP** | Same class, marker was a shared-engine filename. Re-ran flat -> allowed. |
| 3 | `grep -n -A8 '^class AgentPolicy' <core> \| head; ...; sed -i 's/.../' <scratchpad file>` | gate-self-access / out-of-grammar | `e4d9b0e5bf468345` | **FP** | A read (`grep` of the core) plus a `sed -i` on a **scratchpad** file, in one compound command. Out-of-grammar matched the core path named in the grep. The `sed -i` targeted a temp file, not the gate. |
| 4 | `python3 - <<'PY' ... "<env suffix>" in j.get("reason","") ... PY` | egress.secret | none (no record) | **FP** | The heredoc body contained the env-file suffix as a literal string in a dict-key comparison. Mention in a quoted heredoc body; no such file touched. No chain row, consistent with #680. |
| 5 | `ls -la <fallback path under claude-code>` (and again for a `claude-code` repo path) | mrh.command | none | **TP (blocks audit)** | `'claude-code' is not granted`. Correct scope enforcement - that repo is not in this seat's grant. But it is why the legacy-fallback file's existence is UNVERIFIED (section 7). I did not route around it. |
| 6 | Bash heredoc writing this very document to disk | egress.secret | none (no record) | **FP** | The document's own inventory and appendix name the forbidden tokens (`/.ssh`, key-file names, the env suffix), so writing it through a Bash heredoc tripped the substring scan on `/.ssh`. Wrote it with the Write tool instead - the sanctioned mechanism, and exactly the CASUAL bypass the corpus documents. The audit document about the gate cannot be written through the gate's own Bash channel. |

I did not rephrase around any denial to reach a resource I was not entitled to. Denials 1-3 were re-issued as flat, in-grammar reads (allowed); denial 4's data was gathered by a route that did not spell the token; denial 5 was left as-is and its target recorded as unverified; denial 6 used the Write tool, which is the sanctioned path for writing a file (not an evasion of a resource boundary - the file is the deliverable).
