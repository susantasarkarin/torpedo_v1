import { useState } from "react"
import { buildApiUrl } from "../../config"
import { authFetch } from "../../utils/api"
import { notify } from "../../utils/notify"

// Permanently deletes a SurveyFieldwork Panel member and all their records
// (survey completions, points, redemptions, referrals, flags). The admin must
// type the member's email to confirm.
export default function DeletePanelistDialog({ panelist, onClose, onDeleted }) {
  const [typed, setTyped] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  if (!panelist) return null
  const email = panelist.email || ""
  const name = [panelist.firstName, panelist.lastName].filter(Boolean).join(" ") || email
  const matches = typed.trim().toLowerCase() === email.toLowerCase()

  const remove = async () => {
    setBusy(true)
    setError("")
    try {
      const res = await authFetch(buildApiUrl(`/api/panel-admin/sfwpanel-panelists/${panelist._id}`), {
        method: "DELETE",
        headers: { Authorization: localStorage.getItem("session_id"), "Content-Type": "application/json" },
        body: JSON.stringify({ confirmEmail: typed.trim() }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || data.message || "Could not delete this member")
      notify(`Deleted ${name}`, "success")
      onDeleted?.(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div role="dialog" aria-modal="true" onClick={(e) => { if (e.target === e.currentTarget && !busy) onClose() }}
      style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)", zIndex: 1100, display: "flex", alignItems: "center", justifyContent: "center", padding: "1rem" }}>
      <div style={{ background: "#fff", borderRadius: "12px", width: "100%", maxWidth: "460px", padding: "1.5rem", boxShadow: "0 20px 50px rgba(0,0,0,0.2)" }}>
        <h3 style={{ fontSize: "1.1rem", fontWeight: 700, color: "#991b1b", marginBottom: "0.5rem" }}>Delete {name}?</h3>
        <p style={{ fontSize: "0.875rem", color: "#4a4a4a", lineHeight: 1.5 }}>
          This permanently removes the member and all their survey completions, points, redemptions, referrals and flags.
          Panel totals and finance figures will change. <strong>This cannot be undone.</strong>
        </p>
        <label style={{ display: "block", fontSize: "0.8rem", color: "#5c5c5c", marginTop: "1rem", marginBottom: "0.35rem" }}>
          Type <strong style={{ fontFamily: "monospace" }}>{email}</strong> to confirm
        </label>
        <input autoFocus value={typed} onChange={(e) => { setTyped(e.target.value); setError("") }} disabled={busy}
          style={{ width: "100%", padding: "0.55rem 0.75rem", border: "1px solid #d4cec3", borderRadius: "6px", fontSize: "0.875rem" }} />
        {error && <p style={{ color: "#b91c1c", fontSize: "0.8rem", marginTop: "0.5rem" }}>{error}</p>}
        <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem", marginTop: "1.25rem" }}>
          <button type="button" onClick={onClose} disabled={busy}
            style={{ padding: "0.5rem 1rem", border: "1px solid #d4cec3", background: "#fff", borderRadius: "6px", cursor: "pointer", fontSize: "0.875rem" }}>
            Cancel
          </button>
          <button type="button" onClick={remove} disabled={!matches || busy}
            style={{ padding: "0.5rem 1rem", border: "none", background: matches ? "#dc2626" : "#fca5a5", color: "#fff", borderRadius: "6px", cursor: matches && !busy ? "pointer" : "default", fontSize: "0.875rem", fontWeight: 600 }}>
            {busy ? "Deleting…" : "Delete permanently"}
          </button>
        </div>
      </div>
    </div>
  )
}
