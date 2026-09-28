import { useCallback, useEffect, useState } from "react";
import { agentsInventory, getDashboard, operatorStatus } from "../lib/tauri";
import type { AgentInventory, AgentRow, OperatorStatus } from "../lib/types";

/**
 * Who is on this box, and is it governed.
 *
 * The daemon runs the agent inventory and serves its report: what is installed, what hestia
 * has an adapter for, what is actually governed, and the gaps between. Beings appear here
 * too (hestia #1076) — found by their launcher's `--member`, because a being has no config
 * file for the ordinary check to find.
 *
 * Read-only in this sprint. The rules it must not break:
 *  - UNKNOWN is shown as its reason, never as an empty list. "Could not look" rendered as
 *    "nothing ungoverned here" is the inversion the whole inventory exists to prevent.
 *  - An ungoverned agent is shown with the inventory's own findings IN FULL; they say
 *    exactly which hook is absent and on which event.
 *  - A retired id that is still governed or wired is called out: retiring revokes standing
 *    grants and hides an id by default, and an id that keeps acting after that is the case
 *    an operator most needs to see.
 */

function governanceLabel(row: AgentRow): string {
  if (row.unprovisioned) return "unprovisioned";
  if (row.miswired) return "miswired";
  if (row.partial) return "partial";
  return row.governed ? "governed" : "UNGOVERNED";
}

export function Agents() {
  const [inv, setInv] = useState<AgentInventory | null>(null);
  const [retired, setRetired] = useState<string[]>([]);
  const [status, setStatus] = useState<OperatorStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const st = await operatorStatus();
      setStatus(st);
      if (!st.signed_in) {
        setInv(null);
        setError(null);
        return;
      }
      const [report, snap] = await Promise.all([agentsInventory(), getDashboard()]);
      setInv(report);
      setRetired(snap.retired ?? []);
      setError(null);
    } catch (e) {
      setError(String(e));
      setInv(null);
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 30_000);
    const onFocus = () => refresh();
    window.addEventListener("focus", onFocus);
    return () => {
      clearInterval(t);
      window.removeEventListener("focus", onFocus);
    };
  }, [refresh]);

  const rows = (inv?.detail ?? []).filter((r) => r.installed);
  const dormant = inv?.gaps?.dormant_plugin ?? [];
  const ungoverned = inv?.gaps?.ungoverned ?? [];

  return (
    <div className="page">
      <header className="page-header">
        <h1>Agents</h1>
        {inv?.machine && <span className="muted">on {inv.machine}</span>}
      </header>

      <p className="muted">
        What is running on this box and whether hestia governs it. Read by the daemon from the
        agent inventory; the same report the dashboard's discover pane shows.
      </p>

      {!status?.signed_in && status && (
        <p className="muted">
          Sign in as the operator to read the inventory. Signed out there is nothing to show — which
          is not the same as nothing being ungoverned.
        </p>
      )}

      {error && <div className="error-banner">could not read the inventory: {error}</div>}

      {inv?.status === "UNKNOWN" && (
        <div className="error-banner">
          UNKNOWN — {inv.reason ?? "the inventory could not run"}. This is not a clean result: it
          means the box could not be looked at.
        </div>
      )}

      {inv && inv.status !== "UNKNOWN" && (
        <p>
          {inv.installed?.length ?? 0} installed · {inv.governed?.length ?? 0} governed
          {ungoverned.length > 0 && (
            <strong className="gate-differs"> · ungoverned: {ungoverned.join(", ")}</strong>
          )}
        </p>
      )}

      {rows.length > 0 && (
        <table className="gate-table">
          <thead>
            <tr>
              <th>agent</th>
              <th>governance</th>
              <th>governed as</th>
              <th>what the inventory found</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const isRetired = retired.includes(r.plugin);
              const retiredButLive = isRetired && (r.governed || r.wired);
              return (
                <tr key={r.agent} data-agent={r.agent}>
                  <td>
                    {r.agent}
                    {r.kind === "being" && <span className="muted"> · being</span>}
                  </td>
                  <td>
                    <span className={r.governed ? "" : "gate-differs"}>{governanceLabel(r)}</span>
                    {isRetired && (
                      <div>
                        {retiredButLive ? (
                          <strong className="gate-differs">
                            retired on this seat, but still {r.governed ? "governed" : "wired"}
                          </strong>
                        ) : (
                          <span className="muted">retired on this seat</span>
                        )}
                      </div>
                    )}
                  </td>
                  <td className="pre">
                    {r.plugin}
                    {r.launchers?.map((l) => (
                      <div key={l.unit} className="muted">
                        via {l.unit}
                        {l.member ? ` --member ${l.member}` : " (no --member)"}
                        {!l.sets_hestia_env && " · sets no HESTIA_HOME"}
                      </div>
                    ))}
                  </td>
                  <td>
                    {r.findings.length === 0 ? (
                      <span className="muted">—</span>
                    ) : (
                      <ul className="findings">
                        {r.findings.map((f, i) => (
                          <li key={i}>{f}</li>
                        ))}
                      </ul>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {dormant.length > 0 && (
        <p className="muted">
          Adapters available for agents not installed here: {dormant.join(", ")}.
        </p>
      )}
    </div>
  );
}
