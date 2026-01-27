"use client"

import { useState, useEffect } from "react"
import { useNavigate } from "react-router-dom"
import { API_BASE_URL } from "../../config"
import "./VendorPages.css"
import { buildApiUrl } from "../../config"

function VendorsPage() {
  const navigate = useNavigate()
  const [vendors, setVendors] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [search, setSearch] = useState("")
  const [currentPage, setCurrentPage] = useState(1)
  const [recordsPerPage, setRecordsPerPage] = useState(10)
  const [selectedIds, setSelectedIds] = useState([])
  const [showForm, setShowForm] = useState(false)
  const [editingVendor, setEditingVendor] = useState(null)

  const emptyForm = {
    name: "",
    email: "",
    contact_person: "",
    phone: "",
    type: "panel",
    status: "active",
    address: ""
  }
  const [formData, setFormData] = useState(emptyForm)

  useEffect(() => {
    fetchVendors()
  }, [])

  const fetchVendors = async () => {
    try {
      setLoading(true)
      
      // Fetch unified vendors
      const res = await fetch(buildApiUrl(`/vendors/unified`))
      
      if (res.ok) {
        const data = await res.json()
        setVendors(data || [])
      } else {
        // Demo data
        setVendors([
          { _id: "1", vendor_name: "Panel Vendor A", email: "contact@panela.com", contact_person: "John Smith", source: "panel", status: "active" },
          { _id: "2", vendor_name: "Billing Vendor B", email: "info@billingb.com", contact_person: "Sarah Johnson", source: "billing", status: "active" },
          { _id: "3", vendor_name: "Panel Vendor C", email: "support@panelc.com", contact_person: "Mike Davis", source: "panel", status: "inactive" },
        ])
      }
    } catch (err) {
      console.error("Error fetching vendors:", err)
      // Demo data
      setVendors([
        { _id: "1", vendor_name: "Panel Vendor A", email: "contact@panela.com", contact_person: "John Smith", source: "panel", status: "active" },
        { _id: "2", vendor_name: "Billing Vendor B", email: "info@billingb.com", contact_person: "Sarah Johnson", source: "billing", status: "active" },
        { _id: "3", vendor_name: "Panel Vendor C", email: "support@panelc.com", contact_person: "Mike Davis", source: "panel", status: "inactive" },
      ])
    } finally {
      setLoading(false)
    }
  }

  // Filter vendors
  const filteredVendors = vendors.filter(vendor => {
    const searchLower = search.toLowerCase()
    return (
      (vendor.vendor_name || vendor.name || "").toLowerCase().includes(searchLower) ||
      (vendor.email || "").toLowerCase().includes(searchLower) ||
      (vendor.contact_person || "").toLowerCase().includes(searchLower)
    )
  })

  // Pagination
  const totalPages = Math.ceil(filteredVendors.length / recordsPerPage)
  const startIndex = (currentPage - 1) * recordsPerPage
  const paginatedVendors = filteredVendors.slice(startIndex, startIndex + recordsPerPage)

  // Stats
  const stats = {
    total: vendors.length,
    panel: vendors.filter(v => v.source === "panel").length,
    billing: vendors.filter(v => v.source === "billing").length,
    active: vendors.filter(v => v.status === "active").length
  }

  // Select handlers
  const toggleSelectAll = () => {
    if (selectedIds.length === paginatedVendors.length) {
      setSelectedIds([])
    } else {
      setSelectedIds(paginatedVendors.map(v => v._id))
    }
  }

  const toggleSelect = (id) => {
    if (selectedIds.includes(id)) {
      setSelectedIds(selectedIds.filter(i => i !== id))
    } else {
      setSelectedIds([...selectedIds, id])
    }
  }

  const getTypeBadge = (type) => {
    const styles = {
      panel: { backgroundColor: "#dbeafe", color: "#1e40af" },
      billing: { backgroundColor: "#fef3c7", color: "#92400e" }
    }
    return styles[type] || { backgroundColor: "#f3f4f6", color: "#374151" }
  }

  const getStatusBadge = (status) => {
    const styles = {
      active: { backgroundColor: "#dcfce7", color: "#166534" },
      inactive: { backgroundColor: "#fee2e2", color: "#991b1b" }
    }
    return styles[status] || { backgroundColor: "#f3f4f6", color: "#374151" }
  }

  const openCreate = () => {
    setEditingVendor(null)
    setFormData(emptyForm)
    setShowForm(true)
  }

  const openEdit = (vendor) => {
    setEditingVendor(vendor)
    setFormData({
      name: vendor.vendor_name || vendor.name || "",
      email: vendor.email || "",
      contact_person: vendor.contact_person || "",
      phone: vendor.phone || "",
      type: vendor.source || "panel",
      status: vendor.status || "active",
      address: vendor.address || ""
    })
    setShowForm(true)
  }

  const deleteVendor = async (id) => {
    if (!window.confirm("Are you sure you want to delete this vendor?")) return
    
    try {
      await fetch(buildApiUrl(`/vendors/${id}`), { method: "DELETE" })
      setVendors(vendors.filter(v => v._id !== id))
    } catch (err) {
      console.error("Error deleting vendor:", err)
    }
  }

  if (loading) {
    return (
      <div className="vendor-page">
        <div className="loading-spinner">Loading vendors...</div>
      </div>
    )
  }

  return (
    <div className="vendor-page">
      {/* Page Header */}
      <div className="page-header">
        <div className="header-left">
          <h1>Vendors</h1>
          <p className="subtitle">Manage your panel and billing vendors</p>
        </div>
        <div className="header-actions">
          {selectedIds.length > 0 && (
            <button className="btn btn-danger" onClick={() => {/* bulk delete */}}>
              🗑️ Delete ({selectedIds.length})
            </button>
          )}
          <button className="btn btn-outline" onClick={() => {/* import */}}>
            📥 Import CSV
          </button>
          <button className="btn btn-primary" onClick={openCreate}>
            + Add New Vendor
          </button>
        </div>
      </div>

      {error && <div className="error-alert">{error}</div>}

      {/* Stats Row */}
      <div className="stats-row">
        <div className="stat-card primary">
          <div className="stat-value">{stats.total}</div>
          <div className="stat-label">Total Vendors</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{stats.panel}</div>
          <div className="stat-label">🎯 Panel</div>
        </div>
        <div className="stat-card warning">
          <div className="stat-value">{stats.billing}</div>
          <div className="stat-label">💰 Billing</div>
        </div>
        <div className="stat-card success">
          <div className="stat-value">{stats.active}</div>
          <div className="stat-label">✅ Active</div>
        </div>
      </div>

      {/* Filters Bar */}
      <div className="filters-bar">
        <input
          className="search-input"
          type="text"
          placeholder="Search vendors by name, email, contact..."
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

      {/* Vendors Table */}
      <div className="table-container">
        <table className="data-table">
          <thead>
            <tr>
              <th className="checkbox-col">
                <input
                  type="checkbox"
                  checked={paginatedVendors.length > 0 && paginatedVendors.every(v => selectedIds.includes(v._id))}
                  onChange={toggleSelectAll}
                />
              </th>
              <th>Name</th>
              <th>Email</th>
              <th>Contact Person</th>
              <th>Type</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {paginatedVendors.length === 0 ? (
              <tr>
                <td colSpan="7" style={{ textAlign: "center", padding: "48px" }}>
                  No vendors found
                </td>
              </tr>
            ) : (
              paginatedVendors.map(vendor => (
                <tr key={vendor._id} className={selectedIds.includes(vendor._id) ? "selected" : ""}>
                  <td className="checkbox-col">
                    <input
                      type="checkbox"
                      checked={selectedIds.includes(vendor._id)}
                      onChange={() => toggleSelect(vendor._id)}
                    />
                  </td>
                  <td className="name-cell">
                    <span className="name-link" onClick={() => openEdit(vendor)}>
                      {vendor.vendor_name || vendor.name || "-"}
                    </span>
                  </td>
                  <td>{vendor.email || "-"}</td>
                  <td>{vendor.contact_person || "-"}</td>
                  <td>
                    <span className="stage-badge" style={getTypeBadge(vendor.source)}>
                      {vendor.source === "panel" ? "🎯 Panel" : "💰 Billing"}
                    </span>
                  </td>
                  <td>
                    <span className="status-badge" style={getStatusBadge(vendor.status)}>
                      {vendor.status || "Active"}
                    </span>
                  </td>
                  <td>
                    <div className="actions-cell">
                      <button className="action-btn" title="View">→</button>
                      <button className="action-btn edit" onClick={() => openEdit(vendor)} title="Edit">✏️</button>
                      <button className="action-btn delete" onClick={() => deleteVendor(vendor._id)} title="Delete">🗑️</button>
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
            <h2 style={{ marginBottom: "20px" }}>{editingVendor ? "Edit Vendor" : "Add New Vendor"}</h2>
            <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
              <input
                type="text"
                placeholder="Vendor Name"
                value={formData.name}
                onChange={e => setFormData({ ...formData, name: e.target.value })}
                style={{ padding: "10px", borderRadius: "8px", border: "1px solid #e5e7eb" }}
              />
              <input
                type="email"
                placeholder="Email"
                value={formData.email}
                onChange={e => setFormData({ ...formData, email: e.target.value })}
                style={{ padding: "10px", borderRadius: "8px", border: "1px solid #e5e7eb" }}
              />
              <input
                type="text"
                placeholder="Contact Person"
                value={formData.contact_person}
                onChange={e => setFormData({ ...formData, contact_person: e.target.value })}
                style={{ padding: "10px", borderRadius: "8px", border: "1px solid #e5e7eb" }}
              />
              <input
                type="text"
                placeholder="Phone"
                value={formData.phone}
                onChange={e => setFormData({ ...formData, phone: e.target.value })}
                style={{ padding: "10px", borderRadius: "8px", border: "1px solid #e5e7eb" }}
              />
              <select
                value={formData.type}
                onChange={e => setFormData({ ...formData, type: e.target.value })}
                style={{ padding: "10px", borderRadius: "8px", border: "1px solid #e5e7eb" }}
              >
                <option value="panel">Panel Vendor</option>
                <option value="billing">Billing Vendor</option>
              </select>
              <select
                value={formData.status}
                onChange={e => setFormData({ ...formData, status: e.target.value })}
                style={{ padding: "10px", borderRadius: "8px", border: "1px solid #e5e7eb" }}
              >
                <option value="active">Active</option>
                <option value="inactive">Inactive</option>
              </select>
              <div style={{ display: "flex", gap: "12px", marginTop: "8px" }}>
                <button className="btn btn-outline" onClick={() => setShowForm(false)}>
                  Cancel
                </button>
                <button className="btn btn-primary" onClick={() => setShowForm(false)}>
                  {editingVendor ? "Update" : "Create"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default VendorsPage
