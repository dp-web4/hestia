import type { TrustView } from "../lib/types";
import { TensorBar } from "./TensorBar";

interface TrustCardProps {
  trust: TrustView;
}

const LEVEL_COLORS: Record<string, string> = {
  high: "#4ade80",
  "medium-high": "#a3e635",
  medium: "#facc15",
  "medium-low": "#fb923c",
  low: "#f87171",
};

export function TrustCard({ trust }: TrustCardProps) {
  const levelColor = LEVEL_COLORS[trust.level] ?? "#94a3b8";

  return (
    <div className="trust-card">
      <div className="trust-header">
        <span className="trust-plugin">{trust.plugin_id}</span>
        <span className="trust-level" style={{ color: levelColor }}>
          {trust.level}
        </span>
      </div>
      <div className="trust-tensors">
        <div className="tensor-group">
          <span className="tensor-group-label">T3</span>
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
      <div className="trust-footer">
        <span>{trust.action_count} actions</span>
        <span>{Math.round(trust.success_rate * 100)}% success</span>
      </div>
    </div>
  );
}
