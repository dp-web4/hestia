import { useCallback, useEffect, useState } from "react";
import {
  delegationGrant,
  delegationRevoke,
  delegationsList,
  getDashboard,
  operatorStatus,
} from "../lib/tauri";
import type { DelegationList, DelegationRow, OperatorStatus } from "../lib/types";

/**
 * Delegations — signed authority the operator delegates to ONE member (Sprint 4c).
 *
 * The rules this page must not soften:
 *  - The member is CHOSEN from the ones this seat has recorded; its delegation key is derived by
 *    the daemon, never typed or sent (#1067).
 *  - Roles come from the daemon's closed list. Actions are an open vocabulary: the daemon reads
 *    each the way the enforcer will, refuses one that binds nothing, and names the verbs it does
 *    not interpret — shown here in full, because "delegated" alone would read as "checked".
 *  - A delegation with no roles and no actions is full authority, and is refused.
 *  - A retired member's delegations stay READABLE, and nothing may be granted to it.
 *  - Signed out, the controls are absent.
 *  - Granting needs a reason. So does revoking — the daemon's current rule, which inverts the
 *    asymmetry kept everywhere else (narrowing should never cost more than widening); it is
 *    raised with the owner rather than worked around here.
 */

const EXPIRY: { label: string; hours: number | null }[] = [
  { label: "no expiry", hours: null },
  { label: "1 hour", hours: 1 },
  { label: "8 hours", hours: 8 },
  { label: "1 day", hours: 24 },
  { label: "7 days", hours: 168 },
];

const roleText = (r: unknown) => (typeof r === "string" ? r : JSON.stringify(r));

function status(d: DelegationRow): string {
  if (d.revoked) return "revoked";
  return d.active ? "active" : "expired";
}

function DelegationCard({
  d,
  member,
  signedIn,
  onActed,
}: {
  d: DelegationRow;
  member: string;
  signedIn: boolean;
  onActed: (msg: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const st = status(d);

  const revoke = async () => {
    setBusy(true);
    setErr(null);
    try {
      const out = await delegationRevoke(member, d.id, reason);
      onActed(
        out.outcome === "already_revoked"
          ? `${d.id.slice(0, 8)}…: already revoked elsewhere.`
          : `${d.id.slice(0, 8)}…: revoked.`,
      );
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={`delegation-card ${st}`} data-delegation={d.id}>
      <div className="delegation-header">
        <span className="delegation-id" title={d.id}>
          {d.id.slice(0, 8)}…
        </span>
        <span className={`badge ${st === "active" ? "badge-success" : "badge-danger"}`}>{st}</span>
      </div>
      <div className="delegation-body">
        <div className="delegation-field">
          <span className="field-label">Roles</span>
          <span>{d.scope.roles.length ? d.scope.roles.map(roleText).join(", ") : "—"}</span>
        </div>
        <div className="delegation-field">
          <span className="field-label">Actions</span>
          <span className="pre">{d.scope.actions.length ? d.scope.actions.join(", ") : "—"}</span>
        </div>
        <div className="delegation-field">
          <span className="field-label">Granted</span>
          <span>{new Date(d.created_at).toLocaleString()}</span>
        </div>
        <div className="delegation-field">
          <span className="field-label">Expires</span>
          <span>{d.expires_at ? new Date(d.expires_at).toLocaleString() : "never"}</span>
        </div>
      </div>
      {signedIn && st === "active" && !open && <button onClick={() => setOpen(true)}>Revoke…</button>}
      {signedIn && open && (
        <div className="decide-actions">
          <label>
            reason <span className="muted">(the daemon requires one to revoke)</span>
            <input type="text" value={reason} maxLength={512} onChange={(e) => setReason(e.target.value)} />
          </label>
          <button disabled={busy} onClick={revoke}>
            Revoke
          </button>
          <button disabled={busy} onClick={() => setOpen(false)}>
            Cancel
          </button>
        </div>
      )}
      {err && <div className="error-banner">{err}</div>}
    </div>
  );
}

function GrantForm({
  member,
  roles,
  onActed,
}: {
  member: string;
  roles: string[];
  onActed: (msg: string) => void;
}) {
  const [picked, setPicked] = useState<string[]>([]);
  const [actions, setActions] = useState("");
  const [expiry, setExpiry] = useState(0);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const toggle = (r: string) =>
    setPicked((p) => (p.includes(r) ? p.filter((x) => x !== r) : [...p, r]));

  const grant = async () => {
    setNotice(null);
    const acts = actions
      .split("\n")
      .map((a) => a.trim())
      .filter(Boolean);
    if (!picked.length && !acts.length)
      return setNotice("Name what is delegated: with no roles and no actions it would be full authority.");
    if (!reason.trim()) return setNotice("Delegating authority requires a reason.");
    setBusy(true);
    try {
      const out = await delegationGrant(member, picked, acts, EXPIRY[expiry].hours, reason.trim());
      const unv = out.unvalidated_actions ?? [];
      setPicked([]);
      setActions("");
      setReason("");
      onActed(
        unv.length
          ? `Delegated to ${member} — but NOT validated: ${unv.join(", ")} ${unv.length === 1 ? "is not a verb" : "are not verbs"} this daemon interprets, so ${unv.length === 1 ? "it was" : "they were"} stored as given and checked for nothing.`
          : `Delegated to ${member}.`,
      );
    } catch (e) {
      setNotice(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="section">
      <h2>Delegate to {member}</h2>
      <div className="decide-actions">
        <fieldset>
          <legend>roles</legend>
          {roles.map((r) => (
            <label key={r} className="check">
              <input type="checkbox" checked={picked.includes(r)} onChange={() => toggle(r)} />
              {r}
            </label>
          ))}
        </fieldset>
        <label>
          actions <span className="muted">(one per line, e.g. scope.decide:{member}:/path)</span>
          <textarea value={actions} rows={3} onChange={(e) => setActions(e.target.value)} />
        </label>
        <label>
          expires
          <select value={expiry} onChange={(e) => setExpiry(Number(e.target.value))}>
            {EXPIRY.map((x, i) => (
              <option key={x.label} value={i}>
                {x.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          reason <span className="muted">(required)</span>
          <input
            type="text"
            value={reason}
            maxLength={512}
            onChange={(e) => setReason(e.target.value)}
            placeholder="why this member needs this authority"
          />
        </label>
      </div>
      {notice && <div className="error-banner">{notice}</div>}
      <button disabled={busy} onClick={grant}>
        Delegate
      </button>
    </section>
  );
}

export function Delegations() {
  const [members, setMembers] = useState<string[]>([]);
  const [member, setMember] = useState("");
  const [list, setList] = useState<DelegationList | null>(null);
  const [status, setStatus] = useState<OperatorStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const loadMembers = useCallback(async () => {
    try {
      const [snap, st] = await Promise.all([getDashboard(), operatorStatus()]);
      setMembers([...(snap.members ?? [])].sort());
      setStatus(st);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  const loadList = useCallback(async (m: string) => {
    if (!m) {
      setList(null);
      return;
    }
    try {
      setList(await delegationsList(m));
      setError(null);
    } catch (e) {
      // A failed look is a failed look: an empty list would read as "nothing delegated".
      setError(String(e));
      setList(null);
    }
  }, []);

  useEffect(() => {
    loadMembers();
  }, [loadMembers]);

  const signedIn = !!status?.signed_in;

  useEffect(() => {
    // Every /api/* read is operator-gated: signed out there is nothing to look at, which is
    // said below rather than rendered as an error or an empty list.
    if (!signedIn) return;
    loadList(member);
    const onFocus = () => loadList(member);
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [member, loadList, signedIn]);
  const acted = (msg: string) => {
    setNotice(msg);
    loadList(member);
  };

  return (
    <div className="page">
      <header className="page-header">
        <h1>Delegations</h1>
      </header>
      <p className="muted">
        Authority you delegate to one member, signed with your operator key. Pick the member; its
        delegation key is derived from the registry, never typed.
      </p>

      <label>
        member
        <select value={member} onChange={(e) => setMember(e.target.value)}>
          <option value="">— choose —</option>
          {members.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </label>

      {error && <div className="error-banner">could not read delegations: {error}</div>}
      {notice && <p data-notice>{notice}</p>}

      {list && (
        <>
          {list.retired && (
            <div className="error-banner">
              {list.plugin_id} is retired on this seat. Its delegations were revoked at retirement and
              stay listed as history; nothing can be delegated to it until it is reinstated.
            </div>
          )}
          {list.delegations.length === 0 ? (
            <p className="muted">Nothing has been delegated to {list.plugin_id}.</p>
          ) : (
            <div className="delegation-list">
              {list.delegations.map((d) => (
                <DelegationCard key={d.id} d={d} member={list.plugin_id} signedIn={signedIn} onActed={acted} />
              ))}
            </div>
          )}
          {signedIn && !list.retired && (
            <GrantForm member={list.plugin_id} roles={list.roles} onActed={acted} />
          )}
        </>
      )}
      {!signedIn && status && (
        <p className="muted">
          Sign in as the operator to read or change delegations. Signed out there is nothing to show —
          which is not the same as nothing being delegated.
        </p>
      )}
    </div>
  );
}
