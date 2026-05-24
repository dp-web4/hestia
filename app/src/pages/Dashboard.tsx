import { useDashboard } from "../hooks/useDashboard";
import { StatusBadge } from "../components/StatusBadge";
import { TrustCard } from "../components/TrustCard";
import { ChainFeed } from "../components/ChainFeed";
import { ToolHistogram } from "../components/ToolHistogram";

export function Dashboard() {
  const { data, online, error } = useDashboard(2000);

  if (error && !data) {
    return (
      <div className="page">
        <div className="error-panel">
          <StatusBadge online={false} />
          <p>Cannot reach Hestia daemon</p>
          <code>{error}</code>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="page">
        <div className="loading">Connecting to Hestia daemon...</div>
      </div>
    );
  }

  const { society, stats, trust, recent } = data;

  return (
    <div className="page">
      <header className="dashboard-header">
        <div className="header-left">
          <h1 className="brand">Hestia</h1>
          <StatusBadge online={online} />
        </div>
        <div className="header-stats">
          <div className="stat">
            <span className="stat-value">{society.chain_length}</span>
            <span className="stat-label">Chain</span>
          </div>
          <div className="stat">
            <span className="stat-value">{stats.total_actions}</span>
            <span className="stat-label">Actions</span>
          </div>
          <div className="stat">
            <span className="stat-value">
              {Math.round(stats.success_rate * 100)}%
            </span>
            <span className="stat-label">Success</span>
          </div>
          <div className="stat">
            <span className="stat-value">{stats.actions_last_hour}</span>
            <span className="stat-label">Last Hour</span>
          </div>
        </div>
      </header>

      <div className="dashboard-grid">
        <section className="section trust-section">
          <h2>Agent Trust</h2>
          {trust.length === 0 ? (
            <p className="empty">No active plugins in the last hour</p>
          ) : (
            <div className="trust-grid">
              {trust.map((t) => (
                <TrustCard key={t.plugin_id} trust={t} />
              ))}
            </div>
          )}
        </section>

        <section className="section chain-section">
          <h2>Witness Chain</h2>
          <ChainFeed entries={recent} />
        </section>

        <section className="section tools-section">
          <h2>Tool Usage</h2>
          <ToolHistogram data={stats.by_tool} />
        </section>
      </div>

      <footer className="dashboard-footer">
        <span title={society.sovereign_lct}>
          LCT: {society.sovereign_lct.slice(0, 12)}...
        </span>
        <span>{society.vault_entries} vault entries</span>
        <span>{society.active_sessions} sessions</span>
        <span>
          Updated: {new Date(data.generated_at).toLocaleTimeString()}
        </span>
      </footer>
    </div>
  );
}
