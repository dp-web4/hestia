# Hestia App — Cross-Platform Build Plan

**Date**: 2026-05-23
**Author**: Legion (Opus 4.7)
**Status**: Built. Desktop (Linux .deb/.rpm/AppImage) + Android (APK/AAB) complete.
**Binary size**: 17MB desktop, 18MB APK, 8.2MB AAB
**Build time**: ~55s desktop (Rust release), ~90s Android (cross-compile + Gradle)

## What we're building

A single Tauri 2.x application that runs on desktop (Linux, macOS, Windows) and
mobile (iOS, Android). Two modes from one binary:

- **Sovereign mode** (full node): local vault, local witness chain, local policy
  engine, local MCP server. The daemon as it exists today, wrapped in an app shell.
- **Mirror mode** (thin client): connects to one or more remote Hestia daemons,
  displays their state, relays policy decisions. No local vault or chain.

Mode is a runtime config toggle (`mode: sovereign | mirror`), not a build-time
split. A sovereign node can also mirror remote peers — these compose, not exclude.

## Why one app, not two

1. Federation (Phase 4) requires every node to be both — sovereign for its own
   actions, mirror for peers. Building them separately means rewriting for
   federation.
2. The thin client IS the full node minus `vault/` + `storage/` init. The UI,
   IPC bridge, and data model are identical — they just point at different
   data sources (local SQLite vs. remote HTTP).
3. Mirror mode is just a feature flag on the sovereign app: `--remote
   <host:port>` adds a remote data source alongside (or instead of) local.

## Architecture

```
hestia-app/
├── src-tauri/                    # Rust backend (Tauri + hestia core)
│   ├── src/
│   │   ├── main.rs               # Tauri entry, setup, system tray
│   │   ├── commands/             # Tauri IPC commands
│   │   │   ├── mod.rs
│   │   │   ├── dashboard.rs      # get_dashboard, get_failures
│   │   │   ├── vault.rs          # vault_list, vault_get, vault_set, vault_delete
│   │   │   ├── policy.rs         # get_policy, set_preset, add_rule
│   │   │   ├── chain.rs          # query_chain, chain_stats
│   │   │   ├── settings.rs       # get_config, set_mode, add_remote
│   │   │   └── remote.rs         # list_remotes, remote_dashboard, remote_status
│   │   ├── bridge.rs             # Wraps hestia core lib for Tauri context
│   │   └── remote.rs             # HTTP client to remote Hestia daemons
│   ├── Cargo.toml                # depends on hestia = { path = "../core" }
│   ├── tauri.conf.json
│   ├── capabilities/
│   │   └── default.json          # Tauri 2 capability permissions
│   └── icons/                    # App icons (flame)
├── src/                          # React + TypeScript frontend
│   ├── main.tsx                  # Entry point
│   ├── App.tsx                   # Router + layout
│   ├── pages/
│   │   ├── Dashboard.tsx         # Society overview, trust cards, chain feed
│   │   ├── Vault.tsx             # Credential management
│   │   ├── Policy.tsx            # Policy preset + rule editor
│   │   ├── Chain.tsx             # Witness chain explorer
│   │   ├── Fleet.tsx             # Remote daemon grid (mirror mode)
│   │   └── Settings.tsx          # Mode toggle, remote config, daemon status
│   ├── components/
│   │   ├── TrustCard.tsx         # Per-plugin trust tensor display
│   │   ├── ChainEntry.tsx        # Single witness chain row
│   │   ├── ChainFeed.tsx         # Live-scrolling chain entries
│   │   ├── TensorBar.tsx         # T3/V3 bar visualization
│   │   ├── ToolHistogram.tsx     # Tool usage chart
│   │   ├── StatusBadge.tsx       # Online/offline/degraded indicator
│   │   ├── PolicyRuleRow.tsx     # Single policy rule editor row
│   │   └── RemoteCard.tsx        # Remote daemon status card
│   ├── hooks/
│   │   ├── useHestia.ts          # Tauri invoke wrapper
│   │   ├── useDashboard.ts       # Polling dashboard data
│   │   └── useRemotes.ts         # Remote daemon state
│   ├── lib/
│   │   ├── types.ts              # TypeScript types mirroring Rust structs
│   │   └── tauri.ts              # Typed invoke bindings
│   └── styles/
│       └── global.css            # Hearth-fire palette, responsive layout
├── package.json
├── tsconfig.json
├── vite.config.ts
└── index.html
```

## Data flow

### Sovereign mode
```
React UI ─── Tauri IPC ───► Rust commands ───► hestia core lib
                                                  │
                                          ┌───────┼────────┐
                                          │       │        │
                                        Vault  Chain   TrustStore
                                     (~/.hestia/)
```

### Mirror mode
```
React UI ─── Tauri IPC ───► Rust commands ───► HTTP client
                                                  │
                                          GET /api/dashboard
                                          GET /api/failures
                                                  │
                                          Remote Hestia daemon
                                          (fleet machine:7711)
```

### Sovereign + Mirror (federation-ready)
```
React UI ─── Tauri IPC ───► Rust commands ─┬─► local hestia core
                                            └─► remote HTTP clients (N)
```

## Mobile considerations

- **Tauri 2.x mobile** uses WKWebView (iOS) and Android WebView. Same React
  frontend, responsive CSS.
- **Vault key storage**: iOS Keychain / Android Keystore for the vault master
  key (replaces passphrase prompt on desktop). Tauri 2 plugin `tauri-plugin-biometric`.
- **Background sync**: mirror mode polls on configurable interval (default 30s).
  iOS background app refresh or Android WorkManager for persistent monitoring.
- **Push notifications**: for policy decisions requiring user approval (Phase 2+).
  Initially: pull-based polling.
- **No local MCP server on mobile**: agents don't run on phones. Mobile is
  always sovereign-for-vault + mirror-for-fleet. MCP server module excluded
  from mobile builds via `#[cfg(not(target_os = "ios/android"))]`.

## What stays unchanged

- The hestia core daemon binary (`hestia serve`) continues to work standalone.
  The app is an additional surface, not a replacement.
- Plugin SDKs unchanged — they connect to the MCP server, which runs whether
  invoked from the app or CLI.
- Existing Claude Code hooks unchanged — they talk to localhost:7711 regardless
  of whether the daemon was started by the app or systemd.
- The embedded HTML dashboard at `/` stays — it's the zero-install fallback.

---

# Sprint Plan

## Sprint 1: Tauri scaffold + dashboard mirror
**Goal**: App launches, shows live dashboard data from local daemon.
**Estimate**: ~1 hour

- [ ] `npm create tauri-app` with React + TypeScript + Vite
- [ ] Wire `hestia` core as path dependency in `src-tauri/Cargo.toml`
- [ ] IPC command: `get_dashboard()` → calls local `/api/dashboard` or uses
      core lib directly
- [ ] Dashboard page: society stats, trust cards, chain feed, tool histogram
- [ ] Hearth-fire CSS theme (the palette from current HTML dashboard)
- [ ] System tray icon (flame) with show/hide toggle
- [ ] Build and run on Linux (this machine)

**Deliverable**: Desktop app showing same data as `http://127.0.0.1:7711/`

## Sprint 2: Vault + Policy UI
**Goal**: Full credential management and policy configuration through the app.
**Estimate**: ~1 hour

- [ ] Vault page: list credentials (name, scope, tags, last rotated — never
      show secret values in list)
- [ ] Vault add/edit modal: name, secret, scope tags, allowed consumers
- [ ] Vault delete with confirmation
- [ ] IPC commands: `vault_list`, `vault_get`, `vault_set`, `vault_delete`,
      `vault_rotate`
- [ ] Policy page: preset selector (permissive/safety/strict/audit-only)
- [ ] Policy rule list with add/edit/delete
- [ ] IPC commands: `get_policy`, `set_preset`, `add_rule`, `remove_rule`

**Deliverable**: Full vault + policy management without CLI

## Sprint 3: Witness chain explorer + settings
**Goal**: Searchable chain history, daemon configuration.
**Estimate**: ~45 min

- [ ] Chain page: paginated chain entries with search/filter
- [ ] Filter by: event_type, tool_name, success/fail, date range
- [ ] Chain entry detail view (full event_data JSON)
- [ ] Chain integrity indicator (hash verification status)
- [ ] Settings page: mode toggle (sovereign/mirror), bind address, data dir
- [ ] Daemon status panel: uptime, chain length, connected plugins, memory

**Deliverable**: Complete sovereign-mode app

## Sprint 4: Mirror mode + fleet view
**Goal**: Connect to remote Hestia daemons, display fleet state.
**Estimate**: ~1 hour

- [ ] Remote daemon configuration: add/remove/edit remotes (host:port + optional auth token)
- [ ] HTTP client in Rust backend: poll remote `/api/dashboard` on interval
- [ ] Fleet page: grid of remote daemon cards (status, chain length, trust summary)
- [ ] Click-through from fleet card to full remote dashboard view
- [ ] Mode toggle: sovereign-only / mirror-only / sovereign+mirror
- [ ] Connection health: online/offline/degraded per remote, auto-reconnect
- [ ] IPC commands: `add_remote`, `remove_remote`, `list_remotes`,
      `get_remote_dashboard`

**Deliverable**: Phone or second computer can monitor the fleet

## Sprint 5: Mobile targets
**Goal**: iOS and Android builds.
**Estimate**: ~1.5 hours

- [ ] Tauri 2 mobile init (`cargo tauri android init`, `cargo tauri ios init`)
- [ ] Responsive CSS: dashboard, vault, fleet pages adapt to narrow screens
- [ ] Touch-friendly: larger tap targets, swipe gestures for chain feed
- [ ] Conditional compilation: exclude MCP server on mobile
      (`#[cfg(not(any(target_os = "android", target_os = "ios")))]`)
- [ ] Vault master key: iOS Keychain / Android Keystore integration
      (fallback to passphrase if unavailable)
- [ ] Build APK (Android) and test on device/emulator
- [ ] Build IPA (iOS) if Xcode available, otherwise defer to CBP (macOS)

**Deliverable**: Mobile app running on at least Android

## Sprint 6: Polish + packaging
**Goal**: Production-ready packaging for all platforms.
**Estimate**: ~1 hour

- [ ] App icon set (flame, all required sizes)
- [ ] Splash screen (mobile)
- [ ] Linux: AppImage + .deb packaging
- [ ] Windows: MSI installer (can be cross-compiled or deferred to CBP)
- [ ] macOS: .dmg + notarization (deferred to CBP if needed)
- [ ] Android: signed APK/AAB
- [ ] iOS: TestFlight submission (requires Apple dev account)
- [ ] Update ARCHITECTURE.md with app build instructions
- [ ] Update README.md with app screenshots

**Deliverable**: Distributable packages for all platforms

---

## Post-build: what this enables

- **dp's phone** becomes a fleet dashboard — witness chains, trust state,
  policy decisions, all without SSH
- **Any machine** in the fleet can run sovereign + mirror, seeing peers
- **Federation** (Phase 4) is just mirror-mode with mutual trust negotiation
  instead of manual remote config
- **Enterprise** (Phase 4) is sovereign-mode on employee machines +
  admin-mirror for the security team
