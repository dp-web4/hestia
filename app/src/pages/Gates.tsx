import { useCallback, useEffect, useState } from "react";
import { gatesRatify, gatesVerify, operatorStatus } from "../lib/tauri";
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
 * Evidence, not a verdict. Nothing is refused because bytes differ; the operator decides.
 * Three rules hold regardless:
 *  - a reason is required to ratify, as for every permitting act;
 *  - signed out, there is no ratify control at all;
 *  - ratifying REPLACES the previous expectations (last edit wins), so the page shows what
 *    it replaces and re-reads the gates immediately before the write. If the bytes moved
 *    since the operator looked, it stops and says so rather than ratifying unseen bytes.
 */

const short = (h?: string | null) => (h ? h.slice(0, 12) : "—");


function ratifiedDigest(v: GateVerdict): string | null {
  if (v.status === "verified") return v.sha256;
  if (v.status === "modified" || v.status === "missing") return v.expected;
  return null;
}

type Provenance = "matches" | "differs" | "no-record" | "unreadable";

function provenance(path: string, report: GateReport): Provenance {
  const cur = report.evidence?.current?.[path];
  const dep = report.evidence?.deployed?.files?.[path];
  if (cur === null || cur === undefined) return "unreadable";
  if (!dep) return "no-record";
  return cur === dep ? "matches" : "differs";
}

/** The set of current digests an operator actually looked at — the stale-read key. */
function fingerprint(report: GateReport | null): string {
  const cur = report?.evidence?.current ?? {};
  return JSON.stringify(Object.keys(cur).sort().map((k) => [k, cur[k]]));
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

  const ratify = async () => {
    setNotice(null);
    if (!reason.trim()) {
      setNotice(
        "Ratifying requires a reason: it records why these bytes are the ones you trust, and the chain entry is what makes that judgement reviewable.",
      );
      return;
    }
    setBusy(true);
    try {
      // Last edit wins, so never ratify bytes the operator has not seen: re-read, and stop
      // if the installed gates moved since the page was rendered.
      const fresh = await gatesVerify();
      if (fingerprint(fresh) !== fingerprint(report)) {
        setReport(fresh);
        setNotice(
          "The installed gates changed since you looked. Nothing was ratified — review the new bytes below first.",
        );
        return;
      }
      await gatesRatify(reason.trim());
      setReason("");
      setNotice("Ratified. The expectations above were replaced; re-reading.");
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
  const anyDiffers =
    report?.gates?.some((g) => provenance(g.path, report) === "differs") ?? false;

  return (
    <div className="page">
      <header className="page-header">
        <h1>Gates</h1>
        {report && <span className={`gate-status gate-${report.status.toLowerCase()}`}>{report.status}</span>}
      </header>

      <p className="muted">
        Tamper-evident, not tamper-proof: the daemon hashes the gates itself and compares them to
        what you last ratified. Ratifying records the bytes installed now as the build you trust.
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

      {deployed && (
        <p className="muted">
          Deploy authority: <code>{deployed.build_id ?? "?"}</code> from main{" "}
          <code>{short(deployed.head_sha)}</code>, installed {deployed.installed_at_iso ?? "?"}.
        </p>
      )}

      {report?.gates && report.gates.length > 0 && (
        <table className="gate-table">
          <thead>
            <tr>
              <th>gate</th>
              <th>status</th>
              <th>installed now</th>
              <th>last ratified</th>
              <th>vs the deploy</th>
            </tr>
          </thead>
          <tbody>
            {report.gates.map((g, i) => {
              const path = g.path;
              const prov = provenance(path, report);
              return (
                <tr key={i} data-gate-status={g.status}>
                  <td className="pre">{path}</td>
                  <td>{g.status}</td>
                  <td className="pre">{short(current[path])}</td>
                  <td className="pre">{short(ratifiedDigest(g))}</td>
                  <td>
                    {prov === "matches" && (
                      <span className="muted">matches what {deployed?.build_id} installed</span>
                    )}
                    {prov === "differs" && (
                      <strong className="gate-differs">
                        DIFFERS from what the deploy installed — changed after install
                      </strong>
                    )}
                    {prov === "no-record" && <span className="muted">no deploy record for this file</span>}
                    {prov === "unreadable" && <strong>unreadable</strong>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {signedIn && report && report.status !== "UNKNOWN" && (report.gates?.length ?? 0) > 0 && (
        <section className="section">
          <h2>Ratify the installed gates</h2>
          <p className="muted">
            This replaces the expectation for every gate above with its <em>installed now</em>{" "}
            digest. The <em>last ratified</em> column is what gets replaced.
          </p>
          {anyDiffers && (
            <div className="error-banner">
              At least one gate differs from what the deploy installed. Ratifying would record those
              changed bytes as trusted. You can — this is your decision, not the daemon's — but it is
              the one case this check exists to make you look at.
            </div>
          )}
          {notice && <div className="error-banner">{notice}</div>}
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
            <button disabled={busy} onClick={ratify}>
              Ratify
            </button>
          </div>
        </section>
      )}
    </div>
  );
}
