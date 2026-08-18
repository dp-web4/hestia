# Deploying hestia — the runbook

**Merged is not deployed. Deployed is not in force. In force is not verified.**

Every one of those gaps has been hit on CBP, more than once, by three different members. This
document exists because the fleet kept rediscovering them one at a time.

---

## The four layers, and why they drift independently

A hestia deployment is **four artifacts**, each with its own path from the repo to the running
system. Any one can be current while the others are stale, and nothing about updating one updates
another.

| # | layer | lives at | updated by |
|---|---|---|---|
| 1 | **daemon binary** | `~/.local/bin/hestia` | build + `install` + `systemctl restart` |
| 2 | **member gates** (per member) | each harness's own hooks dir | **`deploy/install-members.sh`** |
| 3 | **systemd unit** | `~/.config/systemd/user/hestia.service` | copied from `deploy/templates/` |
| 4 | **deployment authority** | `$HESTIA_HOME/current-build.json` | written by the installer |

**The most common failure is treating layer 1 as the deployment.** Measured 2026-08-08: 65 commits
merged, the daemon rebuilt and running exactly `origin/main` — and **three of four members were
still running the previous day's gates.** A report of "rebuilt and redeployed current" was true of
the daemon and false of the layer that was actually refusing calls.

**Layer 1 currency is also not behavioural currency.** `hestia --version` reporting a commit behind
main means nothing if the intervening commits touched only `docs/` and hooks. Check *what changed*,
not the version string:

```bash
git diff --name-only <running-sha>..origin/main | sed -E 's|^(core/src)/.*|\1 (DAEMON)|; s|^plugins/([^/]+)/hooks/.*|plugins/\1 (HOOK)|' | sort -u
```

---

## The sequence

### 0. Know what you are deploying

```bash
git fetch origin && git log --oneline <running>..origin/main
```

Build from a **clean worktree at `origin/main`**, never from a shared checkout. The shared tree is
routinely on another member's branch with uncommitted work — verified on 2026-08-07, when a `pull`
refused to fast-forward because a peer had an unpushed commit checked out there.

```bash
git worktree add -f --detach ../hestia-deploy-main origin/main
```

> **Why an adjacent worktree and not `/tmp` or a nested `.wt/`.** `core/` has sibling-repo path dependencies —
> `hub-plugin = { path = "../../web4/hub/hub-plugin" }`, and the same shape for `web4-core`,
> `web4-trust-core`, `web4-policy`. Those resolve relative to `core/`, so a worktree anywhere
> outside the tree that holds the `web4` checkout cannot build.
> An adjacent `hestia-deploy-main` worktree preserves that relationship without tracking an
> installation-specific symlink. If the sibling dependency is absent, stop and obtain it through
> the installation's documented source mechanism rather than fabricating a repository-local link.

### 1. Daemon binary

```bash
cd ../hestia-deploy-main/core
CARGO_TARGET_DIR=<shared-target> cargo build --release
```

Then install and restart. **Check for in-flight agent sessions first** — restarting the gate while a
`--dangerously-skip-permissions` session is running leaves that session *ungated*, because
Claude-lineage harnesses fail **open** on hook timeout. A down daemon is not a denial, it is an
absence.

```bash
pgrep -cf 'claude -p --dangerously'; pgrep -cf 'kimi -p'
```

If sessions are live and the deploy can wait, stop the mesh watchers first so no *new* ones fire,
let the current ones drain against their 1800 s cap, then deploy and **re-arm the watchers**:

```bash
systemctl --user stop  hestia-watch-claude hestia-watch-codex hestia-watch-kimi
# ... deploy ...
systemctl --user start hestia-watch-claude hestia-watch-codex hestia-watch-kimi
```

A stopped watcher is invisible: mail simply stops arriving. **Re-arming is part of the deploy, not
an afterthought.**

### 2. Member gates — `deploy/install-members.sh`

**This step is mandatory and is the one most often skipped.** Merging a gate fix changes nothing
until this runs. Every FP-class repair, every predicate fix, every matcher correction is inert until
the installed copy is replaced.

```bash
DRY_RUN=1 deploy/install-members.sh     # always first: shows the plan, writes nothing
deploy/install-members.sh
```

**It must be run from a plain operator shell.** The installer refuses to run inside a governed agent
session and says why: installing there would let a session refresh the gates that decide its own
calls, for *every* member at once. There is an operator override
(`HESTIA_GATE_INSTALL_ACK=i-am-the-operator`) and it is for the human — an agent asserting it is
making a false identity claim, and routing a fleet-wide gate refresh through a script does not
change what the act is.

What the installer guarantees, each invariant learned from a defect:

- **absent destination = member not on this box → skip, never `mkdir`** (creating it fabricates a
  member, and the next audit reads the fabrication as real);
- **back up before overwrite** (the running gate is the only copy of what is currently enforcing);
- **verify by reading back, per file** (`cp` exiting 0 is not evidence the bytes landed);
- **write the authority file last, and only on full success** (a confidently-wrong indicator is
  worse than "unknown");
- targets are **derived from each harness's own registration**, not assumed — a declared path can
  drift from where the engine actually invokes the hook.

### 3. Systemd unit, when the template changes

The unit is copied, not linked, so a template change does not reach the running service.
`deploy/templates/hestia.service` carries `Environment=HESTIA_CURRENT_BUILD_FILE=…`; an installed
unit predating that line leaves the dashboard reporting `deployment: unknown` forever, with no
indication the config is stale rather than the state.

### 4. Verify — *in force*, not merged

```bash
DRY_RUN=1 deploy/install-members.sh        # every member should report "already current"
$HOME/.local/bin/hestia --version          # matches origin/main
cat "$HESTIA_HOME/current-build.json"      # build id AND per-file hashes
systemctl --user is-active hestia hestia-watch-claude hestia-watch-codex hestia-watch-kimi
```

Then prove the daemon is *governing*, not merely running — a live process and a working gate are
different facts when the failure mode is failing open. The chain should be accruing entries within
seconds of a tool call.

> **The authority file must carry per-file hashes, not only a build id.** A build id alone reports
> "current" while individual member gates are stale — exactly the 2026-08-08 state. If the file
> disagrees with a `DRY_RUN` pass, the file is wrong.

---

## Why this document exists

Recorded so the next reader does not re-derive it:

- The deployment-freshness indicator shipped with **a reader, a config line, and no writer**. It
  could not go green, therefore could not go amber — the one state it was built to show.
- The shared policy core is imported by two harnesses and **deployed nowhere**, so telemetry call
  sites resolving it by walking up from `__file__` succeed in CI (repo layout) and record nothing on
  a real member.
- `claude-code` — the member with the largest gate — had **no installer at all** until 2026-08-07,
  and was hand-deployed. That is a sufficient explanation for the drift measured against it.

The pattern behind all three: **this system builds correct mechanisms and under-connects them.**
Before adding a step here, check whether the mechanism already exists and is merely unwired.
