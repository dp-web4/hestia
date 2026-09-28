# One gate, four witnesses: the outcome half of the seam, measured

**2026-09-28, cbp-claude.** Found while qualifying hooks from agent-atlas (#1144, agent-atlas #2).
Two hooks in `~/.kimi-code/hooks/` had no hestia provenance: `witness.py` and
`prompt-disposition-watch.sh`. dp: *"most likely, kimi built those itself. this is an important
finding for our one-gate+shims work."*

## What the two files are

- **`witness.py`** is a byte-for-byte copy of `plugins/claude-code/hooks/witness.py` as shipped
  between `fdd2661` (2026-07-09, *"one witness for all members"*) and `19752a3` (2026-08-06);
  git blob `5d6362f`. Its docstring still says "Hestia witness hook for Claude Code".
  - Until 2026-07-26, Kimi's `config.toml` ran it from the hestia checkout on 9p, so it
    tracked every change.
  - On 2026-07-26 around 11:41, a Kimi session relocated its hooks to ext4. From the session
    transcript: *"Deploy steps: 1. mkdir -p ~/.kimi-code/hooks … 2. cp the files … 3. Edit
    config.toml hook commands … witness.py → python3 /home/dp/.kimi-code/hooks/witness.py
    (keep HESTIA_PLUGIN_ID=kimi-code)"*.
  - The copy froze. Nothing refreshed it: the Kimi plugin never declared a witness, so the
    installer had nothing to maintain.
  - It has since missed 8 changes. Among them: #977 (close the action the gate authorized),
    #696 (spool on daemon outage, so fail-open means DEFER, not DESTROY), and the host-session
    and role-basis fields.
- **`prompt-disposition-watch.sh`** (2026-08-27) exists nowhere in hestia's history. Kimi wrote
  it for #366: an approval sat unread while its 600 s claim window burned, because the mesh inbox
  is read only at SessionStart. It peeks the inbox on every prompt and surfaces new dispositions.
  It is a seat-built capability hestia does not ship, for a gap that is still open.

## The measurement: does the gate's action get its outcome?

A `gate:warn` action executes, so under #977 the witness should close it with an outcome under the
**same `action_id`**. Measured from `~/.hestia/reputation-deltas.jsonl` (plaintext; 2026-07-10 to
2026-09-28), per member LCT:

| member | warned acts with a same-id outcome | since #977 (2026-09-07) |
|---|---|---|
| claude-code | 1985 / 10342 (0 of 7403 in Jul–Aug) | **1985 / 1986** |
| kimi-code | 0 / 103 | **0 / 37** |
| codex | 0 / 13 | **0 / 1** |

(`allow` decisions produce no reputation delta, so warns are the observable sample. The chain
itself is SQLCipher and its MCP read returns 500 entries, so it cannot reach this history.)

## Per harness, on current main

| harness | ships a daemon witness | #977 correlation in it | declared observe target | what reports outcomes |
|---|---|---|---|---|
| claude-code | yes | yes (4 refs) | none (event-only) | shipped witness |
| codex | yes | **no (0 refs)** | `witness.py` (#1134) | shipped witness, not linked to the gate |
| kimi | **no** | — | none | **the seat's frozen 07-26 fork** |
| gemini | **no** | — | none | **nothing reaches the daemon**; `observe.sh` writes a local file |

In every row the inventory reads the observe role as served. For kimi and gemini it is served by
event only, via `observe.sh`: the #1133 shape, still open for two harnesses.

## What it means for one-gate + shims

- **The witness forked the way the gate did.** #934 found four seat orchestrators sharing a law
  library. The outcome side is the same, one level down: four witness situations, and the #977 fix
  in one of them. A fix to a per-harness copy is a fix to that harness. The other copies do not
  inherit it.
- **#1139 unifies the decision record, not the outcome record.** Without a shared outcome path,
  a unified gate still produces evidence that cannot be joined to what ran on 3 of 4 harnesses.
  The correlation that #1140 calls "a private `/tmp/hestia-actions` bridge" is exactly what
  claude-code's witness has and the others lack.
- **A seat fills a governance gap with a private fork.** The fork is invisible to review, to the
  installer and to the inventory (until #1144). The same happened with `society_pre_tool_use.py`
  in the same directory, retired 2026-08-13.

## Recommendations

1. **One outcome witness in the shared core, beside #1139's decision witness.** Shims only map
   their harness's PostToolUse / AfterTool event shape onto it. Correlation with the gate's
   action lives in the core, and no shim carries its own.
2. **Every harness plugin ships it and declares it:** `targets: {observe: [<witness>]}`. The
   inventory then reads a role served only by `observe.sh` as MISWIRED, as #1134 does for codex.
3. **Acceptance metric per harness:** the share of warned acts closed by a same-id outcome, from
   the delta stream, as above. claude-code shows ~100% is reachable.
4. **Retire Kimi's fork** once the shipped witness reaches Kimi. Until then it is Kimi's only
   daemon witness, so removing it now would stop Kimi's outcome evidence entirely.
5. **Upstream `prompt-disposition-watch.sh`** into member-mesh for every seat, or close #366
   another way. A seat built it because the gap is real.

## Decision and follow-through (same day)

dp agreed all five recommendations: *"document the findings, and agreed on all 5. go ahead"*.
Implementing them turned up four more facts. Each one changes what "one witness" had to contain.

1. **Only claude-code's GATE cached the action it began.** The #977 seam has two halves. The gate
   writes the action id under a per-call key, and the witness reads it. Only
   `plugins/claude-code/hooks/pre_tool_use.py` ever wrote `/tmp/hestia-actions`. So copying
   claude-code's witness to kimi (the 07-26 fork) could never have closed anything: the
   half it needed was not in any file it copied. The fix puts the write in the shared
   mechanism: `query_society_safety(..., correlation_key=)`. Every gate that asks the
   daemon now caches the id through that one call.
2. **Each harness names the call differently.** claude-code and codex send `tool_use_id`;
   codex's `pre-tool-use.command.input` schema requires it. Kimi sends `tool_call_id`, from
   `toolCallId: ctx.toolCall.id` in its hook runner. The fork keyed on `tool_use_id`, so it
   fell back to the SESSION id and matched nothing. Gemini sends no call id at all, and its
   gate hands the governor a translated event. The shared key rule takes the harness's own
   call id first. Failing that, it derives a key from the fields both events carry, reading
   the pre side from the untranslated `source_event`.
3. **Kimi reports a failed call as its own event.** Kimi fires `PostToolUseFailure` instead of
   `PostToolUse` when a call fails. Its registration put the witness on `PostToolUse` only, so
   **no failed kimi act was ever witnessed**: 3,235 failure events sit in kimi's local observe
   log, and none reached the chain. The core closes all three outcome events (`PostToolUse`,
   `PostToolUseFailure` and gemini's `AfterTool`). Kimi now declares both events, served by
   `witness.py`, so a host missing either one reads as MISWIRED.
4. **The upstreamed disposition watch had to drop one line** (#1148). Kimi's hook told the
   reader to `hestia gate poll <id>`. On claude-code, co-seats share a plugin id, and `poll`
   arms the ASKER's claim window (#732). On 09-18, 6 of 6 dispositions delivered to claude-code
   were a co-seat's. The shipped watch keeps everything else. It is interim: #366's real fix is
   the session-addressed lane in #849 / PRD_DISPOSITION_DELIVERY R4.

**Implementation prepared, and where it lands.** Status as of 2026-09-28 (GPT review of 08e6caa):
nothing below is on main, deployed or live-verified yet. Each row says how far it has actually got.

| rec | landing target | status |
|---|---|---|
| 1. one outcome witness in the core | `plugins/_shared/hestia_witness_core.py` holds both halves of the seam; the gate half is in `query_society_safety(..., correlation_key=)` | core file committed on branch `cbp/one-outcome-witness`; the other 19 files are one patch awaiting governance approval |
| 2. ship and declare | byte-identical `hooks/witness.py` shims; `targets.observe: [witness.py]` for every harness; kimi registration template plus the flat-layout reader; gemini installer | built, same patch |
| 3. acceptance metric | `tools/witness_closure_census.py [--min-rate R --min-warns N]`; certification criterion C13 | built and tested; reproduces this finding's table live |
| 4. retire kimi's fork | the installer's registered path for kimi's `witness.py` is the fork's own path, so the first deploy replaces it (`.pre-install.bak` kept) | follows rec 1's merge and deploy |
| 5. upstream the disposition watch | member-mesh, `UserPromptSubmit`, on claude-code, kimi and codex | #1148; held by GPT (a per-member watermark lets a sibling session consume the asker's ruling), being reworked to track presentation per session |

The recommendations are also recorded where the one-gate plan is kept. `docs/PRD_GATE_CONSOLIDATION.md`
§14 closes the open criterion 11 by naming its root. `docs/PRD_SHIM_CERTIFICATION.md` C13 makes
the outcome half a certification criterion, and states the contract that #934, #1139 and #1140
must keep.

**Still open, found along the way.** Gemini's gate runs the governor as
`HESTIA_PLUGIN_ID=gemini-cli`, but the seat's projection and expects are `gemini`. The governor
would therefore look for a `seats/gemini-cli.env` projection that does not exist. This was not
measured live, because no gemini observe log exists on CBP.

**The acceptance test after deploy:** `witness_closure_census.py --since <deploy time>` should
move kimi-code and codex from 0% toward claude-code's 99.9%. If it does not, the finding's
diagnosis is incomplete, which would be the next finding.

## Reproduce

```
git -C hestia log --all --find-object=5d6362fdb9673f42d3d4b6238f078b5357269532   # the fork's origin
python3 - <<'PY'   # warned-act closure per member LCT (lcts from any recent chain row's instance_lct)
import json, collections
warn=collections.defaultdict(set); out=collections.defaultdict(set)
for l in open('/home/dp/.hestia/reputation-deltas.jsonl','rb'):
    try: r=json.loads(l)
    except Exception: continue
    a, s, why = r.get('action_id'), r.get('subject_lct'), r.get('reason','')
    if why.startswith('gate:warn') and r.get('timestamp','')>='2026-09-07': warn[s].add(a)
    if why.startswith('outcome:'): out[s].add(a)
for s in warn: print(s, len(warn[s] & out[s]), '/', len(warn[s]))
PY
```
