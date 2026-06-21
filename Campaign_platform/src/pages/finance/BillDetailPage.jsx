"use client"

import { useState, useEffect } from "react"
import { useParams, useNavigate } from "react-router-dom"
import { buildApiUrl } from "../../config"
import { formatCurrency } from "../../utils/currency"
import { ArrowLeft, FileText, Loader2 } from "lucide-react"

const statusColors = {
  pending: { background: "#f3f4f6", color: "#374151" },
  paid:    { background: "#dcfce7", color: "#15803d" },
  overdue: { background: "#fee2e2", color: "#b91c1c" },
  partial: { background: "#fef9c3", color: "#854d0e" },
  open:    { background: "#dbeafe", color: "#1d4ed8" },
}

function badge(status) {
  const s = (status || "pending").toLowerCase()
  const c = statusColors[s] || statusColors.pending
  return (
    <span style={{ ...c, padding: "0.25rem 0.75rem", borderRadius: "1rem", fontSize: "0.8rem", fontWeight: 600 }}>
      {s.charAt(0).toUpperCase() + s.slice(1)}
    </span>
  )
}

function fmt(dateStr) {
  if (!dateStr) return "—"
  try { return new Date(dateStr).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }) }
  catch { return dateStr }
}

export default function BillDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [bill, setBill] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")

  useEffect(() => {
    const sessionId = localStorage.getItem("session_id")
    fetch(buildApiUrl(`/finance/bills/${id}`), { headers: { Authorization: sessionId || "" } })
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(setBill)
      .catch(e => setError(e === 404 ? "Bill not found." : "Failed to load bill."))
      .finally(() => setLoading(false))
  }, [id])

  if (loading) return (
    <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: "50vh" }}>
      <Loader2 style={{ width: 32, height: 32, animation: "spin 1s linear infinite", color: "#0d6efd" }} />
    </div>
  )

  if (error) return (
    <div style={{ padding: "2rem", color: "#b91c1c" }}>
      <button onClick={() => navigate(-1)} style={styles.backBtn}><ArrowLeft size={16} /> Back</button>
      <p style={{ marginTop: "1rem" }}>{error}</p>
    </div>
  )

  const cur = bill.currency_code || bill.currency || "INR"
  const items = bill.items || []

  return (
    <div style={styles.page}>
      <div style={styles.topBar}>
        <button onClick={() => navigate("/admin/finance/bills")} style={styles.backBtn}>
          <ArrowLeft size={16} style={{ marginRight: 6 }} />Back to Bills
        </button>
      </div>

      <div style={styles.card}>
        {/* Title row */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "1.5rem", flexWrap: "wrap", gap: "0.5rem" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
            <FileText size={24} color="#f59e0b" />
            <div>
              <h2 style={{ margin: 0, fontSize: "1.4rem", fontWeight: 700, color: "#111" }}>
                {bill.bill_number || "—"}
              </h2>
              <p style={{ margin: 0, color: "#6b7280", fontSize: "0.85rem" }}>Bill / Accounts Payable</p>
            </div>
          </div>
          {badge(bill.status)}
        </div>

        {/* Meta grid */}
        <div style={styles.metaGrid}>
          <div style={styles.metaBlock}>
            <span style={styles.metaLabel}>Vendor</span>
            <span style={styles.metaValue}>{bill.vendor_name || bill.vendor_id || "—"}</span>
          </div>
          <div style={styles.metaBlock}>
            <span style={styles.metaLabel}>Bill Date</span>
            <span style={styles.metaValue}>{fmt(bill.bill_date)}</span>
          </div>
          <div style={styles.metaBlock}>
            <span style={styles.metaLabel}>Due Date</span>
            <span style={styles.metaValue}>{fmt(bill.due_date)}</span>
          </div>
          <div style={styles.metaBlock}>
            <span style={styles.metaLabel}>Currency</span>
            <span style={styles.metaValue}>{cur}</span>
          </div>
          {bill.po_reference && (
            <div style={styles.metaBlock}>
              <span style={styles.metaLabel}>PO Reference</span>
              <span style={styles.metaValue}>{bill.po_reference}</span>
            </div>
          )}
          {bill.branch && (
            <div style={styles.metaBlock}>
              <span style={styles.metaLabel}>Branch</span>
              <span style={styles.metaValue}>{bill.branch}</span>
            </div>
          )}
          {bill.gstin && (
            <div style={styles.metaBlock}>
              <span style={styles.metaLabel}>GSTIN</span>
              <span style={styles.metaValue}>{bill.gstin}</span>
            </div>
          )}
          {bill.gst_treatment && (
            <div style={styles.metaBlock}>
              <span style={styles.metaLabel}>GST Treatment</span>
              <span style={styles.metaValue}>{bill.gst_treatment}</span>
            </div>
          )}
        </div>

        {/* Line items */}
        {items.length > 0 && (
          <div style={{ marginTop: "1.5rem" }}>
            <h3 style={styles.sectionTitle}>Line Items</h3>
            <div style={{ overflowX: "auto" }}>
              <table style={styles.table}>
                <thead>
                  <tr style={styles.thead}>
                    <th style={styles.th}>Item</th>
                    <th style={styles.th}>Account</th>
                    <th style={{ ...styles.th, textAlign: "right" }}>Qty</th>
                    <th style={{ ...styles.th, textAlign: "right" }}>Rate</th>
                    <th style={{ ...styles.th, textAlign: "right" }}>Tax %</th>
                    <th style={{ ...styles.th, textAlign: "right" }}>Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item, i) => (
                    <tr key={i} style={{ borderBottom: "1px solid #f3f4f6" }}>
                      <td style={styles.td}>{item.name || "—"}</td>
                      <td style={{ ...styles.td, color: "#6b7280", fontSize: "0.85rem" }}>{item.account || item.description || "—"}</td>
                      <td style={{ ...styles.td, textAlign: "right" }}>{item.quantity ?? 1}</td>
                      <td style={{ ...styles.td, textAlign: "right" }}>{formatCurrency(item.rate, cur)}</td>
                      <td style={{ ...styles.td, textAlign: "right" }}>{item.tax_percent ?? 0}%</td>
                      <td style={{ ...styles.td, textAlign: "right", fontWeight: 600 }}>{formatCurrency(item.amount, cur)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Totals */}
        <div style={styles.totalsBox}>
          <div style={styles.totalRow}>
            <span>Subtotal</span>
            <span>{formatCurrency(bill.subtotal, cur)}</span>
          </div>
          {(bill.tax_total > 0 || bill.tax_amount > 0) && (
            <div style={styles.totalRow}>
              <span>Tax</span>
              <span>{formatCurrency(bill.tax_total ?? bill.tax_amount, cur)}</span>
            </div>
          )}
          <div style={{ ...styles.totalRow, fontWeight: 700, fontSize: "1.05rem", borderTop: "2px solid #e5e7eb", paddingTop: "0.5rem", marginTop: "0.25rem" }}>
            <span>Total</span>
            <span>{formatCurrency(bill.total_amount ?? bill.total, cur)}</span>
          </div>
          {bill.amount_paid > 0 && (
            <div style={{ ...styles.totalRow, color: "#15803d" }}>
              <span>Amount Paid</span>
              <span>{formatCurrency(bill.amount_paid, cur)}</span>
            </div>
          )}
          <div style={{ ...styles.totalRow, fontWeight: 700, color: bill.balance_due > 0 ? "#b91c1c" : "#15803d" }}>
            <span>Balance Due</span>
            <span>{formatCurrency(bill.balance_due, cur)}</span>
          </div>
        </div>

        {/* Notes */}
        {bill.notes && (
          <div style={{ marginTop: "1.5rem" }}>
            <h3 style={styles.sectionTitle}>Notes</h3>
            <p style={{ color: "#374151", lineHeight: 1.6, whiteSpace: "pre-wrap" }}>{bill.notes}</p>
          </div>
        )}
      </div>
    </div>
  )
}

const styles = {
  page: { padding: "1.5rem", maxWidth: 900, margin: "0 auto" },
  topBar: { marginBottom: "1rem" },
  backBtn: {
    display: "inline-flex", alignItems: "center", gap: 4,
    background: "none", border: "1px solid #d1d5db", borderRadius: 6,
    padding: "0.4rem 0.9rem", cursor: "pointer", fontSize: "0.875rem", color: "#374151",
  },
  card: { background: "#fff", borderRadius: 10, padding: "2rem", boxShadow: "0  1px 4px rgba(0,0,0,0.08)" },
  metaGrid: { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: "1rem", background: "#f9fafb", borderRadius: 8, padding: "1rem" },
  metaBlock: { display: "flex", flexDirection: "column", gap: 2 },
  metaLabel: { fontSize: "0.75rem", color: "#9ca3af", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" },
  metaValue: { fontSize: "0.95rem", color: "#111827", fontWeight: 500 },
  sectionTitle: { fontSize: "0.9rem", fontWeight: 700, color: "#374151", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: "0.75rem" },
  table: { width: "100%", borderCollapse: "collapse", fontSize: "0.875rem" },
  thead: { background: "#f9fafb" },
  th: { padding: "0.6rem 0.75rem", textAlign: "left", fontWeight: 600, color: "#374151", borderBottom: "2px solid #e5e7eb", whiteSpace: "nowrap" },
  td: { padding: "0.6rem 0.75rem", color: "#111827" },
  totalsBox: { marginTop: "1.5rem", marginLeft: "auto", maxWidth: 340, display: "flex", flexDirection: "column", gap: "0.4rem" },
  totalRow: { display: "flex", justifyContent: "space-between", fontSize: "0.9rem", color: "#374151", padding: "0.15rem 0" },
}
