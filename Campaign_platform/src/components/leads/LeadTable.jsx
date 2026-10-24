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
}

function resolveColumns(columns) {
  return columns.map(c => (typeof c === "string" ? { key: c, ...LEAD_COLUMNS[c] } : c))
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

function ResizableHeader({ col, width, onResize, onReset }) {
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

/**
 * selection (optional): { isSelected(id), onToggle(id), onToggleAll(), allSelected }
 */
export default function LeadTable({ leads, columns, storageKey, onRowClick, selection, onStatusUpdated }) {
  const cols = resolveColumns(columns)
  const [widths, setWidths] = useState(() => loadWidths(storageKey, cols))

  const resize = (key, width, commit) => {
    setWidths(prev => {
      const next = { ...prev, [key]: width }
      if (commit) {
        try { localStorage.setItem(storageKey, JSON.stringify(next)) } catch (_) {}
      }
      return next
    })
  }
  const reset = (key) => resize(key, cols.find(c => c.key === key).width, true)

  const checkboxWidth = selection ? 40 : 0
  const tableWidth = checkboxWidth + cols.reduce((sum, c) => sum + (widths[c.key] ?? c.width), 0)

  return (
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
              <ResizableHeader key={c.key} col={c} width={widths[c.key] ?? c.width} onResize={resize} onReset={reset} />
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
  )
}
