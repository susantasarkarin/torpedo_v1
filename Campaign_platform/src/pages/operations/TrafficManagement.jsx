"use client"
import { useEffect, useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
import { API_BASE_URL } from "../../config"
import "./TrafficManagement.css"

// Status badge color mapping
const statusColors = {
  INCOMPLETE: { bg: "#fff3e0", color: "#e65100" },
  COMPLETE: { bg: "#e8f5e9", color: "#2e7d32" },
  TERMINATED: { bg: "#ffebee", color: "#c62828" },
  QUOTAFULL: { bg: "#f3e5f5", color: "#7b1fa2" },
}

export default function TrafficManagement() {
  const navigate = useNavigate()
  const [records, setRecords] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [search, setSearch] = useState("")
  const [statusFilter, setStatusFilter] = useState("")
  const [currentPage, setCurrentPage] = useState(1)
  const [recordsPerPage, setRecordsPerPage] = useState(20)
  const [totalRecords, setTotalRecords] = useState(0)
  const [totalPages, setTotalPages] = useState(0)
  const [stats, setStats] = useState({ total: 0, by_status: {} })
  const [expandedRow, setExpandedRow] = useState(null)
  const [selectedIds, setSelectedIds] = useState([])
  const [deleting, setDeleting] = useState(false)

  // Fetch traffic records
  const fetchRecords = async () => {
    const sessionId = localStorage.getItem("session_id")
    if (!sessionId) {
      navigate("/login")
      return
    }

    setLoading(true)
    setError(null)

    try {
      const params = new URLSearchParams({
        page: currentPage,
        page_size: recordsPerPage,
      })

      if (statusFilter) params.append("status", statusFilter)
      if (search) params.append("search", search)

      const res = await fetch(`${API_BASE_URL}/api/traffic/list?${params}`, {
        headers: {
          "Content-Type": "application/json",
          Authorization: sessionId,
        },
      })

      if (res.status === 401) {
        alert("Session expired. Please login again.")
        localStorage.removeItem("session_id")
        navigate("/login")
        return
      }

      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || "Failed to load traffic records")

      setRecords(data.records || [])
      setTotalRecords(data.pagination?.total || 0)
      setTotalPages(data.pagination?.total_pages || 0)
    } catch (e) {
      setError(e.message || "Failed to load traffic records")
    } finally {
      setLoading(false)
    }
  }

  // Fetch traffic stats
  const fetchStats = async () => {
    const sessionId = localStorage.getItem("session_id")
    if (!sessionId) return

    try {
      const res = await fetch(`${API_BASE_URL}/api/traffic/stats`, {
        headers: {
          "Content-Type": "application/json",
          Authorization: sessionId,
        },
      })

      if (res.ok) {
        const data = await res.json()
        setStats(data)
      }
    } catch (e) {
      console.error("Failed to load stats:", e)
    }
  }

  useEffect(() => {
    fetchRecords()
    fetchStats()
  }, [currentPage, recordsPerPage, statusFilter])

  // Auto-refresh every 30 seconds
  useEffect(() => {
    const interval = setInterval(() => {
      fetchRecords()
      fetchStats()
    }, 30000) // 30 seconds
    return () => clearInterval(interval)
  }, [currentPage, recordsPerPage, statusFilter, search])

  // Handle search with debounce
  useEffect(() => {
    const timer = setTimeout(() => {
      setCurrentPage(1)
      fetchRecords()
    }, 500)
    return () => clearTimeout(timer)
  }, [search])

  const formatDate = (dateStr) => {
    if (!dateStr) return "N/A"
    return new Date(dateStr).toLocaleString()
  }

  const handleRefresh = () => {
    fetchRecords()
    fetchStats()
  }

  const toggleExpandRow = (id) => {
    setExpandedRow(expandedRow === id ? null : id)
  }

  // Handle checkbox selection
  const handleSelectRecord = (id, e) => {
    e.stopPropagation() // Prevent row expansion when clicking checkbox
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    )
  }

  // Handle select all on current page
  const handleSelectAll = (e) => {
    if (e.target.checked) {
      setSelectedIds(records.map((r) => r._id))
    } else {
      setSelectedIds([])
    }
  }

  // Delete selected records
  const handleDeleteSelected = async () => {
    if (selectedIds.length === 0) return
    
    if (!window.confirm(`Are you sure you want to delete ${selectedIds.length} record(s)?`)) {
      return
    }

    const sessionId = localStorage.getItem("session_id")
    if (!sessionId) {
      navigate("/login")
      return
    }

    setDeleting(true)
    try {
      const res = await fetch(`${API_BASE_URL}/api/traffic/delete`, {
        method: "DELETE",
        headers: {
          "Content-Type": "application/json",
          Authorization: sessionId,
        },
        body: JSON.stringify({ ids: selectedIds }),
      })

      if (res.status === 401) {
        alert("Session expired. Please login again.")
        localStorage.removeItem("session_id")
        navigate("/login")
        return
      }

      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || "Failed to delete records")

      alert(`Successfully deleted ${data.deleted_count} record(s)`)
      setSelectedIds([])
      fetchRecords()
      fetchStats()
    } catch (e) {
      alert("Error deleting records: " + e.message)
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="traffic-management-container">
      <div className="traffic-header">
        <div>
          <h1>🚦 Traffic Management</h1>
          <p>Monitor and track survey traffic records</p>
        </div>
        <button onClick={handleRefresh} disabled={loading} className="refresh-btn">
          {loading ? "⏳ Loading..." : "🔄 Refresh"}
        </button>
      </div>

      {/* Stats Cards */}
      <div className="traffic-stats">
        <div className="stat-card total">
          <span className="stat-value">{stats.total || 0}</span>
          <span className="stat-label">Total Records</span>
        </div>
        {Object.entries(stats.by_status || {}).map(([status, count]) => (
          <div
            key={status}
            className="stat-card clickable"
            style={{
              backgroundColor: statusColors[status]?.bg || "#f5f5f5",
              borderColor: statusColors[status]?.color || "#666",
            }}
            onClick={() => setStatusFilter(status === statusFilter ? "" : status)}
          >
            <span className="stat-value" style={{ color: statusColors[status]?.color || "#333" }}>
              {count}
            </span>
            <span className="stat-label">{status}</span>
          </div>
        ))}
      </div>

      {/* Filters */}
      <div className="traffic-filters">
        <div className="search-box">
          <input
            type="text"
            placeholder="Search by Vendor ID, Respondent ID, Country..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="filter-controls">
          {selectedIds.length > 0 && (
            <button
              onClick={handleDeleteSelected}
              disabled={deleting}
              className="delete-selected-btn"
            >
              {deleting ? "⏳ Deleting..." : `🗑️ Delete (${selectedIds.length})`}
            </button>
          )}
          <select
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value)
              setCurrentPage(1)
            }}
          >
            <option value="">All Statuses</option>
            <option value="INCOMPLETE">INCOMPLETE</option>
            <option value="COMPLETE">COMPLETE</option>
            <option value="TERMINATED">TERMINATED</option>
            <option value="QUOTAFULL">QUOTAFULL</option>
          </select>
          <select
            value={recordsPerPage}
            onChange={(e) => {
              setRecordsPerPage(Number(e.target.value))
              setCurrentPage(1)
            }}
          >
            <option value={10}>10 per page</option>
            <option value={20}>20 per page</option>
            <option value={50}>50 per page</option>
            <option value={100}>100 per page</option>
          </select>
        </div>
      </div>

      {error && <div className="traffic-error">❌ {error}</div>}

      {/* Table */}
      {loading && records.length === 0 ? (
        <div className="traffic-loading">
          <div className="loading-spinner"></div>
          <p>Loading traffic records...</p>
        </div>
      ) : records.length === 0 ? (
        <div className="traffic-empty">
          <p>📭 No traffic records found</p>
          {(search || statusFilter) && (
            <button
              onClick={() => {
                setSearch("")
                setStatusFilter("")
              }}
              className="clear-filters-btn"
            >
              Clear Filters
            </button>
          )}
        </div>
      ) : (
        <>
          <div className="traffic-table-container">
            <table className="traffic-table">
              <thead>
                <tr>
                  <th className="checkbox-cell">
                    <input
                      type="checkbox"
                      checked={records.length > 0 && selectedIds.length === records.length}
                      onChange={handleSelectAll}
                    />
                  </th>
                  <th></th>
                  <th>Record ID</th>
                  <th>Created At</th>
                  <th>Vendor ID</th>
                  <th>Country</th>
                  <th>Respondent ID</th>
                  <th>Survey ID</th>
                  <th>Status</th>
                  <th>Updated At</th>
                </tr>
              </thead>
              <tbody>
                {records.map((record) => (
                  <>
                    <tr key={record._id} onClick={() => toggleExpandRow(record._id)} className="clickable-row">
                      <td className="checkbox-cell" onClick={(e) => e.stopPropagation()}>
                        <input
                          type="checkbox"
                          checked={selectedIds.includes(record._id)}
                          onChange={(e) => handleSelectRecord(record._id, e)}
                        />
                      </td>
                      <td className="expand-cell">{expandedRow === record._id ? "▼" : "▶"}</td>
                      <td className="record-id" title={record._id}>{record._id?.slice(-8) || "N/A"}</td>
                      <td>{formatDate(record.createdAt)}</td>
                      <td>{record.vendorId || "N/A"}</td>
                      <td>{record.countryCode || "N/A"}</td>
                      <td className="respondent-id">{record.respondentId || "N/A"}</td>
                      <td>{record.assignedSurveyId || "—"}</td>
                      <td>
                        <span
                          className="status-badge"
                          style={{
                            backgroundColor: statusColors[record.status]?.bg || "#f5f5f5",
                            color: statusColors[record.status]?.color || "#333",
                          }}
                        >
                          {record.status}
                        </span>
                      </td>
                      <td>{formatDate(record.updatedAt)}</td>
                    </tr>
                    {expandedRow === record._id && (
                      <tr className="expanded-row">
                        <td colSpan="10">
                          <div className="expanded-content">
                            <div className="expanded-section">
                              <h4>📋 Record Details</h4>
                              <div className="detail-grid">
                                <div>
                                  <strong>Record ID:</strong> {record._id}
                                </div>
                                <div>
                                  <strong>Assigned At:</strong> {formatDate(record.assignedAt)}
                                </div>
                                <div>
                                  <strong>Completed At:</strong> {formatDate(record.completedAt)}
                                </div>
                              </div>
                            </div>
                            {record.redirectUrl && (
                              <div className="expanded-section">
                                <h4>🔗 Redirect URL</h4>
                                <code className="redirect-url">{record.redirectUrl}</code>
                              </div>
                            )}
                            {record.params && Object.keys(record.params).length > 0 && (
                              <div className="expanded-section">
                                <h4>📦 Raw Parameters</h4>
                                <pre className="raw-payload">{JSON.stringify(record.params, null, 2)}</pre>
                              </div>
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          <div className="traffic-pagination">
            <div className="pagination-info">
              Showing {(currentPage - 1) * recordsPerPage + 1} to{" "}
              {Math.min(currentPage * recordsPerPage, totalRecords)} of {totalRecords} records
            </div>
            <div className="pagination-controls">
              <button
                onClick={() => setCurrentPage(1)}
                disabled={currentPage === 1 || loading}
                className="pagination-btn"
              >
                ⬅️ First
              </button>
              <button
                onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                disabled={currentPage === 1 || loading}
                className="pagination-btn"
              >
                ◀ Prev
              </button>
              <span className="page-indicator">
                Page {currentPage} of {totalPages}
              </span>
              <button
                onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                disabled={currentPage >= totalPages || loading}
                className="pagination-btn"
              >
                Next ▶
              </button>
              <button
                onClick={() => setCurrentPage(totalPages)}
                disabled={currentPage >= totalPages || loading}
                className="pagination-btn"
              >
                Last ➡️
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
