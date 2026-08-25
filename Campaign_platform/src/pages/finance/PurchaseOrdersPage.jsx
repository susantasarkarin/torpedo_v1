"use client"

import { useState, useEffect, useRef, useMemo } from "react"
import { useNavigate } from "react-router-dom"
import { API_BASE_URL } from "../../config"
import { Package, Plus, Search, Eye, FileText, CheckCircle, X, Loader2, Trash2, Upload, Download } from "lucide-react"
import { buildApiUrl } from "../../config"
import { authFetch } from "../../utils/api"
import Pagination from "../../components/ui/Pagination"

function PurchaseOrdersPage() {
  const navigate = useNavigate()
  const [purchaseOrders, setPurchaseOrders] = useState([])
  const [vendors, setVendors] = useState([])
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [searchTerm, setSearchTerm] = useState("")
  const [statusFilter, setStatusFilter] = useState("all")
  const [showModal, setShowModal] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [importing, setImporting] = useState(false)
  const [currentPage, setCurrentPage] = useState(1)
  const [recordsPerPage, setRecordsPerPage] = useState(100)
  const [totalPOs, setTotalPOs] = useState(0)
  const totalPages = Math.ceil(totalPOs / recordsPerPage)
  const fileInputRef = useRef(null)
  const [formData, setFormData] = useState({
    vendor_id: "",
    po_number: "",
    order_date: new Date().toISOString().split("T")[0],
    expected_delivery: "",
    items: [{ item_id: "", description: "", quantity: 1, rate: 0, tax_rate: 18 }],
    shipping_address: "",
    notes: "",
  })

  useEffect(() => {
    fetchPurchaseOrders(currentPage, recordsPerPage, searchTerm, statusFilter)
    fetchVendors()
    fetchItems()
  }, [currentPage, recordsPerPage, searchTerm, statusFilter])

  const fetchPurchaseOrders = async (page = 1, page_size = 100, search = "", status = "all") => {
    setLoading(true)
    try {
      const params = new URLSearchParams({
        page: page.toString(),
        page_size: page_size.toString(),
        ...(search ? { search } : {}),
        ...(status && status !== "all" ? { status } : {}),
      })
      const response = await authFetch(buildApiUrl(`/finance/purchase-orders/?${params}`))
      if (response.ok) {
        const data = await response.json()
        setPurchaseOrders(data.items || [])
        setTotalPOs(data.total || 0)
      }
    } catch (error) {
      console.error("Error fetching purchase orders:", error)
    } finally {
      setLoading(false)
    }
  }

  const fetchVendors = async () => {
    try {
      const response = await authFetch(buildApiUrl(`/finance/vendors/`))
      if (response.ok) {
        const data = await response.json()
        setVendors(data)
      }
    } catch (error) {
      console.error("Error fetching vendors:", error)
    }
  }

  const fetchItems = async () => {
    try {
      const response = await authFetch(buildApiUrl(`/finance/items/`))
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
      const poData = {
        ...formData,
        items: formData.items.map((item) => ({
          ...item,
          amount: item.quantity * item.rate,
          tax_amount: (item.quantity * item.rate * item.tax_rate) / 100,
        })),
      }

      const response = await authFetch(buildApiUrl(`/finance/purchase-orders/`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(poData),
      })

      if (response.ok) {
        fetchPurchaseOrders()
        handleCloseModal()
      }
    } catch (error) {
      console.error("Error creating purchase order:", error)
    }
  }

  const handleItemChange = (index, field, value) => {
    const newItems = [...formData.items]
    
    // Handle numeric fields - ensure they are valid numbers
    if (field === "quantity" || field === "rate" || field === "tax_rate") {
      const numValue = parseFloat(value)
      newItems[index][field] = isNaN(numValue) ? 0 : numValue
    } else {
      newItems[index][field] = value
    }

    if (field === "item_id" && value) {
      const selectedItem = items.find((i) => i._id === value)
      if (selectedItem) {
        newItems[index].description = selectedItem.name
        newItems[index].rate = parseFloat(selectedItem.purchase_price) || parseFloat(selectedItem.selling_price) || 0
        newItems[index].tax_rate = parseFloat(selectedItem.tax_rate) || 18
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
    setFormData({
      vendor_id: "",
      po_number: "",
      order_date: new Date().toISOString().split("T")[0],
      expected_delivery: "",
      items: [{ item_id: "", description: "", quantity: 1, rate: 0, tax_rate: 18 }],
      shipping_address: "",
      notes: "",
    })
  }

  const getStatusBadge = (status) => {
    const badgeStyles = {
      approved: { backgroundColor: "#d1fae5", color: "#065f46" },
      pending: { backgroundColor: "#fef3c7", color: "#92400e" },
      received: { backgroundColor: "#dbeafe", color: "#1e40af" },
      cancelled: { backgroundColor: "#fee2e2", color: "#991b1b" },
      draft: { backgroundColor: "#e5e7eb", color: "#6b7280" },
    }

    return (
      <span style={{ ...styles.statusBadge, ...badgeStyles[status] }}>
        {status ? status.charAt(0).toUpperCase() + status.slice(1) : ""}
      </span>
    )
  }

  const formatCurrency = (amount) => {
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency: "INR",
      maximumFractionDigits: 0,
    }).format(amount || 0)
  }

  const calculateSubtotal = () => {
    return formData.items.reduce((sum, item) => {
      const qty = parseFloat(item.quantity) || 0
      const rate = parseFloat(item.rate) || 0
      return sum + (qty * rate)
    }, 0)
  }

  const calculateTax = () => {
    return formData.items.reduce((sum, item) => {
      const qty = parseFloat(item.quantity) || 0
      const rate = parseFloat(item.rate) || 0
      const taxRate = parseFloat(item.tax_rate) || 0
      return sum + ((qty * rate * taxRate) / 100)
    }, 0)
  }


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

  const handlePageChange = (page) => {
    setCurrentPage(page)
  }

  // Export purchase orders to CSV
  const handleExportCSV = async () => {
    setExporting(true)
    try {
      const response = await authFetch(buildApiUrl(`/finance/purchase-orders/export/csv`))
      if (response.ok) {
        const blob = await response.blob()
        const url = window.URL.createObjectURL(blob)
        const a = document.createElement("a")
        a.href = url
        a.download = `purchase_orders_export_${new Date().toISOString().split("T")[0]}.csv`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        window.URL.revokeObjectURL(url)
      }
    } catch (error) {
      console.error("Error exporting purchase orders:", error)
      alert("Failed to export purchase orders")
    } finally {
      setExporting(false)
    }
  }

  // Import purchase orders from CSV
  const handleImportCSV = async (event) => {
    const file = event.target.files?.[0]
    if (!file) return

    setImporting(true)
    const formDataUpload = new FormData()
    formDataUpload.append("file", file)

    try {
      const response = await authFetch(buildApiUrl(`/finance/purchase-orders/import/csv`), {
        method: "POST",
        body: formDataUpload,
      })

      if (response.ok) {
        const result = await response.json()
        alert(`Successfully imported ${result.imported} purchase orders`)
        fetchPurchaseOrders()
      } else {
        const error = await response.json()
        alert(`Import failed: ${error.detail}`)
      }
    } catch (error) {
      console.error("Error importing purchase orders:", error)
      alert("Failed to import purchase orders")
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
          <h2 style={styles.title}>Purchase Orders</h2>
          <p style={styles.subtitle}>Manage purchase orders to vendors</p>
        </div>
        <div style={{ display: "flex", gap: "0.75rem" }}>
          <button 
            style={styles.btnSecondary} 
            onClick={() => navigate("/admin/finance/purchase-orders/import")}
          >
            <Upload style={{ width: "16px", height: "16px" }} />
            Import CSV
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
            + Create PO
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
            placeholder="Search by PO #, vendor..."
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
          <option value="pending">Pending Approval</option>
          <option value="approved">Approved</option>
          <option value="received">Received</option>
          <option value="cancelled">Cancelled</option>
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
          <span>Total: <strong>{purchaseOrders.length}</strong></span>
          <span>Draft: <strong>{purchaseOrders.filter(po => po.status === "draft").length}</strong></span>
          <span>Approved: <strong>{purchaseOrders.filter(po => po.status === "approved").length}</strong></span>
          <span>Received: <strong>{purchaseOrders.filter(po => po.status === "received").length}</strong></span>
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
            <p style={{ color: "#6b7280" }}>Loading purchase orders...</p>
          </div>
        </div>
      ) : (
        <div style={styles.tableContainer}>
          <table style={styles.table}>
            <thead style={styles.thead}>
              <tr>
                <th style={styles.th}>PO #</th>
                <th style={styles.th}>Vendor</th>
                <th style={styles.th}>Order Date</th>
                <th style={styles.th}>Expected Delivery</th>
                <th style={styles.th}>Amount</th>
                <th style={styles.th}>Status</th>
                <th style={styles.th}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {purchaseOrders.map((po) => (
                <tr key={po._id} style={styles.tr}>
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
                      {po.po_number}
                    </code>
                  </td>
                  <td style={styles.td}>{po.vendor_name || "N/A"}</td>
                  <td style={styles.td}>{new Date(po.order_date).toLocaleDateString("en-IN")}</td>
                  <td style={styles.td}>
                    {po.expected_delivery ? new Date(po.expected_delivery).toLocaleDateString("en-IN") : "-"}
                  </td>
                  <td style={{ ...styles.td, fontWeight: "600" }}>{formatCurrency(po.total_amount)}</td>
                  <td style={styles.td}>{getStatusBadge(po.status)}</td>
                  <td style={styles.td}>
                    <div style={styles.actionButtons}>
                      <button style={styles.btnEdit}>
                        <Eye style={{ width: "16px", height: "16px" }} />
                      </button>
                      <button style={styles.btnEdit}>
                        <FileText style={{ width: "16px", height: "16px" }} />
                      </button>
                      <button style={styles.btnEdit}>
                        <CheckCircle style={{ width: "16px", height: "16px" }} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {purchaseOrders.length === 0 && (
                <tr>
                  <td colSpan={7} style={styles.emptyState}>
                    <Package style={{ width: "48px", height: "48px", margin: "0 auto 1rem", opacity: 0.5 }} />
                    <p>No purchase orders found. Click "Create PO" to add one.</p>
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
        totalRecords={totalPOs}
        pageSize={recordsPerPage}
        onPageChange={handlePageChange}
        onPageSizeChange={handleRecordsPerPageChange}
        loading={loading}
      />

      {showModal && (
        <div style={styles.modal} onClick={handleCloseModal}>
          <div style={styles.modalContent} onClick={(e) => e.stopPropagation()}>
            <div style={styles.modalHeader}>
              <h3 style={styles.modalTitle}>Create Purchase Order</h3>
              <button onClick={handleCloseModal} style={styles.closeBtn}>
                ×
              </button>
            </div>

            <div style={{ ...styles.modalBody, overflow: "auto", flex: 1 }}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem", marginBottom: "1rem" }}>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Vendor *</label>
                  <select
                    style={styles.select}
                    value={formData.vendor_id}
                    onChange={(e) => setFormData({ ...formData, vendor_id: e.target.value })}
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
                  <label style={styles.label}>PO Number</label>
                  <input
                    style={styles.input}
                    type="text"
                    value={formData.po_number}
                    onChange={(e) => setFormData({ ...formData, po_number: e.target.value })}
                    placeholder="Auto-generated if empty"
                  />
                </div>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Order Date</label>
                  <input
                    style={styles.input}
                    type="date"
                    value={formData.order_date}
                    onChange={(e) => setFormData({ ...formData, order_date: e.target.value })}
                  />
                </div>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Expected Delivery</label>
                  <input
                    style={styles.input}
                    type="date"
                    value={formData.expected_delivery}
                    onChange={(e) => setFormData({ ...formData, expected_delivery: e.target.value })}
                  />
                </div>
              </div>

              <div style={{ marginBottom: "1.5rem" }}>
                <label style={styles.label}>Shipping Address</label>
                <textarea
                  style={{ ...styles.input, minHeight: "80px", resize: "vertical" }}
                  value={formData.shipping_address}
                  onChange={(e) => setFormData({ ...formData, shipping_address: e.target.value })}
                  placeholder="Delivery address..."
                />
              </div>

              <div style={styles.section}>
                <h4 style={styles.sectionTitle}>Line Items</h4>
                <div style={{ overflowX: "auto" }}>
                  <table style={{ width: "100%", fontSize: "0.9rem" }}>
                    <thead style={styles.thead}>
                      <tr>
                        <th style={styles.th}>Item</th>
                        <th style={styles.th}>Description</th>
                        <th style={{ ...styles.th, width: "5rem" }}>Qty</th>
                        <th style={{ ...styles.th, width: "7rem" }}>Rate</th>
                        <th style={{ ...styles.th, width: "5rem" }}>Tax %</th>
                        <th style={{ ...styles.th, width: "7rem", textAlign: "right" }}>Amount</th>
                        <th style={{ width: "2rem" }}></th>
                      </tr>
                    </thead>
                    <tbody>
                      {formData.items.map((item, index) => (
                        <tr key={index} style={styles.tr}>
                          <td style={styles.td}>
                            <select
                              style={styles.select}
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
                              style={styles.input}
                              type="text"
                              value={item.description}
                              onChange={(e) => handleItemChange(index, "description", e.target.value)}
                              placeholder="Description"
                            />
                          </td>
                          <td style={styles.td}>
                            <input
                              style={styles.input}
                              type="number"
                              value={item.quantity}
                              onChange={(e) => handleItemChange(index, "quantity", e.target.value)}
                              min={1}
                            />
                          </td>
                          <td style={styles.td}>
                            <input
                              style={styles.input}
                              type="number"
                              value={item.rate}
                              onChange={(e) => handleItemChange(index, "rate", e.target.value)}
                              min={0}
                            />
                          </td>
                          <td style={styles.td}>
                            <select
                              style={styles.select}
                              value={String(item.tax_rate || 18)}
                              onChange={(e) => handleItemChange(index, "tax_rate", e.target.value)}
                            >
                              <option value="0">0%</option>
                              <option value="5">5%</option>
                              <option value="12">12%</option>
                              <option value="18">18%</option>
                              <option value="28">28%</option>
                            </select>
                          </td>
                          <td style={{ ...styles.td, textAlign: "right", fontWeight: "600" }}>
                            {formatCurrency((parseFloat(item.quantity) || 0) * (parseFloat(item.rate) || 0))}
                          </td>
                          <td style={styles.td}>
                            <button
                              type="button"
                              onClick={() => removeLineItem(index)}
                              style={styles.btnDelete}
                            >
                              <Trash2 style={{ width: "16px", height: "16px" }} />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <button
                  type="button"
                  onClick={addLineItem}
                  style={{ ...styles.btnPrimary, marginTop: "1rem" }}
                >
                  + Add Line Item
                </button>
              </div>

              <div
                style={{
                  backgroundColor: "#f9fafb",
                  borderRadius: "0.5rem",
                  padding: "1rem",
                  marginBottom: "1.5rem",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.5rem" }}>
                  <span style={{ fontSize: "0.9rem", color: "#6b7280" }}>Subtotal:</span>
                  <span style={{ fontSize: "0.9rem", fontWeight: "600" }}>{formatCurrency(calculateSubtotal())}</span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.5rem" }}>
                  <span style={{ fontSize: "0.9rem", color: "#6b7280" }}>Tax:</span>
                  <span style={{ fontSize: "0.9rem", fontWeight: "600" }}>{formatCurrency(calculateTax())}</span>
                </div>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    borderTop: "1px solid #e5e7eb",
                    paddingTop: "0.5rem",
                  }}
                >
                  <span style={{ fontSize: "1.125rem", fontWeight: "600" }}>Grand Total:</span>
                  <span style={{ fontSize: "1.125rem", fontWeight: "600", color: "#0d6efd" }}>
                    {formatCurrency(calculateSubtotal() + calculateTax())}
                  </span>
                </div>
              </div>

              <div style={{ marginBottom: "1.5rem" }}>
                <label style={styles.label}>Notes</label>
                <textarea
                  style={{ ...styles.input, minHeight: "80px", resize: "vertical" }}
                  value={formData.notes}
                  onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
                  placeholder="Internal notes..."
                />
              </div>
            </div>

            <div style={styles.modalFooter}>
              <button style={styles.btnCancel} type="button" onClick={handleCloseModal}>
                Cancel
              </button>
              <button style={styles.btnSave} onClick={handleSubmit}>
                Create Purchase Order
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
  statusBadge: {
    display: "inline-block",
    padding: "0.375rem 0.75rem",
    borderRadius: "0.375rem",
    fontSize: "0.8rem",
    fontWeight: "600",
    textTransform: "capitalize",
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

export default PurchaseOrdersPage