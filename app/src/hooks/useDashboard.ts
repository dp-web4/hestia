import { useState, useEffect, useCallback, useRef } from "react";
import type { DashboardSnapshot, Handshake } from "../lib/types";
import { getDashboard, getDaemonStatus } from "../lib/tauri";

export function useDashboard(pollMs = 2000) {
  const [data, setData] = useState<DashboardSnapshot | null>(null);
  const [online, setOnline] = useState(false);
  // Signed-out is NOT the same failure as daemon-down; conflating them is what
  // made v0.1.2 read as simply broken once the operator gate landed.
  const [signedIn, setSignedIn] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // What the daemon at the configured URL is (web4#904). Read on every failure, because a
  // refusal from the shell may mean "incompatible daemon", which is neither down nor signed out.
  const [handshake, setHandshake] = useState<Handshake | null>(null);
  // Polls overlap (interval, sign-in, URL change), and a slow failure must not land on top of
  // a newer success. The guard keys on the newest response APPLIED, not the newest poll
  // STARTED: keyed on starts, a daemon slower than the interval had every answer discarded
  // and the dashboard never left "Connecting" (hestia#1280 recheck). `floor` is the first poll
  // after a sign-in or URL change; anything started before it spoke for the old context.
  const started = useRef(0);
  const applied = useRef(0);
  const floor = useRef(0);
  const stale = (mine: number) => mine < floor.current || mine < applied.current;

  const refresh = useCallback(async () => {
    const mine = ++started.current;
    try {
      const snapshot = await getDashboard();
      if (stale(mine)) return;
      applied.current = mine;
      setData(snapshot);
      setOnline(true);
      setSignedIn(true);
      setError(null);
      // The shell refuses every operator route to a daemon it has not found compatible, so a
      // route that answered IS the newer compatibility evidence. Without this, a recovered
      // daemon stayed behind the incompatible panel until the page remounted (hestia#1280).
      setHandshake(null);
    } catch (e) {
      if (stale(mine)) return;
      applied.current = mine;
      const msg = String(e);
      setError(msg);
      if (msg.includes("not signed in") || msg.includes("session expired")) {
        setSignedIn(false);
      }
      // The daemon may be perfectly healthy, or a release this app cannot talk to: ask it.
      try {
        const status = await getDaemonStatus();
        if (stale(mine)) return;
        setOnline(status.online);
        setHandshake(status.handshake ?? null);
      } catch {
        if (stale(mine)) return;
        setOnline(false);
        setHandshake(null);
      }
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, pollMs);
    // Sign-in/out happens in the sidebar; re-poll immediately rather than
    // making the operator wait out the interval.
    // The same for a new daemon URL: what the old daemon was says nothing about the new one.
    const onAuth = () => {
      floor.current = started.current + 1;
      refresh();
    };
    window.addEventListener("hestia:auth", onAuth);
    window.addEventListener("hestia:daemon-url", onAuth);
    return () => {
      clearInterval(interval);
      window.removeEventListener("hestia:auth", onAuth);
      window.removeEventListener("hestia:daemon-url", onAuth);
    };
  }, [refresh, pollMs]);

  const checkStatus = useCallback(async () => {
    try {
      const status = await getDaemonStatus();
      setOnline(status.online);
      setSignedIn(status.signed_in ?? false);
      setHandshake(status.handshake ?? null);
    } catch {
      setOnline(false);
    }
  }, []);

  return { data, online, signedIn, error, handshake, refresh, checkStatus };
}
