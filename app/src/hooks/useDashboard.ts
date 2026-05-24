import { useState, useEffect, useCallback } from "react";
import type { DashboardSnapshot } from "../lib/types";
import { getDashboard, getDaemonStatus } from "../lib/tauri";

export function useDashboard(pollMs = 2000) {
  const [data, setData] = useState<DashboardSnapshot | null>(null);
  const [online, setOnline] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const snapshot = await getDashboard();
      setData(snapshot);
      setOnline(true);
      setError(null);
    } catch (e) {
      setError(String(e));
      setOnline(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, pollMs);
    return () => clearInterval(interval);
  }, [refresh, pollMs]);

  const checkStatus = useCallback(async () => {
    try {
      const status = await getDaemonStatus();
      setOnline(status.online);
    } catch {
      setOnline(false);
    }
  }, []);

  return { data, online, error, refresh, checkStatus };
}
