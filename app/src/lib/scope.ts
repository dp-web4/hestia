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
  req: Pick<PendingScopeRequest, "origin" | "invited_peers"> & { decided_by_default?: string },
): boolean {
  // dp, 2026-10-13: "escalate to me after a timeout" -- the daemon turns `decided_by_default`
  // to "operator" once the peer window lapses; an older daemon falls back to the routing rule.
  if (typeof req.decided_by_default === "string") return req.decided_by_default !== "peer";
  return !(req.origin === "gate_deny" && (req.invited_peers?.length ?? 0) > 0);
}

export type ScopeDecision = ScopeDuration | "refuse";

type DecisionInputs = Pick<PendingScopeRequest, "once_available" | "once_only" | "allowed_decisions">;

/**
 * #1287 part 2: the rulings the daemon's decide endpoint ACCEPTS for this request, as the
 * daemon reports them (`allowed_decisions`, from the same function its refusal reads). An older
 * daemon without the field falls back to the flags it did send: "this act once" only when the
 * gate recorded an act to bind; no session or standing for an act the gate could not enumerate
 * (`once_only`, dp 2026-10-10).
 */
export function scopeAllowedDecisions(req: DecisionInputs): ScopeDecision[] {
  if (Array.isArray(req.allowed_decisions)) return req.allowed_decisions;
  const out: ScopeDecision[] = [];
  if (req.once_available === true) out.push("once");
  if (req.once_only !== true) out.push("session", "standing");
  out.push("refuse");
  return out;
}

/** The grant durations the card may offer: exactly the accepted ones. */
export function scopeDurations(req: DecisionInputs): ScopeDuration[] {
  const a = scopeAllowedDecisions(req);
  return (["once", "session", "standing"] as const).filter((d) => a.includes(d));
}

/**
 * No session and no standing ruling: what the act reaches is decided by an expansion, so the
 * only grant is this exact act. The card renders exactly "Approve once" and "Refuse".
 */
export function scopeOnceOnly(req: DecisionInputs): boolean {
  const a = scopeAllowedDecisions(req);
  return !a.includes("session") && !a.includes("standing");
}

/** Whether the request names a path at all (false for an act the gate could not enumerate). */
export function scopeEnumerable(
  req: Pick<PendingScopeRequest, "enumerable" | "once_only">,
): boolean {
  return typeof req.enumerable === "boolean" ? req.enumerable : req.once_only !== true;
}

export const SCOPE_ONCE_ONLY_WHY =
  "what this act reaches is decided by an expansion, so only this exact act can be approved";

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
