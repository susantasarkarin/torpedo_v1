import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { RefreshCw, Undo2 } from "lucide-react"
import { buildApiUrl } from "../../config"
import { authFetch } from "../../utils/api"
import { confirmAction, notify } from "../../utils/notify"
import { formatDateTime } from "../../utils/format"

// Marketing > Decisions: what the engine proposed, what ran (shadow or live) with undo, and how each type scores.
const api = async (path, opts = {}) => {
  const res = await authFetch(buildApiUrl(`/api/marketing/decisions${path}`), { headers: { "Content-Type": "application/json" }, ...opts })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`)
  return data
}

function Row({ d, onUndo }) {
  const [open, setOpen] = useState(false)
  const canUndo = ["executed", "shadow_executed"].includes(d.status) && (!d.undo_until || new Date(d.undo_until) > new Date())
  return (
    <div className="border-b border-gray-100 py-2 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <button type="button" className="text-left" onClick={() => setOpen(!open)}>
          <strong>{d.decision_type}</strong> {d.name} · {d.entity_label || d.entity_key} · <em>{d.final_action}</em>
          <span className="text-gray-600"> · {d.status.replace("_", " ")} · confidence {d.confidence ? d.confidence.score : "—"} · {formatDateTime(d.created_at)}</span>
        </button>
        <div className="flex gap-2">
          {d.status === "in_review" && <Link className="btn btn-secondary" to="/admin/review-queue">Approve / reject</Link>}
          {canUndo && <button type="button" className="btn btn-secondary flex items-center gap-1" onClick={() => onUndo(d)}><Undo2 size={14} /> Undo</button>}
        </div>
      </div>
      {open && (
        <div className="mt-2 grid gap-2 rounded bg-gray-50 p-2 md:grid-cols-2">
          <div><strong>Evidence</strong><pre className="whitespace-pre-wrap text-xs">{JSON.stringify(d.evidence, null, 1)}</pre></div>
          <div>
            {d.reasoning && <p><strong>Reasoning:</strong> {d.reasoning}</p>}
            {d.risks && <p><strong>Risks:</strong> {d.risks}</p>}
            {(d.validation_problems || []).length > 0 && <p className="text-red-700"><strong>Not accepted:</strong> {d.validation_problems.join("; ")}</p>}
            {d.gate && <p><strong>Held at L1:</strong> {d.gate}</p>}
            {d.would_execute && <p><strong>Would execute:</strong> {d.would_execute.platform} {d.would_execute.action} ({d.shadow_reason})</p>}
            {d.outcome && <p><strong>Outcome:</strong> {d.outcome.summary} — {d.outcome.better_than_baseline ? "better" : "worse"} than baseline</p>}
          </div>
        </div>
      )}
    </div>
  )
}

export default function MarketingDecisions() {
  const [score, setScore] = useState(null)
  const [rows, setRows] = useState([])
  const [status, setStatus] = useState("in_review")

  const load = async () => {
    try {
      const [s, r] = await Promise.all([api("/scorecard"), api(status ? `?status=${status}` : "")])
      setScore(s)
      setRows(r.decisions || [])
    } catch (e) {
      notify(e.message, "error")
    }
  }
  useEffect(() => { load() }, [status])

  const undo = async (d) => {
    if (!(await confirmAction(`Undo ${d.final_action} on ${d.entity_label || d.entity_key}?`))) return
    try { await api(`/${d._id}/undo`, { method: "POST" }); load() } catch (e) { notify(e.message, "error") }
  }

  if (!score) return <div className="card">Loading…</div>
  const killed = score.kill_switch && Object.entries(score.kill_switch).filter(([, v]) => v).map(([k]) => k)
  return (
    <div className="space-y-4">
      <div className="card">
        <div className="card-header flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="card-title">Decision Engine</h2>
            <p className="card-description">
              Mode: <strong>{score.mode}</strong>{killed && killed.length ? <> · <span className="font-semibold text-red-700">kill switch on: {killed.join(", ")}</span></> : null}.
              A type above L1 acts only after 85 % agreement with your verdicts over 14 days.
            </p>
          </div>
          <button type="button" className="btn btn-secondary flex items-center gap-1" onClick={load}><RefreshCw size={16} /> Refresh</button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="text-left"><th>Type</th><th>Autonomy (set → effective)</th><th>Proposed</th><th>In review</th>
              <th>Accepted</th><th>Rejected</th><th>Executed</th><th>Agreement 14 d</th><th>Outcomes better</th></tr></thead>
            <tbody>
              {score.types.map((t) => (
                <tr key={t.type} title={t.gate}>
                  <td>{t.type} {t.name.replace(/_/g, " ")}</td>
                  <td>{t.autonomy_set}{t.autonomy_effective !== t.autonomy_set ? ` → ${t.autonomy_effective}` : ""}</td>
                  <td>{t.proposed}</td><td>{t.in_review}</td><td>{t.accepted}</td><td>{t.rejected}</td><td>{t.executed}</td>
                  <td>{t.agreement_14d == null ? "—" : `${Math.round(t.agreement_14d * 100)}%`}</td>
                  <td>{t.measured ? `${t.better_than_baseline}/${t.measured}` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <div className="card">
        <div className="mb-2 flex gap-2">
          {[["in_review", "Open"], ["shadow_executed,executed", "Executed"], ["undone,rejected,blocked,skipped", "Other"], ["", "All"]].map(([v, l]) => (
            <button key={l} type="button" className={`btn ${status === v ? "btn-primary" : "btn-secondary"}`} onClick={() => setStatus(v)}>{l}</button>
          ))}
        </div>
        {rows.length === 0 ? <p className="text-gray-700">None.</p> : rows.map((d) => <Row key={d._id} d={d} onUndo={undo} />)}
      </div>
    </div>
  )
}
