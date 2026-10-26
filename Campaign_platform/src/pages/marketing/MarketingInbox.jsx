import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { Clock, RefreshCw } from "lucide-react"
import { buildApiUrl } from "../../config"
import { authFetch } from "../../utils/api"
import { notify } from "../../utils/notify"
import { formatDateTime } from "../../utils/format"

// Marketing > Inbox: website forms, social comments and DMs, WhatsApp, lead forms -- one list, with SLA.
const api = async (path, opts = {}) => {
  const res = await authFetch(buildApiUrl(`/api/marketing/inbox${path}`), { headers: { "Content-Type": "application/json" }, ...opts })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`)
  return data
}

const label = (c) => c.replace(/_/g, " ")

export default function MarketingInbox() {
  const [data, setData] = useState(null)
  const [f, setF] = useState({ status: "open", channel: "", bu: "" })

  const load = async () => {
    try {
      const q = new URLSearchParams(Object.entries(f).filter(([, v]) => v)).toString()
      setData(await api(q ? `?${q}` : ""))
    } catch (e) {
      notify(e.message, "error")
    }
  }
  useEffect(() => { load() }, [f.status, f.channel, f.bu])

  const act = async (id, action) => {
    try { await api(`/${id}/${action}`, { method: "POST" }); load() } catch (e) { notify(e.message, "error") }
  }

  if (!data) return <div className="card">Loading…</div>
  const stats = Object.entries(data.stats || {})
  return (
    <div className="space-y-4">
      <div className="card">
        <div className="card-header flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="card-title">Inbox</h2>
            <p className="card-description">
              Every inbound message across channels. Replies are drafted into the Review Queue; an item counts as answered
              when its draft is approved. SLA: leads 1 working hour, comments 4 working hours.
            </p>
          </div>
          <button type="button" className="btn btn-secondary flex items-center gap-1" onClick={load}><RefreshCw size={16} /> Refresh</button>
        </div>
        <div className="flex flex-wrap gap-2">
          <select className="form-input" value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}>
            {["open", "replied", "closed", "spam", ""].map((s) => <option key={s} value={s}>{s || "all"}</option>)}
          </select>
          <select className="form-input" value={f.channel} onChange={(e) => setF({ ...f, channel: e.target.value })}>
            <option value="">All channels</option>{data.channels.map((c) => <option key={c} value={c}>{label(c)}</option>)}
          </select>
          <select className="form-input" value={f.bu} onChange={(e) => setF({ ...f, bu: e.target.value })}>
            <option value="">All BUs</option>{["SFW", "COGENTIX", "BIM"].map((b) => <option key={b}>{b}</option>)}
          </select>
        </div>
      </div>

      {stats.length > 0 && (
        <div className="card overflow-x-auto">
          <h3 className="card-title">Last 30 days</h3>
          <table className="mt-2 w-full text-sm">
            <thead><tr className="text-left"><th>Channel</th><th>Received</th><th>Answered</th><th>Within SLA</th><th>Median response</th><th>Open past SLA</th></tr></thead>
            <tbody>
              {stats.map(([c, s]) => (
                <tr key={c}>
                  <td>{label(c)}</td><td>{s.received}</td><td>{s.replied}</td>
                  <td>{s.sla_met_pct == null ? "—" : `${s.sla_met_pct}%`}</td>
                  <td>{s.median_response_minutes == null ? "—" : `${s.median_response_minutes} min`}</td>
                  <td className={s.open_breached ? "font-semibold text-red-700" : ""}>{s.open_breached}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data.items.length === 0 && <div className="card text-gray-700">Nothing here.</div>}
      {data.items.map((it) => (
        <div key={it._id} className="card">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <p className="font-semibold">
                {label(it.channel)} · {it.bu || "—"} · {it.category}{it.sender_type && it.sender_type !== "other" ? ` (${it.sender_type})` : ""}
              </p>
              <p className="text-sm text-gray-700">
                {(it.author && (it.author.name || it.author.handle)) || "Unknown"} · {formatDateTime(it.at)}
                {it.url && <> · <a href={it.url} target="_blank" rel="noreferrer" className="underline">open</a></>}
              </p>
            </div>
            {it.status === "open" && it.due_at && (
              <span className={`flex items-center gap-1 text-sm font-semibold ${it.breached ? "text-red-700" : "text-gray-800"}`}>
                <Clock size={14} /> {it.breached ? "Past SLA since" : "Reply by"} {formatDateTime(it.due_at)}
              </span>
            )}
          </div>
          <p className="mt-2 whitespace-pre-wrap text-sm">{it.text}</p>
          {it.draft && <p className="mt-2 rounded bg-gray-50 p-2 text-sm"><strong>Draft:</strong> {it.draft}</p>}
          <div className="mt-2 flex flex-wrap gap-2">
            {it.review_item && <Link className="btn btn-secondary" to="/admin/review-queue">Open in Review Queue</Link>}
            {it.status === "open" && <button type="button" className="btn btn-secondary" onClick={() => act(it._id, "replied")}>Mark replied</button>}
            {it.status === "open" && <button type="button" className="btn btn-secondary" onClick={() => act(it._id, "close")}>Close</button>}
            {it.status !== "spam" && <button type="button" className="btn btn-secondary" onClick={() => act(it._id, "spam")}>Spam</button>}
            {it.status !== "open" && <button type="button" className="btn btn-secondary" onClick={() => act(it._id, "reopen")}>Reopen</button>}
          </div>
        </div>
      ))}
    </div>
  )
}
