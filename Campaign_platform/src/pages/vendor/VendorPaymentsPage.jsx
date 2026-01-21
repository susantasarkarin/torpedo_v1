"use client"

import { useState, useEffect } from "react"
import { useNavigate } from "react-router-dom"
import { API_BASE_URL } from "../../config"
import "../../styles/SalesPages.css"

function VendorPaymentsPage() {
  const navigate = useNavigate()
  const [payments, setPayments] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [search, setSearch] = useState("")
  const [currentPage, setCurrentPage] = useState(1)
  const [recordsPerPage, setRecordsPerPage] = useState(10)
  const [selectedIds, setSelectedIds] = useState([])
  const [showForm, setShowForm] = useState(false)
  const [editingPayment, setEditingPayment] = useState(null)

  const emptyForm = {
    payment_id: "",
    vendor_id: "",
    vendor_name: "",
    invoice_id: "",
    amount: "",
    payment_date: "",
    payment_method: "bank_transfer",
    status: "pending",
    reference: ""
  }
  const [formData, setFormData] = useState(emptyForm)

  useEffect(() => {
    fetchPayments()
  }, [])

  const fetchPayments = async () => {
    try {
      setLoading(true)
      
      // Fetch vendor payments
      const res = await fetch(`${API_BASE_URL}/vendor-payments`)
      
      if (res.ok) {
        const data = await res.json()
        setPayments(data.payments || data || [])
      } else {
        // Demo data
        setPayments([
          { _id: "1", payment_id: "PAY-001", vendor_name: "Panel Vendor A", amount: 5000, payment_date: "2026-01-15", payment_method: "bank_transfer", status: "completed" },
          { _id: "2", payment_id: "PAY-002", vendor_name: "Billing Vendor B", amount: 3500, payment_date: "2026-01-18", payment_method: "paypal", status: "pending" },
          { _id: "3", payment_id: "PAY-003", vendor_name: "Panel Vendor C", amount: 7200, payment_date: "2026-01-20", payment_method: "wire", status: "processing" },
          { _id: "4", payment_id: "PAY-004", vendor_name: "Panel Vendor A", amount: 2800, payment_date: "2026-01-10", payment_method: "bank_transfer", status: "completed" },
        ])
      }
    } catch (err) {
      console.error("Error fetching payments:", err)
      // Demo data
      setPayments([
        { _id: "1", payment_id: "PAY-001", vendor_name: "Panel Vendor A", amount: 5000, payment_date: "2026-01-15", payment_method: "bank_transfer", status: "completed" },
        { _id: "2", payment_id: "PAY-002", vendor_name: "Billing Vendor B", amount: 3500, payment_date: "2026-01-18", payment_method: "paypal", status: "pending" },
        { _id: "3", payment_id: "PAY-003", vendor_name: "Panel Vendor C", amount: 7200, payment_date: "2026-01-20", payment_method: "wire", status: "processing" },
        { _id: "4", payment_id: "PAY-004", vendor_name: "Panel Vendor A", amount: 2800, payment_date: "2026-01-10", payment_method: "bank_transfer", status: "completed" },
      ])
    } finally {
      setLoading(false)
    }
  }

  // Filter payments
  const filteredPayments = payments.filter(pay => {
    const searchLower = search.toLowerCase()
    return (
      (pay.payment_id || "").toLowerCase().includes(searchLower) ||
      (pay.vendor_name || "").toLowerCase().includes(searchLower) ||
      (pay.reference || "").toLowerCase().includes(searchLower)
    )
  })

  // Pagination
  const totalPages = Math.ceil(filteredPayments.length / recordsPerPage)
  const startIndex = (currentPage - 1) * recordsPerPage
  const paginatedPayments = filteredPayments.slice(startIndex, startIndex + recordsPerPage)

  // Stats
  const stats = {
    total: payments.length,
    totalAmount: payments.reduce((sum, p) => sum + (p.amount || 0), 0),
    completed: payments.filter(p => p.status === "completed").length,
    pending: payments.filter(p => p.status === "pending").length,
    processing: payments.filter(p => p.status === "processing").length
  }

  // Select handlers
  const toggleSelectAll = () => {
    if (selectedIds.length === paginatedPayments.length) {
      setSelectedIds([])
    } else {
      setSelectedIds(paginatedPayments.map(p => p._id))
    }
  }

  const toggleSelect = (id) => {
    if (selectedIds.includes(id)) {
      setSelectedIds(selectedIds.filter(i => i !== id))
    } else {
      setSelectedIds([...selectedIds, id])
    }
  }

  const getStatusBadge = (status) => {
    const styles = {
      pending: { backgroundColor: "#fef3c7", color: "#92400e" },
      processing: { backgroundColor: "#dbeafe", color: "#1e40af" },
      completed: { backgroundColor: "#dcfce7", color: "#166534" },
      failed: { backgroundColor: "#fee2e2", color: "#991b1b" }
    }
    return styles[status] || { backgroundColor: "#f3f4f6", color: "#374151" }
  }

  const getMethodLabel = (method) => {
    const labels = {
      bank_transfer: "🏦 Bank Transfer",
      paypal: "💳 PayPal",
      wire: "📤 Wire Transfer",
      check: "📝 Check",
      crypto: "₿ Crypto"
    }
    return labels[method] || method
  }

  const formatCurrency = (amount) => {
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(amount || 0)
  }

  const openCreate = () => {
    setEditingPayment(null)
    setFormData(emptyForm)
    setShowForm(true)
  }

  const openEdit = (payment) => {
    setEditingPayment(payment)
    setFormData({
      payment_id: payment.payment_id || "",
      vendor_id: payment.vendor_id || "",
      vendor_name: payment.vendor_name || "",
      invoice_id: payment.invoice_id || "",
      amount: payment.amount || "",
      payment_date: payment.payment_date || "",
      payment_method: payment.payment_method || "bank_transfer",
      status: payment.status || "pending",
      reference: payment.reference || ""
    })
    setShowForm(true)
  }

  const deletePayment = async (id) => {
    if (!window.confirm("Are you sure you want to delete this payment?")) return
    
    try {
      await fetch(`${API_BASE_URL}/vendor-payments/${id}`, { method: "DELETE" })
      setPayments(payments.filter(p => p._id !== id))
    } catch (err) {
      console.error("Error deleting payment:", err)
    }
  }

  if (loading) {
    return (
      <div className="sales-page">
        <div className="loading-spinner">Loading payments...</div>
      </div>
    )
  }

  return (
    <div className="sales-page">
      {/* Page Header */}
      <div className="page-header">
        <div className="header-left">
          <h1>Payment</h1>
          <p className="subtitle">Track and manage vendor payments</p>
        </div>
        <div className="header-actions">
          {selectedIds.length > 0 && (
            <button className="btn btn-danger" onClick={() => {/* bulk delete */}}>
              🗑️ Delete ({selectedIds.length})
            </button>
          )}
          <button className="btn btn-outline" onClick={() => {/* export */}}>
            📤 Export
          </button>
          <button className="btn btn-primary" onClick={openCreate}>
            + New Payment
          </button>
        </div>
      </div>

      {error && <div className="error-alert">{error}</div>}

      {/* Stats Row */}
      <div className="stats-row">
        <div className="stat-card primary">
          <div className="stat-value">{stats.total}</div>
          <div className="stat-label">Total Payments</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{formatCurrency(stats.totalAmount)}</div>
          <div className="stat-label">💵 Total Paid</div>
        </div>
        <div className="stat-card success">
          <div className="stat-value">{stats.completed}</div>
          <div className="stat-label">✅ Completed</div>
        </div>
        <div className="stat-card warning">
          <div className="stat-value">{stats.pending}</div>
          <div className="stat-label">⏳ Pending</div>
        </div>
      </div>

      {/* Filters Bar */}
      <div className="filters-bar">
        <input
          className="search-input"
          type="text"
          placeholder="Search by payment ID, vendor, reference..."
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
        <select
          className="records-select"
          value={recordsPerPage}
          onChange={e => {
            setRecordsPerPage(parseInt(e.target.value))
            setCurrentPage(1)
          }}
          style={{ padding: "10px 16px", borderRadius: "8px", border: "1px solid #e5e7eb" }}
        >
          <option value={10}>10 per page</option>
          <option value={20}>20 per page</option>
          <option value={50}>50 per page</option>
          <option value={100}>100 per page</option>
        </select>
      </div>

      {/* Payments Table */}
      <div className="table-container">
        <table className="data-table">
          <thead>
            <tr>
              <th className="checkbox-col">
                <input
                  type="checkbox"
                  checked={paginatedPayments.length > 0 && paginatedPayments.every(p => selectedIds.includes(p._id))}
                  onChange={toggleSelectAll}
                />
              </th>
              <th>Payment ID</th>
              <th>Vendor</th>
              <th>Amount</th>
              <th>Date</th>
              <th>Method</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {paginatedPayments.length === 0 ? (
              <tr>
                <td colSpan="8" style={{ textAlign: "center", padding: "48px" }}>
                  No payments found
                </td>
              </tr>
            ) : (
              paginatedPayments.map(payment => (
                <tr key={payment._id} className={selectedIds.includes(payment._id) ? "selected" : ""}>
                  <td className="checkbox-col">
                    <input
                      type="checkbox"
                      checked={selectedIds.includes(payment._id)}
                      onChange={() => toggleSelect(payment._id)}
                    />
                  </td>
                  <td className="name-cell">
                    <span className="name-link" onClick={() => openEdit(payment)}>
                      {payment.payment_id || "-"}
                    </span>
                  </td>
                  <td>{payment.vendor_name || "-"}</td>
                  <td style={{ fontWeight: "600" }}>{formatCurrency(payment.amount)}</td>
                  <td>{payment.payment_date || "-"}</td>
                  <td>{getMethodLabel(payment.payment_method)}</td>
                  <td>
                    <span className="stage-badge" style={getStatusBadge(payment.status)}>
                      {payment.status || "Pending"}
                    </span>
                  </td>
                  <td>
                    <div className="actions-cell">
                      <button className="action-btn" title="View">→</button>
                      <button className="action-btn edit" onClick={() => openEdit(payment)} title="Edit">✏️</button>
                      <button className="action-btn delete" onClick={() => deletePayment(payment._id)} title="Delete">🗑️</button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="pagination-bar">
          <button
            className="btn btn-outline"
            onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
            disabled={currentPage === 1}
          >
            Previous
          </button>
          <span className="page-info">
            Page {currentPage} of {totalPages}
          </span>
          <button
            className="btn btn-outline"
            onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
            disabled={currentPage === totalPages}
          >
            Next
          </button>
        </div>
      )}

      {/* Add/Edit Modal */}
      {showForm && (
        <div className="modal-overlay" onClick={() => setShowForm(false)}>
          <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: "500px", padding: "24px" }}>
            <h2 style={{ marginBottom: "20px" }}>{editingPayment ? "Edit Payment" : "New Payment"}</h2>
            <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
              <input
                type="text"
                placeholder="Payment ID"
                value={formData.payment_id}
                onChange={e => setFormData({ ...formData, payment_id: e.target.value })}
                style={{ padding: "10px", borderRadius: "8px", border: "1px solid #e5e7eb" }}
              />
              <input
                type="text"
                placeholder="Vendor Name"
                value={formData.vendor_name}
                onChange={e => setFormData({ ...formData, vendor_name: e.target.value })}
                style={{ padding: "10px", borderRadius: "8px", border: "1px solid #e5e7eb" }}
              />
              <input
                type="number"
                placeholder="Amount"
                value={formData.amount}
                onChange={e => setFormData({ ...formData, amount: e.target.value })}
                style={{ padding: "10px", borderRadius: "8px", border: "1px solid #e5e7eb" }}
              />
              <input
                type="date"
                placeholder="Payment Date"
                value={formData.payment_date}
                onChange={e => setFormData({ ...formData, payment_date: e.target.value })}
                style={{ padding: "10px", borderRadius: "8px", border: "1px solid #e5e7eb" }}
              />
              <select
                value={formData.payment_method}
                onChange={e => setFormData({ ...formData, payment_method: e.target.value })}
                style={{ padding: "10px", borderRadius: "8px", border: "1px solid #e5e7eb" }}
              >
                <option value="bank_transfer">Bank Transfer</option>
                <option value="paypal">PayPal</option>
                <option value="wire">Wire Transfer</option>
                <option value="check">Check</option>
                <option value="crypto">Crypto</option>
              </select>
              <select
                value={formData.status}
                onChange={e => setFormData({ ...formData, status: e.target.value })}
                style={{ padding: "10px", borderRadius: "8px", border: "1px solid #e5e7eb" }}
              >
                <option value="pending">Pending</option>
                <option value="processing">Processing</option>
                <option value="completed">Completed</option>
                <option value="failed">Failed</option>
              </select>
              <input
                type="text"
                placeholder="Reference Number"
                value={formData.reference}
                onChange={e => setFormData({ ...formData, reference: e.target.value })}
                style={{ padding: "10px", borderRadius: "8px", border: "1px solid #e5e7eb" }}
              />
              <div style={{ display: "flex", gap: "12px", marginTop: "8px" }}>
                <button className="btn btn-outline" onClick={() => setShowForm(false)}>
                  Cancel
                </button>
                <button className="btn btn-primary" onClick={() => setShowForm(false)}>
                  {editingPayment ? "Update" : "Create"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default VendorPaymentsPage
