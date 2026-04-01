import { useState, useEffect, useCallback } from "react"
import { useNavigate } from "react-router-dom"
import {
  Building2, Plus, Save, Trash2, RefreshCw,
  CheckCircle, AlertCircle, ChevronRight, FileText,
  Loader2, Info,
} from "lucide-react"

const API = "/api/sales-outreach"

function token() {
  return localStorage.getItem("session_id") || ""
}

function authHeaders() {
  const t = token()
  if (!t) return {}
  return { Authorization: t }
}

const TEMPLATE = `BUSINESS UNIT: [Name] — [Tagline]
SLUG: [slug]

DESCRIPTION:
[What this business unit does — 2-3 sentences]

CORE CAPABILITIES:
- [Capability 1]
- [Capability 2]
- [Capability 3]

IDEAL CUSTOMER PROFILE:
- [Target role/company 1]
- [Target role/company 2]

PAIN POINTS WE SOLVE:
- [Pain point 1]
- [Pain point 2]

VALUE PROPOSITION:
[Why leads should care — 2-3 sentences]

SENDER: [Full Name], [Title], [Business Unit Name]`

export default function AIConfig() {
  const navigate = useNavigate()
  const [units, setUnits] = useState([])
  const [selected, setSelected] = useState(null)   // slug of selected BU
  const [content, setContent] = useState("")
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [toast, setToast] = useState(null)          // {type: "success"|"error", msg}
  const [showNewForm, setShowNewForm] = useState(false)
  const [newSlug, setNewSlug] = useState("")
  const [dirty, setDirty] = useState(false)

  // ─── Toast helper ───
  const showToast = (type, msg) => {
    setToast({ type, msg })
    setTimeout(() => setToast(null), 3500)
  }

  // ─── Load all BU configs ───
  const loadUnits = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch(`${API}/bu-configs`, { headers: authHeaders() })
      if (!res.ok) throw new Error("Failed to load")
      const data = await res.json()
      setUnits(data.business_units || [])
      // auto-select first
      if (data.business_units?.length && !selected) {
        const first = data.business_units[0]
        setSelected(first.slug)
        setContent(first.content)
        setDirty(false)
      }
    } catch (e) {
      showToast("error", "Could not load business unit configs")
    } finally {
      setLoading(false)
    }
  }, [selected])

  useEffect(() => { loadUnits() }, [])

  // ─── Select a BU tab ───
  const selectUnit = (unit) => {
    if (dirty && !window.confirm("You have unsaved changes. Switch anyway?")) return
    setSelected(unit.slug)
    setContent(unit.content)
    setDirty(false)
    setShowNewForm(false)
  }

  // ─── Save (update) ───
  const handleSave = async () => {
    if (!selected) return
    setSaving(true)
    try {
      const res = await fetch(`${API}/bu-configs/${selected}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ content }),
      })
      if (!res.ok) throw new Error("Save failed")
      setDirty(false)
      // refresh sidebar name in case header changed
      setUnits(prev => prev.map(u =>
        u.slug === selected ? { ...u, content } : u
      ))
      showToast("success", "Business unit config saved")
    } catch {
      showToast("error", "Failed to save — check your connection")
    } finally {
      setSaving(false)
    }
  }

  // ─── Delete ───
  const handleDelete = async () => {
    if (!selected) return
    if (!window.confirm(`Delete "${selected}" permanently? This cannot be undone.`)) return
    setDeleting(true)
    try {
      const res = await fetch(`${API}/bu-configs/${selected}`, {
        method: "DELETE",
        headers: authHeaders(),
      })
      if (!res.ok) throw new Error("Delete failed")
      showToast("success", "Business unit deleted")
      setSelected(null)
      setContent("")
      setDirty(false)
      await loadUnits()
      // auto-select first remaining
      setUnits(prev => {
        if (prev.length) { setSelected(prev[0].slug); setContent(prev[0].content) }
        return prev
      })
    } catch {
      showToast("error", "Failed to delete")
    } finally {
      setDeleting(false)
    }
  }

  // ─── Create new BU ───
  const handleCreate = async () => {
    const slug = newSlug.trim().toLowerCase().replace(/[^a-z0-9_]/g, "_")
    if (!slug) return showToast("error", "Slug cannot be empty")
    try {
      const res = await fetch(`${API}/bu-configs`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ slug, content: TEMPLATE }),
      })
      if (res.status === 409) return showToast("error", `"${slug}" already exists`)
      if (!res.ok) throw new Error("Create failed")
      setNewSlug("")
      setShowNewForm(false)
      await loadUnits()
      setSelected(slug)
      setContent(TEMPLATE)
      setDirty(false)
      showToast("success", `Created "${slug}" — edit and save below`)
    } catch {
      showToast("error", "Failed to create business unit")
    }
  }

  return (
    <div className="text-white flex flex-col" style={{ height: "calc(100vh - 154px)" }}>

      {/* ── Header ── */}
      <div className="bg-gray-900 border border-gray-800 rounded-t-xl px-6 py-4 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-indigo-600/20 rounded-lg">
            <Building2 className="text-indigo-400" size={20} />
          </div>
          <div>
            <h1 className="text-base font-semibold text-white">AI Reference Material</h1>
            <p className="text-xs text-gray-400 mt-0.5">
              Business unit descriptions used by Gemini (routing) and GPT-4 (email drafting)
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={loadUnits}
            className="p-2 text-gray-400 hover:text-white hover:bg-gray-700 rounded-lg transition"
            title="Refresh"
          >
            <RefreshCw size={15} />
          </button>
          <button
            onClick={() => { setShowNewForm(v => !v); setDirty(false) }}
            className="flex items-center gap-1.5 px-3 py-2 bg-indigo-600 hover:bg-indigo-500 rounded-lg text-sm font-medium transition"
          >
            <Plus size={14} /> New Business Unit
          </button>
        </div>
      </div>

      {/* ── How it works banner ── */}
      <div className="bg-indigo-950/50 border-x border-indigo-900/40 px-5 py-2.5 flex items-start gap-2 text-xs text-indigo-300 shrink-0">
        <Info size={13} className="mt-0.5 shrink-0 text-indigo-400" />
        <span>
          <strong className="text-indigo-200">How Gemini + GPT-4 use these files:</strong>&nbsp;
          Gemini reads all BU files to pick the best match and write a gap analysis.
          GPT-4 then uses the chosen BU file + gap analysis to draft the personalised outreach email.
        </span>
      </div>

      {/* ── New BU form (inline, above columns) ── */}
      {showNewForm && (
        <div className="bg-gray-900 border-x border-gray-800 px-6 py-4 flex items-end gap-3 shrink-0">
          <div className="flex flex-col gap-1">
            <label className="text-xs text-gray-400">Slug (lowercase, used as filename)</label>
            <input
              value={newSlug}
              onChange={e => setNewSlug(e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "_"))}
              placeholder="e.g. data_quality"
              className="bg-gray-800 border border-gray-700 rounded-lg text-sm text-white px-3 py-2 w-56 focus:outline-none focus:border-indigo-500"
            />
          </div>
          <button
            onClick={handleCreate}
            disabled={!newSlug.trim()}
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 rounded-lg text-sm font-medium transition"
          >
            Create
          </button>
          <button
            onClick={() => setShowNewForm(false)}
            className="px-3 py-2 text-gray-400 hover:text-white text-sm transition"
          >
            Cancel
          </button>
          <p className="text-xs text-gray-500 pb-0.5">A template will be pre-filled — edit and save to activate.</p>
        </div>
      )}

      <div className="flex flex-1 min-h-0 border border-gray-800 rounded-b-xl overflow-hidden">

        {/* ── Sidebar ── */}
        <aside className="w-52 bg-gray-900 border-r border-gray-800 flex flex-col shrink-0">
          <div className="px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wider border-b border-gray-800">
            Business Units
          </div>

          {loading ? (
            <div className="flex-1 flex items-center justify-center">
              <Loader2 className="animate-spin text-gray-600" size={20} />
            </div>
          ) : (
            <nav className="flex-1 overflow-y-auto">
              {units.map(unit => (
                <button
                  key={unit.slug}
                  onClick={() => selectUnit(unit)}
                  className={`w-full flex items-center gap-2 px-4 py-3 text-left text-sm transition border-l-2 ${
                    selected === unit.slug
                      ? "border-indigo-500 bg-indigo-950/40 text-white"
                      : "border-transparent text-gray-400 hover:bg-gray-800 hover:text-white"
                  }`}
                >
                  <FileText size={13} className="shrink-0" />
                  <span className="truncate">{unit.name || unit.slug}</span>
                  {selected === unit.slug && <ChevronRight size={13} className="ml-auto shrink-0 text-indigo-400" />}
                </button>
              ))}
              {units.length === 0 && (
                <p className="px-4 py-4 text-xs text-gray-600 italic">No configs yet.<br/>Create one above →</p>
              )}
            </nav>
          )}
        </aside>

        {/* ── Main editor area ── */}
        <main className="flex-1 flex flex-col min-w-0 bg-gray-950">

          {/* Editor toolbar */}
          {selected ? (
            <>
              <div className="bg-gray-900 border-b border-gray-800 px-5 py-3 flex items-center justify-between shrink-0">
                <div className="flex items-center gap-2.5">
                  <span className="text-sm font-semibold text-white">
                    {units.find(u => u.slug === selected)?.name || selected}
                  </span>
                  <span className="text-xs text-gray-500 font-mono bg-gray-800 px-2 py-0.5 rounded">{selected}.txt</span>
                  {dirty && (
                    <span className="text-xs text-amber-400 flex items-center gap-1">
                      <span className="w-1.5 h-1.5 rounded-full bg-amber-400 inline-block" />
                      unsaved
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={handleDelete}
                    disabled={deleting}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-red-400 hover:text-red-300 hover:bg-red-900/20 rounded-lg text-sm transition"
                  >
                    {deleting ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13} />}
                    Delete
                  </button>
                  <button
                    onClick={handleSave}
                    disabled={saving || !dirty}
                    className="flex items-center gap-1.5 px-4 py-1.5 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 rounded-lg text-sm font-medium transition"
                  >
                    {saving ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
                    Save
                  </button>
                </div>
              </div>

              {/* Textarea — fills all remaining height */}
              <div className="flex-1 p-4 min-h-0">
                <textarea
                  value={content}
                  onChange={e => { setContent(e.target.value); setDirty(true) }}
                  spellCheck={false}
                  className="w-full h-full bg-gray-900 border border-gray-800 rounded-xl text-sm text-gray-100 font-mono p-5 resize-none focus:outline-none focus:border-indigo-600 leading-relaxed"
                  placeholder="Paste your business unit description here…"
                />
              </div>
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center text-center">
              <div>
                <Building2 size={40} className="text-gray-700 mx-auto mb-3" />
                <p className="text-gray-500 text-sm">Select a business unit to edit</p>
                <p className="text-gray-600 text-xs mt-1">or create a new one above</p>
              </div>
            </div>
          )}
        </main>
      </div>

      {/* ── Toast ── */}
      {toast && (
        <div className={`fixed bottom-6 right-6 flex items-center gap-2 px-4 py-3 rounded-xl shadow-xl text-sm font-medium z-50 animate-in slide-in-from-bottom-4 ${
          toast.type === "success"
            ? "bg-emerald-900 border border-emerald-700 text-emerald-200"
            : "bg-red-900 border border-red-700 text-red-200"
        }`}>
          {toast.type === "success"
            ? <CheckCircle size={16} />
            : <AlertCircle size={16} />
          }
          {toast.msg}
        </div>
      )}
    </div>
  )
}
