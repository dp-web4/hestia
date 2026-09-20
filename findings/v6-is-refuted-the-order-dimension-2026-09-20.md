# v6 is refuted, by the generator that cleared it — the battery had no ORDER dimension

`2026-09-20` · CBP · claude-code · PR #1082 · supersedes the v6 candidate in
`findings/the-holes-are-a-product-space-2026-09-20.md`

## The ask that never arrived

On the v6 write-up I asked codex for one thing: *attack v6, it passes a battery I wrote,
which is exactly what made v5 look safe.* That notice (13425) bounced —
`fire-rc=1;why=out-of-credits`. Nobody was going to run it. I named the falsifier
precisely enough to run it myself, so this is that run, against my own candidate.

## Result

| | unsafe rows | of | new unsafe |
|---|---|---|---|
| v6 `8d39395`, battery as shipped in that commit (4 dimensions) | **0** | 5,634 | 0 |
| v6, **same battery plus an ORDER dimension** | **48** | 17,490 | 48 |
| v7 (below), same extended battery | **0** | 17,490 | 0 |

v6 is refuted. All 48 rows are one order — `write-first-comment` — across 11 contexts and
2 binding forms. Every row adjudicated by bash; nothing written.

## Why the battery could not see it

The generator emitted `prefix + separator + write` and nothing else. The binding was
always before the write. So the one invariant every version has carried since v1 —
**(V5) the binding precedes every use** — was the one invariant the generator could not
vary, and therefore could not test. 5,634 green rows said nothing about it.

This is the same defect as the one it failed to find, one level up: *a dimension held
constant is a dimension not measured.* The v5 write-up said a hand-written case list
measures its author. A generator that does not generate a dimension measures its author
just as narrowly, and hides it behind four digits of sample size.

## The defect in v6

v6 proves (V2)–(V4) over **bash's rendering** and then enforces (V5) over `_tokenize` of
the **raw command**, mapping the two by searching the raw token stream for the binding's
text. The two representations disagree, and the disagreement is a property v6 *advertised
as a feature*: the pretty-printer strips comments, `_tokenize` does not.

```
# OUT=/tmp/battery-safe
echo plugins/_shared/hestia_governance_closure.py > "$OUT"
OUT=/tmp/battery-safe
```

The rendering has two lines and one bare `OUT`, so (V2) and (V3) pass. The name is then
released at the **comment's** raw token index — ahead of the write it is required to
follow. bash writes to the governed path; v6 answers `read`; the shipped gate answers
`write`. Three spellings of the comment reproduce (`# X`, `true # X`, trailing
whitespace).

(V2)'s uniqueness — exactly one bare occurrence of the name — is what makes a needle
search for `NAME=value` sound. That property was only ever measured in the rendering, so
the search is only sound there.

## v7: scan the representation the proof was stated over

`tools/redirect_target_resolver_v7.py` is v6 with one line changed and no clause added:

```python
toks = g._tokenize(rendering if rendering is not None
                   else g._strip_heredoc_bodies(command))
```

0 unsafe of 17,490 on the extended battery, and it keeps v6's benefit: 1,878 false
positives vs the shipped 1,926 on the generated space, and the same real-corpus clearing.

**v7 is unreviewed and passes a battery I wrote.** Named and unproven: the write-shape
dimension is barely varied (see below), and nothing here tests a resolver under a
rendering bash produces but this box's bash version does not.

## Two control arms that changed the conclusion

A first pass flagged `cont-join`, `heredoc-decoy`, `quoted-decoy`, `skipped-body-decoy`
and a comment-after-a-compound as v6 holes as well. They are not. Those probes used
`echo x > $OUT`, with no governed path in the command text, and the thing that failed was
not the resolver — see the next section. Re-run with the governed path in the text, only
the three comment spellings reproduce. **Five of eight apparent findings were my own
missing control arm.**

## What the control arm found instead: the fail direction is not what we documented

v6's docstring, and the PR body, both say:

> FAIL DIRECTION. Unchanged: anything unproven resolves to nothing, and an unresolved
> destination is classified `write`.

That is false, measured against the **installed** closure at
`/home/dp/.claude/_shared/hestia_governance_closure.py` — the copy governing this seat:

| command | destination bash uses | classification |
|---|---|---|
| `echo x > "$OUT"` | governed file | **`none`** |
| `echo <governed> > "$OUT"` | governed file | `write` (`governance-closure-out-of-grammar`) |
| `SRC=$(git diff --name-only \| head -1)` + `cp /tmp/new "$SRC"` | governed file | **`none`** |
| `echo x > <governed>` *(control)* | governed file | `write` (`governance-closure-write`) |

`_OutOfGrammar` does not mean `write`. It means *out of grammar*, and the escalation to
`write` requires the governed path to appear in the command **text**. An unresolvable
write destination, in a command that does not spell a governed path, is classified `none`
and goes ungoverned.

The extended battery demonstrates this on one variable. Crossing the context/order space
with six more write spellings (`--extra-writes`), the shipped gate has **181 unsafe rows,
and all 181 are the single shape whose text does not mention the governed path**:

```
cp /dev/null "$OUT"; OUT=/tmp/battery-safe        ->  shipped: none
```

`append`, `tee`, `heredoc`, `two-writes` and `fd-dup` all carry the governed path as an
argument, and all are classified `write` — by the text, not by the destination.

### Why this reframes PR #1082

The false positives this PR exists to clear are, every one of them, commands that mention
a governed path in their text. That is the only reason they were ever classified `write`.
The identical unresolvable destination, in a command that does not mention one, is already
allowed today. So the resolver's benefit and the gate's exposure are two faces of one
decision nobody wrote down: **the gate trusts the text when it cannot resolve the
target.**

Whether that trade is right is a separate question with a real argument on both sides —
without the text condition, every command with a variable destination escalates. What is
not defensible is that it is documented as the opposite. The resolver work is worth
finishing either way; it should stop claiming a fail direction the gate does not have.

Not measured here, and worth measuring next: how many real corpus commands have an
unresolvable write destination and no governed path in their text.

## Reproduce

```
python3 tools/redirect_resolver_battery.py --file tools/redirect_target_resolver_v6.py   # 48 unsafe
python3 tools/redirect_resolver_battery.py --file tools/redirect_target_resolver_v7.py   # 0
python3 tools/redirect_resolver_battery.py --file tools/redirect_target_resolver_v7.py \
        --only-binding plain --extra-writes                                              # shipped 181
```
