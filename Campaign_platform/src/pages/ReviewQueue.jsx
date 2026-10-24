import { useEffect, useMemo, useState } from "react"
import { buildApiUrl } from "../config"
import { authFetch } from "../utils/api"
import { formatDateTime } from "../utils/format"

// CRM plan 3.1: the one place a person needs to look day to day. Every item
// waiting on a decision (low-confidence or invalid AI output, RFQ extractions,
// ambiguous entity links, unusual prices, finance mismatches, paused
// mailboxes...) with one-click approve / correct / reject / reassign. Approve
// and correct resume the workflow where it stopped (server side).

const MODULE_LABEL = {
  rfq_extraction: "RFQ extraction",
  reply_classification: "Reply classification",
  sender_type: "Sender type",
  lead_bucketing: "Lead bucketing",
  vendor_bid_parse: "Vendor bids",
  linking: "Data linking",
  pricing: "Pricing",
  finance: "Finance",
  deliverability: "Deliverability",
}

function age(iso) {
  if (!iso) return ""
  const h = (Date.now() - new Date(iso).getTime()) / 36e5
  return h < 1 ? `${Math.max(1, Math.round(h * 60))} min` : h < 48 ? `${Math.round(h)} h` : `${Math.round(h / 24)} d`
}

export default function ReviewQueue() {
  const [items, setItems] = useState([])
  const [counts, setCounts] = useState({ pending_total: 0, by_module: {} })
  const [module, setModule] = useState("")
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(null)
  const [editing, setEditing] = useState(null)   // item id being corrected
  const [draft, setDraft] = useState("")
  const [error, setError] = useState("")

  const load = async () => {
    setLoading(true)
    setError("")
    try {
      const q = module ? `?module=${encodeURIComponent(module)}` : ""
      const r = await authFetch(buildApiUrl(`/api/platform/review-queue${q}`))
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const data = await r.json()
      setItems(data.items || [])
      setCounts(data.counts || { pending_total: 0, by_module: {} })
    } catch (e) {
      setError(`Could not load the Review Queue (${e.message}).`)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [module])   // eslint-disable-line react-hooks/exhaustive-deps

  const act = async (item, action, extra = {}) => {
    setBusy(item._id)
    setError("")
    try {
      const r = await authFetch(buildApiUrl(`/api/platform/review-queue/${item._id}/${action}`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(extra),
      })
      const data = await r.json().catch(() => ({}))
      if (!r.ok || data.ok === false) throw new Error(data.error || data.detail || `HTTP ${r.status}`)
      setEditing(null)
      await load()
    } catch (e) {
      setError(`${action} failed: ${e.message}`)
    } finally {
      setBusy(null)
    }
  }

  const startCorrect = (item) => {
    setEditing(item._id)
    setDraft(JSON.stringify(item.suggested || {}, null, 2))
  }

  const submitCorrect = (item) => {
    let correction
    try { correction = JSON.parse(draft) } catch { setError("The correction is not valid JSON."); return }
    act(item, "correct", { correction })
  }

  const reassign = (item) => {
    const assignee = window.prompt("Reassign to (username):", item.owner || "")
    if (assignee) act(item, "reassign", { assignee })
  }

  const modules = useMemo(() => Object.entries(counts.by_module || {}).sort((a, b) => b[1].pending - a[1].pending), [counts])

  return (
    <div className="p-4 sm:p-6">
      <div className="mb-5">
        <h1 className="text-xl sm:text-2xl font-bold text-gray-900">Review Queue</h1>
        <p className="mt-1 text-sm text-gray-500">
          {counts.pending_total} waiting for a decision. Approve or correct to let the workflow continue; nothing in this list is acted on until you do.
        </p>
      </div>

      <div className="flex flex-wrap gap-2 mb-4">
        <button onClick={() => setModule("")}
          className={`px-3 py-1.5 rounded-full text-sm border ${module === "" ? "bg-gray-900 text-white border-gray-900" : "bg-white text-gray-700 border-gray-200"}`}>
          All ({counts.pending_total})
        </button>
        {modules.map(([m, v]) => (
          <button key={m} onClick={() => setModule(m)}
            className={`px-3 py-1.5 rounded-full text-sm border ${module === m ? "bg-gray-900 text-white border-gray-900" : "bg-white text-gray-700 border-gray-200"}`}>
            {MODULE_LABEL[m] || m} ({v.pending})
          </button>
        ))}
      </div>

      {(counts.legacy_pending || []).some((q) => q.pending > 0) && (
        <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-800">
          Still in older queues (moved here during the data back-fill):{" "}
          {counts.legacy_pending.filter((q) => q.pending > 0).map((q) => `${q.queue} ${q.pending}`).join(" · ")}
        </div>
      )}

      {error && <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">{error}</div>}

      {loading ? (
        <p className="text-sm text-gray-500">Loading…</p>
      ) : items.length === 0 ? (
        <div className="rounded-xl border border-gray-200 bg-white p-8 text-center text-gray-500">Nothing waiting. 🎉</div>
      ) : (
        <ul className="space-y-3">
          {items.map((it) => (
            <li key={it._id} className="rounded-xl border border-gray-200 bg-white p-4">
              <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500">
                    <span className="rounded bg-gray-100 px-2 py-0.5 font-medium text-gray-700">{MODULE_LABEL[it.module] || it.module}</span>
                    <span>{it.type.replace(/_/g, " ")}</span>
                    {it.bu && <span className="rounded bg-blue-50 px-2 py-0.5 text-blue-700">{it.bu}</span>}
                    <span title={formatDateTime ? formatDateTime(it.created_at) : it.created_at}>waiting {age(it.created_at)}</span>
                    {it.owner && <span>· {it.owner}</span>}
                    {it.value_inr ? <span>· ₹{Number(it.value_inr).toLocaleString("en-IN")}</span> : null}
                  </div>
                  <p className="mt-1 text-sm text-gray-900">{it.reason}</p>
                  {it.ref?.id && <p className="mt-0.5 text-xs text-gray-400 break-all">{it.ref.collection} · {it.ref.id}</p>}
                </div>
                <div className="flex shrink-0 flex-wrap gap-2">
                  <button disabled={busy === it._id} onClick={() => act(it, "approve")}
                    className="rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50">Approve</button>
                  <button disabled={busy === it._id} onClick={() => startCorrect(it)}
                    className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50">Correct</button>
                  <button disabled={busy === it._id} onClick={() => act(it, "reject")}
                    className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50">Reject</button>
                  <button disabled={busy === it._id} onClick={() => reassign(it)}
                    className="rounded-lg px-3 py-1.5 text-sm text-gray-500 hover:text-gray-800 disabled:opacity-50">Reassign</button>
                </div>
              </div>
              {it.suggested && Object.keys(it.suggested).length > 0 && editing !== it._id && (
                <pre className="mt-3 max-h-48 overflow-auto rounded-lg bg-gray-50 p-3 text-xs text-gray-700">{JSON.stringify(it.suggested, null, 2)}</pre>
              )}
              {editing === it._id && (
                <div className="mt-3">
                  <textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={8}
                    className="w-full rounded-lg border border-gray-300 p-2 font-mono text-xs" />
                  <div className="mt-2 flex gap-2">
                    <button onClick={() => submitCorrect(it)} className="rounded-lg bg-gray-900 px-3 py-1.5 text-sm font-medium text-white">Save correction</button>
                    <button onClick={() => setEditing(null)} className="rounded-lg px-3 py-1.5 text-sm text-gray-600">Cancel</button>
                  </div>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
