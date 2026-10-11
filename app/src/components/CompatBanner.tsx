import { useCallback, useEffect, useState } from "react";
import { getDaemonStatus } from "../lib/tauri";
import type { Handshake } from "../lib/types";
import { blocksRoutes, compatTitle, sideLabel } from "../lib/compat";

/**
 * App-wide statement of what is on the other end of the daemon URL (web4#904).
 *
 * The Rust shell refuses every operator route to a daemon that does not speak this app's API,
 * with one sentence. Pages still show that sentence as their own error; this banner says it
 * once, above every page, with both sides' versions, so the operator reads "this daemon is a
 * different release" rather than a dozen unrelated-looking route failures.
 */
export function CompatBanner({ pollMs = 10000 }: { pollMs?: number }) {
  const [handshake, setHandshake] = useState<Handshake | null>(null);

  const refresh = useCallback(async () => {
    try {
      setHandshake((await getDaemonStatus()).handshake ?? null);
    } catch {
      setHandshake(null);
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, pollMs);
    const onChange = () => refresh();
    window.addEventListener("hestia:auth", onChange);
    window.addEventListener("hestia:daemon-url", onChange);
    return () => {
      clearInterval(interval);
      window.removeEventListener("hestia:auth", onChange);
      window.removeEventListener("hestia:daemon-url", onChange);
    };
  }, [refresh, pollMs]);

  if (!handshake) return null;
  if (blocksRoutes(handshake)) {
    return (
      <div className="compat-banner compat-blocking" role="alert" data-compat={handshake.state}>
        <strong>{compatTitle(handshake)}</strong>
        <span>{handshake.message}</span>
        <span className="compat-sides">
          daemon: {sideLabel(handshake.daemon_version, handshake.daemon_api_compat)}
          {handshake.daemon_build_id ? ` (build ${handshake.daemon_build_id})` : ""} — app:{" "}
          {sideLabel(handshake.app_version, handshake.app_api_compat)}
        </span>
      </div>
    );
  }
  if (handshake.state === "skew") {
    return (
      <div className="compat-banner compat-skew" role="status" data-compat="skew">
        <strong>{compatTitle(handshake)}</strong>
        <span>{handshake.message}</span>
      </div>
    );
  }
  return null;
}
