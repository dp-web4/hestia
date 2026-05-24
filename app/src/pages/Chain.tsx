import { useState, useEffect, useCallback } from "react";
import type { RecentEntry } from "../lib/types";
import { queryChain } from "../lib/tauri";
import { ChainFeed } from "../components/ChainFeed";

export function Chain() {
  const [entries, setEntries] = useState<RecentEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [limit, setLimit] = useState(100);
  const [eventFilter, setEventFilter] = useState("");
  const [toolFilter, setToolFilter] = useState("");

  const refresh = useCallback(async () => {
    try {
      const result = (await queryChain(
        limit,
        eventFilter || undefined,
        toolFilter || undefined
      )) as { entries?: RecentEntry[] };
      setEntries(result.entries ?? []);
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }, [limit, eventFilter, toolFilter]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return (
    <div className="page">
      <header className="page-header">
        <h1>Witness Chain</h1>
        <button className="btn btn-secondary" onClick={refresh}>
          Refresh
        </button>
      </header>

      {error && <div className="error-banner">{error}</div>}

      <div className="chain-filters">
        <input
          placeholder="Event type filter"
          value={eventFilter}
          onChange={(e) => setEventFilter(e.target.value)}
        />
        <input
          placeholder="Tool name filter"
          value={toolFilter}
          onChange={(e) => setToolFilter(e.target.value)}
        />
        <select
          value={limit}
          onChange={(e) => setLimit(Number(e.target.value))}
        >
          <option value={50}>50 entries</option>
          <option value={100}>100 entries</option>
          <option value={200}>200 entries</option>
          <option value={500}>500 entries</option>
        </select>
      </div>

      <ChainFeed entries={entries} />
    </div>
  );
}
