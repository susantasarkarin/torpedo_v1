"use client"

import { useState, useEffect, useRef } from "react"
import { API_BASE_URL } from "../../config"
import { Package, Search, Pencil, Trash2, Loader2, Wrench, Upload, Download } from "lucide-react"

function ItemsPage() {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [searchTerm, setSearchTerm] = useState("")
  const [showModal, setShowModal] = useState(false)
  const [editingItem, setEditingItem] = useState(null)
  const [exporting, setExporting] = useState(false)
  const [importing, setImporting] = useState(false)
  const fileInputRef = useRef(null)
  const [formData, setFormData] = useState({
    name: "",
    sku: "",
    description: "",
    type: "goods",
    unit: "nos",
    selling_price: 0,
    purchase_price: 0,
    tax_rate: 18,
    hsn_sac_code: "",
    track_inventory: true,
    stock_quantity: 0,
    low_stock_threshold: 10,
  })

  useEffect(() => {
    fetchItems()
  }, [])

  const fetchItems = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/finance/finance/items/`)
      if (response.ok) {
        const data = await response.json()
        setItems(data)
      }
    } catch (error) {
      console.error("Error fetching items:", error)
    } finally {
      setLoading(false)
    }
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    try {
      const url = editingItem
        ? `${API_BASE_URL}/finance/finance/items/${editingItem._id}`
        : `${API_BASE_URL}/finance/finance/items/`

      const method = editingItem ? "PUT" : "POST"

      const response = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(formData),
      })

      if (response.ok) {
        fetchItems()
        handleCloseModal()
      }
    } catch (error) {
      console.error("Error saving item:", error)
    }
  }

  const handleDelete = async (id) => {
    if (!window.confirm("Are you sure you want to delete this item?")) return

    try {
      const response = await fetch(`${API_BASE_URL}/finance/finance/items/${id}`, {
        method: "DELETE",
      })
      if (response.ok) {
        fetchItems()
      }
    } catch (error) {
      console.error("Error deleting item:", error)
    }
  }

  const handleEdit = (item) => {
    setEditingItem(item)
    setFormData({
      name: item.name || "",
      sku: item.sku || "",
      description: item.description || "",
      type: item.type || "goods",
      unit: item.unit || "nos",
      selling_price: item.selling_price || 0,
      purchase_price: item.purchase_price || 0,
      tax_rate: item.tax_rate || 18,
      hsn_sac_code: item.hsn_sac_code || "",
      track_inventory: item.track_inventory ?? true,
      stock_quantity: item.stock_quantity || 0,
      low_stock_threshold: item.low_stock_threshold || 10,
    })
    setShowModal(true)
  }

  const handleCloseModal = () => {
    setShowModal(false)
    setEditingItem(null)
    setFormData({
      name: "",
      sku: "",
      description: "",
      type: "goods",
      unit: "nos",
      selling_price: 0,
      purchase_price: 0,
      tax_rate: 18,
      hsn_sac_code: "",
      track_inventory: true,
      stock_quantity: 0,
      low_stock_threshold: 10,
    })
  }

  const filteredItems = items.filter(
    (item) =>
      item.name?.toLowerCase().includes(searchTerm.toLowerCase()) ||
      item.sku?.toLowerCase().includes(searchTerm.toLowerCase()),
  )

  const formatCurrency = (amount) => {
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency: "INR",
      maximumFractionDigits: 0,
    }).format(amount || 0)
  }

  const getStockStatus = (item) => {
    if (!item.track_inventory) return "not-tracked"
    if (item.stock_quantity <= 0) return "out-of-stock"
    if (item.stock_quantity <= item.low_stock_threshold) return "low-stock"
    return "in-stock"
  }

  const getStockBadge = (item) => {
    const status = getStockStatus(item)
    const badgeStyles = {
      "in-stock": { backgroundColor: "#d1fae5", color: "#065f46" },
      "low-stock": { backgroundColor: "#fef3c7", color: "#92400e" },
      "out-of-stock": { backgroundColor: "#fee2e2", color: "#991b1b" },
      "not-tracked": { backgroundColor: "#e5e7eb", color: "#6b7280" },
    }

    return (
      <span style={{ ...styles.statusBadge, ...badgeStyles[status] }}>
        {status === "in-stock"
          ? "In Stock"
          : status === "low-stock"
            ? "Low Stock"
            : status === "out-of-stock"
              ? "Out of Stock"
              : "N/A"}
      </span>
    )
  }

  // Export items to CSV
  const handleExportCSV = async () => {
    setExporting(true)
    try {
      const response = await fetch(`${API_BASE_URL}/finance/finance/items/export/csv`)
      if (response.ok) {
        const blob = await response.blob()
        const url = window.URL.createObjectURL(blob)
        const a = document.createElement("a")
        a.href = url
        a.download = `items_export_${new Date().toISOString().split("T")[0]}.csv`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        window.URL.revokeObjectURL(url)
      }
    } catch (error) {
      console.error("Error exporting items:", error)
      alert("Failed to export items")
    } finally {
      setExporting(false)
    }
  }

  // Import items from CSV
  const handleImportCSV = async (event) => {
    const file = event.target.files?.[0]
    if (!file) return

    setImporting(true)
    const formDataUpload = new FormData()
    formDataUpload.append("file", file)

    try {
      const response = await fetch(`${API_BASE_URL}/finance/finance/items/import/csv`, {
        method: "POST",
        body: formDataUpload,
      })

      if (response.ok) {
        const result = await response.json()
        let message = `Successfully imported ${result.imported} items`
        if (result.errors && result.errors.length > 0) {
          message += `\n\nWarnings:\n${result.errors.slice(0, 5).join("\n")}`
          if (result.errors.length > 5) {
            message += `\n... and ${result.errors.length - 5} more`
          }
        }
        alert(message)
        fetchItems()
      } else {
        const error = await response.json()
        alert(`Import failed: ${error.detail}`)
      }
    } catch (error) {
      console.error("Error importing items:", error)
      alert("Failed to import items")
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
          <h2 style={styles.title}>Estimates</h2>
          <p style={styles.subtitle}>Manage products and services for estimates</p>
        </div>
        <div style={{ display: "flex", gap: "0.75rem" }}>
          <input
            type="file"
            ref={fileInputRef}
            accept=".csv"
            onChange={handleImportCSV}
            style={{ display: "none" }}
          />
          <button 
            style={styles.btnSecondary} 
            onClick={() => fileInputRef.current?.click()}
            disabled={importing}
          >
            <Upload style={{ width: "16px", height: "16px", marginRight: "0.5rem" }} />
            {importing ? "Importing..." : "Import CSV"}
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
            + Add Item
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
            placeholder="Search items..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        </div>
        <div style={styles.stats}>
          <span>
            Total: <strong>{filteredItems.length}</strong>
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
            <p style={{ color: "#6b7280" }}>Loading items...</p>
          </div>
        </div>
      ) : (
        <div style={styles.tableContainer}>
          <table style={styles.table}>
            <thead style={styles.thead}>
              <tr>
                <th style={styles.th}>Name</th>
                <th style={styles.th}>SKU</th>
                <th style={styles.th}>Type</th>
                <th style={styles.th}>Selling Price</th>
                <th style={styles.th}>Stock</th>
                <th style={styles.th}>Status</th>
                <th style={styles.th}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredItems.map((item) => (
                <tr key={item._id} style={styles.tr}>
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
                        {item.type === "goods" ? (
                          <Package style={{ width: "16px", height: "16px", color: "#6b7280" }} />
                        ) : (
                          <Wrench style={{ width: "16px", height: "16px", color: "#6b7280" }} />
                        )}
                      </div>
                      <span style={{ fontWeight: "500" }}>{item.name}</span>
                    </div>
                  </td>
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
                      {item.sku || "-"}
                    </code>
                  </td>
                  <td style={styles.td}>
                    <span
                      style={{
                        ...styles.statusBadge,
                        ...(item.type === "goods"
                          ? { backgroundColor: "#dbeafe", color: "#1e40af" }
                          : { backgroundColor: "#e9d5ff", color: "#6b21a8" }),
                      }}
                    >
                      {item.type === "goods" ? "Goods" : "Service"}
                    </span>
                  </td>
                  <td style={{ ...styles.td, fontWeight: "600" }}>{formatCurrency(item.selling_price)}</td>
                  <td style={styles.td}>{item.track_inventory ? item.stock_quantity : "-"}</td>
                  <td style={styles.td}>{getStockBadge(item)}</td>
                  <td style={styles.td}>
                    <div style={styles.actionButtons}>
                      <button style={styles.btnEdit} onClick={() => handleEdit(item)}>
                        <Pencil style={{ width: "16px", height: "16px" }} />
                      </button>
                      <button style={styles.btnDelete} onClick={() => handleDelete(item._id)}>
                        <Trash2 style={{ width: "16px", height: "16px" }} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {filteredItems.length === 0 && (
                <tr>
                  <td colSpan={7} style={styles.emptyState}>
                    <Package style={{ width: "48px", height: "48px", margin: "0 auto 1rem", opacity: 0.5 }} />
                    <p>No items found. Click "Add Item" to create one.</p>
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
              <h3 style={styles.modalTitle}>{editingItem ? "Edit Item" : "Add Item"}</h3>
              <button style={styles.closeBtn} onClick={handleCloseModal}>
                ×
              </button>
            </div>

            <form onSubmit={handleSubmit} style={{ ...styles.modalBody, overflow: "auto", flex: 1 }}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem", marginBottom: "1rem" }}>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Item Name *</label>
                  <input
                    style={styles.input}
                    type="text"
                    value={formData.name}
                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                    required
                    placeholder="Enter item name"
                  />
                </div>
                <div style={styles.formGroup}>
                  <label style={styles.label}>SKU</label>
                  <input
                    style={styles.input}
                    type="text"
                    value={formData.sku}
                    onChange={(e) => setFormData({ ...formData, sku: e.target.value })}
                    placeholder="SKU-001"
                  />
                </div>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Type</label>
                  <select
                    style={styles.select}
                    value={formData.type}
                    onChange={(e) => setFormData({ ...formData, type: e.target.value })}
                  >
                    <option value="goods">Goods</option>
                    <option value="service">Service</option>
                  </select>
                </div>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Unit</label>
                  <select
                    style={styles.select}
                    value={formData.unit}
                    onChange={(e) => setFormData({ ...formData, unit: e.target.value })}
                  >
                    <option value="nos">Nos</option>
                    <option value="pcs">Pieces</option>
                    <option value="kg">Kilograms</option>
                    <option value="l">Liters</option>
                    <option value="hrs">Hours</option>
                    <option value="days">Days</option>
                  </select>
                </div>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Selling Price (₹)</label>
                  <input
                    style={styles.input}
                    type="number"
                    value={formData.selling_price}
                    onChange={(e) => setFormData({ ...formData, selling_price: Number.parseFloat(e.target.value) })}
                    min={0}
                    step={0.01}
                  />
                </div>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Purchase Price (₹)</label>
                  <input
                    style={styles.input}
                    type="number"
                    value={formData.purchase_price}
                    onChange={(e) => setFormData({ ...formData, purchase_price: Number.parseFloat(e.target.value) })}
                    min={0}
                    step={0.01}
                  />
                </div>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Tax Rate (%)</label>
                  <select
                    style={styles.select}
                    value={formData.tax_rate}
                    onChange={(e) => setFormData({ ...formData, tax_rate: Number.parseFloat(e.target.value) })}
                  >
                    <option value={0}>0%</option>
                    <option value={5}>5%</option>
                    <option value={12}>12%</option>
                    <option value={18}>18%</option>
                    <option value={28}>28%</option>
                  </select>
                </div>
                <div style={styles.formGroup}>
                  <label style={styles.label}>HSN/SAC Code</label>
                  <input
                    style={styles.input}
                    type="text"
                    value={formData.hsn_sac_code}
                    onChange={(e) => setFormData({ ...formData, hsn_sac_code: e.target.value })}
                    placeholder="9954"
                  />
                </div>
              </div>

              <div style={{ marginBottom: "1.5rem" }}>
                <label style={styles.label}>Description</label>
                <textarea
                  style={{ ...styles.input, minHeight: "80px", resize: "vertical" }}
                  value={formData.description}
                  onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                  placeholder="Item description..."
                />
              </div>

              <div style={styles.section}>
                <h4 style={styles.sectionTitle}>Inventory</h4>
                <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "1rem" }}>
                  <input
                    type="checkbox"
                    id="track_inventory"
                    checked={formData.track_inventory}
                    onChange={(e) => setFormData({ ...formData, track_inventory: e.target.checked })}
                    style={{ width: "16px", height: "16px" }}
                  />
                  <label htmlFor="track_inventory" style={{ fontSize: "0.875rem", color: "#374151" }}>
                    Track Inventory
                  </label>
                </div>
                {formData.track_inventory && (
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
                    <div style={styles.formGroup}>
                      <label style={styles.label}>Stock Quantity</label>
                      <input
                        style={styles.input}
                        type="number"
                        value={formData.stock_quantity}
                        onChange={(e) => setFormData({ ...formData, stock_quantity: Number.parseInt(e.target.value) })}
                        min={0}
                      />
                    </div>
                    <div style={styles.formGroup}>
                      <label style={styles.label}>Low Stock Threshold</label>
                      <input
                        style={styles.input}
                        type="number"
                        value={formData.low_stock_threshold}
                        onChange={(e) =>
                          setFormData({ ...formData, low_stock_threshold: Number.parseInt(e.target.value) })
                        }
                        min={0}
                      />
                    </div>
                  </div>
                )}
              </div>
            </form>

            <div style={styles.modalFooter}>
              <button style={styles.btnCancel} type="button" onClick={handleCloseModal}>
                Cancel
              </button>
              <button style={styles.btnSave} type="submit" onClick={handleSubmit}>
                {editingItem ? "Update Item" : "Create Item"}
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

export default ItemsPage
