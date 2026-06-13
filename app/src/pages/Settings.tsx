import { useState, useEffect, useCallback } from "react";
import { getConfig, setMode, setDaemonUrl, getDaemonStatus } from "../lib/tauri";
import { StatusBadge } from "../components/StatusBadge";

export function Settings() {
  const [config, setConfig] = useState<{
    mode: string;
    daemon_url: string;
  } | null>(null);
  const [online, setOnline] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [urlDraft, setUrlDraft] = useState<string>("");

  const refresh = useCallback(async () => {
    try {
      const cfg = await getConfig();
      setConfig({ mode: cfg.mode, daemon_url: cfg.daemon_url });
      setUrlDraft(cfg.daemon_url);
      const status = await getDaemonStatus();
      setOnline(status.online);
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleUrlSave = async () => {
    try {
      await setDaemonUrl(urlDraft);
      refresh();
    } catch (e) {
      setError(String(e));
    }
  };

  const handleMode = async (mode: string) => {
    try {
      await setMode(mode);
      refresh();
    } catch (e) {
      setError(String(e));
    }
  };

  return (
    <div className="page">
      <header className="page-header">
        <h1>Settings</h1>
      </header>

      {error && <div className="error-banner">{error}</div>}

      <section className="section">
        <h2>Daemon</h2>
        <div className="settings-row">
          <span>Status</span>
          <StatusBadge online={online} />
        </div>
        {config && (
          <div className="settings-row">
            <span>URL</span>
            <span style={{ display: "flex", gap: 8, alignItems: "center", flex: 1, justifyContent: "flex-end" }}>
              <input
                value={urlDraft}
                onChange={(e) => setUrlDraft(e.target.value)}
                placeholder="http://host:7711"
                spellCheck={false}
                autoCapitalize="none"
                style={{
                  flex: 1,
                  maxWidth: 320,
                  background: "var(--bg)",
                  border: "1px solid var(--border)",
                  borderRadius: 6,
                  color: "var(--text)",
                  padding: "6px 10px",
                  fontFamily: "var(--font-mono)",
                  fontSize: 12,
                }}
              />
              <button
                className="btn"
                onClick={handleUrlSave}
                disabled={!urlDraft || urlDraft === config.daemon_url}
              >
                Save
              </button>
            </span>
          </div>
        )}
      </section>

      <section className="section">
        <h2>Mode</h2>
        <div className="mode-grid">
          {["sovereign", "mirror", "hybrid"].map((m) => (
            <button
              key={m}
              className={`btn mode-btn ${config?.mode === m ? "mode-active" : ""}`}
              onClick={() => handleMode(m)}
            >
              <strong>{m}</strong>
              <span className="mode-desc">
                {m === "sovereign" && "Local vault + chain + policy. Full node."}
                {m === "mirror" && "Read-only view of remote daemons."}
                {m === "hybrid" && "Local node + remote fleet monitoring."}
              </span>
            </button>
          ))}
        </div>
      </section>

      <section className="section">
        <h2>About</h2>
        <div className="about-info">
          <div className="settings-row">
            <span>Version</span>
            <span>0.1.0</span>
          </div>
          <div className="settings-row">
            <span>License</span>
            <span>AGPL-3.0</span>
          </div>
        </div>
      </section>
    </div>
  );
}
