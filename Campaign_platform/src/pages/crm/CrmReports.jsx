/**
 * CRM Reports — pipeline value by stage, weighted forecast, win rate,
 * velocity, and activity volume. Plus duplicate-account review & merge.
 */
import { useEffect, useState, useCallback } from "react";
import { RefreshCw, TrendingUp, GitMerge } from "lucide-react";
import api from "../../utils/api";
import CrmNav, { Modal } from "./CrmNav";
import "../../styles/crm-ui.css";

const fmt = (n) =>
  typeof n === "number" ? n.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 }) : "—";

export default function CrmReports() {
  const [pipeline, setPipeline] = useState(null);
  const [activity, setActivity] = useState(null);
  const [dupes, setDupes] = useState([]);
  const [merging, setMerging] = useState(null);   // duplicate group being merged
  const [primaryId, setPrimaryId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [p, a, d] = await Promise.all([
        api.get("/api/crm/reports/pipeline", {}, { cacheTTL: 0 }),
        api.get("/api/crm/reports/activity", { days: 30 }, { cacheTTL: 0 }),
        api.get("/api/crm/duplicates/accounts", {}, { cacheTTL: 0 }),
      ]);
      setPipeline(p);
      setActivity(a);
      setDupes(Array.isArray(d) ? d : []);
    } catch (e) {
      setError(e.message || "Failed to load reports");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const confirmMerge = async () => {
    setBusy(true);
    try {
      await api.post("/api/crm/accounts/merge", {
        primary_id: primaryId,
        duplicate_ids: merging.accounts.map((a) => a._id).filter((id) => id !== primaryId),
      });
      setMerging(null);
      await load();
    } catch (e) { setError(e.message || "Merge failed"); }
    finally { setBusy(false); }
  };

  const maxStageValue = Math.max(1, ...(pipeline?.stages || []).map((s) => s.value));

  return (
    <div className="crm-page">
      <CrmNav />
      <div className="crm-head">
        <div>
          <h1 className="crm-title">Reports</h1>
          <p className="crm-subtitle">Pipeline health, forecast and data quality.</p>
        </div>
        <button className="crm-btn" onClick={load}><RefreshCw size={15} /> Refresh</button>
      </div>

      {error && <div className="crm-error">{error}</div>}
      {loading ? <p className="crm-muted">Loading…</p> : (
        <>
          <div className="crm-cards">
            <div className="crm-card">
              <div className="crm-card__top"><span className="crm-card__label">Open pipeline</span><TrendingUp size={18} className="crm-icon" /></div>
              <div className="crm-card__value">{fmt(pipeline?.open_value)}</div>
              <div className="crm-muted" style={{ fontSize: "0.75rem" }}>{pipeline?.open_count ?? 0} open deals</div>
            </div>
            <div className="crm-card">
              <div className="crm-card__top"><span className="crm-card__label">Weighted forecast</span></div>
              <div className="crm-card__value">{fmt(pipeline?.forecast)}</div>
              <div className="crm-muted" style={{ fontSize: "0.75rem" }}>amount × stage probability</div>
            </div>
            <div className="crm-card">
              <div className="crm-card__top"><span className="crm-card__label">Win rate</span></div>
              <div className="crm-card__value">
                {pipeline?.win_rate != null ? `${Math.round(pipeline.win_rate * 100)}%` : "—"}
              </div>
              <div className="crm-muted" style={{ fontSize: "0.75rem" }}>
                {pipeline?.won_count ?? 0} won / {pipeline?.lost_count ?? 0} lost
              </div>
            </div>
            <div className="crm-card">
              <div className="crm-card__top"><span className="crm-card__label">Avg days to close</span></div>
              <div className="crm-card__value">{pipeline?.avg_days_to_close ?? "—"}</div>
              <div className="crm-muted" style={{ fontSize: "0.75rem" }}>won deals only</div>
            </div>
          </div>

          <div className="crm-panel" style={{ marginBottom: "1rem" }}>
            <div className="crm-panel__head">Pipeline by stage</div>
            <div style={{ padding: "1rem" }}>
              {(pipeline?.stages || []).map((s) => (
                <div key={s.stage} style={{ display: "flex", alignItems: "center", gap: "0.6rem", marginBottom: "0.45rem" }}>
                  <span className="crm-mono" style={{ width: 90 }}>{s.stage}</span>
                  <div style={{ flex: 1, background: "#f3f4f6", borderRadius: "0.3rem", height: 18, overflow: "hidden" }}>
                    <div style={{
                      width: `${Math.round((s.value / maxStageValue) * 100)}%`,
                      minWidth: s.count ? 4 : 0, height: "100%",
                      background: s.stage === "won" ? "#059669" : s.stage === "lost" ? "#dc2626" : "#3b82f6",
                    }} />
                  </div>
                  <span style={{ width: 150, textAlign: "right", fontSize: "0.8rem" }}>
                    {s.count} · {fmt(s.value)}
                  </span>
                </div>
              ))}
            </div>
          </div>

          <div className="crm-md" style={{ alignItems: "start" }}>
            <div className="crm-panel">
              <div className="crm-panel__head">Activity — last {activity?.days ?? 30} days ({activity?.total ?? 0})</div>
              <div style={{ padding: "0.75rem 1rem" }}>
                {Object.entries(activity?.by_type || {}).length === 0 ? (
                  <p className="crm-muted">No activity in window.</p>
                ) : Object.entries(activity.by_type).map(([type, n]) => (
                  <div key={type} className="crm-row" style={{ padding: "0.3rem 0" }}>
                    <span className="crm-mono" style={{ flex: 1 }}>{type}</span>
                    <span style={{ fontWeight: 600 }}>{n}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="crm-panel">
              <div className="crm-panel__head">
                <GitMerge size={15} className="crm-icon" /> Possible duplicate accounts ({dupes.length} groups)
              </div>
              <div style={{ padding: "0.75rem 1rem" }}>
                {dupes.length === 0 ? (
                  <p className="crm-muted">No likely duplicates. 🎉</p>
                ) : dupes.map((g) => (
                  <div key={g.key} style={{ border: "1px solid #f3f4f6", borderRadius: "0.4rem", padding: "0.5rem 0.7rem", marginBottom: "0.5rem" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <span style={{ fontSize: "0.82rem" }}>
                        {g.accounts.map((a) => a.name).join("  ·  ")}
                      </span>
                      <button className="crm-btn" style={{ padding: "0.25rem 0.5rem", fontSize: "0.72rem" }}
                        onClick={() => { setMerging(g); setPrimaryId(g.accounts[0]._id); }}>
                        <GitMerge size={13} /> Merge
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </>
      )}

      {merging && (
        <Modal title="Merge duplicate accounts" onClose={() => setMerging(null)}>
          <p className="crm-muted" style={{ marginTop: 0, fontSize: "0.82rem" }}>
            Pick the account to keep. All contacts, deals, invoices and history from the
            others will be re-pointed onto it; the duplicates are archived.
          </p>
          {merging.accounts.map((a) => (
            <label key={a._id} style={{ display: "flex", gap: "0.5rem", alignItems: "center", padding: "0.35rem 0", fontSize: "0.85rem" }}>
              <input type="radio" name="primary" checked={primaryId === a._id}
                onChange={() => setPrimaryId(a._id)} />
              <span style={{ fontWeight: primaryId === a._id ? 700 : 400 }}>{a.name}</span>
              <span className="crm-muted" style={{ fontSize: "0.72rem" }}>
                created {a.created_at ? new Date(a.created_at).toLocaleDateString() : "?"}
              </span>
            </label>
          ))}
          <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem", marginTop: "0.6rem" }}>
            <button className="crm-btn" onClick={() => setMerging(null)}>Cancel</button>
            <button className="crm-btn crm-btn--primary" disabled={busy} onClick={confirmMerge}>
              {busy ? "Merging…" : "Merge into selected"}
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
