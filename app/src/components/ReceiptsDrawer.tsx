import { useEffect, useState } from "react";
import { getDerivation } from "../lib/tauri";
import type { DerivationReceipt, DerivedDimension } from "../lib/types";

interface Props {
  pluginId: string;
  role?: string;
  onClose: () => void;
}

const DIMS: { key: keyof DerivationReceipt; label: string }[] = [
  { key: "temperament", label: "Temperament" },
  { key: "validity", label: "Validity" },
  { key: "veracity", label: "Veracity" },
  { key: "valuation", label: "Valuation" },
];

function score(d: DerivedDimension) {
  return d.score == null ? "unmeasured" : `${Math.round(d.score * 100)}%`;
}

function Dimension({ label, dim }: { label: string; dim: DerivedDimension }) {
  return (
    <div className="receipt-dim">
      <div className="receipt-dim-head">
        <strong>{label}</strong>
        <span style={{ opacity: dim.score == null ? 0.55 : 1 }}>
          {score(dim)} · n={dim.observations}
        </span>
      </div>
      <p className="receipt-formula">{dim.formula}</p>
      {dim.evidence.length === 0 ? (
        <p className="receipt-empty">
          No evidence on this dimension — the score is unmeasured, not zero.
        </p>
      ) : (
        <ul className="receipt-evidence">
          {dim.evidence.map((e) => {
            // Exclusions (exoneration / amnesty) are carried in `contribution`
            // by the daemon; surface them rather than hiding the history.
            const excluded = e.contribution.toUpperCase().includes("EXCLUDED");
            return (
              <li key={e.hash} className={excluded ? "excluded" : undefined}>
                <span className="receipt-pos">#{e.chain_position}</span>
                <span className="receipt-contrib">{e.contribution}</span>
                <span className="receipt-meta">
                  {e.event_type} · {e.timestamp.slice(0, 19).replace("T", " ")}
                </span>
                {e.reference && <span className="receipt-ref">{e.reference}</span>}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

/**
 * The receipts drawer: why a trust score is what it is, with every piece of
 * evidence addressable by chain position + hash. The app never computes a
 * score — the daemon derives, this displays.
 */
export function ReceiptsDrawer({ pluginId, role, onClose }: Props) {
  const [receipt, setReceipt] = useState<DerivationReceipt | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    getDerivation(pluginId, role)
      .then((r) => live && setReceipt(r))
      .catch((e) => live && setError(String(e)));
    return () => {
      live = false;
    };
  }, [pluginId, role]);

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="drawer" onClick={(e) => e.stopPropagation()}>
        <header className="drawer-head">
          <div>
            <h2>{pluginId}</h2>
            {receipt && <code className="drawer-role">{receipt.role_lct}</code>}
          </div>
          <button className="drawer-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </header>

        {error && <p className="receipt-error">{error}</p>}
        {!receipt && !error && <p className="receipt-empty">Loading receipts…</p>}

        {receipt && (
          <>
            <p className="drawer-sub">
              {receipt.derivation_version} · generated{" "}
              {receipt.generated_at.slice(0, 19).replace("T", " ")} · level{" "}
              <strong>{receipt.level}</strong>
            </p>
            {DIMS.map(({ key, label }) => (
              <Dimension
                key={label}
                label={label}
                dim={receipt[key] as DerivedDimension}
              />
            ))}
          </>
        )}
      </aside>
    </div>
  );
}
