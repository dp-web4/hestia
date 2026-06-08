import { useState, useEffect, useCallback } from "react";
import { getDashboard } from "../lib/tauri";
import { StatusBadge } from "../components/StatusBadge";

interface HubConnection {
  id: string;
  url: string;
  hub_lct_id: string;
  our_lct_id: string;
  connected_at: string;
  last_seen?: string;
  api_version: string;
  rest_endpoint: string;
  hubs_joined: string[];
}

export function Hubs() {
  const [connections, setConnections] = useState<HubConnection[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await getDashboard();
      setConnections((data as any)?.hub_connections ?? []);
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
        <h1>Hub Connections</h1>
        <button className="btn btn-secondary" onClick={refresh}>
          Refresh
        </button>
      </header>

      {error && <div className="error-banner">{error}</div>}

      <section className="section">
        <h2>Connected Hubs</h2>
        <p className="section-description">
          Web4 hubs you've connected to. Each connection is authenticated
          via challenge-response with your LCT identity.
        </p>

        {connections.length === 0 ? (
          <div className="empty-state">
            <p className="empty">No hub connections</p>
            <code className="hint">
              hestia hub connect https://hub.example.com
            </code>
          </div>
        ) : (
          <div className="hub-list">
            {connections.map((conn) => (
              <div key={conn.id} className="hub-card">
                <div className="hub-card-header">
                  <span className="hub-url">{conn.url}</span>
                  <StatusBadge online={true} />
                </div>
                <div className="hub-card-body">
                  <div className="hub-field">
                    <span className="field-label">Hub LCT</span>
                    <code>{conn.hub_lct_id.slice(0, 12)}...</code>
                  </div>
                  <div className="hub-field">
                    <span className="field-label">Our LCT</span>
                    <code>{conn.our_lct_id.slice(0, 12)}...</code>
                  </div>
                  <div className="hub-field">
                    <span className="field-label">API</span>
                    <span>{conn.api_version}</span>
                  </div>
                  <div className="hub-field">
                    <span className="field-label">Connected</span>
                    <span>
                      {new Date(conn.connected_at).toLocaleDateString()}
                    </span>
                  </div>
                  <div className="hub-field">
                    <span className="field-label">REST endpoint</span>
                    <code className="hub-endpoint">{conn.rest_endpoint}</code>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="section">
        <h2>How Hub Connection Works</h2>
        <div className="info-grid">
          <div className="info-card">
            <h3>Discovery</h3>
            <p>
              Hestia finds the hub via <code>/.well-known/web4-hub.json</code>.
              No manual endpoint configuration needed.
            </p>
          </div>
          <div className="info-card">
            <h3>Challenge-Response</h3>
            <p>
              Every request is signed with a fresh challenge nonce.
              No bearer tokens, no sessions — cryptographic proof every time.
            </p>
          </div>
          <div className="info-card">
            <h3>Multi-Hub</h3>
            <p>
              Connect to multiple hubs simultaneously. Each hub sees your
              identity; you control what each one knows.
            </p>
          </div>
        </div>
      </section>
    </div>
  );
}
