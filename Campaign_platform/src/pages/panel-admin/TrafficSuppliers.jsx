import { useEffect, useState } from "react"
import { buildApiUrl } from "../../config"

const PANEL_ADMIN_API_PREFIX = "/api/panel-admin"

/**
 * Traffic suppliers — Facebook, Google, Quora and third-party panel vendors.
 *
 * Suppliers live on the SFW panel (it owns signup, so it owns attribution);
 * this page proxies through Torpedo so they are managed alongside the rest of
 * the panel. The two links per row are the whole point of the page: the signup
 * URL goes to the vendor, the dashboard URL is what they check their numbers on.
 */

const card = {
  background: "#fff",
  border: "1px solid #e5e7eb",
  borderRadius: "10px",
  padding: "1.25rem",
  marginBottom: "1.25rem",
}

function CopyField({ label, value, hint }) {
  const [copied, setCopied] = useState(false)

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      setTimeout(() => setCopied(false), 1600)
    } catch {
      // Clipboard blocked (non-HTTPS origin or denied permission) — the input
      // is selectable, so the admin can still copy it by hand.
    }
  }

  return (
    <div style={{ marginTop: "0.75rem" }}>
      <div style={{ fontSize: "0.75rem", fontWeight: 700, color: "#6b7280", textTransform: "uppercase", letterSpacing: "0.03em" }}>
        {label}
      </div>
      <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.25rem" }}>
        <input
          readOnly
          value={value}
          onFocus={(e) => e.target.select()}
          style={{
            flex: 1, padding: "0.5rem 0.65rem", border: "1px solid #e5e7eb", borderRadius: "6px",
            fontFamily: "ui-monospace, Menlo, monospace", fontSize: "0.78rem", background: "#f9fafb", color: "#111827",
          }}
        />
        <button
          onClick={copy}
          style={{
            padding: "0.5rem 0.9rem", borderRadius: "6px", border: "1px solid #d1d5db",
            background: copied ? "#059669" : "#fff", color: copied ? "#fff" : "#374151",
            fontWeight: 600, fontSize: "0.8rem", cursor: "pointer", whiteSpace: "nowrap",
          }}
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      {hint && <p style={{ fontSize: "0.75rem", color: "#6b7280", margin: "0.3rem 0 0" }}>{hint}</p>}
    </div>
  )
}

export default function TrafficSuppliers() {
  const [suppliers, setSuppliers] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [showForm, setShowForm] = useState(false)
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState({
    name: "", slug: "", payoutPerConversionPaise: "", postbackUrl: "", postbackEnabled: false, notes: "",
  })

  const sessionId = localStorage.getItem("session_id") || ""

  const fetchSuppliers = async () => {
    setLoading(true)
    setError("")
    try {
      const res = await fetch(buildApiUrl(`${PANEL_ADMIN_API_PREFIX}/suppliers`), {
        headers: { Authorization: sessionId },
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || "Failed to load suppliers")
      setSuppliers(data.suppliers || [])
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchSuppliers() }, [])

  const submit = async (e) => {
    e.preventDefault()
    setSaving(true)
    setError("")
    try {
      const res = await fetch(buildApiUrl(`${PANEL_ADMIN_API_PREFIX}/suppliers`), {
        method: "POST",
        headers: { Authorization: sessionId, "Content-Type": "application/json" },
        body: JSON.stringify({
          ...form,
          // Rupees in the form, paise on the wire — the panel stores money as
          // integer paise everywhere else.
          payoutPerConversionPaise: Math.round(parseFloat(form.payoutPerConversionPaise || 0) * 100),
        }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || "Could not create supplier")
      setForm({ name: "", slug: "", payoutPerConversionPaise: "", postbackUrl: "", postbackEnabled: false, notes: "" })
      setShowForm(false)
      fetchSuppliers()
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  const toggleStatus = async (s) => {
    await fetch(buildApiUrl(`${PANEL_ADMIN_API_PREFIX}/suppliers/${s.slug}`), {
      method: "PATCH",
      headers: { Authorization: sessionId, "Content-Type": "application/json" },
      body: JSON.stringify({ status: s.status === "active" ? "paused" : "active" }),
    })
    fetchSuppliers()
  }

  const rotate = async (s) => {
    if (!window.confirm(`Rotate ${s.name}'s dashboard link?\n\nTheir current link stops working immediately and you will need to send them the new one.`)) return
    await fetch(buildApiUrl(`${PANEL_ADMIN_API_PREFIX}/suppliers/${s.slug}/rotate-token`), {
      method: "POST",
      headers: { Authorization: sessionId },
    })
    fetchSuppliers()
  }

  const input = {
    width: "100%", padding: "0.55rem 0.7rem", border: "1px solid #d1d5db",
    borderRadius: "6px", fontSize: "0.9rem", marginTop: "0.25rem",
  }
  const label = { fontSize: "0.8rem", fontWeight: 600, color: "#374151" }

  return (
    <div style={{ padding: "1.5rem", maxWidth: "1000px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "1.25rem" }}>
        <div>
          <h2 style={{ fontSize: "1.5rem", fontWeight: 800, color: "#111827", margin: 0 }}>Traffic Suppliers</h2>
          <p style={{ color: "#6b7280", margin: "0.25rem 0 0", fontSize: "0.9rem" }}>
            Where panel signups come from. Each supplier gets a tracked signup link and a private dashboard.
            A signup counts as <strong>payable once the panelist completes their profile</strong> — the point they can be routed to a survey.
          </p>
        </div>
        <button
          onClick={() => setShowForm(!showForm)}
          style={{
            padding: "0.6rem 1.1rem", background: "#7c3aed", color: "#fff", border: "none",
            borderRadius: "8px", fontWeight: 700, cursor: "pointer", whiteSpace: "nowrap",
          }}
        >
          {showForm ? "Cancel" : "+ Add supplier"}
        </button>
      </div>

      {error && (
        <div style={{ ...card, borderColor: "#fecaca", background: "#fef2f2", color: "#b91c1c" }}>{error}</div>
      )}

      {showForm && (
        <form onSubmit={submit} style={card}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
            <div>
              <label style={label}>Name</label>
              <input style={input} required value={form.name} placeholder="Quora Ads"
                onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </div>
            <div>
              <label style={label}>Slug</label>
              <input style={input} required value={form.slug} placeholder="quora"
                pattern="[a-z0-9][a-z0-9_-]{1,40}"
                onChange={(e) => setForm({ ...form, slug: e.target.value.toLowerCase() })} />
              <p style={{ fontSize: "0.72rem", color: "#6b7280", margin: "0.25rem 0 0" }}>
                Appears in the link. Lowercase, no spaces. Cannot be changed later.
              </p>
            </div>
            <div>
              <label style={label}>Payout per conversion (₹)</label>
              <input style={input} type="number" step="0.01" min="0" value={form.payoutPerConversionPaise}
                placeholder="25.00"
                onChange={(e) => setForm({ ...form, payoutPerConversionPaise: e.target.value })} />
            </div>
            <div>
              <label style={label}>Postback URL (optional)</label>
              <input style={input} value={form.postbackUrl}
                placeholder="https://vendor.com/pb?click={CLICK_ID}"
                onChange={(e) => setForm({ ...form, postbackUrl: e.target.value })} />
              <label style={{ ...label, display: "flex", alignItems: "center", gap: "0.4rem", marginTop: "0.4rem", fontWeight: 500 }}>
                <input type="checkbox" checked={form.postbackEnabled}
                  onChange={(e) => setForm({ ...form, postbackEnabled: e.target.checked })} />
                Fire a postback when a signup converts
              </label>
            </div>
          </div>
          <button type="submit" disabled={saving}
            style={{
              marginTop: "1rem", padding: "0.6rem 1.4rem", background: saving ? "#a78bfa" : "#7c3aed",
              color: "#fff", border: "none", borderRadius: "8px", fontWeight: 700, cursor: saving ? "default" : "pointer",
            }}>
            {saving ? "Creating…" : "Create supplier"}
          </button>
        </form>
      )}

      {loading ? (
        <p style={{ color: "#6b7280" }}>Loading…</p>
      ) : suppliers.length === 0 ? (
        <div style={{ ...card, textAlign: "center", padding: "2.5rem 1.25rem" }}>
          <p style={{ fontWeight: 700, color: "#111827", margin: 0 }}>No suppliers yet</p>
          <p style={{ color: "#6b7280", fontSize: "0.9rem", margin: "0.4rem 0 0" }}>
            Add one for each traffic source — Facebook, Google, Quora, or a panel vendor — and send them their tracked signup link.
            Signups that arrive without a link are recorded as organic.
          </p>
        </div>
      ) : (
        suppliers.map((s) => {
          const convRate = s.signups > 0 ? ((s.converted / s.signups) * 100).toFixed(1) : "0.0"
          return (
            <div key={s.slug} style={card}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "1rem" }}>
                <div>
                  <span style={{ fontSize: "1.05rem", fontWeight: 800, color: "#111827" }}>{s.name}</span>
                  <span style={{
                    marginLeft: "0.6rem", fontSize: "0.7rem", fontWeight: 700, padding: "0.15rem 0.5rem",
                    borderRadius: "99px", textTransform: "uppercase",
                    background: s.status === "active" ? "#dcfce7" : "#fef3c7",
                    color: s.status === "active" ? "#166534" : "#92400e",
                  }}>{s.status}</span>
                  <div style={{ color: "#6b7280", fontSize: "0.8rem", marginTop: "0.2rem" }}>
                    <code>{s.slug}</code>
                    {s.postbackEnabled && " · postback on"}
                  </div>
                </div>
                <div style={{ display: "flex", gap: "0.5rem" }}>
                  <button onClick={() => toggleStatus(s)} style={{
                    padding: "0.4rem 0.8rem", border: "1px solid #d1d5db", borderRadius: "6px",
                    background: "#fff", fontSize: "0.8rem", fontWeight: 600, cursor: "pointer",
                  }}>{s.status === "active" ? "Pause" : "Activate"}</button>
                  <button onClick={() => rotate(s)} style={{
                    padding: "0.4rem 0.8rem", border: "1px solid #d1d5db", borderRadius: "6px",
                    background: "#fff", fontSize: "0.8rem", fontWeight: 600, cursor: "pointer",
                  }}>Rotate link</button>
                </div>
              </div>

              <div style={{ display: "flex", gap: "2rem", marginTop: "1rem", flexWrap: "wrap" }}>
                {[
                  ["Signups", s.signups.toLocaleString()],
                  ["Profile complete", s.converted.toLocaleString()],
                  ["Conversion", `${convRate}%`],
                  ["Accrued", `₹${(((s.payoutPerConversionPaise || 0) * s.converted) / 100).toLocaleString("en-IN")}`],
                ].map(([k, v]) => (
                  <div key={k}>
                    <div style={{ fontSize: "0.72rem", color: "#6b7280", textTransform: "uppercase", letterSpacing: "0.03em" }}>{k}</div>
                    <div style={{ fontSize: "1.25rem", fontWeight: 800, color: "#111827" }}>{v}</div>
                  </div>
                ))}
              </div>

              <CopyField
                label="Signup link — send this to the supplier"
                value={s.signupUrl}
                hint="Replace {CLICK_ID} with the supplier's own click identifier, or leave it for them to substitute."
              />
              <CopyField
                label="Their dashboard"
                value={s.dashboardUrl || s.dashboardPath}
                hint="Private link — anyone holding it can see this supplier's numbers. Rotate it if it leaks."
              />
            </div>
          )
        })
      )}
    </div>
  )
}
