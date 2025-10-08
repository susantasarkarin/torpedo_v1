"use client"
import { useEffect, useMemo, useState } from "react"
import "./clients.css"

function ClientsPage() {
  const [clients, setClients] = useState([])
  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [search, setSearch] = useState("")

  const emptyForm = {
    name: "",
    contactPerson: "",
    email: "",
    address: "",
    clientVariable: "",
    currency: "",
    clientType: "Offline",
    status: "Active",
  }
  const [formData, setFormData] = useState(emptyForm)

  // Fetch clients
  useEffect(() => {
    const run = async () => {
      try {
        const res = await fetch("http://localhost:8000/clients/")
        const data = await res.json()
        setClients(data.clients || [])
      } catch (e) {
        setError(e.message || "Failed to load clients")
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
  const openEdit = (c) => {
    setEditingId(c._id)
    setFormData({
      name: c.name || "",
      contactPerson: c.contactPerson || "",
      email: c.email || "",
      address: c.address || "",
      clientVariable: c.clientVariable || "",
      currency: c.currency || "",
      clientType: c.clientType || "Offline",
      status: c.status || "Active",
    })
    setShowForm(true)
  }

  // Create or Update client
  const saveClient = async () => {
    setLoading(true)
    setError(null)
    try {
      if (editingId) {
        // UPDATE
        const res = await fetch(`http://localhost:8000/clients/${editingId}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(formData),
        })
        if (!res.ok) {
          const msg = await res.json().catch(() => ({}))
          throw new Error(msg?.detail || "Failed to update client")
        }
        setClients(prev =>
          prev.map(c => (c._id === editingId ? { ...c, ...formData, _id: editingId } : c))
        )
      } else {
        // CREATE
        const res = await fetch("http://localhost:8000/clients/", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(formData),
        })
        const data = await res.json()
        if (!res.ok) throw new Error(data?.detail || "Failed to create client")
        setClients(prev => [...prev, data.client])
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

  // Delete client
  const deleteClient = async (id) => {
    if (!window.confirm("Delete this client?")) return
    setError(null)
    try {
      const res = await fetch(`http://localhost:8000/clients/${id}`, { method: "DELETE" })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data?.detail || "Failed to delete client")
      setClients(prev => prev.filter(c => c._id !== id))
    } catch (e) {
      setError(e.message || "Delete failed")
    }
  }

 const filtered = useMemo(() => {
  const q = search.trim().toLowerCase()
  if (!q) return clients
  return clients.filter(c =>
    ["name", "email", "contactPerson", "address", "clientVariable"].some(field =>
      String(c[field] || "").toLowerCase().includes(q)
    )
  )
}, [clients, search])




  return (
    <div className="clients-page">
      <div className="page-header">
        <div>
          <h2>Clients</h2>
          <p>Manage your survey clients and their information</p>
        </div>
        <button className="btn btn-primary" onClick={openCreate}>
          + Add New Client
        </button>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {/* Search and Stats */}
      <div className="search-stats-section">
        <div className="search-box">
          <input
            type="text"
            placeholder="Search clients by name or email..."
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>
        <div className="stats">
          <span>Total: {clients.length}</span>
          <span>Active: {clients.filter(c => c.status === "Active").length}</span>
        </div>
      </div>

      {/* Clients Table */}
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Email</th>
            <th>Phone (contactPerson)</th>
            <th>Status</th>
            <th style={{ width: 120 }}>Actions</th>
          </tr>
        </thead>
        <tbody>
          {filtered.map(c => (
            <tr key={c._id}>
              <td>{c.name}</td>
              <td>{c.email}</td>
              <td>{c.contactPerson}</td>
              <td>
                <span className={`status ${(c.status || "Active").toLowerCase()}`}>
                  {c.status || "Active"}
                </span>
              </td>
              <td>
                <div className="action-buttons">
                  <button className="action-btn edit-btn" onClick={() => openEdit(c)}>✏️</button>
                  <button className="action-btn delete-btn" onClick={() => deleteClient(c._id)}>🗑️</button>
                </div>
              </td>
            </tr>
          ))}
          {filtered.length === 0 && (
            <tr>
              <td colSpan={5} style={{ textAlign: "center", padding: "1rem" }}>
                No clients found.
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
              <h3>{editingId ? "Edit Client" : "Add New Client"}</h3>
              <button className="close-btn" onClick={() => setShowForm(false)}>×</button>
            </div>

            <div className="modal-body">
              <div className="form-group">
                <label>Client Name *</label>
                <input
                  name="name"
                  placeholder="Enter client name"
                  value={formData.name}
                  onChange={handleChange}
                />
              </div>

              <div className="form-group">
                <label>Email Address *</label>
                <input
                  name="email"
                  type="email"
                  placeholder="Enter email address"
                  value={formData.email}
                  onChange={handleChange}
                />
              </div>

              <div className="form-group">
                <label>Phone Number *</label>
                <input
                  name="contactPerson"
                  placeholder="Enter phone number"
                  value={formData.contactPerson}
                  onChange={handleChange}
                />
              </div>

              <div className="form-group">
                <label>Address</label>
                <input
                  name="address"
                  placeholder="Enter address"
                  value={formData.address}
                  onChange={handleChange}
                />
              </div>

              <div className="form-group">
                <label>Client Variable</label>
                <input
                  name="clientVariable"
                  placeholder="Enter client variable"
                  value={formData.clientVariable}
                  onChange={handleChange}
                />
              </div>

              <div className="form-group">
                <label>Currency</label>
                <input
                  name="currency"
                  placeholder="Enter currency"
                  value={formData.currency}
                  onChange={handleChange}
                />
              </div>

              <div className="form-group">
                <label>Client Type</label>
                <select name="clientType" value={formData.clientType} onChange={handleChange}>
                  <option>Offline</option>
                  <option>Online</option>
                  <option>API</option>
                </select>
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
              <button className="btn btn-save" onClick={saveClient} disabled={loading}>
                {loading ? "Saving..." : editingId ? "Save Changes" : "Add Client"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default ClientsPage
