"use client"

import { useState, useEffect, useRef, useMemo } from "react"
import { useNavigate } from "react-router-dom"
import { API_BASE_URL } from "../../config"
import { FileText, Search, Pencil, Trash2, Loader2, Upload, Download, Plus, Eye } from "lucide-react"
import { buildApiUrl } from "../../config"

// Estimate status options
const ESTIMATE_STATUS_OPTIONS = [
  { value: "draft", label: "Draft" },
  { value: "sent", label: "Sent" },
  { value: "accepted", label: "Accepted" },
  { value: "declined", label: "Declined" },
  { value: "expired", label: "Expired" },
]

function EstimatesPage() {
  const navigate = useNavigate()
  const [estimates, setEstimates] = useState([])
  const [customers, setCustomers] = useState([])
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [searchTerm, setSearchTerm] = useState("")
  const [statusFilter, setStatusFilter] = useState("all")
  const [showModal, setShowModal] = useState(false)
  const [editingEstimate, setEditingEstimate] = useState(null)
  const [formErrors, setFormErrors] = useState({})
  const [exporting, setExporting] = useState(false)
  const [importing, setImporting] = useState(false)
  const [error, setError] = useState(null)
  const [currentPage, setCurrentPage] = useState(1)
  const [recordsPerPage, setRecordsPerPage] = useState(10)
  const fileInputRef = useRef(null)

  const initialFormData = {
    customer_id: "",
    estimate_number: "",
    estimate_date: new Date().toISOString().split("T")[0],
    expiry_date: new Date(Date.now() + 30 * 24 * 60 * 60 * 1000).toISOString().split("T")[0],
    reference: "",
    items: [{ item_id: "", description: "", quantity: 1, rate: 0, tax_rate: 18 }],
    discount_type: "flat",
    discount_value: 0,
    notes: "",
    terms: "This estimate is valid for 30 days",
    status: "draft",
  }

  const [formData, setFormData] = useState(initialFormData)

  useEffect(() => {
    fetchEstimates()
    fetchCustomers()
    fetchItems()
  }, [])

  const fetchEstimates = async () => {
    const sessionId = localStorage.getItem("session_id")
    if (!sessionId) {
      navigate("/admin/login")
      return
    }

    try {
      setError(null)
      const response = await fetch(buildApiUrl(`/finance/finance/estimates/`), {
        headers: {
          "Content-Type": "application/json",
          Authorization: sessionId,
        },
      })

      if (response.status === 401) {
        alert("Session expired. Please login again.")
        localStorage.removeItem("session_id")
        navigate("/admin/login")
        return
      }

      if (response.ok) {
        const data = await response.json()
        setEstimates(data)
      } else {
        const errorData = await response.json().catch(() => ({}))
        throw new Error(errorData.detail || "Failed to fetch estimates")
      }
    } catch (error) {
      console.error("Error fetching estimates:", error)
      setError(error.message || "Failed to load estimates")
    } finally {
      setLoading(false)
    }
  }

  const fetchCustomers = async () => {
    try {
      const sessionId = localStorage.getItem("session_id")
      const response = await fetch(buildApiUrl(`/finance/finance/customers/`), {
        headers: {
          "Content-Type": "application/json",
          Authorization: sessionId,
        },
      })
      if (response.ok) {
        const data = await response.json()
        setCustomers(data)
      }
    } catch (error) {
      console.error("Error fetching customers:", error)
    }
  }

  const fetchItems = async () => {
    try {
      const sessionId = localStorage.getItem("session_id")
      const response = await fetch(buildApiUrl(`/finance/finance/items/`), {
        headers: {
          "Content-Type": "application/json",
          Authorization: sessionId,
        },
      })
      if (response.ok) {
        const data = await response.json()
        setItems(data)
      }
    } catch (error) {
      console.error("Error fetching items:", error)
    }
  }

  const validateForm = () => {
    const errors = {}

    if (!formData.customer_id) {
      errors.customer_id = "Customer is required"
    }

    if (!formData.estimate_date) {
      errors.estimate_date = "Estimate date is required"
    }

    if (!formData.expiry_date) {
      errors.expiry_date = "Expiry date is required"
    }

    if (formData.items.length === 0 || !formData.items.some((item) => item.description || item.item_id)) {
      errors.items = "At least one item is required"
    }

    setFormErrors(errors)
    return Object.keys(errors).length === 0
  }

  const handleSubmit = async (e) => {
    e.preventDefault()

    if (!validateForm()) {
      return
    }

    const sessionId = localStorage.getItem("session_id")
    if (!sessionId) {
      navigate("/admin/login")
      return
    }

    setError(null)

    try {
      const estimateData = {
        ...formData,
        items: formData.items.map((item) => ({
          ...item,
          amount: item.quantity * item.rate,
          tax_amount: (item.quantity * item.rate * item.tax_rate) / 100,
        })),
      }

      const url = editingEstimate
        ? buildApiUrl(`/finance/finance/estimates/${editingEstimate._id}`)
        : buildApiUrl(`/finance/finance/estimates/`)

      const method = editingEstimate ? "PUT" : "POST"

      const response = await fetch(url, {
        method,
        headers: {
          "Content-Type": "application/json",
          Authorization: sessionId,
        },
        body: JSON.stringify(estimateData),
      })

      if (response.status === 401) {
        alert("Session expired. Please login again.")
        localStorage.removeItem("session_id")
        navigate("/admin/login")
        return
      }

      if (response.ok) {
        fetchEstimates()
        handleCloseModal()
      } else {
        const errorData = await response.json().catch(() => ({}))
        throw new Error(errorData.detail || "Failed to save estimate")
      }
    } catch (error) {
      console.error("Error saving estimate:", error)
      setError(error.message || "Save failed")
    }
  }

  const handleDelete = async (id) => {
    if (!window.confirm("Are you sure you want to delete this estimate?")) return

    const sessionId = localStorage.getItem("session_id")
    if (!sessionId) {
      navigate("/admin/login")
      return
    }

    try {
      setError(null)
      const response = await fetch(buildApiUrl(`/finance/finance/estimates/${id}`), {
        method: "DELETE",
        headers: {
          "Content-Type": "application/json",
          Authorization: sessionId,
        },
      })

      if (response.status === 401) {
        alert("Session expired. Please login again.")
        localStorage.removeItem("session_id")
        navigate("/admin/login")
        return
      }

      if (response.ok) {
        setEstimates((prev) => prev.filter((e) => e._id !== id))
      } else {
        const errorData = await response.json().catch(() => ({}))
        throw new Error(errorData.detail || "Failed to delete estimate")
      }
    } catch (error) {
      console.error("Error deleting estimate:", error)
      setError(error.message || "Delete failed")
    }
  }

  const handleEdit = (estimate) => {
    setEditingEstimate(estimate)
    setFormData({
      customer_id: estimate.customer_id || "",
      estimate_number: estimate.estimate_number || "",
      estimate_date: estimate.estimate_date?.split("T")[0] || new Date().toISOString().split("T")[0],
      expiry_date: estimate.expiry_date?.split("T")[0] || "",
      reference: estimate.reference || "",
      items: estimate.items?.length
        ? estimate.items.map((item) => ({
            item_id: item.item_id || "",
            description: item.description || "",
            quantity: item.quantity || 1,
            rate: item.rate || 0,
            tax_rate: item.tax_rate || 18,
          }))
        : [{ item_id: "", description: "", quantity: 1, rate: 0, tax_rate: 18 }],
      discount_type: estimate.discount_type || "flat",
      discount_value: estimate.discount_value || 0,
      notes: estimate.notes || "",
      terms: estimate.terms || "This estimate is valid for 30 days",
      status: estimate.status || "draft",
    })
    setFormErrors({})
    setError(null)
    setShowModal(true)
  }

  const handleItemChange = (index, field, value) => {
    const newItems = [...formData.items]
    newItems[index][field] = value

    if (field === "item_id") {
      const selectedItem = items.find((i) => i._id === value)
      if (selectedItem) {
        newItems[index].description = selectedItem.name
        newItems[index].rate = selectedItem.selling_price
        newItems[index].tax_rate = selectedItem.tax_rate
      }
    }

    setFormData({ ...formData, items: newItems })
  }

  const addLineItem = () => {
    setFormData({
      ...formData,
      items: [...formData.items, { item_id: "", description: "", quantity: 1, rate: 0, tax_rate: 18 }],
    })
  }

  const removeLineItem = (index) => {
    const newItems = formData.items.filter((_, i) => i !== index)
    setFormData({
      ...formData,
      items: newItems.length ? newItems : [{ item_id: "", description: "", quantity: 1, rate: 0, tax_rate: 18 }],
    })
  }

  const handleCloseModal = () => {
    setShowModal(false)
    setEditingEstimate(null)
    setFormData(initialFormData)
    setFormErrors({})
    setError(null)
  }

  // Filtered estimates with search and status filter
  const filteredEstimates = useMemo(() => {
    const q = searchTerm.trim().toLowerCase()
    return estimates.filter((estimate) => {
      const matchesSearch =
        !q ||
        estimate.estimate_number?.toLowerCase().includes(q) ||
        estimate.customer_name?.toLowerCase().includes(q) ||
        estimate.reference?.toLowerCase().includes(q)

      const matchesStatus = statusFilter === "all" || estimate.status === statusFilter

      return matchesSearch && matchesStatus
    })
  }, [estimates, searchTerm, statusFilter])

  // Pagination
  const totalPages = Math.ceil(filteredEstimates.length / recordsPerPage)
  const startIdx = (currentPage - 1) * recordsPerPage
  const endIdx = startIdx + recordsPerPage
  const paginatedEstimates = filteredEstimates.slice(startIdx, endIdx)

  const handleSearch = (value) => {
    setSearchTerm(value)
    setCurrentPage(1)
  }

  const handleStatusFilterChange = (value) => {
    setStatusFilter(value)
    setCurrentPage(1)
  }

  const handleRecordsPerPageChange = (value) => {
    setRecordsPerPage(parseInt(value))
    setCurrentPage(1)
  }

  const formatCurrency = (amount) => {
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency: "INR",
      maximumFractionDigits: 0,
    }).format(amount || 0)
  }

  const calculateSubtotal = () => {
    return formData.items.reduce((sum, item) => sum + item.quantity * item.rate, 0)
  }

  const calculateTax = () => {
    return formData.items.reduce((sum, item) => sum + (item.quantity * item.rate * item.tax_rate) / 100, 0)
  }

  const calculateDiscount = () => {
    const subtotal = calculateSubtotal()
    if (formData.discount_type === "percent") {
      return (subtotal * (formData.discount_value || 0)) / 100
    }
    return formData.discount_value || 0
  }

  const calculateTotal = () => {
    return calculateSubtotal() + calculateTax() - calculateDiscount()
  }

  const getCustomerName = (customerId) => {
    const customer = customers.find((c) => c._id === customerId)
    return customer?.name || "-"
  }

  const getStatusVariant = (status) => {
    switch (status) {
      case "accepted":
        return styles.statusAccepted
      case "sent":
        return styles.statusSent
      case "declined":
        return styles.statusDeclined
      case "expired":
        return styles.statusExpired
      case "draft":
        return styles.statusDraft
      default:
        return styles.statusDefault
    }
  }

  // Export estimates to CSV
  const handleExportCSV = async () => {
    const sessionId = localStorage.getItem("session_id")
    if (!sessionId) {
      navigate("/admin/login")
      return
    }

    setExporting(true)
    try {
      const response = await fetch(buildApiUrl(`/finance/finance/estimates/export/csv`), {
        headers: {
          Authorization: sessionId,
        },
      })

      if (response.status === 401) {
        alert("Session expired. Please login again.")
        localStorage.removeItem("session_id")
        navigate("/admin/login")
        return
      }

      if (response.ok) {
        const blob = await response.blob()
        const url = window.URL.createObjectURL(blob)
        const a = document.createElement("a")
        a.href = url
        a.download = `estimates_export_${new Date().toISOString().split("T")[0]}.csv`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        window.URL.revokeObjectURL(url)
      }
    } catch (error) {
      console.error("Error exporting estimates:", error)
      setError("Failed to export estimates")
    } finally {
      setExporting(false)
    }
  }

  // Import estimates from CSV
  const handleImportCSV = async (event) => {
    const file = event.target.files?.[0]
    if (!file) return

    const sessionId = localStorage.getItem("session_id")
    if (!sessionId) {
      navigate("/admin/login")
      return
    }

    setImporting(true)
    const formDataUpload = new FormData()
    formDataUpload.append("file", file)

    try {
      const response = await fetch(buildApiUrl(`/finance/finance/estimates/import/csv`), {
        method: "POST",
        headers: {
          Authorization: sessionId,
        },
        body: formDataUpload,
      })

      if (response.status === 401) {
        alert("Session expired. Please login again.")
        localStorage.removeItem("session_id")
        navigate("/admin/login")
        return
      }

      if (response.ok) {
        const result = await response.json()
        let message = `Successfully imported ${result.imported} estimates`
        if (result.errors?.length) {
          message += `\n\nErrors:\n${result.errors.join("\n")}`
        }
        alert(message)
        fetchEstimates()
      } else {
        const errorData = await response.json().catch(() => ({}))
        throw new Error(errorData.detail || "Import failed")
      }
    } catch (error) {
      console.error("Error importing estimates:", error)
      alert(error.message || "Failed to import estimates")
    } finally {
      setImporting(false)
      if (fileInputRef.current) {
        fileInputRef.current.value = ""
      }
    }
  }

  // Open add modal
  const openAddModal = () => {
    setEditingEstimate(null)
    setFormData(initialFormData)
    setFormErrors({})
    setError(null)
    setShowModal(true)
  }

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <div>
          <h2 style={styles.title}>Estimates</h2>
          <p style={styles.subtitle}>Create and manage sales estimates</p>
        </div>
        <div style={{ display: "flex", gap: "0.75rem" }}>
          <button
            style={styles.btnSecondary}
            onClick={() => navigate("/admin/finance/estimates/import")}
          >
            <Upload style={{ width: "16px", height: "16px" }} />
            Import CSV
          </button>
          <button style={styles.btnSecondary} onClick={handleExportCSV} disabled={exporting}>
            <Download style={{ width: "16px", height: "16px" }} />
            {exporting ? "Exporting..." : "Export CSV"}
          </button>
          <button style={styles.btnPrimary} onClick={openAddModal}>
            <Plus style={{ width: "16px", height: "16px" }} />
            New Estimate
          </button>
        </div>
      </div>

      {error && <div style={styles.errorAlert}>{error}</div>}

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
            type="text"
            placeholder="Search by estimate no, customer, reference..."
            value={searchTerm}
            onChange={(e) => handleSearch(e.target.value)}
            style={styles.searchInput}
          />
        </div>
        <select
          style={styles.statusSelect}
          value={statusFilter}
          onChange={(e) => handleStatusFilterChange(e.target.value)}
        >
          <option value="all">All Status</option>
          {ESTIMATE_STATUS_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
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
          <option value={200}>200 per page</option>
        </select>
        <div style={styles.stats}>
          <span>
            Total: <strong>{estimates.length}</strong>
          </span>
          <span>
            Draft: <strong>{estimates.filter((e) => e.status === "draft").length}</strong>
          </span>
          <span>
            Sent: <strong>{estimates.filter((e) => e.status === "sent").length}</strong>
          </span>
          <span>
            Accepted: <strong>{estimates.filter((e) => e.status === "accepted").length}</strong>
          </span>
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
            <p style={{ color: "#6b7280" }}>Loading estimates...</p>
          </div>
        </div>
      ) : (
        <div style={styles.tableContainer}>
          <table style={styles.table}>
            <thead style={styles.thead}>
              <tr>
                <th style={styles.th}>Estimate No</th>
                <th style={styles.th}>Customer</th>
                <th style={styles.th}>Date</th>
                <th style={styles.th}>Expiry</th>
                <th style={styles.th}>Status</th>
                <th style={styles.th}>Amount</th>
                <th style={styles.th}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {paginatedEstimates.map((estimate) => (
                <tr key={estimate._id} style={styles.tr}>
                  <td style={styles.td}>
                    <span style={styles.estimateNo}>{estimate.estimate_number || "N/A"}</span>
                  </td>
                  <td style={styles.td}>
                    <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
                      <div
                        style={{
                          width: "32px",
                          height: "32px",
                          backgroundColor: "#f3f4f6",
                          borderRadius: "0.5rem",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                        }}
                      >
                        {(estimate.customer_name || getCustomerName(estimate.customer_id))
                          ?.charAt(0)
                          .toUpperCase()}
                      </div>
                      <span style={{ fontWeight: "500" }}>
                        {estimate.customer_name || getCustomerName(estimate.customer_id)}
                      </span>
                    </div>
                  </td>
                  <td style={styles.td}>
                    {estimate.estimate_date
                      ? new Date(estimate.estimate_date).toLocaleDateString("en-IN")
                      : "-"}
                  </td>
                  <td style={styles.td}>
                    {estimate.expiry_date ? new Date(estimate.expiry_date).toLocaleDateString("en-IN") : "-"}
                  </td>
                  <td style={styles.td}>
                    <span style={{ ...styles.statusBadge, ...getStatusVariant(estimate.status) }}>
                      {estimate.status?.charAt(0).toUpperCase() + estimate.status?.slice(1) || "Draft"}
                    </span>
                  </td>
                  <td style={{ ...styles.td, fontWeight: "600" }}>
                    <span style={styles.currencyBadge}>{formatCurrency(estimate.total || 0)}</span>
                  </td>
                  <td style={styles.td}>
                    <div style={styles.actionButtons}>
                      <button style={styles.btnEdit} onClick={() => handleEdit(estimate)} title="Edit">
                        <Pencil style={{ width: "16px", height: "16px" }} />
                      </button>
                      <button style={styles.btnView} title="View">
                        <Eye style={{ width: "16px", height: "16px" }} />
                      </button>
                      <button
                        style={styles.btnDelete}
                        onClick={() => handleDelete(estimate._id)}
                        title="Delete"
                      >
                        <Trash2 style={{ width: "16px", height: "16px" }} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {paginatedEstimates.length === 0 && filteredEstimates.length === 0 && (
                <tr>
                  <td colSpan={7} style={styles.emptyState}>
                    <FileText style={{ width: "48px", height: "48px", margin: "0 auto 1rem", opacity: 0.5 }} />
                    <p>No estimates found. Click "New Estimate" to create one.</p>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      <Pagination
        currentPage={currentPage}
        totalPages={totalPages}
        totalRecords={totalEstimates}
        pageSize={recordsPerPage}
        onPageChange={handlePageChange}
        onPageSizeChange={handleRecordsPerPageChange}
        loading={loading}
      />

      {/* Modal for Add/Edit Estimate */}
      {showModal && (
        <div style={styles.modal} onClick={handleCloseModal}>
          <div style={styles.modalContent} onClick={(e) => e.stopPropagation()}>
            <div style={styles.modalHeader}>
              <h3 style={styles.modalTitle}>{editingEstimate ? "Edit Estimate" : "New Estimate"}</h3>
              <button style={styles.closeBtn} onClick={handleCloseModal}>
                ×
              </button>
            </div>

            <div style={{ ...styles.modalBody, overflow: "auto", flex: 1, maxHeight: "70vh" }}>
              {/* Estimate Number - Read only when editing */}
              {editingEstimate && formData.estimate_number && (
                <div style={{ marginBottom: "1.5rem" }}>
                  <div style={styles.formGroup}>
                    <label style={styles.label}>Estimate No</label>
                    <input
                      style={{ ...styles.input, backgroundColor: "#f3f4f6", cursor: "not-allowed" }}
                      value={formData.estimate_number}
                      disabled
                      readOnly
                    />
                  </div>
                </div>
              )}

              {/* Basic Information */}
              <div
                style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "1rem", marginBottom: "1.5rem" }}
              >
                <div style={styles.formGroup}>
                  <label style={styles.label}>Customer *</label>
                  <select
                    style={{
                      ...styles.select,
                      borderColor: formErrors.customer_id ? "#ef4444" : undefined,
                    }}
                    value={formData.customer_id}
                    onChange={(e) => setFormData({ ...formData, customer_id: e.target.value })}
                    required
                  >
                    <option value="">Select Customer</option>
                    {customers.map((customer) => (
                      <option key={customer._id} value={customer._id}>
                        {customer.name}
                      </option>
                    ))}
                  </select>
                  {formErrors.customer_id && <span style={styles.errorText}>{formErrors.customer_id}</span>}
                </div>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Estimate Date *</label>
                  <input
                    style={{
                      ...styles.input,
                      borderColor: formErrors.estimate_date ? "#ef4444" : undefined,
                    }}
                    type="date"
                    value={formData.estimate_date}
                    onChange={(e) => setFormData({ ...formData, estimate_date: e.target.value })}
                    required
                  />
                  {formErrors.estimate_date && <span style={styles.errorText}>{formErrors.estimate_date}</span>}
                </div>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Expiry Date *</label>
                  <input
                    style={{
                      ...styles.input,
                      borderColor: formErrors.expiry_date ? "#ef4444" : undefined,
                    }}
                    type="date"
                    value={formData.expiry_date}
                    onChange={(e) => setFormData({ ...formData, expiry_date: e.target.value })}
                    required
                  />
                  {formErrors.expiry_date && <span style={styles.errorText}>{formErrors.expiry_date}</span>}
                </div>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem", marginBottom: "1.5rem" }}>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Reference</label>
                  <input
                    style={styles.input}
                    type="text"
                    value={formData.reference}
                    onChange={(e) => setFormData({ ...formData, reference: e.target.value })}
                    placeholder="PO or reference number"
                  />
                </div>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Status</label>
                  <select
                    style={styles.select}
                    value={formData.status}
                    onChange={(e) => setFormData({ ...formData, status: e.target.value })}
                  >
                    {ESTIMATE_STATUS_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              {/* Line Items */}
              <div style={styles.section}>
                <h4 style={styles.sectionTitle}>Items</h4>
                {formErrors.items && <span style={styles.errorText}>{formErrors.items}</span>}
                <table style={{ ...styles.table, marginBottom: "1rem" }}>
                  <thead style={styles.thead}>
                    <tr>
                      <th style={styles.th}>Item</th>
                      <th style={styles.th}>Description</th>
                      <th style={styles.th}>Qty</th>
                      <th style={styles.th}>Rate</th>
                      <th style={styles.th}>Tax %</th>
                      <th style={styles.th}>Amount</th>
                      <th style={styles.th}></th>
                    </tr>
                  </thead>
                  <tbody>
                    {formData.items.map((item, index) => (
                      <tr key={index} style={styles.tr}>
                        <td style={styles.td}>
                          <select
                            style={{ ...styles.select, minWidth: "120px" }}
                            value={item.item_id}
                            onChange={(e) => handleItemChange(index, "item_id", e.target.value)}
                          >
                            <option value="">Select Item</option>
                            {items.map((i) => (
                              <option key={i._id} value={i._id}>
                                {i.name}
                              </option>
                            ))}
                          </select>
                        </td>
                        <td style={styles.td}>
                          <input
                            style={{ ...styles.input, minWidth: "150px" }}
                            type="text"
                            value={item.description}
                            onChange={(e) => handleItemChange(index, "description", e.target.value)}
                            placeholder="Description"
                          />
                        </td>
                        <td style={styles.td}>
                          <input
                            style={{ ...styles.input, width: "70px" }}
                            type="number"
                            min="1"
                            value={item.quantity}
                            onChange={(e) => handleItemChange(index, "quantity", parseInt(e.target.value) || 0)}
                          />
                        </td>
                        <td style={styles.td}>
                          <input
                            style={{ ...styles.input, width: "100px" }}
                            type="number"
                            min="0"
                            value={item.rate}
                            onChange={(e) => handleItemChange(index, "rate", parseFloat(e.target.value) || 0)}
                          />
                        </td>
                        <td style={styles.td}>
                          <input
                            style={{ ...styles.input, width: "70px" }}
                            type="number"
                            min="0"
                            max="100"
                            value={item.tax_rate}
                            onChange={(e) => handleItemChange(index, "tax_rate", parseFloat(e.target.value) || 0)}
                          />
                        </td>
                        <td style={styles.td}>{formatCurrency(item.quantity * item.rate)}</td>
                        <td style={styles.td}>
                          <button style={styles.btnDelete} onClick={() => removeLineItem(index)}>
                            <Trash2 style={{ width: "14px", height: "14px" }} />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <button style={styles.btnSecondary} onClick={addLineItem}>
                  <Plus style={{ width: "14px", height: "14px" }} />
                  Add Item
                </button>
              </div>

              {/* Totals */}
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 1fr",
                  gap: "2rem",
                  marginBottom: "1.5rem",
                }}
              >
                <div>
                  {/* Discount */}
                  <div style={styles.section}>
                    <h4 style={styles.sectionTitle}>Discount</h4>
                    <div style={{ display: "flex", gap: "1rem" }}>
                      <select
                        style={styles.select}
                        value={formData.discount_type}
                        onChange={(e) => setFormData({ ...formData, discount_type: e.target.value })}
                      >
                        <option value="flat">Flat Amount</option>
                        <option value="percent">Percentage</option>
                      </select>
                      <input
                        style={styles.input}
                        type="number"
                        min="0"
                        value={formData.discount_value}
                        onChange={(e) =>
                          setFormData({ ...formData, discount_value: parseFloat(e.target.value) || 0 })
                        }
                        placeholder={formData.discount_type === "percent" ? "%" : "Amount"}
                      />
                    </div>
                  </div>
                </div>
                <div style={styles.totalsCard}>
                  <div style={styles.totalRow}>
                    <span>Subtotal:</span>
                    <span>{formatCurrency(calculateSubtotal())}</span>
                  </div>
                  <div style={styles.totalRow}>
                    <span>Tax:</span>
                    <span>{formatCurrency(calculateTax())}</span>
                  </div>
                  <div style={styles.totalRow}>
                    <span>Discount:</span>
                    <span>-{formatCurrency(calculateDiscount())}</span>
                  </div>
                  <div style={{ ...styles.totalRow, ...styles.totalFinal }}>
                    <span>Total:</span>
                    <span>{formatCurrency(calculateTotal())}</span>
                  </div>
                </div>
              </div>

              {/* Notes & Terms */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Notes</label>
                  <textarea
                    style={{ ...styles.input, minHeight: "80px", resize: "vertical" }}
                    value={formData.notes}
                    onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
                    placeholder="Any notes for the customer"
                  />
                </div>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Terms & Conditions</label>
                  <textarea
                    style={{ ...styles.input, minHeight: "80px", resize: "vertical" }}
                    value={formData.terms}
                    onChange={(e) => setFormData({ ...formData, terms: e.target.value })}
                    placeholder="Terms and conditions"
                  />
                </div>
              </div>
            </div>

            <div style={styles.modalFooter}>
              <button style={styles.btnCancel} onClick={handleCloseModal}>
                Cancel
              </button>
              <button style={styles.btnSave} onClick={handleSubmit}>
                {editingEstimate ? "Update Estimate" : "Create Estimate"}
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
    display: "flex",
    alignItems: "center",
    gap: "0.5rem",
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
  errorAlert: {
    padding: "1rem",
    marginBottom: "1.5rem",
    backgroundColor: "#fee2e2",
    color: "#991b1b",
    borderRadius: "0.5rem",
    border: "1px solid #fecaca",
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
  },
  td: {
    padding: "1rem",
    fontSize: "0.9rem",
    color: "#374151",
  },
  estimateNo: {
    fontWeight: "600",
    color: "#059669",
    fontFamily: "monospace",
    fontSize: "0.95rem",
  },
  statusBadge: {
    display: "inline-block",
    padding: "0.375rem 0.75rem",
    borderRadius: "0.375rem",
    fontSize: "0.8rem",
    fontWeight: "600",
    textTransform: "capitalize",
  },
  statusDraft: {
    backgroundColor: "#e5e7eb",
    color: "#6b7280",
  },
  statusSent: {
    backgroundColor: "#dbeafe",
    color: "#1e40af",
  },
  statusAccepted: {
    backgroundColor: "#d1fae5",
    color: "#065f46",
  },
  statusDeclined: {
    backgroundColor: "#fee2e2",
    color: "#991b1b",
  },
  statusExpired: {
    backgroundColor: "#fef3c7",
    color: "#92400e",
  },
  statusDefault: {
    backgroundColor: "#e5e7eb",
    color: "#6b7280",
  },
  currencyBadge: {
    backgroundColor: "#ecfdf5",
    color: "#047857",
    padding: "0.375rem 0.75rem",
    borderRadius: "0.375rem",
    fontFamily: "monospace",
    fontSize: "0.95rem",
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
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
  },
  btnView: {
    padding: "0.5rem 0.75rem",
    backgroundColor: "#0d6efd",
    color: "white",
    border: "none",
    borderRadius: "0.375rem",
    cursor: "pointer",
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
    maxWidth: "1000px",
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
  },
  modalBody: {
    padding: "1.5rem",
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
    backgroundColor: "white",
    cursor: "pointer",
  },
  errorText: {
    color: "#ef4444",
    fontSize: "0.75rem",
    marginTop: "0.25rem",
  },
  totalsCard: {
    backgroundColor: "#f9fafb",
    padding: "1.25rem",
    borderRadius: "0.5rem",
    border: "1px solid #e5e7eb",
  },
  totalRow: {
    display: "flex",
    justifyContent: "space-between",
    marginBottom: "0.5rem",
    fontSize: "0.95rem",
    color: "#374151",
  },
  totalFinal: {
    fontSize: "1.2rem",
    fontWeight: "700",
    borderTop: "2px solid #e5e7eb",
    paddingTop: "0.75rem",
    marginTop: "0.5rem",
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

export default EstimatesPage
