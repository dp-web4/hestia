import { useState, useEffect, useCallback } from "react";
import type { DashboardSnapshot } from "../lib/types";
import { getDashboard, getDaemonStatus } from "../lib/tauri";

export function useDashboard(pollMs = 2000) {
  const [data, setData] = useState<DashboardSnapshot | null>(null);
  const [online, setOnline] = useState(false);
  // Signed-out is NOT the same failure as daemon-down; conflating them is what
  // made v0.1.2 read as simply broken once the operator gate landed.
  const [signedIn, setSignedIn] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const snapshot = await getDashboard();
      setData(snapshot);
      setOnline(true);
      setSignedIn(true);
      setError(null);
    } catch (e) {
      const msg = String(e);
      setError(msg);
      if (msg.includes("not signed in") || msg.includes("session expired")) {
        setSignedIn(false);
        // The daemon may be perfectly healthy — ask it directly.
        try {
          setOnline((await getDaemonStatus()).online);
        } catch {
          setOnline(false);
        }
      } else {
        setOnline(false);
      }
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, pollMs);
    // Sign-in/out happens in the sidebar; re-poll immediately rather than
    // making the operator wait out the interval.
    const onAuth = () => refresh();
    window.addEventListener("hestia:auth", onAuth);
    return () => {
      clearInterval(interval);
      window.removeEventListener("hestia:auth", onAuth);
    };
  }, [refresh, pollMs]);

  const checkStatus = useCallback(async () => {
    try {
      const status = await getDaemonStatus();
      setOnline(status.online);
      setSignedIn(status.signed_in ?? false);
    } catch {
      setOnline(false);
    }
  }, []);

  return { data, online, signedIn, error, refresh, checkStatus };
}
