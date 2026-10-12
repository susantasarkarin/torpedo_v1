import { useCallback, useEffect, useState } from "react"
import { buildApiUrl } from "../../config"
import { authFetch } from "../../utils/api"

const PANEL_ADMIN_API_PREFIX = "/api/panel-admin"

/**
 * Profiling (questionnaire v1.1) on the SFW panel — tier / module / quality
 * counts, and the brand lists the profiling questions use (insurers, banks,
 * vehicle makes, per country). Codes are permanent on the panel: renaming
 * keeps the code, removing a brand retires it, new brands get the next code.
 */

const card = {
  background: "#fff",
  border: "1px solid #e5e7eb",
  borderRadius: "10px",
  padding: "1.25rem",
  marginBottom: "1.25rem",
}
const th = { textAlign: "left", padding: "0.5rem 0.6rem", fontSize: "0.8rem", color: "#4b5563", borderBottom: "1px solid #e5e7eb", whiteSpace: "nowrap" }
const td = { padding: "0.5rem 0.6rem", fontSize: "0.875rem", color: "#1a1a1a", borderBottom: "1px solid #f3f4f6" }
const btn = { padding: "0.45rem 0.9rem", borderRadius: "8px", border: "1px solid #d1d5db", background: "#fff", cursor: "pointer", fontSize: "0.85rem" }
const primary = { ...btn, background: "#4f46e5", borderColor: "#4f46e5", color: "#fff" }

const LIST_LABELS = { insurers: "Insurers", banks: "Banks & card issuers", vehicle_makes: "Vehicle makes" }
const COUNTRY_LABELS = { IN: "India", UK: "United Kingdom", US: "United States" }
const TIER_LABELS = { null: "No tier yet", 0: "Tier 0 · exchange (Cint / CPX)", 1: "Tier 1 · specialist", 2: "Tier 2 · qual & field" }
const RULES = {
  QC_02: "Module too fast — reset",
  QC_03: "Straight-lining — reset",
  QC_04: "Personal income above household",
  QC_06: "No licence but main driver",
  QC_07: "Insurance-paid treatment, no health cover",
  QC_08: "Over-claiming (have / plan > 80%)",
  QC_09: "Under 21 with top income band",
}

async function call(path, options) {
  const res = await authFetch(buildApiUrl(`${PANEL_ADMIN_API_PREFIX}${path}`), options)
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(body.detail || `Request failed (${res.status})`)
  return body
}

function Stats({ stats }) {
  const tiers = {}
  stats.tiers.forEach((t) => {
    const k = String(t.tier)
    tiers[k] = (tiers[k] || 0) + t.members
  })
  return (
    <div style={card}>
      <h3 style={{ margin: "0 0 0.75rem", fontSize: "1rem" }}>Panel profile</h3>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "1.5rem", marginBottom: "1rem", fontSize: "0.9rem" }}>
        <span><strong>{stats.layer0Complete.toLocaleString()}</strong> core profile done</span>
        <span><strong>{stats.flowComplete.toLocaleString()}</strong> whole flow done (10 points paid)</span>
        <span><strong>{stats.attentionCheckFailed.toLocaleString()}</strong> failed the attention check</span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: "1rem" }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr><th style={th}>Tier</th><th style={th}>Members</th></tr></thead>
          <tbody>
            {["null", "0", "1", "2"].map((k) => (
              <tr key={k}><td style={td}>{TIER_LABELS[k]}</td><td style={td}>{(tiers[k] || 0).toLocaleString()}</td></tr>
            ))}
          </tbody>
        </table>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr><th style={th}>Section</th><th style={th}>Completed</th></tr></thead>
          <tbody>
            {stats.modules.map((m) => <tr key={m.key}><td style={td}>{m.title}</td><td style={td}>{m.completed.toLocaleString()}</td></tr>)}
          </tbody>
        </table>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr><th style={th}>Quality flag</th><th style={th}>Members</th></tr></thead>
          <tbody>
            {stats.flags.length === 0
              ? <tr><td style={{ ...td, color: "#6b7280" }} colSpan={2}>None</td></tr>
              : stats.flags.map((f) => <tr key={f.rule}><td style={td}>{f.rule} · {RULES[f.rule] || ""}</td><td style={td}>{f.members.toLocaleString()}</td></tr>)}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function ListEditor({ listKey, variant, items, onSaved }) {
  const [rows, setRows] = useState(items)
  const [newLabel, setNewLabel] = useState("")
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState("")

  useEffect(() => { setRows(items); setMessage("") }, [items])

  const dirty = JSON.stringify(rows) !== JSON.stringify(items)
  const update = (code, patch) => setRows((r) => r.map((x) => (x.code === code ? { ...x, ...patch } : x)))
  const add = () => {
    const label = newLabel.trim()
    if (!label) return
    setRows((r) => [...r, { code: `new-${Date.now()}`, label, active: true }])
    setNewLabel("")
  }
  const save = async () => {
    setSaving(true)
    setMessage("")
    try {
      const items = rows.map((r) => ({ code: typeof r.code === "number" ? r.code : null, label: r.label, active: r.active }))
      await call(`/profiling/lists/${listKey}/${variant}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ items }) })
      setMessage("Saved. Members see the change within a minute.")
      onSaved()
    } catch (e) {
      setMessage(e.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div style={card}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "0.5rem", marginBottom: "0.75rem" }}>
        <h3 style={{ margin: 0, fontSize: "1rem" }}>{LIST_LABELS[listKey]} · {COUNTRY_LABELS[variant]}</h3>
        <span style={{ fontSize: "0.8rem", color: "#6b7280" }}>{rows.filter((r) => r.active).length} active · "Other" and "Don't know" are added automatically</span>
      </div>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr><th style={th}>Code</th><th style={th}>Name shown to members</th><th style={th}>Active</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.code} style={{ opacity: r.active ? 1 : 0.5 }}>
                <td style={{ ...td, width: "5rem", color: "#6b7280" }}>{typeof r.code === "number" ? r.code : "new"}</td>
                <td style={td}>
                  <input value={r.label} onChange={(e) => update(r.code, { label: e.target.value })} style={{ width: "100%", padding: "0.35rem 0.5rem", border: "1px solid #d1d5db", borderRadius: "6px" }} />
                </td>
                <td style={{ ...td, width: "5rem" }}>
                  <input type="checkbox" checked={r.active} onChange={(e) => update(r.code, { active: e.target.checked })} aria-label={`${r.label} active`} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.75rem", flexWrap: "wrap" }}>
        <input value={newLabel} onChange={(e) => setNewLabel(e.target.value)} onKeyDown={(e) => e.key === "Enter" && add()} placeholder="Add a brand"
          style={{ flex: "1 1 220px", padding: "0.45rem 0.6rem", border: "1px solid #d1d5db", borderRadius: "8px" }} />
        <button type="button" style={btn} onClick={add}>Add</button>
        <button type="button" style={btn} onClick={() => setRows(items)} disabled={!dirty || saving}>Undo changes</button>
        <button type="button" style={primary} onClick={save} disabled={!dirty || saving}>{saving ? "Saving…" : "Save list"}</button>
      </div>
      {message && <p style={{ fontSize: "0.85rem", color: "#374151", margin: "0.6rem 0 0" }}>{message}</p>}
    </div>
  )
}

export default function ProfilingAdmin() {
  const [stats, setStats] = useState(null)
  const [lists, setLists] = useState(null)
  const [listKey, setListKey] = useState("insurers")
  const [variant, setVariant] = useState("IN")
  const [error, setError] = useState("")

  const load = useCallback(() => {
    setError("")
    Promise.all([call("/profiling/stats"), call("/profiling/lists")])
      .then(([s, l]) => { setStats(s); setLists(l) })
      .catch((e) => setError(e.message))
  }, [])

  useEffect(() => { load() }, [load])

  return (
    <div style={{ padding: "1.5rem", maxWidth: "1100px" }}>
      <h2 style={{ margin: "0 0 0.25rem" }}>Profiling</h2>
      <p style={{ margin: "0 0 1.25rem", color: "#4b5563", fontSize: "0.9rem" }}>
        Consumer-journey profile (questionnaire v1.1) on the SFW panel: who has finished it, which tier they are in, and the brand lists the questions use.
      </p>
      {error && <div style={{ ...card, borderColor: "#fecaca", color: "#b91c1c" }}>{error}</div>}
      {stats && <Stats stats={stats} />}
      {lists && (
        <>
          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginBottom: "0.75rem" }}>
            <label style={{ fontSize: "0.85rem" }}>List{" "}
              <select value={listKey} onChange={(e) => setListKey(e.target.value)} style={{ padding: "0.35rem", borderRadius: "6px" }}>
                {lists.lists.map((k) => <option key={k} value={k}>{LIST_LABELS[k] || k}</option>)}
              </select>
            </label>
            <label style={{ fontSize: "0.85rem" }}>Country{" "}
              <select value={variant} onChange={(e) => setVariant(e.target.value)} style={{ padding: "0.35rem", borderRadius: "6px" }}>
                {lists.variants.map((v) => <option key={v} value={v}>{COUNTRY_LABELS[v] || v}</option>)}
              </select>
            </label>
          </div>
          <ListEditor listKey={listKey} variant={variant} items={lists.data[variant][listKey]} onSaved={load} />
        </>
      )}
    </div>
  )
}
