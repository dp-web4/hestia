import { useState, useEffect, useCallback } from "react";
import type { RemoteEntry, DashboardSnapshot } from "../lib/types";
import {
  listRemotes,
  addRemote,
  removeRemote,
  getRemoteDashboard,
} from "../lib/tauri";
import { StatusBadge } from "../components/StatusBadge";

interface RemoteState {
  config: RemoteEntry;
  data: DashboardSnapshot | null;
  online: boolean;
  error?: string;
}

export function Fleet() {
  const [remotes, setRemotes] = useState<RemoteState[]>([]);
  const [showAdd, setShowAdd] = useState(false);
  const [newName, setNewName] = useState("");
  const [newUrl, setNewUrl] = useState("");
  const [error, setError] = useState<string | null>(null);

  const refreshRemotes = useCallback(async () => {
    try {
      const { remotes: configs } = await listRemotes();
      const states = await Promise.all(
        configs.map(async (config) => {
          try {
            const data = await getRemoteDashboard(config.url);
            const online = !("error" in data);
            return { config, data: online ? data : null, online };
          } catch {
            return { config, data: null, online: false };
          }
        })
      );
      setRemotes(states);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  useEffect(() => {
    refreshRemotes();
    const interval = setInterval(refreshRemotes, 5000);
    return () => clearInterval(interval);
  }, [refreshRemotes]);

  const handleAdd = async () => {
    if (!newName || !newUrl) return;
    try {
      await addRemote(newName, newUrl);
      setNewName("");
      setNewUrl("");
      setShowAdd(false);
      refreshRemotes();
    } catch (e) {
      setError(String(e));
    }
  };

  const handleRemove = async (name: string) => {
    try {
      await removeRemote(name);
      refreshRemotes();
    } catch (e) {
      setError(String(e));
    }
  };

  return (
    <div className="page">
      <header className="page-header">
        <h1>Fleet</h1>
        <button className="btn btn-primary" onClick={() => setShowAdd(!showAdd)}>
          {showAdd ? "Cancel" : "Add Remote"}
        </button>
      </header>

      {error && <div className="error-banner">{error}</div>}

      {showAdd && (
        <div className="remote-form">
          <input
            placeholder="Name (e.g. cbp, sprout, thor)"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
          />
          <input
            placeholder="URL (e.g. http://192.168.1.10:7711)"
            value={newUrl}
            onChange={(e) => setNewUrl(e.target.value)}
          />
          <button className="btn btn-primary" onClick={handleAdd}>
            Connect
          </button>
        </div>
      )}

      {remotes.length === 0 ? (
        <p className="empty">
          No remote daemons configured. Add a remote to monitor your fleet.
        </p>
      ) : (
        <div className="fleet-grid">
          {remotes.map(({ config, data, online }) => (
            <div key={config.name} className="fleet-card">
              <div className="fleet-card-header">
                <span className="fleet-name">{config.name}</span>
                <StatusBadge online={online} />
                <button
                  className="btn btn-danger btn-sm"
                  onClick={() => handleRemove(config.name)}
                >
                  Remove
                </button>
              </div>
              {data ? (
                <div className="fleet-card-body">
                  <div className="fleet-stats">
                    <span>Chain: {data.society.chain_length}</span>
                    <span>Actions: {data.stats.total_actions}</span>
                    <span>
                      Success: {Math.round(data.stats.success_rate * 100)}%
                    </span>
                    <span>Plugins: {data.trust.length}</span>
                  </div>
                  <div className="fleet-plugins">
                    {data.trust.map((t) => (
                      <span key={t.plugin_id} className="fleet-plugin-pill">
                        {t.plugin_id}: {t.level}
                      </span>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="fleet-card-body">
                  <span className="fleet-offline">Unreachable</span>
                  <code className="fleet-url">{config.url}</code>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
