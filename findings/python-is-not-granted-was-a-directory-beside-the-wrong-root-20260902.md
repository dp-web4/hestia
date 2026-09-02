# 'python' is not granted was a directory beside the wrong root

Date: 2026-09-02. Seat: claude-code on CBP. Predicate: `hestia_gate_core.command_in_scope` at main `4aa2260`. Instrument: `tools/mrh_scope_differential.py` (this PR). Status: MEASURED, REPRODUCED IN A FIXTURE, REMEDY PROPOSED, PARSER UNCHANGED.

## What was seen

Seven `mrh.command` refusals in one hour of read-only work, each naming a token that is not a path:

| refusal | command shape |
|---|---|
| `'exec' is not granted` | `exec(compile(...))` inside a python heredoc body |
| `'*' is not granted` | `ls -d <root>/*/` |
| `'python' is not granted` | `echo "ci python test step"` (#744, again) |
| `'#' is not granted` | `sed "s#<root>#<P>#g"` |
| `'ai-agents' is not granted` | the word in prose; and every genuine out-of-scope reach |

#744 read this as quoted data being extracted and checked as a command. #760 carried that reading into its design: "never tell the member 'python' is not granted when the only occurrence was quoted data", filed under the TOOLS axis. The memory this seat carries said the same: `python`, `exec`, `ai-agents` are lexical tokens the gate trips on.

All three readings are wrong about the mechanism. No command name is being checked anywhere.

## The mechanism

`command_in_scope` has two passes.

Pass 1 splits the command text on the resolved workspace root string and reads the next path segment as a repository name. A glob (`*`), a sed delimiter (`#`), or the empty segment (naming the root itself) all arrive in that position.

Pass 2 takes every bare token of the command, quoted or not, and if the token equals the name of a directory that exists beside the granted repositories under the resolved root (`_all_repos(workspace)` is a plain `os.listdir`), probes the filesystem under the event cwd and under every granted repository root. An existing out-of-scope hit is a deny.

So `python` denies exactly when (a) the seat's resolved root has a sibling directory called `python`, and (b) the event cwd is where that directory is.

On this seat both held. The claude-code hook line carries no `HESTIA_WORKSPACE` (codex and gemini both pin `.../ai-agents` inline; `deploy/fleet/install.sh` writes a `.hestia-workspace` marker, never run here). `detect_workspace` therefore falls to the session cwd, which is `/mnt/c/exe/projects`: one level ABOVE the directory every grant lives under. That level has 22 sibling directories, among them `python`, `exec`, `misc`, `archive`, `ye`, and `ai-agents`.

Two consequences follow that nobody had attributed:

- Every genuine out-of-scope reach at that root is reported as `'ai-agents' is not granted`, because `ai-agents` is the first segment under the wrong root. The deny names the container of every grant as the offender; a member reading it would ask for scope it already holds. The "ai-agents token FP" this seat remembered was this, not a lexical match.
- The same token passes when the event cwd is inside a granted repository. The verdict on a fixed command varies with where the session happened to be parked.

A second, independent cause makes `ai-agents` collide even at the right root: `/mnt/c/exe/projects/ai-agents/ai-agents` is a self-referential symlink dated 2025-11-21. `os.listdir` lists it, so the workspace's own name is one of its "sibling repos".

## Reproduced without the host

`tools/mrh_scope_differential.py` builds the layout in a tempdir (wrong root with `python`, `exec`, `misc`, `archive`; the real root beneath it with a granted `hestia`, an ungranted `private-context`, verb-shaped `docs` and `scripts`, and the self-link) and runs each case at four cells: root in {wrong, right} x cwd in {root, granted repo}.

```
case                                     wrong/root         wrong/repo         right/root         right/repo         expect
744.echo-label-simple                    deny 'python'      allow              allow              allow              allow  FP  split
744.echo-label-compound                  deny 'python'      allow              allow              allow              allow  FP  split
744.grep-pattern-compound                deny 'python'      allow              allow              allow              allow  FP  split
0902.exec-in-heredoc-body                deny 'exec'        allow              allow              allow              allow  FP  split
0902.sed-delimiter-after-root            deny '#'           deny '#'           allow              allow              allow  FP  split
0902.bare-word-in-prose                  deny 'ai-agents'   allow              deny 'ai-agents'   allow              allow  FP  split
0902.verb-shaped-sibling-at-right-root   allow              allow              deny 'scripts'     allow              allow  FP  split
0902.glob-under-wrong-root               deny '*'           deny '*'           allow              allow              -      split
0902.name-the-right-root                 deny 'ai-agents'   deny 'ai-agents'   deny '<ws root>'   deny '<ws root>'   -
ctl.interpreter-head                     allow              allow              allow              allow              allow
ctl.granted-absolute-read                allow              allow              allow              allow              allow
ctl.ungranted-sibling-repo               deny 'ai-agents'   deny 'ai-agents'   deny 'private-c'   deny 'private-c'   deny
ctl.traversal-out-of-grant               deny 'ai-agents'   deny 'ai-agents'   deny 'private-c'   deny 'private-c'   deny

cases with a false positive cell: 7   false negative: 0   root/cwd splits: 8
```

Read down the columns. The wrong root plus a cwd at that root reproduces every live refusal, token for token. The right root removes five of the seven. The seventh row shows the right root is not sufficient: a session parked at the real workspace root still denies on any bare word that names a sibling directory there (`scripts`). The controls deny where they should at every cell; at the wrong root they deny with the wrong offender.

The pins in the instrument record these cells, false positives included. CI runs it in pinned mode, so a regression and a fix are both visible as cells moving; `--strict` is the acceptance for #760's replacement model and exits 1 today.

## What this changes

For #744: the specific regression is a FILES-axis defect (a token judged as a path because a directory of that name exists under the event cwd), not a TOOLS-axis one. It closes when `--strict` is green on the three `744.*` rows.

For #760: the TOOLS + FILES migration remains the right shape, but the parse contract it names must include the two things this measures: a bare token is a path reach only in a path position (never from inside quoted data, a heredoc body, or a sed program), and the offender in a deny must be the resolved path, not the first segment under whatever root the seat happened to resolve. The wrong-root case is the one the migration cannot fix on its own; it is a deployment defect, below.

For #695 (token-vs-prefix, closed into #760): `'*'` and `'#'` are its family, arriving through pass 1.

## Remedies, by layer

1. Deployment, this seat, one line: the claude-code hook command in `~/.claude/settings.json` gains `HESTIA_WORKSPACE=/mnt/c/exe/projects/ai-agents` the way codex's and gemini's already carry it. This is the seat's own hook line, so it is an operator edit, not a member edit. Expected effect on the live seat: rows 1 through 5 stop firing; row 6 keeps firing until the symlink goes; row 7 keeps firing whenever the session cwd is the workspace root.
2. Host hygiene: the self-symlink `ai-agents/ai-agents` (2025-11-21) should go. It is outside every grant and outside `/tmp`, so it is the operator's deletion.
3. Installer: `deploy/install-members.sh` registers the claude-code hook line without a workspace, and `deploy/fleet/install.sh` writes the marker only when `HESTIA_WORKSPACE` is passed. A seat installed by the first and never touched by the second resolves its root from wherever its first session starts. One of them should refuse to register a gate with no workspace, the way `plugins/gemini/install.sh` already does ("public installers do not guess host layout").
4. Predicate (#760): pass 2 should not turn a bare token into a filesystem probe on the strength of the event cwd alone; pass 1 should reject a glob, a delimiter, or an empty segment as a repository name rather than deny on it; the deny should carry the resolved path.

## What is not claimed

The seven refusals were counted from this seat's own session; no rate over the fleet is offered. Codex and gemini carry the workspace and were not measured here; kimi's hook line was not read. Whether the daemon-side `mrh.path` scope check shares any of this is untested. The remedy in (1) is proposed, not applied, and its expected effect is a prediction the instrument can check after the edit by re-running the live commands, not by re-running the fixture.
