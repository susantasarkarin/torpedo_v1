/**
 * One Finance record, opened in its own tab from any Finance list (owner
 * 2026-10-26). Every field is editable here; Save sends only what changed
 * (PUT /finance/records/{kind}/{id}, old values kept in edit_history).
 * A new record (id "new") is created through the kind's existing POST.
 */
import { useEffect, useMemo, useState } from "react"
import { Link, useParams } from "react-router-dom"
import { buildApiUrl } from "../../config"
import { authFetch } from "../../utils/api"
import { notify } from "../../utils/notify"
import { formatDate, formatDateTime } from "../../utils/format"
import { formatMoney } from "../../utils/currency"
import { FINANCE_KINDS, StatusBadge, apiKind, fieldLabel } from "../../components/finance/financeKinds"
import "../../styles/SalesPages.css"

const CREATE = {
  customers: "/finance/customers/", estimates: "/finance/estimates/", invoices: "/finance/invoices/",
  vendors: "/finance/vendors/", bills: "/finance/bills/", purchase_orders: "/finance/purchase-orders/",
  expenses: "/finance/expenses/", items: "/finance/items/", payments: "/finance/payments/received/",
}
const LIST_PATH = { purchase_orders: "purchase-orders" }
const DATE_FIELD = /(^date$|_date$|_at$)/
const NUMBER_FIELD = /(amount|total|balance|rate|percent|limit|paid|payables|receivables|quantity|price|tds|opening)/
const LONG_FIELD = /(notes|terms|address|description)/
const HIDDEN = new Set(["_id", "items", "line_items", "edit_history", "zoho_sync_history", "fills", "snapshot",
  "fingerprint", "invoices", "estimates", "backfill", "change", "customer_name", "ai_summary", "master_cleanup"])

const card = { background: "#fff", border: "1px solid #e6e3dc", borderRadius: 12, padding: 20, marginBottom: 16 }
const grid = { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: 14 }
const label = { display: "block", fontSize: "0.85rem", fontWeight: 600, color: "#55524c", marginBottom: 4 }
const input = { width: "100%", padding: "8px 10px", border: "1px solid #d6d2c8", borderRadius: 8, fontSize: "0.95rem",
  boxSizing: "border-box", background: "#fff" }

const toInput = (f, v) => {
  if (v === null || v === undefined) return ""
  if (DATE_FIELD.test(f)) return String(v).slice(0, 10)
  if (typeof v === "object") return JSON.stringify(v)
  return v
}

function Field({ f, value, onChange, statuses }) {
  const id = `fld-${f}`
  let control
  if (f === "status" && statuses) {
    control = (
      <select id={id} style={input} value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
        {[...new Set([value, ...statuses].filter(Boolean))].map((s) => <option key={s} value={s}>{s.replace(/_/g, " ")}</option>)}
      </select>
    )
  } else if (typeof value === "object" && value !== null && !Array.isArray(value) && !DATE_FIELD.test(f)) {
    const text = Object.values(value).filter((x) => x && typeof x !== "object").join(", ")
    control = <textarea id={id} style={{ ...input, minHeight: 64 }} value={text}
                        onChange={(e) => onChange(e.target.value)} />
  } else if (LONG_FIELD.test(f)) {
    control = <textarea id={id} style={{ ...input, minHeight: 80 }} value={toInput(f, value)} onChange={(e) => onChange(e.target.value)} />
  } else {
    const type = DATE_FIELD.test(f) ? "date" : NUMBER_FIELD.test(f) ? "number" : "text"
    control = <input id={id} type={type} style={input} value={toInput(f, value)}
                     onChange={(e) => onChange(type === "number" ? (e.target.value === "" ? null : Number(e.target.value)) : e.target.value)} />
  }
  return <div style={LONG_FIELD.test(f) ? { gridColumn: "1 / -1" } : undefined}><label htmlFor={id} style={label}>{fieldLabel(f)}</label>{control}</div>
}

function Lines({ items, onChange, currency }) {
  const set = (i, k, v) => onChange(items.map((it, n) => (n === i ? { ...it, [k]: v } : it)))
  const total = items.reduce((s, it) => s + (Number(it.quantity) || 0) * (Number(it.rate ?? it.unit_price) || 0), 0)
  return (
    <div style={{ overflowX: "auto" }}>
      <table className="lead-table" style={{ width: "100%", minWidth: 640 }}>
        <thead><tr><th>Description</th><th style={{ width: 110 }}>Qty</th><th style={{ width: 130 }}>Rate</th><th style={{ width: 140 }}>Amount</th><th style={{ width: 70 }} /></tr></thead>
        <tbody>
          {items.map((it, i) => (
            <tr key={i}>
              <td><input style={input} value={it.description || it.name || ""} onChange={(e) => set(i, "description", e.target.value)} aria-label="Description" /></td>
              <td><input style={input} type="number" value={it.quantity ?? ""} onChange={(e) => set(i, "quantity", Number(e.target.value))} aria-label="Quantity" /></td>
              <td><input style={input} type="number" step="0.01" value={it.rate ?? it.unit_price ?? ""} onChange={(e) => set(i, "rate", Number(e.target.value))} aria-label="Rate" /></td>
              <td>{formatMoney((Number(it.quantity) || 0) * (Number(it.rate ?? it.unit_price) || 0), currency)}</td>
              <td><button type="button" className="btn btn-outline" onClick={() => onChange(items.filter((_, n) => n !== i))} aria-label="Remove line">✕</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 10 }}>
        <button type="button" className="btn btn-outline" onClick={() => onChange([...items, { description: "", quantity: 1, rate: 0 }])}>+ Add line</button>
        <strong>Subtotal {formatMoney(total, currency)}</strong>
      </div>
    </div>
  )
}

function Related({ title, rows, kind, numberField, dateField, amountField }) {
  return (
    <section style={card}>
      <h2 style={{ fontSize: "1.05rem", margin: "0 0 12px" }}>{title} ({rows.length})</h2>
      {rows.length === 0 ? <p style={{ color: "#6b6b6b", margin: 0 }}>None yet.</p> : (
        <table className="lead-table" style={{ width: "100%" }}>
          <tbody>
            {rows.map((r) => (
              <tr key={r._id} onClick={() => window.open(`/admin/finance/record/${kind}/${r._id}`, "_blank", "noopener")}>
                <td><strong>{r[numberField]}</strong>{r.project_name ? <div style={{ color: "#6b6b6b", fontSize: "0.85rem" }}>{r.project_name}</div> : null}</td>
                <td>{formatDate(r[dateField])}</td>
                <td><StatusBadge status={r.status} /></td>
                <td style={{ textAlign: "right" }}>{formatMoney(r[amountField] || 0, r.currency_code || r.currency || "INR")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}

export default function FinanceRecordPage() {
  const { kind, id } = useParams()
  const cfg = FINANCE_KINDS[kind]
  const isNew = id === "new"
  const [doc, setDoc] = useState(null)
  const [draft, setDraft] = useState({})
  const [versions, setVersions] = useState([])
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")

  const load = async () => {
    if (isNew) { setDoc({ status: cfg?.statuses?.[0] || "active", items: [] }); return }
    try {
      const r = await authFetch(buildApiUrl(`/finance/records/${apiKind(kind)}/${id}`))
      if (!r.ok) throw new Error(r.status === 404 ? "This record does not exist (it may have been merged or hidden)." : `HTTP ${r.status}`)
      const d = await r.json()
      setDoc(d)
      setDraft({})
      document.title = `${d[cfg.numberField] || cfg.singular} · Finance`
      if (kind === "estimates" && d.opportunity_id) {
        authFetch(buildApiUrl(`/rfq/${d.opportunity_id}/estimates`)).then((x) => (x.ok ? x.json() : null))
          .then((v) => v && setVersions(v.versions || [])).catch(() => {})
      }
    } catch (e) {
      setError(e.message)
    }
  }
  useEffect(() => { if (cfg) load() }, [kind, id])

  const value = (f) => (f in draft ? draft[f] : doc?.[f])
  const set = (f, v) => setDraft((p) => ({ ...p, [f]: v }))
  const itemsKey = doc && !doc.items && doc.line_items ? "line_items" : "items"
  const dirty = Object.keys(draft).length > 0
  const shown = useMemo(() => new Set((cfg?.fields || []).flatMap(([, fs]) => fs)), [cfg])
  const others = doc ? Object.entries(doc).filter(([k, v]) => !shown.has(k) && !HIDDEN.has(k) && v !== null && v !== "" &&
    (typeof v !== "object" || v instanceof Date)) : []

  const save = async () => {
    setSaving(true)
    try {
      const r = isNew
        ? await authFetch(buildApiUrl(CREATE[kind]), { method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ ...doc, ...draft }) })
        : await authFetch(buildApiUrl(`/finance/records/${apiKind(kind)}/${id}`), { method: "PUT",
            headers: { "Content-Type": "application/json" }, body: JSON.stringify(draft) })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`)
      if (isNew) {
        const newId = d._id || d.id || d.customer?._id
        notify(`${cfg.singular} created`)
        if (newId) window.location.replace(`/admin/finance/record/${kind}/${newId}`)
        return
      }
      notify(d.changed?.length ? `Saved: ${d.changed.length} field(s) changed` : "Nothing changed")
      await load()
    } catch (e) {
      notify(`Could not save: ${e.message}`)
    } finally {
      setSaving(false)
    }
  }

  if (!cfg) return <div className="sales-page"><div className="error-alert">Unknown finance record type.</div></div>
  if (error) return <div className="sales-page"><div className="error-alert">{error}</div></div>
  if (!doc) return <div className="sales-page"><p>Loading…</p></div>

  const currency = value("currency_code") || value("currency") || "INR"
  const amount = value("total_amount") ?? value("total") ?? value("amount")
  return (
    <div className="sales-page">
      <div className="page-header">
        <div className="header-left">
          <Link to={`/admin/finance/${LIST_PATH[kind] || kind}`} style={{ color: "#6b6b6b", fontSize: "0.9rem" }}>← {cfg.title}</Link>
          <h1 className="cx-page-title" style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            {isNew ? `New ${cfg.singular.toLowerCase()}` : doc[cfg.numberField] || cfg.singular}
            {!isNew && <StatusBadge status={value("status")} />}
          </h1>
          <p className="subtitle">
            {doc.customer_name && <>{doc.customer_name} · </>}
            {doc.project_name && <>{doc.project_name} · </>}
            {amount != null && cfg.lines !== undefined && <>{formatMoney(amount, currency)} · </>}
            {doc.updated_at && <>updated {formatDateTime(doc.updated_at)}</>}
          </p>
        </div>
        <div className="header-actions">
          {doc.opportunity_id && <a className="btn btn-outline" href={`/admin/sales/rfq/${doc.opportunity_id}/estimate`} target="_blank" rel="noopener noreferrer">Open RFQ</a>}
          {(doc.ops_project_id || doc.ops_project_ids?.[0]) && (
            <a className="btn btn-outline" href={`/admin/operations/projects/${doc.ops_project_id || doc.ops_project_ids[0]}`} target="_blank" rel="noopener noreferrer">Open project</a>
          )}
          {kind === "customers" && doc.crm_account_id && (
            <a className="btn btn-outline" href={`/admin/sales/accounts?account=${doc.crm_account_id}`} target="_blank" rel="noopener noreferrer">Open account</a>
          )}
          {dirty && !isNew && <button className="btn btn-outline" onClick={() => setDraft({})} disabled={saving}>Discard</button>}
          <button className="btn btn-primary" onClick={save} disabled={saving || (!dirty && !isNew)}>{saving ? "Saving…" : isNew ? "Create" : "Save changes"}</button>
        </div>
      </div>

      {cfg.fields.map(([title, fs]) => (
        <section key={title} style={card}>
          <h2 style={{ fontSize: "1.05rem", margin: "0 0 14px" }}>{title}</h2>
          <div style={grid}>
            {fs.map((f) => <Field key={f} f={f} value={value(f)} onChange={(v) => set(f, v)} statuses={cfg.statuses} />)}
          </div>
        </section>
      ))}

      {cfg.lines && (
        <section style={card}>
          <h2 style={{ fontSize: "1.05rem", margin: "0 0 14px" }}>Line items</h2>
          <Lines items={value(itemsKey) || []} onChange={(v) => set(itemsKey, v)} currency={currency} />
        </section>
      )}

      {kind === "customers" && !isNew && (
        <>
          <Related title="Estimates" rows={doc.estimates || []} kind="estimates" numberField="estimate_number" dateField="date" amountField="total_amount" />
          <Related title="Invoices" rows={doc.invoices || []} kind="invoices" numberField="invoice_number" dateField="invoice_date" amountField="total" />
        </>
      )}

      {kind === "estimates" && versions.length > 1 && (
        <section style={card}>
          <h2 style={{ fontSize: "1.05rem", margin: "0 0 12px" }}>Versions ({versions.length})</h2>
          <table className="lead-table" style={{ width: "100%" }}>
            <tbody>
              {versions.map((v) => (
                <tr key={v._id} onClick={() => v._id !== id && window.open(`/admin/finance/record/estimates/${v._id}`, "_blank", "noopener")}
                    style={v._id === id ? { background: "#fbf6ec" } : undefined}>
                  <td><strong>V{v.version}</strong></td>
                  <td>{formatDate(v.date)}</td>
                  <td><StatusBadge status={v.status} /></td>
                  <td>{formatMoney(v.total_amount || 0, v.currency || "INR")}</td>
                  <td style={{ color: "#55524c" }}>{[...(v.change?.scope || []), ...(v.change?.price || [])].join("; ") || v.change_reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {others.length > 0 && (
        <section style={card}>
          <h2 style={{ fontSize: "1.05rem", margin: "0 0 14px" }}>Other details</h2>
          <div style={grid}>
            {others.map(([k, v]) => (
              <div key={k}><div style={label}>{fieldLabel(k)}</div>
                <div style={{ wordBreak: "break-word" }}>{DATE_FIELD.test(k) ? formatDateTime(v) : String(v)}</div></div>
            ))}
          </div>
        </section>
      )}
      {doc.edit_history?.length > 0 && <p style={{ color: "#6b6b6b" }}>Edited {doc.edit_history.length} time(s); previous values are kept.</p>}
    </div>
  )
}
