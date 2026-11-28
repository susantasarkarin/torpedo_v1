import { useEffect, useState } from "react"
import { RefreshCw, Plus, Trash2, Globe, Pencil, Send, Copy, ExternalLink } from "lucide-react"
import { confirmAction, notify } from "../../utils/notify"
import { formatDateTime } from "../../utils/format"
import { marketingApi } from "./api"

// Marketing > Websites: the company sites' health, and blog posts.
const api = marketingApi("/api/marketing")

const EMPTY_POST = { title: "", site_id: "", excerpt: "", body: "", meta_title: "", meta_description: "", status: "draft" }

function Health({ check }) {
  if (!check) return <span className="mk-pill">Not checked yet</span>
  return (
    <div className="mk-site-stats">
      <span className={`mk-pill ${check.up ? "ok" : "bad"}`}>
        <span className="mk-dot" />
        {check.up ? `Up · ${check.status_code}` : `Down${check.status_code ? ` · ${check.status_code}` : ""}`}
      </span>
      {check.response_ms != null && <span className={`mk-pill ${check.response_ms > 2000 ? "warn" : ""}`}>{(check.response_ms / 1000).toFixed(1)} s</span>}
      {check.ssl_days_left != null && (
        <span className={`mk-pill ${check.ssl_days_left < 15 ? "bad" : ""}`}>SSL {check.ssl_days_left} days</span>
      )}
      {check.up && !check.has_meta_description && <span className="mk-pill warn">No meta description</span>}
    </div>
  )
}

const postStatus = (p) => {
  if (p.status === "published") return p.live === false ? ["Removed from site", ""] : ["Live", "ok"]
  if (p.status === "sent_to_site") return ["Sent to site", "info"]
  if (p.status === "ready") return ["Ready", "warn"]
  return ["Draft", ""]
}

const visits = (n) => (n == null || n === 0 ? <span className="mk-muted">{n == null ? "—" : 0}</span> : n.toLocaleString())

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

  const [syncing, setSyncing] = useState(false)
  const syncPosts = async () => {
    setSyncing(true)
    try {
      const r = await api("/posts/sync", { method: "POST" })
      notify(r.new?.length ? `${r.new.length} new post(s) found and sent to search engines` : "Posts and visits are up to date", "success")
      load()
    } catch (e) { notify(e.message, "error") }
    finally { setSyncing(false) }
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
  const field = "form-input"

  return (
    <div>
      <div className="mk-section-head">
        <div>
          <h1 className="cx-page-title">Websites</h1>
          <p>Uptime, speed and SSL for the company websites, checked automatically.</p>
        </div>
        <div className="mk-actions">
          <button className="btn btn-secondary" onClick={() => setNewSite({ name: "", url: "" })}><Plus size={16} /> Add website</button>
          <button className="btn btn-primary" onClick={checkAll} disabled={checking}>
            <RefreshCw size={16} className={checking ? "animate-spin" : ""} /> {checking ? "Checking…" : "Check all now"}
          </button>
        </div>
      </div>

      {loading ? <div className="loading-spinner" /> : (
        <>
          {sites.length === 0 ? (
            <div className="empty-state mb-10 py-10"><h3>No websites yet</h3><p>Add one to start health checks.</p></div>
          ) : (
            <div className="mk-sites">
              {sites.map((s) => {
                const c = s.last_check
                return (
                  <div key={s._id} className={`mk-site-card ${!c ? "is-unknown" : c.up ? "" : "is-down"}`}>
                    <div className="mk-site-head">
                      <div className="min-w-0">
                        <div className="mk-site-name"><Globe size={16} /> {s.name}</div>
                        <a className="mk-site-url" href={s.url} target="_blank" rel="noreferrer">{s.url.replace(/^https?:\/\//, "")}</a>
                      </div>
                      <button className="mk-icon-btn danger" title={`Remove ${s.name}`} aria-label={`Remove ${s.name}`} onClick={() => removeSite(s)}><Trash2 size={16} /></button>
                    </div>
                    <Health check={c} />
                    {c?.title && <div className="mk-site-title" title={c.title}>{c.title}</div>}
                    {c?.checked_at && <div className="mk-site-foot">Checked {formatDateTime(c.checked_at)}</div>}
                  </div>
                )
              })}
            </div>
          )}

          <div className="mk-section-head">
            <div>
              <h2>Blog posts <span className="mk-muted font-normal">({posts.length})</span></h2>
              <p>Posts on the websites appear here automatically (every 30 minutes and after each deploy). Visits come from the website tracker.</p>
            </div>
            <div className="mk-actions">
              <button className="btn btn-secondary" onClick={syncPosts} disabled={syncing} title="Read every site's sitemap, refresh visits, tell search engines about new posts">
                <RefreshCw size={16} className={syncing ? "animate-spin" : ""} /> {syncing ? "Syncing…" : "Sync posts"}
              </button>
              <button className="btn btn-primary" onClick={() => setEditing({ ...EMPTY_POST, site_id: sites[0]?._id || "" })}>
                <Plus size={16} /> New post
              </button>
            </div>
          </div>
          {posts.length === 0 ? (
            <div className="empty-state py-10"><h3>No posts yet</h3><p>Write one with "New post".</p></div>
          ) : (
            <div className="mk-table-wrap">
              <table className="min-w-[760px]">
                <thead><tr><th>Title</th><th>Website</th><th>Status</th><th>Published</th>
                  <th className="num">Visits (30 d)</th><th className="num">Visits (total)</th><th><span className="sr-only">Actions</span></th></tr></thead>
                <tbody>
                  {posts.map((p) => {
                    const [statusLabel, statusTone] = postStatus(p)
                    return (
                      <tr key={p._id}>
                        <td className="font-semibold">{p.title}</td>
                        <td className="nowrap">{siteName(p.site_id)}</td>
                        <td><span className={`mk-pill ${statusTone}`}>{statusLabel}</span></td>
                        <td className="nowrap">{formatDateTime(p.published_at || p.updated_at)}</td>
                        <td className="num">{visits(p.views_30d)}</td>
                        <td className="num">{visits(p.views_total)}</td>
                        <td>
                          <div className="flex items-center justify-end gap-1">
                            {p.published_url && (
                              <a className="mk-icon-btn" href={p.published_url} target="_blank" rel="noreferrer" title="Open post" aria-label={`Open ${p.title}`}><ExternalLink size={16} /></a>
                            )}
                            {p.source !== "site" && (
                              <>
                                <button className="mk-icon-btn" title="Edit" aria-label="Edit" onClick={() => setEditing(p)}><Pencil size={16} /></button>
                                <button className="mk-icon-btn" title="Copy HTML" aria-label="Copy HTML" onClick={() => copyHtml(p)}><Copy size={16} /></button>
                                <button className="mk-icon-btn" title="Send to the website (WordPress)" aria-label="Send to website" onClick={() => publish(p)}><Send size={16} /></button>
                                <button className="mk-icon-btn danger" title="Delete" aria-label="Delete" onClick={() => removePost(p)}><Trash2 size={16} /></button>
                              </>
                            )}
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {newSite && (
        <div className="modal-overlay fixed inset-0 z-[2000] flex items-center justify-center p-4" onClick={() => setNewSite(null)}>
          <div className="modal-content w-full max-w-md p-6" onClick={(e) => e.stopPropagation()}>
            <h3 className="mb-4 text-xl font-bold">Add website</h3>
            <label className="mk-label">Name</label>
            <input className={`${field} mb-4`} value={newSite.name} onChange={(e) => setNewSite({ ...newSite, name: e.target.value })} />
            <label className="mk-label">Address</label>
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
                <label className="mk-label">Title</label>
                <input className={field} value={editing.title} onChange={(e) => setEditing({ ...editing, title: e.target.value })} />
              </div>
              <div>
                <label className="mk-label">Website</label>
                <select className={field} value={editing.site_id || ""} onChange={(e) => setEditing({ ...editing, site_id: e.target.value })}>
                  {sites.map((s) => <option key={s._id} value={s._id}>{s.name}</option>)}
                </select>
              </div>
              <div>
                <label className="mk-label">Status</label>
                <select className={field} value={editing.status || "draft"} onChange={(e) => setEditing({ ...editing, status: e.target.value })}>
                  <option value="draft">Draft</option>
                  <option value="ready">Ready</option>
                </select>
              </div>
              <div className="md:col-span-2">
                <label className="mk-label">Summary</label>
                <textarea className={field} rows={2} value={editing.excerpt || ""} onChange={(e) => setEditing({ ...editing, excerpt: e.target.value })} />
              </div>
              <div className="md:col-span-2">
                <label className="mk-label">Body (HTML allowed)</label>
                <textarea className={`${field} font-mono text-sm`} rows={12} value={editing.body || ""} onChange={(e) => setEditing({ ...editing, body: e.target.value })} />
              </div>
              <div>
                <label className="mk-label">SEO title</label>
                <input className={field} value={editing.meta_title || ""} onChange={(e) => setEditing({ ...editing, meta_title: e.target.value })} />
              </div>
              <div>
                <label className="mk-label">SEO description</label>
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
