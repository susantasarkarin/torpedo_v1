/**
 * CRM Dashboard — overview of the canonical CRM spine (/api/crm/*).
 * Plain CSS (this app does not use Tailwind) via styles/crm-ui.css.
 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Building2, Users, UserPlus, Target, Activity as ActivityIcon, KanbanSquare } from "lucide-react";
import api from "../../utils/api";
import "../../styles/crm-ui.css";

const CARDS = [
  { key: "accounts", label: "Accounts", icon: Building2 },
  { key: "contacts", label: "Contacts", icon: Users },
  { key: "leads", label: "Leads", icon: UserPlus },
  { key: "opportunities", label: "Opportunities", icon: Target },
];

export default function CrmDashboard() {
  const [counts, setCounts] = useState({});
  const [activities, setActivities] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    (async () => {
      try {
        const [accounts, contacts, leads, opportunities, recent] = await Promise.all([
          api.get("/api/crm/accounts", { limit: 1000 }),
          api.get("/api/crm/contacts", { limit: 1000 }),
          api.get("/api/crm/leads", { limit: 1000 }),
          api.get("/api/crm/opportunities", { limit: 1000 }),
          api.get("/api/crm/activities", { limit: 12 }),
        ]);
        setCounts({
          accounts: accounts.length,
          contacts: contacts.length,
          leads: leads.length,
          opportunities: opportunities.length,
        });
        setActivities(Array.isArray(recent) ? recent : []);
      } catch (e) {
        setError(e.message || "Failed to load CRM data");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  return (
    <div className="crm-page">
      <div className="crm-head">
        <div>
          <h1 className="crm-title">CRM Dashboard</h1>
          <p className="crm-subtitle">Canonical accounts, contacts, leads and opportunities.</p>
        </div>
        <div style={{ display: "flex", gap: "0.5rem" }}>
          <Link to="/admin/crm/accounts" className="crm-btn"><Building2 size={16} /> Accounts</Link>
          <Link to="/admin/crm/pipeline" className="crm-btn crm-btn--primary"><KanbanSquare size={16} /> Pipeline</Link>
        </div>
      </div>

      {error && <div className="crm-error">{error}</div>}

      <div className="crm-cards">
        {CARDS.map((card) => {
          const CardIcon = card.icon;
          return (
            <div key={card.key} className="crm-card">
              <div className="crm-card__top">
                <span className="crm-card__label">{card.label}</span>
                <CardIcon size={18} className="crm-icon" />
              </div>
              <div className="crm-card__value">{loading ? "—" : (counts[card.key] ?? 0)}</div>
            </div>
          );
        })}
      </div>

      <div className="crm-panel">
        <div className="crm-panel__head"><ActivityIcon size={16} className="crm-icon" /> Recent activity</div>
        {loading ? (
          <p className="crm-muted" style={{ padding: "1.25rem" }}>Loading…</p>
        ) : activities.length === 0 ? (
          <p className="crm-muted" style={{ padding: "1.25rem" }}>
            No activity yet. Run the legacy migration / agents to populate the spine.
          </p>
        ) : (
          activities.map((a) => (
            <div key={a._id} className="crm-row">
              <span className="crm-mono">{a.type}</span>
              <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {a.subject || a.description || "—"}
              </span>
              <span className="crm-muted" style={{ fontSize: "0.75rem" }}>
                {a.created_at ? new Date(a.created_at).toLocaleString() : ""}
              </span>
            </div>
          ))
        )}
      </div>

      <p style={{ marginTop: "1rem" }}>
        <Link to="/admin/ai/approvals" className="crm-muted">AI Approvals queue →</Link>
      </p>
    </div>
  );
}
