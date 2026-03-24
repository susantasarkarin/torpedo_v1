/**
 * Leads Page — Unified Sales Pipeline
 * Steps 11 + 13: Thread list (left) + Lead detail panel (right) + Draft review + Mail summary metrics
 *
 * Layout:
 * ┌─────────────────────────────────────────────────────────┐
 * │  Metrics bar: Open 68% · Click 24% · Bounce 3% · ...    │
 * ├──────────────────────────┬──────────────────────────────┤
 * │  Thread list (left)      │  Lead detail (right)         │
 * │  Gmail-style, sorted     │  Stage timeline              │
 * │  by last_message_at      │  Mail threads inline         │
 * │                          │  Enrichment data             │
 * │  [Avatar] Name · Co      │  Draft review panel          │
 * │  Preview...    [Opened]  │  RFQ link                    │
 * └──────────────────────────┴──────────────────────────────┘
 */
"use client"
import { useEffect, useState, useMemo, useCallback } from "react"
import { useNavigate } from "react-router-dom"
import { buildApiUrl } from "../../config"
import "./Leads.css"

// ── Pipeline stage config (matches backend LeadStage enum) ──
const STAGES = [
  { id: "new", label: "New", icon: "🆕", color: "#94a3b8" },
  { id: "email_construction", label: "Email Build", icon: "🔧", color: "#f59e0b" },
  { id: "verified", label: "Verified", icon: "✅", color: "#22c55e" },
  { id: "enriched", label: "Enriched", icon: "🧠", color: "#8b5cf6" },
  { id: "outreach_sent", label: "Sent", icon: "📧", color: "#3b82f6" },
  { id: "replied", label: "Replied", icon: "💬", color: "#14b8a6" },
  { id: "discovery", label: "Discovery", icon: "📞", color: "#f97316" },
  { id: "rfq", label: "RFQ", icon: "💰", color: "#6366f1" },
  { id: "negotiation", label: "Negotiation", icon: "🤝", color: "#ec4899" },
  { id: "won", label: "Won", icon: "🏆", color: "#16a34a" },
  { id: "lost", label: "Lost", icon: "❌", color: "#ef4444" },
]
const STAGE_MAP = Object.fromEntries(STAGES.map(s => [s.id, s]))

// Allowed transitions — must match backend state machine
const ALLOWED_TRANSITIONS = {
  new:                 ["email_construction", "verified"],
  email_construction:  ["verified", "new"],
  verified:            ["enriched"],
  enriched:            ["outreach_sent"],
  outreach_sent:       ["replied", "bounced", "enriched"],
  replied:             ["discovery", "lost"],
  discovery:           ["rfq", "lost"],
  rfq:                 ["negotiation", "lost"],
  negotiation:         ["won", "lost"],
  won:                 [],
  lost:                [],
}

const STATUS_PILLS = {
  sent:    { label: "Sent",    bg: "#e2e8f0", color: "#475569" },
  opened:  { label: "Opened",  bg: "#dcfce7", color: "#166534" },
  clicked: { label: "Clicked", bg: "#dbeafe", color: "#1e40af" },
  replied: { label: "Replied", bg: "#ccfbf1", color: "#0f766e" },
  bounced: { label: "Bounced", bg: "#fee2e2", color: "#991b1b" },
}

function getInitials(name) {
  if (!name) return "?"
  const parts = name.trim().split(/\s+/)
  return ((parts[0]?.[0] || "") + (parts[1]?.[0] || "")).toUpperCase()
}

function timeAgo(dateStr) {
  if (!dateStr) return ""
  const d = new Date(dateStr)
  const now = new Date()
  const diff = (now - d) / 1000
  if (diff < 60) return "just now"
  if (diff < 3600) return `${Math.floor(diff / 60)}m`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h`
  if (diff < 604800) return `${Math.floor(diff / 86400)}d`
  return d.toLocaleDateString()
}

// ══════════════════════════════════════
//  MAIN COMPONENT
// ══════════════════════════════════════

function Leads() {
  const navigate = useNavigate()

  // State
  const [leads, setLeads] = useState([])
  const [threads, setThreads] = useState([])
  const [stats, setStats] = useState(null)
  const [selectedLead, setSelectedLead] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [search, setSearch] = useState("")
  const [stageFilter, setStageFilter] = useState("all")
  const [trackFilter, setTrackFilter] = useState("all")
  const [draftFilter, setDraftFilter] = useState(false)
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [tab, setTab] = useState("leads") // "leads" | "threads"

  // Draft editing
  const [editSubject, setEditSubject] = useState("")
  const [editBody, setEditBody] = useState("")
  const [regenInstruction, setRegenInstruction] = useState("")
  const [showRegen, setShowRegen] = useState(false)

  // Create modal
  const [showCreate, setShowCreate] = useState(false)
  const [createForm, setCreateForm] = useState({ name: "", email: "", company: "", domain: "", source: "manual", track: "cold" })
  const [saving, setSaving] = useState(false)

  const limit = 50

  const getHeaders = useCallback(() => {
    const sid = localStorage.getItem("session_id")
    if (!sid) { navigate("/login"); return {} }
    return { "Content-Type": "application/json", Authorization: sid }
  }, [navigate])

  // ── Fetch leads ──
  const fetchLeads = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams({ page: String(page), limit: String(limit) })
      if (stageFilter !== "all") params.set("stage", stageFilter)
      if (trackFilter !== "all") params.set("track", trackFilter)
      if (draftFilter) params.set("draft_status", "pending_review")
      if (search) params.set("search", search)

      const res = await fetch(buildApiUrl(`/api/leads?${params}`), { headers: getHeaders() })
      if (res.status === 401) { localStorage.removeItem("session_id"); navigate("/login"); return }
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || "Failed to load leads")
      setLeads(data.leads || [])
      setTotal(data.total || 0)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [page, stageFilter, trackFilter, draftFilter, search, getHeaders, navigate])

  // ── Fetch mail threads ──
  const fetchThreads = useCallback(async () => {
    try {
      const res = await fetch(buildApiUrl("/api/mail/threads?limit=50"), { headers: getHeaders() })
      if (res.ok) {
        const data = await res.json()
        setThreads(data.threads || [])
      }
    } catch { /* non-critical */ }
  }, [getHeaders])

  // ── Fetch mail stats ──
  const fetchStats = useCallback(async () => {
    try {
      const res = await fetch(buildApiUrl("/api/mail/stats"), { headers: getHeaders() })
      if (res.ok) setStats(await res.json())
    } catch { /* non-critical */ }
  }, [getHeaders])

  useEffect(() => { fetchLeads() }, [fetchLeads])
  useEffect(() => { fetchThreads(); fetchStats() }, [fetchThreads, fetchStats])

  // ── Stage transition ──
  const transitionStage = async (leadId, newStage, reason) => {
    try {
      const body = { new_stage: newStage }
      if (reason) body.reason = reason
      const res = await fetch(buildApiUrl(`/api/leads/${leadId}/stage`), {
        method: "PUT", headers: getHeaders(), body: JSON.stringify(body),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || "Transition failed")
      fetchLeads()
      if (selectedLead?._id === leadId) {
        setSelectedLead(prev => prev ? { ...prev, stage: newStage } : null)
      }
    } catch (e) {
      alert(e.message)
    }
  }

  // ── Draft actions ──
  const approveDraft = async (leadId) => {
    try {
      const body = {}
      if (editSubject) body.subject = editSubject
      if (editBody) body.body = editBody
      const res = await fetch(buildApiUrl(`/api/leads/${leadId}/draft/approve`), {
        method: "PUT", headers: getHeaders(), body: JSON.stringify(body),
      })
      if (!res.ok) { const d = await res.json(); throw new Error(d.detail || "Failed") }
      fetchLeads()
      setSelectedLead(prev => prev ? { ...prev, email_draft: { ...prev.email_draft, status: "approved" } } : null)
    } catch (e) { alert(e.message) }
  }

  const discardDraft = async (leadId) => {
    try {
      const res = await fetch(buildApiUrl(`/api/leads/${leadId}/draft/discard`), {
        method: "PUT", headers: getHeaders(),
      })
      if (!res.ok) { const d = await res.json(); throw new Error(d.detail || "Failed") }
      fetchLeads()
      setSelectedLead(prev => prev ? { ...prev, email_draft: { ...prev.email_draft, status: "discarded" } } : null)
    } catch (e) { alert(e.message) }
  }

  const regenerateDraft = async (leadId) => {
    try {
      const res = await fetch(buildApiUrl(`/api/leads/${leadId}/draft/regenerate`), {
        method: "POST", headers: getHeaders(),
        body: JSON.stringify({ instruction: regenInstruction || null }),
      })
      if (!res.ok) { const d = await res.json(); throw new Error(d.detail || "Failed") }
      setShowRegen(false)
      setRegenInstruction("")
      alert("Draft regeneration queued. Refresh in a moment.")
    } catch (e) { alert(e.message) }
  }

  const bulkApprove = async () => {
    const pending = leads.filter(l => l.email_draft?.status === "pending_review")
    if (!pending.length) return
    if (!window.confirm(`Approve ${pending.length} drafts?`)) return
    try {
      const res = await fetch(buildApiUrl("/api/leads/drafts/bulk-approve"), {
        method: "POST", headers: getHeaders(),
        body: JSON.stringify(pending.map(l => l._id)),
      })
      if (!res.ok) { const d = await res.json(); throw new Error(d.detail || "Failed") }
      fetchLeads()
    } catch (e) { alert(e.message) }
  }

  // ── Archive lead ──
  const archiveLead = async (leadId) => {
    if (!window.confirm("Archive this lead?")) return
    try {
      const res = await fetch(buildApiUrl(`/api/leads/${leadId}`), {
        method: "DELETE", headers: getHeaders(),
      })
      if (!res.ok) { const d = await res.json(); throw new Error(d.detail || "Failed") }
      fetchLeads()
      if (selectedLead?._id === leadId) setSelectedLead(null)
    } catch (e) { alert(e.message) }
  }

  // ── Create lead ──
  const createLead = async () => {
    if (!createForm.name.trim()) { alert("Name is required"); return }
    setSaving(true)
    try {
      const res = await fetch(buildApiUrl("/api/leads"), {
        method: "POST", headers: getHeaders(),
        body: JSON.stringify(createForm),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || "Create failed")
      setShowCreate(false)
      setCreateForm({ name: "", email: "", company: "", domain: "", source: "manual", track: "cold" })
      fetchLeads()
    } catch (e) { alert(e.message) }
    finally { setSaving(false) }
  }

  // ── Select a lead ──
  const selectLead = (lead) => {
    setSelectedLead(lead)
    if (lead.email_draft) {
      setEditSubject(lead.email_draft.subject || "")
      setEditBody(lead.email_draft.body || "")
    } else {
      setEditSubject("")
      setEditBody("")
    }
    setShowRegen(false)
  }

  // ── Select from thread → load full lead ──
  const selectThread = async (thread) => {
    try {
      const res = await fetch(buildApiUrl(`/api/leads/${thread.lead_id}`), { headers: getHeaders() })
      if (res.ok) {
        const lead = await res.json()
        selectLead(lead)
        setTab("leads")
      }
    } catch { /* ignore */ }
  }

  // ── Computed ──
  const pendingDrafts = useMemo(() => leads.filter(l => l.email_draft?.status === "pending_review"), [leads])
  const totalPages = Math.ceil(total / limit)

  // ═══════════ RENDER ═══════════

  return (
    <div className="leads-page">
      {/* METRICS BAR */}
      <div className="metrics-bar">
        {stats ? (
          <>
            <MetricPill label="Open Rate" value={`${stats.open_rate}%`} color="#22c55e" />
            <MetricPill label="Click Rate" value={`${stats.click_rate}%`} color="#3b82f6" />
            <MetricPill label="Bounce Rate" value={`${stats.bounce_rate}%`} color="#ef4444" />
            <MetricPill label="Reply Rate" value={`${stats.reply_rate}%`} color="#14b8a6" />
            <MetricPill label="Deliverability" value={`${stats.deliverability_score}`} color="#8b5cf6" />
          </>
        ) : (
          <span style={{ color: "#94a3b8", fontSize: 13 }}>Loading metrics…</span>
        )}
        <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          {pendingDrafts.length > 0 && (
            <button className="btn-sm btn-teal" onClick={bulkApprove}>
              ✉ Approve all ({pendingDrafts.length})
            </button>
          )}
          <button className="btn-sm btn-primary" onClick={() => setShowCreate(true)}>+ New Lead</button>
          <button className="btn-sm btn-outline" onClick={() => navigate("/admin/sales/leads/import")}>📥 Import</button>
        </div>
      </div>

      {/* TOOLBAR */}
      <div className="toolbar">
        <div className="tab-bar">
          <button className={`tab-btn ${tab === "leads" ? "active" : ""}`} onClick={() => setTab("leads")}>
            Leads ({total})
          </button>
          <button className={`tab-btn ${tab === "threads" ? "active" : ""}`} onClick={() => setTab("threads")}>
            Mail Threads ({threads.length})
          </button>
        </div>
        <input
          className="search-box"
          type="text"
          placeholder="Search by name, email, company…"
          value={search}
          onChange={e => { setSearch(e.target.value); setPage(1) }}
        />
        <select className="filter-select" value={stageFilter} onChange={e => { setStageFilter(e.target.value); setPage(1) }}>
          <option value="all">All stages</option>
          {STAGES.map(s => <option key={s.id} value={s.id}>{s.icon} {s.label}</option>)}
        </select>
        <select className="filter-select" value={trackFilter} onChange={e => { setTrackFilter(e.target.value); setPage(1) }}>
          <option value="all">All tracks</option>
          <option value="inbound">🟢 Inbound</option>
          <option value="cold">🔵 Cold</option>
          <option value="reengagement">🟠 Re-engagement</option>
        </select>
        <label className="filter-check">
          <input type="checkbox" checked={draftFilter} onChange={e => { setDraftFilter(e.target.checked); setPage(1) }} />
          Pending drafts
        </label>
      </div>

      {error && <div className="error-bar">{error}</div>}

      {/* MAIN SPLIT LAYOUT */}
      <div className="split-layout">
        {/* LEFT: List panel */}
        <div className="list-panel">
          {loading ? (
            <div className="empty-msg">Loading…</div>
          ) : tab === "leads" ? (
            <>
              {leads.map(lead => (
                <div
                  key={lead._id}
                  className={`list-row ${selectedLead?._id === lead._id ? "selected" : ""}`}
                  onClick={() => selectLead(lead)}
                >
                  <div className="avatar" style={{ background: STAGE_MAP[lead.stage]?.color || "#94a3b8" }}>
                    {getInitials(lead.name)}
                  </div>
                  <div className="row-body">
                    <div className="row-top">
                      <span className="row-name">{lead.name || "—"}</span>
                      <span className="row-company">{lead.company ? `· ${lead.company}` : ""}</span>
                      {lead.email_draft?.status === "pending_review" && <span className="draft-badge">Draft</span>}
                    </div>
                    <div className="row-bottom">
                      <span className="row-email">{lead.email || "no email"}</span>
                      <span className="row-stage-pill" style={{ background: STAGE_MAP[lead.stage]?.color || "#94a3b8" }}>
                        {STAGE_MAP[lead.stage]?.label || lead.stage}
                      </span>
                    </div>
                  </div>
                  <div className="row-time">{timeAgo(lead.updated_at || lead.created_at)}</div>
                </div>
              ))}
              {leads.length === 0 && <div className="empty-msg">No leads found. Add one or adjust filters.</div>}
              {totalPages > 1 && (
                <div className="pagination">
                  <button disabled={page <= 1} onClick={() => setPage(p => p - 1)}>←</button>
                  <span>{page} / {totalPages}</span>
                  <button disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>→</button>
                </div>
              )}
            </>
          ) : (
            /* THREADS TAB */
            <>
              {threads.map(thread => {
                const pill = STATUS_PILLS[thread.latest_status] || STATUS_PILLS.sent
                return (
                  <div
                    key={thread.lead_id}
                    className={`list-row ${selectedLead?._id === thread.lead_id ? "selected" : ""}`}
                    onClick={() => selectThread(thread)}
                  >
                    <div className="avatar" style={{ background: pill.color }}>
                      {getInitials(thread.name)}
                    </div>
                    <div className="row-body">
                      <div className="row-top">
                        <span className="row-name">{thread.name}</span>
                        <span className="row-company">{thread.company ? `· ${thread.company}` : ""}</span>
                      </div>
                      <div className="row-bottom">
                        <span className="row-preview">{thread.subject_preview || thread.body_preview || "—"}</span>
                      </div>
                    </div>
                    <div className="row-meta">
                      <span className="status-pill" style={{ background: pill.bg, color: pill.color }}>{pill.label}</span>
                      <span className="row-time">{timeAgo(thread.last_message_at)}</span>
                    </div>
                  </div>
                )
              })}
              {threads.length === 0 && <div className="empty-msg">No mail threads yet.</div>}
            </>
          )}
        </div>

        {/* RIGHT: Detail panel */}
        <div className="detail-panel">
          {selectedLead ? (
            <>
              {/* Header */}
              <div className="detail-header">
                <div>
                  <h2 className="detail-name">{selectedLead.name}</h2>
                  <p className="detail-sub">{selectedLead.email}{selectedLead.company ? ` | ${selectedLead.company}` : ""}</p>
                </div>
                <button className="btn-sm btn-danger" onClick={() => archiveLead(selectedLead._id)}>Archive</button>
              </div>

              {/* Stage Timeline */}
              <div className="stage-timeline">
                {STAGES.filter(s => s.id !== "lost").map(s => {
                  const idx = STAGES.findIndex(x => x.id === s.id)
                  const currentIdx = STAGES.findIndex(x => x.id === selectedLead.stage)
                  const isCurrent = s.id === selectedLead.stage
                  const isPast = idx < currentIdx && selectedLead.stage !== "lost"
                  return (
                    <div key={s.id} className={`stage-dot ${isCurrent ? "current" : isPast ? "past" : "future"}`} title={s.label}>
                      <span className="dot" style={{ background: isCurrent || isPast ? s.color : "#e2e8f0" }}>{s.icon}</span>
                      <span className="dot-label">{s.label}</span>
                    </div>
                  )
                })}
              </div>

              {/* Stage transition actions */}
              {(ALLOWED_TRANSITIONS[selectedLead.stage] || []).length > 0 && (
                <div className="detail-section">
                  <h4>Move Stage</h4>
                  <div className="stage-actions">
                    {(ALLOWED_TRANSITIONS[selectedLead.stage] || []).map(ns => (
                      <button
                        key={ns}
                        className="btn-sm"
                        style={{ background: STAGE_MAP[ns]?.color || "#e2e8f0", color: "#fff", border: "none" }}
                        onClick={() => {
                          if (ns === "lost") {
                            const reason = prompt("Reason for loss?")
                            if (!reason) return
                            transitionStage(selectedLead._id, ns, reason)
                          } else {
                            transitionStage(selectedLead._id, ns)
                          }
                        }}
                      >
                        → {STAGE_MAP[ns]?.label || ns}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Enrichment Data */}
              {selectedLead.enrichment?.status === "done" && (
                <div className="detail-section">
                  <h4>🧠 Enrichment</h4>
                  <div className="info-grid">
                    {selectedLead.enrichment.company_size && <InfoRow label="Company Size" value={selectedLead.enrichment.company_size} />}
                    {selectedLead.intent_score != null && <InfoRow label="Intent Score" value={`${selectedLead.intent_score}/100`} />}
                    {selectedLead.enrichment.pain_points?.length > 0 && <InfoRow label="Pain Points" value={selectedLead.enrichment.pain_points.join(", ")} />}
                    {selectedLead.enrichment.hook && <InfoRow label="Hook" value={selectedLead.enrichment.hook} />}
                    {selectedLead.enrichment.news && <InfoRow label="News" value={selectedLead.enrichment.news} />}
                  </div>
                </div>
              )}

              {/* Draft Review Panel */}
              {selectedLead.email_draft?.status === "pending_review" && (
                <div className="detail-section draft-section">
                  <h4>📝 Draft Review</h4>
                  <div className="draft-context">
                    <small>Track: {selectedLead.track} | Score: {selectedLead.intent_score ?? "—"}</small>
                  </div>
                  <label className="field-label">Subject</label>
                  <input className="draft-input" value={editSubject} onChange={e => setEditSubject(e.target.value)} />
                  <label className="field-label">Body</label>
                  <textarea className="draft-textarea" rows={6} value={editBody} onChange={e => setEditBody(e.target.value)} />
                  <div className="draft-actions">
                    <button className="btn-sm btn-green" onClick={() => approveDraft(selectedLead._id)}>✓ Approve & Send</button>
                    <button className="btn-sm btn-outline" onClick={() => setShowRegen(!showRegen)}>🔄 Regenerate</button>
                    <button className="btn-sm btn-danger" onClick={() => discardDraft(selectedLead._id)}>✕ Discard</button>
                  </div>
                  {showRegen && (
                    <div className="regen-box">
                      <input className="draft-input" placeholder="Any specific instructions? (optional)" value={regenInstruction} onChange={e => setRegenInstruction(e.target.value)} />
                      <button className="btn-sm btn-primary" onClick={() => regenerateDraft(selectedLead._id)}>Submit</button>
                    </div>
                  )}
                </div>
              )}

              {/* Lead Info */}
              <div className="detail-section">
                <h4>Details</h4>
                <div className="info-grid">
                  <InfoRow label="Source" value={selectedLead.source} />
                  <InfoRow label="Track" value={selectedLead.track} />
                  <InfoRow label="Domain" value={selectedLead.domain || "—"} />
                  <InfoRow label="Email Status" value={selectedLead.email_status} />
                  {selectedLead.contactus_message && <InfoRow label="Form Message" value={selectedLead.contactus_message} />}
                  {selectedLead.rfq_id && (
                    <div className="info-row">
                      <span className="info-label">RFQ</span>
                      <button className="link-btn" onClick={() => navigate("/admin/sales/rfq")}>View RFQ →</button>
                    </div>
                  )}
                  <InfoRow label="Created" value={new Date(selectedLead.created_at).toLocaleString()} />
                  <InfoRow label="Updated" value={new Date(selectedLead.updated_at).toLocaleString()} />
                  {selectedLead.last_contacted && <InfoRow label="Last Contact" value={new Date(selectedLead.last_contacted).toLocaleString()} />}
                </div>
              </div>
            </>
          ) : (
            <div className="empty-detail">
              <div className="empty-icon">📋</div>
              <p>Select a lead or thread to view details</p>
            </div>
          )}
        </div>
      </div>

      {/* CREATE LEAD MODAL */}
      {showCreate && (
        <div className="modal-overlay" onClick={e => { if (e.target === e.currentTarget) setShowCreate(false) }}>
          <div className="modal-box">
            <div className="modal-hdr">
              <h3>Add New Lead</h3>
              <button className="close-btn" onClick={() => setShowCreate(false)}>×</button>
            </div>
            <div className="modal-body-inner">
              <label className="field-label">Name *</label>
              <input className="form-input" value={createForm.name} onChange={e => setCreateForm(f => ({ ...f, name: e.target.value }))} />
              <label className="field-label">Email</label>
              <input className="form-input" type="email" value={createForm.email} onChange={e => setCreateForm(f => ({ ...f, email: e.target.value }))} />
              <label className="field-label">Company</label>
              <input className="form-input" value={createForm.company} onChange={e => setCreateForm(f => ({ ...f, company: e.target.value }))} />
              <label className="field-label">Domain</label>
              <input className="form-input" placeholder="e.g. acme.com" value={createForm.domain} onChange={e => setCreateForm(f => ({ ...f, domain: e.target.value }))} />
              <div style={{ display: "flex", gap: 12 }}>
                <div style={{ flex: 1 }}>
                  <label className="field-label">Source</label>
                  <select className="form-input" value={createForm.source} onChange={e => setCreateForm(f => ({ ...f, source: e.target.value }))}>
                    <option value="manual">Manual</option>
                    <option value="form">Contact Form</option>
                    <option value="csv">CSV Import</option>
                    <option value="google_search">Google Search</option>
                  </select>
                </div>
                <div style={{ flex: 1 }}>
                  <label className="field-label">Track</label>
                  <select className="form-input" value={createForm.track} onChange={e => setCreateForm(f => ({ ...f, track: e.target.value }))}>
                    <option value="cold">Cold</option>
                    <option value="inbound">Inbound</option>
                    <option value="reengagement">Re-engagement</option>
                  </select>
                </div>
              </div>
            </div>
            <div className="modal-ft">
              <button className="btn-sm btn-outline" onClick={() => setShowCreate(false)}>Cancel</button>
              <button className="btn-sm btn-primary" disabled={saving} onClick={createLead}>
                {saving ? "Saving…" : "Create Lead"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Sub-components ──

function MetricPill({ label, value, color }) {
  return (
    <div className="metric-pill">
      <span className="metric-value" style={{ color }}>{value}</span>
      <span className="metric-label">{label}</span>
    </div>
  )
}

function InfoRow({ label, value }) {
  return (
    <div className="info-row">
      <span className="info-label">{label}</span>
      <span className="info-value">{value}</span>
    </div>
  )
}

export default Leads
