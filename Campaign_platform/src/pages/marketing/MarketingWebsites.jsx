import { useEffect, useState } from "react"
import { RefreshCw, Plus, Trash2, Globe, Pencil, Send, Copy } from "lucide-react"
import { buildApiUrl } from "../../config"
import { authFetch } from "../../utils/api"
import { confirmAction, notify } from "../../utils/notify"
import { formatDateTime } from "../../utils/format"

// Marketing > Websites: the company sites' health, and blog posts.
const api = async (path, opts = {}) => {
  const res = await authFetch(buildApiUrl(`/api/marketing${path}`), {
    headers: { "Content-Type": "application/json" }, ...opts,
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`)
  return data
}

const EMPTY_POST = { title: "", site_id: "", excerpt: "", body: "", meta_title: "", meta_description: "", status: "draft" }

function Health({ check }) {
  if (!check) return <span className="text-gray-600">Not checked yet</span>
  return (
    <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <span className={check.up ? "font-semibold text-green-700" : "font-semibold text-red-700"}>
        {check.up ? `Up (${check.status_code})` : `Down${check.status_code ? ` (${check.status_code})` : ""}`}
      </span>
      {check.response_ms != null && <span>{(check.response_ms / 1000).toFixed(1)} s</span>}
      {check.ssl_days_left != null && (
        <span className={check.ssl_days_left < 15 ? "font-semibold text-red-700" : ""}>SSL {check.ssl_days_left} days left</span>
      )}
      {check.up && !check.has_meta_description && <span className="text-cogentix-orange-700">No meta description</span>}
    </span>
  )
}

export default function MarketingWebsites() {
  const [sites, setSites] = useState([])
  const [posts, setPosts] = useState([])
  const [loading, setLoading] = useState(true)
  const [checking, setChecking] = useState(false)
  const [newSite, setNewSite] = useState(null)
  const [editing, setEditing] = useState(null)
  const [saving, setSaving] = useState(false)

  const load = async () => {
    try {
      const [s, p] = await Promise.all([api("/websites"), api("/posts")])
      setSites(s.websites || [])
      setPosts(p.posts || [])
    } catch (e) {
      notify(e.message, "error")
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { load() }, [])

  const checkAll = async () => {
    setChecking(true)
    try { setSites((await api("/websites/check", { method: "POST" })).websites || []) }
    catch (e) { notify(e.message, "error") }
    finally { setChecking(false) }
  }

  const saveSite = async () => {
    try {
      await api("/websites", { method: "POST", body: JSON.stringify(newSite) })
      setNewSite(null)
      load()
    } catch (e) { notify(e.message, "error") }
  }

  const removeSite = async (s) => {
    if (!(await confirmAction(`Remove ${s.name} from the list?`, { confirmText: "Remove" }))) return
    await api(`/websites/${s._id}`, { method: "DELETE" }).catch((e) => notify(e.message, "error"))
    load()
  }

  const savePost = async () => {
    setSaving(true)
    try {
      const body = JSON.stringify(editing)
      if (editing._id) await api(`/posts/${editing._id}`, { method: "PUT", body })
      else await api("/posts", { method: "POST", body })
      setEditing(null)
      load()
      notify("Post saved", "success")
    } catch (e) { notify(e.message, "error") }
    finally { setSaving(false) }
  }

  const publish = async (p) => {
    if (!(await confirmAction(`Send "${p.title}" to the website as a draft for review there?`, { confirmText: "Send to site" }))) return
    try {
      const r = await api(`/posts/${p._id}/publish`, { method: "POST" })
      notify(`Sent to the site${r.link ? `: ${r.link}` : ""}`, "success")
      load()
    } catch (e) { notify(e.message, "error") }
  }

  const removePost = async (p) => {
    if (!(await confirmAction(`Delete the post "${p.title}"?`, { confirmText: "Delete" }))) return
    await api(`/posts/${p._id}`, { method: "DELETE" }).catch((e) => notify(e.message, "error"))
    load()
  }

  const copyHtml = (p) => {
    navigator.clipboard.writeText(`<h1>${p.title}</h1>\n${p.body || ""}`)
    notify("HTML copied", "success")
  }

  const siteName = (id) => sites.find((s) => s._id === id)?.name || "—"
  const field = "w-full rounded-lg border border-gray-300 px-3 py-2"

  return (
    <div className="p-6">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="cx-page-title">Websites</h1>
          <p className="text-gray-600">Health of the company websites, and blog posts</p>
        </div>
        <div className="flex gap-2">
          <button className="btn btn-secondary" onClick={() => setNewSite({ name: "", url: "" })}><Plus size={16} /> Add website</button>
          <button className="btn btn-primary" onClick={checkAll} disabled={checking}>
            <RefreshCw size={16} className={checking ? "animate-spin" : ""} /> {checking ? "Checking…" : "Check all now"}
          </button>
        </div>
      </div>

      {loading ? <div className="loading-spinner" /> : (
        <>
          <div className="mb-8 grid gap-4 md:grid-cols-3">
            {sites.map((s) => (
              <div key={s._id} className="stat-card p-4">
                <div className="mb-2 flex items-start justify-between gap-2">
                  <div>
                    <div className="flex items-center gap-2 font-semibold text-cogentix-navy"><Globe size={16} /> {s.name}</div>
                    <a href={s.url} target="_blank" rel="noreferrer">{s.url.replace(/^https?:\/\//, "")}</a>
                  </div>
                  <button className="action-btn" title="Remove" aria-label="Remove" onClick={() => removeSite(s)}><Trash2 size={16} /></button>
                </div>
                <Health check={s.last_check} />
                {s.last_check?.title && <p className="mt-2 text-gray-600">Title: {s.last_check.title}</p>}
                {s.last_check?.checked_at && <p className="mt-1 text-gray-600">Checked {formatDateTime(s.last_check.checked_at)}</p>}
              </div>
            ))}
          </div>

          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-xl font-bold text-cogentix-navy">Blog posts</h2>
            <button className="btn btn-primary" onClick={() => setEditing({ ...EMPTY_POST, site_id: sites[0]?._id || "" })}>
              <Plus size={16} /> New post
            </button>
          </div>
          {posts.length === 0 ? (
            <div className="empty-state py-10"><h3>No posts yet</h3><p>Write one with "New post".</p></div>
          ) : (
            <table className="w-full text-left">
              <thead><tr><th className="py-2">Title</th><th className="py-2">Website</th><th className="py-2">Status</th>
                <th className="py-2">Updated</th><th className="py-2" /></tr></thead>
              <tbody>
                {posts.map((p) => (
                  <tr key={p._id} className="border-t border-gray-100">
                    <td className="py-2 font-semibold">{p.title}</td>
                    <td className="py-2">{siteName(p.site_id)}</td>
                    <td className="py-2"><span className="status-badge" style={{ background: "#fff7ed" }}>
                      {p.status === "sent_to_site" ? "Sent to site" : p.status === "ready" ? "Ready" : "Draft"}</span>
                      {p.published_url && <> · <a href={p.published_url} target="_blank" rel="noreferrer">open</a></>}
                    </td>
                    <td className="py-2">{formatDateTime(p.updated_at)}</td>
                    <td className="py-2">
                      <div className="flex justify-end gap-2">
                        <button className="action-btn" title="Edit" aria-label="Edit" onClick={() => setEditing(p)}><Pencil size={16} /></button>
                        <button className="action-btn" title="Copy HTML" aria-label="Copy HTML" onClick={() => copyHtml(p)}><Copy size={16} /></button>
                        <button className="action-btn" title="Send to the website (WordPress)" aria-label="Send to website" onClick={() => publish(p)}><Send size={16} /></button>
                        <button className="action-btn" title="Delete" aria-label="Delete" onClick={() => removePost(p)}><Trash2 size={16} /></button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}

      {newSite && (
        <div className="modal-overlay fixed inset-0 z-[2000] flex items-center justify-center p-4" onClick={() => setNewSite(null)}>
          <div className="modal-content w-full max-w-md p-6" onClick={(e) => e.stopPropagation()}>
            <h3 className="mb-4 text-xl font-bold">Add website</h3>
            <label className="mb-1 block font-medium">Name</label>
            <input className={`${field} mb-3`} value={newSite.name} onChange={(e) => setNewSite({ ...newSite, name: e.target.value })} />
            <label className="mb-1 block font-medium">Address</label>
            <input className={`${field} mb-4`} placeholder="https://example.com" value={newSite.url}
                   onChange={(e) => setNewSite({ ...newSite, url: e.target.value })} />
            <div className="flex justify-end gap-2">
              <button className="btn btn-secondary" onClick={() => setNewSite(null)}>Cancel</button>
              <button className="btn btn-primary" onClick={saveSite}>Add</button>
            </div>
          </div>
        </div>
      )}

      {editing && (
        <div className="modal-overlay fixed inset-0 z-[2000] flex items-center justify-center p-4" onClick={() => setEditing(null)}>
          <div className="modal-content max-h-[90vh] w-full max-w-3xl overflow-y-auto p-6" onClick={(e) => e.stopPropagation()}>
            <h3 className="mb-4 text-xl font-bold">{editing._id ? "Edit post" : "New post"}</h3>
            <div className="grid gap-3 md:grid-cols-2">
              <div className="md:col-span-2">
                <label className="mb-1 block font-medium">Title</label>
                <input className={field} value={editing.title} onChange={(e) => setEditing({ ...editing, title: e.target.value })} />
              </div>
              <div>
                <label className="mb-1 block font-medium">Website</label>
                <select className={field} value={editing.site_id || ""} onChange={(e) => setEditing({ ...editing, site_id: e.target.value })}>
                  {sites.map((s) => <option key={s._id} value={s._id}>{s.name}</option>)}
                </select>
              </div>
              <div>
                <label className="mb-1 block font-medium">Status</label>
                <select className={field} value={editing.status || "draft"} onChange={(e) => setEditing({ ...editing, status: e.target.value })}>
                  <option value="draft">Draft</option>
                  <option value="ready">Ready</option>
                </select>
              </div>
              <div className="md:col-span-2">
                <label className="mb-1 block font-medium">Summary</label>
                <textarea className={field} rows={2} value={editing.excerpt || ""} onChange={(e) => setEditing({ ...editing, excerpt: e.target.value })} />
              </div>
              <div className="md:col-span-2">
                <label className="mb-1 block font-medium">Body (HTML allowed)</label>
                <textarea className={`${field} font-mono`} rows={12} value={editing.body || ""} onChange={(e) => setEditing({ ...editing, body: e.target.value })} />
              </div>
              <div>
                <label className="mb-1 block font-medium">SEO title</label>
                <input className={field} value={editing.meta_title || ""} onChange={(e) => setEditing({ ...editing, meta_title: e.target.value })} />
              </div>
              <div>
                <label className="mb-1 block font-medium">SEO description</label>
                <input className={field} value={editing.meta_description || ""} onChange={(e) => setEditing({ ...editing, meta_description: e.target.value })} />
              </div>
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <button className="btn btn-secondary" onClick={() => setEditing(null)}>Cancel</button>
              <button className="btn btn-primary" onClick={savePost} disabled={saving || !editing.title?.trim()}>{saving ? "Saving…" : "Save"}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
