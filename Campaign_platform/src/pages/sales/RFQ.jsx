"use client"

import { useState, useEffect } from "react"
import { API_BASE_URL } from "../../config"
import { Link } from "react-router-dom"
import "./RFQ.css"
import "../../styles/SalesPages.css"
import { buildApiUrl } from "../../config"

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
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [totalPages, setTotalPages] = useState(1)
  const [editingValue, setEditingValue] = useState(null) // { rfq_id, value, currency }
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState({ type: "", text: "" })
  const [selectedIds, setSelectedIds] = useState([])
  const [selectedRfq, setSelectedRfq] = useState(null) // For detail modal
  const [showDetailModal, setShowDetailModal] = useState(false)
  
  // Conversion modal state
  const [showConvertModal, setShowConvertModal] = useState(false)
  const [convertType, setConvertType] = useState("") // "estimate" or "invoice"
  const [converting, setConverting] = useState(false)
  const [conversionForm, setConversionForm] = useState({
    customer_id: "",
    unit_price: "",
    discount_percent: 0,
    tax_percent: 18,
    due_days: 30,
    notes: ""
  })
  const [customers, setCustomers] = useState([])

  useEffect(() => {
    loadRFQs()
    loadStats()
    loadCustomers()
  }, []) // eslint-disable-line

  useEffect(() => {
    const debounce = setTimeout(() => {
      setPage(1)
      loadRFQs(1)
    }, 300)
    return () => clearTimeout(debounce)
  }, [filters]) // eslint-disable-line

  useEffect(() => {
    loadRFQs(page)
  }, [page]) // eslint-disable-line

  const loadRFQs = async (pageNum) => {
    const currentPage = pageNum ?? page
    setLoading(true)
    try {
      const token = localStorage.getItem("session_id")
      const params = new URLSearchParams({ page: String(currentPage), limit: "25" })
      
      if (filters.status) params.append("status", filters.status)
      if (filters.priority) params.append("priority", filters.priority)
      if (filters.search) params.append("search", filters.search)
      
      const url = buildApiUrl(`/api/rfq/?${params.toString()}`)
      const response = await fetch(url, {
        headers: { Authorization: token }
      })
      
      if (response.ok) {
        const data = await response.json()
        setRfqs(data.rfqs || [])
        setTotal(data.total || 0)
        setTotalPages(data.pages || 1)
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
      const response = await fetch(buildApiUrl(`/api/rfq/stats`), {
        headers: { Authorization: token }
      })
      
      if (response.ok) {
        const data = await response.json()
        setStats({
          total: data.total_count,
          by_status: {
            won: data.stats?.won?.count || 0,
            pending: data.stats?.pending?.count || 0,
          },
          total_value: data.total_value,
        })
      }
    } catch (error) {
      console.error("Error loading stats:", error)
    }
  }

  const loadCustomers = async () => {
    try {
      const token = localStorage.getItem("session_id")
      const response = await fetch(buildApiUrl(`/finance/customers/`), {
        headers: { Authorization: token }
      })
      
      if (response.ok) {
        const data = await response.json()
        setCustomers(data || [])
      }
    } catch (error) {
      console.error("Error loading customers:", error)
    }
  }

  // Open conversion modal
  const openConvertModal = (type) => {
    setConvertType(type)
    setConversionForm({
      customer_id: "",
      unit_price: "",
      discount_percent: 0,
      tax_percent: 18,
      due_days: type === "estimate" ? 15 : 30,
      notes: ""
    })
    setShowConvertModal(true)
  }

  // Convert RFQ to Estimate or Invoice
  const handleConversion = async () => {
    if (!selectedRfq) return
    
    setConverting(true)
    try {
      const token = localStorage.getItem("session_id")
      const endpoint = convertType === "estimate" 
        ? buildApiUrl(`/api/rfq/${selectedRfq.rfq_id}/convert-to-estimate`)
        : buildApiUrl(`/api/rfq/${selectedRfq.rfq_id}/convert-to-invoice`)
      
      const body = {
        ...conversionForm,
        unit_price: conversionForm.unit_price ? parseFloat(conversionForm.unit_price) : null,
        customer_id: conversionForm.customer_id || null
      }
      
      const response = await fetch(endpoint, {
        method: "POST",
        headers: { 
          Authorization: token,
          "Content-Type": "application/json"
        },
        body: JSON.stringify(body)
      })
      
      if (response.ok) {
        const data = await response.json()
        setMessage({ 
          type: "success", 
          text: `RFQ converted to ${convertType} successfully! ${data.document_number}` 
        })
        setShowConvertModal(false)
        setShowDetailModal(false)
        loadRFQs()
        loadStats()
      } else {
        const error = await response.json()
        setMessage({ type: "error", text: error.detail || `Failed to convert to ${convertType}` })
      }
    } catch (error) {
      console.error("Error converting RFQ:", error)
      setMessage({ type: "error", text: `Failed to convert RFQ to ${convertType}` })
    } finally {
      setConverting(false)
    }
  }

  const updateRFQValue = async (rfqId) => {
    if (!editingValue || editingValue.rfq_id !== rfqId) return
    
    setSaving(true)
    try {
      const token = localStorage.getItem("session_id")
      const response = await fetch(buildApiUrl(`/api/rfq/${rfqId}`), {
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
      const response = await fetch(buildApiUrl(`/api/rfq/${rfqId}`), {
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
      const response = await fetch(buildApiUrl(`/api/rfq/${rfqId}`), {
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
      const response = await fetch(buildApiUrl(`/api/rfq/bulk-delete`), {
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
      const response = await fetch(buildApiUrl(`/api/rfq/${rfqId}`), {
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
      
      const response = await fetch(buildApiUrl(`/api/rfq/${rfqId}`), {
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
    <div className="rfq-container sales-page">
      {/* Stats Cards */}
      <div className="stats-row">
        <div className="stat-card primary">
          <div className="stat-value">{stats?.total ?? "—"}</div>
          <div className="stat-label">Total RFQs</div>
        </div>
        <div className="stat-card success">
          <div className="stat-value">{stats?.by_status?.won ?? "—"}</div>
          <div className="stat-label">Won</div>
        </div>
        <div className="stat-card warning">
          <div className="stat-value">{stats?.by_status?.pending ?? "—"}</div>
          <div className="stat-label">Pending</div>
        </div>
        <div className="stat-card info">
          <div className="stat-value">{stats ? formatCurrency(stats.total_value) : "—"}</div>
          <div className="stat-label">Total Value</div>
        </div>
      </div>

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
                  <th>Country</th>
                  <th>LOI</th>
                  <th>IR</th>
                  <th>N</th>
                  <th>Value</th>
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
                          {rfq.methodology} {rfq.study_type && `• ${rfq.study_type}`}
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
                    <td>
                      <span style={{ fontSize: '0.85rem' }}>{rfq.country || "—"}</span>
                    </td>
                    <td>
                      {rfq.loi ? (
                        <span style={{ fontSize: '0.85rem', color: '#3b82f6', fontWeight: '500' }}>{rfq.loi} min</span>
                      ) : (
                        <span style={{ color: '#9ca3af' }}>—</span>
                      )}
                    </td>
                    <td>
                      {rfq.ir ? (
                        <span style={{ fontSize: '0.85rem', color: '#10b981', fontWeight: '500' }}>{rfq.ir}%</span>
                      ) : (
                        <span style={{ color: '#9ca3af' }}>—</span>
                      )}
                    </td>
                    <td>
                      {rfq.sample_size ? (
                        <span style={{ fontSize: '0.85rem', color: '#8b5cf6', fontWeight: '500' }}>{rfq.sample_size.toLocaleString()}</span>
                      ) : (
                        <span style={{ color: '#9ca3af' }}>—</span>
                      )}
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

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="pagination-bar">
            <button
              className="btn btn-outline"
              onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={page === 1}
            >
               Previous
            </button>
            <span className="page-info">
              Page <strong>{page}</strong> of <strong>{totalPages}</strong>
              {" "}
              <span style={{ marginLeft: 8 }}>({total.toLocaleString()} RFQs)</span>
            </span>
            <button
              className="btn btn-outline"
              onClick={() => setPage(p => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
            >
              Next 
            </button>
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
                  <div className="detail-item">
                    <label>Study Type</label>
                    <select
                      value={selectedRfq.study_type || ""}
                      onChange={(e) => updateRfqField(selectedRfq.rfq_id, "study_type", e.target.value)}
                      style={{ padding: '4px 8px', borderRadius: '4px', border: '1px solid #d1d5db' }}
                    >
                      <option value="">Select...</option>
                      <option value="B2B">B2B</option>
                      <option value="B2C">B2C</option>
                      <option value="Healthcare">Healthcare</option>
                      <option value="IT">IT Decision Makers</option>
                      <option value="Consumer">Consumer</option>
                      <option value="Other">Other</option>
                    </select>
                  </div>
                  <div className="detail-item">
                    <label>Timeline</label>
                    <input
                      type="text"
                      value={selectedRfq.timeline || ""}
                      onChange={(e) => updateRfqField(selectedRfq.rfq_id, "timeline", e.target.value)}
                      placeholder="Project timeline"
                      style={{ padding: '4px 8px', borderRadius: '4px', border: '1px solid #d1d5db' }}
                    />
                  </div>
                </div>
                {/* Target Audience - Full width */}
                <div style={{ marginTop: '12px' }}>
                  <label style={{ display: 'block', fontSize: '0.8rem', color: '#6b7280', marginBottom: '4px' }}>Target Audience</label>
                  <textarea
                    value={selectedRfq.target_audience || ""}
                    onChange={(e) => updateRfqField(selectedRfq.rfq_id, "target_audience", e.target.value)}
                    placeholder="Describe the target audience/respondent profile..."
                    style={{ 
                      width: '100%', 
                      minHeight: '60px', 
                      padding: '8px', 
                      borderRadius: '4px', 
                      border: '1px solid #d1d5db',
                      fontSize: '0.9rem'
                    }}
                  />
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

              {/* Conversion Status */}
              {(selectedRfq.estimate_number || selectedRfq.invoice_number) && (
                <div className="detail-section">
                  <h3>📄 Conversion Status</h3>
                  <div className="detail-grid">
                    {selectedRfq.estimate_number && (
                      <div className="detail-item">
                        <label>Estimate</label>
                        <span style={{ color: '#3b82f6', fontWeight: 'bold' }}>
                          {selectedRfq.estimate_number}
                        </span>
                      </div>
                    )}
                    {selectedRfq.invoice_number && (
                      <div className="detail-item">
                        <label>Invoice</label>
                        <span style={{ color: '#10b981', fontWeight: 'bold' }}>
                          {selectedRfq.invoice_number}
                        </span>
                      </div>
                    )}
                    {selectedRfq.quoted_value && (
                      <div className="detail-item">
                        <label>Quoted Value</label>
                        <span>{formatCurrency(selectedRfq.quoted_value, selectedRfq.manual_currency || 'USD')}</span>
                      </div>
                    )}
                    {selectedRfq.invoiced_value && (
                      <div className="detail-item">
                        <label>Invoiced Value</label>
                        <span>{formatCurrency(selectedRfq.invoiced_value, selectedRfq.manual_currency || 'USD')}</span>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>

            <div className="modal-footer">
              {/* Conversion Buttons - Only show if not already converted */}
              {!selectedRfq.invoice_number && (
                <>
                  {!selectedRfq.estimate_number && selectedRfq.status !== 'won' && (
                    <button 
                      className="btn"
                      style={{ backgroundColor: '#3b82f6', color: 'white' }}
                      onClick={() => openConvertModal("estimate")}
                    >
                      📋 Create Estimate
                    </button>
                  )}
                  {selectedRfq.status !== 'won' && (
                    <button 
                      className="btn"
                      style={{ backgroundColor: '#10b981', color: 'white' }}
                      onClick={() => openConvertModal("invoice")}
                    >
                      💰 Create Invoice
                    </button>
                  )}
                </>
              )}
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

      {/* Conversion Modal */}
      {showConvertModal && selectedRfq && (
        <div className="modal-overlay" onClick={() => setShowConvertModal(false)}>
          <div className="modal-content" style={{ maxWidth: '500px' }} onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>
                {convertType === "estimate" ? "📋 Create Estimate" : "💰 Create Invoice"}
              </h2>
              <button className="modal-close" onClick={() => setShowConvertModal(false)}>×</button>
            </div>
            
            <div className="modal-body">
              {/* RFQ Summary */}
              <div style={{ 
                backgroundColor: '#f0fdf4', 
                padding: '12px', 
                borderRadius: '8px', 
                marginBottom: '16px',
                border: '1px solid #bbf7d0'
              }}>
                <div style={{ fontWeight: 'bold', marginBottom: '4px' }}>
                  {selectedRfq.title || selectedRfq.project_name || 'Untitled RFQ'}
                </div>
                <div style={{ fontSize: '0.9rem', color: '#666' }}>
                  Value: {formatCurrency(selectedRfq.manual_value || selectedRfq.extracted_value, selectedRfq.manual_currency || 'USD')}
                  {selectedRfq.sample_size && ` • ${selectedRfq.sample_size} completes`}
                  {selectedRfq.methodology && ` • ${selectedRfq.methodology}`}
                </div>
              </div>

              {/* Customer Selection */}
              <div className="form-group" style={{ marginBottom: '16px' }}>
                <label style={{ display: 'block', marginBottom: '4px', fontWeight: '500' }}>
                  Customer *
                </label>
                <select
                  value={conversionForm.customer_id}
                  onChange={(e) => setConversionForm(prev => ({ ...prev, customer_id: e.target.value }))}
                  style={{ 
                    width: '100%', 
                    padding: '8px 12px', 
                    borderRadius: '6px', 
                    border: '1px solid #d1d5db'
                  }}
                >
                  <option value="">Select customer...</option>
                  {customers.map(c => (
                    <option key={c._id} value={c._id}>
                      {c.name} {c.email ? `(${c.email})` : ''}
                    </option>
                  ))}
                </select>
                <small style={{ color: '#666' }}>
                  Will auto-match from RFQ if left empty
                </small>
              </div>

              {/* Unit Price */}
              <div className="form-group" style={{ marginBottom: '16px' }}>
                <label style={{ display: 'block', marginBottom: '4px', fontWeight: '500' }}>
                  Unit Price (per complete)
                </label>
                <input
                  type="number"
                  step="0.01"
                  value={conversionForm.unit_price}
                  onChange={(e) => setConversionForm(prev => ({ ...prev, unit_price: e.target.value }))}
                  placeholder="Auto-calculated from RFQ value"
                  style={{ 
                    width: '100%', 
                    padding: '8px 12px', 
                    borderRadius: '6px', 
                    border: '1px solid #d1d5db'
                  }}
                />
              </div>

              {/* Tax & Discount Row */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginBottom: '16px' }}>
                <div className="form-group">
                  <label style={{ display: 'block', marginBottom: '4px', fontWeight: '500' }}>
                    Tax %
                  </label>
                  <input
                    type="number"
                    value={conversionForm.tax_percent}
                    onChange={(e) => setConversionForm(prev => ({ ...prev, tax_percent: parseFloat(e.target.value) || 0 }))}
                    style={{ 
                      width: '100%', 
                      padding: '8px 12px', 
                      borderRadius: '6px', 
                      border: '1px solid #d1d5db'
                    }}
                  />
                </div>
                <div className="form-group">
                  <label style={{ display: 'block', marginBottom: '4px', fontWeight: '500' }}>
                    Discount %
                  </label>
                  <input
                    type="number"
                    value={conversionForm.discount_percent}
                    onChange={(e) => setConversionForm(prev => ({ ...prev, discount_percent: parseFloat(e.target.value) || 0 }))}
                    style={{ 
                      width: '100%', 
                      padding: '8px 12px', 
                      borderRadius: '6px', 
                      border: '1px solid #d1d5db'
                    }}
                  />
                </div>
              </div>

              {/* Due Days */}
              <div className="form-group" style={{ marginBottom: '16px' }}>
                <label style={{ display: 'block', marginBottom: '4px', fontWeight: '500' }}>
                  {convertType === "estimate" ? "Valid for (days)" : "Payment Due (days)"}
                </label>
                <input
                  type="number"
                  value={conversionForm.due_days}
                  onChange={(e) => setConversionForm(prev => ({ ...prev, due_days: parseInt(e.target.value) || 30 }))}
                  style={{ 
                    width: '100%', 
                    padding: '8px 12px', 
                    borderRadius: '6px', 
                    border: '1px solid #d1d5db'
                  }}
                />
              </div>

              {/* Notes */}
              <div className="form-group" style={{ marginBottom: '16px' }}>
                <label style={{ display: 'block', marginBottom: '4px', fontWeight: '500' }}>
                  Notes
                </label>
                <textarea
                  value={conversionForm.notes}
                  onChange={(e) => setConversionForm(prev => ({ ...prev, notes: e.target.value }))}
                  placeholder={`Additional notes for the ${convertType}...`}
                  rows={3}
                  style={{ 
                    width: '100%', 
                    padding: '8px 12px', 
                    borderRadius: '6px', 
                    border: '1px solid #d1d5db'
                  }}
                />
              </div>
            </div>

            <div className="modal-footer">
              <button 
                className="btn btn-secondary"
                onClick={() => setShowConvertModal(false)}
                disabled={converting}
              >
                Cancel
              </button>
              <button 
                className="btn"
                style={{ 
                  backgroundColor: convertType === "estimate" ? '#3b82f6' : '#10b981', 
                  color: 'white' 
                }}
                onClick={handleConversion}
                disabled={converting}
              >
                {converting ? 'Creating...' : `Create ${convertType === "estimate" ? "Estimate" : "Invoice"}`}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default RFQ
