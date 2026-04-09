      <Pagination
        currentPage={currentPage}
        totalPages={totalPages}
        totalRecords={totalExpenses}
        pageSize={recordsPerPage}
        onPageChange={handlePageChange}
        onPageSizeChange={handleRecordsPerPageChange}
        loading={loading}
      />
"use client"

import { useState, useEffect, useRef } from "react"
import { API_BASE_URL } from "../../config"
import { DEFAULT_CURRENCY } from "../../utils/currency"
import { Receipt, Search, Paperclip, Trash2, Loader2, Sparkles, Upload, Download } from "lucide-react"
import { buildApiUrl } from "../../config"

function ExpensesPage() {
  const [expenses, setExpenses] = useState([])
  const [loading, setLoading] = useState(true)
  const [searchTerm, setSearchTerm] = useState("")
  const [categoryFilter, setCategoryFilter] = useState("all")
  const [statusFilter, setStatusFilter] = useState("all")
  const [showModal, setShowModal] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [importing, setImporting] = useState(false)
  const fileInputRef = useRef(null)
  const [formData, setFormData] = useState({
    description: "",
    amount: 0,
    currency_code: DEFAULT_CURRENCY,
    category: "",
    vendor_id: "",
    expense_date: new Date().toISOString().split("T")[0],
    payment_method: "bank_transfer",
    reference_number: "",
    notes: "",
    is_billable: false,
    requires_approval: false,
  })

  const categories = [
    "Office Supplies",
    "Travel",
    "Meals & Entertainment",
    "Utilities",
    "Rent",
    "Software & Subscriptions",
    "Marketing",
    "Professional Services",
    "Equipment",
    "Maintenance",
    "Insurance",
    "Training",
    "Miscellaneous",
  ]

  useEffect(() => {
    fetchExpenses()
  }, [])

  const fetchExpenses = async () => {
    try {
      const response = await fetch(buildApiUrl(`/finance/expenses/`))
      if (response.ok) {
        const data = await response.json()
        setExpenses(data)
      }
    } catch (error) {
      console.error("Error fetching expenses:", error)
    } finally {
      setLoading(false)
    }
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    try {
      const response = await fetch(buildApiUrl(`/finance/expenses/`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(formData),
      })

      if (response.ok) {
        fetchExpenses()
        handleCloseModal()
      }
    } catch (error) {
      console.error("Error creating expense:", error)
    }
  }

  const handleAutoCategorize = async () => {
    if (!formData.description) return

    try {
      const response = await fetch(buildApiUrl(`/finance/expenses/auto-categorize`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          description: formData.description,
          amount: formData.amount,
        }),
      })

      if (response.ok) {
        const data = await response.json()
        if (data.category) {
          setFormData({ ...formData, category: data.category })
        }
      }
    } catch (error) {
      console.error("Error auto-categorizing:", error)
    }
  }

  const handleDelete = async (id) => {
    if (!window.confirm("Are you sure you want to delete this expense?")) return

    try {
      const response = await fetch(buildApiUrl(`/finance/expenses/${id}`), {
        method: "DELETE",
      })
      if (response.ok) {
        fetchExpenses()
      }
    } catch (error) {
      console.error("Error deleting expense:", error)
    }
  }

  const handleCloseModal = () => {
    setShowModal(false)
    setFormData({
      description: "",
      amount: 0,
      currency_code: DEFAULT_CURRENCY,
      category: "",
      vendor_id: "",
      expense_date: new Date().toISOString().split("T")[0],
      payment_method: "bank_transfer",
      reference_number: "",
      notes: "",
      is_billable: false,
      requires_approval: false,
    })
  }

  const getStatusVariant = (status) => {
    switch (status) {
      case "approved":
        return styles.statusApproved
      case "pending":
        return styles.statusPending
      case "rejected":
        return styles.statusRejected
      default:
        return styles.statusDefault
    }
  }

  const formatCurrency = (amount) => {
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency: "INR",
      maximumFractionDigits: 0,
    }).format(amount || 0)
  }

  const filteredExpenses = expenses.filter((exp) => {
    const matchesSearch = exp.description?.toLowerCase().includes(searchTerm.toLowerCase())
    const matchesCategory = categoryFilter === "all" || exp.category === categoryFilter
    const matchesStatus = statusFilter === "all" || exp.approval_status === statusFilter
    return matchesSearch && matchesCategory && matchesStatus
  })

  const totalExpenses = filteredExpenses.reduce((sum, e) => sum + (e.amount || 0), 0)

  // Export expenses to CSV
  const handleExportCSV = async () => {
    setExporting(true)
    try {
      const response = await fetch(buildApiUrl(`/finance/expenses/export/csv`))
      if (response.ok) {
        const blob = await response.blob()
        const url = window.URL.createObjectURL(blob)
        const a = document.createElement("a")
        a.href = url
        a.download = `expenses_export_${new Date().toISOString().split("T")[0]}.csv`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        window.URL.revokeObjectURL(url)
      }
    } catch (error) {
      console.error("Error exporting expenses:", error)
      alert("Failed to export expenses")
    } finally {
      setExporting(false)
    }
  }

  // Import expenses from CSV
  const handleImportCSV = async (event) => {
    const file = event.target.files?.[0]
    if (!file) return

    setImporting(true)
    const formDataUpload = new FormData()
    formDataUpload.append("file", file)

    try {
      const response = await fetch(buildApiUrl(`/finance/expenses/import/csv`), {
        method: "POST",
        body: formDataUpload,
      })

      if (response.ok) {
        const result = await response.json()
        alert(`Successfully imported ${result.imported} expenses`)
        fetchExpenses()
      } else {
        const error = await response.json()
        alert(`Import failed: ${error.detail}`)
      }
    } catch (error) {
      console.error("Error importing expenses:", error)
      alert("Failed to import expenses")
    } finally {
      setImporting(false)
      if (fileInputRef.current) {
        fileInputRef.current.value = ""
      }
    }
  }

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <div>
          <h2 style={styles.title}>Expenses</h2>
          <p style={styles.subtitle}>Track and manage business expenses</p>
        </div>
        <div style={{ display: "flex", gap: "0.75rem" }}>
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleImportCSV}
            accept=".csv"
            style={{ display: "none" }}
          />
          <button 
            style={styles.btnSecondary} 
            onClick={() => fileInputRef.current?.click()}
            disabled={importing}
          >
            <Upload style={{ width: "16px", height: "16px" }} />
            {importing ? "Importing..." : "Import CSV"}
          </button>
          <button 
            style={styles.btnSecondary} 
            onClick={handleExportCSV}
            disabled={exporting}
          >
            <Download style={{ width: "16px", height: "16px" }} />
            {exporting ? "Exporting..." : "Export CSV"}
          </button>
          <button style={styles.btnPrimary} onClick={() => setShowModal(true)}>
            + Record Expense
          </button>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem", marginBottom: "1.5rem" }}>
        <div style={styles.summaryCard}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
            <div>
              <p style={{ fontSize: "0.875rem", color: "#6b7280", margin: 0 }}>Total Expenses</p>
              <p style={{ fontSize: "1.875rem", fontWeight: "700", color: "#1a1a1a", margin: "0.5rem 0 0 0" }}>
                {formatCurrency(totalExpenses)}
              </p>
            </div>
            <div
              style={{
                width: "48px",
                height: "48px",
                backgroundColor: "#fee2e2",
                borderRadius: "0.5rem",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <Receipt style={{ width: "24px", height: "24px", color: "#dc2626" }} />
            </div>
          </div>
        </div>
        <div style={styles.summaryCard}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
            <div>
              <p style={{ fontSize: "0.875rem", color: "#6b7280", margin: 0 }}>Count</p>
              <p style={{ fontSize: "1.875rem", fontWeight: "700", color: "#1a1a1a", margin: "0.5rem 0 0 0" }}>
                {filteredExpenses.length}
              </p>
            </div>
            <div
              style={{
                width: "48px",
                height: "48px",
                backgroundColor: "#dbeafe",
                borderRadius: "0.5rem",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <Receipt style={{ width: "24px", height: "24px", color: "#2563eb" }} />
            </div>
          </div>
        </div>
      </div>

      <div style={styles.searchSection}>
        <div style={{ flex: 1, maxWidth: "400px", position: "relative" }}>
          <Search
            style={{
              position: "absolute",
              left: "12px",
              top: "50%",
              transform: "translateY(-50%)",
              width: "16px",
              height: "16px",
              color: "#9ca3af",
            }}
          />
          <input
            style={styles.searchInput}
            type="text"
            placeholder="Search expenses..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        </div>
        <select
          style={styles.recordsPerPageSelect}
          value={categoryFilter}
          onChange={(e) => setCategoryFilter(e.target.value)}
        >
          <option value="all">All Categories</option>
          {categories.map((cat) => (
            <option key={cat} value={cat}>
              {cat}
            </option>
          ))}
        </select>
        <select
          style={styles.recordsPerPageSelect}
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        >
          <option value="all">All Status</option>
          <option value="pending">Pending</option>
          <option value="approved">Approved</option>
          <option value="rejected">Rejected</option>
        </select>
      </div>

      {loading ? (
        <div style={styles.tableContainer}>
          <div style={{ textAlign: "center", padding: "3rem" }}>
            <Loader2
              style={{
                width: "32px",
                height: "32px",
                animation: "spin 1s linear infinite",
                margin: "0 auto 1rem",
                color: "#0d6efd",
              }}
            />
            <p style={{ color: "#6b7280" }}>Loading expenses...</p>
          </div>
        </div>
      ) : (
        <div style={styles.tableContainer}>
          <table style={styles.table}>
            <thead style={styles.thead}>
              <tr>
                <th style={styles.th}>Date</th>
                <th style={styles.th}>Description</th>
                <th style={styles.th}>Category</th>
                <th style={styles.th}>Amount</th>
                <th style={styles.th}>Payment Method</th>
                <th style={styles.th}>Status</th>
                <th style={styles.th}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredExpenses.map((expense) => (
                <tr key={expense._id} style={styles.tr}>
                  <td style={styles.td}>{new Date(expense.expense_date).toLocaleDateString("en-IN")}</td>
                  <td style={{ ...styles.td, fontWeight: "500" }}>{expense.description}</td>
                  <td style={styles.td}>
                    <span style={{ ...styles.statusBadge, backgroundColor: "#e9d5ff", color: "#6b21a8" }}>
                      {expense.category || "Uncategorized"}
                    </span>
                  </td>
                  <td style={{ ...styles.td, fontWeight: "600" }}>{formatCurrency(expense.amount)}</td>
                  <td style={{ ...styles.td, textTransform: "capitalize" }}>
                    {expense.payment_method?.replace("_", " ") || "-"}
                  </td>
                  <td style={styles.td}>
                    <span style={{ ...styles.statusBadge, ...getStatusVariant(expense.approval_status) }}>
                      {expense.approval_status || "N/A"}
                    </span>
                  </td>
                  <td style={styles.td}>
                    <div style={styles.actionButtons}>
                      <button style={styles.btnEdit}>
                        <Paperclip style={{ width: "16px", height: "16px" }} />
                      </button>
                      <button style={styles.btnDelete} onClick={() => handleDelete(expense._id)}>
                        <Trash2 style={{ width: "16px", height: "16px" }} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {filteredExpenses.length === 0 && (
                <tr>
                  <td colSpan={7} style={styles.emptyState}>
                    <Receipt style={{ width: "48px", height: "48px", margin: "0 auto 1rem", opacity: 0.5 }} />
                    <p>No expenses found. Click "Record Expense" to add one.</p>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {showModal && (
        <div style={styles.modal} onClick={handleCloseModal}>
          <div style={styles.modalContent} onClick={(e) => e.stopPropagation()}>
            <div style={styles.modalHeader}>
              <h3 style={styles.modalTitle}>Record Expense</h3>
              <button style={styles.closeBtn} onClick={handleCloseModal}>
                ×
              </button>
            </div>

            <form onSubmit={handleSubmit} style={{ ...styles.modalBody, overflow: "auto", flex: 1 }}>
              <div style={{ marginBottom: "1.5rem" }}>
                <label style={styles.label}>Description *</label>
                <div style={{ display: "flex", gap: "0.5rem" }}>
                  <input
                    style={{ ...styles.input, flex: 1 }}
                    type="text"
                    value={formData.description}
                    onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                    required
                    placeholder="Enter expense description"
                  />
                  <button
                    style={{ ...styles.btnPrimary, padding: "0.75rem 1rem", fontSize: "0.85rem" }}
                    type="button"
                    onClick={handleAutoCategorize}
                  >
                    <Sparkles style={{ width: "16px", height: "16px", marginRight: "0.25rem", display: "inline" }} />{" "}
                    Auto
                  </button>
                </div>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem", marginBottom: "1rem" }}>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Amount (₹) *</label>
                  <input
                    style={styles.input}
                    type="number"
                    value={formData.amount}
                    onChange={(e) => setFormData({ ...formData, amount: Number.parseFloat(e.target.value) })}
                    required
                    min={0}
                    step={0.01}
                  />
                </div>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Category *</label>
                  <select
                    style={styles.select}
                    value={formData.category}
                    onChange={(e) => setFormData({ ...formData, category: e.target.value })}
                    required
                  >
                    <option value="">Select Category</option>
                    {categories.map((cat) => (
                      <option key={cat} value={cat}>
                        {cat}
                      </option>
                    ))}
                  </select>
                </div>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Date</label>
                  <input
                    style={styles.input}
                    type="date"
                    value={formData.expense_date}
                    onChange={(e) => setFormData({ ...formData, expense_date: e.target.value })}
                  />
                </div>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Payment Method</label>
                  <select
                    style={styles.select}
                    value={formData.payment_method}
                    onChange={(e) => setFormData({ ...formData, payment_method: e.target.value })}
                  >
                    <option value="bank_transfer">Bank Transfer</option>
                    <option value="cash">Cash</option>
                    <option value="credit_card">Credit Card</option>
                    <option value="debit_card">Debit Card</option>
                    <option value="upi">UPI</option>
                    <option value="cheque">Cheque</option>
                  </select>
                </div>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Reference Number</label>
                  <input
                    style={styles.input}
                    type="text"
                    value={formData.reference_number}
                    onChange={(e) => setFormData({ ...formData, reference_number: e.target.value })}
                    placeholder="Transaction ID"
                  />
                </div>
              </div>

              <div style={{ marginBottom: "1.5rem" }}>
                <label style={styles.label}>Notes</label>
                <textarea
                  style={{ ...styles.input, minHeight: "60px", resize: "vertical" }}
                  value={formData.notes}
                  onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
                  placeholder="Additional notes..."
                />
              </div>

              <div style={{ display: "flex", gap: "1.5rem" }}>
                <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", cursor: "pointer" }}>
                  <input
                    type="checkbox"
                    checked={formData.is_billable}
                    onChange={(e) => setFormData({ ...formData, is_billable: e.target.checked })}
                    style={{ width: "16px", height: "16px" }}
                  />
                  <span style={{ fontSize: "0.875rem", color: "#374151" }}>Billable to Client</span>
                </label>
                <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", cursor: "pointer" }}>
                  <input
                    type="checkbox"
                    checked={formData.requires_approval}
                    onChange={(e) => setFormData({ ...formData, requires_approval: e.target.checked })}
                    style={{ width: "16px", height: "16px" }}
                  />
                  <span style={{ fontSize: "0.875rem", color: "#374151" }}>Requires Approval</span>
                </label>
              </div>
            </form>

            <div style={styles.modalFooter}>
              <button style={styles.btnCancel} type="button" onClick={handleCloseModal}>
                Cancel
              </button>
              <button style={styles.btnSave} type="submit" onClick={handleSubmit}>
                Record Expense
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

const styles = {
  container: {
    padding: "1.5rem",
    backgroundColor: "#f9fafb",
    minHeight: "100vh",
  },
  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "flex-start",
    marginBottom: "2rem",
  },
  title: {
    fontSize: "2rem",
    fontWeight: "700",
    margin: "0 0 0.5rem 0",
    color: "#1a1a1a",
  },
  subtitle: {
    color: "#6b7280",
    margin: "0",
    fontSize: "0.95rem",
  },
  btnPrimary: {
    padding: "0.75rem 1.5rem",
    backgroundColor: "#0d6efd",
    color: "white",
    border: "none",
    borderRadius: "0.5rem",
    fontSize: "0.95rem",
    fontWeight: "500",
    cursor: "pointer",
    transition: "all 0.2s",
  },
  btnSecondary: {
    padding: "0.75rem 1.5rem",
    backgroundColor: "#6c757d",
    color: "white",
    border: "none",
    borderRadius: "0.5rem",
    fontSize: "0.95rem",
    fontWeight: "500",
    cursor: "pointer",
    display: "flex",
    alignItems: "center",
    gap: "0.5rem",
  },
  summaryCard: {
    backgroundColor: "white",
    borderRadius: "0.75rem",
    padding: "1rem",
    boxShadow: "0 1px 3px rgba(0,0,0,0.1)",
  },
  searchSection: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: "1.5rem",
    padding: "1.25rem",
    backgroundColor: "white",
    borderRadius: "0.75rem",
    boxShadow: "0 1px 3px rgba(0,0,0,0.1)",
    gap: "1rem",
    flexWrap: "wrap",
  },
  searchInput: {
    width: "100%",
    paddingLeft: "2.5rem",
    paddingRight: "1rem",
    paddingTop: "0.75rem",
    paddingBottom: "0.75rem",
    border: "1px solid #d1d5db",
    borderRadius: "0.5rem",
    fontSize: "0.95rem",
  },
  recordsPerPageSelect: {
    padding: "0.75rem 1rem",
    border: "1px solid #d1d5db",
    borderRadius: "0.5rem",
    fontSize: "0.95rem",
    backgroundColor: "white",
    cursor: "pointer",
  },
  tableContainer: {
    backgroundColor: "white",
    borderRadius: "0.75rem",
    overflow: "hidden",
    boxShadow: "0 1px 3px rgba(0,0,0,0.1)",
  },
  table: {
    width: "100%",
    borderCollapse: "collapse",
  },
  thead: {
    backgroundColor: "#f9fafb",
    borderBottom: "2px solid #e5e7eb",
  },
  th: {
    padding: "1rem",
    textAlign: "left",
    fontSize: "0.75rem",
    fontWeight: "600",
    textTransform: "uppercase",
    color: "#6b7280",
    letterSpacing: "0.05em",
  },
  tr: {
    borderBottom: "1px solid #e5e7eb",
    transition: "background-color 0.15s",
  },
  td: {
    padding: "1rem",
    fontSize: "0.9rem",
    color: "#374151",
  },
  statusBadge: {
    display: "inline-block",
    padding: "0.375rem 0.75rem",
    borderRadius: "0.375rem",
    fontSize: "0.8rem",
    fontWeight: "600",
    textTransform: "uppercase",
  },
  statusApproved: {
    backgroundColor: "#d1fae5",
    color: "#065f46",
  },
  statusPending: {
    backgroundColor: "#fef3c7",
    color: "#92400e",
  },
  statusRejected: {
    backgroundColor: "#fee2e2",
    color: "#991b1b",
  },
  statusDefault: {
    backgroundColor: "#e5e7eb",
    color: "#6b7280",
  },
  actionButtons: {
    display: "flex",
    gap: "0.5rem",
  },
  btnEdit: {
    padding: "0.5rem 0.75rem",
    backgroundColor: "#6b7280",
    color: "white",
    border: "none",
    borderRadius: "0.375rem",
    cursor: "pointer",
    fontSize: "1rem",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
  },
  btnDelete: {
    padding: "0.5rem 0.75rem",
    backgroundColor: "#ef4444",
    color: "white",
    border: "none",
    borderRadius: "0.375rem",
    cursor: "pointer",
    fontSize: "1rem",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
  },
  emptyState: {
    textAlign: "center",
    padding: "3rem",
    color: "#9ca3af",
  },
  modal: {
    position: "fixed",
    top: "0",
    left: "0",
    right: "0",
    bottom: "0",
    backgroundColor: "rgba(0, 0, 0, 0.5)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    zIndex: "1000",
    padding: "1rem",
  },
  modalContent: {
    backgroundColor: "white",
    borderRadius: "0.75rem",
    width: "100%",
    maxWidth: "700px",
    maxHeight: "90vh",
    overflow: "hidden",
    display: "flex",
    flexDirection: "column",
    boxShadow: "0 25px 50px -12px rgba(0, 0, 0, 0.25)",
  },
  modalHeader: {
    padding: "1.5rem",
    borderBottom: "1px solid #e5e7eb",
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
  },
  modalTitle: {
    fontSize: "1.5rem",
    fontWeight: "600",
    color: "#1a1a1a",
    margin: "0",
  },
  closeBtn: {
    background: "none",
    border: "none",
    fontSize: "2rem",
    color: "#9ca3af",
    cursor: "pointer",
    padding: "0",
    width: "2rem",
    height: "2rem",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
  },
  modalBody: {
    padding: "1.5rem",
  },
  formGroup: {
    display: "flex",
    flexDirection: "column",
  },
  label: {
    marginBottom: "0.5rem",
    fontSize: "0.875rem",
    fontWeight: "500",
    color: "#374151",
  },
  input: {
    padding: "0.75rem",
    border: "1px solid #d1d5db",
    borderRadius: "0.5rem",
    fontSize: "0.95rem",
    backgroundColor: "white",
  },
  select: {
    padding: "0.75rem",
    border: "1px solid #d1d5db",
    borderRadius: "0.5rem",
    fontSize: "0.95rem",
    cursor: "pointer",
    backgroundColor: "white",
  },
  modalFooter: {
    padding: "1rem 1.5rem",
    borderTop: "1px solid #e5e7eb",
    display: "flex",
    justifyContent: "flex-end",
    gap: "0.75rem",
  },
  btnCancel: {
    padding: "0.75rem 1.5rem",
    backgroundColor: "#6b7280",
    color: "white",
    border: "none",
    borderRadius: "0.5rem",
    fontSize: "0.95rem",
    fontWeight: "500",
    cursor: "pointer",
  },
  btnSave: {
    padding: "0.75rem 1.5rem",
    backgroundColor: "#0d6efd",
    color: "white",
    border: "none",
    borderRadius: "0.5rem",
    fontSize: "0.95rem",
    fontWeight: "500",
    cursor: "pointer",
  },
}

export default ExpensesPage
