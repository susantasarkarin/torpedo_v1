"use client"

import { useState, useEffect } from "react"
import { API_BASE_URL } from "../../config"
import { Link } from "react-router-dom"
import "./RFQ.css"

// Helper to get auth token - handles both storage methods
const getAuthToken = () => localStorage.getItem("session_id") || sessionStorage.getItem("token")

// Currency options
const CURRENCIES = [
  { code: "USD", symbol: "$", name: "US Dollar" },
  { code: "INR", symbol: "₹", name: "Indian Rupee" },
  { code: "EUR", symbol: "€", name: "Euro" },
  { code: "GBP", symbol: "£", name: "British Pound" },
  { code: "AUD", symbol: "A$", name: "Australian Dollar" },
  { code: "CAD", symbol: "C$", name: "Canadian Dollar" },
  { code: "SGD", symbol: "S$", name: "Singapore Dollar" },
  { code: "AED", symbol: "د.إ", name: "UAE Dirham" },
]

// Methodology options
const METHODOLOGIES = [
  "CATI", "CAWI", "F2F", "CAPI", "Online Panel", "B2B Survey", 
  "Healthcare Survey", "Consumer Survey", "IDI", "Focus Group", "Other"
]

function RFQ() {
  const [rfqs, setRfqs] = useState([])
  const [loading, setLoading] = useState(true)
  const [stats, setStats] = useState(null)
  const [filters, setFilters] = useState({
    status: "",
    priority: "",
    search: ""
  })
  const [editingValue, setEditingValue] = useState(null) // { rfq_id, value, currency }
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState({ type: "", text: "" })
  const [selectedIds, setSelectedIds] = useState([])
  const [selectedRfq, setSelectedRfq] = useState(null) // For detail modal
  const [showDetailModal, setShowDetailModal] = useState(false)

  useEffect(() => {
    loadRFQs()
    loadStats()
  }, [])

  useEffect(() => {
    const debounce = setTimeout(() => {
      loadRFQs()
    }, 300)
    return () => clearTimeout(debounce)
  }, [filters])

  const loadRFQs = async () => {
    try {
      const token = localStorage.getItem("session_id")
      const params = new URLSearchParams()
      
      if (filters.status) params.append("status", filters.status)
      if (filters.priority) params.append("priority", filters.priority)
      
      const url = `${API_BASE_URL}/rfq/?${params.toString()}`
      const response = await fetch(url, {
        headers: { Authorization: token }
      })
      
      if (response.ok) {
        const data = await response.json()
        let rfqList = data.rfqs || []
        
        // Client-side search filter
        if (filters.search) {
          const search = filters.search.toLowerCase()
          rfqList = rfqList.filter(rfq => 
            rfq.title?.toLowerCase().includes(search) ||
            rfq.client_name?.toLowerCase().includes(search) ||
            rfq.client_email?.toLowerCase().includes(search) ||
            rfq.lead_email?.toLowerCase().includes(search)
          )
        }
        
        setRfqs(rfqList)
      }
    } catch (error) {
      console.error("Error loading RFQs:", error)
      setMessage({ type: "error", text: "Failed to load RFQs" })
    } finally {
      setLoading(false)
    }
  }

  const loadStats = async () => {
    try {
      const token = localStorage.getItem("session_id")
      const response = await fetch(`${API_BASE_URL}/rfq/stats`, {
        headers: { Authorization: token }
      })
      
      if (response.ok) {
        const data = await response.json()
        setStats(data)
      }
    } catch (error) {
      console.error("Error loading stats:", error)
    }
  }

  const updateRFQValue = async (rfqId) => {
    if (!editingValue || editingValue.rfq_id !== rfqId) return
    
    setSaving(true)
    try {
      const token = localStorage.getItem("session_id")
      const response = await fetch(`${API_BASE_URL}/rfq/${rfqId}`, {
        method: "PUT",
        headers: { 
          Authorization: token,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ 
          extracted_value: parseFloat(editingValue.value) || 0,
          value_override: true
        })
      })
      
      if (response.ok) {
        setMessage({ type: "success", text: "Value updated successfully" })
        setEditingValue(null)
        loadRFQs()
        loadStats()
      } else {
        const error = await response.json()
        setMessage({ type: "error", text: error.detail || "Failed to update value" })
      }
    } catch (error) {
      console.error("Error updating RFQ:", error)
      setMessage({ type: "error", text: "Failed to update RFQ" })
    } finally {
      setSaving(false)
    }
  }

  const updateRFQStatus = async (rfqId, newStatus) => {
    try {
      const token = localStorage.getItem("session_id")
      const response = await fetch(`${API_BASE_URL}/rfq/${rfqId}`, {
        method: "PUT",
        headers: { 
          Authorization: token,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ status: newStatus })
      })
      
      if (response.ok) {
        setMessage({ type: "success", text: "Status updated" })
        loadRFQs()
        loadStats()
      }
    } catch (error) {
      console.error("Error updating status:", error)
    }
  }

  const deleteRFQ = async (rfqId) => {
    if (!window.confirm("Are you sure you want to delete this RFQ?")) return
    
    try {
      const token = localStorage.getItem("session_id")
      const response = await fetch(`${API_BASE_URL}/rfq/${rfqId}`, {
        method: "DELETE",
        headers: { Authorization: token }
      })
      
      if (response.ok) {
        setMessage({ type: "success", text: "RFQ deleted" })
        loadRFQs()
        loadStats()
      }
    } catch (error) {
      console.error("Error deleting RFQ:", error)
    }
  }

  // Bulk delete RFQs
  const bulkDeleteRFQs = async () => {
    if (selectedIds.length === 0) return
    if (!window.confirm(`Delete ${selectedIds.length} selected RFQs?`)) return
    
    try {
      const token = localStorage.getItem("session_id")
      const response = await fetch(`${API_BASE_URL}/rfq/bulk-delete`, {
        method: "POST",
        headers: { 
          Authorization: token,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ ids: selectedIds })
      })
      
      if (response.ok) {
        const data = await response.json()
        setMessage({ type: "success", text: `${data.deleted_count} RFQs deleted` })
        setSelectedIds([])
        loadRFQs()
        loadStats()
      } else {
        const error = await response.json()
        setMessage({ type: "error", text: error.detail || "Failed to delete RFQs" })
      }
    } catch (error) {
      console.error("Error bulk deleting RFQs:", error)
      setMessage({ type: "error", text: "Failed to delete RFQs" })
    }
  }

  // Toggle selection
  const toggleSelect = (rfqId) => {
    setSelectedIds((prev) =>
      prev.includes(rfqId) ? prev.filter((x) => x !== rfqId) : [...prev, rfqId]
    )
  }

  // Toggle select all
  const toggleSelectAll = () => {
    const allIds = rfqs.map((r) => r.rfq_id)
    const allSelected = allIds.every((id) => selectedIds.includes(id))
    if (allSelected) {
      setSelectedIds([])
    } else {
      setSelectedIds(allIds)
    }
  }

  const formatCurrency = (value, currency = "USD") => {
    if (!value && value !== 0) return "—"
    const currencyInfo = CURRENCIES.find(c => c.code === currency) || CURRENCIES[0]
    return `${currencyInfo.symbol}${value.toLocaleString()}`
  }

  // Load RFQ details for modal
  const loadRfqDetails = async (rfqId) => {
    try {
      const token = localStorage.getItem("session_id")
      const response = await fetch(`${API_BASE_URL}/rfq/${rfqId}`, {
        headers: { Authorization: token }
      })
      
      if (response.ok) {
        const data = await response.json()
        setSelectedRfq(data.rfq)
        setShowDetailModal(true)
      }
    } catch (error) {
      console.error("Error loading RFQ details:", error)
    }
  }

  // Update RFQ fields (including currency)
  const updateRfqField = async (rfqId, field, value) => {
    try {
      const token = localStorage.getItem("session_id")
      const body = {}
      body[field] = value
      
      const response = await fetch(`${API_BASE_URL}/rfq/${rfqId}`, {
        method: "PUT",
        headers: { 
          Authorization: token,
          "Content-Type": "application/json"
        },
        body: JSON.stringify(body)
      })
      
      if (response.ok) {
        loadRFQs()
        loadStats()
        if (selectedRfq && selectedRfq.rfq_id === rfqId) {
          loadRfqDetails(rfqId)
        }
      }
    } catch (error) {
      console.error(`Error updating RFQ ${field}:`, error)
    }
  }

  const formatDate = (dateStr) => {
    if (!dateStr) return "—"
    return new Date(dateStr).toLocaleDateString()
  }

  const getStatusColor = (status) => {
    const colors = {
      detected: { bg: "#dbeafe", color: "#1e40af" },
      pending: { bg: "#fef3c7", color: "#92400e" },
      quoted: { bg: "#e0e7ff", color: "#3730a3" },
      negotiating: { bg: "#fce7f3", color: "#9d174d" },
      won: { bg: "#dcfce7", color: "#166534" },
      lost: { bg: "#fee2e2", color: "#991b1b" },
      cancelled: { bg: "#f3f4f6", color: "#6b7280" }
    }
    return colors[status] || colors.pending
  }

  const getPriorityColor = (priority) => {
    const colors = {
      low: { bg: "#f3f4f6", color: "#6b7280" },
      medium: { bg: "#dbeafe", color: "#1e40af" },
      high: { bg: "#fef3c7", color: "#92400e" },
      urgent: { bg: "#fee2e2", color: "#991b1b" }
    }
    return colors[priority] || colors.medium
  }

  return (
    <div className="rfq-container">
      {/* Stats Cards */}
      {stats && (
        <div className="rfq-stats">
          <div className="stat-card">
            <span className="stat-label">Total RFQs</span>
            <span className="stat-value">{stats.total}</span>
          </div>
          <div className="stat-card success">
            <span className="stat-label">Won</span>
            <span className="stat-value">{stats.by_status?.won || 0}</span>
          </div>
          <div className="stat-card warning">
            <span className="stat-label">Pending</span>
            <span className="stat-value">{stats.by_status?.pending || 0}</span>
          </div>
          <div className="stat-card info">
            <span className="stat-label">Total Value</span>
            <span className="stat-value">{formatCurrency(stats.total_value)}</span>
          </div>
        </div>
      )}

      {/* Message */}
      {message.text && (
        <div className={`rfq-message ${message.type}`}>
          {message.text}
          <button onClick={() => setMessage({ type: "", text: "" })}>×</button>
        </div>
      )}

      <div className="card">
        <div className="card-header">
          <h2 className="card-title">Request for Quotation (RFQ)</h2>
          <p className="card-description">
            Manage quotation requests detected from email conversations and track proposal status.
          </p>
        </div>

        {/* Filters */}
        <div className="rfq-filters">
          <input
            type="text"
            placeholder="Search RFQs..."
            value={filters.search}
            onChange={(e) => setFilters(prev => ({ ...prev, search: e.target.value }))}
            className="rfq-search"
          />
          <select
            value={filters.status}
            onChange={(e) => setFilters(prev => ({ ...prev, status: e.target.value }))}
            className="rfq-filter-select"
          >
            <option value="">All Status</option>
            <option value="detected">Detected</option>
            <option value="pending">Pending</option>
            <option value="quoted">Quoted</option>
            <option value="negotiating">Negotiating</option>
            <option value="won">Won</option>
            <option value="lost">Lost</option>
            <option value="cancelled">Cancelled</option>
          </select>
          <select
            value={filters.priority}
            onChange={(e) => setFilters(prev => ({ ...prev, priority: e.target.value }))}
            className="rfq-filter-select"
          >
            <option value="">All Priority</option>
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
            <option value="urgent">Urgent</option>
          </select>
          <button 
            className="btn btn-secondary"
            onClick={() => setFilters({ status: "", priority: "", search: "" })}
          >
            Clear Filters
          </button>
          {selectedIds.length > 0 && (
            <button 
              className="btn btn-danger"
              onClick={bulkDeleteRFQs}
              style={{ backgroundColor: '#dc2626', color: 'white' }}
            >
              🗑️ Delete ({selectedIds.length})
            </button>
          )}
        </div>

        {/* RFQ Table */}
        {loading ? (
          <div className="rfq-loading">
            <div className="spinner"></div>
            <span>Loading RFQs...</span>
          </div>
        ) : rfqs.length === 0 ? (
          <div className="rfq-empty">
            <p>No RFQs found. RFQs are automatically created when pricing requests are detected in emails.</p>
          </div>
        ) : (
          <div className="card rfq-table-container">
            <table className="rfq-table">
              <thead>
                <tr>
                  <th style={{ width: '40px' }}>
                    <input 
                      type="checkbox" 
                      checked={rfqs.length > 0 && rfqs.every(r => selectedIds.includes(r.rfq_id))}
                      onChange={toggleSelectAll}
                      style={{ cursor: 'pointer' }}
                    />
                  </th>
                  <th>Title / Subject</th>
                  <th>Lead</th>
                  <th>Value</th>
                  <th>Currency</th>
                  <th>Country</th>
                  <th>Priority</th>
                  <th>Status</th>
                  <th>Detected</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {rfqs.map((rfq) => (
                  <tr key={rfq.rfq_id} style={{ backgroundColor: selectedIds.includes(rfq.rfq_id) ? '#eff6ff' : 'transparent', cursor: 'pointer' }} onClick={() => loadRfqDetails(rfq.rfq_id)}>
                    <td onClick={(e) => e.stopPropagation()}>
                      <input 
                        type="checkbox" 
                        checked={selectedIds.includes(rfq.rfq_id)}
                        onChange={() => toggleSelect(rfq.rfq_id)}
                        style={{ cursor: 'pointer' }}
                      />
                    </td>
                    <td className="rfq-title-cell">
                      <div className="rfq-title">{rfq.title || "Untitled RFQ"}</div>
                      {rfq.methodology && (
                        <div className="rfq-subtitle" style={{ color: '#6b7280', fontSize: '0.75rem' }}>
                          {rfq.methodology} {rfq.loi && `• ${rfq.loi} min`} {rfq.ir && `• ${rfq.ir}% IR`}
                        </div>
                      )}
                    </td>
                    <td>
                      <div className="rfq-lead">
                        <Link to={`/admin/sales/leads/${rfq.lead_id}`} className="lead-link" onClick={(e) => e.stopPropagation()}>
                          {rfq.lead_name || rfq.sender_name || rfq.contact_email || "Unknown"}
                        </Link>
                        {rfq.sender_company && (
                          <div className="rfq-company">{rfq.sender_company}</div>
                        )}
                      </div>
                    </td>
                    <td onClick={(e) => e.stopPropagation()}>
                      {editingValue?.rfq_id === rfq.rfq_id ? (
                        <div className="value-edit">
                          <input
                            type="number"
                            value={editingValue.value}
                            onChange={(e) => setEditingValue({ ...editingValue, value: e.target.value })}
                            className="value-input"
                            autoFocus
                          />
                          <button 
                            className="value-save"
                            onClick={() => updateRFQValue(rfq.rfq_id)}
                            disabled={saving}
                          >
                            ✓
                          </button>
                          <button 
                            className="value-cancel"
                            onClick={() => setEditingValue(null)}
                          >
                            ×
                          </button>
                        </div>
                      ) : (
                        <div 
                          className="rfq-value"
                          onClick={() => setEditingValue({ rfq_id: rfq.rfq_id, value: rfq.manual_value || rfq.extracted_value || 0 })}
                          title="Click to edit value"
                        >
                          {formatCurrency(rfq.manual_value || rfq.extracted_value, rfq.manual_currency || rfq.extracted_currency || "USD")}
                          {rfq.manual_value && <span className="override-badge">✎</span>}
                        </div>
                      )}
                    </td>
                    <td onClick={(e) => e.stopPropagation()}>
                      <select
                        value={rfq.manual_currency || rfq.extracted_currency || "USD"}
                        onChange={(e) => updateRfqField(rfq.rfq_id, "manual_currency", e.target.value)}
                        className="currency-select"
                        style={{ padding: '4px 8px', fontSize: '0.8rem', borderRadius: '4px', border: '1px solid #d1d5db' }}
                      >
                        {CURRENCIES.map(c => (
                          <option key={c.code} value={c.code}>{c.code}</option>
                        ))}
                      </select>
                    </td>
                    <td>
                      <span style={{ fontSize: '0.85rem' }}>{rfq.country || "—"}</span>
                    </td>
                    <td onClick={(e) => e.stopPropagation()}>
                      <span 
                        className="priority-badge"
                        style={getPriorityColor(rfq.priority)}
                      >
                        {rfq.priority || "medium"}
                      </span>
                    </td>
                    <td onClick={(e) => e.stopPropagation()}>
                      <select
                        value={rfq.status}
                        onChange={(e) => updateRFQStatus(rfq.rfq_id, e.target.value)}
                        className="status-select"
                        style={{ 
                          backgroundColor: getStatusColor(rfq.status).bg,
                          color: getStatusColor(rfq.status).color
                        }}
                      >
                        <option value="detected">Detected</option>
                        <option value="pending">Pending</option>
                        <option value="quoted">Quoted</option>
                        <option value="negotiating">Negotiating</option>
                        <option value="won">Won</option>
                        <option value="lost">Lost</option>
                        <option value="cancelled">Cancelled</option>
                      </select>
                    </td>
                    <td className="rfq-date">{formatDate(rfq.received_date || rfq.created_at)}</td>
                    <td onClick={(e) => e.stopPropagation()}>
                      <div className="rfq-actions">
                        <button
                          className="btn btn-outline btn-sm"
                          onClick={() => loadRfqDetails(rfq.rfq_id)}
                          title="View Details"
                        >
                          👁️
                        </button>
                        <Link 
                          to={`/admin/sales/leads/${rfq.lead_id}`}
                          className="btn btn-outline btn-sm"
                          title="View Lead"
                        >
                          👤
                        </Link>
                        <button
                          className="btn btn-outline btn-sm btn-danger"
                          onClick={() => deleteRFQ(rfq.rfq_id)}
                          title="Delete RFQ"
                        >
                          🗑️
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* RFQ Detail Modal */}
      {showDetailModal && selectedRfq && (
        <div className="modal-overlay" onClick={() => setShowDetailModal(false)}>
          <div className="modal-content rfq-detail-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>📋 RFQ Details: {selectedRfq.rfq_id}</h2>
              <button className="modal-close" onClick={() => setShowDetailModal(false)}>×</button>
            </div>
            
            <div className="modal-body">
              {/* Sender Information */}
              <div className="detail-section">
                <h3>👤 Sender Information</h3>
                <div className="detail-grid">
                  <div className="detail-item">
                    <label>Name</label>
                    <span>{selectedRfq.sender_name || selectedRfq.lead_name || "Unknown"}</span>
                  </div>
                  <div className="detail-item">
                    <label>Email</label>
                    <span>{selectedRfq.sender_email || selectedRfq.contact_email}</span>
                  </div>
                  <div className="detail-item">
                    <label>Company</label>
                    <span>{selectedRfq.sender_company || "—"}</span>
                  </div>
                  <div className="detail-item">
                    <label>Title</label>
                    <span>{selectedRfq.sender_title || "—"}</span>
                  </div>
                </div>
              </div>

              {/* RFQ Details */}
              <div className="detail-section">
                <h3>💰 RFQ Information</h3>
                <div className="detail-grid">
                  <div className="detail-item">
                    <label>Title</label>
                    <span>{selectedRfq.title || "Untitled"}</span>
                  </div>
                  <div className="detail-item">
                    <label>Value</label>
                    <span style={{ fontWeight: 'bold', color: '#10b981' }}>
                      {formatCurrency(selectedRfq.manual_value || selectedRfq.extracted_value, selectedRfq.manual_currency || selectedRfq.extracted_currency)}
                    </span>
                  </div>
                  <div className="detail-item">
                    <label>Currency</label>
                    <select
                      value={selectedRfq.manual_currency || selectedRfq.extracted_currency || "USD"}
                      onChange={(e) => updateRfqField(selectedRfq.rfq_id, "manual_currency", e.target.value)}
                      style={{ padding: '4px 8px', borderRadius: '4px', border: '1px solid #d1d5db' }}
                    >
                      {CURRENCIES.map(c => (
                        <option key={c.code} value={c.code}>{c.code} - {c.name}</option>
                      ))}
                    </select>
                  </div>
                  <div className="detail-item">
                    <label>Status</label>
                    <span 
                      className="status-badge"
                      style={{ ...getStatusColor(selectedRfq.status), padding: '4px 12px', borderRadius: '12px' }}
                    >
                      {selectedRfq.status}
                    </span>
                  </div>
                  <div className="detail-item">
                    <label>Priority</label>
                    <span 
                      className="priority-badge"
                      style={{ ...getPriorityColor(selectedRfq.priority), padding: '4px 12px', borderRadius: '12px' }}
                    >
                      {selectedRfq.priority}
                    </span>
                  </div>
                  <div className="detail-item">
                    <label>Received</label>
                    <span>{formatDate(selectedRfq.received_date)}</span>
                  </div>
                </div>
              </div>

              {/* Research Details */}
              <div className="detail-section">
                <h3>📊 Research Parameters</h3>
                <div className="detail-grid">
                  <div className="detail-item">
                    <label>Methodology</label>
                    <select
                      value={selectedRfq.methodology || ""}
                      onChange={(e) => updateRfqField(selectedRfq.rfq_id, "methodology", e.target.value)}
                      style={{ padding: '4px 8px', borderRadius: '4px', border: '1px solid #d1d5db' }}
                    >
                      <option value="">Select...</option>
                      {METHODOLOGIES.map(m => (
                        <option key={m} value={m}>{m}</option>
                      ))}
                    </select>
                  </div>
                  <div className="detail-item">
                    <label>LOI (minutes)</label>
                    <input
                      type="number"
                      value={selectedRfq.loi || ""}
                      onChange={(e) => updateRfqField(selectedRfq.rfq_id, "loi", parseInt(e.target.value) || null)}
                      placeholder="Length of Interview"
                      style={{ padding: '4px 8px', borderRadius: '4px', border: '1px solid #d1d5db', width: '100px' }}
                    />
                  </div>
                  <div className="detail-item">
                    <label>IR (%)</label>
                    <input
                      type="number"
                      value={selectedRfq.ir || ""}
                      onChange={(e) => updateRfqField(selectedRfq.rfq_id, "ir", parseFloat(e.target.value) || null)}
                      placeholder="Incidence Rate"
                      style={{ padding: '4px 8px', borderRadius: '4px', border: '1px solid #d1d5db', width: '100px' }}
                    />
                  </div>
                  <div className="detail-item">
                    <label>Country</label>
                    <input
                      type="text"
                      value={selectedRfq.country || ""}
                      onChange={(e) => updateRfqField(selectedRfq.rfq_id, "country", e.target.value)}
                      placeholder="Target country"
                      style={{ padding: '4px 8px', borderRadius: '4px', border: '1px solid #d1d5db' }}
                    />
                  </div>
                  <div className="detail-item">
                    <label>Sample Size</label>
                    <input
                      type="number"
                      value={selectedRfq.sample_size || ""}
                      onChange={(e) => updateRfqField(selectedRfq.rfq_id, "sample_size", parseInt(e.target.value) || null)}
                      placeholder="Required completes"
                      style={{ padding: '4px 8px', borderRadius: '4px', border: '1px solid #d1d5db', width: '100px' }}
                    />
                  </div>
                </div>
              </div>

              {/* Description */}
              <div className="detail-section">
                <h3>📝 Description</h3>
                <textarea
                  value={selectedRfq.description || ""}
                  onChange={(e) => updateRfqField(selectedRfq.rfq_id, "description", e.target.value)}
                  placeholder="Add RFQ description..."
                  style={{ 
                    width: '100%', 
                    minHeight: '100px', 
                    padding: '12px', 
                    borderRadius: '8px', 
                    border: '1px solid #d1d5db',
                    fontSize: '0.9rem'
                  }}
                />
              </div>

              {/* Email Body */}
              {selectedRfq.email_body && (
                <div className="detail-section">
                  <h3>📧 Original Email</h3>
                  <div style={{ 
                    backgroundColor: '#f9fafb', 
                    padding: '16px', 
                    borderRadius: '8px', 
                    border: '1px solid #e5e7eb',
                    maxHeight: '300px',
                    overflowY: 'auto',
                    whiteSpace: 'pre-wrap',
                    fontSize: '0.9rem',
                    lineHeight: '1.6'
                  }}>
                    {selectedRfq.email_body}
                  </div>
                </div>
              )}

              {/* Summary */}
              {selectedRfq.summary && (
                <div className="detail-section">
                  <h3>📋 AI Summary</h3>
                  <div style={{ 
                    backgroundColor: '#eff6ff', 
                    padding: '16px', 
                    borderRadius: '8px', 
                    border: '1px solid #bfdbfe',
                    fontSize: '0.9rem',
                    lineHeight: '1.6'
                  }}>
                    {selectedRfq.summary}
                  </div>
                </div>
              )}
            </div>

            <div className="modal-footer">
              <Link 
                to={`/admin/sales/leads/${selectedRfq.lead_id}`}
                className="btn btn-primary"
              >
                👤 View Lead Profile
              </Link>
              <button 
                className="btn btn-secondary"
                onClick={() => setShowDetailModal(false)}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default RFQ
