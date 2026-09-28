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
