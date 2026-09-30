import { useCallback, useEffect, useMemo, useState } from "react";
import { getDashboard, grantReach, operatorStatus, revokeReach } from "../lib/tauri";
import type { DashboardSnapshot, OperatorStatus, ScopeGrantRow } from "../lib/types";

/**
 * Reach — what each member can touch, and the operator's own grant and revoke (Sprint 4a).
 *
 * The rules this page must not soften:
 *  - Every row says its LIFETIME. A live grant dies at the next daemon restart; a standing one
 *    does not. One list, with the distinction on the face of each row.
 *  - GRANTING needs a reason; REVOKING does not. Narrowing never costs more than widening.
 *  - Members are CHOSEN from the ones this seat has recorded, never typed (#1067), and a retired
 *    id is not offered.
 *  - LAST EDIT WINS (ruled 2026-09-25): a grant on a (member, path) that already has a standing
 *    grant replaces it. The form shows that row before you write, and the write is bound to it —
 *    if another view changed it since, nothing is sent and the new row is shown instead.
 *  - Signed out, the controls are absent.
 *
 * Out of this sprint: promote-to-standing, reassign and delegations (4b / 4c), and the society
 * floor, which the spec keeps off every UI for now.
 */

const short = (n?: number | null) => {
  if (n == null) return "";
  if (n < 3600) return `${Math.max(1, Math.floor(n / 60))}m`;
  if (n < 86400) return `${Math.floor(n / 3600)}h`;
  return `${Math.floor(n / 86400)}d`;
};

const EXPIRY: { label: string; secs: number | null }[] = [
  { label: "no expiry", secs: null },
  { label: "1 hour", secs: 3600 },
  { label: "8 hours", secs: 8 * 3600 },
  { label: "1 day", secs: 86400 },
  { label: "7 days", secs: 7 * 86400 },
];

function normalize(path: string): string {
  // The daemon's normalize_scope_path, so "this replaces" looks up the key the store holds.
  const p = path.trim();
  const out: string[] = [];
  for (const seg of p.split("/")) {
    if (seg === "" || seg === ".") continue;
    if (seg === "..") out.pop();
    else out.push(seg);
  }
  return (p.startsWith("/") ? "/" : "") + out.join("/");
}

/** PURE: the standing row a grant on (member, path) would replace, or null. */
export function replacedBy(
  grants: ScopeGrantRow[],
  member: string,
  path: string,
): ScopeGrantRow | null {
  const key = normalize(path);
  return (
    grants.find((g) => g.lifetime === "standing" && g.plugin_id === member && g.path === key) ??
    null
  );
}

function GrantRow({
  g,
  signedIn,
  onActed,
}: {
  g: ScopeGrantRow;
  signedIn: boolean;
  onActed: (msg: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const revoke = async () => {
    setBusy(true);
    setErr(null);
    try {
      const out = await revokeReach(g, reason.trim() || null);
      if (out.outcome === "already_revoked") {
        onActed(`${g.plugin_id} · ${g.path}: already gone — ${out.detail}`);
      } else if (out.outcome === "revoked") {
        const still = (out.result as { standing_grant_still_covers_path?: boolean })
          .standing_grant_still_covers_path;
        onActed(
          still
            ? `${g.plugin_id} · ${g.path}: live grant revoked, but a STANDING grant still covers this path.`
            : `${g.plugin_id} · ${g.path}: revoked.`,
        );
      }
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <tr data-grant={`${g.lifetime}:${g.plugin_id}:${g.path}`}>
      <td className="pre">{g.path}</td>
      <td>
        <span className={g.lifetime === "live" ? "gate-differs" : ""}>{g.lifetime}</span>
        {g.lifetime === "live" ? (
          <div className="muted">dies at the next restart · {short(g.secs_remaining)} left</div>
        ) : g.expires_at ? (
          <div className="muted">until {new Date(g.expires_at * 1000).toLocaleString()}</div>
        ) : null}
      </td>
      <td>{g.recursive ? "this path and everything below" : "exactly this path"}</td>
      <td>
        {g.reason || <span className="muted">— none recorded —</span>}
        <div className="muted">
          {g.origin === "member_request" || g.request_id ? "answered the member's ask" : "operator-originated"}
          {g.granted_by ? ` · by ${g.granted_by}` : ""}
        </div>
      </td>
      <td>
        {signedIn &&
          (open ? (
            <div className="decide-actions">
              <label>
                reason <span className="muted">(optional — revoking needs none)</span>
                <input
                  type="text"
                  value={reason}
                  maxLength={512}
                  onChange={(e) => setReason(e.target.value)}
                />
              </label>
              <button disabled={busy} onClick={revoke}>
                Revoke
              </button>
            </div>
          ) : (
            <button onClick={() => setOpen(true)}>Revoke…</button>
          ))}
        {err && <div className="error-banner">{err}</div>}
      </td>
    </tr>
  );
}

function GrantForm({
  members,
  grants,
  onActed,
}: {
  members: string[];
  grants: ScopeGrantRow[];
  onActed: (msg: string) => void;
}) {
  const [member, setMember] = useState("");
  const [path, setPath] = useState("");
  const [recursive, setRecursive] = useState(false);
  const [expiry, setExpiry] = useState(0);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  // What this write would replace, from the last read — the value the operator is shown and
  // the value the write is bound to.
  const replaces = member && path.trim() ? replacedBy(grants, member, path) : null;

  const grant = async () => {
    setNotice(null);
    if (!member) return setNotice("Choose the member to grant to.");
    if (!path.trim().startsWith("/")) return setNotice("The path must be absolute.");
    if (!reason.trim())
      return setNotice(
        "Granting reach requires a reason: an operator grant answers no member's ask, so the reason is the only account of why the reach exists.",
      );
    setBusy(true);
    try {
      const out = await grantReach(member, path, reason.trim(), {
        recursive,
        expiresInSecs: EXPIRY[expiry].secs,
        seen: replaces,
      });
      if (out.outcome === "moved") {
        setNotice(
          out.current
            ? `The standing grant on this path changed since you looked — it now reads "${out.current.reason ?? ""}". Nothing was granted; review it above and resubmit.`
            : "The standing grant you were about to replace was removed elsewhere since you looked. Nothing was granted; resubmit if you still want this.",
        );
        onActed("");
      } else if (out.outcome === "granted") {
        setReason("");
        onActed(
          out.replaced
            ? `Granted ${member} · ${normalize(path)} — replaced the standing grant whose reason was "${out.replaced.reason ?? ""}".`
            : `Granted ${member} · ${normalize(path)} (standing).`,
        );
      }
    } catch (e) {
      setNotice(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="section">
      <h2>Grant reach</h2>
      <p className="muted">
        A standing grant: it survives restarts until revoked or expired. Exact unless you choose
        the subtree.
      </p>
      <div className="decide-actions">
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
        <label>
          path
          <input type="text" value={path} onChange={(e) => setPath(e.target.value)} placeholder="/absolute/path" />
        </label>
        <label className="check">
          <input type="checkbox" checked={recursive} onChange={(e) => setRecursive(e.target.checked)} />
          include everything below this path
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
            placeholder="why this member needs this reach"
          />
        </label>
      </div>
      {replaces && (
        <div className="error-banner" data-replaces>
          This REPLACES the standing grant already on this path: {replaces.recursive ? "subtree" : "exact"},
          reason "{replaces.reason ?? ""}"
          {replaces.expires_at ? `, until ${new Date(replaces.expires_at * 1000).toLocaleString()}` : ", no expiry"}.
          Last edit wins — the old reason and reach will not be kept.
        </div>
      )}
      {notice && <div className="error-banner">{notice}</div>}
      <button disabled={busy} onClick={grant}>
        {replaces ? "Replace grant" : "Grant"}
      </button>
    </section>
  );
}

export function Reach() {
  const [snap, setSnap] = useState<DashboardSnapshot | null>(null);
  const [status, setStatus] = useState<OperatorStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [s, st] = await Promise.all([getDashboard(), operatorStatus()]);
      setSnap(s);
      setStatus(st);
      setError(null);
    } catch (e) {
      // A failed look is a failed look: an empty table here would read as "no reach granted".
      setError(String(e));
      setSnap(null);
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 15_000);
    const onFocus = () => refresh();
    window.addEventListener("focus", onFocus);
    return () => {
      clearInterval(t);
      window.removeEventListener("focus", onFocus);
    };
  }, [refresh]);

  const grants = useMemo(() => snap?.scope_grants ?? [], [snap]);
  const byMember = useMemo(() => {
    const m = new Map<string, ScopeGrantRow[]>();
    for (const g of grants) m.set(g.plugin_id, [...(m.get(g.plugin_id) ?? []), g]);
    return [...m.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [grants]);
  const retired = new Set(snap?.retired ?? []);
  const grantable = (snap?.members ?? []).filter((m) => !retired.has(m)).sort();
  const signedIn = !!status?.signed_in;

  const acted = (msg: string) => {
    if (msg) setNotice(msg);
    refresh();
  };

  return (
    <div className="page">
      <header className="page-header">
        <h1>Reach</h1>
        {snap?.standing_generation !== undefined && (
          <span className="muted">standing store generation {snap.standing_generation}</span>
        )}
      </header>

      <p className="muted">
        What each member may touch beyond its own scope. One engine, several views: the dashboard
        and the CLI change these too, and the last edit wins — so a grant shows what it replaces
        before it is written.
      </p>

      {error && <div className="error-banner">could not read the grants: {error}</div>}
      {notice && <p data-notice>{notice}</p>}

      {snap && grants.length === 0 && (
        <p className="muted">No grants are in force: every member is held to its own scope.</p>
      )}

      {byMember.map(([member, rows]) => (
        <section key={member} className="section" data-member={member}>
          <h2>
            {member}
            {retired.has(member) && <span className="gate-differs"> · retired, still holding reach</span>}
          </h2>
          <table className="gate-table">
            <thead>
              <tr>
                <th>path</th>
                <th>lifetime</th>
                <th>reach</th>
                <th>why</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((g) => (
                <GrantRow
                  key={`${g.lifetime}:${g.path}:${g.request_id ?? ""}`}
                  g={g}
                  signedIn={signedIn}
                  onActed={acted}
                />
              ))}
            </tbody>
          </table>
        </section>
      ))}

      {signedIn && snap ? (
        <GrantForm members={grantable} grants={grants} onActed={acted} />
      ) : (
        status && (
          <p className="muted">
            Sign in as the operator to grant or revoke. Without the operator key these grants are
            only readable here.
          </p>
        )
      )}
    </div>
  );
}
