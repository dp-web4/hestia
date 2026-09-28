import { useCallback, useEffect, useState } from "react";
import { gatesForget, gatesRatify, gatesVerify, operatorStatus } from "../lib/tauri";
import type { GateReport, GateVerdict, OperatorStatus } from "../lib/types";

/**
 * Gate integrity — are the installed gates the build you trust?
 *
 * Ratifying is the operator asserting "these installed bytes are the build I trust".
 * The daemon cannot tell a good build from a bad one, so the operator must ratify from a
 * state they believe correct. This page makes that belief CHECKABLE: beside each gate it
 * shows the bytes installed now and the bytes the deploy recorded installing, from which
 * build. If they match, the gate is exactly what the deploy wrote from main. If they
 * differ, something changed it after install — the case ratifying would bless.
 *
 * PER GATE (dp, 2026-09-28: "currently gate ratify button ratifies all - including mismatched
 * and non-deployed ... provide a by-gate ratification"). Each discovered gate is ratified on
 * its own, and only its own expectation changes. "Ratify all" remains for the clean case and
 * is offered only when the daemon says every gate is the bytes the deploy installed — the
 * daemon refuses it otherwise. A stale expectation (a path no gate is wired at any more) can
 * be forgotten, per path.
 *
 * Three rules hold regardless:
 *  - a reason is required to ratify or forget, as for every permitting act;
 *  - signed out, there are no controls at all;
 *  - the page re-reads the gates immediately before a write, and if the bytes being ratified
 *    moved since the operator looked, it stops and says so rather than ratifying unseen bytes.
 */

const short = (h?: string | null) => (h ? h.slice(0, 12) : "—");

function ratifiedDigest(v: GateVerdict): string | null {
  if (v.status === "verified") return v.sha256;
  if (v.status === "modified" || v.status === "missing") return v.expected;
  return null;
}


/** The digests an operator looked at, for the given paths — the stale-read key. */
function fingerprint(report: GateReport | null, paths?: string[]): string {
  const cur = report?.evidence?.current ?? {};
  const keys = (paths ?? Object.keys(cur)).slice().sort();
  return JSON.stringify(keys.map((k) => [k, cur[k] ?? null]));
}

export function Gates() {
  const [report, setReport] = useState<GateReport | null>(null);
  const [status, setStatus] = useState<OperatorStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const st = await operatorStatus();
      setStatus(st);
      if (!st.signed_in) {
        // Every /api/* route is operator-gated, so a signed-out app cannot read the gates.
        // Say that, rather than rendering an empty — and therefore reassuring — table.
        setReport(null);
        setError(null);
        return;
      }
      setReport(await gatesVerify());
      setError(null);
    } catch (e) {
      setError(String(e));
      setReport(null);
    }
  }, []);

  useEffect(() => {
    refresh();
    const onFocus = () => refresh();
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [refresh]);

  const needReason = (verb: string) => {
    if (reason.trim()) return false;
    setNotice(
      `${verb} requires a reason: it records why, and the chain entry is what makes that judgement reviewable.`,
    );
    return true;
  };

  /** paths === undefined: ratify all (the daemon accepts it only when every gate matches). */
  const ratify = async (paths?: string[]) => {
    setNotice(null);
    if (needReason("Ratifying")) return;
    setBusy(true);
    try {
      // Never ratify bytes the operator has not seen: re-read, and stop if the gates being
      // ratified moved since the page was rendered.
      const fresh = await gatesVerify();
      if (fingerprint(fresh, paths) !== fingerprint(report, paths)) {
        setReport(fresh);
        setNotice(
          "The installed gates changed since you looked. Nothing was ratified — review the new bytes below first.",
        );
        return;
      }
      const cur = report?.evidence?.current ?? {};
      const expected = paths ? Object.fromEntries(paths.map((p) => [p, cur[p] ?? null])) : cur;
      await gatesRatify(reason.trim(), expected, paths);
      setReason("");
      setNotice(paths ? `Ratified ${paths.join(", ")}. Other gates are unchanged; re-reading.`
                      : "Ratified every gate (all matched the deploy). Re-reading.");
      await refresh();
    } catch (e) {
      setNotice(String(e));
    } finally {
      setBusy(false);
    }
  };

  const forget = async (path: string) => {
    setNotice(null);
    if (needReason("Forgetting an expectation")) return;
    setBusy(true);
    try {
      await gatesForget(reason.trim(), [path]);
      setReason("");
      setNotice(`Forgot the expectation for ${path}. Re-reading.`);
      await refresh();
    } catch (e) {
      setNotice(String(e));
    } finally {
      setBusy(false);
    }
  };

  const signedIn = !!status?.signed_in;
  const current = report?.evidence?.current ?? {};
  const deployed = report?.evidence?.deployed ?? null;
  // A daemon that predates per-gate ratification ignores `paths` and would ratify EVERY gate
  // from a per-gate click. It is recognised by the absent `bulk_ratify` block.
  const perGate = !!report?.bulk_ratify;
  const canAct = signedIn && !!report && report.status !== "UNKNOWN" && perGate;

  return (
    <div className="page">
      <header className="page-header">
        <h1>Gates</h1>
        {report && <span className={`gate-status gate-${report.status.toLowerCase()}`}>{report.status}</span>}
      </header>

      <p className="muted">
        Tamper-evident, not tamper-proof: the daemon hashes the gates itself and compares them to
        what you last ratified. Ratifying a gate records its bytes installed now as the build you
        trust.
      </p>

      {!signedIn && status && (
        <p className="muted">
          Sign in as the operator to read gate integrity. The daemon serves it only to a proved
          operator key, so there is nothing to show here signed out — which is not the same as
          nothing being wrong.
        </p>
      )}

      {error && <div className="error-banner">could not read gate integrity: {error}</div>}

      {report?.status === "UNKNOWN" && (
        <div className="error-banner">
          UNKNOWN — {report.reason ?? "the daemon could not establish the gate set"}. This is not a
          clean result.
        </div>
      )}

      {signedIn && report && report.status !== "UNKNOWN" && !perGate && (
        <div className="error-banner">
          This daemon predates per-gate ratification, and would ratify every gate from any ratify
          request. Update the daemon; nothing can be ratified from here until then.
        </div>
      )}

      {deployed && (
        <p className="muted">
          Deploy authority: <code>{deployed.build_id ?? "?"}</code> from main{" "}
          <code>{short(deployed.head_sha)}</code>, installed {deployed.installed_at_iso ?? "?"}.
        </p>
      )}

      {canAct && (
        <div className="decide-actions">
          <label>
            reason <span className="muted">(required)</span>
            <input
              type="text"
              value={reason}
              maxLength={512}
              onChange={(e) => setReason(e.target.value)}
              placeholder="why these bytes are the build you trust"
            />
          </label>
        </div>
      )}
      {notice && <div className="error-banner">{notice}</div>}

      {report?.gates && report.gates.length > 0 && (
        <table className="gate-table">
          <thead>
            <tr>
              <th>gate</th>
              <th>status</th>
              <th>installed now</th>
              <th>last ratified</th>
              <th>vs the deploy</th>
              {canAct && <th></th>}
            </tr>
          </thead>
          <tbody>
            {report.gates.map((g, i) => {
              const path = g.path;
              const stale = g.discovered === false;
              // #1156: the daemon's judgement, rendered as-is. A ratified gate whose member still
              // declares one but has none registered is a bypass or a miswire, not a stale row.
              const notRegistered = g.not_registered === true;
              // The daemon's per-row status (spec v3): the same five values the dashboard shows.
              const dep = g.deployment;
              return (
                <tr key={i} data-gate-status={g.status}>
                  <td className="pre">{path}</td>
                  <td>{stale ? `${g.status} · no longer wired` : g.status}</td>
                  <td className="pre">{short(current[path])}</td>
                  <td className="pre">{short(ratifiedDigest(g))}</td>
                  <td>
                    {notRegistered && (
                      <strong className="gate-differs" title={g.forget_blocked_reason ?? undefined}>
                        NOT REGISTERED — possible bypass
                      </strong>
                    )}
                    {stale && !notRegistered && <span className="muted">not a gate on this machine any more</span>}
                    {!stale && dep === "match" && (
                      <span className="muted">matches what {deployed?.build_id} installed</span>
                    )}
                    {!stale && dep === "differs" && (
                      <strong className="gate-differs">
                        DIFFERS from what the deploy installed — changed after install
                      </strong>
                    )}
                    {!stale && dep === "not-deployed" && (
                      <span className="muted">not deployed: the deploy record names no such file</span>
                    )}
                    {!stale && dep === "no-deploy-record" && (
                      <span className="muted">no deploy record is readable on this box</span>
                    )}
                    {!stale && dep === "unreadable" && <strong>unreadable</strong>}
                  </td>
                  {canAct && (
                    <td>
                      {stale ? (
                        g.forgettable === true ? (
                          <button disabled={busy} aria-label={`forget ${path}`} onClick={() => forget(path)}>
                            Forget
                          </button>
                        ) : (
                          <span className="muted">{g.forget_blocked_reason ?? "not forgettable"}</span>
                        )
                      ) : (
                        <button
                          disabled={busy || dep === "unreadable"}
                          aria-label={`ratify ${path}`}
                          onClick={() => ratify([path])}
                        >
                          Ratify
                        </button>
                      )}
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {canAct && (report?.gates?.length ?? 0) > 0 && (
        <section className="section">
          <h2>Ratify all</h2>
          {report?.bulk_ratify?.allowed ? (
            <p className="muted">
              Every gate is exactly the bytes the deploy installed, so all of them can be ratified at
              once. This replaces every expectation, including stale ones.
            </p>
          ) : (
            <div className="error-banner">
              Not every gate is the bytes the deploy installed, so there is no ratify-all: review
              and ratify each gate on its own above. Ratifying a gate that differs records those
              changed bytes as trusted — you can, and the record says so, but it is the one case
              this check exists to make you look at.
              <ul>
                {(report?.bulk_ratify?.blocked_by ?? []).map((b) => (
                  <li key={b.path} className="pre">
                    {b.path} — {b.deployment}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <button disabled={busy || !report?.bulk_ratify?.allowed} onClick={() => ratify(undefined)}>
            Ratify all
          </button>
        </section>
      )}
    </div>
  );
}
