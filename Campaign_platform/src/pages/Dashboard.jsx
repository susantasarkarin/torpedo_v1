import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { buildApiUrl } from "../config"

const SEVERITY = {
  high: { bar: "#dc2626", bg: "#fef2f2", label: "Action needed" },
  normal: { bar: "#f59e0b", bg: "#fffbeb", label: "Review" },
  low: { bar: "#9ca3af", bg: "#f9fafb", label: "FYI" },
}

function AttentionItem({ item, onOpen }) {
  const s = SEVERITY[item.severity] || SEVERITY.normal
  return (
    <div
      onClick={() => item.link && onOpen(item.link)}
      style={{
        display: "flex", gap: "12px", padding: "12px 14px", marginBottom: "8px",
        background: s.bg, borderLeft: `4px solid ${s.bar}`, borderRadius: "6px",
        cursor: item.link ? "pointer" : "default",
      }}
    >
      <div style={{ fontSize: "1.5rem", fontWeight: 700, minWidth: "56px", color: s.bar, textAlign: "right" }}>
        {item.count.toLocaleString()}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 600, color: "#111827" }}>{item.title}</div>
        {item.detail && <div style={{ fontSize: "0.8rem", color: "#4b5563" }}>{item.detail}</div>}
        {item.examples?.length > 0 && (
          <div style={{ fontSize: "0.75rem", color: "#6b7280", marginTop: "2px",
                        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {item.examples.join(" · ")}
          </div>
        )}
      </div>
      <div style={{ fontSize: "0.7rem", color: s.bar, fontWeight: 600, whiteSpace: "nowrap" }}>{s.label}</div>
    </div>
  )
}

function Dashboard() {
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [error, setError] = useState("")

  useEffect(() => {
    const sessionId = localStorage.getItem("session_id")
    if (!sessionId) {
      navigate("/login")
      return
    }
    const load = async () => {
      try {
        const res = await fetch(buildApiUrl("/attention"), {
          headers: { "Content-Type": "application/json", Authorization: sessionId },
        })
        if (res.status === 401) {
          localStorage.removeItem("session_id")
          navigate("/login")
          return
        }
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        setData(await res.json())
        setError("")
      } catch (err) {
        setError(`Could not load the attention list: ${err.message}`)
      }
    }
    load()
    const timer = setInterval(load, 5 * 60 * 1000)
    return () => clearInterval(timer)
  }, [navigate])

  const stats = data?.stats || {}
  const items = data?.items || []
  const statCards = [
    { label: "Active campaigns", value: stats.active_campaigns, color: "#3b82f6", link: "/admin/sales/outreach" },
    { label: "Leads", value: stats.leads, color: "#10b981", link: "/admin/sales/leads" },
    { label: "Vendor leads", value: stats.vendor_leads, color: "#8b5cf6", link: "/admin/vendor/leads" },
    { label: "Open RFQs", value: stats.open_rfqs, color: "#f59e0b", link: "/admin/sales/rfq" },
  ]

  return (
    <div>
      <div className="card">
        <div className="card-header">
          <h2 className="card-title">Needs your attention</h2>
          <p className="card-description">
            What is waiting on you across sales, finance and the automations. Click an item to open it.
          </p>
        </div>
        {error && <p style={{ color: "#dc2626" }}>{error}</p>}
        {!data && !error && <p className="card-description">Loading…</p>}
        {data && items.length === 0 && <p className="card-description">Nothing needs you right now.</p>}
        {items.map(item => <AttentionItem key={item.key} item={item} onOpen={navigate} />)}
      </div>

      <div style={{ marginTop: "16px", display: "grid", gap: "16px",
                    gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" }}>
        {statCards.map(c => (
          <div key={c.label} className="card" onClick={() => navigate(c.link)} style={{ cursor: "pointer" }}>
            <h3 className="card-title">{c.label}</h3>
            <p style={{ fontSize: "2rem", fontWeight: "bold", color: c.color }}>
              {c.value === undefined ? "—" : c.value.toLocaleString()}
            </p>
          </div>
        ))}
      </div>
    </div>
  )
}

export default Dashboard
