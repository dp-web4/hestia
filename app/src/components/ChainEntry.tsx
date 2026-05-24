import type { RecentEntry } from "../lib/types";

interface ChainEntryProps {
  entry: RecentEntry;
}

export function ChainEntryRow({ entry }: ChainEntryProps) {
  const time = new Date(entry.timestamp).toLocaleTimeString();
  const hashShort = entry.hash.slice(0, 8);

  let badge = "";
  let badgeClass = "badge-neutral";
  if (entry.event_type === "outcome") {
    badge = entry.success ? "OK" : "FAIL";
    badgeClass = entry.success ? "badge-success" : "badge-fail";
  } else if (entry.event_type === "policy_decision") {
    badge = entry.decision?.toUpperCase() ?? "POLICY";
    badgeClass =
      entry.decision === "allow"
        ? "badge-success"
        : entry.decision === "deny"
          ? "badge-fail"
          : "badge-warn";
  } else {
    badge = entry.event_type;
  }

  return (
    <div className="chain-entry">
      <span className="chain-pos">#{entry.chain_position}</span>
      <span className="chain-time">{time}</span>
      <span className={`chain-badge ${badgeClass}`}>{badge}</span>
      <span className="chain-tool">{entry.tool_name ?? ""}</span>
      <span className="chain-target">{entry.target ?? ""}</span>
      <span className="chain-hash" title={entry.hash}>
        {hashShort}
      </span>
    </div>
  );
}
