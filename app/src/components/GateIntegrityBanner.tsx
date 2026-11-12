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

export function GateIntegrityBanner() {
  const [report, setReport] = useState<GateReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let stopped = false;
    let timer: number | undefined;
    const load = async () => {
      try {
        const next = await gatesVerify();
        if (!stopped) {
          setReport(next);
          setError(null);
        }
      } catch (e) {
        if (!stopped) setError(String(e));
      } finally {
        if (!stopped) timer = window.setTimeout(load, 15000);
      }
    };
    void load();
    return () => {
      stopped = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, []);

  if (error) {
    return (
      <div className="error-panel gate-integrity-banner" role="alert">
        <strong>Gate integrity could not be read.</strong> {error}
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
