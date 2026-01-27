"use client"
import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { API_BASE_URL } from "../../config"
import "./CPXCallbackLogs.css"
import { buildApiUrl } from "../../config"

export default function CPXCallbackLogs() {
  const navigate = useNavigate()
  const [logs, setLogs] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [currentPage, setCurrentPage] = useState(1)
  const [logsPerPage, setLogsPerPage] = useState(50)
  const [totalLogs, setTotalLogs] = useState(0)
  const [totalPages, setTotalPages] = useState(0)
  const [stats, setStats] = useState({ total: 0, success: 0, failed: 0 })
  const [successFilter, setSuccessFilter] = useState("all")
  const [expandedRow, setExpandedRow] = useState(null)
  const [clearing, setClearing] = useState(false)

  // Fetch logs
  const fetchLogs = async () => {
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
        page_size: logsPerPage,
      })

      if (successFilter !== "all") {
        params.append("success_filter", successFilter)
      }

      const res = await fetch(buildApiUrl(`/api/cpx-callback-logs?${params}`), {
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
      if (!res.ok) throw new Error(data.detail || "Failed to load logs")

      setLogs(data.logs || [])
      setTotalLogs(data.pagination?.total || 0)
      setTotalPages(data.pagination?.total_pages || 0)
      setStats(data.stats || { total: 0, success: 0, failed: 0 })
    } catch (e) {
      setError(e.message || "Failed to load logs")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchLogs()
  }, [currentPage, logsPerPage, successFilter])

  // Auto-refresh every 10 seconds
  useEffect(() => {
    const interval = setInterval(() => {
      fetchLogs()
    }, 10000)
    return () => clearInterval(interval)
  }, [currentPage, logsPerPage, successFilter])

  const formatDate = (dateStr) => {
    if (!dateStr) return "N/A"
    return new Date(dateStr).toLocaleString()
  }

  const handleRefresh = () => {
    fetchLogs()
  }

  const toggleExpandRow = (id) => {
    setExpandedRow(expandedRow === id ? null : id)
  }

  const handleClearLogs = async () => {
    if (!window.confirm("Are you sure you want to clear all callback logs?")) {
      return
    }

    const sessionId = localStorage.getItem("session_id")
    if (!sessionId) {
      navigate("/login")
      return
    }

    setClearing(true)
    try {
      const res = await fetch(buildApiUrl(`/api/cpx-callback-logs`), {
        method: "DELETE",
        headers: {
          "Content-Type": "application/json",
          Authorization: sessionId,
        },
      })

      if (res.ok) {
        const data = await res.json()
        alert(`Cleared ${data.deleted_count} logs`)
        fetchLogs()
      } else {
        const data = await res.json()
        throw new Error(data.detail || "Failed to clear logs")
      }
    } catch (e) {
      alert("Error clearing logs: " + e.message)
    } finally {
      setClearing(false)
    }
  }

  return (
    <div className="cpx-logs-container">
      <div className="cpx-logs-header">
        <div>
          <h1>📊 CPX Callback Logs</h1>
          <p>Monitor incoming CPX survey callbacks and redirects</p>
        </div>
        <div className="header-actions">
          <button onClick={handleClearLogs} disabled={clearing} className="clear-btn">
            {clearing ? "⏳ Clearing..." : "🗑️ Clear Logs"}
          </button>
          <button onClick={handleRefresh} disabled={loading} className="refresh-btn">
            {loading ? "⏳ Loading..." : "🔄 Refresh"}
          </button>
        </div>
      </div>

      {/* Stats Cards */}
      <div className="cpx-logs-stats">
        <div className="stat-card total">
          <span className="stat-value">{stats.total || 0}</span>
          <span className="stat-label">Total Callbacks</span>
        </div>
        <div
          className="stat-card success clickable"
          onClick={() => setSuccessFilter(successFilter === "true" ? "all" : "true")}
        >
          <span className="stat-value">{stats.success || 0}</span>
          <span className="stat-label">✅ Successful</span>
        </div>
        <div
          className="stat-card failed clickable"
          onClick={() => setSuccessFilter(successFilter === "false" ? "all" : "false")}
        >
          <span className="stat-value">{stats.failed || 0}</span>
          <span className="stat-label">❌ Failed</span>
        </div>
      </div>

      {/* Filters */}
      <div className="cpx-logs-filters">
        <select
          value={successFilter}
          onChange={(e) => {
            setSuccessFilter(e.target.value)
            setCurrentPage(1)
          }}
        >
          <option value="all">All Callbacks</option>
          <option value="true">Successful Only</option>
          <option value="false">Failed Only</option>
        </select>
        <select
          value={logsPerPage}
          onChange={(e) => {
            setLogsPerPage(Number(e.target.value))
            setCurrentPage(1)
          }}
        >
          <option value={20}>20 per page</option>
          <option value={50}>50 per page</option>
          <option value={100}>100 per page</option>
        </select>
      </div>

      {error && <div className="cpx-logs-error">❌ {error}</div>}

      {/* Table */}
      {loading && logs.length === 0 ? (
        <div className="cpx-logs-loading">
          <div className="loading-spinner"></div>
          <p>Loading callback logs...</p>
        </div>
      ) : logs.length === 0 ? (
        <div className="cpx-logs-empty">
          <p>📭 No callback logs found</p>
          <p className="hint">Callbacks will appear here when CPX sends responses back</p>
        </div>
      ) : (
        <>
          <div className="cpx-logs-table-container">
            <table className="cpx-logs-table">
              <thead>
                <tr>
                  <th></th>
                  <th>Timestamp</th>
                  <th>RID Received</th>
                  <th>Decoded SFWID</th>
                  <th>Status</th>
                  <th>Vendor ID</th>
                  <th>Respondent ID</th>
                  <th>Result</th>
                </tr>
              </thead>
              <tbody>
                {logs.map((log) => (
                  <>
                    <tr
                      key={log._id}
                      onClick={() => toggleExpandRow(log._id)}
                      className={`clickable-row ${log.success ? "success-row" : "failed-row"}`}
                    >
                      <td className="expand-cell">{expandedRow === log._id ? "▼" : "▶"}</td>
                      <td>{formatDate(log.timestamp)}</td>
                      <td className="rid-cell" title={log.rid_received}>
                        {log.rid_received?.slice(0, 20)}...
                      </td>
                      <td className="sfwid-cell">{log.decoded_sfwid || "—"}</td>
                      <td>
                        <span className={`status-badge ${log.new_status?.toLowerCase()}`}>
                          {log.new_status || log.status_code || "—"}
                        </span>
                      </td>
                      <td>{log.vendor_id || "—"}</td>
                      <td>{log.respondent_id || "—"}</td>
                      <td>
                        {log.success ? (
                          <span className="result-success">✅ Redirected</span>
                        ) : (
                          <span className="result-failed">❌ Failed</span>
                        )}
                      </td>
                    </tr>
                    {expandedRow === log._id && (
                      <tr className="expanded-row">
                        <td colSpan="8">
                          <div className="expanded-content">
                            <div className="expanded-section">
                              <h4>📋 Callback Details</h4>
                              <div className="detail-grid">
                                <div>
                                  <strong>Log ID:</strong> {log._id}
                                </div>
                                <div>
                                  <strong>Traffic Found:</strong> {log.traffic_found ? "Yes" : "No"}
                                </div>
                                <div>
                                  <strong>Traffic ID:</strong> {log.traffic_id || "—"}
                                </div>
                                <div>
                                  <strong>Vendor Found:</strong> {log.vendor_found ? "Yes" : "No"}
                                </div>
                                <div>
                                  <strong>Vendor Name:</strong> {log.vendor_name || "—"}
                                </div>
                                <div>
                                  <strong>Redirect Type:</strong> {log.redirect_type || "—"}
                                </div>
                              </div>
                            </div>
                            <div className="expanded-section">
                              <h4>🔗 Full RID Received</h4>
                              <code className="full-rid">{log.rid_received || "—"}</code>
                            </div>
                            <div className="expanded-section">
                              <h4>📥 Callback URL</h4>
                              <code className="callback-url">{log.callback_url || "—"}</code>
                            </div>
                            <div className="expanded-section">
                              <h4>🚀 Vendor Redirect URL</h4>
                              {log.vendor_redirect_url ? (
                                <a
                                  href={log.vendor_redirect_url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="redirect-url"
                                >
                                  {log.vendor_redirect_url}
                                </a>
                              ) : (
                                <code className="redirect-url">—</code>
                              )}
                            </div>
                            {log.error && (
                              <div className="expanded-section error-section">
                                <h4>❌ Error</h4>
                                <code className="error-message">{log.error}</code>
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
          <div className="cpx-logs-pagination">
            <div className="pagination-info">
              Showing {(currentPage - 1) * logsPerPage + 1} to{" "}
              {Math.min(currentPage * logsPerPage, totalLogs)} of {totalLogs} logs
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
