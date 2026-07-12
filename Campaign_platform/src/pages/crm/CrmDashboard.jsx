/**
 * CRM Dashboard — overview of the canonical CRM spine (/api/crm/*) with
 * global search and the CRM notification feed.
 */
import { useEffect, useState, useRef } from "react";
import { Link } from "react-router-dom";
import {
  Building2, Users, UserPlus, Target, Activity as ActivityIcon, Search, Bell,
} from "lucide-react";
import api from "../../utils/api";
import CrmNav from "./CrmNav";
import "../../styles/crm-ui.css";

const CARDS = [
  { key: "accounts", label: "Accounts", icon: Building2, to: "/admin/crm/accounts" },
  { key: "contacts", label: "Contacts", icon: Users, to: "/admin/crm/accounts" },
  { key: "leads", label: "Leads", icon: UserPlus, to: "/admin/crm/leads" },
  { key: "opportunities", label: "Opportunities", icon: Target, to: "/admin/crm/pipeline" },
];

const RESULT_LINKS = {
  accounts: () => "/admin/crm/accounts",
  contacts: () => "/admin/crm/accounts",
  leads: () => "/admin/crm/leads",
  opportunities: () => "/admin/crm/pipeline",
};

export default function CrmDashboard() {
  const [counts, setCounts] = useState({});
  const [activities, setActivities] = useState([]);
  const [notifications, setNotifications] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState(null);
  const searchTimer = useRef(null);

  const loadNotifications = async () => {
    try {
      const n = await api.get("/api/crm/notifications", { unread: true, limit: 20 }, { cacheTTL: 0 });
      setNotifications(Array.isArray(n) ? n : []);
    } catch { /* non-fatal */ }
  };

  useEffect(() => {
    (async () => {
      try {
        const [accounts, contacts, leads, opportunities, recent] = await Promise.all([
          api.get("/api/crm/accounts", { limit: 1000 }, { cacheTTL: 0 }),
          api.get("/api/crm/contacts", { limit: 1000 }, { cacheTTL: 0 }),
          api.get("/api/crm/leads", { limit: 1000 }, { cacheTTL: 0 }),
          api.get("/api/crm/opportunities", { limit: 1000 }, { cacheTTL: 0 }),
          api.get("/api/crm/activities", { limit: 12 }, { cacheTTL: 0 }),
        ]);
        setCounts({
          accounts: accounts.length,
          contacts: contacts.length,
          leads: leads.length,
          opportunities: opportunities.length,
        });
        setActivities(Array.isArray(recent) ? recent : []);
        await loadNotifications();
      } catch (e) {
        setError(e.message || "Failed to load CRM data");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  // Debounced global search
  useEffect(() => {
    if (searchTimer.current) clearTimeout(searchTimer.current);
    if (query.trim().length < 2) { setResults(null); return; }
    searchTimer.current = setTimeout(async () => {
      try {
        setResults(await api.get("/api/crm/search", { q: query.trim() }, { cacheTTL: 0 }));
      } catch { setResults(null); }
    }, 300);
    return () => searchTimer.current && clearTimeout(searchTimer.current);
  }, [query]);

  const markRead = async (n) => {
    try {
      await api.post(`/api/crm/notifications/${n._id}/read`);
      setNotifications((prev) => prev.filter((x) => x._id !== n._id));
    } catch { /* ignore */ }
  };

  return (
    <div className="crm-page">
      <CrmNav />
      <div className="crm-head">
        <div>
          <h1 className="crm-title">CRM Dashboard</h1>
          <p className="crm-subtitle">Canonical accounts, contacts, leads and opportunities.</p>
        </div>
      </div>

      {error && <div className="crm-error">{error}</div>}

      {/* global search */}
      <div style={{ position: "relative", marginBottom: "1rem", maxWidth: 480 }}>
        <div className="crm-search" style={{ border: "1px solid #d1d5db", borderRadius: "0.45rem" }}>
          <Search size={16} className="crm-icon" />
          <input value={query} onChange={(e) => setQuery(e.target.value)}
            placeholder="Search the whole CRM — accounts, contacts, leads, deals…" />
        </div>
        {results && (
          <div style={{
            position: "absolute", top: "110%", left: 0, right: 0, zIndex: 50,
            background: "#fff", border: "1px solid #e5e7eb", borderRadius: "0.45rem",
            boxShadow: "0 12px 24px rgba(0,0,0,0.12)", maxHeight: 380, overflowY: "auto",
          }}>
            {Object.entries(results).every(([, v]) => !v.length) ? (
              <p className="crm-muted" style={{ padding: "0.8rem" }}>No matches.</p>
            ) : Object.entries(results).map(([kind, items]) => items.length > 0 && (
              <div key={kind}>
                <div style={{ padding: "0.4rem 0.8rem", fontSize: "0.7rem", fontWeight: 700, color: "#6b7280", textTransform: "uppercase", background: "#f9fafb" }}>
                  {kind}
                </div>
                {items.map((it) => (
                  <Link key={it._id} to={RESULT_LINKS[kind]?.(it) || "/admin/crm"}
                    onClick={() => setQuery("")}
                    style={{ display: "block", padding: "0.45rem 0.8rem", fontSize: "0.84rem", color: "#111827", textDecoration: "none" }}>
                    {it.name || it.title || it.email}
                    <span className="crm-muted" style={{ fontSize: "0.72rem", marginLeft: "0.4rem" }}>
                      {it.email && (it.name || it.title) ? it.email : it.company || it.stage || ""}
                    </span>
                  </Link>
                ))}
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="crm-cards">
        {CARDS.map((card) => {
          const CardIcon = card.icon;
          return (
            <Link key={card.key} to={card.to} className="crm-card" style={{ textDecoration: "none" }}>
              <div className="crm-card__top">
                <span className="crm-card__label">{card.label}</span>
                <CardIcon size={18} className="crm-icon" />
              </div>
              <div className="crm-card__value">{loading ? "—" : (counts[card.key] ?? 0)}</div>
            </Link>
          );
        })}
      </div>

      <div className="crm-md" style={{ alignItems: "start" }}>
        <div className="crm-panel">
          <div className="crm-panel__head"><ActivityIcon size={16} className="crm-icon" /> Recent activity</div>
          {loading ? (
            <p className="crm-muted" style={{ padding: "1.25rem" }}>Loading…</p>
          ) : activities.length === 0 ? (
            <p className="crm-muted" style={{ padding: "1.25rem" }}>No activity yet.</p>
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

        <div className="crm-panel">
          <div className="crm-panel__head">
            <Bell size={15} className="crm-icon" /> Notifications ({notifications.length} unread)
          </div>
          {notifications.length === 0 ? (
            <p className="crm-muted" style={{ padding: "1.25rem" }}>All caught up.</p>
          ) : notifications.map((n) => (
            <div key={n._id} className="crm-row">
              <span className="crm-mono">{n.type}</span>
              <span style={{ flex: 1, fontSize: "0.84rem" }}>{n.message}</span>
              <button className="crm-btn" style={{ padding: "0.2rem 0.5rem", fontSize: "0.72rem" }}
                onClick={() => markRead(n)}>Dismiss</button>
            </div>
          ))}
        </div>
      </div>

      <p style={{ marginTop: "1rem" }}>
        <Link to="/admin/ai/approvals" className="crm-muted">AI Approvals queue →</Link>
      </p>
    </div>
  );
}
