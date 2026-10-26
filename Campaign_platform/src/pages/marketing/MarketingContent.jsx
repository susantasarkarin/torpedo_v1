import { useEffect, useState } from "react"
import { AlertTriangle, CheckCircle2, Link2, Plus, RefreshCw, Sparkles } from "lucide-react"
import { buildApiUrl } from "../../config"
import { authFetch } from "../../utils/api"
import { notify } from "../../utils/notify"
import { formatDateTime } from "../../utils/format"

// Marketing > Content: calendar per BU and channel, Qwen drafts, claim checks, approval, brand voice, UTM links.
const api = async (path, opts = {}) => {
  const res = await authFetch(buildApiUrl(`/api/marketing/content${path}`), {
    headers: { "Content-Type": "application/json" }, ...opts,
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`)
  return data
}

const BUS = ["SFW", "COGENTIX", "BIM"]
const STATUS_ORDER = ["idea", "draft", "in_review", "approved", "scheduled", "published"]
const EMPTY = { bu: "SFW", channel: "linkedin", title: "", body: "", scheduled_for: "" }

function Item({ it, flow, onChange }) {
  const [body, setBody] = useState(it.body || "")
  const [when, setWhen] = useState(it.scheduled_for ? it.scheduled_for.slice(0, 16) : "")
  const locked = ["approved", "scheduled", "published"].includes(it.status)
  const call = async (path, opts) => {
    try { await api(path, opts); onChange() } catch (e) { notify(e.message, "error") }
  }
  const save = () => call(`/${it._id}`, { method: "PUT", body: JSON.stringify({ body, scheduled_for: when || null }) })
  const next = (flow[it.status] || []).filter((s) => !["approved", "scheduled"].includes(s))

  return (
    <div className="card">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="card-title">{it.title || it.topic || "(untitled)"}</h3>
          <p className="card-description">
            {it.bu} · {it.channel} · <strong>{it.status.replace("_", " ")}</strong>
            {it.scheduled_for && <> · for {formatDateTime(it.scheduled_for)}</>}
            {it.would_publish_at && <> · would publish ({it.shadow_reason})</>}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {it.status === "idea" && (
            <button type="button" className="btn btn-secondary flex items-center gap-1" onClick={() => call(`/${it._id}/draft`, { method: "POST" })}>
              <Sparkles size={16} /> Qwen draft
            </button>
          )}
          {next.map((s) => (
            <button key={s} type="button" className="btn btn-secondary" onClick={() => call(`/${it._id}/move/${s}`, { method: "POST" })}>
              {s === "draft" && it.status !== "idea" ? "Back to draft" : `To ${s.replace("_", " ")}`}
            </button>
          ))}
          {it.status === "in_review" && (
            <>
              <button type="button" className="btn btn-primary" onClick={() => call(`/${it._id}/approve`, { method: "POST" })}>Approve</button>
              <button type="button" className="btn btn-primary" disabled={!it.scheduled_for}
                onClick={() => call(`/${it._id}/approve?schedule=true`, { method: "POST" })}>Approve &amp; schedule</button>
            </>
          )}
        </div>
      </div>
      {(it.claim_problems || []).length > 0 && (
        <ul className="mt-2 text-sm font-semibold text-red-700">
          {it.claim_problems.map((p) => <li key={p} className="flex items-center gap-1"><AlertTriangle size={14} /> {p}</li>)}
        </ul>
      )}
      {it.draft_error && <p className="mt-2 text-sm text-gray-700">{it.draft_error}</p>}
      <textarea className="form-input mt-3 w-full" rows={5} value={body} disabled={locked} onChange={(e) => setBody(e.target.value)}
        placeholder="Write the post, or ask Qwen for a draft" />
      {!locked && (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <label className="text-sm">Publish at <input type="datetime-local" className="form-input" value={when} onChange={(e) => setWhen(e.target.value)} /></label>
          <button type="button" className="btn btn-secondary" onClick={save}>Save</button>
        </div>
      )}
    </div>
  )
}

function Utm() {
  const [f, setF] = useState({ url: "", bu: "SFW", channel: "quora", campaign: "answers", content: "" })
  const [out, setOut] = useState("")
  const make = async () => {
    try { setOut((await api("/utm-link", { method: "POST", body: JSON.stringify(f) })).url) } catch (e) { notify(e.message, "error") }
  }
  return (
    <div className="card">
      <h3 className="card-title flex items-center gap-2"><Link2 size={18} /> Tagged link (Quora answers, posts)</h3>
      <div className="mt-3 grid gap-2 md:grid-cols-5">
        <input className="form-input md:col-span-2" placeholder="https://… page to link" value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} />
        <select className="form-input" value={f.bu} onChange={(e) => setF({ ...f, bu: e.target.value })}>{BUS.map((b) => <option key={b}>{b}</option>)}</select>
        <input className="form-input" placeholder="topic / campaign" value={f.campaign} onChange={(e) => setF({ ...f, campaign: e.target.value })} />
        <button type="button" className="btn btn-primary" onClick={make}>Make link</button>
      </div>
      {out && <p className="mt-2 break-all font-mono text-sm">{out}</p>}
    </div>
  )
}

export default function MarketingContent() {
  const [data, setData] = useState(null)
  const [voices, setVoices] = useState([])
  const [filter, setFilter] = useState({ bu: "", channel: "", status: "" })
  const [draft, setDraft] = useState(null)

  const load = async () => {
    try {
      const q = new URLSearchParams(Object.entries(filter).filter(([, v]) => v)).toString()
      const [d, v] = await Promise.all([api(q ? `?${q}` : ""), api("/brand-voice")])
      setData(d)
      setVoices(v.voices || [])
    } catch (e) {
      notify(e.message, "error")
    }
  }
  useEffect(() => { load() }, [filter.bu, filter.channel, filter.status])

  const create = async () => {
    try {
      await api("", { method: "POST", body: JSON.stringify({ ...draft, scheduled_for: draft.scheduled_for || null }) })
      setDraft(null)
      load()
    } catch (e) {
      notify(e.message, "error")
    }
  }

  if (!data) return <div className="card">Loading…</div>
  const items = [...data.items].sort((a, b) => STATUS_ORDER.indexOf(a.status) - STATUS_ORDER.indexOf(b.status))
  return (
    <div className="space-y-4">
      <div className="card">
        <div className="card-header flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="card-title">Content calendar</h2>
            <p className="card-description">
              Nothing is published without approval. Claims are checked before review: no guaranteed incidence,
              no panel sizes outside the panel book, no client names without permission.
            </p>
          </div>
          <div className="flex gap-2">
            <button type="button" className="btn btn-secondary flex items-center gap-1" onClick={load}><RefreshCw size={16} /> Refresh</button>
            <button type="button" className="btn btn-primary flex items-center gap-1" onClick={() => setDraft({ ...EMPTY })}><Plus size={16} /> New piece</button>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <select className="form-input" value={filter.bu} onChange={(e) => setFilter({ ...filter, bu: e.target.value })}>
            <option value="">All BUs</option>{BUS.map((b) => <option key={b}>{b}</option>)}
          </select>
          <select className="form-input" value={filter.channel} onChange={(e) => setFilter({ ...filter, channel: e.target.value })}>
            <option value="">All channels</option>{data.channels.map((c) => <option key={c}>{c}</option>)}
          </select>
          <select className="form-input" value={filter.status} onChange={(e) => setFilter({ ...filter, status: e.target.value })}>
            <option value="">All statuses</option>{STATUS_ORDER.map((s) => <option key={s} value={s}>{s.replace("_", " ")} ({data.counts[s] || 0})</option>)}
          </select>
        </div>
      </div>

      {draft && (
        <div className="card">
          <div className="grid gap-2 md:grid-cols-4">
            <select className="form-input" value={draft.bu} onChange={(e) => setDraft({ ...draft, bu: e.target.value })}>{BUS.map((b) => <option key={b}>{b}</option>)}</select>
            <select className="form-input" value={draft.channel} onChange={(e) => setDraft({ ...draft, channel: e.target.value })}>{data.channels.map((c) => <option key={c}>{c}</option>)}</select>
            <input className="form-input md:col-span-2" placeholder="Topic / title" value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} />
          </div>
          <textarea className="form-input mt-2 w-full" rows={4} placeholder="Leave empty to keep it as an idea for Qwen to draft overnight"
            value={draft.body} onChange={(e) => setDraft({ ...draft, body: e.target.value })} />
          <div className="mt-2 flex gap-2">
            <button type="button" className="btn btn-primary" onClick={create}>Add</button>
            <button type="button" className="btn btn-secondary" onClick={() => setDraft(null)}>Cancel</button>
          </div>
        </div>
      )}

      {items.length === 0 && <div className="card text-gray-700">No content yet. Add an idea, or Qwen proposes topics from the SEO content gaps.</div>}
      {items.map((it) => <Item key={it._id} it={it} flow={data.flow} onChange={load} />)}

      <Utm />

      <div className="card">
        <h3 className="card-title">Brand voice</h3>
        <p className="card-description">Drafted by Claude from each company's services; approve or edit before Qwen writes in it.</p>
        <div className="mt-3 grid gap-3 md:grid-cols-3">
          {voices.map((v) => (
            <div key={v.bu} className="rounded border border-gray-200 p-3 text-sm">
              <p className="font-semibold">{v.bu} {v.status === "approved"
                ? <CheckCircle2 size={14} className="inline text-green-700" /> : <span className="text-gray-600">(proposed)</span>}</p>
              <p className="mt-1">{v.voice}</p>
              <p className="mt-1"><strong>Do:</strong> {(v.do || []).join("; ")}</p>
              <p className="mt-1"><strong>Don't:</strong> {(v.dont || []).join("; ")}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
