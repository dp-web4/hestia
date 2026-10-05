/**
 * Ruling a scope request: the DURATION and BREADTH choices (spec decide-scope-request,
 * 2026-10-05 — a scope refusal is an escalation with a standing option). Pure, so the option
 * sets are tested as values, and the same sets the dashboard offers.
 */
import type { PendingScopeRequest } from "./types";

export type ScopeDuration = "once" | "session" | "standing";

/**
 * dp, 2026-10-05: "scope escalations should go to peers not to me". A gate-opened request with
 * invited peers awaits a NOT-SAME peer; only a request no peer can clear awaits the operator.
 */
export function scopeAwaitsOperator(
  req: Pick<PendingScopeRequest, "origin" | "invited_peers">,
): boolean {
  return !(req.origin === "gate_deny" && (req.invited_peers?.length ?? 0) > 0);
}

/** "This act once" is a choice only when the gate recorded an act to bind. */
export function scopeDurations(req: Pick<PendingScopeRequest, "once_available">): ScopeDuration[] {
  return req.once_available === true ? ["once", "session", "standing"] : ["session", "standing"];
}

export const DURATION_LABEL: Record<ScopeDuration, string> = {
  once: "this act once (spent by the identical act, inside the claim window)",
  session: "for the session (memory-only, expires)",
  standing: "standing (vault; survives restart until revoked)",
};

/** One breadth the operator may grant at: the path the grant will reach from, and how. */
export interface ScopeBreadth {
  grantPath: string | null;
  recursive: boolean;
  label: string;
}

/**
 * Exactly the asked path (not for a glob reach), the path and everything below it, and every
 * directory ABOVE it, recursive — never the root.
 */
export function scopeBreadthOptions(path: string, subtree: boolean): ScopeBreadth[] {
  const p = String(path || "").replace(/\/+$/, "");
  if (!p.startsWith("/")) return [];
  const out: ScopeBreadth[] = [];
  if (!subtree) out.push({ grantPath: null, recursive: false, label: `exactly ${p}` });
  out.push({ grantPath: null, recursive: true, label: `${p}/** (this path and everything below)` });
  const parts = p.split("/").filter(Boolean);
  for (let i = parts.length - 1; i >= 1; i--) {
    const anc = "/" + parts.slice(0, i).join("/");
    out.push({ grantPath: anc, recursive: true, label: `${anc}/** (directory above, recursive)` });
  }
  return out;
}

/** The options `ruleScopeRequest` sends. A refusal carries no duration and no breadth. */
export function scopeRulingOpts(
  req: Pick<PendingScopeRequest, "path">,
  granted: boolean,
  duration: ScopeDuration,
  breadth: ScopeBreadth | undefined,
) {
  if (!granted) return { standing: false, recursive: false, askedPath: req.path };
  if (duration === "once") return { once: true, askedPath: req.path };
  return {
    standing: duration === "standing",
    recursive: !!breadth?.recursive,
    grantPath: breadth?.grantPath ?? null,
    askedPath: req.path,
  };
}
