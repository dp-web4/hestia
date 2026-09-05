import { useState, useEffect, useCallback } from "react";
import { configSeatList, configSeatGet, configSeatPut } from "../lib/tauri";
import type {
  SeatConfigSummary,
  SeatConfigVerdict,
  SeatConfigPutResult,
} from "../lib/types";

// Vault-authored runtime config (#944 phase 0).
//
// The list is keys + health and refreshes; the inspect is the one place a value is shown, and
// the daemon witnesses that look. Save goes through the daemon's PUT, which validates, witnesses
// the intent (keys, never values), writes the vault, renders the projection in the same act and
// hands back that render's verdict — shown here immediately, so the operator sees whether what
// they saved is what the seat will start from. There is no delete on this surface: removing a
// variable is an edit; removing a seat's authoritative config is a lockout, and lives nowhere.

interface EnvRow {
  key: string;
  value: string;
}

function VerdictBadge({ v }: { v: SeatConfigVerdict }) {
  const cls =
    v.status === "verified"
      ? "cfg-verdict cfg-verdict-ok"
      : v.status === "unconfigured"
      ? "cfg-verdict cfg-verdict-none"
      : "cfg-verdict cfg-verdict-bad";
  const detail =
    v.status === "miswired"
      ? `expected ${v.expected?.slice(0, 12)}… found ${v.actual?.slice(0, 12)}…`
      : v.status === "missing"
      ? "no rendered artifact on disk"
      : v.status === "unreadable"
      ? v.error ?? ""
      : v.status === "unbacked"
      ? v.reason ?? "artifact present, vault declares nothing"
      : v.status === "verified"
      ? `sha256 ${v.sha256?.slice(0, 12)}…`
      : "";
  return (
    <span className={cls} title={detail}>
      {v.status}
    </span>
  );
}

function rowsFromEnv(env: Record<string, string>): EnvRow[] {
  return Object.keys(env)
    .sort()
    .map((key) => ({ key, value: env[key] }));
}

export function RuntimeConfig() {
  const [seats, setSeats] = useState<SeatConfigSummary[]>([]);
  const [renderDir, setRenderDir] = useState<string>("");
  const [listError, setListError] = useState<string | null>(null);

  const [selected, setSelected] = useState<string | null>(null);
  const [rows, setRows] = useState<EnvRow[]>([]);
  const [note, setNote] = useState("");
  const [loaded, setLoaded] = useState<SeatConfigSummary | null>(null);
  const [editError, setEditError] = useState<string | null>(null);
  const [saved, setSaved] = useState<SeatConfigPutResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [newSeat, setNewSeat] = useState("");

  const refresh = useCallback(async () => {
    try {
      const result = await configSeatList();
      setSeats(result.seats ?? []);
      setRenderDir(result.render_dir ?? "");
      setListError(null);
    } catch (e) {
      setListError(String(e));
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Open one seat. A configured seat is INSPECTED (values revealed, witnessed by the daemon);
  // an unconfigured one opens as an empty draft without a read, because there is nothing to
  // reveal and a 404 is not an error the operator needs to see.
  const open = async (member: string, configured: boolean) => {
    setSelected(member);
    setSaved(null);
    setEditError(null);
    if (!configured) {
      setRows([]);
      setNote("");
      setLoaded(null);
      return;
    }
    setBusy(true);
    try {
      const r = await configSeatGet(member);
      setRows(rowsFromEnv(r.config.env));
      setNote(r.config.note ?? "");
      setLoaded(r.summary);
    } catch (e) {
      setEditError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    if (!selected) return;
    const env: Record<string, string> = {};
    for (const r of rows) {
      const k = r.key.trim();
      if (!k) continue;
      if (k in env) {
        setEditError(`duplicate key ${k}`);
        return;
      }
      env[k] = r.value;
    }
    setBusy(true);
    setEditError(null);
    try {
      const result = await configSeatPut(selected, env, note);
      setSaved(result);
      // Re-inspect so the panel shows what the vault now holds, not what the form held.
      const r = await configSeatGet(selected);
      setRows(rowsFromEnv(r.config.env));
      setNote(r.config.note ?? "");
      setLoaded(r.summary);
      await refresh();
    } catch (e) {
      setEditError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const discard = () => {
    if (selected) {
      const s = seats.find((x) => x.member === selected);
      open(selected, s?.configured ?? false);
    }
  };

  const setRow = (i: number, patch: Partial<EnvRow>) =>
    setRows(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const removeRow = (i: number) => setRows(rows.filter((_, j) => j !== i));
  const addRow = () => setRows([...rows, { key: "", value: "" }]);

  return (
    <section className="runtime-config">
      <header className="page-header">
        <h2>Runtime config</h2>
        <button className="btn btn-sm" onClick={refresh} disabled={busy}>
          Refresh
        </button>
      </header>
      <p className="cfg-hint">
        Each seat's environment is authored here, held in the vault, rendered to{" "}
        <code>{renderDir || "…/seats"}</code> and checked against the vault. The list shows keys
        and health only; opening a seat reveals its values and is witnessed on the chain.
      </p>

      {listError && <div className="error-banner">{listError}</div>}

      <div className="cfg-seats">
        {seats.length === 0 ? (
          <p className="empty">No seats known to the daemon yet</p>
        ) : (
          seats.map((s) => (
            <div
              key={s.member}
              className={"cfg-seat" + (s.member === selected ? " cfg-seat-selected" : "")}
            >
              <span className="cfg-seat-name">{s.member}</span>
              <span className="cfg-seat-keys">
                {s.configured ? `${s.keys.length} var${s.keys.length === 1 ? "" : "s"}` : "not configured"}
                {s.configured && s.keys.length > 0 && (
                  <span className="cfg-seat-keylist"> — {s.keys.join(", ")}</span>
                )}
              </span>
              <VerdictBadge v={s.verdict} />
              <button
                className="btn btn-sm"
                onClick={() => open(s.member, s.configured)}
                disabled={busy}
              >
                {s.configured ? "Inspect" : "Configure"}
              </button>
            </div>
          ))
        )}
        <div className="cfg-seat cfg-seat-new">
          <input
            placeholder="seat id not listed (e.g. gemini)"
            value={newSeat}
            onChange={(e) => setNewSeat(e.target.value)}
          />
          <button
            className="btn btn-sm"
            disabled={busy || !newSeat.trim()}
            onClick={() => {
              const id = newSeat.trim();
              setNewSeat("");
              open(id, seats.some((s) => s.member === id && s.configured));
            }}
          >
            Configure
          </button>
        </div>
      </div>

      {selected && (
        <div className="cfg-editor">
          <div className="cfg-editor-header">
            <span className="cfg-seat-name">{selected}</span>
            {loaded && <VerdictBadge v={loaded.verdict} />}
            {loaded?.expected_sha256 && (
              <span className="cfg-digest" title={loaded.artifact}>
                expects {loaded.expected_sha256.slice(0, 16)}…
              </span>
            )}
          </div>

          {editError && <div className="error-banner">{editError}</div>}

          <table className="cfg-env">
            <thead>
              <tr>
                <th>variable</th>
                <th>value</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  <td>
                    <input
                      className="cfg-key"
                      placeholder="HESTIA_WORKSPACE"
                      value={r.key}
                      onChange={(e) => setRow(i, { key: e.target.value })}
                    />
                  </td>
                  <td>
                    <input
                      className="cfg-value"
                      value={r.value}
                      onChange={(e) => setRow(i, { value: e.target.value })}
                    />
                  </td>
                  <td>
                    <button className="btn btn-danger btn-sm" onClick={() => removeRow(i)}>
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="cfg-actions">
            <button className="btn btn-sm" onClick={addRow} disabled={busy}>
              Add variable
            </button>
            <input
              className="cfg-note"
              placeholder="note (why this config is what it is)"
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
            <button className="btn btn-primary" onClick={save} disabled={busy}>
              Save to vault
            </button>
            <button className="btn btn-sm" onClick={discard} disabled={busy}>
              Discard changes
            </button>
          </div>

          {saved && (
            <div className="cfg-saved">
              <div>
                {saved.replaced ? "Replaced" : "Created"} <strong>{saved.member}</strong> in the
                vault; rendered to <code>{saved.artifact}</code>. Intent{" "}
                <code>{saved.intentEntryHash.slice(0, 16)}…</code> on the chain.
              </div>
              <div className="cfg-saved-verdicts">
                {saved.verdict.length === 0 ? (
                  <span className="cfg-verdict cfg-verdict-bad">
                    no verdict returned — the render did not run
                  </span>
                ) : (
                  saved.verdict.map((v, i) => (
                    <span key={i}>
                      <VerdictBadge v={v} />{" "}
                      {v.status === "verified"
                        ? "the projection on disk matches what you saved"
                        : `the projection is ${v.status}; see the daemon's chain row`}
                    </span>
                  ))
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
