/**
 * Account Timeline — master/detail over the CRM central linking layer.
 * Plain CSS (crm-ui.css). Consumes /api/crm/accounts + /api/crm/timeline/account/{id}.
 */
import { useEffect, useState, useCallback } from "react";
import { Building2, Search, Mail, Phone, FileText, CheckSquare, Clock } from "lucide-react";
import api from "../../utils/api";
import "../../styles/crm-ui.css";

const ACTIVITY_ICONS = { email: Mail, call: Phone, note: FileText, rfq_created: FileText, opportunity_won: FileText };

function ActivityRow({ act }) {
  const Icon = ACTIVITY_ICONS[act.type] || FileText;
  return (
    <li className="crm-tl-item">
      <span className="crm-tl-dot"><Icon size={14} /></span>
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
          <span className="crm-mono">{act.type}</span>
          <span style={{ fontWeight: 600, color: "#111827" }}>{act.subject || "—"}</span>
        </div>
        {act.description && <p className="crm-muted" style={{ margin: "0.15rem 0 0" }}>{act.description}</p>}
        <span className="crm-muted" style={{ fontSize: "0.72rem", display: "inline-flex", alignItems: "center", gap: "0.25rem" }}>
          <Clock size={12} /> {act.created_at ? new Date(act.created_at).toLocaleString() : ""}
        </span>
      </div>
    </li>
  );
}

export default function AccountTimeline() {
  const [accounts, setAccounts] = useState([]);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState(null);
  const [timeline, setTimeline] = useState(null);
  const [loadingAccounts, setLoadingAccounts] = useState(true);
  const [loadingTimeline, setLoadingTimeline] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    (async () => {
      try {
        const data = await api.get("/api/crm/accounts", { limit: 1000 });
        const list = Array.isArray(data) ? data : [];
        setAccounts(list);
        if (list.length) setSelected(list[0]);
      } catch (e) {
        setError(e.message || "Failed to load accounts");
      } finally {
        setLoadingAccounts(false);
      }
    })();
  }, []);

  const loadTimeline = useCallback(async (accountId) => {
    setLoadingTimeline(true);
    try {
      setTimeline(await api.get(`/api/crm/timeline/account/${accountId}`));
    } catch (e) {
      setError(e.message || "Failed to load timeline");
    } finally {
      setLoadingTimeline(false);
    }
  }, []);

  useEffect(() => { if (selected?._id) loadTimeline(selected._id); }, [selected, loadTimeline]);

  const filtered = accounts.filter((a) => (a.name || "").toLowerCase().includes(search.toLowerCase()));

  return (
    <div className="crm-page">
      <div className="crm-head">
        <div>
          <h1 className="crm-title">Account Timeline</h1>
          <p className="crm-subtitle">Activities and tasks linked to each account.</p>
        </div>
      </div>

      {error && <div className="crm-error">{error}</div>}

      <div className="crm-md">
        <div className="crm-panel">
          <div className="crm-search">
            <Search size={16} className="crm-icon" />
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search accounts…" />
          </div>
          <div className="crm-list">
            {loadingAccounts ? (
              <p className="crm-muted" style={{ padding: "1rem" }}>Loading…</p>
            ) : filtered.length === 0 ? (
              <p className="crm-muted" style={{ padding: "1rem" }}>No accounts.</p>
            ) : (
              filtered.map((a) => (
                <button key={a._id} onClick={() => setSelected(a)}
                  className={`crm-list__item ${selected?._id === a._id ? "active" : ""}`}>
                  <Building2 size={16} className="crm-icon" />
                  <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.name || "(unnamed)"}</span>
                </button>
              ))
            )}
          </div>
        </div>

        <div className="crm-panel" style={{ padding: "1rem" }}>
          {!selected ? (
            <p className="crm-muted" style={{ textAlign: "center", padding: "3rem" }}>Select an account.</p>
          ) : (
            <>
              <div style={{ borderBottom: "1px solid #f3f4f6", paddingBottom: "0.75rem", marginBottom: "1rem" }}>
                <h2 style={{ margin: 0, fontSize: "1.1rem", fontWeight: 600, color: "#111827" }}>{selected.name}</h2>
                <div style={{ marginTop: "0.25rem", display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                  {selected.account_type && <span className="crm-badge">{selected.account_type}</span>}
                  {selected.website && <span className="crm-muted" style={{ fontSize: "0.75rem" }}>{selected.website}</span>}
                </div>
              </div>

              {loadingTimeline ? (
                <p className="crm-muted">Loading timeline…</p>
              ) : (
                <>
                  {timeline?.tasks?.length > 0 && (
                    <div style={{ marginBottom: "1.25rem" }}>
                      <h3 className="crm-section-title"><CheckSquare size={16} className="crm-icon" /> Tasks ({timeline.tasks.length})</h3>
                      {timeline.tasks.map((t) => (
                        <div key={t._id} className="crm-row" style={{ border: "1px solid #f3f4f6", borderRadius: "0.4rem", marginBottom: "0.35rem" }}>
                          <span style={{ flex: 1 }}>{t.title}</span>
                          <span className="crm-badge">{t.status}</span>
                        </div>
                      ))}
                    </div>
                  )}
                  <h3 className="crm-section-title"><Clock size={16} className="crm-icon" /> Activity</h3>
                  {timeline?.activities?.length > 0 ? (
                    <ul className="crm-timeline">
                      {timeline.activities.map((act) => <ActivityRow key={act._id} act={act} />)}
                    </ul>
                  ) : (
                    <p className="crm-muted">No activity linked to this account yet.</p>
                  )}
                </>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
