"use client"

import { useState, useEffect } from "react"
import { API_BASE_URL } from "../../config"
import { Link } from "react-router-dom"
import "./RFQ.css"

// Helper to get auth token - handles both storage methods
const getAuthToken = () => localStorage.getItem("session_id") || sessionStorage.getItem("token")

function RFQ() {
  const [rfqs, setRfqs] = useState([])
  const [loading, setLoading] = useState(true)
  const [stats, setStats] = useState(null)
  const [filters, setFilters] = useState({
    status: "",
    priority: "",
    search: ""
  })
  const [editingValue, setEditingValue] = useState(null) // { rfq_id, value }
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState({ type: "", text: "" })

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

  const formatCurrency = (value, currency = "USD") => {
    if (!value && value !== 0) return "—"
    const symbols = { USD: "$", INR: "₹", EUR: "€", GBP: "£" }
    const symbol = symbols[currency] || "$"
    return `${symbol}${value.toLocaleString()}`
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
                  <th>Title / Subject</th>
                  <th>Lead</th>
                  <th>Value</th>
                  <th>Priority</th>
                  <th>Status</th>
                  <th>Detected</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {rfqs.map((rfq) => (
                  <tr key={rfq.rfq_id}>
                    <td className="rfq-title-cell">
                      <div className="rfq-title">{rfq.title || "Untitled RFQ"}</div>
                      {rfq.source_email?.subject && (
                        <div className="rfq-subtitle">{rfq.source_email.subject}</div>
                      )}
                    </td>
                    <td>
                      <div className="rfq-lead">
                        <Link to={`/admin/sales/leads/${rfq.lead_id}`} className="lead-link">
                          {rfq.client_name || rfq.lead_email || "Unknown"}
                        </Link>
                        {rfq.client_company && (
                          <div className="rfq-company">{rfq.client_company}</div>
                        )}
                      </div>
                    </td>
                    <td>
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
                          onClick={() => setEditingValue({ rfq_id: rfq.rfq_id, value: rfq.extracted_value || 0 })}
                          title="Click to edit value"
                        >
                          {formatCurrency(rfq.extracted_value, rfq.currency)}
                          {rfq.value_override && <span className="override-badge">✎</span>}
                        </div>
                      )}
                    </td>
                    <td>
                      <span 
                        className="priority-badge"
                        style={getPriorityColor(rfq.priority)}
                      >
                        {rfq.priority || "medium"}
                      </span>
                    </td>
                    <td>
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
                    <td className="rfq-date">{formatDate(rfq.detected_at)}</td>
                    <td>
                      <div className="rfq-actions">
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
    </div>
  )
}

export default RFQ
