import { useEffect, useRef, useState } from "react"
import { Upload, Trash2, Download, FileText, Film } from "lucide-react"
import { buildApiUrl } from "../../config"
import { authFetch } from "../../utils/api"
import { confirmAction, notify } from "../../utils/notify"
import { formatDate } from "../../utils/format"

// Marketing > Media: images, video and documents for marketing use.
const sizeText = (b) => (b >= 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`)

function Preview({ item }) {
  const [src, setSrc] = useState(null)
  useEffect(() => {
    if (!item.mime_type?.startsWith("image/")) return undefined
    let url
    authFetch(buildApiUrl(`/api/marketing/media/${item._id}/file`))
      .then((r) => (r.ok ? r.blob() : null))
      .then((b) => { if (b) { url = URL.createObjectURL(b); setSrc(url) } })
    return () => url && URL.revokeObjectURL(url)
  }, [item._id, item.mime_type])
  if (src) return <img src={src} alt={item.filename} className="h-36 w-full rounded-lg object-cover" />
  const Icon = item.mime_type?.startsWith("video/") ? Film : FileText
  return <div className="flex h-36 w-full items-center justify-center rounded-lg bg-cogentix-orange-50"><Icon size={40} className="text-cogentix-orange-700" /></div>
}

export default function MarketingMedia() {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const input = useRef(null)

  const load = async () => {
    try {
      const res = await authFetch(buildApiUrl("/api/marketing/media"))
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || "Could not load the media library")
      setItems(data.media || [])
    } catch (e) { notify(e.message, "error") }
    finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])

  const upload = async (files) => {
    setUploading(true)
    for (const f of Array.from(files || [])) {
      const body = new FormData()
      body.append("file", f)
      const res = await authFetch(buildApiUrl("/api/marketing/media"), { method: "POST", body })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) notify(`${f.name}: ${data.detail || "upload failed"}`, "error")
    }
    setUploading(false)
    load()
  }

  const open = async (item) => {
    const res = await authFetch(buildApiUrl(`/api/marketing/media/${item._id}/file`))
    if (!res.ok) { notify("Could not open the file", "error"); return }
    const url = URL.createObjectURL(await res.blob())
    const a = document.createElement("a")
    a.href = url
    a.download = item.filename
    a.click()
    setTimeout(() => URL.revokeObjectURL(url), 30000)
  }

  const remove = async (item) => {
    if (!(await confirmAction(`Delete ${item.filename}?`, { confirmText: "Delete" }))) return
    await authFetch(buildApiUrl(`/api/marketing/media/${item._id}`), { method: "DELETE" })
    load()
  }

  return (
    <div className="p-6" onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); upload(e.dataTransfer.files) }}>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="cx-page-title">Media library</h1>
          <p className="text-gray-600">Images, video and documents for marketing — drop files anywhere on this page</p>
        </div>
        <button className="btn btn-primary" onClick={() => input.current?.click()} disabled={uploading}>
          <Upload size={16} /> {uploading ? "Uploading…" : "Upload"}
        </button>
        <input ref={input} type="file" multiple hidden onChange={(e) => { upload(e.target.files); e.target.value = "" }}
               accept="image/*,video/*,application/pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.csv" />
      </div>
      {loading ? <div className="loading-spinner" /> : items.length === 0 ? (
        <div className="empty-state py-16"><h3>No files yet</h3><p>Upload images, video or documents (up to 25 MB each).</p></div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {items.map((m) => (
            <div key={m._id} className="stat-card p-3">
              <Preview item={m} />
              <div className="mt-2 truncate font-semibold" title={m.filename}>{m.filename}</div>
              <div className="text-gray-600">{sizeText(m.size_bytes)} · {formatDate(m.uploaded_at)}</div>
              <div className="mt-2 flex gap-2">
                <button className="btn btn-secondary btn-sm" onClick={() => open(m)}><Download size={14} /> Download</button>
                <button className="btn btn-secondary btn-sm" aria-label="Delete" title="Delete" onClick={() => remove(m)}><Trash2 size={14} /></button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
