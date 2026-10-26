/**
 * Finance tabs as configuration (owner 2026-10-26): every tab is the shared
 * Sales list (LeadTable) over GET /finance/records/{kind}, and every row opens
 * the one record page (/admin/finance/record/{kind}/{id}) in a new tab.
 *
 * columns: LeadTable columns ({ key, label, width, render, sortable })
 * fields:  the record page's editable fields, in groups; anything else on the
 *          record shows read-only under "Other details"
 * lines:   true when the record has editable line items
 */
import { formatDate } from "../../utils/format"
import { formatMoney } from "../../utils/currency"

const DASH = <span style={{ color: "#9a9a9a" }}>—</span>
const clip = (v) => (v || v === 0 ? <div className="cell-clip" title={String(v)}>{v}</div> : DASH)
const day = (v) => (v ? formatDate(v) : DASH)
const money = (v, cur) => (v || v === 0 ? formatMoney(v, cur || "INR") : DASH)

const STATUS_COLOURS = {
  paid: ["#e7f6ec", "#1e7a3c"], accepted: ["#e7f6ec", "#1e7a3c"], active: ["#e7f6ec", "#1e7a3c"],
  sent: ["#e8f0fe", "#1a56b8"], draft: ["#f1f1ef", "#55524c"], overdue: ["#fdecea", "#b3261e"],
  declined: ["#fdecea", "#b3261e"], expired: ["#f4efe6", "#8a6d3b"], superseded: ["#f4efe6", "#8a6d3b"],
  written_off: ["#f3e8fd", "#6b3fa0"], void: ["#f1f1ef", "#55524c"], partially_paid: ["#fff4e0", "#9a5b00"],
}

export function StatusBadge({ status }) {
  if (!status) return DASH
  const [bg, fg] = STATUS_COLOURS[status] || ["#f1f1ef", "#55524c"]
  return (
    <span style={{ background: bg, color: fg, borderRadius: 999, padding: "2px 10px", fontSize: "0.85rem",
                   fontWeight: 600, whiteSpace: "nowrap" }}>
      {status.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase())}
    </span>
  )
}

const status = { key: "status", label: "Status", width: 130, render: (r) => <StatusBadge status={r.status} /> }

export const FINANCE_KINDS = {
  customers: {
    title: "Customers", singular: "Customer", numberField: "name",
    subtitle: "The CRM accounts we quote or bill — one per account",
    columns: [
      { key: "name", label: "Customer", width: 260, required: true, render: (r) => <strong className="cell-clip">{r.name}</strong> },
      { key: "legal_name", label: "Billed as", width: 220, sortable: false, render: (r) => clip(r.legal_name || r.company_name) },
      { key: "estimate_count", label: "Estimates", width: 100, sortable: false, render: (r) => clip(r.estimate_count) },
      { key: "invoice_count", label: "Invoices", width: 100, sortable: false, render: (r) => clip(r.invoice_count) },
      { key: "balance_due_total", label: "Outstanding", width: 140, sortable: false, render: (r) => money(r.balance_due_total, r.currency_code) },
      { key: "gstin", label: "GSTIN", width: 160, sortable: false, render: (r) => clip(r.gstin) },
      { key: "email", label: "Email", width: 220, sortable: false, render: (r) => clip(r.email) },
    ],
    fields: [
      ["Company", ["name", "legal_name", "company_name", "customer_number", "status"]],
      ["Contact", ["email", "phone", "billing_address", "shipping_address"]],
      ["Tax & terms", ["gstin", "pan", "gst_treatment", "currency_code", "payment_terms", "credit_limit"]],
      ["Notes", ["notes"]],
    ],
  },
  estimates: {
    title: "Estimates", singular: "Estimate", numberField: "estimate_number", lines: true,
    subtitle: "One per RFQ; a change of scope or price is a new version",
    statuses: ["draft", "sent", "accepted", "declined", "expired"],
    columns: [
      { key: "estimate_number", label: "Estimate", width: 210, required: true,
        render: (r) => <div><strong className="cell-clip">{r.estimate_number}</strong>
          {r.project_name && <div className="cell-clip" style={{ color: "#6b6b6b", fontSize: "0.85rem" }} title={r.project_name}>{r.project_name}</div>}</div> },
      { key: "customer_name", label: "Customer", width: 220, render: (r) => clip(r.customer_name) },
      { key: "date", label: "Date", width: 120, render: (r) => day(r.date || r.estimate_date) },
      { key: "expiry_date", label: "Valid until", width: 120, render: (r) => day(r.expiry_date) },
      status,
      { key: "total_amount", label: "Amount", width: 140, render: (r) => money(r.total_amount, r.currency_code || r.currency) },
      { key: "version", label: "Version", width: 90, sortable: false, render: (r) => clip(r.version ? `V${r.version}` : null) },
    ],
    fields: [
      ["Estimate", ["estimate_number", "status", "date", "expiry_date", "currency_code", "project_name"]],
      ["Terms", ["discount_percent", "tax_percent", "tax_amount", "notes", "terms"]],
    ],
  },
  invoices: {
    title: "Invoices", singular: "Invoice", numberField: "invoice_number", lines: true,
    subtitle: "Invoices raised to clients (matched to Zoho)",
    statuses: ["draft", "sent", "overdue", "partially_paid", "paid", "written_off", "void"],
    columns: [
      { key: "invoice_number", label: "Invoice", width: 170, required: true, render: (r) => <strong className="cell-clip">{r.invoice_number}</strong> },
      { key: "customer_name", label: "Customer", width: 230, sortable: false, render: (r) => clip(r.customer_name) },
      { key: "invoice_date", label: "Date", width: 120, render: (r) => day(r.invoice_date) },
      { key: "due_date", label: "Due", width: 120, render: (r) => day(r.due_date) },
      status,
      { key: "total", label: "Amount", width: 140, render: (r) => money(r.total ?? r.total_amount, r.currency_code) },
      { key: "balance_due", label: "Balance due", width: 140, render: (r) => money(r.balance_due, r.currency_code) },
      { key: "po_reference", label: "Client PO", width: 140, sortable: false, render: (r) => clip(r.po_reference) },
    ],
    fields: [
      ["Invoice", ["invoice_number", "status", "invoice_date", "due_date", "currency_code", "po_reference", "branch"]],
      ["Amounts", ["total", "amount_paid", "balance_due", "payment_status", "tax_amount", "tds_amount"]],
      ["Tax & notes", ["gstin", "gst_treatment", "notes"]],
    ],
  },
  payments: {
    title: "Payments", singular: "Payment", api: "payments_received", numberField: "payment_number",
    subtitle: "Payments received from clients",
    columns: [
      { key: "payment_number", label: "Payment", width: 160, required: true, render: (r) => <strong className="cell-clip">{r.payment_number || r.reference}</strong> },
      { key: "customer_name", label: "Customer", width: 220, sortable: false, render: (r) => clip(r.customer_name) },
      { key: "payment_date", label: "Date", width: 120, render: (r) => day(r.payment_date) },
      { key: "invoice_number", label: "Invoice", width: 150, sortable: false, render: (r) => clip(r.invoice_number) },
      { key: "amount", label: "Amount", width: 140, render: (r) => money(r.amount, r.currency_code) },
      { key: "payment_mode", label: "Mode", width: 120, sortable: false, render: (r) => clip(r.payment_mode) },
    ],
    fields: [["Payment", ["payment_number", "payment_date", "amount", "currency_code", "payment_mode", "reference", "invoice_number", "notes"]]],
  },
  vendors: {
    title: "Vendors", singular: "Vendor", numberField: "name",
    subtitle: "Panel and fieldwork suppliers we pay",
    columns: [
      { key: "name", label: "Vendor", width: 260, required: true, render: (r) => <strong className="cell-clip">{r.name}</strong> },
      { key: "vendor_type", label: "Type", width: 140, sortable: false, render: (r) => clip(r.vendor_type) },
      { key: "email", label: "Email", width: 220, sortable: false, render: (r) => clip(r.email) },
      { key: "total_payables", label: "Payable", width: 130, sortable: false, render: (r) => money(r.total_payables, r.currency) },
      status,
    ],
    fields: [
      ["Vendor", ["name", "vendor_type", "status", "email", "phone", "billing_address"]],
      ["Tax & terms", ["gstin", "pan", "gst_treatment", "currency", "payment_terms", "opening_balance"]],
      ["Notes", ["notes"]],
    ],
  },
  bills: {
    title: "Bills", singular: "Bill", numberField: "bill_number", lines: true, subtitle: "Vendor bills",
    columns: [
      { key: "bill_number", label: "Bill", width: 160, required: true, render: (r) => <strong className="cell-clip">{r.bill_number}</strong> },
      { key: "vendor_name", label: "Vendor", width: 220, sortable: false, render: (r) => clip(r.vendor_name) },
      { key: "bill_date", label: "Date", width: 120, render: (r) => day(r.bill_date) },
      { key: "due_date", label: "Due", width: 120, render: (r) => day(r.due_date) },
      status,
      { key: "total", label: "Amount", width: 140, render: (r) => money(r.total, r.currency_code) },
    ],
    fields: [["Bill", ["bill_number", "status", "bill_date", "due_date", "currency_code", "reference", "notes"]]],
  },
  purchase_orders: {
    title: "Purchase Orders", singular: "Purchase order", numberField: "po_number", lines: true, subtitle: "Orders placed with vendors",
    columns: [
      { key: "po_number", label: "PO", width: 160, required: true, render: (r) => <strong className="cell-clip">{r.po_number}</strong> },
      { key: "vendor_name", label: "Vendor", width: 220, sortable: false, render: (r) => clip(r.vendor_name) },
      { key: "date", label: "Date", width: 120, render: (r) => day(r.date) },
      status,
      { key: "total", label: "Amount", width: 140, render: (r) => money(r.total, r.currency_code) },
    ],
    fields: [["Purchase order", ["po_number", "status", "date", "currency_code", "reference", "notes"]]],
  },
  expenses: {
    title: "Expenses", singular: "Expense", numberField: "description", subtitle: "Spend recorded outside bills",
    columns: [
      { key: "date", label: "Date", width: 120, render: (r) => day(r.date) },
      { key: "description", label: "Expense", width: 280, required: true, sortable: false, render: (r) => clip(r.description) },
      { key: "category", label: "Category", width: 160, render: (r) => clip(r.category) },
      { key: "vendor_name", label: "Paid to", width: 200, sortable: false, render: (r) => clip(r.vendor_name) },
      { key: "amount", label: "Amount", width: 140, render: (r) => money(r.amount, r.currency_code) },
    ],
    fields: [["Expense", ["description", "date", "category", "amount", "currency_code", "vendor_name", "reference", "notes"]]],
  },
  items: {
    title: "Items", singular: "Item", numberField: "name", subtitle: "Products and services used on estimates and invoices",
    columns: [
      { key: "name", label: "Item", width: 260, required: true, render: (r) => <strong className="cell-clip">{r.name}</strong> },
      { key: "description", label: "Description", width: 300, sortable: false, render: (r) => clip(r.description) },
      { key: "rate", label: "Rate", width: 120, render: (r) => money(r.rate) },
      { key: "hsn_sac_code", label: "HSN/SAC", width: 120, sortable: false, render: (r) => clip(r.hsn_sac_code) },
    ],
    fields: [["Item", ["name", "description", "rate", "unit", "hsn_sac_code", "tax_rate", "status"]]],
  },
}

export const apiKind = (kind) => FINANCE_KINDS[kind]?.api || kind

export const FIELD_LABELS = {
  legal_name: "Billed as (legal name)", company_name: "Company name", customer_number: "Customer no.",
  gstin: "GSTIN", pan: "PAN", gst_treatment: "GST treatment", currency_code: "Currency", po_reference: "Client PO",
  tds_amount: "TDS", hsn_sac_code: "HSN/SAC", expiry_date: "Valid until", project_name: "Project / study",
}

export const fieldLabel = (f) => FIELD_LABELS[f] || f.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase())
