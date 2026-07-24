import { useEffect, useState } from "react";
import { operatorSignIn, operatorSignOut, operatorStatus } from "../lib/tauri";
import type { OperatorStatus } from "../lib/types";

/**
 * Operator sign-in, sidebar-resident.
 *
 * Every `/api/*` route on the daemon is behind the operator gate, so without
 * a session the app can read nothing at all. One click signs in from
 * ~/.hestia/operator.key (dp: "I'd rather just click login"); a path box
 * covers a key kept elsewhere.
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

  const apply = (s: OperatorStatus) => {
    setStatus(s);
    setError(null);
    onChange?.();
  };

  useEffect(() => {
    operatorStatus()
      .then((s) => {
        setStatus(s);
        setPath(s.key_path ?? "");
      })
      .catch((e) => setError(String(e)));
  }, []);

  const signIn = async (keyPath?: string) => {
    setBusy(true);
    try {
      apply(await operatorSignIn(keyPath));
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
      <button
        className="operator-signin"
        onClick={() => signIn(undefined)}
        disabled={busy || !status.key_path}
      >
        {busy ? "signing in…" : "Sign in"}
      </button>
      <button className="operator-link" onClick={() => setShowPath((v) => !v)}>
        {status.key_path ? "other key…" : "choose key…"}
      </button>
      {showPath && (
        <div className="operator-path">
          <input
            value={path}
            placeholder="/path/to/operator.key"
            onChange={(e) => setPath(e.target.value)}
          />
          <button onClick={() => signIn(path)} disabled={busy || !path.trim()}>
            go
          </button>
        </div>
      )}
      {error && <p className="operator-error">{error}</p>}
    </div>
  );
}
