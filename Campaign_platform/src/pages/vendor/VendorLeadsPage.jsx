"use client"

import { useState, useEffect } from "react"
import { useNavigate } from "react-router-dom"
import { API_BASE_URL } from "../../config"
import "../../styles/SalesPages.css"

function VendorLeadsPage() {
  const navigate = useNavigate()
  const [leads, setLeads] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [search, setSearch] = useState("")
  const [currentPage, setCurrentPage] = useState(1)
  const [recordsPerPage, setRecordsPerPage] = useState(10)
  const [selectedIds, setSelectedIds] = useState([])
  const [showForm, setShowForm] = useState(false)
  const [editingLead, setEditingLead] = useState(null)

  const emptyForm = {
    name: "",
    email: "",
    title: "",
    company: "",
    vendor_id: "",
    status: "new",
    notes: ""
  }
  const [formData, setFormData] = useState(emptyForm)

  useEffect(() => {
    fetchLeads()
  }, [])

  const fetchLeads = async () => {
    try {
      setLoading(true)
      const sessionId = localStorage.getItem("session_id")
      
      // Fetch vendor leads
      const res = await fetch(`${API_BASE_URL}/vendor-leads`, {
        headers: {
          "Content-Type": "application/json",
          Authorization: sessionId || ""
        }
      })
      
      if (res.ok) {
        const data = await res.json()
        setLeads(data.leads || data || [])
      } else {
        // Demo data for now
        setLeads([
          { _id: "1", name: "John Smith", email: "john.smith@example.com", title: "Procurement Manager", company: "ABC Corp", vendor_name: "Panel Vendor A", status: "new" },
          { _id: "2", name: "Sarah Johnson", email: "sarah.j@example.com", title: "Vendor Manager", company: "XYZ Inc", vendor_name: "Billing Vendor B", status: "contacted" },
          { _id: "3", name: "Mike Davis", email: "mike.d@example.com", title: "Supply Chain Director", company: "Tech Solutions", vendor_name: "Panel Vendor C", status: "qualified" },
        ])
      }
    } catch (err) {
      console.error("Error fetching vendor leads:", err)
      // Demo data
      setLeads([
        { _id: "1", name: "John Smith", email: "john.smith@example.com", title: "Procurement Manager", company: "ABC Corp", vendor_name: "Panel Vendor A", status: "new" },
        { _id: "2", name: "Sarah Johnson", email: "sarah.j@example.com", title: "Vendor Manager", company: "XYZ Inc", vendor_name: "Billing Vendor B", status: "contacted" },
        { _id: "3", name: "Mike Davis", email: "mike.d@example.com", title: "Supply Chain Director", company: "Tech Solutions", vendor_name: "Panel Vendor C", status: "qualified" },
      ])
    } finally {
      setLoading(false)
    }
  }

  // Filter leads
  const filteredLeads = leads.filter(lead => {
    const searchLower = search.toLowerCase()
    return (
      (lead.name || "").toLowerCase().includes(searchLower) ||
      (lead.email || "").toLowerCase().includes(searchLower) ||
      (lead.company || "").toLowerCase().includes(searchLower) ||
      (lead.title || "").toLowerCase().includes(searchLower)
    )
  })

  // Pagination
  const totalPages = Math.ceil(filteredLeads.length / recordsPerPage)
  const startIndex = (currentPage - 1) * recordsPerPage
  const paginatedLeads = filteredLeads.slice(startIndex, startIndex + recordsPerPage)

  // Stats
  const stats = {
    total: leads.length,
    new: leads.filter(l => l.status === "new").length,
    contacted: leads.filter(l => l.status === "contacted").length,
    qualified: leads.filter(l => l.status === "qualified").length
  }

  // Select handlers
  const toggleSelectAll = () => {
    if (selectedIds.length === paginatedLeads.length) {
      setSelectedIds([])
    } else {
      setSelectedIds(paginatedLeads.map(l => l._id))
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
      new: { backgroundColor: "#dbeafe", color: "#1e40af" },
      contacted: { backgroundColor: "#fef3c7", color: "#92400e" },
      qualified: { backgroundColor: "#dcfce7", color: "#166534" },
      rejected: { backgroundColor: "#fee2e2", color: "#991b1b" }
    }
    return styles[status] || { backgroundColor: "#f3f4f6", color: "#374151" }
  }

  const openCreate = () => {
    setEditingLead(null)
    setFormData(emptyForm)
    setShowForm(true)
  }

  const openEdit = (lead) => {
    setEditingLead(lead)
    setFormData({
      name: lead.name || "",
      email: lead.email || "",
      title: lead.title || "",
      company: lead.company || "",
      vendor_id: lead.vendor_id || "",
      status: lead.status || "new",
      notes: lead.notes || ""
    })
    setShowForm(true)
  }

  const deleteLead = async (id) => {
    if (!window.confirm("Are you sure you want to delete this lead?")) return
    
    try {
      const sessionId = localStorage.getItem("session_id")
      await fetch(`${API_BASE_URL}/vendor-leads/${id}`, {
        method: "DELETE",
        headers: { Authorization: sessionId || "" }
      })
      setLeads(leads.filter(l => l._id !== id))
    } catch (err) {
      console.error("Error deleting lead:", err)
    }
  }

  if (loading) {
    return (
      <div className="sales-page">
        <div className="loading-spinner">Loading vendor leads...</div>
      </div>
    )
  }

  return (
    <div className="sales-page">
      {/* Page Header */}
      <div className="page-header">
        <div className="header-left">
          <h1>Vendor Leads</h1>
          <p className="subtitle">Track and manage leads from your vendors</p>
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
            + Add New Lead
          </button>
        </div>
      </div>

      {error && <div className="error-alert">{error}</div>}

      {/* Stats Row */}
      <div className="stats-row">
        <div className="stat-card primary">
          <div className="stat-value">{stats.total}</div>
          <div className="stat-label">Total Leads</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{stats.new}</div>
          <div className="stat-label">🆕 New</div>
        </div>
        <div className="stat-card warning">
          <div className="stat-value">{stats.contacted}</div>
          <div className="stat-label">📞 Contacted</div>
        </div>
        <div className="stat-card success">
          <div className="stat-value">{stats.qualified}</div>
          <div className="stat-label">✅ Qualified</div>
        </div>
      </div>

      {/* Filters Bar */}
      <div className="filters-bar">
        <input
          className="search-input"
          type="text"
          placeholder="Search leads by name, company, title..."
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

      {/* Leads Table */}
      <div className="table-container">
        <table className="data-table">
          <thead>
            <tr>
              <th className="checkbox-col">
                <input
                  type="checkbox"
                  checked={paginatedLeads.length > 0 && paginatedLeads.every(l => selectedIds.includes(l._id))}
                  onChange={toggleSelectAll}
                />
              </th>
              <th>Name</th>
              <th>Email</th>
              <th>Title</th>
              <th>Company</th>
              <th>Vendor</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {paginatedLeads.length === 0 ? (
              <tr>
                <td colSpan="8" style={{ textAlign: "center", padding: "48px" }}>
                  No vendor leads found
                </td>
              </tr>
            ) : (
              paginatedLeads.map(lead => (
                <tr key={lead._id} className={selectedIds.includes(lead._id) ? "selected" : ""}>
                  <td className="checkbox-col">
                    <input
                      type="checkbox"
                      checked={selectedIds.includes(lead._id)}
                      onChange={() => toggleSelect(lead._id)}
                    />
                  </td>
                  <td className="name-cell">
                    <span className="name-link" onClick={() => openEdit(lead)}>
                      {lead.name || "-"}
                    </span>
                  </td>
                  <td>{lead.email || "-"}</td>
                  <td>{lead.title || "-"}</td>
                  <td>{lead.company || "-"}</td>
                  <td>{lead.vendor_name || "-"}</td>
                  <td>
                    <span className="stage-badge" style={getStatusBadge(lead.status)}>
                      {lead.status || "New"}
                    </span>
                  </td>
                  <td>
                    <div className="actions-cell">
                      <button className="action-btn" title="View">→</button>
                      <button className="action-btn edit" onClick={() => openEdit(lead)} title="Edit">✏️</button>
                      <button className="action-btn delete" onClick={() => deleteLead(lead._id)} title="Delete">🗑️</button>
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
            <h2 style={{ marginBottom: "20px" }}>{editingLead ? "Edit Lead" : "Add New Lead"}</h2>
            <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
              <input
                type="text"
                placeholder="Name"
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
                placeholder="Title"
                value={formData.title}
                onChange={e => setFormData({ ...formData, title: e.target.value })}
                style={{ padding: "10px", borderRadius: "8px", border: "1px solid #e5e7eb" }}
              />
              <input
                type="text"
                placeholder="Company"
                value={formData.company}
                onChange={e => setFormData({ ...formData, company: e.target.value })}
                style={{ padding: "10px", borderRadius: "8px", border: "1px solid #e5e7eb" }}
              />
              <select
                value={formData.status}
                onChange={e => setFormData({ ...formData, status: e.target.value })}
                style={{ padding: "10px", borderRadius: "8px", border: "1px solid #e5e7eb" }}
              >
                <option value="new">New</option>
                <option value="contacted">Contacted</option>
                <option value="qualified">Qualified</option>
                <option value="rejected">Rejected</option>
              </select>
              <div style={{ display: "flex", gap: "12px", marginTop: "8px" }}>
                <button className="btn btn-outline" onClick={() => setShowForm(false)}>
                  Cancel
                </button>
                <button className="btn btn-primary" onClick={() => setShowForm(false)}>
                  {editingLead ? "Update" : "Create"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default VendorLeadsPage
