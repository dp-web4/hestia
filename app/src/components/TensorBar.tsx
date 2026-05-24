interface TensorBarProps {
  label: string;
  value: number;
  color: string;
}

export function TensorBar({ label, value, color }: TensorBarProps) {
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
