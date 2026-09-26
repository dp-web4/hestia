import { useCallback, useEffect, useState } from "react";
import { decideGateEscalation, getDashboard, operatorStatus, ruleScopeRequest } from "../lib/tauri";
import type { OperatorStatus, PendingEscalation, PendingScopeRequest } from "../lib/types";

/**
 * Decide — governance-surface escalations awaiting this operator.
 *
 * These arrive on every dashboard tick and were discarded before render until
 * now. Deciding here goes through `POST /api/operator/gate-escalation`, the
 * channel authenticated by a proved operator LCT, rather than the CLI path that
 * any member holding filesystem access to HESTIA_HOME can also drive.
 *
 * Two rules this view must not soften:
 *  - APPROVE needs a reason; DENY does not. Refusing is the default and costs
 *    nothing to explain. The form must not make denying feel like the act that
 *    needs defending.
 *  - When no operator is signed in the controls are ABSENT, not greyed. A
 *    disabled-looking button still says "this is yours to press"; it is not,
 *    because nothing here can be signed without the key.
 */

function age(secs: number): string {
  if (secs < 60) return `${secs}s`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m`;
  return `${Math.floor(secs / 3600)}h ${Math.floor((secs % 3600) / 60)}m`;
}

function EscalationCard({
  esc,
  signedIn,
  onDecided,
}: {
  esc: PendingEscalation;
  signedIn: boolean;
  onDecided: (id: string, result: string) => void;
}) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const decide = async (approve: boolean) => {
    setBusy(true);
    setErr(null);
    try {
      const out = await decideGateEscalation(esc.id, approve, reason || null);
      if (out.outcome === "already_decided") {
        // Another view of this same engine got there first — the dashboard on
        // this machine, the CLI, or a peer. The operator's click did not fail;
        // the question was already answered. Say that, and re-read the queue.
        onDecided(esc.id, "already decided elsewhere");
      } else {
        onDecided(esc.id, approve ? "approved" : "denied");
      }
    } catch (e) {
      // The app's own refusal (an approve with no reason) and the daemon's are
      // shown the same way: the operator needs the sentence, not its origin.
      setErr(String(e));
      setBusy(false);
    }
  };

  return (
    <article className="section" data-escalation={esc.id}>
      <header className="page-header">
        <h2>
          {esc.tool_name} <span className="muted">· {esc.marker}</span>
        </h2>
        <span className="muted">{age(esc.secs_remaining)} left</span>
      </header>

      <dl className="kv">
        <dt>asked by</dt>
        {/* Caller-asserted, not authenticated (HST-005). Say so where it is read. */}
        <dd>
          {esc.claimed_by} <span className="muted">(claimed, not proved)</span>
          {esc.role ? ` · ${esc.role}` : ""}
        </dd>
        <dt>stated reason</dt>
        <dd>{esc.stated_reason || <span className="muted">— none given —</span>}</dd>
        {esc.stated_detail && (
          <>
            <dt>detail</dt>
            {/* In full: truncating here is how a write gets approved on its summary. */}
            <dd className="pre">{esc.stated_detail}</dd>
          </>
        )}
        <dt>bar</dt>
        <dd>
          {esc.bar}
          {esc.operator_alone_suffices ? (
            <span className="muted"> · your approval is sufficient</span>
          ) : (
            <strong>
              {" "}
              · your approval is NECESSARY, NOT SUFFICIENT
              {esc.still_needs?.length ? ` — still needs ${esc.still_needs.join(", ")}` : ""}
            </strong>
          )}
        </dd>
      </dl>

      {err && <div className="error-banner">{err}</div>}

      {signedIn ? (
        <div className="decide-actions">
          <label>
            reason <span className="muted">(required to approve)</span>
            <input
              type="text"
              value={reason}
              maxLength={512}
              onChange={(e) => setReason(e.target.value)}
              placeholder="why permitting this is right"
            />
          </label>
          <button disabled={busy} onClick={() => decide(true)}>
            Approve
          </button>
          <button disabled={busy} onClick={() => decide(false)}>
            Deny
          </button>
        </div>
      ) : (
        <p className="muted">
          Sign in as the operator to decide. Deciding proves an operator key; without it this
          escalation is only readable here.
        </p>
      )}
    </article>
  );
}

/**
 * A scope request: a member ASKING for reach, not a refused act. Kept visually
 * distinct from an escalation because the two are opposite questions — "should
 * this act that was stopped go ahead?" versus "should this member be able to
 * reach this path at all?".
 *
 * The daemon's rules, not softened here: a GRANT needs a reason and a REFUSAL
 * does not ("refusing is the safe direction and must never carry more friction
 * than approving"). But the asker reads whatever the ruler writes — a being that
 * receives a bare "no" tends to appeal it — so the reason field is offered on
 * both sides and says who will read it. Invited, never required, on refusal.
 */
function ScopeRequestCard({
  req,
  signedIn,
  onDecided,
}: {
  req: PendingScopeRequest;
  signedIn: boolean;
  onDecided: (id: string, result: string) => void;
}) {
  const [reason, setReason] = useState("");
  const [recursive, setRecursive] = useState(false);
  const [standing, setStanding] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const rule = async (granted: boolean) => {
    setBusy(true);
    setErr(null);
    try {
      const out = await ruleScopeRequest(req.request_id, granted, reason || null, {
        // A standing refusal is not a thing; only a grant may be standing.
        standing: granted && standing,
        recursive,
      });
      if (out.outcome === "already_decided") {
        onDecided(req.request_id, "already ruled elsewhere");
      } else {
        onDecided(req.request_id, granted ? "granted" : "refused");
      }
    } catch (e) {
      setErr(String(e));
      setBusy(false);
    }
  };

  return (
    <article className="section scope-request" data-scope-request={req.request_id}>
      <header className="page-header">
        <h2>
          reach requested <span className="muted">· {req.path}</span>
        </h2>
        <span className="muted">{age(req.secs_remaining)} left</span>
      </header>

      <dl className="kv">
        <dt>asked by</dt>
        <dd>
          {req.claimed_by} <span className="muted">(claimed, not proved)</span>
          {req.role ? ` · ${req.role}` : ""}
        </dd>
        <dt>path</dt>
        {/* Exactly one path. The asker cannot request recursion; only the ruler can grant it. */}
        <dd className="pre">{req.path}</dd>
        <dt>their reason</dt>
        {/* Whole: truncating the asker's words is how a request gets ruled on its summary. */}
        <dd className="pre">{req.reason || <span className="muted">— none given —</span>}</dd>
      </dl>

      {err && <div className="error-banner">{err}</div>}

      {signedIn ? (
        <div className="decide-actions">
          <label>
            reason{" "}
            <span className="muted">
              (required to grant — and {req.claimed_by} reads whatever you write, refusals included)
            </span>
            <input
              type="text"
              value={reason}
              maxLength={512}
              onChange={(e) => setReason(e.target.value)}
              placeholder="what they should know about this ruling"
            />
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={recursive}
              onChange={(e) => setRecursive(e.target.checked)}
            />
            include everything below this path
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={standing}
              onChange={(e) => setStanding(e.target.checked)}
            />
            standing (grant only)
          </label>
          <button disabled={busy} onClick={() => rule(true)}>
            Grant
          </button>
          <button disabled={busy} onClick={() => rule(false)}>
            Refuse
          </button>
        </div>
      ) : (
        <p className="muted">
          Sign in as the operator to rule. Without the operator key this request is only readable
          here.
        </p>
      )}
    </article>
  );
}

export function Decide() {
  const [pending, setPending] = useState<PendingEscalation[] | null>(null);
  const [scopeReqs, setScopeReqs] = useState<PendingScopeRequest[] | null>(null);
  const [status, setStatus] = useState<OperatorStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [decided, setDecided] = useState<Record<string, string>>({});

  const refresh = useCallback(async () => {
    try {
      const [snap, st] = await Promise.all([getDashboard(), operatorStatus()]);
      // The daemon drops expired entries before sending, so anything here is
      // decidable right now.
      setPending(snap.pending_escalations ?? []);
      setScopeReqs(snap.pending_scope_requests ?? []);
      setStatus(st);
      setError(null);
    } catch (e) {
      // A failed look is reported as a failed look. Rendering an empty queue
      // here would say "nothing is waiting", which is the inversion this
      // surface exists to prevent.
      setError(String(e));
      setPending(null);
      setScopeReqs(null);
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 10_000);
    // The dashboard and the CLI act on the same engine, so this window can be
    // stale the moment it loses focus. Re-read on focus as well as on the tick:
    // a queue that offers a button for something already decided teaches the
    // operator that the button lies, and switching windows is exactly when that
    // happens.
    const onFocus = () => refresh();
    window.addEventListener("focus", onFocus);
    return () => {
      clearInterval(t);
      window.removeEventListener("focus", onFocus);
    };
  }, [refresh]);

  return (
    <div className="page">
      <header className="page-header">
        <h1>Decide</h1>
        {status?.signed_in ? (
          <span className="muted">operator {status.lct_id?.slice(0, 16)}…</span>
        ) : (
          <span className="muted">signed out</span>
        )}
      </header>

      <p className="muted">
        One engine, several views: this app, the daemon's own dashboard on this machine, and the
        CLI all act on the same queue. The daemon decides, and a decision is single-shot — if one
        is settled in another window it leaves here on the next read.
      </p>

      {error && <div className="error-banner">could not read the queue: {error}</div>}

      {pending === null && !error && <p className="muted">loading…</p>}

      {pending !== null &&
        scopeReqs !== null &&
        pending.length === 0 &&
        scopeReqs.length === 0 && <p className="muted">Nothing is waiting on you.</p>}

      {pending && pending.length > 0 && <h2 className="queue-heading">Stopped acts</h2>}
      {pending?.map((esc) => (
        <div key={esc.id}>
          {decided[esc.id] ? (
            <article className="section">
              <p>
                {esc.tool_name} — <strong>{decided[esc.id]}</strong>. It leaves this queue on the
                next tick.
              </p>
            </article>
          ) : (
            <EscalationCard
              esc={esc}
              signedIn={!!status?.signed_in}
              onDecided={(id, result) => {
                setDecided((d) => ({ ...d, [id]: result }));
                // Whatever happened, the engine is now the only thing that knows
                // the queue. Ask it rather than mutating a local copy.
                refresh();
              }}
            />
          )}
        </div>
      ))}

      {scopeReqs && scopeReqs.length > 0 && <h2 className="queue-heading">Reach requested</h2>}
      {scopeReqs?.map((req) => (
        <div key={req.request_id}>
          {decided[req.request_id] ? (
            <article className="section">
              <p>
                {req.path} — <strong>{decided[req.request_id]}</strong>. It leaves this queue on the
                next tick.
              </p>
            </article>
          ) : (
            <ScopeRequestCard
              req={req}
              signedIn={!!status?.signed_in}
              onDecided={(id, result) => {
                setDecided((d) => ({ ...d, [id]: result }));
                refresh();
              }}
            />
          )}
        </div>
      ))}
    </div>
  );
}
