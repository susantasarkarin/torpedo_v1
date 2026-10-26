/**
 * LeadTable — the shared lead list used by Sales > Leads, Sales > Contacts
 * and the AI Database. All three read leads_enriched records, so they share
 * one set of cells; each page picks its columns and may add its own (a
 * contact's pipeline stage, row actions).
 *
 * Column widths are dragged by the handle on each header's right edge
 * (double-click resets) and remembered per browser under `storageKey`. Cell
 * content wraps or clips to whatever width the column has, so a wider column
 * shows more of the email, reply and segment.
 */
import { useState } from "react"
import { buildApiUrl } from "../../config"
import { authFetch } from "../../utils/api"
import "./LeadTable.css"

export const BASKET_COLORS = {
  A: { bg: "#dcfce7", color: "#166534", border: "#6ee7b7" },
  B: { bg: "#ede9fe", color: "#5b21b6", border: "#c4b5fd" },
  C: { bg: "#fdf4e7", color: "#d17f08", border: "#fde68a" },
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

const NURTURE_LABEL = {
  active: "Nurturing",
  paused_new_reply: "Paused — they replied",
  completed: "Nurture done",
  stopped: "Stopped",
}

const MIN_COL_WIDTH = 60
const DASH = <span className="lead-table-empty">—</span>

const pill = (s) => ({
  display: "inline-block", maxWidth: "100%", padding: "2px 8px", borderRadius: 9999,
  fontSize: "0.875rem", background: s.bg, color: s.color, border: `1px solid ${s.border}`,
})

export function ReplyCell({ lead }) {
  const t = lead.reply_triage
  const n = lead.nurture
  const m = lead.mail_pool
  if (!t && !n && !m) return DASH
  const mailSummary = m ? (m.model_summary || m.last_summary || "") : ""
  const title = t
    ? `${t.reason || ""}\n\n"${(t.reply_text || "").slice(0, 400)}"`
    : m ? `${m.last_subject || ""}\n\n${mailSummary}${m.triage?.reason ? `\n\nTriage: ${m.triage.reason}` : ""}` : ""
  return (
    <div style={{ fontSize: "0.875rem", lineHeight: 1.35 }} title={title}>
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

export function LeadStatusBadge({ lead, onUpdated }) {
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
        headers: { Authorization: localStorage.getItem("session_id"), "Content-Type": "application/json" },
        body: JSON.stringify({ lead_status: newStatus }),
      })
      if (res.ok) onUpdated?.(lead._id, newStatus)
    } catch (_) {}
    finally { setSaving(false) }
  }

  return (
    <div style={{ display: "inline-block", maxWidth: "100%" }} onClick={e => e.stopPropagation()}>
      <select
        value={current}
        onChange={handleChange}
        disabled={saving}
        style={{ ...pill(s), padding: "2px 6px", fontWeight: 600, cursor: "pointer", appearance: "auto" }}
      >
        {isNurture && <option value="Nurture" disabled>{NURTURE_STYLE.icon} Nurture</option>}
        {STATUS_OPTIONS.map(opt => (
          <option key={opt} value={opt}>{LEAD_STATUS_STYLE[opt].icon} {opt}</option>
        ))}
      </select>
    </div>
  )
}

// The built-in columns. A page passes keys from here, or its own
// { key, label, width, render } objects, in the order it wants them.
export const LEAD_COLUMNS = {
  lead: {
    label: "Lead", width: 200,
    render: (lead) => {
      const seniority = lead.seniority_level && lead.seniority_level !== "Unknown" ? lead.seniority_level : null
      const role = [lead.title, seniority].filter(Boolean).join(" · ")
      const name = lead.name || [lead.first_name, lead.last_name].filter(Boolean).join(" ")
      return (
        <>
          <div className="name-link cell-clip" title={name}>{name || "—"}</div>
          {role && <div className="cell-clip lead-table-sub" title={role}>{role}</div>}
        </>
      )
    },
  },
  email: {
    label: "Email", width: 220,
    render: (lead) => (
      <>
        <div className="cell-clip" title={lead.email || ""}>{lead.email || "—"}</div>
        {(lead.email_status || "").toLowerCase() === "bounced" && (
          <span style={{ fontSize: "0.75rem", fontWeight: 600, color: "#b91c1c" }}>Email bounced</span>
        )}
      </>
    ),
  },
  company: {
    label: "Company", width: 170,
    render: (lead) => (
      <>
        <div className="cell-clip" title={lead.company_name || ""}>{lead.company_name || "—"}</div>
        {lead.company_industry && (
          <div className="cell-clip lead-table-sub" title={lead.company_industry}>{lead.company_industry}</div>
        )}
      </>
    ),
  },
  icp: {
    label: "ICP Segment", width: 190,
    render: (lead) => {
      if (!ICP_BASKETS.includes(lead.classification_basket)) return DASH
      const code = lead.classification_basket
      const name = lead.classification_basket_name?.split(":")[0]?.split("(")[0]?.trim() || code
      return (
        <span className="cell-clip" title={`${code} — ${name}`} style={{ ...pill(BASKET_COLORS[code]), fontWeight: 700 }}>
          {code} — {name}
        </span>
      )
    },
  },
  fit: {
    label: "Fit Tier", width: 110,
    render: (lead) => {
      if (!lead.fit_tier) return DASH
      const s = TIER_STYLE[lead.fit_tier] || TIER_STYLE[3]
      return (
        <span className="cell-clip" style={{ ...pill(s), fontWeight: 500 }}>
          {s.icon} {lead.fit_tier_label || `Tier ${lead.fit_tier}`}
        </span>
      )
    },
  },
  persona: {
    label: "Persona", width: 160,
    render: (lead) => {
      const p = lead.persona_label || lead.persona
      return p ? <div className="cell-clip" title={p}>{p}</div> : DASH
    },
  },
  reply: {
    label: "Reply / Nurture", width: 340,
    render: (lead) => <ReplyCell lead={lead} />,
  },
  status: {
    label: "Status", width: 170,
    render: (lead, { onStatusUpdated }) => <LeadStatusBadge lead={lead} onUpdated={onStatusUpdated} />,
  },
  // Optional columns — off by default, switched on from the Columns menu.
  title: { label: "Title", width: 180, render: (l) => text(l.title) },
  seniority: { label: "Seniority", width: 120, render: (l) => text(l.seniority_level !== "Unknown" && l.seniority_level) },
  department: { label: "Department", width: 140, render: (l) => text(l.department) },
  industry: { label: "Industry", width: 160, render: (l) => text(l.company_industry || l.industry) },
  source: { label: "Source", width: 130, render: (l) => text(SOURCE_LABEL[l.source] || l.source) },
  email_status: { label: "Email Status", width: 130, render: (l) => text(l.email_status) },
  location: { label: "Location", width: 160, render: (l) => text([l.location, l.country].filter(Boolean).join(", ")) },
  country: { label: "Country", width: 130, render: (l) => text(l.country) },
  phone: { label: "Phone", width: 150, render: (l) => text(l.phone) },
  domain: { label: "Company Domain", width: 170, render: (l) => text(l.company_domain) },
  website: { label: "Website", width: 180, render: (l) => link(l.company_website) },
  linkedin: { label: "LinkedIn", width: 120, render: (l) => link(l.linkedin_url, "Profile ↗") },
  created: { label: "Added", width: 120, render: (l) => text(day(l.created_at)) },
  updated: { label: "Updated", width: 120, render: (l) => text(day(l.updated_at)) },
}

const SOURCE_LABEL = {
  gmail: "Gmail", gmail_contact: "Gmail Contact", gmail_calendar: "Gmail Calendar",
  gmail_reply: "Gmail Reply", outreach_reply: "Outreach Reply", web_search: "Web Search",
  websearch: "Web Search", google_search: "Google", linkedin: "LinkedIn",
  csv: "CSV Import", csv_import: "CSV Import",
}

function text(value) {
  return value ? <div className="cell-clip" title={String(value)}>{value}</div> : DASH
}

function link(url, label) {
  if (!url) return DASH
  const href = url.startsWith("http") ? url : `https://${url}`
  return (
    <a className="cell-clip" style={{ display: "block" }} href={href} target="_blank" rel="noopener noreferrer"
       onClick={e => e.stopPropagation()} title={url}>
      {label || url}
    </a>
  )
}

function day(value) {
  return value ? String(value).slice(0, 10) : ""
}

function loadVisible(storageKey, defaults, all) {
  try {
    const saved = JSON.parse(localStorage.getItem(`${storageKey}:visible`) || "null")
    if (Array.isArray(saved)) {
      const known = saved.filter(k => all.some(c => c.key === k))
      if (known.length) return known
    }
  } catch (_) {}
  return defaults
}

function loadWidths(storageKey, cols) {
  const widths = Object.fromEntries(cols.map(c => [c.key, c.width]))
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) || "{}")
    for (const c of cols) {
      if (Number.isFinite(saved[c.key])) widths[c.key] = Math.max(MIN_COL_WIDTH, saved[c.key])
    }
  } catch (_) {}
  return widths
}

function SortArrows({ col, sort, onSort }) {
  if (!onSort || col.sortable === false) return null
  const active = sort?.by === col.key ? sort.order : null
  return (
    <span className="sort-arrows" onPointerDown={e => e.stopPropagation()}>
      <button
        type="button"
        className={active === "asc" ? "active" : ""}
        onClick={() => onSort(active === "asc" ? null : col.key, active === "asc" ? null : "asc")}
        title={`Sort ${col.label} ascending`}
        aria-label={`Sort ${col.label} ascending`}
        aria-pressed={active === "asc"}
      >▲</button>
      <button
        type="button"
        className={active === "desc" ? "active" : ""}
        onClick={() => onSort(active === "desc" ? null : col.key, active === "desc" ? null : "desc")}
        title={`Sort ${col.label} descending`}
        aria-label={`Sort ${col.label} descending`}
        aria-pressed={active === "desc"}
      >▼</button>
    </span>
  )
}

function ColumnPicker({ all, visible, onChange, onReset }) {
  const [open, setOpen] = useState(false)
  const toggle = (key) => {
    const next = visible.includes(key) ? visible.filter(k => k !== key) : [...visible, key]
    if (next.length) onChange(next)
  }
  return (
    <div className="column-picker">
      <button type="button" className="column-picker-btn" onClick={() => setOpen(o => !o)} aria-expanded={open}>
        ☰ Columns ({visible.length})
      </button>
      {open && (
        <>
          <div className="column-picker-backdrop" onClick={() => setOpen(false)} />
          <div className="column-picker-menu" role="menu">
            {all.filter(c => !c.required).map(c => (
              <label key={c.key} className="column-picker-item">
                <input type="checkbox" checked={visible.includes(c.key)} onChange={() => toggle(c.key)} />
                {c.label}
              </label>
            ))}
            <button type="button" className="column-picker-reset" onClick={() => { onReset(); setOpen(false) }}>
              Reset to default
            </button>
          </div>
        </>
      )}
    </div>
  )
}

function ResizableHeader({ col, width, onResize, onReset, sort, onSort }) {
  const startDrag = (e) => {
    e.preventDefault()
    e.stopPropagation()
    const startX = e.clientX
    const move = (ev) => onResize(col.key, Math.max(MIN_COL_WIDTH, width + ev.clientX - startX), false)
    const up = (ev) => {
      window.removeEventListener("pointermove", move)
      window.removeEventListener("pointerup", up)
      onResize(col.key, Math.max(MIN_COL_WIDTH, width + ev.clientX - startX), true)
    }
    window.addEventListener("pointermove", move)
    window.addEventListener("pointerup", up)
  }
  return (
    <th className="resizable-th" aria-sort={sort?.by === col.key ? (sort.order === "asc" ? "ascending" : "descending") : undefined}>
      <div className="resizable-th-inner">
        <span className="resizable-th-label">{col.label}</span>
        <SortArrows col={col} sort={sort} onSort={onSort} />
      </div>
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

/**
 * columns:      shown by default — LEAD_COLUMNS keys or { key, label, width, render,
 *               sortable?, required? } objects (required ones cannot be hidden)
 * selection:    optional { isSelected(id), onToggle(id), onToggleAll(), allSelected }
 * sort/onSort:  optional { by, order } and onSort(key|null, "asc"|"desc"|null) — the
 *               page sorts server-side, since its rows are one page of many
 * toolbar:      optional controls rendered left of the Columns menu
 * filterPanel:  optional node shown under the toolbar (a page's collapsible filters)
 * empty:        shown instead of the table when there are no rows
 * catalog:      the optional columns the Columns menu offers (default: the lead
 *               cells); Finance lists pass their own
 */
export default function LeadTable({
  leads, columns, storageKey, onRowClick, selection, onStatusUpdated,
  sort, onSort, toolbar, filterPanel, empty, catalog = LEAD_COLUMNS,
}) {
  const defaults = columns.map(c => (typeof c === "string" ? { key: c, ...catalog[c] } : c))
  const all = [...defaults, ...Object.keys(catalog)
    .filter(k => !defaults.some(c => c.key === k))
    .map(k => ({ key: k, ...catalog[k] }))]
  const defaultKeys = defaults.map(c => c.key)
  const [visible, setVisible] = useState(() => loadVisible(storageKey, defaultKeys, all))
  const changeVisible = (keys) => {
    const withRequired = [...new Set([...keys, ...all.filter(c => c.required).map(c => c.key)])]
    setVisible(withRequired)
    try { localStorage.setItem(`${storageKey}:visible`, JSON.stringify(withRequired)) } catch (_) {}
  }
  const resetVisible = () => {
    setVisible(defaultKeys)
    try { localStorage.removeItem(`${storageKey}:visible`) } catch (_) {}
  }
  // Shown in the order of `all` (page defaults first, then optional), so a
  // column switched on later appears in a stable place.
  const cols = all.filter(c => visible.includes(c.key))
  const [widths, setWidths] = useState(() => loadWidths(storageKey, all))

  const resize = (key, width, commit) => {
    setWidths(prev => {
      const next = { ...prev, [key]: width }
      if (commit) {
        try { localStorage.setItem(storageKey, JSON.stringify(next)) } catch (_) {}
      }
      return next
    })
  }
  const reset = (key) => resize(key, all.find(c => c.key === key).width, true)

  const checkboxWidth = selection ? 40 : 0
  const tableWidth = checkboxWidth + cols.reduce((sum, c) => sum + (widths[c.key] ?? c.width), 0)

  return (
    <>
    <div className="lead-table-toolbar">
      <div className="lead-table-toolbar-left">{toolbar}</div>
      <ColumnPicker all={all} visible={visible} onChange={changeVisible} onReset={resetVisible} />
    </div>
    {filterPanel}
    {leads.length === 0 && empty ? empty : (
    <div className="lead-table-scroll">
      <table className="lead-table" style={{ width: tableWidth }}>
        <colgroup>
          {selection && <col style={{ width: checkboxWidth }} />}
          {cols.map(c => <col key={c.key} style={{ width: widths[c.key] ?? c.width }} />)}
        </colgroup>
        <thead>
          <tr>
            {selection && (
              <th className="lead-table-check">
                <input type="checkbox" checked={!!selection.allSelected} onChange={selection.onToggleAll} aria-label="Select all" />
              </th>
            )}
            {cols.map(c => (
              <ResizableHeader key={c.key} col={c} width={widths[c.key] ?? c.width} onResize={resize} onReset={reset}
                               sort={sort} onSort={onSort} />
            ))}
          </tr>
        </thead>
        <tbody>
          {leads.map(lead => (
            <tr
              key={lead._id}
              className={selection?.isSelected(lead._id) ? "selected" : ""}
              onClick={onRowClick ? () => onRowClick(lead) : undefined}
            >
              {selection && (
                <td className="lead-table-check" onClick={e => e.stopPropagation()}>
                  <input
                    type="checkbox"
                    checked={selection.isSelected(lead._id)}
                    onChange={() => selection.onToggle(lead._id)}
                    aria-label={`Select ${lead.name || lead.email}`}
                  />
                </td>
              )}
              {cols.map(c => <td key={c.key}>{c.render(lead, { onStatusUpdated })}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
    )}
    </>
  )
}
