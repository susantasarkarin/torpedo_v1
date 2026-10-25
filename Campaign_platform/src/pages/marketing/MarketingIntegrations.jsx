import { useEffect, useState } from "react"
import { CheckCircle2, Circle, KeyRound, RefreshCw, Trash2 } from "lucide-react"
import { buildApiUrl } from "../../config"
import { authFetch } from "../../utils/api"
import { confirmAction, notify } from "../../utils/notify"
import { formatDateTime } from "../../utils/format"

// Marketing > Integrations: platform tokens (stored encrypted, never shown again) and their IDs.
const api = async (path, opts = {}) => {
  const res = await authFetch(buildApiUrl(`/api/marketing/integrations${path}`), {
    headers: { "Content-Type": "application/json" }, ...opts,
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`)
  return data
}

const label = (f) => f.replace(/_/g, " ").replace(/\bids\b/, "IDs").replace(/\bid\b/, "ID").replace(/json/, "JSON")

// settings accept plain text, or JSON for per-BU maps / lists, e.g. {"SFW": "123", "BIM": "456"}
const toText = (v) => (v == null ? "" : typeof v === "string" ? v : JSON.stringify(v))
const fromText = (s) => {
  const t = s.trim()
  if (!t) return null
  if (t.startsWith("{") || t.startsWith("[")) {
    try { return JSON.parse(t) } catch { throw new Error(`Not valid JSON: ${t.slice(0, 40)}`) }
  }
  return t
}

function Platform({ id, p, onSaved }) {
  const [secrets, setSecrets] = useState({})
  const [settings, setSettings] = useState(() =>
    Object.fromEntries(Object.entries(p.settings).map(([k, v]) => [k, toText(v)])))
  const [saving, setSaving] = useState(false)

  const save = async () => {
    setSaving(true)
    try {
      const body = { secrets, settings: Object.fromEntries(Object.entries(settings).map(([k, v]) => [k, fromText(v)])) }
      await api(`/${id}`, { method: "PUT", body: JSON.stringify(body) })
      setSecrets({})
      notify("Saved", "success")
      onSaved()
    } catch (e) {
      notify(e.message, "error")
    } finally {
      setSaving(false)
    }
  }

  const disconnect = async () => {
    if (!(await confirmAction(`Remove all stored credentials for ${p.label}?`))) return
    try { await api(`/${id}`, { method: "DELETE" }); onSaved() } catch (e) { notify(e.message, "error") }
  }

  return (
    <div className="card">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="card-title flex items-center gap-2">
            {p.connected ? <CheckCircle2 size={18} className="text-green-700" /> : <Circle size={18} className="text-gray-400" />}
            {p.label}
          </h3>
          <p className="card-description">
            Plan {p.plan}
            {p.updated_at && <> · updated {formatDateTime(p.updated_at)}{p.updated_by ? ` by ${p.updated_by}` : ""}</>}
            {p.last_ok_at && <> · last OK {formatDateTime(p.last_ok_at)}</>}
          </p>
          {p.last_error && <p className="text-sm font-semibold text-red-700">Last error: {p.last_error}</p>}
        </div>
        {p.connected && (
          <button type="button" className="btn btn-secondary flex items-center gap-1" onClick={disconnect}>
            <Trash2 size={16} /> Disconnect
          </button>
        )}
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-2">
        {Object.keys(p.secrets).map((f) => (
          <label key={f} className="block text-sm">
            <span className="flex items-center gap-1 font-medium">
              <KeyRound size={14} /> {label(f)}
              <span className={p.secrets[f] ? "text-green-700" : "text-gray-600"}>({p.secrets[f] ? "set" : "not set"})</span>
            </span>
            {f.endsWith("_json") ? (
              <textarea className="form-input mt-1 w-full font-mono" rows={3} autoComplete="off" spellCheck={false}
                placeholder={p.secrets[f] ? "Stored. Paste a new key file to replace it." : "Paste the key file contents"}
                value={secrets[f] || ""} onChange={(e) => setSecrets({ ...secrets, [f]: e.target.value })} />
            ) : (
              <input type="password" className="form-input mt-1 w-full" autoComplete="new-password"
                placeholder={p.secrets[f] ? "Stored. Type to replace." : ""}
                value={secrets[f] || ""} onChange={(e) => setSecrets({ ...secrets, [f]: e.target.value })} />
            )}
          </label>
        ))}
        {Object.keys(p.settings).map((f) => (
          <label key={f} className="block text-sm">
            <span className="font-medium">{label(f)}</span>
            <input className="form-input mt-1 w-full font-mono" placeholder='text, or {"SFW": "…", "COGENTIX": "…", "BIM": "…"}'
              value={settings[f] || ""} onChange={(e) => setSettings({ ...settings, [f]: e.target.value })} />
          </label>
        ))}
      </div>
      <div className="mt-4">
        <button type="button" className="btn btn-primary" disabled={saving} onClick={save}>{saving ? "Saving…" : "Save"}</button>
      </div>
    </div>
  )
}

export default function MarketingIntegrations() {
  const [data, setData] = useState(null)
  const load = async () => {
    try { setData(await api("")) } catch (e) { notify(e.message, "error") }
  }
  useEffect(() => { load() }, [])

  if (!data) return <div className="card">Loading…</div>
  const platforms = Object.entries(data).filter(([k]) => !k.startsWith("_"))
  return (
    <div className="space-y-4">
      <div className="card">
        <div className="card-header flex items-center justify-between">
          <div>
            <h2 className="card-title">Integrations</h2>
            <p className="card-description">
              Tokens are encrypted on the server and never shown again: a field says only whether it is set.
              Steps for each platform are in docs/marketing/MARKETING_AUDIT.md §4.
            </p>
          </div>
          <button type="button" className="btn btn-secondary flex items-center gap-1" onClick={load}><RefreshCw size={16} /> Refresh</button>
        </div>
        {!data._key_configured && (
          <p className="font-semibold text-red-700">The server has no encryption key (MARKETING_SECRETS_KEY), so tokens cannot be saved yet.</p>
        )}
      </div>
      {platforms.map(([id, p]) => <Platform key={id} id={id} p={p} onSaved={load} />)}
    </div>
  )
}
