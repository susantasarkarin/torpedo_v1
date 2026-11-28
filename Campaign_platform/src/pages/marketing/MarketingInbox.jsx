import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { Clock, RefreshCw } from "lucide-react"
import { notify } from "../../utils/notify"
import { formatDateTime } from "../../utils/format"
import { marketingApi, BUS } from "./api"

// Marketing > Inbox: website forms, social comments and DMs, WhatsApp, lead forms -- one list, with SLA.
const api = marketingApi("/api/marketing/inbox")

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

  if (!data) return <div className="loading-spinner" />
  const stats = Object.entries(data.stats || {})
  const STATUS_PILL = { open: "warn", replied: "ok", closed: "", spam: "bad" }
  return (
    <div className="space-y-5">
      <div className="mk-section-head">
        <div>
          <h1 className="cx-page-title">Inbox</h1>
          <p>
            Every inbound message across channels. Replies are drafted into the Review Queue; an item counts as answered
            when its draft is approved. SLA: leads 1 working hour, comments 4 working hours.
          </p>
        </div>
        <button type="button" className="btn btn-secondary" onClick={load}><RefreshCw size={16} /> Refresh</button>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <label>
          <span className="mk-label">Status</span>
          <select className="form-input mk-auto" value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}>
            {["open", "replied", "closed", "spam", ""].map((s) => <option key={s} value={s}>{s ? s[0].toUpperCase() + s.slice(1) : "All"}</option>)}
          </select>
        </label>
        <label>
          <span className="mk-label">Channel</span>
          <select className="form-input mk-auto" value={f.channel} onChange={(e) => setF({ ...f, channel: e.target.value })}>
            <option value="">All channels</option>{data.channels.map((c) => <option key={c} value={c}>{label(c)}</option>)}
          </select>
        </label>
        <label>
          <span className="mk-label">Business unit</span>
          <select className="form-input mk-auto" value={f.bu} onChange={(e) => setF({ ...f, bu: e.target.value })}>
            <option value="">All BUs</option>{BUS.map((b) => <option key={b}>{b}</option>)}
          </select>
        </label>
      </div>

      {stats.length > 0 && (
        <div>
          <h2 className="mb-2 text-lg font-bold">Last 30 days</h2>
          <div className="mk-table-wrap">
            <table>
              <thead><tr><th>Channel</th><th className="num">Received</th><th className="num">Answered</th><th className="num">Within SLA</th><th className="num">Median response</th><th className="num">Open past SLA</th></tr></thead>
              <tbody>
                {stats.map(([c, s]) => (
                  <tr key={c}>
                    <td className="font-semibold capitalize">{label(c)}</td><td className="num">{s.received}</td><td className="num">{s.replied}</td>
                    <td className="num">{s.sla_met_pct == null ? <span className="mk-muted">—</span> : `${s.sla_met_pct}%`}</td>
                    <td className="num">{s.median_response_minutes == null ? <span className="mk-muted">—</span> : `${s.median_response_minutes} min`}</td>
                    <td className={`num ${s.open_breached ? "font-semibold text-red-700" : ""}`}>{s.open_breached}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div>
        <h2 className="mb-2 text-lg font-bold">Messages <span className="mk-muted font-normal">({data.items.length})</span></h2>
        {data.items.length === 0 ? (
          <div className="empty-state py-10"><h3>Nothing here</h3><p>No messages match these filters.</p></div>
        ) : (
          <div className="mk-table-wrap divide-y divide-gray-100">
            {data.items.map((it) => (
              <div key={it._id} className="space-y-2 px-5 py-4">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="flex min-w-0 flex-wrap items-center gap-2">
                    <span className="mk-pill capitalize">{label(it.channel)}</span>
                    {it.bu && <span className="mk-pill info">{it.bu}</span>}
                    <span className="mk-pill">{it.category}{it.sender_type && it.sender_type !== "other" ? ` · ${it.sender_type}` : ""}</span>
                    {it.status !== "open" && <span className={`mk-pill ${STATUS_PILL[it.status] || ""}`}>{it.status}</span>}
                  </div>
                  {it.status === "open" && it.due_at && (
                    <span className={`mk-pill ${it.breached ? "bad" : "warn"}`}>
                      <Clock size={14} /> {it.breached ? "Past SLA since" : "Reply by"} {formatDateTime(it.due_at)}
                    </span>
                  )}
                </div>
                <p className="text-sm text-gray-600">
                  <span className="font-semibold text-gray-900">{(it.author && (it.author.name || it.author.handle)) || "Unknown"}</span> · {formatDateTime(it.at)}
                  {it.url && <> · <a href={it.url} target="_blank" rel="noreferrer" className="mk-link">View source</a></>}
                </p>
                <p className="whitespace-pre-wrap">{it.text}</p>
                {it.draft && <p className="mk-notice"><span><strong>Draft:</strong> {it.draft}</span></p>}
                <div className="flex flex-wrap gap-2 pt-1">
                  {it.review_item && <Link className="btn btn-primary btn-sm" to="/admin/review-queue">Open in Review Queue</Link>}
                  {it.status === "open" && <button type="button" className={`btn ${it.review_item ? "btn-secondary" : "btn-primary"} btn-sm`} onClick={() => act(it._id, "replied")}>Mark replied</button>}
                  {it.status === "open" && <button type="button" className="btn btn-secondary btn-sm" onClick={() => act(it._id, "close")}>Close</button>}
                  {it.status !== "open" && <button type="button" className="btn btn-secondary btn-sm" onClick={() => act(it._id, "reopen")}>Reopen</button>}
                  {it.status !== "spam" && <button type="button" className="btn btn-secondary btn-sm ml-auto" onClick={() => act(it._id, "spam")}>Mark as spam</button>}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
