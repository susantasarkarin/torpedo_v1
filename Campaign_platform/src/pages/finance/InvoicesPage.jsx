"use client"

import { useState, useEffect, useRef, useMemo } from "react"
import { Link } from "react-router-dom"
import { API_BASE_URL } from "../../config"
import { CURRENCIES, DEFAULT_CURRENCY, formatCurrency } from "../../utils/currency"
import { FileText, Search, Eye, Download, Mail, Loader2, Trash2, Upload } from "lucide-react"

// Invoice status options
const INVOICE_STATUS_OPTIONS = [
  { value: "draft", label: "Draft" },
  { value: "sent", label: "Sent" },
  { value: "paid", label: "Paid" },
  { value: "overdue", label: "Overdue" },
]

// Discount type options
const DISCOUNT_TYPE_OPTIONS = [
  { value: "flat", label: "Flat Amount" },
  { value: "percent", label: "Percentage" },
]

function InvoicesPage() {
  const [invoices, setInvoices] = useState([])
  const [customers, setCustomers] = useState([])
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [searchTerm, setSearchTerm] = useState("")
  const [statusFilter, setStatusFilter] = useState("all")
  const [showModal, setShowModal] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [importing, setImporting] = useState(false)
  const [currentPage, setCurrentPage] = useState(1)
  const [recordsPerPage, setRecordsPerPage] = useState(10)
  const fileInputRef = useRef(null)
  
  const initialFormData = {
    customer_id: "",
    invoice_number: "",
    invoice_date: new Date().toISOString().split("T")[0],
    due_date: "",
    currency_code: DEFAULT_CURRENCY,
    po_reference: "",
    items: [{ item_id: "", description: "", quantity: 1, rate: 0, tax_rate: 18 }],
    discount_type: "flat",
    discount_value: 0,
    notes: "",
    terms: "Payment due within 30 days",
    terms_and_conditions: "",
    status: "draft",
    payment_status: "unpaid",
    payment_date: "",
    payment_reference: "",
  }
  
  const [formData, setFormData] = useState(initialFormData)

  useEffect(() => {
    fetchInvoices()
    fetchCustomers()
    fetchItems()
  }, [])

  const fetchInvoices = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/finance/finance/invoices/`)
      if (response.ok) {
        const data = await response.json()
        setInvoices(data)
      }
    } catch (error) {
      console.error("Error fetching invoices:", error)
    } finally {
      setLoading(false)
    }
  }

  const fetchCustomers = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/finance/finance/customers/`)
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
      const response = await fetch(`${API_BASE_URL}/finance/finance/items/`)
      if (response.ok) {
        const data = await response.json()
        setItems(data)
      }
    } catch (error) {
      console.error("Error fetching items:", error)
    }
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    try {
      const invoiceData = {
        ...formData,
        items: formData.items.map((item) => ({
          ...item,
          amount: item.quantity * item.rate,
          tax_amount: (item.quantity * item.rate * item.tax_rate) / 100,
        })),
      }

      const response = await fetch(`${API_BASE_URL}/finance/finance/invoices/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(invoiceData),
      })

      if (response.ok) {
        fetchInvoices()
        handleCloseModal()
      }
    } catch (error) {
      console.error("Error creating invoice:", error)
    }
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
    setFormData(initialFormData)
  }

  const getStatusVariant = (status) => {
    switch (status) {
      case "paid":
        return styles.statusPaid
      case "sent":
        return styles.statusSent
      case "overdue":
        return styles.statusOverdue
      case "draft":
        return styles.statusDraft
      default:
        return styles.statusDefault
    }
  }

  const handleCustomerChange = (customerId) => {
    const selectedCustomer = customers.find((c) => c._id === customerId)
    setFormData({
      ...formData,
      customer_id: customerId,
      currency_code: selectedCustomer?.currency_code || DEFAULT_CURRENCY,
    })
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

  // Export invoices to CSV
  const handleExportCSV = async () => {
    setExporting(true)
    try {
      const response = await fetch(`${API_BASE_URL}/finance/finance/invoices/export/csv`)
      if (response.ok) {
        const blob = await response.blob()
        const url = window.URL.createObjectURL(blob)
        const a = document.createElement("a")
        a.href = url
        a.download = `invoices_export_${new Date().toISOString().split("T")[0]}.csv`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        window.URL.revokeObjectURL(url)
      }
    } catch (error) {
      console.error("Error exporting invoices:", error)
      alert("Failed to export invoices")
    } finally {
      setExporting(false)
    }
  }

  // Import invoices from CSV
  const handleImportCSV = async (event) => {
    const file = event.target.files?.[0]
    if (!file) return

    setImporting(true)
    const formDataUpload = new FormData()
    formDataUpload.append("file", file)

    try {
      const response = await fetch(`${API_BASE_URL}/finance/finance/invoices/import/csv`, {
        method: "POST",
        body: formDataUpload,
      })

      if (response.ok) {
        const result = await response.json()
        let message = `Successfully imported ${result.imported} invoices`
        if (result.errors && result.errors.length > 0) {
          message += `\n\nWarnings:\n${result.errors.slice(0, 5).join("\n")}`
          if (result.errors.length > 5) {
            message += `\n... and ${result.errors.length - 5} more`
          }
        }
        alert(message)
        fetchInvoices()
      } else {
        const error = await response.json()
        alert(`Import failed: ${error.detail}`)
      }
    } catch (error) {
      console.error("Error importing invoices:", error)
      alert("Failed to import invoices")
    } finally {
      setImporting(false)
      if (fileInputRef.current) {
        fileInputRef.current.value = ""
      }
    }
  }

  const filteredInvoices = useMemo(() => {
    return invoices.filter((inv) => {
      const q = searchTerm.trim().toLowerCase()
      const matchesSearch = !q || 
        inv.invoice_number?.toLowerCase().includes(q) ||
        inv.customer_name?.toLowerCase().includes(q)
      const matchesStatus = statusFilter === "all" || inv.status === statusFilter
      return matchesSearch && matchesStatus
    })
  }, [invoices, searchTerm, statusFilter])

  // Pagination
  const totalPages = Math.ceil(filteredInvoices.length / recordsPerPage)
  const startIdx = (currentPage - 1) * recordsPerPage
  const endIdx = startIdx + recordsPerPage
  const paginatedInvoices = filteredInvoices.slice(startIdx, endIdx)

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

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <div>
          <h2 style={styles.title}>Invoices</h2>
          <p style={styles.subtitle}>Manage sales invoices and customer payments</p>
        </div>
        <div style={{ display: "flex", gap: "0.75rem" }}>
          <button 
            style={styles.btnSecondary} 
            onClick={() => navigate("/admin/finance/invoices/import")}
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
            + Create Invoice
          </button>
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
            placeholder="Search by invoice #, customer..."
            value={searchTerm}
            onChange={(e) => handleSearch(e.target.value)}
          />
        </div>
        <select
          style={styles.statusSelect}
          value={statusFilter}
          onChange={(e) => handleStatusFilter(e.target.value)}
        >
          <option value="all">All Status</option>
          <option value="draft">Draft</option>
          <option value="sent">Sent</option>
          <option value="paid">Paid</option>
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
          <span>Total: <strong>{invoices.length}</strong></span>
          <span>Draft: <strong>{invoices.filter(i => i.status === "draft").length}</strong></span>
          <span>Paid: <strong>{invoices.filter(i => i.status === "paid").length}</strong></span>
          <span>Overdue: <strong>{invoices.filter(i => i.status === "overdue").length}</strong></span>
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
            <p style={{ color: "#6b7280" }}>Loading invoices...</p>
          </div>
        </div>
      ) : (
        <div style={styles.tableContainer}>
          <table style={styles.table}>
            <thead style={styles.thead}>
              <tr>
                <th style={styles.th}>Invoice #</th>
                <th style={styles.th}>Customer</th>
                <th style={styles.th}>Date</th>
                <th style={styles.th}>Due Date</th>
                <th style={styles.th}>Currency</th>
                <th style={styles.th}>Amount</th>
                <th style={styles.th}>Status</th>
                <th style={styles.th}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {paginatedInvoices.map((invoice) => (
                <tr key={invoice._id} style={styles.tr}>
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
                      {invoice.invoice_number}
                    </code>
                  </td>
                  <td style={styles.td}>{invoice.customer_name || "N/A"}</td>
                  <td style={styles.td}>{new Date(invoice.invoice_date).toLocaleDateString("en-IN")}</td>
                  <td style={styles.td}>{new Date(invoice.due_date).toLocaleDateString("en-IN")}</td>
                  <td style={styles.td}>
                    <span style={styles.currencyBadge}>
                      {invoice.currency_code || "INR"}
                    </span>
                  </td>
                  <td style={{ ...styles.td, fontWeight: "600" }}>
                    {formatCurrency(invoice.total_amount, invoice.currency_code || "INR")}
                  </td>
                  <td style={styles.td}>
                    <span style={{ ...styles.statusBadge, ...getStatusVariant(invoice.status) }}>{invoice.status}</span>
                  </td>
                  <td style={styles.td}>
                    <div style={styles.actionButtons}>
                      <Link to={`/admin/finance/invoices/${invoice._id}`}>
                        <button style={styles.btnEdit}>
                          <Eye style={{ width: "16px", height: "16px" }} />
                        </button>
                      </Link>
                      <button style={styles.btnEdit}>
                        <Download style={{ width: "16px", height: "16px" }} />
                      </button>
                      <button style={styles.btnEdit}>
                        <Mail style={{ width: "16px", height: "16px" }} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {paginatedInvoices.length === 0 && filteredInvoices.length === 0 && (
                <tr>
                  <td colSpan={8} style={styles.emptyState}>
                    <FileText style={{ width: "48px", height: "48px", margin: "0 auto 1rem", opacity: 0.5 }} />
                    <p>No invoices found. Click "Create Invoice" to create one.</p>
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
              <h3 style={styles.modalTitle}>Create Invoice</h3>
              <button style={styles.closeBtn} onClick={handleCloseModal}>
                ×
              </button>
            </div>

            <form onSubmit={handleSubmit} style={{ ...styles.modalBody, overflow: "auto", flex: 1, maxHeight: "70vh" }}>
              {/* Basic Invoice Information */}
              <div
                style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: "1rem", marginBottom: "1rem" }}
              >
                <div style={styles.formGroup}>
                  <label style={styles.label}>Invoice Number</label>
                  <input
                    style={styles.input}
                    type="text"
                    value={formData.invoice_number}
                    onChange={(e) => setFormData({ ...formData, invoice_number: e.target.value })}
                    placeholder="Auto-generated if empty"
                  />
                </div>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Customer *</label>
                  <select
                    style={styles.select}
                    value={formData.customer_id}
                    onChange={(e) => handleCustomerChange(e.target.value)}
                    required
                  >
                    <option value="">Select Customer</option>
                    {customers.map((c) => (
                      <option key={c._id} value={c._id}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div style={styles.formGroup}>
                  <label style={styles.label}>PO Reference</label>
                  <input
                    style={styles.input}
                    type="text"
                    value={formData.po_reference}
                    onChange={(e) => setFormData({ ...formData, po_reference: e.target.value })}
                    placeholder="Customer PO number"
                  />
                </div>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Status</label>
                  <select
                    style={styles.select}
                    value={formData.status}
                    onChange={(e) => setFormData({ ...formData, status: e.target.value })}
                  >
                    {INVOICE_STATUS_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>{opt.label}</option>
                    ))}
                  </select>
                </div>
              </div>

              <div
                style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: "1rem", marginBottom: "1.5rem" }}
              >
                <div style={styles.formGroup}>
                  <label style={styles.label}>Currency</label>
                  <select
                    style={styles.select}
                    value={formData.currency_code}
                    onChange={(e) => setFormData({ ...formData, currency_code: e.target.value })}
                  >
                    {CURRENCIES.map((c) => (
                      <option key={c.code} value={c.code}>
                        {c.symbol} {c.code}
                      </option>
                    ))}
                  </select>
                </div>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Invoice Date *</label>
                  <input
                    style={styles.input}
                    type="date"
                    value={formData.invoice_date}
                    onChange={(e) => setFormData({ ...formData, invoice_date: e.target.value })}
                    required
                  />
                </div>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Due Date *</label>
                  <input
                    style={styles.input}
                    type="date"
                    value={formData.due_date}
                    onChange={(e) => setFormData({ ...formData, due_date: e.target.value })}
                    required
                  />
                </div>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Payment Status</label>
                  <select
                    style={styles.select}
                    value={formData.payment_status}
                    onChange={(e) => setFormData({ ...formData, payment_status: e.target.value })}
                  >
                    <option value="unpaid">Unpaid</option>
                    <option value="partial">Partially Paid</option>
                    <option value="paid">Paid</option>
                  </select>
                </div>
              </div>

              <div style={styles.section}>
                <h4 style={styles.sectionTitle}>Line Items</h4>
                <div style={{ overflowX: "auto" }}>
                  <table style={{ width: "100%", fontSize: "0.9rem" }}>
                    <thead
                      style={{
                        backgroundColor: "#f9fafb",
                        borderTop: "1px solid #e5e7eb",
                        borderBottom: "1px solid #e5e7eb",
                      }}
                    >
                      <tr>
                        <th style={{ padding: "0.75rem", textAlign: "left", fontWeight: "500", color: "#6b7280" }}>
                          Item
                        </th>
                        <th style={{ padding: "0.75rem", textAlign: "left", fontWeight: "500", color: "#6b7280" }}>
                          Description
                        </th>
                        <th
                          style={{
                            padding: "0.75rem",
                            textAlign: "left",
                            fontWeight: "500",
                            color: "#6b7280",
                            width: "80px",
                          }}
                        >
                          Qty
                        </th>
                        <th
                          style={{
                            padding: "0.75rem",
                            textAlign: "left",
                            fontWeight: "500",
                            color: "#6b7280",
                            width: "112px",
                          }}
                        >
                          Rate
                        </th>
                        <th
                          style={{
                            padding: "0.75rem",
                            textAlign: "left",
                            fontWeight: "500",
                            color: "#6b7280",
                            width: "80px",
                          }}
                        >
                          Tax %
                        </th>
                        <th
                          style={{
                            padding: "0.75rem",
                            textAlign: "right",
                            fontWeight: "500",
                            color: "#6b7280",
                            width: "112px",
                          }}
                        >
                          Amount
                        </th>
                        <th style={{ padding: "0.75rem", width: "40px" }}></th>
                      </tr>
                    </thead>
                    <tbody>
                      {formData.items.map((item, index) => (
                        <tr key={index} style={{ borderBottom: "1px solid #f3f4f6" }}>
                          <td style={{ padding: "0.75rem" }}>
                            <select
                              style={{
                                width: "100%",
                                padding: "0.375rem",
                                border: "1px solid #d1d5db",
                                borderRadius: "0.375rem",
                                fontSize: "0.85rem",
                              }}
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
                          <td style={{ padding: "0.75rem" }}>
                            <input
                              style={{
                                width: "100%",
                                padding: "0.375rem",
                                border: "1px solid #d1d5db",
                                borderRadius: "0.375rem",
                                fontSize: "0.85rem",
                              }}
                              type="text"
                              value={item.description}
                              onChange={(e) => handleItemChange(index, "description", e.target.value)}
                              placeholder="Description"
                            />
                          </td>
                          <td style={{ padding: "0.75rem" }}>
                            <input
                              style={{
                                width: "100%",
                                padding: "0.375rem",
                                border: "1px solid #d1d5db",
                                borderRadius: "0.375rem",
                                fontSize: "0.85rem",
                              }}
                              type="number"
                              value={item.quantity}
                              onChange={(e) => handleItemChange(index, "quantity", Number.parseFloat(e.target.value))}
                              min={1}
                            />
                          </td>
                          <td style={{ padding: "0.75rem" }}>
                            <input
                              style={{
                                width: "100%",
                                padding: "0.375rem",
                                border: "1px solid #d1d5db",
                                borderRadius: "0.375rem",
                                fontSize: "0.85rem",
                              }}
                              type="number"
                              value={item.rate}
                              onChange={(e) => handleItemChange(index, "rate", Number.parseFloat(e.target.value))}
                              min={0}
                            />
                          </td>
                          <td style={{ padding: "0.75rem" }}>
                            <select
                              style={{
                                width: "100%",
                                padding: "0.375rem",
                                border: "1px solid #d1d5db",
                                borderRadius: "0.375rem",
                                fontSize: "0.85rem",
                              }}
                              value={item.tax_rate}
                              onChange={(e) => handleItemChange(index, "tax_rate", Number.parseFloat(e.target.value))}
                            >
                              <option value={0}>0%</option>
                              <option value={5}>5%</option>
                              <option value={12}>12%</option>
                              <option value={18}>18%</option>
                              <option value={28}>28%</option>
                            </select>
                          </td>
                          <td style={{ padding: "0.75rem", textAlign: "right", fontWeight: "500" }}>
                            {formatCurrency(item.quantity * item.rate, formData.currency_code)}
                          </td>
                          <td style={{ padding: "0.75rem" }}>
                            <button style={styles.btnDelete} type="button" onClick={() => removeLineItem(index)}>
                              <Trash2 style={{ width: "16px", height: "16px" }} />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <button
                  style={{ ...styles.btnPrimary, marginTop: "1rem", fontSize: "0.85rem" }}
                  type="button"
                  onClick={addLineItem}
                >
                  + Add Line Item
                </button>
              </div>

              <div
                style={{
                  backgroundColor: "#f9fafb",
                  borderRadius: "0.5rem",
                  padding: "1rem",
                  marginTop: "1rem",
                  textAlign: "right",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    fontSize: "0.9rem",
                    marginBottom: "0.5rem",
                  }}
                >
                  <span style={{ color: "#6b7280" }}>Subtotal:</span>
                  <span style={{ fontWeight: "500" }}>
                    {formatCurrency(calculateSubtotal(), formData.currency_code)}
                  </span>
                </div>
                
                {/* Discount Section */}
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    fontSize: "0.9rem",
                    marginBottom: "0.5rem",
                  }}
                >
                  <span style={{ color: "#6b7280" }}>Discount:</span>
                  <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                    <select
                      style={{ ...styles.input, width: "80px", padding: "0.25rem", fontSize: "0.85rem" }}
                      value={formData.discount_type}
                      onChange={(e) => setFormData({ ...formData, discount_type: e.target.value })}
                    >
                      {DISCOUNT_TYPE_OPTIONS.map(opt => (
                        <option key={opt.value} value={opt.value}>{opt.label}</option>
                      ))}
                    </select>
                    <input
                      type="number"
                      style={{ ...styles.input, width: "80px", padding: "0.25rem", fontSize: "0.85rem", textAlign: "right" }}
                      value={formData.discount_value}
                      onChange={(e) => setFormData({ ...formData, discount_value: parseFloat(e.target.value) || 0 })}
                      min="0"
                      step="0.01"
                    />
                    <span style={{ fontWeight: "500", minWidth: "80px", textAlign: "right" }}>
                      -{formatCurrency(calculateDiscount(), formData.currency_code)}
                    </span>
                  </div>
                </div>

                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    fontSize: "0.9rem",
                    marginBottom: "0.5rem",
                  }}
                >
                  <span style={{ color: "#6b7280" }}>Tax:</span>
                  <span style={{ fontWeight: "500" }}>{formatCurrency(calculateTax(), formData.currency_code)}</span>
                </div>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    fontSize: "1.1rem",
                    fontWeight: "700",
                    borderTop: "1px solid #e5e7eb",
                    paddingTop: "0.5rem",
                  }}
                >
                  <span>Grand Total:</span>
                  <span>{formatCurrency(calculateTotal(), formData.currency_code)}</span>
                </div>
              </div>

              {/* Payment Details (shown when payment_status is paid) */}
              {formData.payment_status === "paid" && (
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem", marginTop: "1rem" }}>
                  <div>
                    <label style={styles.label}>Payment Date</label>
                    <input
                      type="date"
                      style={styles.input}
                      value={formData.payment_date}
                      onChange={(e) => setFormData({ ...formData, payment_date: e.target.value })}
                    />
                  </div>
                  <div>
                    <label style={styles.label}>Payment Reference</label>
                    <input
                      type="text"
                      style={styles.input}
                      value={formData.payment_reference}
                      onChange={(e) => setFormData({ ...formData, payment_reference: e.target.value })}
                      placeholder="Transaction ID / Reference No."
                    />
                  </div>
                </div>
              )}

              <div style={{ marginTop: "1rem" }}>
                <label style={styles.label}>Terms & Conditions</label>
                <textarea
                  style={{ ...styles.input, minHeight: "80px", resize: "vertical" }}
                  value={formData.terms_and_conditions || ""}
                  onChange={(e) => setFormData({ ...formData, terms_and_conditions: e.target.value })}
                  placeholder="Enter terms and conditions..."
                />
              </div>

              <div style={{ marginTop: "1rem" }}>
                <label style={styles.label}>Notes</label>
                <textarea
                  style={{ ...styles.input, minHeight: "60px", resize: "vertical" }}
                  value={formData.notes}
                  onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
                  placeholder="Notes for customer..."
                />
              </div>
            </form>

            <div style={styles.modalFooter}>
              <button style={styles.btnCancel} type="button" onClick={handleCloseModal}>
                Cancel
              </button>
              <button style={styles.btnSave} type="submit" onClick={handleSubmit}>
                Create Invoice
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
    fontFamily: "inherit",
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
    transition: "all 0.2s",
    display: "flex",
    alignItems: "center",
    gap: "0.5rem",
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
  statusBadge: {
    display: "inline-block",
    padding: "0.375rem 0.75rem",
    borderRadius: "0.375rem",
    fontSize: "0.8rem",
    fontWeight: "600",
    textTransform: "uppercase",
  },
  statusPaid: {
    backgroundColor: "#d1fae5",
    color: "#065f46",
  },
  statusSent: {
    backgroundColor: "#dbeafe",
    color: "#1e40af",
  },
  statusOverdue: {
    backgroundColor: "#fee2e2",
    color: "#991b1b",
  },
  statusDraft: {
    backgroundColor: "#fef3c7",
    color: "#92400e",
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
  currencyBadge: {
    display: "inline-block",
    backgroundColor: "#dbeafe",
    color: "#1e40af",
    borderRadius: "0.375rem",
    padding: "0.375rem 0.75rem",
    fontSize: "0.8rem",
    fontWeight: "600",
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
    backgroundColor: "white",
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
    lineHeight: "1",
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
    transition: "all 0.2s",
    backgroundColor: "white",
  },
  select: {
    padding: "0.75rem",
    border: "1px solid #d1d5db",
    borderRadius: "0.5rem",
    fontSize: "0.95rem",
    transition: "all 0.2s",
    cursor: "pointer",
    backgroundColor: "white",
  },
  modalFooter: {
    padding: "1rem 1.5rem",
    borderTop: "1px solid #e5e7eb",
    display: "flex",
    justifyContent: "flex-end",
    gap: "0.75rem",
    backgroundColor: "white",
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

export default InvoicesPage
