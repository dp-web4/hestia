import { useState, useEffect, useCallback } from "react";
import { getDashboard } from "../lib/tauri";

interface Delegation {
  id: string;
  delegator_lct_id: string;
  agent_lct_id: string;
  scope: {
    roles: string[];
    actions: string[];
  };
  created_at: string;
  expires_at?: string;
  revoked: boolean;
}

export function Delegations() {
  const [delegations, setDelegations] = useState<Delegation[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      // Delegations come from the daemon's dashboard endpoint
      // (or a dedicated endpoint — for now we show the concept)
      const data = await getDashboard();
      // The dashboard snapshot may include delegations in future;
      // for now show the placeholder with the delegation store data
      setDelegations((data as any)?.delegations ?? []);
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return (
    <div className="page">
      <header className="page-header">
        <h1>Delegations</h1>
        <button className="btn btn-secondary" onClick={refresh}>
          Refresh
        </button>
      </header>

      {error && <div className="error-banner">{error}</div>}

      <section className="section">
        <h2>Active Delegations</h2>
        <p className="section-description">
          Cryptographically signed authority grants from you to AI agents.
          Each delegation is scoped to specific roles and actions, with
          optional expiration. Revocable at any time.
        </p>

        {delegations.length === 0 ? (
          <div className="empty-state">
            <p className="empty">No active delegations</p>
            <code className="hint">
              hestia delegate grant &lt;agent-uuid&gt; --role administrator --expires 24
            </code>
          </div>
        ) : (
          <div className="delegation-list">
            {delegations.map((d) => (
              <div
                key={d.id}
                className={`delegation-card ${d.revoked ? "revoked" : "active"}`}
              >
                <div className="delegation-header">
                  <span className="delegation-id" title={d.id}>
                    {d.id.slice(0, 8)}...
                  </span>
                  <span
                    className={`badge ${d.revoked ? "badge-danger" : "badge-success"}`}
                  >
                    {d.revoked ? "Revoked" : "Active"}
                  </span>
                </div>
                <div className="delegation-body">
                  <div className="delegation-field">
                    <span className="field-label">Agent</span>
                    <code>{d.agent_lct_id.slice(0, 12)}...</code>
                  </div>
                  <div className="delegation-field">
                    <span className="field-label">Roles</span>
                    <span>
                      {d.scope.roles.length > 0
                        ? d.scope.roles.join(", ")
                        : "all"}
                    </span>
                  </div>
                  <div className="delegation-field">
                    <span className="field-label">Actions</span>
                    <span>
                      {d.scope.actions.length > 0
                        ? d.scope.actions.join(", ")
                        : "all"}
                    </span>
                  </div>
                  <div className="delegation-field">
                    <span className="field-label">Expires</span>
                    <span>
                      {d.expires_at
                        ? new Date(d.expires_at).toLocaleString()
                        : "Never"}
                    </span>
                  </div>
                  <div className="delegation-field">
                    <span className="field-label">Created</span>
                    <span>{new Date(d.created_at).toLocaleString()}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="section">
        <h2>How Delegation Works</h2>
        <div className="info-grid">
          <div className="info-card">
            <h3>Signed</h3>
            <p>
              Each delegation is Ed25519-signed by the delegator. The hub can
              verify that the agent's authority traces back to you.
            </p>
          </div>
          <div className="info-card">
            <h3>Scoped</h3>
            <p>
              Restrict by role (administrator, witness, etc.) and by specific
              actions. An agent can only do what you explicitly permit.
            </p>
          </div>
          <div className="info-card">
            <h3>Revocable</h3>
            <p>
              Revoke any delegation instantly. The agent loses authority
              immediately — no grace period, no negotiation.
            </p>
          </div>
        </div>
      </section>
    </div>
  );
}
