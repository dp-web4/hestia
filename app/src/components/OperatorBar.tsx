import { useEffect, useState } from "react";
import { operatorSignIn, operatorSignOut, operatorStatus } from "../lib/tauri";
import type { OperatorStatus } from "../lib/types";

/**
 * Operator sign-in, sidebar-resident.
 *
 * Every `/api/*` route on the daemon is behind the operator gate, so without
 * a session the app can read nothing at all. The passphrase unlocks an
 * app-owned encrypted identity vault; first use imports and retires the
 * legacy plaintext operator credential only after the vault verifies.
 *
 * The key bytes and the bearer token never enter this webview — the Rust
 * shell holds both. This component only moves intent in and status out.
 */
export function OperatorBar({ onChange }: { onChange?: () => void }) {
  const [status, setStatus] = useState<OperatorStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showPath, setShowPath] = useState(false);
  const [path, setPath] = useState("");
  const [passphrase, setPassphrase] = useState("");

  const apply = (s: OperatorStatus) => {
    setStatus(s);
    setError(null);
    onChange?.();
  };

  useEffect(() => {
    operatorStatus()
      .then((s) => {
        setStatus(s);
        setPath(s.vault_path ?? "");
      })
      .catch((e) => setError(String(e)));
  }, []);

  const signIn = async (vaultPath?: string) => {
    setBusy(true);
    try {
      apply(await operatorSignIn(passphrase, vaultPath));
      setPassphrase("");
      setShowPath(false);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const signOut = async () => {
    setBusy(true);
    try {
      apply(await operatorSignOut());
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  if (!status) return <div className="operator-bar" />;

  if (status.signed_in) {
    return (
      <div className="operator-bar signed-in">
        <span className="operator-dot" aria-hidden />
        <span className="operator-lct" title={status.lct_id ?? ""}>
          {(status.lct_id ?? "").replace(/^lct:web4:[^:]*:/, "").slice(0, 10)}…
        </span>
        <button className="operator-link" onClick={signOut} disabled={busy}>
          sign out
        </button>
      </div>
    );
  }

  return (
    <div className="operator-bar">
      <input
        type="password"
        autoComplete="current-password"
        value={passphrase}
        placeholder="Identity vault passphrase"
        aria-label="Identity vault passphrase"
        onChange={(e) => setPassphrase(e.target.value)}
      />
      <button
        className="operator-signin"
        onClick={() => signIn(undefined)}
        disabled={
          busy ||
          !passphrase ||
          (!status.vault_exists && !status.migration_available)
        }
      >
        {busy
          ? "signing in…"
          : status.vault_exists
            ? "Sign in"
            : "Create vault & sign in"}
      </button>
      <button className="operator-link" onClick={() => setShowPath((v) => !v)}>
        other vault…
      </button>
      {showPath && (
        <div className="operator-path">
          <input
            value={path}
            placeholder="/path/to/identity.vault"
            onChange={(e) => setPath(e.target.value)}
          />
          <button
            onClick={() => signIn(path)}
            disabled={busy || !passphrase || !path.trim()}
          >
            go
          </button>
        </div>
      )}
      {error && <p className="operator-error">{error}</p>}
    </div>
  );
}
