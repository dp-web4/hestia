import type { Handshake } from "./types";

/** The lockstep release this app was built as (from package.json, which VERSION drives). */
export const APP_VERSION: string = __APP_VERSION__;

/**
 * Does this handshake stop the app from using operator routes? Mirrors
 * `CompatState::usable` in app/src-tauri/src/handshake.rs: only `compatible` and `skew`
 * may proceed; `unreachable` is the offline state, which the existing screens own.
 */
export function blocksRoutes(h: Handshake | null | undefined): boolean {
  return !!h && (h.state === "incompatible" || h.state === "no_version_endpoint" || h.state === "malformed");
}

/** A heading for the state, for screens that name it before the shell's sentence. */
export function compatTitle(h: Handshake): string {
  switch (h.state) {
    case "incompatible":
      return "Incompatible daemon";
    case "no_version_endpoint":
      return "Incompatible daemon (no version endpoint)";
    case "malformed":
      return "Daemon compatibility unknown";
    case "skew":
      return "Version skew";
    case "unreachable":
      return "Daemon unreachable";
    default:
      return "Compatible daemon";
  }
}

/** "hestia 0.3.0 · API v1" for either side; unknown parts are said, not guessed. */
export function sideLabel(version: string | null, compat: number | null): string {
  return `hestia ${version ?? "unknown"} · API ${compat === null ? "unknown" : `v${compat}`}`;
}
