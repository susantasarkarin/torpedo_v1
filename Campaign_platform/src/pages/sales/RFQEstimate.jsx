/**
 * Create Estimate from an RFQ
 * Path: /admin/sales/rfq/:rfqId/estimate
 *
 * Prefilled from the RFQ brief (study, completes, CPI or value, LOI, IR,
 * country); every line is editable. Saving posts to
 * POST /api/rfq/{id}/convert-to-estimate, which writes the Finance estimate,
 * moves the RFQ to Quoted and links the two.
 */
import { useEffect, useMemo, useState } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import { buildApiUrl } from "../../config"
import { authFetch } from "../../utils/api"
import { formatMoney } from "../../utils/currency"
import "../../styles/SalesPages.css"
import "./RFQEstimate.css"

const CURRENCIES = ["USD", "INR", "EUR", "GBP", "AUD", "SGD", "AED"]

function firstNumber(value) {
  if (typeof value === "number") return value
  const m = String(value || "").match(/\d[\d,]*(?:\.\d+)?/)
  return m ? parseFloat(m[0].replace(/,/g, "")) : 0
}

// The same line the backend would generate, so what you see is what is saved.
function lineFromRfq(rfq) {
  const completes = firstNumber(rfq.sample_size)
  const value = firstNumber(rfq.final_value || rfq.manual_value || rfq.extracted_value)
  const rate = firstNumber(rfq.cpi) || (completes ? value / completes : value)
  const parts = [rfq.methodology || "Online Survey"]
  if (rfq.country) parts[0] += ` - ${rfq.country}`
  if (rfq.loi) parts.push(`LOI: ${firstNumber(rfq.loi)} mins`)
  if (rfq.ir) parts.push(`IR: ${firstNumber(rfq.ir)}%`)
  return {
    description: parts.join(" | "),
    quantity: completes || 1,
    unit: completes ? "completes" : "project",
    unit_price: Math.round(rate * 100) / 100,
  }
}

function RFQEstimate() {
  const { rfqId } = useParams()
  const navigate = useNavigate()
  const [rfq, setRfq] = useState(null)
  const [customers, setCustomers] = useState([])
  const [error, setError] = useState(null)
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState({
    customer_id: "", currency: "", discount_percent: 0, tax_percent: 18, due_days: 15, notes: "",
  })
  const [lines, setLines] = useState([])

  useEffect(() => {
    const headers = { Authorization: localStorage.getItem("session_id") }
    ;(async () => {
      try {
        const [rfqRes, custRes] = await Promise.all([
          authFetch(buildApiUrl(`/api/rfq/${rfqId}`), { headers }),
          authFetch(buildApiUrl(`/finance/customers/`), { headers }),
        ])
        const rfqData = await rfqRes.json()
        if (!rfqRes.ok) throw new Error(rfqData.detail || "RFQ not found")
        const r = rfqData.rfq
        setRfq(r)
        setLines([lineFromRfq(r)])
        setForm(f => ({ ...f, currency: (r.final_currency || r.extracted_currency || "USD").toUpperCase() }))
        if (custRes.ok) setCustomers((await custRes.json()) || [])
      } catch (e) {
        setError(e.message)
      }
    })()
  }, [rfqId])

  const totals = useMemo(() => {
    const subtotal = lines.reduce((s, l) => s + (Number(l.quantity) || 0) * (Number(l.unit_price) || 0), 0)
    const discount = subtotal * (Number(form.discount_percent) || 0) / 100
    const tax = (subtotal - discount) * (Number(form.tax_percent) || 0) / 100
    return { subtotal, discount, tax, total: subtotal - discount + tax }
  }, [lines, form.discount_percent, form.tax_percent])

  const setLine = (i, field, value) =>
    setLines(prev => prev.map((l, j) => (j === i ? { ...l, [field]: value } : l)))

  const save = async () => {
    setSaving(true)
    setError(null)
    try {
      const line_items = lines
        .filter(l => l.description.trim())
        .map(l => {
          const quantity = Number(l.quantity) || 0
          const unit_price = Number(l.unit_price) || 0
          return { description: l.description.trim(), quantity, unit: l.unit, unit_price,
                   amount: Math.round(quantity * unit_price * 100) / 100 }
        })
      if (!line_items.length) throw new Error("Add at least one line")
      const res = await authFetch(buildApiUrl(`/api/rfq/${rfq.opportunity_id}/convert-to-estimate`), {
        method: "POST",
        headers: { Authorization: localStorage.getItem("session_id"), "Content-Type": "application/json" },
        body: JSON.stringify({
          ...form,
          customer_id: form.customer_id || null,
          discount_percent: Number(form.discount_percent) || 0,
          tax_percent: Number(form.tax_percent) || 0,
          due_days: Number(form.due_days) || 15,
          line_items,
        }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || "Could not create the estimate")
      navigate("/admin/finance/estimates", { state: { created: data.document_number } })
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  if (error && !rfq) {
    return (
      <div className="sales-page">
        <p className="error-alert">{error}</p>
        <Link to="/admin/sales/rfq" className="btn btn-outline">← Back to RFQs</Link>
      </div>
    )
  }
  if (!rfq) return <div className="sales-page"><p>Loading RFQ…</p></div>

  const money = (v) => formatMoney(v, form.currency || "USD")

  return (
    <div className="sales-page rfq-estimate">
      <div className="page-header">
        <div className="header-left">
          <h1 className="cx-page-title">Create Estimate</h1>
          <p className="subtitle">
            {rfq.title || "Untitled RFQ"} · {rfq.account_name || rfq.contact_email || "—"} · {rfq.rfq_id}
          </p>
        </div>
        <div className="header-actions">
          <Link to="/admin/sales/rfq" className="btn btn-outline">Cancel</Link>
          <button className="btn btn-primary" onClick={save} disabled={saving}>
            {saving ? "Saving…" : "Save Estimate"}
          </button>
        </div>
      </div>

      {error && <div className="error-alert">{error}</div>}

      <section className="est-card">
        <h2>Brief</h2>
        <dl className="est-brief">
          <div><dt>Methodology</dt><dd>{rfq.methodology || "—"}</dd></div>
          <div><dt>Country</dt><dd>{rfq.country || "—"}</dd></div>
          <div><dt>Completes</dt><dd>{rfq.sample_size || "—"}</dd></div>
          <div><dt>LOI</dt><dd>{rfq.loi || "—"}</dd></div>
          <div><dt>IR</dt><dd>{rfq.ir || "—"}</dd></div>
          <div><dt>Audience</dt><dd>{rfq.target_audience || "—"}</dd></div>
        </dl>
      </section>

      <section className="est-card">
        <h2>Bill to</h2>
        <div className="est-grid">
          <label>
            Customer
            <select value={form.customer_id} onChange={e => setForm({ ...form, customer_id: e.target.value })}>
              <option value="">Match from RFQ ({rfq.account_name || rfq.contact_email || "client"})</option>
              {customers.map(c => (
                <option key={c._id} value={c._id}>{c.name}{c.email ? ` (${c.email})` : ""}</option>
              ))}
            </select>
          </label>
          <label>
            Currency
            <select value={form.currency} onChange={e => setForm({ ...form, currency: e.target.value })}>
              {[...new Set([form.currency, ...CURRENCIES])].filter(Boolean).map(c => <option key={c}>{c}</option>)}
            </select>
          </label>
          <label>
            Valid for (days)
            <input type="number" min="1" value={form.due_days} onChange={e => setForm({ ...form, due_days: e.target.value })} />
          </label>
        </div>
      </section>

      <section className="est-card">
        <h2>Line items</h2>
        <div className="est-table-wrap">
          <table className="est-table">
            <thead>
              <tr>
                <th>Description</th><th>Qty</th><th>Unit</th><th>Rate</th><th>Amount</th><th aria-label="Remove" />
              </tr>
            </thead>
            <tbody>
              {lines.map((l, i) => (
                <tr key={i}>
                  <td><input value={l.description} onChange={e => setLine(i, "description", e.target.value)} aria-label="Description" /></td>
                  <td><input type="number" min="0" value={l.quantity} onChange={e => setLine(i, "quantity", e.target.value)} aria-label="Quantity" /></td>
                  <td><input value={l.unit} onChange={e => setLine(i, "unit", e.target.value)} aria-label="Unit" /></td>
                  <td><input type="number" min="0" step="0.01" value={l.unit_price} onChange={e => setLine(i, "unit_price", e.target.value)} aria-label="Rate" /></td>
                  <td className="est-amount">{money((Number(l.quantity) || 0) * (Number(l.unit_price) || 0))}</td>
                  <td>
                    <button type="button" className="est-remove" onClick={() => setLines(lines.filter((_, j) => j !== i))}
                            disabled={lines.length === 1} aria-label="Remove line">×</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <button type="button" className="btn btn-outline btn-sm"
                onClick={() => setLines([...lines, { description: "", quantity: 1, unit: "project", unit_price: 0 }])}>
          + Add line
        </button>

        <div className="est-totals">
          <div><span>Subtotal</span><span>{money(totals.subtotal)}</span></div>
          <div>
            <span>Discount <input type="number" min="0" max="100" value={form.discount_percent}
                                  onChange={e => setForm({ ...form, discount_percent: e.target.value })} aria-label="Discount percent" />%</span>
            <span>−{money(totals.discount)}</span>
          </div>
          <div>
            <span>Tax <input type="number" min="0" max="100" value={form.tax_percent}
                             onChange={e => setForm({ ...form, tax_percent: e.target.value })} aria-label="Tax percent" />%</span>
            <span>{money(totals.tax)}</span>
          </div>
          <div className="est-total"><span>Total</span><span>{money(totals.total)}</span></div>
        </div>
      </section>

      <section className="est-card">
        <h2>Notes</h2>
        <textarea rows={3} value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })}
                  placeholder={`Estimate for ${rfq.title || "this RFQ"}`} />
      </section>
    </div>
  )
}

export default RFQEstimate
