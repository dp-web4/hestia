import { useEffect, useState } from "react";
import { Link } from "react-router";
import { gatesVerify } from "../lib/tauri";
import type { GateReport, GateVerdict } from "../lib/types";

function member(v: GateVerdict): string {
  return v.plugin_id || v.path.split("/").filter(Boolean).pop() || v.path;
}

function summary(report: GateReport): string {
  if (report.status === "UNKNOWN") {
    return `UNKNOWN — ${report.reason || "the gate set could not be established"}`;
  }
  const rows = (report.gates || []).filter((v) => v.status !== "verified" || v.not_registered === true || v.deployment === "differs");
  const count = (pick: (v: GateVerdict) => boolean) => rows.filter(pick).length;
  const parts: string[] = [];
  const notRegistered = count((v) => v.not_registered === true);
  const modified = count((v) => v.status === "modified");
  const missing = count((v) => v.status === "missing" || v.status === "unreadable");
  const differs = count((v) => v.deployment === "differs");
  const pending = count((v) => v.status === "unratified" && v.deployment === "match");
  const unratified = count((v) => v.status === "unratified" && v.deployment !== "match");
  if (notRegistered) parts.push(`${notRegistered} not registered — possible bypass`);
  if (modified) parts.push(`${modified} modified since ratification`);
  if (missing) parts.push(`${missing} missing or unreadable`);
  if (differs) parts.push(`${differs} differs from the deploy`);
  if (pending) parts.push(`${pending} deployed, not yet ratified`);
  if (unratified) parts.push(`${unratified} unratified`);
  if (!parts.length) parts.push(report.status);
  const members = [...new Set(rows.map(member))];
  const shown = members.slice(0, 3).join(", ") + (members.length > 3 ? ` +${members.length - 3} more` : "");
  return `${rows.length} gate${rows.length === 1 ? "" : "s"}: ${parts.join(" · ")}${shown ? ` — ${shown}` : ""}`;
}

function healthy(report: GateReport): boolean {
  return report.status === "VERIFIED"
    && !(report.gates || []).some((v) => v.status !== "verified" || v.not_registered === true || v.deployment === "differs");
}

// A verify read that never answers must not keep the last state (#1575): each read is bounded,
// and once the last answer is older than two polls the banner says the set is unverified and
// since when, instead of staying silent on an old VERIFIED. `invoke` takes no AbortSignal, so the
// bound is a race; an answer that lands after it is dropped and the next poll reads again.
const POLL_MS = 15000;
const TIMEOUT_MS = 15000;
const STALE_MS = 2 * POLL_MS;

function bounded<T>(p: Promise<T>, ms: number): Promise<T> {
  return new Promise((resolve, reject) => {
    const t = window.setTimeout(() => reject(new Error(`no answer after ${ms / 1000}s`)), ms);
    p.then(
      (v) => { window.clearTimeout(t); resolve(v); },
      (e) => { window.clearTimeout(t); reject(e); },
    );
  });
}

export function GateIntegrityBanner() {
  const [report, setReport] = useState<GateReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [verifiedAt, setVerifiedAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    let stopped = false;
    let inFlight = false;
    let timer: number | undefined;
    const load = async () => {
      if (inFlight) return;
      inFlight = true;
      if (timer !== undefined) window.clearTimeout(timer);
      try {
        const next = await bounded(gatesVerify(), TIMEOUT_MS);
        if (!stopped) {
          setReport(next);
          setError(null);
          setVerifiedAt(Date.now());
        }
      } catch (e) {
        if (!stopped) setError(String(e));
      } finally {
        inFlight = false;
        if (!stopped) timer = window.setTimeout(load, POLL_MS);
      }
    };
    const onVisible = () => {
      if (document.visibilityState === "visible") void load();
    };
    const clock = window.setInterval(() => setNow(Date.now()), 5000);
    document.addEventListener("visibilitychange", onVisible);
    void load();
    return () => {
      stopped = true;
      if (timer !== undefined) window.clearTimeout(timer);
      window.clearInterval(clock);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, []);

  const since = verifiedAt !== null ? new Date(verifiedAt).toLocaleTimeString() : null;
  if (error) {
    return (
      <div className="error-panel gate-integrity-banner" role="alert">
        {since
          ? <strong>Gate integrity unverified — stale since {since}.</strong>
          : <strong>Gate integrity could not be read.</strong>} {error}
        <Link to="/gates">Inspect in Gates</Link>
      </div>
    );
  }
  if (verifiedAt !== null && now - verifiedAt > STALE_MS) {
    return (
      <div className="error-panel gate-integrity-banner" role="alert">
        <strong>Gate integrity unverified — stale since {since}.</strong> The last read has not answered.
        <Link to="/gates">Inspect in Gates</Link>
      </div>
    );
  }
  if (!report || healthy(report)) return null;
  return (
    <div className="error-panel gate-integrity-banner" role="alert">
      <strong>Gate integrity: {summary(report)}</strong>
      <Link to="/gates">Review and ratify in Gates</Link>
    </div>
  );
}
