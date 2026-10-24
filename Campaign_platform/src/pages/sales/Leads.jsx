/**
 * Sales Leads Page
 * Shows ONLY qualified leads: Gmail contacts + cold outreach replies.
 * Reads from leads_enriched via GET /leads?qualified_only=true
 */
import { useEffect, useState, useCallback } from "react"
import { useNavigate } from "react-router-dom"
import { buildApiUrl } from "../../config"
import { authFetch } from "../../utils/api"
import "./campaign/AILeads.css"
import LeadTable from "../../components/leads/LeadTable"

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
  const [leadStatus, setLeadStatus] = useState("")
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [total, setTotal] = useState(0)
  const [importingRfqs, setImportingRfqs] = useState(false)
  const [importResult, setImportResult] = useState(null)
  const [syncingReplies, setSyncingReplies] = useState(false)
  const [showFilters, setShowFilters] = useState(false)
  const [sort, setSort] = useState({ by: null, order: null })
  const activeFilters = [basket, fitTier, source, leadStatus].filter(Boolean).length
  const fetchLeads = useCallback(async () => {
    if (!sessionId) { navigate("/login"); return }
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams({ page: String(page), limit: "50", view: "leads" })
      if (sort.by) { params.set("sort_by", sort.by); params.set("sort_order", sort.order) }
      if (search) params.set("search", search)
      if (fitTier) params.set("fit_tier", fitTier)
      if (basket) params.set("basket", basket)
      if (source) params.set("source", source)
      if (leadStatus) params.set("lead_status", leadStatus)

      const res = await authFetch(buildApiUrl(`/leads?${params}`), {
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
  }, [page, search, fitTier, basket, source, leadStatus, sort, sessionId, navigate])

  useEffect(() => { fetchLeads() }, [fetchLeads])

  const importFromRfqs = async () => {
    if (!sessionId) return
    setImportingRfqs(true)
    setImportResult(null)
    try {
      const res = await authFetch(buildApiUrl("/leads/import/from-rfqs"), {
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

  const syncOutreachReplies = async () => {
    if (!sessionId) return
    setSyncingReplies(true)
    try {
      const res = await authFetch(buildApiUrl("/api/cold-outreach/sync-replies-to-leads"), {
        method: "POST",
        headers: { Authorization: sessionId },
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || "Sync failed")
      setImportResult({ syncResult: data })
      fetchLeads()
    } catch (e) {
      setImportResult({ error: e.message })
    } finally {
      setSyncingReplies(false)
    }
  }

  const handleStatusUpdated = (leadId, newStatus) => {
    setLeads(prev => prev.map(l => l._id === leadId ? { ...l, lead_status: newStatus } : l))
  }

  return (
    <div className="ai-leads-page">
      {/* Header */}
      <div className="page-header">
        <div className="header-left">
          <h1 className="cx-page-title">Sales Leads</h1>
          <p className="subtitle">{total.toLocaleString()} qualified leads (Gmail contacts &amp; outreach replies)</p>
        </div>
        <div className="header-actions">
          <button
            className="btn btn-secondary"
            onClick={syncOutreachReplies}
            disabled={syncingReplies}
            title="Sync all outreach reply contacts into this list"
          >
            {syncingReplies ? "Syncing…" : "🔄 Sync Outreach Replies"}
          </button>
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
            <span>Operation failed: {importResult.error}</span>
          ) : importResult.syncResult ? (
            <span>
              Sync complete — <strong>{importResult.syncResult.promoted}</strong> reply contacts promoted to leads (of {importResult.syncResult.total_replied} total replied)
            </span>
          ) : (
            <span>
              Import complete — <strong>{importResult.inserted}</strong> new, <strong>{importResult.updated}</strong> updated, <strong>{importResult.skipped}</strong> skipped (from {importResult.total_rfq_contacts} RFQ contacts)
            </span>
          )}
          <button onClick={() => setImportResult(null)} style={{ background: "none", border: "none", cursor: "pointer", fontSize: "1rem", lineHeight: 1 }}>×</button>
        </div>
      )}

      {error && (
        <div style={{ background: "#fef2f2", border: "1px solid #fca5a5", borderRadius: 8, padding: "12px 16px", color: "#dc2626", marginBottom: 16 }}>
          {error}
        </div>
      )}

      {/* Table — always mounted so the search box keeps focus while rows reload */}
      <LeadTable
        leads={leads}
        columns={["lead", "email", "company", "icp", "fit", "reply", "status"]}
        storageKey="sales_leads_col_widths"
        onRowClick={lead => navigate(`/admin/sales/campaign/ai-leads/${lead._id}`)}
        onStatusUpdated={handleStatusUpdated}
        filterPanel={showFilters && (
          <div className="lead-table-filters">
            <select value={basket} onChange={e => { setBasket(e.target.value); setPage(1) }} aria-label="ICP segment">
              <option value="">All ICP Segments</option>
              <option value="A">A — Survey Fieldwork</option>
              <option value="B">B — Cogentix Research</option>
              <option value="C">C — BIMwave</option>
            </select>
            <select value={fitTier} onChange={e => { setFitTier(e.target.value); setPage(1) }} aria-label="Fit tier">
              <option value="">All Fit Tiers</option>
              <option value="1">🔥 Tier 1 — Hot</option>
              <option value="2">☀️ Tier 2 — Warm</option>
              <option value="3">❄️ Tier 3 — Cold</option>
            </select>
            <select value={source} onChange={e => { setSource(e.target.value); setPage(1) }} aria-label="Source">
              <option value="">All Sources</option>
              <option value="gmail">✉️ Gmail</option>
              <option value="gmail_contact">📇 Gmail Contact</option>
              <option value="gmail_calendar">📅 Gmail Calendar</option>
              <option value="outreach_reply">💬 Outreach Reply</option>
            </select>
            <select value={leadStatus} onChange={e => { setLeadStatus(e.target.value); setPage(1) }} aria-label="Status">
              <option value="">All Statuses</option>
              <option value="Positive">✅ Positive</option>
              <option value="Needs Human">🙋 Needs Human</option>
              <option value="Neutral">⬜ Neutral</option>
              <option value="Nurture">🌱 Nurture</option>
              <option value="Negative">🚫 Negative</option>
            </select>
            {activeFilters > 0 && (
              <button type="button" className="toolbar-btn" onClick={() => { setBasket(""); setFitTier(""); setSource(""); setLeadStatus(""); setPage(1) }}>
                Clear
              </button>
            )}
          </div>
        )}
        sort={sort}
        onSort={(by, order) => { setSort({ by, order }); setPage(1) }}
        toolbar={
          <>
            <input
              type="text"
              placeholder="Search name, email, company…"
              value={search}
              onChange={e => { setSearch(e.target.value); setPage(1) }}
              style={{ minWidth: 240 }}
              aria-label="Search leads"
            />
            <button type="button" className={`toolbar-btn ${showFilters || activeFilters ? "active" : ""}`}
                    onClick={() => setShowFilters(v => !v)} aria-expanded={showFilters}>
              Filters ▾{activeFilters ? ` (${activeFilters})` : ""}
            </button>
            {loading && <span style={{ color: "#6f6f6f", fontSize: "0.85rem" }}>Loading…</span>}
          </>
        }
        empty={
          <div style={{ textAlign: "center", padding: 64, color: "#5c5c5c" }}>
            <p>{loading ? "Loading leads…" : "No leads found matching your filters."}</p>
          </div>
        }
      />

      {/* Pagination */}
      {totalPages > 1 && (
        <div style={{ display: "flex", justifyContent: "center", gap: 8, marginTop: 16, alignItems: "center" }}>
          <button
            disabled={page <= 1}
            onClick={() => setPage(p => p - 1)}
            style={{ padding: "6px 14px", borderRadius: 6, border: "1px solid #e8e4dc", cursor: page <= 1 ? "not-allowed" : "pointer", opacity: page <= 1 ? 0.5 : 1, background: "#fff" }}
          >←</button>
          <span style={{ fontSize: "0.9rem", color: "#4a4a4a" }}>Page {page} of {totalPages}</span>
          <button
            disabled={page >= totalPages}
            onClick={() => setPage(p => p + 1)}
            style={{ padding: "6px 14px", borderRadius: 6, border: "1px solid #e8e4dc", cursor: page >= totalPages ? "not-allowed" : "pointer", opacity: page >= totalPages ? 0.5 : 1, background: "#fff" }}
          >→</button>
        </div>
      )}
    </div>
  )
}

export default Leads
