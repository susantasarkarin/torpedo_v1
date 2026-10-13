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
  QC_12: "QUAL_09 pasted in, not typed",
}
const RESEARCH = { 1: "Online 1:1", 2: "Online group", 3: "In-person group", 4: "Home visit", 5: "Diary", 6: "Mobile ethnography", 7: "Product test", 8: "Store accompaniment", 9: "Phone", 10: "Mystery shopping" }

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
        <span><strong>{(stats.mysteryShoppers || 0).toLocaleString()}</strong> mystery shoppers ready</span>
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

// Tier 2 needs checks only people can make: QUAL_09 articulation (1-5),
// identity (KYC provider or recruiter video call — no ID document is stored),
// and for mystery shopping the MYS_07 practice evaluation.
function QualReview({ onChanged }) {
  const [rows, setRows] = useState(null)
  const [showAll, setShowAll] = useState(false)
  const [busy, setBusy] = useState("")
  const [error, setError] = useState("")

  const load = useCallback(() => {
    call(`/profiling/qual-review?all=${showAll ? 1 : 0}`).then((d) => setRows(d.members)).catch((e) => setError(e.message))
  }, [showAll])
  useEffect(() => { load() }, [load])

  const update = async (userId, patch) => {
    setBusy(userId)
    setError("")
    try {
      await call(`/profiling/qual-review/${userId}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch) })
      load()
      onChanged()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy("")
    }
  }

  return (
    <div style={card}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "0.5rem", marginBottom: "0.75rem" }}>
        <h3 style={{ margin: 0, fontSize: "1rem" }}>Qual & field review (Tier 2)</h3>
        <label style={{ fontSize: "0.85rem" }}><input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} /> Show reviewed members too</label>
      </div>
      {error && <p style={{ color: "#b91c1c", fontSize: "0.85rem" }}>{error}</p>}
      {!rows ? <p style={{ color: "#6b7280", fontSize: "0.875rem" }}>Loading…</p> : rows.length === 0 ? (
        <p style={{ color: "#6b7280", fontSize: "0.875rem", margin: 0 }}>Nobody is waiting. Tier 1 members appear here once they answer the qual questions.</p>
      ) : rows.map((m) => (
        <div key={m.userId} style={{ borderTop: "1px solid #f3f4f6", padding: "0.9rem 0" }}>
          <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: "0.5rem" }}>
            <strong>{m.name || m.email} <span style={{ fontWeight: 400, color: "#6b7280" }}>· {m.email} · {m.country} · Tier {m.tier ?? "—"}{m.mysteryShopper ? " · mystery shopper" : ""}</span></strong>
            <span style={{ fontSize: "0.8rem", color: "#6b7280" }}>
              Camera / mic: {m.techCheck ? `${m.techCheck.camera ? "✓" : "✗"} / ${m.techCheck.mic ? "✓" : "✗"}` : "not needed"}
              {m.openFlags.length ? ` · open flags: ${m.openFlags.join(", ")}` : ""}
            </span>
          </div>
          <p style={{ fontSize: "0.8rem", color: "#4b5563", margin: "0.3rem 0" }}>Would do: {m.researchTypes.map((c) => RESEARCH[c] || c).join(", ")}</p>
          <blockquote style={{ margin: "0.4rem 0", padding: "0.5rem 0.75rem", background: "#f9fafb", borderLeft: "3px solid #c7d2fe", fontSize: "0.875rem", whiteSpace: "pre-wrap" }}>{m.qual09}</blockquote>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem", alignItems: "center", fontSize: "0.85rem" }}>
            <span>Articulation:{" "}
              {[1, 2, 3, 4, 5].map((n) => (
                <button key={n} type="button" disabled={busy === m.userId} onClick={() => update(m.userId, { articulation: n })}
                  style={{ ...btn, padding: "0.25rem 0.55rem", marginRight: "0.2rem", ...(m.qual.articulation === n ? { background: "#4f46e5", color: "#fff", borderColor: "#4f46e5" } : {}) }}>{n}</button>
              ))}
            </span>
            <span>Identity:{" "}
              {m.qual.idVerifiedAt ? <span style={{ color: "#047857" }}>verified ({m.qual.idMethod})</span> : (
                <>
                  <button type="button" style={btn} disabled={busy === m.userId} onClick={() => update(m.userId, { idVerified: true, idMethod: "recruiter video check" })}>Verified by video call</button>{" "}
                  <button type="button" style={btn} disabled={busy === m.userId} onClick={() => update(m.userId, { idVerified: true, idMethod: "KYC provider" })}>Verified by KYC provider</button>
                </>
              )}
            </span>
            {m.researchTypes.includes(10) && (
              <span>Mystery practice:{" "}
                {["pass", "fail"].map((r) => (
                  <button key={r} type="button" disabled={busy === m.userId} onClick={() => update(m.userId, { mysPractice: r })}
                    style={{ ...btn, padding: "0.25rem 0.6rem", marginRight: "0.2rem", ...(m.qual.mysPractice === r ? { background: r === "pass" ? "#047857" : "#b91c1c", color: "#fff" } : {}) }}>{r}</button>
                ))}
              </span>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

function FlagReview({ onChanged }) {
  const [rows, setRows] = useState(null)
  const [error, setError] = useState("")
  const load = useCallback(() => { call("/profiling/flags").then((d) => setRows(d.members)).catch((e) => setError(e.message)) }, [])
  useEffect(() => { load() }, [load])
  const clear = async (userId, rule) => {
    try {
      await call(`/profiling/flags/${userId}/${rule}/clear`, { method: "POST" })
      load()
      onChanged()
    } catch (e) {
      setError(e.message)
    }
  }
  return (
    <div style={card}>
      <h3 style={{ margin: "0 0 0.75rem", fontSize: "1rem" }}>Quality flags to review</h3>
      <p style={{ margin: "0 0 0.75rem", fontSize: "0.8rem", color: "#6b7280" }}>Open consistency flags keep a member out of Tier 1. Clear a flag once you have checked the answers are genuine.</p>
      {error && <p style={{ color: "#b91c1c", fontSize: "0.85rem" }}>{error}</p>}
      {!rows ? <p style={{ color: "#6b7280", fontSize: "0.875rem" }}>Loading…</p> : rows.length === 0 ? (
        <p style={{ color: "#6b7280", fontSize: "0.875rem", margin: 0 }}>No open flags.</p>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr><th style={th}>Member</th><th style={th}>Country</th><th style={th}>Flag</th><th style={th}>Raised</th><th style={th} /></tr></thead>
            <tbody>
              {rows.flatMap((m) => m.flags.map((f) => (
                <tr key={`${m.userId}-${f.rule}-${f.at}`}>
                  <td style={td}>{m.name || m.email}<div style={{ fontSize: "0.75rem", color: "#6b7280" }}>{m.email}</div></td>
                  <td style={td}>{m.country}</td>
                  <td style={td}>{f.rule} · {RULES[f.rule] || ""}{f.module ? ` (${f.module})` : ""}</td>
                  <td style={td}>{f.at ? new Date(f.at).toLocaleDateString() : ""}</td>
                  <td style={td}>{["QC_02", "QC_03"].includes(f.rule) ? <span style={{ color: "#6b7280", fontSize: "0.8rem" }}>answers were reset</span> : <button type="button" style={btn} onClick={() => clear(m.userId, f.rule)}>Clear</button>}</td>
                </tr>
              )))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

const RULE_LABEL = {
  QC_02: "Section too fast (reset)",
  QC_02Q: "Quick start too fast",
  QC_03: "Same answer on every row (reset)",
  QC_03Q: "First option every time (Quick start)",
}

// Profile quality: speeders, straight-liners and dropouts across all profiles.
function QualityReport() {
  const [data, setData] = useState(null)
  const [error, setError] = useState("")
  useEffect(() => { call("/profiling/quality").then(setData).catch((e) => setError(e.message)) }, [])
  const tile = (label, value, tone) => (
    <div style={{ background: "#f9fafb", borderRadius: "8px", padding: "0.75rem 1rem", minWidth: "150px", flex: "1 1 150px" }}>
      <p style={{ fontSize: "1.5rem", fontWeight: 700, color: tone, margin: 0 }}>{value}</p>
      <p style={{ fontSize: "0.8rem", color: "#4b5563", margin: 0 }}>{label}</p>
    </div>
  )
  const memberTable = (rows) => (
    <div style={{ overflowX: "auto", maxHeight: "260px", overflowY: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead><tr><th style={th}>Member</th><th style={th}>Check</th><th style={th}>Section</th><th style={th}>When</th></tr></thead>
        <tbody>
          {rows.map((m, i) => (
            <tr key={`${m.email}-${m.rule}-${i}`}>
              <td style={td}>{m.name || m.email}<div style={{ fontSize: "0.75rem", color: "#6b7280" }}>{m.email} · {m.panelistId}</div></td>
              <td style={td}>{RULE_LABEL[m.rule] || m.rule}{m.count > 1 ? ` ×${m.count}` : ""}</td>
              <td style={td}>{m.section || "—"}</td>
              <td style={td}>{m.at ? new Date(m.at).toLocaleDateString() : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
  return (
    <div style={card}>
      <h3 style={{ margin: "0 0 0.25rem", fontSize: "1rem" }}>Profile quality</h3>
      <p style={{ margin: "0 0 0.9rem", fontSize: "0.8rem", color: "#6b7280" }}>
        Speeders and straight-liners are caught while members answer (sections are reset and asked again; Quick start is flagged).
        Dropouts are members who started and haven't answered for {data?.thresholds?.dropoutHours || 24} hours.
      </p>
      {error && <p style={{ color: "#b91c1c", fontSize: "0.85rem" }}>{error}</p>}
      {!data ? <p style={{ color: "#6b7280", fontSize: "0.875rem" }}>Loading…</p> : (
        <>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem", marginBottom: "1rem" }}>
            {tile("Speeders", data.speeders.count, "#b45309")}
            {tile("Straight-liners", data.straightLiners.count, "#b45309")}
            {tile("Quick start dropouts", data.dropouts.quickStart, "#b91c1c")}
            {tile("Section dropouts", data.dropouts.sections, "#b91c1c")}
            {tile("Older members — Quick start not started", data.dropouts.quickStartNotStarted || 0, "#4b5563")}
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: "1rem" }}>
            <div>
              <p style={{ fontWeight: 700, fontSize: "0.85rem", margin: "0 0 0.4rem" }}>Where Quick start dropouts stopped (started, then left)</p>
              {data.dropouts.quickStartStops.length === 0 ? <p style={{ fontSize: "0.85rem", color: "#6b7280" }}>None</p> : (
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead><tr><th style={th}>Question</th><th style={th}>Members</th></tr></thead>
                  <tbody>{data.dropouts.quickStartStops.map((q) => <tr key={q.id}><td style={td}>{q.text}</td><td style={td}>{q.count}</td></tr>)}</tbody>
                </table>
              )}
            </div>
            <div>
              <p style={{ fontWeight: 700, fontSize: "0.85rem", margin: "0 0 0.4rem" }}>Sections left unfinished</p>
              {data.dropouts.sectionStops.length === 0 ? <p style={{ fontSize: "0.85rem", color: "#6b7280" }}>None</p> : (
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead><tr><th style={th}>Section</th><th style={th}>Members</th></tr></thead>
                  <tbody>{data.dropouts.sectionStops.map((s) => <tr key={s.key}><td style={td}>{s.title}</td><td style={td}>{s.count}</td></tr>)}</tbody>
                </table>
              )}
            </div>
          </div>
          {data.speeders.members.length > 0 && (<><p style={{ fontWeight: 700, fontSize: "0.85rem", margin: "1rem 0 0.4rem" }}>Speeders</p>{memberTable(data.speeders.members)}</>)}
          {data.straightLiners.members.length > 0 && (<><p style={{ fontWeight: 700, fontSize: "0.85rem", margin: "1rem 0 0.4rem" }}>Straight-liners</p>{memberTable(data.straightLiners.members)}</>)}
        </>
      )}
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
      <QualityReport />
      <QualReview onChanged={load} />
      <FlagReview onChanged={load} />
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
