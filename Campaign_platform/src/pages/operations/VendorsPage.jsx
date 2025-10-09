"use client"

import { useEffect, useMemo, useState } from "react"
import "./clients.css"  // reuse same styles

function VendorsPage() {
  const [vendors, setVendors] = useState([])
  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [search, setSearch] = useState("")

  const emptyForm = {
    vendorName: "",
    vendorEmail: "",
    vendorVariable: "",
    vendorType: "Panel",
    status: "Active",
    completeRD: "",
    terminateRD: "",
    quotaFullRD: "",
  }
  const [formData, setFormData] = useState(emptyForm)

  // Fetch vendors
  useEffect(() => {
    const run = async () => {
      try {
        const res = await fetch("http://localhost:8000/vendors/")
        const data = await res.json()
        setVendors(data.vendors || [])
      } catch (e) {
        setError(e.message || "Failed to load vendors")
      }
    }
    run()
  }, [])

  // Handle form input
  const handleChange = (e) => {
    setFormData({ ...formData, [e.target.name]: e.target.value })
  }

  // Open modal for create
  const openCreate = () => {
    setEditingId(null)
    setFormData(emptyForm)
    setShowForm(true)
  }

  // Open modal for edit
  const openEdit = (v) => {
    setEditingId(v._id)
    setFormData({
      vendorName: v.vendorName || "",
      vendorEmail: v.vendorEmail || "",
      vendorVariable: v.vendorVariable || "",
      vendorType: v.vendorType || "Panel",
      status: v.status || "Active",
      completeRD: v.completeRD || "",
      terminateRD: v.terminateRD || "",
      quotaFullRD: v.quotaFullRD || "",
    })
    setShowForm(true)
  }

  // Create or Update vendor
  const saveVendor = async () => {
    setLoading(true)
    setError(null)
    try {
      if (editingId) {
        // UPDATE
        const res = await fetch(`http://localhost:8000/vendors/${editingId}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(formData),
        })
        if (!res.ok) {
          const msg = await res.json().catch(() => ({}))
          throw new Error(msg?.detail || "Failed to update vendor")
        }
        setVendors(prev =>
          prev.map(v => (v._id === editingId ? { ...v, ...formData, _id: editingId } : v))
        )
      } else {
        // CREATE
        const res = await fetch("http://localhost:8000/vendors/", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(formData),
        })
        const data = await res.json()
        if (!res.ok) throw new Error(data?.detail || "Failed to create vendor")
        setVendors(prev => [...prev, data.vendor])
      }

      setShowForm(false)
      setEditingId(null)
      setFormData(emptyForm)
    } catch (e) {
      setError(e.message || "Save failed")
    } finally {
      setLoading(false)
    }
  }

  // Delete vendor
  const deleteVendor = async (id) => {
    if (!window.confirm("Delete this vendor?")) return
    setError(null)
    try {
      const res = await fetch(`http://localhost:8000/vendors/${id}`, { method: "DELETE" })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data?.detail || "Failed to delete vendor")
      setVendors(prev => prev.filter(v => v._id !== id))
    } catch (e) {
      setError(e.message || "Delete failed")
    }
  }

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return vendors
    return vendors.filter(v =>
      ["vendorName", "vendorEmail", "vendorVariable", "vendorType"].some(field =>
        String(v[field] || "").toLowerCase().includes(q)
      )
    )
  }, [vendors, search])

  return (
    <div className="clients-page">
      <div className="page-header">
        <div>
          <h2>Vendors</h2>
          <p>Manage your survey vendors and their information</p>
        </div>
        <button className="btn btn-primary" onClick={openCreate}>
          + Add New Vendor
        </button>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {/* Search and Stats */}
      <div className="search-stats-section">
        <div className="search-box">
          <input
            type="text"
            placeholder="Search vendors by name or email..."
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>
        <div className="stats">
          <span>Total: {vendors.length}</span>
          <span>Active: {vendors.filter(v => v.status === "Active").length}</span>
        </div>
      </div>

      {/* Vendors Table */}
      <table>
        <thead>
          <tr>
           
            <th>Vendor Name</th>
            <th>Email</th>
            <th>Variable</th>
            <th>Type</th>
            <th>Status</th>
            <th style={{ width: 120 }}>Actions</th>
          </tr>
        </thead>
        <tbody>
          {filtered.map(v => (
            <tr key={v._id}>
              
              <td>{v.vendorName}</td>
              <td>{v.vendorEmail}</td>
              <td>{v.vendorVariable}</td>
              <td>{v.vendorType}</td>
              <td>
                <span className={`status ${(v.status || "Active").toLowerCase()}`}>
                  {v.status || "Active"}
                </span>
              </td>
              <td>
                <div className="action-buttons">
                  <button className="action-btn edit-btn" onClick={() => openEdit(v)}>✏️</button>
                  <button className="action-btn delete-btn" onClick={() => deleteVendor(v._id)}>🗑️</button>
                </div>
              </td>
            </tr>
          ))}
          {filtered.length === 0 && (
            <tr>
              <td colSpan={7} style={{ textAlign: "center", padding: "1rem" }}>
                No vendors found.
              </td>
            </tr>
          )}
        </tbody>
      </table>

      {/* Add/Edit Modal */}
      {showForm && (
        <div className="modal" onClick={(e) => {
          if (e.target.className === 'modal') setShowForm(false)
        }}>
          <div className="modal-content">
            <div className="modal-header">
              <h3>{editingId ? "Edit Vendor" : "Add New Vendor"}</h3>
              <button className="close-btn" onClick={() => setShowForm(false)}>×</button>
            </div>

            <div className="modal-body">
              <div className="form-group">
                <label>Vendor Name *</label>
                <input
                  name="vendorName"
                  placeholder="Enter vendor name"
                  value={formData.vendorName}
                  onChange={handleChange}
                />
              </div>

              <div className="form-group">
                <label>Email Address *</label>
                <input
                  name="vendorEmail"
                  type="email"
                  placeholder="Enter email address"
                  value={formData.vendorEmail}
                  onChange={handleChange}
                />
              </div>

              <div className="form-group">
                <label>Vendor Variable</label>
                <input
                  name="vendorVariable"
                  placeholder="Enter vendor variable"
                  value={formData.vendorVariable}
                  onChange={handleChange}
                />
              </div>

              <div className="form-group">
                <label>Vendor Type</label>
                <select name="vendorType" value={formData.vendorType} onChange={handleChange}>
                  <option>Panel</option>
                  <option>Affiliate</option>
                  <option>API</option>
                </select>
              </div>

              <div className="form-group">
                <label>Complete RD</label>
                <input
                  name="completeRD"
                  placeholder="Enter complete RD URL"
                  value={formData.completeRD}
                  onChange={handleChange}
                />
              </div>

              <div className="form-group">
                <label>Terminate RD</label>
                <input
                  name="terminateRD"
                  placeholder="Enter terminate RD URL"
                  value={formData.terminateRD}
                  onChange={handleChange}
                />
              </div>

              <div className="form-group">
                <label>Quota Full RD</label>
                <input
                  name="quotaFullRD"
                  placeholder="Enter quota full RD URL"
                  value={formData.quotaFullRD}
                  onChange={handleChange}
                />
              </div>

              <div className="form-group">
                <label>Status</label>
                <select name="status" value={formData.status} onChange={handleChange}>
                  <option>Active</option>
                  <option>Inactive</option>
                </select>
              </div>
            </div>

            <div className="modal-footer">
              <button className="btn btn-cancel" onClick={() => setShowForm(false)} disabled={loading}>Cancel</button>
              <button className="btn btn-save" onClick={saveVendor} disabled={loading}>
                {loading ? "Saving..." : editingId ? "Save Changes" : "Add Vendor"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default VendorsPage
