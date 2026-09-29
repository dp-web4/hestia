import { useCallback, useEffect, useState } from "react";
import { agentsInventory, getDashboard, operatorStatus, reinstateAgent, retireAgent } from "../lib/tauri";
import type {
  AgentInventory,
  AgentRow,
  DashboardSnapshot,
  MemberActOutcome,
  OperatorStatus,
} from "../lib/types";

/**
 * Who is on this box, and is it governed.
 *
 * The daemon runs the agent inventory and serves its report: what is installed, what hestia
 * has an adapter for, what is actually governed, and the gaps between. Beings appear here
 * too (hestia #1076) — found by their launcher's `--member`, because a being has no config
 * file for the ordinary check to find.
 *
 * Sprint 3b adds the one lifecycle act that belongs here: RETIRE a recorded member id that
 * nothing on this machine accounts for (a typo, a grant made before an agent ever connected),
 * and REINSTATE it. Offered only on those ids — the same place the dashboard offers it — and
 * never on an installed agent's row: retiring the seat you are typing from is the accident the
 * daemon's live-member guard exists for, and the app should not walk toward it.
 *
 * `connect` is deliberately NOT offered. The route wires only a PostToolUse witness hook, not
 * the gate, so a button beside an UNGOVERNED row would promise governance it does not deliver;
 * governing is the members' installer's act.
 *
 * The rules it must not break:
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

/** Hestia's own clients connect to witness; they are not agents and never offered retire. */
const HESTIA_OWN_CLIENTS = new Set(["hestia-cli", "agent-inventory"]);

export interface UnaccountedMember {
  id: string;
  actions: number;
  retired: boolean;
}

/**
 * PURE: member ids this seat has recorded that no installed agent here carries — the
 * dashboard's "nothing on this machine accounts for it" group, from the same two sources
 * (the registry in the snapshot, the inventory's governance ids). An alias's acts count
 * toward its target, as they do on the dashboard.
 */
export function unaccountedMembers(
  inv: AgentInventory | null,
  snap: Pick<DashboardSnapshot, "trust" | "members" | "retired"> | null,
): UnaccountedMember[] {
  if (!snap) return [];
  const machine = (inv?.machine ?? "").toLowerCase();
  const accounted = new Set<string>();
  for (const r of inv?.detail ?? []) {
    if (r.plugin) accounted.add(r.plugin);
    if (r.kind === "being" && machine) accounted.add(`${machine}-being`);
    for (const l of r.launchers ?? []) if (l.member) accounted.add(l.member);
  }
  const acts = new Map<string, number>();
  for (const t of snap.trust ?? []) {
    const id = t.aliased_to || t.plugin_id;
    acts.set(id, (acts.get(id) ?? 0) + (t.action_count ?? 0));
  }
  const ids = new Set<string>([...(snap.members ?? []), ...acts.keys()]);
  const retired = new Set(snap.retired ?? []);
  return [...ids]
    .filter((id) => id && !accounted.has(id) && !HESTIA_OWN_CLIENTS.has(id))
    .sort()
    .map((id) => ({ id, actions: acts.get(id) ?? 0, retired: retired.has(id) }));
}

function MemberLifecycle({
  m,
  onActed,
}: {
  m: UnaccountedMember;
  onActed: () => void;
}) {
  const [reason, setReason] = useState("");
  const [ref, setRef] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  // Set only by the daemon's live-member refusal. The operator ticks it; it is never pre-set.
  const [question, setQuestion] = useState<Extract<MemberActOutcome, { outcome: "needs_confirmation" }> | null>(null);
  const [confirm, setConfirm] = useState(false);

  const act = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const out = m.retired
        ? await reinstateAgent(m.id, reason)
        : await retireAgent(m.id, reason, ref, confirm);
      if (out.outcome === "needs_confirmation") {
        setQuestion(out);
        setConfirm(false);
      } else if (out.outcome === "already_retired" || out.outcome === "already_reinstated") {
        setMsg(out.detail);
        onActed();
      } else if (out.outcome === "reinstated") {
        const back = (out.result.grants_not_restored as string[] | undefined) ?? [];
        setMsg(
          back.length
            ? `Reinstated. NOT restored — re-grant deliberately if still wanted: ${back.join(", ")}`
            : "Reinstated. It held no standing grants when it was retired.",
        );
        onActed();
      } else {
        setMsg("Retired on this seat. Not deleted: the chain keeps every act it made.");
        onActed();
      }
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="decide-actions" data-member={m.id}>
      <label>
        reason <span className="muted">(required)</span>
        <input type="text" value={reason} maxLength={512} onChange={(e) => setReason(e.target.value)} />
      </label>
      {!m.retired && (
        <label>
          reference <span className="muted">(required — the ruling, finding or issue)</span>
          <input type="text" value={ref} maxLength={512} onChange={(e) => setRef(e.target.value)} />
        </label>
      )}
      {question && (
        <div className="error-banner">
          {question.detail}
          <label className="check">
            <input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} />
            {question.unmeasurable
              ? "I have established myself that this id is not live"
              : `retire it anyway — ${question.acts_recently} act(s) in ${question.window_hours ?? 24}h`}
          </label>
        </div>
      )}
      <button disabled={busy || (!!question && !confirm)} onClick={act}>
        {m.retired ? "Reinstate" : "Retire"}
      </button>
      {msg && <p className="muted">{msg}</p>}
    </div>
  );
}

export function Agents() {
  const [inv, setInv] = useState<AgentInventory | null>(null);
  const [retired, setRetired] = useState<string[]>([]);
  const [snap, setSnap] = useState<DashboardSnapshot | null>(null);
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
      setSnap(snap);
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
  const orphans = status?.signed_in ? unaccountedMembers(inv, snap) : [];

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

      {orphans.length > 0 && (
        <section className="section">
          <h2>Recorded as a member here — and nothing on this machine accounts for it</h2>
          <p className="muted">
            A member id hestia has recorded, with no agent on disk behind it: a typo, or a grant made
            before an agent first connected. If it is a typo, merge it into the real id first so its
            acts are not orphaned. Retiring revokes its standing, live and delegated authority on
            this seat; it is not deletion, and it is reversible — but reinstating does not give the
            authority back.
          </p>
          {orphans.map((m) => (
            <article key={m.id} className="section" data-orphan={m.id}>
              <h3>
                <code>{m.id}</code>{" "}
                <span className="muted">
                  · {m.actions ? `${m.actions} act(s) recorded` : "never acted"}
                  {m.retired ? " · retired on this seat" : ""}
                </span>
              </h3>
              <MemberLifecycle m={m} onActed={refresh} />
            </article>
          ))}
        </section>
      )}

      {dormant.length > 0 && (
        <p className="muted">
          Adapters available for agents not installed here: {dormant.join(", ")}.
        </p>
      )}
    </div>
  );
}
