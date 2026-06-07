/**
 * AI Approvals — human-in-the-loop queue for the AI decision engine.
 * Plain CSS (crm-ui.css). Consumes /api/ai/queue + approve/reject + /api/ai/decisions.
 */
import { useEffect, useState, useCallback } from "react";
import { CheckCircle2, XCircle, RefreshCw, Bot, ShieldAlert, ListChecks, History } from "lucide-react";
import api from "../../utils/api";
import "../../styles/crm-ui.css";

function PendingQueue() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [actingId, setActingId] = useState(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const data = await api.get("/api/ai/queue", { status: "pending" });
      setItems(Array.isArray(data) ? data : []);
    } catch (e) {
      setError(e.message || "Failed to load queue");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const decide = async (id, approve) => {
    const reason = approve ? null : (window.prompt("Reason for rejection (optional):") || null);
    setActingId(id);
    try {
      if (approve) await api.post(`/api/ai/queue/${id}/approve`);
      else await api.post(`/api/ai/queue/${id}/reject`, { reason });
      setItems((prev) => prev.filter((it) => it._id !== id));
    } catch (e) {
      setError(e.message || "Action failed");
    } finally {
      setActingId(null);
    }
  };

  return (
    <div>
      <div className="crm-head">
        <p className="crm-muted">{loading ? "Loading…" : `${items.length} action${items.length === 1 ? "" : "s"} awaiting approval`}</p>
        <button onClick={load} className="crm-btn"><RefreshCw size={16} /> Refresh</button>
      </div>

      {error && <div className="crm-error">{error}</div>}

      {!loading && items.length === 0 && !error && (
        <div className="crm-empty"><CheckCircle2 size={28} style={{ color: "#34d399" }} /><div style={{ marginTop: "0.5rem" }}>Nothing pending. The AI queue is clear.</div></div>
      )}

      {items.map((item) => (
        <div key={item._id} className="crm-queue-item">
          <div className="crm-queue-item__head">
            <span className="crm-queue-item__agent"><Bot size={16} style={{ color: "#6366f1" }} /> {item.agent_name}</span>
            <code className="crm-mono">{item.action_type}</code>
            <span className={`crm-badge risk-${item.risk}`}>{item.risk || "—"}</span>
            <span className="crm-badge">{item.autonomy_mode}</span>
            <span className="crm-spacer crm-muted" style={{ fontSize: "0.72rem" }}>
              {item.created_at ? new Date(item.created_at).toLocaleString() : ""}
            </span>
          </div>
          {item.payload && <pre className="crm-pre">{JSON.stringify(item.payload, null, 2)}</pre>}
          <div className="crm-actions">
            <button disabled={actingId === item._id} onClick={() => decide(item._id, true)} className="crm-btn crm-btn--success">
              <CheckCircle2 size={16} /> Approve &amp; execute
            </button>
            <button disabled={actingId === item._id} onClick={() => decide(item._id, false)} className="crm-btn crm-btn--danger">
              <XCircle size={16} /> Reject
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}

function DecisionLog() {
  const [decisions, setDecisions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    (async () => {
      try {
        const data = await api.get("/api/ai/decisions", { limit: 200 });
        setDecisions(Array.isArray(data) ? data : []);
      } catch (e) {
        setError(e.message || "Failed to load decisions");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) return <p className="crm-muted">Loading…</p>;
  if (error) return <div className="crm-error">{error}</div>;
  if (decisions.length === 0) return <p className="crm-muted">No AI decisions logged yet.</p>;

  return (
    <div className="crm-table-wrap">
      <table className="crm-table">
        <thead>
          <tr><th>Agent</th><th>Decision</th><th>Mode</th><th>Conf.</th><th>Status</th><th>When</th></tr>
        </thead>
        <tbody>
          {decisions.map((d) => (
            <tr key={d._id}>
              <td style={{ fontWeight: 600, color: "#111827" }}>{d.agent_name}</td>
              <td>{d.decision}{d.reason && <span className="crm-muted" style={{ display: "block", fontSize: "0.72rem" }}>{d.reason}</span>}</td>
              <td><span className={`crm-badge ${d.autonomy_mode}`}>{d.autonomy_mode}</span></td>
              <td>{d.confidence != null ? `${Math.round(d.confidence * 100)}%` : "—"}</td>
              <td><span className={`crm-badge ${d.status}`}>{d.status}</span></td>
              <td className="crm-muted" style={{ fontSize: "0.72rem" }}>{d.created_at ? new Date(d.created_at).toLocaleString() : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function AIApprovals() {
  const [tab, setTab] = useState("queue");
  const tabs = [
    { key: "queue", label: "Approval Queue", icon: ListChecks },
    { key: "decisions", label: "Decision Log", icon: History },
  ];

  return (
    <div className="crm-page">
      <div className="crm-head__titles" style={{ marginBottom: "1.25rem" }}>
        <ShieldAlert size={28} style={{ color: "#4f46e5" }} />
        <div>
          <h1 className="crm-title">AI Approvals</h1>
          <p className="crm-subtitle">Review and approve AI-proposed actions. Nothing here has run yet.</p>
        </div>
      </div>

      <div className="crm-tabs">
        {tabs.map((t) => {
          const TabIcon = t.icon;
          return (
            <button key={t.key} onClick={() => setTab(t.key)} className={`crm-tab ${tab === t.key ? "active" : ""}`}>
              <TabIcon size={16} /> {t.label}
            </button>
          );
        })}
      </div>

      {tab === "queue" ? <PendingQueue /> : <DecisionLog />}
    </div>
  );
}
