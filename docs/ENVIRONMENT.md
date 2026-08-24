# Environment

Hestia locates everything through environment variables. Nothing in the product
searches for a workspace, enumerates familiar directory layouts, or infers a path
from a hostname — that rule is not a style preference, it is the public boundary
(`docs/PUBLIC_PRIVATE_BOUNDARY.md`): *"Runtime code does not search for a
maintainer's private repositories, enumerate familiar workspace layouts, or treat
a public example as a live configuration."*

The consequence worth stating up front, because it is the whole reason this file
exists: **an unset path variable is a supported state with a defined behaviour,
never a signal to go looking.** A capability whose variable is unset reports
unknown and declines; it does not guess and it does not fail the daemon. That is
safe, and it is also quiet — which is exactly why the variables have to be
written down somewhere a person can read.

## The variables

Every default below was read out of the source, not remembered. Where a variable
has no default, this file says so rather than inventing one.

### Daemon

| Variable | Required | Default | What it does |
|---|---|---|---|
| `HESTIA_HOME` | no | `~/.hestia` (`%h/.hestia` in the unit) | State root: `vault.enc`, `.passphrase`, `current-build.json`. Everything durable lives here. |
| `HESTIA_BIND` | no | `127.0.0.1:7711` | Listen address. Loopback by default and deliberately: reachability is not authority, so binding wider does not grant anything, but it does widen who can attempt. |
| `HESTIA_PASSPHRASE` | yes, at start | none | Vault passphrase. The shipped unit reads it from `$HESTIA_HOME/.passphrase` (mode 600) at `ExecStart` rather than storing it in the unit. **Never put this in a unit file, a shell profile, or Git.** |
| `HESTIA_CURRENT_BUILD_FILE` | no | `$HESTIA_HOME/current-build.json` | Deployment authority: the build the supervisor installed. The dashboard turns amber when it differs from the build actually running. |
| `RUST_LOG` | no | `warn` | Log level. |

### Workspace (optional, and optional on purpose)

| Variable | Required | Default | What it does |
|---|---|---|---|
| `HESTIA_WORKSPACE` | **no** | empty | Root directory containing the `hestia` checkout and any sibling repositories. Used to locate optional tooling — e.g. `agent-inventory` at `$HESTIA_WORKSPACE/hestia/plugins/agent-inventory/inventory.py`. |

**Unset is valid.** With it empty, inventory reports *inference/unknown* rather
than guessing a layout, and the daemon starts and serves normally. Nothing breaks;
one dashboard read is simply less informative. The failure mode is a capability
quietly not being there, not an error — so if a workspace-dependent feature looks
absent, check this variable before looking for a bug.

Set it when you want those features, and set it **explicitly**. Installers render
it from operator-supplied configuration; they must never derive it by probing.

**Tooling that resolves a workspace root** (currently `tools/cargo_target_reaper.py`)
accepts, in order: `AI_WORKSPACE`, then `HESTIA_WORKSPACE`, then **`FLEET_ROOT` (legacy)**,
then a value derived from the tool's own location. One fact, one precedence — `FLEET_ROOT`
predates the others and keeps working because it may be set in units nobody has audited,
but it should not be used in anything new. A variable that is set but names a directory
that does not exist is **refused**, not skipped: quietly measuring a different tree than
the one you named is worse than stopping.

### Members (gate hooks)

Set in each member harness's hook environment, not globally.

| Variable | Required | Default | What it does |
|---|---|---|---|
| `HESTIA_PLUGIN_ID` | yes, per member | none | Identifies the member making the call (e.g. a harness id). |
| `HESTIA_ROLE` | no | none | Member role, when the harness declares one. |
| `HESTIA_ENDPOINT` | no | `http://127.0.0.1:7711/mcp` | Daemon endpoint the hook calls. |
| `HESTIA_PRE_FAIL_CLOSED` | no | unset (off) | When set, a pre-tool hook that cannot reach the daemon **refuses** instead of allowing. Turns daemon availability into a governance property — read `docs/PUBLIC_PRIVATE_BOUNDARY.md` and the gate docs before enabling it fleet-wide. |
| `HESTIA_OBSERVE_DIR` | no | `~/.codex/hestia-observe` | Where an observing (non-gating) member writes its record. |
| `HESTIA_HOOK_DEBUG` | no | unset | Presence enables hook debug output. |

### Operator

| Variable | Required | Default | What it does |
|---|---|---|---|
| `HESTIA_GATE_INSTALL_ACK` | no | none | `deploy/install-members.sh` refuses to run inside a governed agent session, because installing would let a session refresh the gates that decide its own calls — for every member at once. Setting it to `i-am-the-operator` proceeds and says so in the output. It is for a human at a plain shell; an agent asserting it is asserting an identity it does not have. |

## How to set them

Three layers, and they do not substitute for one another. This is the most common
source of confusion: exporting a variable in your shell does **not** put it in the
daemon's environment, because the daemon is started by the service manager, not by
your shell.

**1. The daemon** — the service unit is authoritative.
`deploy/templates/hestia.service` carries the `Environment=` lines. Edit the
installed unit (or re-run the installer), then:

```
systemctl --user daemon-reload
systemctl --user restart hestia
```

**2. Your shell** — for CLI use (`hestia …`) only. Put exports in your shell
profile. This has no effect on the running daemon.

**3. Member hooks** — in the harness's own hook/registration configuration.
`deploy/install-members.sh` derives *where* each member's hooks go from that
harness's **registration**, never from a declared path, because the copy that
enforces is by definition the one the harness invokes.

## What the installer does for you

`deploy/fleet/install.sh` renders the unit with `HESTIA_HOME` and `HESTIA_BIND`,
creates `$HESTIA_HOME` mode 700, and writes the passphrase file mode 600. It
accepts overrides as environment variables at install time:

```
HESTIA_HOME=... HESTIA_BIND=... HESTIA_WORKSPACE=... bash deploy/fleet/install.sh
```

`HESTIA_WORKSPACE` is rendered from what you pass and left **empty if you pass
nothing** — the installer will not guess it. If you want workspace-dependent
features, pass it; if you do not, that is a complete and supported install.

## Verifying what is actually set

Read the running process's environment rather than assuming the unit and the
process agree — a unit edited after start is a real and silent divergence:

```
systemctl --user show hestia.service -p Environment --value
```

And check that the build serving requests is the build you installed:

```
hestia --version
cat "$HESTIA_HOME/current-build.json"
```

If those two disagree, the daemon is running an older binary than the one on
disk; restart it. A file copy does not change a running process.
