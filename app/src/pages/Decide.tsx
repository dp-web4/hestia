import { useCallback, useEffect, useState } from "react";
import { decideGateEscalation, getDashboard, operatorStatus } from "../lib/tauri";
import type { OperatorStatus, PendingEscalation } from "../lib/types";

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
      onDecided(esc.id, approve ? "approved" : "denied");
      void out;
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

export function Decide() {
  const [pending, setPending] = useState<PendingEscalation[] | null>(null);
  const [status, setStatus] = useState<OperatorStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [decided, setDecided] = useState<Record<string, string>>({});

  const refresh = useCallback(async () => {
    try {
      const [snap, st] = await Promise.all([getDashboard(), operatorStatus()]);
      // The daemon drops expired entries before sending, so anything here is
      // decidable right now.
      setPending(snap.pending_escalations ?? []);
      setStatus(st);
      setError(null);
    } catch (e) {
      // A failed look is reported as a failed look. Rendering an empty queue
      // here would say "nothing is waiting", which is the inversion this
      // surface exists to prevent.
      setError(String(e));
      setPending(null);
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 10_000);
    return () => clearInterval(t);
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

      {error && <div className="error-banner">could not read the queue: {error}</div>}

      {pending === null && !error && <p className="muted">loading…</p>}

      {pending !== null && pending.length === 0 && (
        <p className="muted">Nothing is waiting on you.</p>
      )}

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
              onDecided={(id, result) => setDecided((d) => ({ ...d, [id]: result }))}
            />
          )}
        </div>
      ))}
    </div>
  );
}
