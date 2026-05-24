import { useState, useEffect, useCallback } from "react";
import { getPolicy, setPreset } from "../lib/tauri";

const PRESETS = ["permissive", "safety", "strict", "audit-only"];

export function Policy() {
  const [policy, setPolicy] = useState<Record<string, unknown> | null>(null);
  const [activePreset, setActivePreset] = useState("");
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const result = (await getPolicy()) as Record<string, unknown>;
      setPolicy(result);
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handlePreset = async (preset: string) => {
    try {
      await setPreset(preset);
      setActivePreset(preset);
      refresh();
    } catch (e) {
      setError(String(e));
    }
  };

  return (
    <div className="page">
      <header className="page-header">
        <h1>Policy Engine</h1>
      </header>

      {error && <div className="error-banner">{error}</div>}

      <section className="section">
        <h2>Preset</h2>
        <div className="preset-grid">
          {PRESETS.map((p) => (
            <button
              key={p}
              className={`btn preset-btn ${activePreset === p ? "preset-active" : ""}`}
              onClick={() => handlePreset(p)}
            >
              {p}
            </button>
          ))}
        </div>
      </section>

      {policy && (
        <section className="section">
          <h2>Active Rules</h2>
          <pre className="policy-json">{JSON.stringify(policy, null, 2)}</pre>
        </section>
      )}
    </div>
  );
}
