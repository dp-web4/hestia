interface TensorBarProps {
  label: string;
  value: number | null;
  color: string;
}

export function TensorBar({ label, value, color }: TensorBarProps) {
  // Canonical unmeasured-handling: null = zero observations on this dimension —
  // render "unmeasured", never a fabricated score.
  if (value == null) {
    return (
      <div className="tensor-bar">
        <span className="tensor-label">{label}</span>
        <div className="tensor-track" />
        <span className="tensor-value" style={{ opacity: 0.55 }}>unmeasured</span>
      </div>
    );
  }
  const pct = Math.round(value * 100);
  return (
    <div className="tensor-bar">
      <span className="tensor-label">{label}</span>
      <div className="tensor-track">
        <div
          className="tensor-fill"
          style={{ width: `${pct}%`, backgroundColor: color }}
        />
      </div>
      <span className="tensor-value">{pct}%</span>
    </div>
  );
}
