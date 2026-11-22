import { useEffect, useState } from "react"
import { buildApiUrl } from "../../config"
import { confirmAction } from "../../utils/notify"
import { authFetch } from "../../utils/api"
import { colors, card, control, tones } from "../../components/panel-admin/tokens"
import { SectionHeader, Notice, Badge, CountGrid, Field, Modal, ActionMenu } from "../../components/panel-admin/ui"

const PANEL_ADMIN_API_PREFIX = "/api/panel-admin"

/**
 * Traffic suppliers — Facebook, Google, Quora and third-party panel vendors.
 *
 * Suppliers live on the SFW panel (it owns signup, so it owns attribution);
 * this page proxies through Torpedo so they are managed alongside the rest of
 * the panel. The two links per row are the whole point of the page: the signup
 * URL goes to the vendor, the dashboard URL is what they check their numbers on.
 */

const toPaise = (rupees) => Math.round(parseFloat(rupees || 0) * 100)
const toRupees = (paise) => ((paise || 0) / 100).toLocaleString("en-IN", { maximumFractionDigits: 2 })

const small = { padding: "0.35rem 0.8rem", fontSize: "0.85rem", whiteSpace: "nowrap" }
const hint = { fontSize: "0.8rem", color: colors.muted, margin: "0.3rem 0 0", lineHeight: 1.5 }
const input = { ...control, width: "100%" }
const EMPTY_FORM = { name: "", slug: "", payoutPerConversionPaise: "", postbackUrl: "", postbackEnabled: false, notes: "", countryRates: [] }

function CopyField({ label, value, hint: help }) {
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
    <div style={{ marginTop: "0.9rem" }}>
      <div style={{ fontSize: "0.8rem", fontWeight: 600, color: colors.text }}>{label}</div>
      <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.3rem" }}>
        <input
          readOnly
          aria-label={label}
          value={value}
          onFocus={(e) => e.target.select()}
          style={{ ...control, flex: 1, minWidth: 0, fontFamily: "ui-monospace, Menlo, monospace", background: "#faf9f7" }}
        />
        <button type="button" className="btn btn-outline" onClick={copy}
          style={{ ...small, ...(copied ? { background: tones.good.bg, color: tones.good.fg, borderColor: tones.good.border } : {}) }}>
          {copied ? "Copied ✓" : "Copy"}
        </button>
      </div>
      {help && <p style={hint}>{help}</p>}
    </div>
  )
}

/**
 * Per-country rate rows. `rows` are {country, rate} with rate in rupees — the
 * conversion to paise happens once, at submit, so what is typed is what is
 * shown throughout editing.
 */
function CountryRateEditor({ rows, onChange, fallbackRate }) {
  const set = (i, patch) => onChange(rows.map((r, idx) => (idx === i ? { ...r, ...patch } : r)))
  const add = () => onChange([...rows, { country: "", rate: "" }])
  const remove = (i) => onChange(rows.filter((_, idx) => idx !== i))

  return (
    <div>
      <div style={{ fontSize: "0.85rem", fontWeight: 600, color: colors.text }}>Per-country rates</div>
      <p style={{ ...hint, margin: "0.2rem 0 0.6rem" }}>
        Optional. Any country without a row here is paid at the default rate
        {fallbackRate ? ` (₹${fallbackRate})` : ""}. The rate that applies to a conversion is
        frozen when it converts, so changing a rate later never re-prices what you have already been invoiced for.
      </p>
      {rows.map((r, i) => (
        <div key={i} style={{ display: "flex", gap: "0.5rem", marginBottom: "0.45rem", alignItems: "center", flexWrap: "wrap" }}>
          <input
            aria-label="Country code"
            style={{ ...control, width: "4.5rem", textTransform: "uppercase" }}
            placeholder="IN" maxLength={2} value={r.country}
            onChange={(e) => set(i, { country: e.target.value.toUpperCase().replace(/[^A-Z]/g, "") })}
          />
          <span style={{ color: colors.muted, fontSize: "0.875rem" }}>₹</span>
          <input
            aria-label="Rate in rupees"
            style={{ ...control, width: "6.5rem" }} type="number" step="0.01" min="0"
            placeholder="25.00" value={r.rate}
            onChange={(e) => set(i, { rate: e.target.value })}
          />
          <span style={{ color: colors.muted, fontSize: "0.85rem" }}>per profile-complete</span>
          <button type="button" onClick={() => remove(i)} style={{
            marginLeft: "auto", border: "none", background: "none", color: colors.bad,
            cursor: "pointer", fontSize: "0.85rem", fontWeight: 600,
          }}>Remove</button>
        </div>
      ))}
      <button type="button" className="btn btn-outline" onClick={add} style={{ ...small, borderStyle: "dashed" }}>
        + Add country rate
      </button>
    </div>
  )
}

export default function TrafficSuppliers({ embedded = false }) {
  const [suppliers, setSuppliers] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [showForm, setShowForm] = useState(false)
  const [saving, setSaving] = useState(false)
  // One vendor commonly supplies several countries at different rates. Empty
  // by default: a vendor on a single flat rate needs no country rows.
  const [form, setForm] = useState(EMPTY_FORM)
  const [editingRates, setEditingRates] = useState(null) // { slug, rows } while editing

  const sessionId = localStorage.getItem("session_id") || ""

  const fetchSuppliers = async () => {
    setLoading(true)
    setError("")
    try {
      const res = await authFetch(buildApiUrl(`${PANEL_ADMIN_API_PREFIX}/suppliers`), {
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
      const res = await authFetch(buildApiUrl(`${PANEL_ADMIN_API_PREFIX}/suppliers`), {
        method: "POST",
        headers: { Authorization: sessionId, "Content-Type": "application/json" },
        body: JSON.stringify({
          ...form,
          // Rupees in the form, paise on the wire — the panel stores money as
          // integer paise everywhere else.
          payoutPerConversionPaise: toPaise(form.payoutPerConversionPaise),
          countryRates: form.countryRates
            .filter((r) => r.country.trim().length === 2)
            .map((r) => ({ country: r.country.toUpperCase(), payoutPerConversionPaise: toPaise(r.rate) })),
        }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || "Could not create supplier")
      setForm(EMPTY_FORM)
      setShowForm(false)
      fetchSuppliers()
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  const toggleStatus = async (s) => {
    await authFetch(buildApiUrl(`${PANEL_ADMIN_API_PREFIX}/suppliers/${s.slug}`), {
      method: "PATCH",
      headers: { Authorization: sessionId, "Content-Type": "application/json" },
      body: JSON.stringify({ status: s.status === "active" ? "paused" : "active" }),
    })
    fetchSuppliers()
  }

  const saveRates = async (slug, rows) => {
    setError("")
    const res = await authFetch(buildApiUrl(`${PANEL_ADMIN_API_PREFIX}/suppliers/${slug}`), {
      method: "PATCH",
      headers: { Authorization: sessionId, "Content-Type": "application/json" },
      body: JSON.stringify({
        countryRates: rows
          .filter((r) => r.country.trim().length === 2)
          .map((r) => ({ country: r.country.toUpperCase(), payoutPerConversionPaise: toPaise(r.rate) })),
      }),
    })
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      setError(data.detail || "Could not save rates")
      return
    }
    setEditingRates(null)
    fetchSuppliers()
  }

  const rotate = async (s) => {
    if (!(await confirmAction(`Rotate ${s.name}'s dashboard link?\n\nTheir current link stops working immediately and you will need to send them the new one.`))) return
    await authFetch(buildApiUrl(`${PANEL_ADMIN_API_PREFIX}/suppliers/${s.slug}/rotate-token`), {
      method: "POST",
      headers: { Authorization: sessionId },
    })
    fetchSuppliers()
  }

  // Toggle the rate editor for one supplier (a second click closes it).
  const toggleRates = (s) => setEditingRates(editingRates?.slug === s.slug ? null : {
    slug: s.slug,
    rows: (s.countryRates || []).map((r) => ({
      country: r.country, rate: String((r.payoutPerConversionPaise || 0) / 100),
    })),
  })

  return (
    <div style={{ padding: embedded ? 0 : "1.5rem", maxWidth: "1000px" }}>
      <SectionHeader
        title={embedded ? "Traffic suppliers" : "Traffic Suppliers"}
        description={<>
          Where panel signups come from. Each supplier gets a tracked signup link and a private dashboard.
          A signup counts as <strong>payable once the panelist completes their profile</strong>, the point they can be routed to a survey.
        </>}
        actions={
          <button type="button" className="btn btn-primary" onClick={() => { setError(""); setShowForm(true) }}>
            + Add supplier
          </button>
        }
      />

      {error && !showForm && <Notice tone="bad" style={{ marginBottom: "1rem" }}>{error}</Notice>}

      <Modal
        open={showForm}
        title="Add supplier"
        width={640}
        busy={saving}
        onClose={() => setShowForm(false)}
        footer={<>
          <button type="button" className="btn btn-outline" onClick={() => setShowForm(false)} disabled={saving}>Cancel</button>
          <button type="submit" form="add-supplier-form" className="btn btn-primary" disabled={saving}>
            {saving ? "Creating…" : "Create supplier"}
          </button>
        </>}
      >
        <form id="add-supplier-form" onSubmit={submit}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "0 1rem" }}>
            <Field label="Name" htmlFor="sup-name" required>
              <input id="sup-name" style={input} required value={form.name} placeholder="Quora Ads"
                onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </Field>
            <Field label="Slug" htmlFor="sup-slug" required>
              <input id="sup-slug" style={input} required value={form.slug} placeholder="quora"
                // "-" escaped: browsers compile `pattern` with the regex v flag,
                // where an unescaped "-" makes the whole pattern invalid (and ignored).
                pattern="[a-z0-9][a-z0-9_\-]{1,40}"
                onChange={(e) => setForm({ ...form, slug: e.target.value.toLowerCase() })} />
              <p style={hint}>Appears in the link. Lowercase, no spaces. Cannot be changed later.</p>
            </Field>
            <Field label="Default payout per conversion (₹)" htmlFor="sup-payout">
              <input id="sup-payout" style={input} type="number" step="0.01" min="0" value={form.payoutPerConversionPaise}
                placeholder="25.00"
                onChange={(e) => setForm({ ...form, payoutPerConversionPaise: e.target.value })} />
              <p style={hint}>Used for any country without its own rate below.</p>
            </Field>
            <Field label="Postback URL" hint="(optional)" htmlFor="sup-postback">
              <input id="sup-postback" style={input} value={form.postbackUrl}
                placeholder="https://vendor.com/pb?click={CLICK_ID}"
                onChange={(e) => setForm({ ...form, postbackUrl: e.target.value })} />
              <label style={{ display: "flex", alignItems: "center", gap: "0.4rem", marginTop: "0.45rem", fontSize: "0.85rem", color: colors.text }}>
                <input type="checkbox" checked={form.postbackEnabled}
                  onChange={(e) => setForm({ ...form, postbackEnabled: e.target.checked })} />
                Fire a postback when a signup converts
              </label>
            </Field>
          </div>

          <div style={{ marginTop: "0.25rem", paddingTop: "1rem", borderTop: `1px solid ${colors.border}` }}>
            <CountryRateEditor
              rows={form.countryRates}
              fallbackRate={form.payoutPerConversionPaise}
              onChange={(countryRates) => setForm({ ...form, countryRates })}
            />
          </div>
          {error && <Notice tone="bad" style={{ marginTop: "1rem" }}>{error}</Notice>}
        </form>
      </Modal>

      {loading ? (
        <p style={{ color: colors.muted }}>Loading…</p>
      ) : suppliers.length === 0 ? (
        <div style={{ ...card, textAlign: "center", padding: "2.5rem 1.25rem" }}>
          <p style={{ fontWeight: 700, color: colors.text, margin: 0 }}>No suppliers yet</p>
          <p style={{ color: colors.muted, fontSize: "0.9rem", margin: "0.4rem 0 0" }}>
            Add one for each traffic source — Facebook, Google, Quora, or a panel vendor — and send them their tracked signup link.
            Signups that arrive without a link are recorded as organic.
          </p>
        </div>
      ) : (
        suppliers.map((s) => {
          const convRate = s.signups > 0 ? ((s.converted / s.signups) * 100).toFixed(1) : "0.0"
          const editing = editingRates?.slug === s.slug
          return (
            <div key={s.slug} style={card}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "0.75rem", flexWrap: "wrap" }}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", flexWrap: "wrap" }}>
                    <span style={{ fontSize: "1.05rem", fontWeight: 700, color: colors.text }}>{s.name}</span>
                    <Badge tone={s.status === "active" ? "good" : "warn"}>{s.status}</Badge>
                  </div>
                  <div style={{ color: colors.muted, fontSize: "0.85rem", marginTop: "0.2rem" }}>
                    <code>{s.slug}</code>
                    {s.postbackEnabled && " · postback on"}
                  </div>
                </div>
                <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                  <button type="button" className="btn btn-outline" style={small} aria-expanded={editing} onClick={() => toggleRates(s)}>
                    {editing ? "Close rates" : "Edit rates"}
                  </button>
                  <ActionMenu
                    label="More"
                    buttonStyle={small}
                    items={[
                      { label: s.status === "active" ? "Pause supplier" : "Activate supplier", onClick: () => toggleStatus(s) },
                      { label: "Rotate dashboard link…", onClick: () => rotate(s) },
                    ]}
                  />
                </div>
              </div>

              <CountGrid min={120} items={[
                { label: "Signups", value: s.signups },
                { label: "Profile complete", value: s.converted, color: colors.good },
                { label: "Conversion", value: `${convRate}%` },
                // Summed from the rate frozen on each conversion, so a vendor
                // running several countries totals correctly rather than
                // count x one rate.
                { label: "Accrued", value: `₹${toRupees(s.accruedPaise)}` },
              ]} />

              {(s.countryRates || []).length > 0 && !editing && (
                <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap", alignItems: "center" }}>
                  <span style={{ fontSize: "0.8rem", color: colors.muted }}>Rates:</span>
                  {s.countryRates.map((r) => (
                    <Badge key={r.country}>{r.country} ₹{toRupees(r.payoutPerConversionPaise)}</Badge>
                  ))}
                  <Badge tone="accent">other ₹{toRupees(s.payoutPerConversionPaise)}</Badge>
                </div>
              )}

              {editing && (
                <div style={{ marginTop: "0.5rem", paddingTop: "1rem", borderTop: `1px solid ${colors.border}` }}>
                  <CountryRateEditor
                    rows={editingRates.rows}
                    fallbackRate={toRupees(s.payoutPerConversionPaise)}
                    onChange={(rows) => setEditingRates({ ...editingRates, rows })}
                  />
                  <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.75rem" }}>
                    <button type="button" className="btn btn-primary" style={small} onClick={() => saveRates(s.slug, editingRates.rows)}>Save rates</button>
                    <button type="button" className="btn btn-outline" style={small} onClick={() => setEditingRates(null)}>Cancel</button>
                  </div>
                </div>
              )}

              <CopyField
                label="Signup link: send this to the supplier"
                value={s.signupUrl}
                hint="Replace {CLICK_ID} with the supplier's own click identifier, or leave it for them to substitute."
              />
              <CopyField
                label="Their dashboard"
                value={s.dashboardUrl || s.dashboardPath}
                hint="Private link: anyone holding it can see this supplier's numbers. Rotate it if it leaks."
              />
            </div>
          )
        })
      )}
    </div>
  )
}
