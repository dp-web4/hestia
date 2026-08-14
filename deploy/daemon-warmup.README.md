# daemon-warmup — ExecStartPost, pays the cold first-connect at restart

Issue #423: the DeltaClass-era daemon pays ~5.7s on FIRST connect PER PLUGIN (1ms warm).
Any member gate call landing in that window inside its budget reads "daemon unreachable"
-> ratified degraded mode: a restart became a fleet-visible brownout.

This script runs as ExecStartPost (drop-in below): it waits for the MCP endpoint, then
connects once AS EACH registered member (labeled systemd-warmup — honest witness grain),
so systemd pays every cold path before "Started". Measured acceptance 2026-08-13: first
codex-path mechanism run immediately post-restart = 0.03s snapshot + instant verdict.

Install (operator):

    install -m 0755 deploy/daemon-warmup.sh ~/.hestia/daemon-warmup.sh
    mkdir -p ~/.config/systemd/user/hestia.service.d
    printf '[Service]\nExecStartPost=-%%h/.hestia/daemon-warmup.sh\n' \
      > ~/.config/systemd/user/hestia.service.d/warmup.conf
    systemctl --user daemon-reload && systemctl --user restart hestia

Clamp facts verified from config (Class T discipline — measure, never remember):
codex gate hook timeout = **15s** (config.toml; the "3s clamp" was folklore, wrong 5x).
Budget ladder: 15s clamp > 2.5s mechanism budget > ~30ms steady-state legs.
The rust-side fix (move the page-in to daemon startup proper) remains #423.
