"use client"

import { useState, useEffect } from "react"
import { useNavigate } from "react-router-dom"
import { API_BASE_URL } from "../../config"
import "../../styles/SalesPages.css"

function VendorBillingPage() {
  const navigate = useNavigate()
  const [invoices, setInvoices] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [search, setSearch] = useState("")
  const [currentPage, setCurrentPage] = useState(1)
  const [recordsPerPage, setRecordsPerPage] = useState(10)
  const [selectedIds, setSelectedIds] = useState([])
  const [showForm, setShowForm] = useState(false)
  const [editingInvoice, setEditingInvoice] = useState(null)

  const emptyForm = {
    invoice_number: "",
    vendor_id: "",
    vendor_name: "",
    amount: "",
    due_date: "",
    status: "pending",
    description: ""
  }
  const [formData, setFormData] = useState(emptyForm)

  useEffect(() => {
    fetchInvoices()
  }, [])

  const fetchInvoices = async () => {
    try {
      setLoading(true)
      
      // Fetch vendor invoices
      const res = await fetch(`${API_BASE_URL}/vendor-invoices`)
      
      if (res.ok) {
        const data = await res.json()
        setInvoices(data.invoices || data || [])
      } else {
        // Demo data
        setInvoices([
          { _id: "1", invoice_number: "INV-001", vendor_name: "Panel Vendor A", amount: 5000, due_date: "2026-02-15", status: "pending" },
          { _id: "2", invoice_number: "INV-002", vendor_name: "Billing Vendor B", amount: 3500, due_date: "2026-02-10", status: "paid" },
          { _id: "3", invoice_number: "INV-003", vendor_name: "Panel Vendor C", amount: 7200, due_date: "2026-01-30", status: "overdue" },
          { _id: "4", invoice_number: "INV-004", vendor_name: "Panel Vendor A", amount: 2800, due_date: "2026-02-20", status: "draft" },
        ])
      }
    } catch (err) {
      console.error("Error fetching invoices:", err)
      // Demo data
      setInvoices([
        { _id: "1", invoice_number: "INV-001", vendor_name: "Panel Vendor A", amount: 5000, due_date: "2026-02-15", status: "pending" },
        { _id: "2", invoice_number: "INV-002", vendor_name: "Billing Vendor B", amount: 3500, due_date: "2026-02-10", status: "paid" },
        { _id: "3", invoice_number: "INV-003", vendor_name: "Panel Vendor C", amount: 7200, due_date: "2026-01-30", status: "overdue" },
        { _id: "4", invoice_number: "INV-004", vendor_name: "Panel Vendor A", amount: 2800, due_date: "2026-02-20", status: "draft" },
      ])
    } finally {
      setLoading(false)
    }
  }

  // Filter invoices
  const filteredInvoices = invoices.filter(inv => {
    const searchLower = search.toLowerCase()
    return (
      (inv.invoice_number || "").toLowerCase().includes(searchLower) ||
      (inv.vendor_name || "").toLowerCase().includes(searchLower)
    )
  })

  // Pagination
  const totalPages = Math.ceil(filteredInvoices.length / recordsPerPage)
  const startIndex = (currentPage - 1) * recordsPerPage
  const paginatedInvoices = filteredInvoices.slice(startIndex, startIndex + recordsPerPage)

  // Stats
  const stats = {
    total: invoices.length,
    totalAmount: invoices.reduce((sum, inv) => sum + (inv.amount || 0), 0),
    pending: invoices.filter(i => i.status === "pending").length,
    paid: invoices.filter(i => i.status === "paid").length,
    overdue: invoices.filter(i => i.status === "overdue").length
  }

  // Select handlers
  const toggleSelectAll = () => {
    if (selectedIds.length === paginatedInvoices.length) {
      setSelectedIds([])
    } else {
      setSelectedIds(paginatedInvoices.map(i => i._id))
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
      draft: { backgroundColor: "#f3f4f6", color: "#374151" },
      pending: { backgroundColor: "#fef3c7", color: "#92400e" },
      paid: { backgroundColor: "#dcfce7", color: "#166534" },
      overdue: { backgroundColor: "#fee2e2", color: "#991b1b" }
    }
    return styles[status] || { backgroundColor: "#f3f4f6", color: "#374151" }
  }

  const formatCurrency = (amount) => {
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(amount || 0)
  }

  const openCreate = () => {
    setEditingInvoice(null)
    setFormData(emptyForm)
    setShowForm(true)
  }

  const openEdit = (invoice) => {
    setEditingInvoice(invoice)
    setFormData({
      invoice_number: invoice.invoice_number || "",
      vendor_id: invoice.vendor_id || "",
      vendor_name: invoice.vendor_name || "",
      amount: invoice.amount || "",
      due_date: invoice.due_date || "",
      status: invoice.status || "pending",
      description: invoice.description || ""
    })
    setShowForm(true)
  }

  const deleteInvoice = async (id) => {
    if (!window.confirm("Are you sure you want to delete this invoice?")) return
    
    try {
      await fetch(`${API_BASE_URL}/vendor-invoices/${id}`, { method: "DELETE" })
      setInvoices(invoices.filter(i => i._id !== id))
    } catch (err) {
      console.error("Error deleting invoice:", err)
    }
  }

  if (loading) {
    return (
      <div className="sales-page">
        <div className="loading-spinner">Loading billing data...</div>
      </div>
    )
  }

  return (
    <div className="sales-page">
      {/* Page Header */}
      <div className="page-header">
        <div className="header-left">
          <h1>Billing</h1>
          <p className="subtitle">Manage vendor invoices and billing records</p>
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
            + Create Invoice
          </button>
        </div>
      </div>

      {error && <div className="error-alert">{error}</div>}

      {/* Stats Row */}
      <div className="stats-row">
        <div className="stat-card primary">
          <div className="stat-value">{stats.total}</div>
          <div className="stat-label">Total Invoices</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{formatCurrency(stats.totalAmount)}</div>
          <div className="stat-label">💵 Total Amount</div>
        </div>
        <div className="stat-card warning">
          <div className="stat-value">{stats.pending}</div>
          <div className="stat-label">⏳ Pending</div>
        </div>
        <div className="stat-card danger">
          <div className="stat-value">{stats.overdue}</div>
          <div className="stat-label">⚠️ Overdue</div>
        </div>
      </div>

      {/* Filters Bar */}
      <div className="filters-bar">
        <input
          className="search-input"
          type="text"
          placeholder="Search by invoice number, vendor..."
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

      {/* Invoices Table */}
      <div className="table-container">
        <table className="data-table">
          <thead>
            <tr>
              <th className="checkbox-col">
                <input
                  type="checkbox"
                  checked={paginatedInvoices.length > 0 && paginatedInvoices.every(i => selectedIds.includes(i._id))}
                  onChange={toggleSelectAll}
                />
              </th>
              <th>Invoice #</th>
              <th>Vendor</th>
              <th>Amount</th>
              <th>Due Date</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {paginatedInvoices.length === 0 ? (
              <tr>
                <td colSpan="7" style={{ textAlign: "center", padding: "48px" }}>
                  No invoices found
                </td>
              </tr>
            ) : (
              paginatedInvoices.map(invoice => (
                <tr key={invoice._id} className={selectedIds.includes(invoice._id) ? "selected" : ""}>
                  <td className="checkbox-col">
                    <input
                      type="checkbox"
                      checked={selectedIds.includes(invoice._id)}
                      onChange={() => toggleSelect(invoice._id)}
                    />
                  </td>
                  <td className="name-cell">
                    <span className="name-link" onClick={() => openEdit(invoice)}>
                      {invoice.invoice_number || "-"}
                    </span>
                  </td>
                  <td>{invoice.vendor_name || "-"}</td>
                  <td style={{ fontWeight: "600" }}>{formatCurrency(invoice.amount)}</td>
                  <td>{invoice.due_date || "-"}</td>
                  <td>
                    <span className="stage-badge" style={getStatusBadge(invoice.status)}>
                      {invoice.status || "Pending"}
                    </span>
                  </td>
                  <td>
                    <div className="actions-cell">
                      <button className="action-btn" title="View">→</button>
                      <button className="action-btn edit" onClick={() => openEdit(invoice)} title="Edit">✏️</button>
                      <button className="action-btn delete" onClick={() => deleteInvoice(invoice._id)} title="Delete">🗑️</button>
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
            <h2 style={{ marginBottom: "20px" }}>{editingInvoice ? "Edit Invoice" : "Create Invoice"}</h2>
            <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
              <input
                type="text"
                placeholder="Invoice Number"
                value={formData.invoice_number}
                onChange={e => setFormData({ ...formData, invoice_number: e.target.value })}
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
                placeholder="Due Date"
                value={formData.due_date}
                onChange={e => setFormData({ ...formData, due_date: e.target.value })}
                style={{ padding: "10px", borderRadius: "8px", border: "1px solid #e5e7eb" }}
              />
              <select
                value={formData.status}
                onChange={e => setFormData({ ...formData, status: e.target.value })}
                style={{ padding: "10px", borderRadius: "8px", border: "1px solid #e5e7eb" }}
              >
                <option value="draft">Draft</option>
                <option value="pending">Pending</option>
                <option value="paid">Paid</option>
                <option value="overdue">Overdue</option>
              </select>
              <textarea
                placeholder="Description"
                value={formData.description}
                onChange={e => setFormData({ ...formData, description: e.target.value })}
                style={{ padding: "10px", borderRadius: "8px", border: "1px solid #e5e7eb", minHeight: "80px" }}
              />
              <div style={{ display: "flex", gap: "12px", marginTop: "8px" }}>
                <button className="btn btn-outline" onClick={() => setShowForm(false)}>
                  Cancel
                </button>
                <button className="btn btn-primary" onClick={() => setShowForm(false)}>
                  {editingInvoice ? "Update" : "Create"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default VendorBillingPage
