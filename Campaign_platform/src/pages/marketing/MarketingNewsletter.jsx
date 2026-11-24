import { useCallback, useEffect, useRef, useState } from "react"
import { AlertTriangle, ArrowLeft, Image as ImageIcon, Monitor, Plus, RefreshCw, Save, Search, Smartphone, Users } from "lucide-react"
import { buildApiUrl } from "../../config"
import { authFetch } from "../../utils/api"
import { confirmAction, notify } from "../../utils/notify"
import { formatDateTime } from "../../utils/format"
import { BUS, BU_NAMES, marketingApi } from "./api"

// Marketing > Newsletter: design once, send each company's edition from its own mailboxes.
const api = marketingApi("/api/marketing/newsletter")
const mediaApi = marketingApi("/api/marketing")

const TABS = [["newsletters", "Newsletters"], ["contacts", "Mailbox contacts"]]
const STATUS_CLASS = {
  draft: "bg-gray-200 text-gray-800",
  scheduled: "bg-blue-100 text-blue-800",
  sending: "bg-amber-100 text-amber-800",
  paused: "bg-amber-100 text-amber-800",
  sent: "bg-green-100 text-green-800",
  cancelled: "bg-red-100 text-red-800",
}
const RECIPIENT_STATUSES = ["queued", "sending", "sent", "failed", "skipped"]
const TOKEN_HINT = "Tokens: {{first_name}} {{name}} {{company}} {{company_name}}"
const BLOCK_TYPES = ["heading", "text", "image", "button", "divider", "spacer"]
const BLOCK_LABEL = { heading: "Heading", text: "Text", image: "Image", button: "Button", divider: "Divider", spacer: "Spacer" }
const NEW_BLOCK = {
  heading: { type: "heading", text: "", level: 2, align: "left" },
  text: { type: "text", text: "", align: "left" },
  image: { type: "image", src: "", alt: "", link: "", width: 536 },
  button: { type: "button", label: "Call to action", url: "https://", align: "center" },
  divider: { type: "divider" },
  spacer: { type: "spacer", height: 24 },
}
const ALIGNS = ["left", "center", "right"]
const DEFAULT_AUDIENCE = { sources: [], mailbox_scope: "bu", extra_emails: [], exclude_emails: [] }
const OPTIONAL_KEYS = ["alt", "link", "align", "width", "height"]

// Helpers

const parseEmails = (text) => text.split(/[\s,;]+/).map((s) => s.trim()).filter(Boolean)

// Drops empty optional keys so the server gets exactly the block shape it expects.
function cleanBlock(block) {
  const out = { ...block }
  OPTIONAL_KEYS.forEach((k) => {
    if (out[k] === "" || out[k] == null) delete out[k]
  })
  return out
}

function toDraft(doc) {
  return {
    name: doc.name || "",
    subject: doc.subject || "",
    preheader: doc.preheader || "",
    blocks: doc.blocks || [],
    bus: doc.bus || [],
    senders: doc.senders || {},
    audience: doc.audience || {},
  }
}

function toPayload(d) {
  return {
    name: d.name,
    subject: d.subject,
    preheader: d.preheader,
    blocks: d.blocks.map(cleanBlock),
    bus: d.bus,
    senders: Object.fromEntries(d.bus.map((b) => [b, d.senders[b] || []])),
    audience: Object.fromEntries(d.bus.map((b) => [b, { ...DEFAULT_AUDIENCE, ...(d.audience[b] || {}) }])),
  }
}

function StatusBadge({ status }) {
  return <span className={`rounded px-2 py-0.5 text-xs font-semibold ${STATUS_CLASS[status] || ""}`}>{status}</span>
}

function Field({ label, hint, children }) {
  return (
    <label className="block text-sm font-semibold">
      <span>{label}</span>
      <span className="mt-1 block font-normal">{children}</span>
      {hint && <span className="mt-1 block text-xs font-normal text-gray-600">{hint}</span>}
    </label>
  )
}

// Thumbnail fetched with the auth header, same approach as MarketingMedia.
function Thumb({ item }) {
  const [src, setSrc] = useState(null)
  useEffect(() => {
    let alive = true
    let url
    authFetch(buildApiUrl(`/api/marketing/media/${item._id}/file`))
      .then((r) => (r.ok ? r.blob() : null))
      .then((b) => {
        if (b && alive) {
          url = URL.createObjectURL(b)
          setSrc(url)
        }
      })
      .catch(() => {})
    return () => {
      alive = false
      if (url) URL.revokeObjectURL(url)
    }
  }, [item._id])
  if (!src) return <div className="h-20 w-full rounded bg-gray-100" />
  return <img src={src} alt={item.filename} className="h-20 w-full rounded object-cover" />
}

function MediaPicker({ onPick }) {
  const [items, setItems] = useState(null)
  useEffect(() => {
    const loadMedia = async () => {
      try {
        const data = await mediaApi("/media")
        setItems((data.media || []).filter((m) => m.mime_type?.startsWith("image/")))
      } catch (e) {
        notify(e.message, "error")
        setItems([])
      }
    }
    loadMedia()
  }, [])
  if (!items) return <p className="text-sm text-gray-600">Loading…</p>
  if (items.length === 0) return <p className="text-sm text-gray-600">No images in the media library yet. Upload one under Marketing &gt; Media.</p>
  return (
    <div className="grid grid-cols-2 gap-2 rounded border border-gray-200 p-2 sm:grid-cols-4">
      {items.map((m) => (
        <button key={m._id} type="button" className="rounded p-1 hover:ring-2 hover:ring-gray-400" title={m.filename} onClick={() => onPick(m.stored_name)}>
          <Thumb item={m} />
          <span className="mt-1 block truncate text-xs">{m.filename}</span>
        </button>
      ))}
    </div>
  )
}

// Block builder

function BlockCard({ block, index, count, editable, onChange, onMove, onDuplicate, onDelete }) {
  const [picking, setPicking] = useState(false)
  const set = (key) => (e) => onChange({ [key]: e.target.value })
  const setNum = (key) => (e) => onChange({ [key]: e.target.value === "" ? "" : Number(e.target.value) })
  const isMedia = block.src?.startsWith("media:")
  const alignSelect = (
    <select className="form-input" value={block.align || "left"} onChange={set("align")} aria-label="Alignment">
      {ALIGNS.map((a) => <option key={a} value={a}>{a}</option>)}
    </select>
  )

  return (
    <div className="space-y-2 rounded border border-gray-200 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-semibold">{index + 1}. {BLOCK_LABEL[block.type]}</span>
        <div className="flex flex-wrap gap-1">
          <button type="button" className="btn btn-secondary btn-sm" disabled={!editable || index === 0} onClick={() => onMove(-1)}>Move up</button>
          <button type="button" className="btn btn-secondary btn-sm" disabled={!editable || index === count - 1} onClick={() => onMove(1)}>Move down</button>
          <button type="button" className="btn btn-secondary btn-sm" disabled={!editable} onClick={onDuplicate}>Duplicate</button>
          <button type="button" className="btn btn-secondary btn-sm" disabled={!editable} onClick={onDelete}>Delete</button>
        </div>
      </div>
      <fieldset disabled={!editable} className="space-y-2">
        {block.type === "heading" && (
          <div className="grid gap-2 md:grid-cols-4">
            <input className="form-input md:col-span-2" placeholder="Heading text" value={block.text || ""} onChange={set("text")} />
            <select className="form-input" value={block.level || 2} onChange={setNum("level")} aria-label="Heading level">
              {[1, 2, 3].map((l) => <option key={l} value={l}>Level {l}</option>)}
            </select>
            {alignSelect}
          </div>
        )}
        {block.type === "text" && (
          <div className="grid gap-2 md:grid-cols-4">
            <textarea className="form-input md:col-span-3" rows={4} placeholder="Paragraphs are separated by a blank line. Use **bold** and [label](https://url)."
              value={block.text || ""} onChange={set("text")} />
            {alignSelect}
            <p className="text-xs text-gray-600 md:col-span-3">{TOKEN_HINT}</p>
          </div>
        )}
        {block.type === "image" && (
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="text-gray-600">{block.src ? (isMedia ? `Library image: ${block.src.slice(6)}` : block.src) : "No image chosen"}</span>
              <button type="button" className="btn btn-secondary btn-sm flex items-center gap-1" onClick={() => setPicking((p) => !p)}>
                <ImageIcon size={14} /> {picking ? "Hide library" : "Choose from media library"}
              </button>
            </div>
            {picking && <MediaPicker onPick={(name) => { onChange({ src: `media:${name}` }); setPicking(false) }} />}
            <div className="grid gap-2 md:grid-cols-2">
              <input className="form-input" placeholder="…or paste an https:// image URL" value={isMedia ? "" : block.src || ""} onChange={set("src")} />
              <input className="form-input" placeholder="Alt text" value={block.alt || ""} onChange={set("alt")} />
              <input className="form-input" placeholder="Link on click (optional, https://)" value={block.link || ""} onChange={set("link")} />
              <label className="flex items-center gap-2 text-sm">
                Width (80–536 px)
                <input type="number" min={80} max={536} className="form-input w-28" value={block.width ?? ""} onChange={setNum("width")} />
              </label>
            </div>
          </div>
        )}
        {block.type === "button" && (
          <div className="grid gap-2 md:grid-cols-4">
            <input className="form-input" placeholder="Button label" value={block.label || ""} onChange={set("label")} />
            <input className="form-input md:col-span-2" placeholder="https://" value={block.url || ""} onChange={set("url")} />
            {alignSelect}
          </div>
        )}
        {block.type === "divider" && <p className="text-sm text-gray-600">Horizontal line across the email.</p>}
        {block.type === "spacer" && (
          <label className="flex items-center gap-2 text-sm">
            Height (8–80 px)
            <input type="number" min={8} max={80} className="form-input w-28" value={block.height ?? ""} onChange={setNum("height")} />
          </label>
        )}
      </fieldset>
    </div>
  )
}

function BlockEditor({ blocks, editable, onChange }) {
  const setAt = (i, patch) => onChange(blocks.map((b, j) => (j === i ? { ...b, ...patch } : b)))
  const move = (i, dir) => {
    const j = i + dir
    if (j < 0 || j >= blocks.length) return
    const next = [...blocks]
    ;[next[i], next[j]] = [next[j], next[i]]
    onChange(next)
  }
  const duplicate = (i) => {
    const next = [...blocks]
    next.splice(i + 1, 0, { ...blocks[i] })
    onChange(next)
  }
  const remove = (i) => onChange(blocks.filter((_, j) => j !== i))
  const add = (type) => onChange([...blocks, { ...NEW_BLOCK[type] }])

  return (
    <section className="card space-y-4">
      <h3 className="card-title">2. Content</h3>
      {blocks.length === 0 && <p className="text-sm text-gray-600">No blocks yet. Add one below.</p>}
      {blocks.map((b, i) => (
        <BlockCard
          key={i}
          block={b}
          index={i}
          count={blocks.length}
          editable={editable}
          onChange={(patch) => setAt(i, patch)}
          onMove={(dir) => move(i, dir)}
          onDuplicate={() => duplicate(i)}
          onDelete={() => remove(i)}
        />
      ))}
      <div className="flex flex-wrap gap-2">
        {BLOCK_TYPES.map((t) => (
          <button key={t} type="button" className="btn btn-secondary btn-sm flex items-center gap-1" disabled={!editable} onClick={() => add(t)}>
            <Plus size={14} /> Add {BLOCK_LABEL[t].toLowerCase()}
          </button>
        ))}
      </div>
    </section>
  )
}

// Preview

function Preview({ id, content, bu, bus, onBu }) {
  const [out, setOut] = useState(null)
  const [loading, setLoading] = useState(false)
  const [mobile, setMobile] = useState(false)
  const [error, setError] = useState("")
  const seq = useRef(0)
  const { subject, preheader, blocks } = content

  const refresh = useCallback(async () => {
    const mine = ++seq.current
    setLoading(true)
    try {
      const res = await api(`/${id}/preview?bu=${bu}`, {
        method: "POST",
        body: JSON.stringify({ subject, preheader, blocks: blocks.map(cleanBlock) }),
      })
      if (mine === seq.current) {
        setOut(res)
        setError("")
      }
    } catch (e) {
      if (mine === seq.current) setError(e.message)
    } finally {
      if (mine === seq.current) setLoading(false)
    }
  }, [id, bu, subject, preheader, blocks])

  // Debounced auto-refresh after edits.
  useEffect(() => {
    const timer = setTimeout(refresh, 800)
    return () => clearTimeout(timer)
  }, [refresh])

  return (
    <section className="card space-y-3">
      <h3 className="card-title">3. Preview</h3>
      {bus.length === 0 ? (
        <p className="text-sm text-gray-600">Tick a business unit in section 4 to preview its edition.</p>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <select className="form-input" value={bu} onChange={(e) => onBu(e.target.value)} aria-label="Preview business unit">
              {bus.map((b) => <option key={b} value={b}>{BU_NAMES[b]}</option>)}
            </select>
            <button type="button" className="btn btn-secondary btn-sm flex items-center gap-1" onClick={refresh} disabled={loading}>
              <RefreshCw size={14} /> {loading ? "Refreshing…" : "Refresh preview"}
            </button>
            <button type="button" className="btn btn-secondary btn-sm flex items-center gap-1" onClick={() => setMobile((m) => !m)}>
              {mobile ? <Monitor size={14} /> : <Smartphone size={14} />} {mobile ? "Desktop view" : "Mobile view"}
            </button>
          </div>
          {error && <p className="text-sm text-red-700">Preview not updated: {error}</p>}
          {out && <p className="text-sm"><strong>Subject:</strong> {out.subject}</p>}
          <div className="mx-auto" style={{ maxWidth: mobile ? 375 : 600 }}>
            {out ? (
              <iframe srcDoc={out.html} sandbox="" title="Preview" className="w-full rounded border" style={{ height: 600 }} />
            ) : (
              <p className="text-sm text-gray-600">Loading preview…</p>
            )}
          </div>
        </>
      )}
    </section>
  )
}

// Business units and senders

function SendersSection({ meta, draft, editable, update }) {
  const toggleBu = (bu) => {
    update({ bus: draft.bus.includes(bu) ? draft.bus.filter((b) => b !== bu) : [...draft.bus, bu] })
  }
  const toggleSender = (bu, email) => {
    const current = draft.senders[bu] || []
    const next = current.includes(email) ? current.filter((e) => e !== email) : [...current, email]
    update({ senders: { ...draft.senders, [bu]: next } })
  }

  const renderMailbox = (bu, m) => (
    <label key={m.email} className="flex flex-wrap items-center gap-2 text-sm">
      <input type="checkbox" checked={(draft.senders[bu] || []).includes(m.email)} disabled={!editable} onChange={() => toggleSender(bu, m.email)} />
      <span className="font-mono">{m.email}</span>
      {m.display_name && <span className="text-gray-600">{m.display_name}</span>}
      <span className="text-gray-500">sent today: {m.sent_today}</span>
    </label>
  )

  return (
    <section className="card space-y-4">
      <h3 className="card-title">4. Business units &amp; senders</h3>
      <div className="flex flex-wrap gap-4">
        {BUS.map((bu) => (
          <label key={bu} className="flex items-center gap-2 font-semibold">
            <input type="checkbox" checked={draft.bus.includes(bu)} disabled={!editable} onChange={() => toggleBu(bu)} />
            <span className="inline-block h-3 w-3 rounded-full" style={{ background: meta.brands[bu]?.color }} />
            {BU_NAMES[bu]}
          </label>
        ))}
      </div>
      {draft.bus.map((bu) => {
        const mine = meta.mailboxes.filter((m) => m.bu === bu)
        const others = meta.mailboxes.filter((m) => m.bu !== bu)
        return (
          <div key={bu} className="space-y-2 rounded border border-gray-200 p-3">
            <p className="font-semibold">{BU_NAMES[bu]} sends from</p>
            {mine.length === 0 && <p className="text-sm text-gray-600">No mailbox is tagged to this company yet.</p>}
            {mine.map((m) => renderMailbox(bu, m))}
            {others.length > 0 && (
              <>
                <p className="pt-2 text-xs text-gray-500">Other mailboxes</p>
                {others.map((m) => renderMailbox(bu, m))}
              </>
            )}
          </div>
        )
      })}
    </section>
  )
}

// Audience

// Textarea that keeps its own text and reports the parsed email list on each change.
function EmailTextarea({ label, value, disabled, onChange }) {
  const [text, setText] = useState(value.join("\n"))
  return (
    <Field label={label}>
      <textarea
        className="form-input w-full"
        rows={3}
        value={text}
        disabled={disabled}
        onChange={(e) => {
          setText(e.target.value)
          onChange(parseEmails(e.target.value))
        }}
      />
    </Field>
  )
}

function AudienceResult({ result }) {
  return (
    <div className="space-y-2 text-sm">
      <p><strong>{result.count}</strong> recipients for {BU_NAMES[result.bu]}</p>
      <p>By source: {Object.entries(result.by_source || {}).map(([k, n]) => `${k} ${n}`).join(" · ") || "none"}</p>
      <p>Left out: {Object.entries(result.excluded || {}).map(([k, n]) => `${k.replace(/_/g, " ")} ${n}`).join(" · ") || "none"}</p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[480px] text-sm">
          <thead>
            <tr className="border-b text-left text-gray-600">
              <th className="p-2">Email</th><th className="p-2">Name</th><th className="p-2">Company</th><th className="p-2">Sources</th>
            </tr>
          </thead>
          <tbody>
            {(result.sample || []).map((s) => (
              <tr key={s.email} className="border-b">
                <td className="p-2 font-mono">{s.email}</td>
                <td className="p-2">{s.name || "—"}</td>
                <td className="p-2">{s.company || "—"}</td>
                <td className="p-2">{(s.sources || []).join(", ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function AudienceCard({ id, bu, meta, value, editable, onChange, ensureSaved }) {
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)

  const toggleSource = (key) => {
    const has = value.sources.includes(key)
    onChange({ sources: has ? value.sources.filter((s) => s !== key) : [...value.sources, key] })
  }

  const count = async () => {
    setBusy(true)
    try {
      const saved = await ensureSaved()
      if (!saved) return
      setResult(await api(`/${id}/audience?bu=${bu}&sample=25`))
    } catch (e) {
      notify(e.message, "error")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-3 rounded border border-gray-200 p-3">
      <p className="font-semibold">{BU_NAMES[bu]}</p>
      <div className="flex flex-wrap gap-4">
        {Object.entries(meta.sources).map(([key, label]) => (
          <label key={key} className="flex items-center gap-1 text-sm">
            <input type="checkbox" checked={value.sources.includes(key)} disabled={!editable} onChange={() => toggleSource(key)} />
            {label}
          </label>
        ))}
      </div>
      {value.sources.includes("mailbox_contacts") && (
        <Field label="Mailbox contacts">
          <select className="form-input w-full" value={value.mailbox_scope} disabled={!editable} onChange={(e) => onChange({ mailbox_scope: e.target.value })}>
            <option value="bu">Only contacts seen in this company's mailboxes</option>
            <option value="all">Contacts from all mailboxes</option>
          </select>
        </Field>
      )}
      <div className="grid gap-3 md:grid-cols-2">
        <EmailTextarea label="Extra emails" value={value.extra_emails} disabled={!editable} onChange={(extra_emails) => onChange({ extra_emails })} />
        <EmailTextarea label="Exclude emails" value={value.exclude_emails} disabled={!editable} onChange={(exclude_emails) => onChange({ exclude_emails })} />
      </div>
      <button type="button" className="btn btn-secondary" onClick={count} disabled={busy}>{busy ? "Counting…" : "Count recipients"}</button>
      {result && <AudienceResult result={result} />}
    </div>
  )
}

function AudienceSection({ id, meta, draft, editable, update, ensureSaved }) {
  const setAudience = (bu, patch) => {
    update({ audience: { ...draft.audience, [bu]: { ...DEFAULT_AUDIENCE, ...(draft.audience[bu] || {}), ...patch } } })
  }
  return (
    <section className="card space-y-4">
      <h3 className="card-title">5. Audience</h3>
      <p className="text-sm text-gray-600">
        Panel members, unsubscribed / bounced addresses, our own domains and no-reply addresses are always left out.
      </p>
      {draft.bus.length === 0 && <p className="text-sm text-gray-600">Tick at least one business unit in section 4.</p>}
      {draft.bus.map((bu) => (
        <AudienceCard
          key={bu}
          id={id}
          bu={bu}
          meta={meta}
          value={{ ...DEFAULT_AUDIENCE, ...(draft.audience[bu] || {}) }}
          editable={editable}
          onChange={(patch) => setAudience(bu, patch)}
          ensureSaved={ensureSaved}
        />
      ))}
    </section>
  )
}

// Test, approval and status

function SendSection({ id, doc, editable, ensureSaved, applyDoc, onBack, onOpen }) {
  const [testTo, setTestTo] = useState("")
  const [testResult, setTestResult] = useState(null)
  const [mode, setMode] = useState("now")
  const [when, setWhen] = useState("")
  const [busy, setBusy] = useState(false)

  const run = async (fn) => {
    setBusy(true)
    try {
      await fn()
    } catch (e) {
      notify(e.message, "error")
    } finally {
      setBusy(false)
    }
  }

  const sendTest = () => run(async () => {
    const to = parseEmails(testTo)
    if (to.length === 0) {
      notify("Enter at least one test address", "error")
      return
    }
    const saved = await ensureSaved()
    if (!saved) return
    setTestResult(await api(`/${id}/test`, { method: "POST", body: JSON.stringify({ to }) }))
    applyDoc(await api(`/${id}`))
  })

  const canApprove = doc.status === "draft" && doc.test_is_current && (doc.problems || []).length === 0

  const approve = () => run(async () => {
    let scheduled = null
    if (mode === "schedule") {
      if (!when) {
        notify("Pick a date and time to schedule", "error")
        return
      }
      scheduled = new Date(when).toISOString()
    }
    const ok = await confirmAction(
      scheduled ? `Schedule this newsletter for ${formatDateTime(scheduled)}?` : "Send this newsletter now to all recipients?",
      { confirmText: scheduled ? "Approve & schedule" : "Approve & send" },
    )
    if (!ok) return
    const saved = await ensureSaved()
    if (!saved) return
    if (!saved.test_is_current || (saved.problems || []).length > 0) {
      notify("The newsletter changed since the last test. Send a new test before approving.", "error")
      return
    }
    applyDoc(await api(`/${id}/approve`, { method: "POST", body: JSON.stringify(scheduled ? { scheduled_for: scheduled } : {}) }))
    notify(scheduled ? "Newsletter scheduled" : "Sending started", "success")
  })

  const statusAction = (action, confirmText) => run(async () => {
    if (confirmText && !(await confirmAction(confirmText, { confirmText: "Yes" }))) return
    applyDoc(await api(`/${id}/status/${action}`, { method: "POST" }))
  })

  const remove = () => run(async () => {
    if (!(await confirmAction("Delete this draft newsletter?", { confirmText: "Delete" }))) return
    await api(`/${id}`, { method: "DELETE" })
    onBack()
  })

  const duplicate = () => run(async () => {
    const copy = await api(`/${id}/duplicate`, { method: "POST" })
    onOpen(copy._id)
  })

  return (
    <section className="card space-y-4">
      <h3 className="card-title">6. Test &amp; send</h3>

      <div className="space-y-2">
        <Field label="Test addresses (comma separated)">
          <input className="form-input w-full" placeholder="me@example.com, colleague@example.com" value={testTo} onChange={(e) => setTestTo(e.target.value)} />
        </Field>
        <button type="button" className="btn btn-secondary" onClick={sendTest} disabled={busy}>Send test</button>
        {testResult && (
          <ul className="space-y-1 text-sm">
            {testResult.results.map((r, i) => (
              <li key={i} className={r.ok ? "text-green-700" : "text-red-700"}>
                {r.bu} · from {r.from} to {String(r.to)}: {r.ok ? "sent" : r.error || "failed"}
              </li>
            ))}
          </ul>
        )}
        {doc.test_is_current
          ? <p className="text-sm font-semibold text-green-700">Test is up to date</p>
          : <p className="text-sm font-semibold text-amber-700">Send a test of the current version before approving</p>}
      </div>

      <div className="space-y-2 rounded border border-gray-200 p-3">
        <div className="flex flex-wrap items-center gap-4 text-sm">
          <label className="flex items-center gap-2">
            <input type="radio" name={`send-mode-${id}`} checked={mode === "now"} disabled={!canApprove} onChange={() => setMode("now")} /> Send now
          </label>
          <label className="flex items-center gap-2">
            <input type="radio" name={`send-mode-${id}`} checked={mode === "schedule"} disabled={!canApprove} onChange={() => setMode("schedule")} /> Schedule
          </label>
          <input type="datetime-local" className="form-input" value={when} disabled={!canApprove || mode !== "schedule"} onChange={(e) => setWhen(e.target.value)} />
        </div>
        <button type="button" className="btn btn-primary" disabled={!canApprove || busy} onClick={approve}>
          {mode === "schedule" ? "Approve & schedule" : "Approve & send"}
        </button>
        {!canApprove && (
          <p className="text-sm text-gray-600">Approval needs a draft with an up-to-date test and no open problems.</p>
        )}
      </div>

      <div className="flex flex-wrap gap-2">
        {doc.status === "scheduled" && (
          <>
            <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => statusAction("unschedule")}>Unschedule</button>
            <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => statusAction("cancel", "Cancel this newsletter? Nothing else will be sent.")}>Cancel</button>
          </>
        )}
        {doc.status === "sending" && (
          <>
            <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => statusAction("pause")}>Pause</button>
            <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => statusAction("cancel", "Cancel this newsletter? Recipients not yet sent will be skipped.")}>Cancel</button>
          </>
        )}
        {doc.status === "paused" && (
          <>
            <button type="button" className="btn btn-primary" disabled={busy} onClick={() => statusAction("resume")}>Resume</button>
            <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => statusAction("cancel", "Cancel this newsletter? Recipients not yet sent will be skipped.")}>Cancel</button>
          </>
        )}
        {doc.status === "draft" && (
          <button type="button" className="btn btn-secondary" disabled={busy || !editable} onClick={remove}>Delete draft</button>
        )}
        <button type="button" className="btn btn-secondary" disabled={busy} onClick={duplicate}>Duplicate</button>
      </div>
    </section>
  )
}

// Delivery

function Delivery({ id, status, onDoc }) {
  const [bu, setBu] = useState("")
  const [recipientStatus, setRecipientStatus] = useState("")
  const [tick, setTick] = useState(0)
  const [data, setData] = useState(null)
  const onDocRef = useRef(onDoc)
  onDocRef.current = onDoc

  // Auto-refresh while the newsletter is sending.
  useEffect(() => {
    if (status !== "sending") return undefined
    const timer = setInterval(() => setTick((n) => n + 1), 30000)
    return () => clearInterval(timer)
  }, [status])

  useEffect(() => {
    const params = new URLSearchParams({ limit: "200" })
    if (bu) params.set("bu", bu)
    if (recipientStatus) params.set("status", recipientStatus)
    const loadRecipients = async () => {
      try {
        setData(await api(`/${id}/recipients?${params}`))
        if (tick > 0) onDocRef.current(await api(`/${id}`))
      } catch (e) {
        notify(e.message, "error")
      }
    }
    loadRecipients()
  }, [id, bu, recipientStatus, tick, status])

  const stats = data?.stats || {}
  return (
    <section className="card space-y-4">
      <h3 className="card-title">7. Delivery</h3>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
        {["total", "queued", "sent", "failed", "skipped"].map((k) => (
          <div key={k} className="stat-card p-3">
            <div className="text-xs uppercase text-gray-600">{k}</div>
            <div className="text-xl font-semibold">{stats[k] ?? 0}</div>
          </div>
        ))}
      </div>
      <div className="flex flex-wrap gap-2">
        <select className="form-input" value={bu} onChange={(e) => setBu(e.target.value)} aria-label="Filter by business unit">
          <option value="">All BUs</option>
          {BUS.map((b) => <option key={b} value={b}>{BU_NAMES[b]}</option>)}
        </select>
        <select className="form-input" value={recipientStatus} onChange={(e) => setRecipientStatus(e.target.value)} aria-label="Filter by status">
          <option value="">All statuses</option>
          {RECIPIENT_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>
      <div className="overflow-x-auto">
        {!data ? (
          <p className="text-sm text-gray-600">Loading…</p>
        ) : (
          <table className="w-full min-w-[720px] text-sm">
            <thead>
              <tr className="border-b text-left text-gray-600">
                <th className="p-2">Email</th><th className="p-2">Name</th><th className="p-2">Company</th><th className="p-2">BU</th>
                <th className="p-2">Status</th><th className="p-2">Mailbox</th><th className="p-2">Sent</th><th className="p-2">Error / reason</th>
              </tr>
            </thead>
            <tbody>
              {data.recipients.length === 0 && (
                <tr><td colSpan={8} className="p-2 text-gray-600">No recipients match.</td></tr>
              )}
              {data.recipients.map((r, i) => (
                <tr key={`${r.email}-${i}`} className="border-b">
                  <td className="p-2 font-mono">{r.email}</td>
                  <td className="p-2">{r.name || "—"}</td>
                  <td className="p-2">{r.company || "—"}</td>
                  <td className="p-2">{BU_NAMES[r.bu] || r.bu || "—"}</td>
                  <td className="p-2">{r.status}</td>
                  <td className="p-2">{r.mailbox || "—"}</td>
                  <td className="p-2">{r.sent_at ? formatDateTime(r.sent_at) : "—"}</td>
                  <td className="p-2">{r.error || r.reason || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  )
}

// Editor

function Editor({ id, meta, onBack, onOpen }) {
  const [doc, setDoc] = useState(null)
  const [draft, setDraft] = useState(null)
  const [previewBu, setPreviewBu] = useState(BUS[0])

  const applyDoc = (d) => {
    setDoc(d)
    setDraft(toDraft(d))
  }

  useEffect(() => {
    const loadNewsletter = async () => {
      try {
        applyDoc(await api(`/${id}`))
      } catch (e) {
        notify(e.message, "error")
      }
    }
    loadNewsletter()
  }, [id])

  const save = async () => {
    try {
      const saved = await api(`/${id}`, { method: "PUT", body: JSON.stringify(toPayload(draft)) })
      applyDoc(saved)
      notify("Saved", "success")
      return saved
    } catch (e) {
      notify(e.message, "error")
      return null
    }
  }

  if (!doc || !draft) return <div className="card">Loading…</div>

  const editable = ["draft", "scheduled"].includes(doc.status)
  const dirty = JSON.stringify(toPayload(draft)) !== JSON.stringify(toPayload(toDraft(doc)))
  const ensureSaved = () => (editable && dirty ? save() : Promise.resolve(doc))
  const syncDoc = (d) => setDoc((cur) => (cur && cur.status !== d.status ? d : cur))
  const update = (patch) => setDraft((d) => ({ ...d, ...patch }))
  const activePreviewBu = draft.bus.includes(previewBu) ? previewBu : draft.bus[0] || BUS[0]

  return (
    <div className="space-y-4">
      <div className="card">
        <div className="card-header flex flex-wrap items-center justify-between gap-2">
          <div>
            <button type="button" className="btn btn-secondary btn-sm mb-2 flex items-center gap-1" onClick={onBack}>
              <ArrowLeft size={14} /> Back to list
            </button>
            <h2 className="card-title flex flex-wrap items-center gap-2">{doc.name || "Untitled"} <StatusBadge status={doc.status} /></h2>
            {doc.scheduled_for && <p className="card-description">Scheduled for {formatDateTime(doc.scheduled_for)}</p>}
          </div>
          {editable && (
            <button type="button" className="btn btn-primary flex items-center gap-1" onClick={save}>
              <Save size={16} /> Save
            </button>
          )}
        </div>
        {(doc.problems || []).length > 0 && (
          <div className="mt-3 rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
            <p className="flex items-center gap-1 font-semibold"><AlertTriangle size={14} /> Fix these before sending</p>
            <ul className="mt-1 list-disc pl-5">
              {doc.problems.map((p, i) => <li key={i}>{p}</li>)}
            </ul>
          </div>
        )}
      </div>

      <section className="card space-y-3">
        <h3 className="card-title">1. Details</h3>
        <fieldset disabled={!editable} className="grid gap-3 md:grid-cols-2">
          <Field label="Name">
            <input className="form-input w-full" value={draft.name} onChange={(e) => update({ name: e.target.value })} />
          </Field>
          <Field label="Subject" hint={TOKEN_HINT}>
            <input className="form-input w-full" value={draft.subject} onChange={(e) => update({ subject: e.target.value })} />
          </Field>
          <Field label="Preheader (preview text shown in inboxes)">
            <input className="form-input w-full" value={draft.preheader} onChange={(e) => update({ preheader: e.target.value })} />
          </Field>
        </fieldset>
      </section>

      <BlockEditor blocks={draft.blocks} editable={editable} onChange={(blocks) => update({ blocks })} />

      <Preview
        id={id}
        content={{ subject: draft.subject, preheader: draft.preheader, blocks: draft.blocks }}
        bu={activePreviewBu}
        bus={draft.bus}
        onBu={setPreviewBu}
      />

      <SendersSection meta={meta} draft={draft} editable={editable} update={update} />

      <AudienceSection id={id} meta={meta} draft={draft} editable={editable} update={update} ensureSaved={ensureSaved} />

      <SendSection
        id={id}
        doc={doc}
        editable={editable}
        ensureSaved={ensureSaved}
        applyDoc={applyDoc}
        onBack={onBack}
        onOpen={onOpen}
      />

      {doc.status !== "draft" && <Delivery id={id} status={doc.status} onDoc={syncDoc} />}

      <section className="card">
        <h3 className="card-title">History</h3>
        <ul className="mt-2 space-y-1 text-sm">
          {[...(doc.history || [])].reverse().slice(0, 15).map((h, i) => (
            <li key={i}>{formatDateTime(h.at)} · {h.by || "system"} · {h.action}</li>
          ))}
        </ul>
      </section>
    </div>
  )
}

// List

function NewsletterList({ meta, onOpen }) {
  const [status, setStatus] = useState("")
  const [rows, setRows] = useState(null)
  const [naming, setNaming] = useState(false)
  const [name, setName] = useState("")

  const load = useCallback(async () => {
    try {
      const data = await api(status ? `?status=${status}` : "")
      setRows(data.newsletters || [])
    } catch (e) {
      notify(e.message, "error")
      setRows((r) => r || [])
    }
  }, [status])

  useEffect(() => {
    load()
  }, [load])

  const create = async () => {
    const title = name.trim()
    if (!title) {
      notify("Enter a name for the newsletter", "error")
      return
    }
    try {
      const doc = await api("", { method: "POST", body: JSON.stringify({ name: title }) })
      onOpen(doc._id)
    } catch (e) {
      notify(e.message, "error")
    }
  }

  return (
    <div className="space-y-4">
      {meta.send_blocker && (
        <div className="card flex items-start gap-2 border border-red-300 bg-red-50 text-red-800">
          <AlertTriangle size={18} className="mt-0.5 shrink-0" />
          <p className="text-sm font-semibold">{meta.send_blocker}</p>
        </div>
      )}

      <div className="card">
        <div className="card-header flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="card-title">Newsletter</h2>
            <p className="card-description">
              Design once, send each company's edition from its own mailboxes. Nothing goes out without a test send and approval.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <select className="form-input" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Filter by status">
              <option value="">All statuses</option>
              {Object.keys(STATUS_CLASS).map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
            <button type="button" className="btn btn-secondary flex items-center gap-1" onClick={load}><RefreshCw size={16} /> Refresh</button>
            <button type="button" className="btn btn-primary flex items-center gap-1" onClick={() => setNaming(true)}>
              <Plus size={16} /> New newsletter
            </button>
          </div>
        </div>
        {naming && (
          <div className="mt-3 flex flex-wrap gap-2">
            <input
              className="form-input flex-1"
              placeholder="Newsletter name, e.g. May partner update"
              value={name}
              autoFocus
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") create() }}
            />
            <button type="button" className="btn btn-primary" onClick={create}>Create</button>
            <button type="button" className="btn btn-secondary" onClick={() => { setNaming(false); setName("") }}>Cancel</button>
          </div>
        )}
      </div>

      <div className="card overflow-x-auto">
        {!rows ? (
          <p className="text-sm text-gray-600">Loading…</p>
        ) : rows.length === 0 ? (
          <p className="text-sm text-gray-600">No newsletters yet. Create one to start a draft.</p>
        ) : (
          <table className="w-full min-w-[680px] text-sm">
            <thead>
              <tr className="border-b text-left text-gray-600">
                <th className="p-2">Name</th><th className="p-2">Subject</th><th className="p-2">Status</th>
                <th className="p-2">Business units</th><th className="p-2">Updated</th><th className="p-2">Delivery</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((n) => (
                <tr key={n._id} className="cursor-pointer border-b hover:bg-gray-50" onClick={() => onOpen(n._id)}>
                  <td className="p-2 font-semibold">{n.name}</td>
                  <td className="p-2">{n.subject || "—"}</td>
                  <td className="p-2"><StatusBadge status={n.status} /></td>
                  <td className="p-2">{(n.bus || []).map((b) => BU_NAMES[b] || b).join(", ") || "—"}</td>
                  <td className="p-2">
                    {n.updated_at ? formatDateTime(n.updated_at) : "—"}
                    {n.scheduled_for && <div className="text-xs text-gray-600">Scheduled {formatDateTime(n.scheduled_for)}</div>}
                  </td>
                  <td className="p-2">
                    {n.stats ? `sent ${n.stats.sent} / total ${n.stats.total}, failed ${n.stats.failed}` : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

// Mailbox contacts

function ContactsTab() {
  const [text, setText] = useState("")
  const [filter, setFilter] = useState({ search: "", bu: "" })
  const [data, setData] = useState(null)
  const [harvesting, setHarvesting] = useState(false)

  const load = useCallback(async () => {
    const params = new URLSearchParams({ limit: "100" })
    if (filter.search) params.set("search", filter.search)
    if (filter.bu) params.set("bu", filter.bu)
    try {
      setData(await api(`/contacts/list?${params}`))
    } catch (e) {
      notify(e.message, "error")
    }
  }, [filter])

  useEffect(() => {
    load()
  }, [load])

  const collect = async () => {
    setHarvesting(true)
    try {
      const res = await api("/contacts/harvest", { method: "POST" })
      notify(
        res.started ? "Collection started. Refresh in a few minutes to see new contacts." : res.detail || "Collection did not start",
        res.started ? "success" : "error",
      )
      load()
    } catch (e) {
      notify(e.message, "error")
    } finally {
      setHarvesting(false)
    }
  }

  const harvest = data?.harvest || {}
  return (
    <div className="space-y-4">
      <div className="card">
        <div className="card-header flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="card-title flex items-center gap-2"><Users size={18} /> Mailbox contacts</h2>
            <p className="card-description">
              External people and companies found in the attached mailboxes (inbound senders and people we wrote to). Collected nightly; you can collect now.
            </p>
          </div>
          <button type="button" className="btn btn-primary" onClick={collect} disabled={harvesting || Boolean(harvest.running)}>
            {harvesting ? "Starting…" : "Collect now"}
          </button>
        </div>
        <form
          className="mt-3 flex flex-wrap gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            setFilter((f) => ({ ...f, search: text.trim() }))
          }}
        >
          <input className="form-input flex-1" placeholder="Search email or name" value={text} onChange={(e) => setText(e.target.value)} />
          <select className="form-input" value={filter.bu} onChange={(e) => setFilter((f) => ({ ...f, bu: e.target.value }))} aria-label="Filter by business unit">
            <option value="">All BUs</option>
            {BUS.map((b) => <option key={b} value={b}>{BU_NAMES[b]}</option>)}
          </select>
          <button type="submit" className="btn btn-secondary flex items-center gap-1"><Search size={16} /> Search</button>
        </form>
        <p className="mt-2 text-sm text-gray-600">
          Last collected: {harvest.ran_at ? formatDateTime(harvest.ran_at) : "never"}
          {harvest.running ? " · running now" : ""}
        </p>
      </div>

      <div className="card overflow-x-auto">
        {!data ? (
          <p className="text-sm text-gray-600">Loading…</p>
        ) : (
          <>
            <p className="mb-2 text-sm text-gray-600">{data.total} contacts</p>
            <table className="w-full min-w-[640px] text-sm">
              <thead>
                <tr className="border-b text-left text-gray-600">
                  <th className="p-2">Email</th><th className="p-2">Name</th><th className="p-2">Business units</th>
                  <th className="p-2">Messages</th><th className="p-2">Last seen</th>
                </tr>
              </thead>
              <tbody>
                {data.contacts.length === 0 && (
                  <tr><td colSpan={5} className="p-2 text-gray-600">No contacts match.</td></tr>
                )}
                {data.contacts.map((c) => (
                  <tr key={c.email} className="border-b">
                    <td className="p-2 font-mono">{c.email}</td>
                    <td className="p-2">{c.name || "—"}</td>
                    <td className="p-2">{(c.bus || []).map((b) => BU_NAMES[b] || b).join(", ") || "—"}</td>
                    <td className="p-2">{c.messages}</td>
                    <td className="p-2">{c.last_seen ? formatDateTime(c.last_seen) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </div>
    </div>
  )
}

// Page

export default function MarketingNewsletter() {
  const [tab, setTab] = useState("newsletters")
  const [meta, setMeta] = useState(null)
  const [editId, setEditId] = useState(null)

  useEffect(() => {
    const loadMeta = async () => {
      try {
        setMeta(await api("/meta"))
      } catch (e) {
        notify(e.message, "error")
      }
    }
    loadMeta()
  }, [])

  let body
  if (tab === "contacts") body = <ContactsTab />
  else if (!meta) body = <div className="card">Loading…</div>
  else if (editId) body = <Editor key={editId} id={editId} meta={meta} onBack={() => setEditId(null)} onOpen={setEditId} />
  else body = <NewsletterList meta={meta} onOpen={setEditId} />

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {TABS.map(([key, label]) => (
          <button
            key={key}
            type="button"
            className={`btn ${tab === key ? "btn-primary" : "btn-secondary"}`}
            onClick={() => {
              setTab(key)
              setEditId(null)
            }}
          >
            {label}
          </button>
        ))}
      </div>
      {body}
    </div>
  )
}
