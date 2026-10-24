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

const BASKET_COLORS = {
  A: { bg: "#dcfce7", color: "#166534", border: "#6ee7b7" },
  B: { bg: "#ede9fe", color: "#5b21b6", border: "#c4b5fd" },
  C: { bg: "#fdf4e7", color: "#d17f08", border: "#fde68a" },
  D: { bg: "#cffafe", color: "#0e7490", border: "#67e8f9" },
  E: { bg: "#f5f3ef", color: "#5c5c5c", border: "#d4cec3" },
}

const TIER_STYLE = {
  1: { bg: "#fef2f2", color: "#dc2626", border: "#fca5a5", icon: "🔥" },
  2: { bg: "#fffbeb", color: "#d97706", border: "#fcd34d", icon: "☀️" },
  3: { bg: "#fdf4e7", color: "#d17f08", border: "#7dd3fc", icon: "❄️" },
}

const LEAD_STATUS_STYLE = {
  Positive: { bg: "#dcfce7", color: "#15803d", border: "#86efac", icon: "✅" },
  "Needs Human": { bg: "#fef3c7", color: "#92400e", border: "#fcd34d", icon: "🙋" },
  Negative: { bg: "#fee2e2", color: "#b91c1c", border: "#fca5a5", icon: "🚫" },
  Neutral:  { bg: "#f5f3ef", color: "#5c5c5c", border: "#d4cec3", icon: "⬜" },
}

const STATUS_OPTIONS = ["Positive", "Needs Human", "Neutral", "Negative"]

// Basket E ("Nurture / Unqualified") is not an ICP segment — it is where a
// lead sits until it qualifies — so it shows in Status instead. Only a
// derived default: a status someone set by hand still wins.
const ICP_BASKETS = ["A", "B", "C"]
const NURTURE_STYLE = { bg: "#ecfdf5", color: "#047857", border: "#a7f3d0", icon: "🌱" }

// Column widths are dragged by the handle on each header's right edge and
// remembered per browser. Cell content wraps or clips to whatever width the
// column has, so a wider column shows more of the email, reply and segment.
const COLUMNS = [
  { key: "lead", label: "Lead", width: 200 },
  { key: "email", label: "Email", width: 220 },
  { key: "company", label: "Company", width: 170 },
  { key: "icp", label: "ICP Segment", width: 190 },
  { key: "fit", label: "Fit Tier", width: 110 },
  { key: "reply", label: "Reply / Nurture", width: 340 },
  { key: "status", label: "Status", width: 170 },
]
const MIN_COL_WIDTH = 60
const WIDTHS_KEY = "sales_leads_col_widths"

function loadWidths() {
  const defaults = Object.fromEntries(COLUMNS.map(c => [c.key, c.width]))
  try {
    const saved = JSON.parse(localStorage.getItem(WIDTHS_KEY) || "{}")
    for (const c of COLUMNS) {
      if (Number.isFinite(saved[c.key])) defaults[c.key] = Math.max(MIN_COL_WIDTH, saved[c.key])
    }
  } catch (_) {}
  return defaults
}

function saveWidths(widths) {
  try { localStorage.setItem(WIDTHS_KEY, JSON.stringify(widths)) } catch (_) {}
}

function ResizableHeader({ col, width, onResize, onReset }) {
  const startDrag = (e) => {
    e.preventDefault()
    e.stopPropagation()
    const startX = e.clientX
    const startW = width
    const move = (ev) => onResize(col.key, Math.max(MIN_COL_WIDTH, startW + ev.clientX - startX), false)
    const up = (ev) => {
      window.removeEventListener("pointermove", move)
      window.removeEventListener("pointerup", up)
      onResize(col.key, Math.max(MIN_COL_WIDTH, startW + ev.clientX - startX), true)
    }
    window.addEventListener("pointermove", move)
    window.addEventListener("pointerup", up)
  }
  return (
    <th className="resizable-th">
      <span className="resizable-th-label">{col.label}</span>
      <span
        className="col-resize-handle"
        onPointerDown={startDrag}
        onDoubleClick={() => onReset(col.key)}
        title="Drag to resize · double-click to reset"
        role="separator"
        aria-orientation="vertical"
        aria-label={`Resize ${col.label} column`}
      />
    </th>
  )
}

const NURTURE_LABEL = {
  active: "Nurturing",
  paused_new_reply: "Paused — they replied",
  completed: "Nurture done",
  stopped: "Stopped",
}

function ReplyCell({ lead }) {
  const t = lead.reply_triage
  const n = lead.nurture
  const m = lead.mail_pool
  if (!t && !n && !m) return <span style={{ color: "#6f6f6f", fontSize: "0.875rem" }}>—</span>
  const mailSummary = m ? (m.model_summary || m.last_summary || "") : ""
  const title = t
    ? `${t.reason || ""}\n\n"${(t.reply_text || "").slice(0, 400)}"`
    : m ? `${m.last_subject || ""}\n\n${mailSummary}${m.triage?.reason ? `\n\nTriage: ${m.triage.reason}` : ""}` : ""
  return (
    <div style={{ fontSize: "0.875rem", lineHeight: 1.35, whiteSpace: "normal" }} title={title}>
      {t?.reply_text && (
        <div className="clamp-3" style={{ color: "#4a4a4a" }}>
          “{t.reply_text.replace(/\s+/g, " ").slice(0, 600)}”
        </div>
      )}
      {!t && m && (
        <>
          <div className="clamp-3" style={{ color: "#4a4a4a" }}>
            {mailSummary.replace(/\s+/g, " ").slice(0, 600) || m.last_subject}
          </div>
          <div style={{ color: "#5c5c5c" }}>
            Mail: {m.messages_in} in / {m.messages_out} out
            {m.last_contact_at ? ` · last ${String(m.last_contact_at).slice(0, 10)}` : ""}
          </div>
        </>
      )}
      {n?.status && (
        <div style={{ color: n.status === "paused_new_reply" ? "#b45309" : "#e8910a", fontWeight: 600 }}>
          {NURTURE_LABEL[n.status] || n.status}
          {n.status === "active" ? ` · step ${n.step || 0}/4` : ""}
        </div>
      )}
    </div>
  )
}

function LeadStatusBadge({ lead, sessionId, onUpdated }) {
  const [saving, setSaving] = useState(false)
  const isNurture = !lead.lead_status && lead.classification_basket === "E"
  const current = lead.lead_status || (isNurture ? "Nurture" : "Neutral")
  const s = isNurture ? NURTURE_STYLE : (LEAD_STATUS_STYLE[current] || LEAD_STATUS_STYLE.Neutral)

  const handleChange = async (e) => {
    e.stopPropagation()
    const newStatus = e.target.value
    if (newStatus === current) return
    setSaving(true)
    try {
      const res = await authFetch(buildApiUrl(`/leads/${lead._id}/status`), {
        method: "PATCH",
        headers: { Authorization: sessionId, "Content-Type": "application/json" },
        body: JSON.stringify({ lead_status: newStatus }),
      })
      if (res.ok) onUpdated(lead._id, newStatus)
    } catch (_) {}
    finally { setSaving(false) }
  }

  return (
    <div style={{ display: "inline-block" }} onClick={e => e.stopPropagation()}>
      <select
        value={current}
        onChange={handleChange}
        disabled={saving}
        style={{
          padding: "2px 6px", borderRadius: 9999, fontSize: "0.875rem", fontWeight: 600,
          background: s.bg, color: s.color, border: `1px solid ${s.border}`,
          cursor: "pointer", appearance: "auto", maxWidth: "100%",
        }}
      >
        {isNurture && <option value="Nurture" disabled>{NURTURE_STYLE.icon} Nurture</option>}
        {STATUS_OPTIONS.map(opt => (
          <option key={opt} value={opt}>{LEAD_STATUS_STYLE[opt].icon} {opt}</option>
        ))}
      </select>
    </div>
  )
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
  const [leadStatus, setLeadStatus] = useState("")
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [total, setTotal] = useState(0)
  const [importingRfqs, setImportingRfqs] = useState(false)
  const [importResult, setImportResult] = useState(null)
  const [syncingReplies, setSyncingReplies] = useState(false)
  const [colWidths, setColWidths] = useState(loadWidths)

  const resizeColumn = (key, width, commit) => {
    setColWidths(prev => {
      const next = { ...prev, [key]: width }
      if (commit) saveWidths(next)
      return next
    })
  }
  const resetColumn = (key) => {
    resizeColumn(key, COLUMNS.find(c => c.key === key).width, true)
  }

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
  }, [page, search, fitTier, basket, source, leadStatus, sessionId, navigate])

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

      {/* Filters */}
      <div style={{ display: "flex", gap: 12, marginBottom: 16, flexWrap: "wrap", alignItems: "center" }}>
        <input
          type="text"
          placeholder="Search name, email, company…"
          value={search}
          onChange={e => { setSearch(e.target.value); setPage(1) }}
          style={{ padding: "8px 12px", borderRadius: 8, border: "1px solid #e8e4dc", fontSize: "0.9rem", minWidth: 240 }}
        />
        <select
          value={basket}
          onChange={e => { setBasket(e.target.value); setPage(1) }}
          style={{ padding: "8px 12px", borderRadius: 8, border: "1px solid #e8e4dc", fontSize: "0.9rem" }}
        >
          <option value="">All ICP Baskets</option>
          <option value="A">A — Survey Fieldwork</option>
          <option value="B">B — Cogentix Research</option>
          <option value="C">C — BIMwave</option>
        </select>
        <select
          value={fitTier}
          onChange={e => { setFitTier(e.target.value); setPage(1) }}
          style={{ padding: "8px 12px", borderRadius: 8, border: "1px solid #e8e4dc", fontSize: "0.9rem" }}
        >
          <option value="">All Fit Tiers</option>
          <option value="1">🔥 Tier 1 — Hot</option>
          <option value="2">☀️ Tier 2 — Warm</option>
          <option value="3">❄️ Tier 3 — Cold</option>
        </select>
        <select
          value={source}
          onChange={e => { setSource(e.target.value); setPage(1) }}
          style={{ padding: "8px 12px", borderRadius: 8, border: "1px solid #e8e4dc", fontSize: "0.9rem" }}
        >
          <option value="">All Sources</option>
          <option value="gmail">✉️ Gmail</option>
          <option value="gmail_contact">📇 Gmail Contact</option>
          <option value="gmail_calendar">📅 Gmail Calendar</option>
          <option value="outreach_reply">💬 Outreach Reply</option>
        </select>
        <select
          value={leadStatus}
          onChange={e => { setLeadStatus(e.target.value); setPage(1) }}
          style={{ padding: "8px 12px", borderRadius: 8, border: "1px solid #e8e4dc", fontSize: "0.9rem" }}
        >
          <option value="">All Statuses</option>
          <option value="Positive">✅ Positive</option>
          <option value="Needs Human">🙋 Needs Human</option>
          <option value="Neutral">⬜ Neutral</option>
          <option value="Nurture">🌱 Nurture</option>
          <option value="Negative">🚫 Negative</option>
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
          <div style={{ textAlign: "center", padding: 64, color: "#5c5c5c" }}>
            <p>No leads found matching your filters.</p>
          </div>
        ) : (
          <table
            className="data-table classified-table compact-view resizable-table"
            style={{ width: COLUMNS.reduce((sum, c) => sum + colWidths[c.key], 0) }}
          >
            <colgroup>
              {COLUMNS.map(c => <col key={c.key} style={{ width: colWidths[c.key] }} />)}
            </colgroup>
            <thead>
              <tr>
                {COLUMNS.map(c => (
                  <ResizableHeader
                    key={c.key}
                    col={c}
                    width={colWidths[c.key]}
                    onResize={resizeColumn}
                    onReset={resetColumn}
                  />
                ))}
              </tr>
            </thead>
            <tbody>
              {leads.map(lead => (
                <tr
                  key={lead._id}
                  className="clickable-row"
                  onClick={() => navigate(`/admin/sales/campaign/ai-leads/${lead._id}`)}
                >
                  {/* Lead: name, then title/seniority when filled — most
                      Gmail-sourced leads have neither yet. */}
                  <td className="name-cell">
                    <div className="name-link cell-clip" title={lead.name || ""}>{lead.name || "—"}</div>
                    {(() => {
                      const seniority = lead.seniority_level && lead.seniority_level !== "Unknown" ? lead.seniority_level : null
                      const role = [lead.title, seniority].filter(Boolean).join(" · ")
                      return role ? <div className="cell-clip" style={{ fontSize: "0.8rem", color: "#4a4a4a" }} title={role}>{role}</div> : null
                    })()}
                  </td>
                  <td className="email-cell">
                    <div className="cell-clip" title={lead.email || ""}>{lead.email || "—"}</div>
                    {(lead.email_status || "").toLowerCase() === "bounced" && (
                      <span style={{ fontSize: "0.75rem", fontWeight: 600, color: "#b91c1c" }}>Email bounced</span>
                    )}
                  </td>
                  <td>
                    <div className="cell-clip" title={lead.company_name || ""}>{lead.company_name || "—"}</div>
                    {lead.company_industry && (
                      <div className="cell-clip" style={{ fontSize: "0.8rem", color: "#6f6f6f" }} title={lead.company_industry}>{lead.company_industry}</div>
                    )}
                  </td>
                  {/* ICP Segment — A/B/C only; basket E shows as Nurture in Status. */}
                  <td>
                    {ICP_BASKETS.includes(lead.classification_basket) ? (() => {
                      const c = BASKET_COLORS[lead.classification_basket]
                      const bname = lead.classification_basket_name?.split(":")[0]?.split("(")[0]?.trim() || lead.classification_basket
                      return (
                        <span className="cell-clip" title={`${lead.classification_basket} — ${bname}`} style={{ display: "inline-block", maxWidth: "100%", padding: "2px 8px", borderRadius: 9999, fontSize: "0.875rem", fontWeight: 700, background: c.bg, color: c.color, border: `1px solid ${c.border}` }}>
                          {lead.classification_basket} — {bname}
                        </span>
                      )
                    })() : <span style={{ color: "#6f6f6f", fontSize: "0.875rem" }}>—</span>}
                  </td>
                  {/* Fit Tier */}
                  <td>
                    {lead.fit_tier ? (() => {
                      const s = TIER_STYLE[lead.fit_tier] || TIER_STYLE[3]
                      return (
                        <span className="cell-clip" style={{ display: "inline-block", maxWidth: "100%", padding: "2px 8px", borderRadius: 9999, fontSize: "0.875rem", fontWeight: 500, background: s.bg, color: s.color, border: `1px solid ${s.border}` }}>
                          {s.icon} {lead.fit_tier_label || `Tier ${lead.fit_tier}`}
                        </span>
                      )
                    })() : <span style={{ color: "#6f6f6f", fontSize: "0.875rem" }}>—</span>}
                  </td>
                  <td><ReplyCell lead={lead} /></td>
                  {/* Lead Status */}
                  <td onClick={e => e.stopPropagation()}>
                    <LeadStatusBadge
                      lead={lead}
                      sessionId={sessionId}
                      onUpdated={handleStatusUpdated}
                    />
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
