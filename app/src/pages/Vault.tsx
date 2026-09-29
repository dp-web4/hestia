import { useState, useEffect, useCallback } from "react";
import { vaultList, vaultSet, vaultDelete } from "../lib/tauri";
import { RuntimeConfig } from "../components/RuntimeConfig";

interface VaultEntry {
  id: string;
  name: string;
  scope: string[];
  tags: string[];
  allowed_consumers: string[];
  created_at: string;
  last_rotated?: string;
  /** Set when the daemon owns the entry (identity, device key, hub config). The daemon refuses
   *  to delete it, so this page offers no delete. Same field the dashboard's Govern -> vault reads. */
  system?: string | null;
}

export function Vault() {
  const [entries, setEntries] = useState<VaultEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState({
    name: "",
    value: "",
    scope: "",
    tags: "",
    consumers: "",
  });

  const refresh = useCallback(async () => {
    try {
      const result = (await vaultList()) as { entries?: VaultEntry[] };
      setEntries(result.entries ?? []);
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleAdd = async () => {
    try {
      await vaultSet(
        form.name,
        form.value,
        form.scope.split(",").map((s) => s.trim()).filter(Boolean),
        form.tags.split(",").map((s) => s.trim()).filter(Boolean),
        form.consumers.split(",").map((s) => s.trim()).filter(Boolean)
      );
      setForm({ name: "", value: "", scope: "", tags: "", consumers: "" });
      setShowAdd(false);
      refresh();
    } catch (e) {
      setError(String(e));
    }
  };

  const handleDelete = async (name: string) => {
    // A deleted value cannot be recovered from here, so typing the name back is the
    // confirmation (same as the dashboard's Govern -> vault).
    const typed = window.prompt(
      `Delete '${name}' from the vault? Its value cannot be recovered.\nType the name to confirm:`,
    );
    if (typed === null) return;
    if (typed.trim() !== name) {
      setError("Name did not match — nothing was deleted.");
      return;
    }
    try {
      await vaultDelete(name);
      refresh();
    } catch (e) {
      setError(String(e));
    }
  };

  return (
    <div className="page">
      <header className="page-header">
        <h1>Credential Vault</h1>
        <button className="btn btn-primary" onClick={() => setShowAdd(!showAdd)}>
          {showAdd ? "Cancel" : "Add Credential"}
        </button>
      </header>

      {error && <div className="error-banner">{error}</div>}

      {showAdd && (
        <div className="vault-form">
          <input
            placeholder="Name (e.g. npm-token)"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
          <input
            type="password"
            placeholder="Secret value"
            value={form.value}
            onChange={(e) => setForm({ ...form, value: e.target.value })}
          />
          <input
            placeholder="Scope (comma-separated: publish, infer)"
            value={form.scope}
            onChange={(e) => setForm({ ...form, scope: e.target.value })}
          />
          <input
            placeholder="Tags (comma-separated)"
            value={form.tags}
            onChange={(e) => setForm({ ...form, tags: e.target.value })}
          />
          <input
            placeholder="Allowed consumers (plugin IDs, comma-separated)"
            value={form.consumers}
            onChange={(e) => setForm({ ...form, consumers: e.target.value })}
          />
          <button className="btn btn-primary" onClick={handleAdd}>
            Store
          </button>
        </div>
      )}

      <div className="vault-list">
        {entries.length === 0 ? (
          <p className="empty">No credentials stored</p>
        ) : (
          entries.map((entry) => (
            <div key={entry.id} className="vault-entry">
              <div className="vault-entry-header">
                <span className="vault-name">{entry.name}</span>
                {entry.system ? (
                  <span className="vault-scope" title={entry.system}>
                    daemon · {entry.system}
                  </span>
                ) : (
                  <button
                    className="btn btn-danger btn-sm"
                    onClick={() => handleDelete(entry.name)}
                  >
                    Delete
                  </button>
                )}
              </div>
              <div className="vault-meta">
                {entry.scope.length > 0 && (
                  <span className="vault-scope">
                    Scope: {entry.scope.join(", ")}
                  </span>
                )}
                {entry.tags.length > 0 && (
                  <span className="vault-tags">
                    Tags: {entry.tags.join(", ")}
                  </span>
                )}
                <span className="vault-created">
                  Created: {new Date(entry.created_at).toLocaleDateString()}
                </span>
              </div>
            </div>
          ))
        )}
      </div>

      <RuntimeConfig />
    </div>
  );
}
