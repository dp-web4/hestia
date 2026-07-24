import { useState } from "react";
import type { TrustView } from "../lib/types";
import { TensorBar } from "./TensorBar";
import { ReceiptsDrawer } from "./ReceiptsDrawer";

interface TrustCardProps {
  trust: TrustView;
}

const LEVEL_COLORS: Record<string, string> = {
  high: "#4ade80",
  "medium-high": "#a3e635",
  medium: "#facc15",
  "medium-low": "#fb923c",
  low: "#f87171",
  unmeasured: "#94a3b8",
};

function pct(v: number | null | undefined) {
  return v == null ? "unmeasured" : `${Math.round(v * 100)}%`;
}

export function TrustCard({ trust }: TrustCardProps) {
  const [showReceipts, setShowReceipts] = useState(false);
  const levelColor = LEVEL_COLORS[trust.level] ?? "#94a3b8";

  // "legacy-lockstep-v1" means the three T3 numbers came from ONE self-reported
  // success scalar smeared across all three dimensions at fixed coefficients.
  // Rendering that as three independent facts is the misreading the T3-from-V3
  // arc exists to kill, so the card says so rather than pretending.
  const lockstep = trust.derivation === "legacy-lockstep-v1";
  const adj = trust.adjudicated_counts ?? [0, 0, 0];
  const adjTotal = adj[0] + adj[1] + adj[2];
  // When the earned record and the self-reported record disagree, show it —
  // that divergence is the whole finding, not an inconsistency to smooth over.
  const divergent =
    trust.legacy_level && trust.legacy_level !== trust.level ? trust.legacy_level : null;

  return (
    <div className="trust-card">
      <div className="trust-header">
        <span className="trust-plugin">{trust.plugin_id}</span>
        <span className="trust-level" style={{ color: levelColor }}>
          {trust.level}
        </span>
      </div>

      {divergent && (
        <p className="trust-divergence">
          self-reported record says <em>{divergent}</em> — displayed level is derived
          from adjudicated evidence
        </p>
      )}

      <div className="trust-tensors">
        <div className="tensor-group">
          <span className="tensor-group-label">
            T3 {lockstep && <em className="tensor-caveat">(lockstep — one scalar)</em>}
          </span>
          <TensorBar label="Talent" value={trust.t3_talent} color="#ff8b3d" />
          <TensorBar label="Training" value={trust.t3_training} color="#ff8b3d" />
          <TensorBar label="Temper" value={trust.t3_temperament} color="#ff8b3d" />
        </div>
        <div className="tensor-group">
          <span className="tensor-group-label">V3</span>
          <TensorBar label="Valuation" value={trust.v3_valuation} color="#60a5fa" />
          <TensorBar label="Veracity" value={trust.v3_veracity} color="#60a5fa" />
          <TensorBar label="Validity" value={trust.v3_validity} color="#60a5fa" />
        </div>
      </div>

      <div className="trust-derived">
        <div className="derived-row">
          <span>Temperament (conduct)</span>
          <span style={{ opacity: trust.derived_temperament == null ? 0.55 : 1 }}>
            {pct(trust.derived_temperament)}
            {trust.derived_temperament_n ? ` · n=${trust.derived_temperament_n}` : ""}
          </span>
        </div>
        <div className="derived-row">
          <span>Adjudicated (earned)</span>
          <span style={{ opacity: adjTotal === 0 ? 0.55 : 1 }}>
            {adjTotal === 0
              ? "no adjudications"
              : `val ${pct(trust.adjudicated_validity)} · ver ${pct(
                  trust.adjudicated_veracity,
                )} · valu ${pct(trust.adjudicated_valuation)}`}
          </span>
        </div>
        <button className="receipts-link" onClick={() => setShowReceipts(true)}>
          receipts →
        </button>
      </div>

      <div className="trust-footer">
        <span>{trust.action_count} actions</span>
        <span>{Math.round(trust.success_rate * 100)}% self-reported</span>
      </div>

      {showReceipts && (
        <ReceiptsDrawer
          pluginId={trust.plugin_id}
          role={trust.entity_id}
          onClose={() => setShowReceipts(false)}
        />
      )}
    </div>
  );
}
