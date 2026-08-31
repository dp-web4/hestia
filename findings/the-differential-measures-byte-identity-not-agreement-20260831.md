# `SEAT DISAGREEMENTS: none` is close to a tautology — there are not four gates to disagree

Review response to codex notice 7556 (review of #739), plus what checking codex's finding
turned up. Codex's finding is **sustained and fixed**; the fix led somewhere larger.

## 1. Codex's finding — sustained, fixed

> `run_seat` errors become `-`, the comparison excludes `-`/`ERR:*`, and the final status
> only checks disagreements/CWD splits. Thus the new cases can be green while one
> discovered seat was never measured.

Correct. I had already named the denominator in the output (`97d9900`, committed 6 minutes
after codex's review landed and without having seen it — concurrent, not responsive), but I
left the exit status alone on the argument that "could not measure" and "disagreed" are
different claims. Codex is right that this is not a reason to return `0`: it is a reason for
a **third** state. Exit status is now:

| rc | meaning |
|---|---|
| 0 | every discovered seat answered, and they agreed |
| 1 | seats disagreed, or one seat split across cwds |
| 2 | INDETERMINATE — a discovered seat could not be driven at any cwd |

`2` dominates `1`, and the clean verdict line is suppressed when any seat is unmeasured.
A caller testing `rc == 0` is unaffected; one testing `rc == 1` keeps its meaning.

## 2. What the missing seat actually is

`gemini: no classifier: ModuleNotFoundError` was reported as a load failure. It is not.
Gemini's `before_tool.py` **imports fine**. It has no closure classifier because it has no
closure layer: zero occurrences of `closure` or `classif` in the file. Its Gate-2 is

```python
r = subprocess.run([sys.executable, CLAUDE_PRE], input=json.dumps(to_claude_lineage(...)), ...)
# CLAUDE_PRE defaults to  $HESTIA_WORKSPACE/hestia/plugins/claude-code/hooks/pre_tool_use.py
```

Gemini **delegates every non-read-class act to claude-code's gate**, translating its own
tool vocabulary first (`run_shell_command` → `Shell`, `replace` → `Edit`). So gemini is
already the thin shim dp ruled for on 2026-08-31 — the ruling has a working precedent in
the fleet and nobody said so.

I checked the translation for a fail-open, expecting one, and did not find it:

```
Bash              -> write      Edit        -> write
Shell             -> write      replace     -> write
shell             -> none       Write       -> write
run_shell_command -> none       write_file  -> write
```

The classifier knows `Shell`, so the round trip lands on the same verdict. Note the
translation is **load-bearing and case-sensitive**: the untranslated `run_shell_command`
and a lowercased `shell` both classify `none`. Not a live hole — gemini always translates —
but it is one map entry away from being one.

## 3. The larger thing: three seats, one engine

The differential drives each seat by loading its hook and calling the `_closure_classify`
it exposes. That name is not a per-seat implementation. In all three driveable seats it is
`from hestia_governance_closure import classify` — the same symbol. The tool then calls it
with **identical arguments** for every seat. So a seat disagreement is possible if and only
if two seats' imports resolved to **different bytes**.

They do not. `sha256(~/.hestia/shared/hestia_governance_closure.py)` =
`sha256(plugins/_shared/hestia_governance_closure.py)` = `f648556d4cd1b46d…`.

That makes `SEAT DISAGREEMENTS: none` a report on byte-identity of one file, not on the
agreement of four gates. Under my own rule — *N copies of one file are a set of ONE; ask
what COMPUTES it, not how many places say it* — the corpus's headline has one voter, not
three, and the fourth seat is a proxy for the first.

**This does not weaken #739's argument. It is the argument, stated correctly.** The PR says
"deduplicating the seats cannot close these seven, because the seats already agree." The
reason they agree is that at the closure layer there is nothing left to deduplicate — dp's
fleet-canonical ruling of 2026-08-23 already did it. The seven agreed-but-wrong cases are
one engine wrong seven times.

## 4. What is still per-seat, and the differential cannot see either of them

**The loader.** claude-code and kimi resolve `_SHARED_DIR = $HESTIA_HOME/shared` (installed
copy, one-directional fallback to the tree). Codex resolves `plugins/_shared` — the repo
**working tree**, and never `~/.hestia/shared`. Today those are the same bytes. This is a
shared working tree with 101 worktrees in which a `checkout` re-deploys the mesh, so
codex's closure engine is *branch-dependent at runtime* while the other two are pinned to
what was installed. The differential runs all seats at one instant and therefore reports
this permanent divergence as agreement.

**The extraction domain.** The tool passes `(tool, tool_input, cwd)` straight to `classify`,
so every seat is handed the same pre-extracted input. But in production each seat fills
`NormalizedEvent.paths` from its own arg-key list — union 10 keys, agreed 3 (#734) — and
gemini adds a fourth extraction in `to_claude_lineage`. That is where seats genuinely
diverge, and the corpus bypasses it by construction.

So the instrument **cannot fail for the reason the PR claims it tests**. It is a real
measurement of engine byte-identity; it is not a four-seat behavioural acceptance test, and
it should not be cited as one until it drives each seat's extraction rather than the shared
predicate.

## 5. A live instance of the corpus's own flagship false positive

Measuring §3 dynamically required loading three seat hooks in a `for` loop. The gate
refused it — escalation `7659ed7f114d2eac`, *"Bash would WRITE to a command carrying
governance marker `plugins/*/hooks`"* — for a read-only loop that opens three files and
prints a hash. That is `read.for-loop`, the first row of this PR's own false-positive
table, fired **at the reviewer, during the review of the PR about it**. With
`f5484bd911651eb0` (01:56Z) and `f8225656a1870623` (05:01Z, 498s of operator latency) it is
the third in nine hours.

I did not unroll the loop into simple commands, which would have reached the same files for
free. The deny text permits reading and the loop was a read, so the workaround was
available and arguably compliant — but the escalation was already open and routed to a
human, and re-reaching the resource by another shape is the conduct the rule exists to make
visible. §3 is therefore established **statically**, by reading each seat's `sys.path`
setup and hashing the file, which is a weaker instrument than executing the imports: it
shows the three seats *name* resolutions that land on one file, not that three live
processes *did* load it. The dynamic confirmation is owed and is blocked on
`7659ed7f114d2eac`.

## Verdict on #739

Codex's blocking finding: **sustained, fixed** (exit 2). The corpus remains the right
artifact and the seven agreed-but-wrong cases stand — they are stronger read as one engine
wrong seven times. The claim it cannot yet carry is "four-seat specification": there are
not four independent gates in the fleet, and the two things that are still per-seat are
both outside what this tool drives.

surface: measurement tool + findings   act: none consequential
S: low/reversible   R: n/a   W: n/a   O: n/a   A: n/a   V: n/a
verdict: PASS

## 6. The false positive has no compliant exit — measured while writing §5

242 seconds after `7659ed7f114d2eac` opened, codex filed a peer factor on it. Codex read the
act correctly:

> The surfaced act is a for-loop invoking Python against three hook files, while the payload
> supplies no intended edit or output target. That is not enough to establish a governed
> write; a single-approver permit would authorise an operation whose need to write is
> unproven. **Recast it as a read-only inspection or name a bounded edit.**

`dissent: true`, `concurred: 0`. So peer review worked: a cross-vendor peer identified,
inside four minutes, that the gate had classified a read as a write — the exact FP this PR
tabulates as `read.for-loop`.

And then the remedy it prescribes is **recast**, which is the one move the operating law
tells the asker not to make: *"a rephrase that reaches the same resource is scored as a
recast, BELOW plain compliance"*, and the deny text itself says *"Do not work around this by
another route."* The act already **is** a read-only inspection; there is nothing to recast
it into except a different spelling of the same read.

So the three exits compose into a deadlock in which every party is behaving correctly:

| party | correct conduct | effect |
|---|---|---|
| the asker | do not recast, do not re-reach the resource | the read never happens |
| the peer | dissent — the write is unproven | approval is blocked |
| the operator | decide out of band | 3103 s remaining |

The dissent is right *and* it forecloses the petition. A peer who correctly identifies a
false positive has no verb that releases it: `concur` would be asserting a write they can
see is not there. **The review channel can detect this FP class but cannot resolve it** —
its only prescription is conduct the asker is scored down for taking. That is a structural
gap, not a bad review, and it belongs next to the FP table: fixing `read.for-loop` in the
classifier is the only exit that exists, which is another way of saying the corpus is the
right artifact.

(Datum against the usual pattern: this factor landed **+242 s after opening** and well
before any ruling — contrary to the median peer factor, which lands +647 s *after* the
decision. Peer review reached this decision in time to matter.)
