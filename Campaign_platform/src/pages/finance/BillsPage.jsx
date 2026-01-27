"use client"

import { useState, useEffect, useRef, useMemo } from "react"
import { Link, useNavigate } from "react-router-dom"
import { API_BASE_URL } from "../../config"
import { DEFAULT_CURRENCY, formatCurrency as formatCurrencyUtil } from "../../utils/currency"
import { FileText, Plus, Search, Eye, Camera, X, Loader2, Trash2, CreditCard, Upload, Download } from "lucide-react"
import { buildApiUrl } from "../../config"

function BillsPage() {
  const navigate = useNavigate()
  const [showModal, setShowModal] = useState(false)
  const [searchTerm, setSearchTerm] = useState("")
  const [statusFilter, setStatusFilter] = useState("all")
  const [bills, setBills] = useState([])
  const [loading, setLoading] = useState(true)
  const [exporting, setExporting] = useState(false)
  const [importing, setImporting] = useState(false)
  const [currentPage, setCurrentPage] = useState(1)
  const [recordsPerPage, setRecordsPerPage] = useState(10)
  const fileInputRef = useRef(null)
  const [formData, setFormData] = useState({
    vendor_id: "",
    bill_number: "",
    bill_date: new Date().toISOString().split("T")[0],
    due_date: "",
    items: [{ description: "", quantity: 1, rate: 0, tax_rate: 0 }],
  })
  const [vendors, setVendors] = useState([])

  useEffect(() => {
    fetchBills()
    fetchVendors()
  }, [])

  // Filtered bills with useMemo
  const filteredBills = useMemo(() => {
    return bills.filter((bill) => {
      const q = searchTerm.trim().toLowerCase()
      const matchesSearch = !q ||
        bill.bill_number?.toLowerCase().includes(q) ||
        bill.vendor_name?.toLowerCase().includes(q)
      const matchesStatus = statusFilter === "all" || bill.status === statusFilter
      return matchesSearch && matchesStatus
    })
  }, [bills, searchTerm, statusFilter])

  // Pagination
  const totalPages = Math.ceil(filteredBills.length / recordsPerPage)
  const startIdx = (currentPage - 1) * recordsPerPage
  const endIdx = startIdx + recordsPerPage
  const paginatedBills = filteredBills.slice(startIdx, endIdx)

  const handleSearch = (value) => {
    setSearchTerm(value)
    setCurrentPage(1)
  }

  const handleStatusFilter = (value) => {
    setStatusFilter(value)
    setCurrentPage(1)
  }

  const handleRecordsPerPageChange = (value) => {
    setRecordsPerPage(parseInt(value))
    setCurrentPage(1)
  }

  const fetchBills = async () => {
    try {
      const response = await fetch(buildApiUrl(`/finance/finance/bills/`))
      if (response.ok) {
        const data = await response.json()
        setBills(data)
      }
    } catch (error) {
      console.error("Error fetching bills:", error)
    } finally {
      setLoading(false)
    }
  }

  const fetchVendors = async () => {
    try {
      const response = await fetch(buildApiUrl(`/finance/finance/vendors/`))
      if (response.ok) {
        const data = await response.json()
        setVendors(data)
      }
    } catch (error) {
      console.error("Error fetching vendors:", error)
    }
  }

  const handleItemChange = (index, field, value) => {
    const newItems = [...formData.items]
    newItems[index][field] = value
    setFormData({ ...formData, items: newItems })
  }

  const addLineItem = () => {
    setFormData({ ...formData, items: [...formData.items, { description: "", quantity: 1, rate: 0, tax_rate: 0 }] })
  }

  const removeLineItem = (index) => {
    const newItems = formData.items.filter((_, i) => i !== index)
    setFormData({ ...formData, items: newItems })
  }

  const calculateSubtotal = () => {
    return formData.items.reduce((total, item) => total + item.quantity * item.rate, 0)
  }

  const calculateTax = () => {
    return formData.items.reduce((total, item) => total + (item.quantity * item.rate * item.tax_rate) / 100, 0)
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    try {
      const billData = {
        ...formData,
        items: formData.items.map((item) => ({
          ...item,
          amount: item.quantity * item.rate,
          tax_amount: (item.quantity * item.rate * item.tax_rate) / 100,
        })),
      }

      const response = await fetch(buildApiUrl(`/finance/finance/bills/`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(billData),
      })

      if (response.ok) {
        fetchBills()
        handleCloseModal()
      } else {
        const error = await response.json()
        alert(error.detail || "Error creating bill")
      }
    } catch (error) {
      console.error("Error creating bill:", error)
      alert("Error creating bill")
    }
  }

  const handleDeleteBill = async (id) => {
    if (!window.confirm("Are you sure you want to delete this bill?")) return

    try {
      const response = await fetch(buildApiUrl(`/finance/finance/bills/${id}`), {
        method: "DELETE",
      })
      if (response.ok) {
        fetchBills()
      }
    } catch (error) {
      console.error("Error deleting bill:", error)
    }
  }

  const handleCloseModal = () => {
    setShowModal(false)
  }

  const formatCurrency = (amount) => {
    return formatCurrencyUtil(amount, DEFAULT_CURRENCY)
  }

  // Export bills to CSV
  const handleExportCSV = async () => {
    setExporting(true)
    try {
      const response = await fetch(buildApiUrl(`/finance/finance/bills/export/csv`))
      if (response.ok) {
        const blob = await response.blob()
        const url = window.URL.createObjectURL(blob)
        const a = document.createElement("a")
        a.href = url
        a.download = `bills_export_${new Date().toISOString().split("T")[0]}.csv`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        window.URL.revokeObjectURL(url)
      }
    } catch (error) {
      console.error("Error exporting bills:", error)
      alert("Failed to export bills")
    } finally {
      setExporting(false)
    }
  }

  // Import bills from CSV
  const handleImportCSV = async (event) => {
    const file = event.target.files?.[0]
    if (!file) return

    setImporting(true)
    const formDataUpload = new FormData()
    formDataUpload.append("file", file)

    try {
      const response = await fetch(buildApiUrl(`/finance/finance/bills/import/csv`), {
        method: "POST",
        body: formDataUpload,
      })

      if (response.ok) {
        const result = await response.json()
        alert(`Successfully imported ${result.imported} bills`)
        fetchBills()
      } else {
        const error = await response.json()
        alert(`Import failed: ${error.detail}`)
      }
    } catch (error) {
      console.error("Error importing bills:", error)
      alert("Failed to import bills")
    } finally {
      setImporting(false)
      if (fileInputRef.current) {
        fileInputRef.current.value = ""
      }
    }
  }

  const styles = {
    container: {
      minHeight: "100vh",
      backgroundColor: "#f9fafb",
      padding: "1.5rem",
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
    statusSelect: {
      padding: "0.75rem 1rem",
      border: "1px solid #d1d5db",
      borderRadius: "0.5rem",
      fontSize: "0.95rem",
      backgroundColor: "white",
      cursor: "pointer",
    },
    recordsPerPageSelect: {
      padding: "0.75rem 1rem",
      border: "1px solid #d1d5db",
      borderRadius: "0.5rem",
      fontSize: "0.95rem",
      backgroundColor: "white",
      cursor: "pointer",
    },
    stats: {
      display: "flex",
      gap: "2rem",
      fontSize: "0.9rem",
      color: "#6b7280",
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
    badgeGreen: {
      display: "inline-block",
      padding: "0.375rem 0.75rem",
      borderRadius: "0.375rem",
      fontSize: "0.8rem",
      fontWeight: "600",
      textTransform: "uppercase",
      backgroundColor: "#d1fae5",
      color: "#065f46",
    },
    badgeOrange: {
      display: "inline-block",
      padding: "0.375rem 0.75rem",
      borderRadius: "0.375rem",
      fontSize: "0.8rem",
      fontWeight: "600",
      textTransform: "uppercase",
      backgroundColor: "#fef3c7",
      color: "#92400e",
    },
    badgeRed: {
      display: "inline-block",
      padding: "0.375rem 0.75rem",
      borderRadius: "0.375rem",
      fontSize: "0.8rem",
      fontWeight: "600",
      textTransform: "uppercase",
      backgroundColor: "#fee2e2",
      color: "#991b1b",
    },
    badgeBlue: {
      display: "inline-block",
      padding: "0.375rem 0.75rem",
      borderRadius: "0.375rem",
      fontSize: "0.8rem",
      fontWeight: "600",
      textTransform: "uppercase",
      backgroundColor: "#dbeafe",
      color: "#1e40af",
    },
    actionButtons: {
      display: "flex",
      gap: "0.5rem",
    },
    btnIcon: {
      padding: "0.5rem",
      backgroundColor: "transparent",
      color: "#6b7280",
      border: "none",
      borderRadius: "0.375rem",
      cursor: "pointer",
      fontSize: "1rem",
      transition: "all 0.2s",
    },
    btnEdit: {
      padding: "0.5rem 0.75rem",
      backgroundColor: "#6b7280",
      color: "white",
      border: "none",
      borderRadius: "0.375rem",
      cursor: "pointer",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
    },
    emptyState: {
      textAlign: "center",
      padding: "3rem",
      color: "#9ca3af",
    },
    paginationContainer: {
      display: "flex",
      justifyContent: "center",
      alignItems: "center",
      gap: "1rem",
      marginTop: "2rem",
      padding: "1rem",
      backgroundColor: "white",
      borderRadius: "0.75rem",
      boxShadow: "0 1px 3px rgba(0,0,0,0.1)",
    },
    paginationBtn: {
      padding: "0.5rem 1rem",
      backgroundColor: "#0d6efd",
      color: "white",
      border: "none",
      borderRadius: "0.375rem",
      fontSize: "0.9rem",
      fontWeight: "500",
      cursor: "pointer",
      transition: "all 0.2s",
    },
    paginationBtnDisabled: {
      backgroundColor: "#d1d5db",
      cursor: "not-allowed",
      opacity: "0.6",
    },
    pageInfo: {
      fontSize: "0.9rem",
      color: "#6b7280",
      minWidth: "150px",
      textAlign: "center",
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
      maxWidth: "900px",
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
      fontSize: "1.5rem",
      color: "#9ca3af",
      cursor: "pointer",
      padding: "0",
    },
    modalBody: {
      padding: "1.5rem",
      overflowY: "auto",
      flex: "1",
    },
    section: {
      marginBottom: "2rem",
      paddingBottom: "1.5rem",
      borderBottom: "1px solid #e5e7eb",
    },
    sectionTitle: {
      fontSize: "1.1rem",
      fontWeight: "600",
      color: "#1a1a1a",
      marginBottom: "1rem",
      textTransform: "uppercase",
      letterSpacing: "0.05em",
    },
    formRow: {
      display: "grid",
      gridTemplateColumns: "repeat(4, 1fr)",
      gap: "1rem",
      marginBottom: "1rem",
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
    required: {
      color: "#ef4444",
    },
    input: {
      padding: "0.75rem",
      border: "1px solid #d1d5db",
      borderRadius: "0.5rem",
      fontSize: "0.95rem",
      transition: "all 0.2s",
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
    lineItemsTable: {
      width: "100%",
      fontSize: "0.9rem",
      borderCollapse: "collapse",
    },
    lineItemsHead: {
      backgroundColor: "#f9fafb",
      borderTop: "1px solid #e5e7eb",
      borderBottom: "1px solid #e5e7eb",
    },
    lineItemsHeadCell: {
      padding: "0.75rem",
      textAlign: "left",
      fontSize: "0.8rem",
      fontWeight: "600",
      textTransform: "uppercase",
      color: "#6b7280",
      letterSpacing: "0.05em",
    },
    lineItemsBody: {
      borderBottom: "1px solid #e5e7eb",
    },
    lineItemsBodyCell: {
      padding: "0.75rem",
      borderRight: "1px solid #f3f4f6",
    },
    totalsSection: {
      backgroundColor: "#f9fafb",
      borderRadius: "0.5rem",
      padding: "1rem",
      marginTop: "1rem",
      textAlign: "right",
    },
    totalRow: {
      display: "flex",
      justifyContent: "space-between",
      fontSize: "0.9rem",
      marginBottom: "0.5rem",
    },
    totalRowBold: {
      display: "flex",
      justifyContent: "space-between",
      fontSize: "1.1rem",
      fontWeight: "700",
      marginTop: "0.75rem",
      paddingTop: "0.75rem",
      borderTop: "2px solid #e5e7eb",
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
      transition: "all 0.2s",
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
      transition: "all 0.2s",
      display: "flex",
      alignItems: "center",
      gap: "0.5rem",
    },
  }

  const getStatusStyle = (status) => {
    switch (status) {
      case "paid":
        return styles.badgeGreen
      case "pending":
        return styles.badgeOrange
      case "overdue":
        return styles.badgeRed
      case "partial":
        return styles.badgeBlue
      default:
        return styles.badgeBlue
    }
  }

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <div>
          <h2 style={styles.title}>Bills</h2>
          <p style={styles.subtitle}>Manage vendor bills and payables</p>
        </div>
        <div style={{ display: "flex", gap: "0.75rem" }}>
          <button 
            style={styles.btnSecondary} 
            onClick={() => navigate("/admin/finance/bills/import")}
          >
            <Upload style={{ width: "16px", height: "16px", marginRight: "0.5rem" }} />
            Import CSV
          </button>
          <button 
            style={styles.btnSecondary} 
            onClick={handleExportCSV}
            disabled={exporting}
          >
            <Download style={{ width: "16px", height: "16px", marginRight: "0.5rem" }} />
            {exporting ? "Exporting..." : "Export CSV"}
          </button>
          <button style={styles.btnPrimary} onClick={() => setShowModal(true)}>
            + Create Bill
          </button>
        </div>
      </div>

      <div style={styles.searchSection}>
        <div style={{ position: "relative", flex: "1", maxWidth: "400px" }}>
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
            type="text"
            placeholder="Search by bill #, vendor..."
            value={searchTerm}
            onChange={(e) => handleSearch(e.target.value)}
            style={styles.searchInput}
          />
        </div>
        <select value={statusFilter} onChange={(e) => handleStatusFilter(e.target.value)} style={styles.statusSelect}>
          <option value="all">All Status</option>
          <option value="pending">Pending</option>
          <option value="paid">Paid</option>
          <option value="partial">Partially Paid</option>
          <option value="overdue">Overdue</option>
        </select>
        <select
          style={styles.recordsPerPageSelect}
          value={recordsPerPage}
          onChange={(e) => handleRecordsPerPageChange(e.target.value)}
        >
          <option value={10}>10 per page</option>
          <option value={20}>20 per page</option>
          <option value={50}>50 per page</option>
          <option value={100}>100 per page</option>
        </select>
        <div style={styles.stats}>
          <span>Total: <strong>{bills.length}</strong></span>
          <span>Pending: <strong>{bills.filter(b => b.status === "pending").length}</strong></span>
          <span>Paid: <strong>{bills.filter(b => b.status === "paid").length}</strong></span>
          <span>Overdue: <strong>{bills.filter(b => b.status === "overdue").length}</strong></span>
        </div>
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
            <p style={{ color: "#6b7280" }}>Loading bills...</p>
          </div>
        </div>
      ) : (
        <div style={styles.tableContainer}>
          <table style={styles.table}>
            <thead style={styles.thead}>
              <tr style={styles.tr}>
                <th style={styles.th}>Bill #</th>
                <th style={styles.th}>Vendor</th>
                <th style={styles.th}>Date</th>
                <th style={styles.th}>Due Date</th>
                <th style={styles.th}>Amount</th>
                <th style={styles.th}>Balance</th>
                <th style={styles.th}>Status</th>
                <th style={styles.th}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {paginatedBills.map((bill) => (
                <tr key={bill._id} style={styles.tr}>
                  <td style={styles.td}>
                    <code
                      style={{
                        fontSize: "0.85rem",
                        backgroundColor: "#f3f4f6",
                        padding: "0.375rem 0.75rem",
                        borderRadius: "0.375rem",
                        fontFamily: "monospace",
                      }}
                    >
                      {bill.bill_number}
                    </code>
                  </td>
                  <td style={styles.td}>{bill.vendor_name || "N/A"}</td>
                  <td style={styles.td}>{new Date(bill.bill_date).toLocaleDateString("en-IN")}</td>
                  <td style={styles.td}>{new Date(bill.due_date).toLocaleDateString("en-IN")}</td>
                  <td style={{ ...styles.td, fontWeight: "600" }}>{formatCurrency(bill.total_amount)}</td>
                  <td
                    style={{
                      ...styles.td,
                      color: bill.balance_due > 0 ? "#b45309" : "#374151",
                      fontWeight: bill.balance_due > 0 ? "500" : "normal",
                    }}
                  >
                    {formatCurrency(bill.balance_due)}
                  </td>
                  <td style={styles.td}>
                    <span style={getStatusStyle(bill.status)}>{bill.status}</span>
                  </td>
                  <td style={styles.td}>
                    <div style={styles.actionButtons}>
                      <button style={styles.btnEdit}>
                        <Eye style={{ width: "16px", height: "16px" }} />
                      </button>
                      <button style={styles.btnEdit}>
                        <CreditCard style={{ width: "16px", height: "16px" }} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {paginatedBills.length === 0 && filteredBills.length === 0 && (
                <tr style={styles.tr}>
                  <td colSpan={8} style={styles.emptyState}>
                    <FileText style={{ width: "48px", height: "48px", margin: "0 auto 1rem", opacity: "0.5" }} />
                    <p>No bills found. Click "Create Bill" to add one.</p>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div style={styles.paginationContainer}>
          <button
            style={{...styles.paginationBtn, ...(currentPage === 1 ? styles.paginationBtnDisabled : {})}}
            onClick={() => setCurrentPage(Math.max(1, currentPage - 1))}
            disabled={currentPage === 1}
          >
            ← Previous
          </button>
          <div style={styles.pageInfo}>
            Page <strong>{currentPage}</strong> of <strong>{totalPages}</strong>
          </div>
          <button
            style={{...styles.paginationBtn, ...(currentPage === totalPages ? styles.paginationBtnDisabled : {})}}
            onClick={() => setCurrentPage(Math.min(totalPages, currentPage + 1))}
            disabled={currentPage === totalPages}
          >
            Next →
          </button>
        </div>
      )}

      {showModal && (
        <div style={styles.modal} onClick={handleCloseModal}>
          <div style={styles.modalContent} onClick={(e) => e.stopPropagation()}>
            <div style={styles.modalHeader}>
              <h3 style={styles.modalTitle}>Create Bill</h3>
              <button onClick={handleCloseModal} style={styles.closeBtn}>
                <X style={{ width: "1.5rem", height: "1.5rem" }} />
              </button>
            </div>

            <form onSubmit={handleSubmit} style={styles.modalBody}>
              <div style={styles.formRow}>
                <div style={styles.formGroup}>
                  <label style={styles.label}>
                    Vendor <span style={styles.required}>*</span>
                  </label>
                  <select
                    value={formData.vendor_id}
                    onChange={(e) => setFormData({ ...formData, vendor_id: e.target.value })}
                    style={styles.select}
                    required
                  >
                    <option value="">Select Vendor</option>
                    {vendors.map((v) => (
                      <option key={v._id} value={v._id}>
                        {v.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div style={styles.formGroup}>
                  <label style={styles.label}>
                    Bill Number <span style={styles.required}>*</span>
                  </label>
                  <input
                    type="text"
                    value={formData.bill_number}
                    onChange={(e) => setFormData({ ...formData, bill_number: e.target.value })}
                    style={styles.input}
                    required
                    placeholder="Vendor's bill number"
                  />
                </div>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Bill Date</label>
                  <input
                    type="date"
                    value={formData.bill_date}
                    onChange={(e) => setFormData({ ...formData, bill_date: e.target.value })}
                    style={styles.input}
                  />
                </div>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Due Date</label>
                  <input
                    type="date"
                    value={formData.due_date}
                    onChange={(e) => setFormData({ ...formData, due_date: e.target.value })}
                    style={styles.input}
                  />
                </div>
              </div>

              <div style={styles.section}>
                <h4 style={styles.sectionTitle}>Line Items</h4>
                <div style={{ overflowX: "auto" }}>
                  <table style={styles.lineItemsTable}>
                    <thead style={styles.lineItemsHead}>
                      <tr>
                        <th style={styles.lineItemsHeadCell}>Description</th>
                        <th style={styles.lineItemsHeadCell}>Qty</th>
                        <th style={styles.lineItemsHeadCell}>Rate</th>
                        <th style={styles.lineItemsHeadCell}>Tax %</th>
                        <th style={{ ...styles.lineItemsHeadCell, textAlign: "right" }}>Amount</th>
                        <th style={styles.lineItemsHeadCell}></th>
                      </tr>
                    </thead>
                    <tbody>
                      {formData.items.map((item, index) => (
                        <tr key={index} style={styles.lineItemsBody}>
                          <td style={styles.lineItemsBodyCell}>
                            <input
                              type="text"
                              value={item.description}
                              onChange={(e) => handleItemChange(index, "description", e.target.value)}
                              placeholder="Description"
                              style={styles.input}
                            />
                          </td>
                          <td style={styles.lineItemsBodyCell}>
                            <input
                              type="number"
                              value={item.quantity}
                              onChange={(e) => handleItemChange(index, "quantity", Number.parseFloat(e.target.value))}
                              min={1}
                              style={styles.input}
                            />
                          </td>
                          <td style={styles.lineItemsBodyCell}>
                            <input
                              type="number"
                              value={item.rate}
                              onChange={(e) => handleItemChange(index, "rate", Number.parseFloat(e.target.value))}
                              min={0}
                              style={styles.input}
                            />
                          </td>
                          <td style={styles.lineItemsBodyCell}>
                            <select
                              value={item.tax_rate}
                              onChange={(e) => handleItemChange(index, "tax_rate", Number.parseFloat(e.target.value))}
                              style={styles.select}
                            >
                              <option value={0}>0%</option>
                              <option value={5}>5%</option>
                              <option value={12}>12%</option>
                              <option value={18}>18%</option>
                              <option value={28}>28%</option>
                            </select>
                          </td>
                          <td style={{ ...styles.lineItemsBodyCell, textAlign: "right", fontWeight: "500" }}>
                            {formatCurrency(item.quantity * item.rate)}
                          </td>
                          <td style={styles.lineItemsBodyCell}>
                            <button style={styles.btnIcon} type="button" onClick={() => removeLineItem(index)}>
                              <Trash2 style={{ width: "1rem", height: "1rem", color: "#ef4444" }} />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <button style={styles.btnSecondary} type="button" onClick={addLineItem}>
                  <Plus style={{ width: "1rem", height: "1rem", marginRight: "0.5rem" }} />
                  Add Line Item
                </button>
              </div>

              <div style={styles.totalsSection}>
                <div style={styles.totalRow}>
                  <span>Subtotal:</span>
                  <span>{formatCurrency(calculateSubtotal())}</span>
                </div>
                <div style={styles.totalRow}>
                  <span>Tax:</span>
                  <span>{formatCurrency(calculateTax())}</span>
                </div>
                <div style={styles.totalRowBold}>
                  <span>Grand Total:</span>
                  <span style={{ color: "#0d6efd" }}>{formatCurrency(calculateSubtotal() + calculateTax())}</span>
                </div>
              </div>
            </form>

            <div style={styles.modalFooter}>
              <button style={styles.btnCancel} type="button" onClick={handleCloseModal}>
                Cancel
              </button>
              <button style={styles.btnPrimary} type="submit" onClick={handleSubmit}>
                Create Bill
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default BillsPage
