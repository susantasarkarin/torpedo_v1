/**
 * Sales Leads Page
 * Shows ONLY qualified leads: Gmail contacts + cold outreach replies.
 * Reads from leads_enriched via GET /leads?qualified_only=true
 */
import { useEffect, useState, useCallback } from "react"
import { useNavigate } from "react-router-dom"
import { buildApiUrl } from "../../config"
import "./campaign/AILeads.css"

const BASKET_COLORS = {
  A: { bg: "#d1fae5", color: "#065f46", border: "#6ee7b7" },
  B: { bg: "#ede9fe", color: "#5b21b6", border: "#c4b5fd" },
  C: { bg: "#dbeafe", color: "#1e40af", border: "#93c5fd" },
  D: { bg: "#cffafe", color: "#0e7490", border: "#67e8f9" },
  E: { bg: "#f3f4f6", color: "#6b7280", border: "#d1d5db" },
}

const TIER_STYLE = {
  1: { bg: "#fef2f2", color: "#dc2626", border: "#fca5a5", icon: "🔥" },
  2: { bg: "#fffbeb", color: "#d97706", border: "#fcd34d", icon: "☀️" },
  3: { bg: "#f0f9ff", color: "#0369a1", border: "#7dd3fc", icon: "❄️" },
}

function Leads() {
  const navigate = useNavigate()
  const sessionId = localStorage.getItem("session_id")

  const [leads, setLeads] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [search, setSearch] = useState("")
  const [fitTier, setFitTier] = useState("")
  const [basket, setBasket] = useState("")
  const [source, setSource] = useState("")
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [total, setTotal] = useState(0)
  const [importingRfqs, setImportingRfqs] = useState(false)
  const [importResult, setImportResult] = useState(null)

  const fetchLeads = useCallback(async () => {
    if (!sessionId) { navigate("/login"); return }
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams({ page: String(page), limit: "50", qualified_only: "true" })
      if (search) params.set("search", search)
      if (fitTier) params.set("fit_tier", fitTier)
      if (basket) params.set("basket", basket)
      if (source) params.set("source", source)

      const res = await fetch(buildApiUrl(`/leads?${params}`), {
        headers: { Authorization: sessionId },
      })
      if (res.status === 401) { localStorage.removeItem("session_id"); navigate("/login"); return }
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || "Failed to load leads")
      setLeads(data.leads || [])
      setTotal(data.total || 0)
      setTotalPages(data.pages || 1)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [page, search, fitTier, basket, source, sessionId, navigate])

  useEffect(() => { fetchLeads() }, [fetchLeads])

  const importFromRfqs = async () => {
    if (!sessionId) return
    setImportingRfqs(true)
    setImportResult(null)
    try {
      const res = await fetch(buildApiUrl("/leads/import/from-rfqs"), {
        method: "POST",
        headers: { Authorization: sessionId, "Content-Type": "application/json" },
        body: JSON.stringify({ skip_classification: true }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || "Import failed")
      setImportResult(data)
      fetchLeads()
    } catch (e) {
      setImportResult({ error: e.message })
    } finally {
      setImportingRfqs(false)
    }
  }

  return (
    <div className="ai-leads-page">
      {/* Header */}
      <div className="page-header">
        <div className="header-left">
          <h1>Sales Leads</h1>
          <p className="subtitle">{total.toLocaleString()} qualified leads (Gmail contacts &amp; outreach replies)</p>
        </div>
        <div className="header-actions">
          <button
            className="btn btn-secondary"
            onClick={importFromRfqs}
            disabled={importingRfqs}
            title="Import all unique contacts from submitted RFQs as leads"
          >
            {importingRfqs ? "Importing…" : "⬇ Import from RFQs"}
          </button>
          <button className="btn btn-primary" onClick={() => navigate("/admin/sales/campaign/ai-leads")}>
            Open AI Database →
          </button>
        </div>
      </div>

      {/* Import result banner */}
      {importResult && (
        <div style={{
          margin: "0 0 12px",
          padding: "10px 16px",
          borderRadius: 8,
          background: importResult.error ? "#fef2f2" : "#f0fdf4",
          border: `1px solid ${importResult.error ? "#fca5a5" : "#86efac"}`,
          color: importResult.error ? "#991b1b" : "#166534",
          fontSize: "0.875rem",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}>
          {importResult.error ? (
            <span>Import failed: {importResult.error}</span>
          ) : (
            <span>
              Import complete — <strong>{importResult.inserted}</strong> new, <strong>{importResult.updated}</strong> updated, <strong>{importResult.skipped}</strong> skipped (from {importResult.total_rfq_contacts} RFQ contacts)
            </span>
          )}
          <button onClick={() => setImportResult(null)} style={{ background: "none", border: "none", cursor: "pointer", fontSize: "1rem", lineHeight: 1 }}>×</button>
        </div>
      )}

      {/* Filters */}
      <div style={{ display: "flex", gap: 12, marginBottom: 16, flexWrap: "wrap", alignItems: "center" }}>
        <input
          type="text"
          placeholder="Search name, email, company…"
          value={search}
          onChange={e => { setSearch(e.target.value); setPage(1) }}
          style={{ padding: "8px 12px", borderRadius: 8, border: "1px solid #e5e7eb", fontSize: "0.9rem", minWidth: 240 }}
        />
        <select
          value={basket}
          onChange={e => { setBasket(e.target.value); setPage(1) }}
          style={{ padding: "8px 12px", borderRadius: 8, border: "1px solid #e5e7eb", fontSize: "0.9rem" }}
        >
          <option value="">All ICP Baskets</option>
          <option value="A">A — Survey Fieldwork</option>
          <option value="B">B — Cogentix Research</option>
          <option value="C">C — BIMwave</option>
          <option value="D">D — Dual Fit</option>
          <option value="E">E — Nurture</option>
        </select>
        <select
          value={fitTier}
          onChange={e => { setFitTier(e.target.value); setPage(1) }}
          style={{ padding: "8px 12px", borderRadius: 8, border: "1px solid #e5e7eb", fontSize: "0.9rem" }}
        >
          <option value="">All Fit Tiers</option>
          <option value="1">🔥 Tier 1 — Hot</option>
          <option value="2">☀️ Tier 2 — Warm</option>
          <option value="3">❄️ Tier 3 — Cold</option>
        </select>
        <select
          value={source}
          onChange={e => { setSource(e.target.value); setPage(1) }}
          style={{ padding: "8px 12px", borderRadius: 8, border: "1px solid #e5e7eb", fontSize: "0.9rem" }}
        >
          <option value="">All Sources</option>
          <option value="gmail">✉️ Gmail</option>
          <option value="gmail_contact">📇 Gmail Contact</option>
          <option value="gmail_calendar">📅 Gmail Calendar</option>
          <option value="outreach_reply">💬 Outreach Reply</option>
        </select>
      </div>

      {error && (
        <div style={{ background: "#fef2f2", border: "1px solid #fca5a5", borderRadius: 8, padding: "12px 16px", color: "#dc2626", marginBottom: 16 }}>
          {error}
        </div>
      )}

      {/* Table */}
      <div className="classified-table-container">
        {loading ? (
          <div className="loading-container">
            <div className="loading-spinner" />
            <span>Loading leads…</span>
          </div>
        ) : leads.length === 0 ? (
          <div style={{ textAlign: "center", padding: 64, color: "#6b7280" }}>
            <p>No leads found matching your filters.</p>
          </div>
        ) : (
          <table className="data-table classified-table compact-view">
            <thead>
              <tr>
                <th>Name</th>
                <th>Email</th>
                <th>Title</th>
                <th>Company</th>
                <th>Seniority</th>
                <th>Industry</th>
                <th>Source</th>
                <th>Email Status</th>
                <th>ICP Segment</th>
                <th>Fit Tier</th>
                <th>Persona</th>
              </tr>
            </thead>
            <tbody>
              {leads.map(lead => (
                <tr
                  key={lead._id}
                  className="clickable-row"
                  onClick={() => navigate(`/admin/sales/campaign/ai-leads/${lead._id}`)}
                >
                  <td className="name-cell">
                    <span className="name-link">{lead.name || "—"}</span>
                  </td>
                  <td className="email-cell">{lead.email || "—"}</td>
                  <td>{lead.title || "—"}</td>
                  <td>{lead.company_name || "—"}</td>
                  <td><span className="badge badge-blue">{lead.seniority_level || "Unknown"}</span></td>
                  <td>{lead.company_industry || "—"}</td>
                  <td>
                    <span className={`source-badge ${(lead.source || "").replace(/_/g, "-")}`}>
                      {lead.source === "gmail" ? "✉️ Gmail" :
                       lead.source === "gmail_contact" ? "📧 Contact" :
                       lead.source === "gmail_calendar" ? "📅 Calendar" :
                       lead.source === "outreach_reply" ? "💬 Reply" :
                       lead.source || "Unknown"}
                    </span>
                  </td>
                  <td>
                    <span className={`status-badge ${(lead.email_status || "unknown").toLowerCase().replace(/ /g, "-")}`}>
                      {lead.email_status || "Unknown"}
                    </span>
                  </td>
                  {/* ICP Segment */}
                  <td>
                    {lead.classification_basket ? (() => {
                      const c = BASKET_COLORS[lead.classification_basket] || BASKET_COLORS.E
                      const bname = lead.classification_basket_name?.split(":")[0]?.split("(")[0]?.trim() || lead.classification_basket
                      return (
                        <span style={{ display: "inline-block", padding: "2px 8px", borderRadius: 9999, fontSize: "0.75rem", fontWeight: 700, background: c.bg, color: c.color, border: `1px solid ${c.border}` }}>
                          {lead.classification_basket} — {bname}
                        </span>
                      )
                    })() : <span style={{ color: "#9ca3af", fontSize: "0.75rem" }}>—</span>}
                  </td>
                  {/* Fit Tier */}
                  <td>
                    {lead.fit_tier ? (() => {
                      const s = TIER_STYLE[lead.fit_tier] || TIER_STYLE[3]
                      return (
                        <span style={{ display: "inline-block", padding: "2px 8px", borderRadius: 9999, fontSize: "0.75rem", fontWeight: 500, background: s.bg, color: s.color, border: `1px solid ${s.border}` }}>
                          {s.icon} {lead.fit_tier_label || `Tier ${lead.fit_tier}`}
                        </span>
                      )
                    })() : <span style={{ color: "#9ca3af", fontSize: "0.75rem" }}>—</span>}
                  </td>
                  {/* Persona */}
                  <td>
                    <span style={{ fontSize: "0.75rem", color: "#374151" }}>
                      {lead.persona_label || lead.persona || "—"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div style={{ display: "flex", justifyContent: "center", gap: 8, marginTop: 16, alignItems: "center" }}>
          <button
            disabled={page <= 1}
            onClick={() => setPage(p => p - 1)}
            style={{ padding: "6px 14px", borderRadius: 6, border: "1px solid #e5e7eb", cursor: page <= 1 ? "not-allowed" : "pointer", opacity: page <= 1 ? 0.5 : 1, background: "#fff" }}
          >←</button>
          <span style={{ fontSize: "0.9rem", color: "#374151" }}>Page {page} of {totalPages}</span>
          <button
            disabled={page >= totalPages}
            onClick={() => setPage(p => p + 1)}
            style={{ padding: "6px 14px", borderRadius: 6, border: "1px solid #e5e7eb", cursor: page >= totalPages ? "not-allowed" : "pointer", opacity: page >= totalPages ? 0.5 : 1, background: "#fff" }}
          >→</button>
        </div>
      )}
    </div>
  )
}

export default Leads
