interface StatusBadgeProps {
  online: boolean;
  label?: string;
}

export function StatusBadge({ online, label }: StatusBadgeProps) {
  return (
    <span className={`status-badge ${online ? "status-online" : "status-offline"}`}>
      <span className="status-dot" />
      {label ?? (online ? "Online" : "Offline")}
    </span>
  );
}
