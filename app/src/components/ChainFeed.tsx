import type { RecentEntry } from "../lib/types";
import { ChainEntryRow } from "./ChainEntry";

interface ChainFeedProps {
  entries: RecentEntry[];
}

export function ChainFeed({ entries }: ChainFeedProps) {
  if (entries.length === 0) {
    return <div className="chain-empty">No witness chain entries yet</div>;
  }

  return (
    <div className="chain-feed">
      <div className="chain-header-row">
        <span>#</span>
        <span>Time</span>
        <span>Type</span>
        <span>Tool</span>
        <span>Target</span>
        <span>Hash</span>
      </div>
      {entries.map((entry) => (
        <ChainEntryRow key={entry.chain_position} entry={entry} />
      ))}
    </div>
  );
}
