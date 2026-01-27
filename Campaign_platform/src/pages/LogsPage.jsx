import { useState, useEffect, useRef } from "react"
import { API_BASE_URL, buildApiUrl } from "../config"
import "./LogsPage.css"

// Helper to get auth token - handles both storage methods
const getAuthToken = () => localStorage.getItem("session_id") || sessionStorage.getItem("token")

function LogsPage() {
  const [logs, setLogs] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [autoRefresh, setAutoRefresh] = useState(false)
  const [lines, setLines] = useState(1000)
  const [fileInfo, setFileInfo] = useState(null)
  const logContainerRef = useRef(null)

  useEffect(() => {
    fetchLogs()
  }, [lines])

  useEffect(() => {
    let interval = null
    if (autoRefresh) {
      interval = setInterval(() => {
        fetchLogs()
      }, 5000) // Refresh every 5 seconds
    }
    return () => {
      if (interval) clearInterval(interval)
    }
  }, [autoRefresh, lines])

  const fetchLogs = async () => {
    try {
      setLoading(true)
      setError(null)
      const token = getAuthToken()
      
      const response = await fetch(buildApiUrl(`/settings/logs?lines=${lines}`), {
        headers: { Authorization: token }
      })
      
      const data = await response.json()
      
      if (data.success) {
        setLogs(data.logs || [])
        setFileInfo({
          filePath: data.file_path,
          totalLines: data.total_lines,
          returnedLines: data.returned_lines,
          fileSize: data.file_size,
          lastModified: data.last_modified
        })
      } else {
        setError(data.message || "Failed to fetch logs")
        setLogs([])
      }
    } catch (err) {
      setError(`Error fetching logs: ${err.message}`)
      setLogs([])
    } finally {
      setLoading(false)
    }
  }

  const handleRefresh = () => {
    fetchLogs()
  }

  const handleClear = () => {
    setLogs([])
  }

  const formatFileSize = (bytes) => {
    if (bytes === 0) return "0 Bytes"
    const k = 1024
    const sizes = ["Bytes", "KB", "MB", "GB"]
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + " " + sizes[i]
  }

  const formatDate = (dateString) => {
    if (!dateString) return "N/A"
    try {
      const date = new Date(dateString)
      return date.toLocaleString()
    } catch {
      return dateString
    }
  }

  // Auto-scroll to bottom when new logs arrive
  useEffect(() => {
    if (logContainerRef.current && logs.length > 0) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight
    }
  }, [logs])

  return (
    <div className="logs-page">
      <div className="logs-header">
        <div>
          <h1>Deployment Logs</h1>
          <p className="logs-subtitle">View cron deployment logs</p>
        </div>
        <div className="logs-actions">
          <div className="logs-controls">
            <label>
              Lines to show:
              <input
                type="number"
                min="100"
                max="10000"
                step="100"
                value={lines}
                onChange={(e) => setLines(parseInt(e.target.value) || 1000)}
                className="lines-input"
              />
            </label>
            <label className="auto-refresh-label">
              <input
                type="checkbox"
                checked={autoRefresh}
                onChange={(e) => setAutoRefresh(e.target.checked)}
              />
              Auto-refresh (5s)
            </label>
          </div>
          <div className="logs-buttons">
            <button onClick={handleRefresh} disabled={loading} className="refresh-btn">
              {loading ? "Loading..." : "🔄 Refresh"}
            </button>
            <button onClick={handleClear} className="clear-btn">
              Clear View
            </button>
          </div>
        </div>
      </div>

      {fileInfo && (
        <div className="logs-info">
          <div className="info-item">
            <span className="info-label">File:</span>
            <span className="info-value">{fileInfo.filePath}</span>
          </div>
          <div className="info-item">
            <span className="info-label">Total Lines:</span>
            <span className="info-value">{fileInfo.totalLines?.toLocaleString() || "N/A"}</span>
          </div>
          <div className="info-item">
            <span className="info-label">Showing:</span>
            <span className="info-value">{fileInfo.returnedLines?.toLocaleString() || "N/A"}</span>
          </div>
          <div className="info-item">
            <span className="info-label">File Size:</span>
            <span className="info-value">{formatFileSize(fileInfo.fileSize)}</span>
          </div>
          <div className="info-item">
            <span className="info-label">Last Modified:</span>
            <span className="info-value">{formatDate(fileInfo.lastModified)}</span>
          </div>
        </div>
      )}

      {error && (
        <div className="logs-error">
          <span>⚠️</span> {error}
        </div>
      )}

      <div className="logs-container" ref={logContainerRef}>
        {loading && logs.length === 0 ? (
          <div className="logs-loading">
            <div className="spinner"></div>
            <p>Loading logs...</p>
          </div>
        ) : logs.length === 0 ? (
          <div className="logs-empty">
            <p>No logs available</p>
          </div>
        ) : (
          <div className="logs-content">
            {logs.map((line, index) => {
              // Simple log level detection for styling
              const isError = line.toLowerCase().includes("error") || line.toLowerCase().includes("failed")
              const isWarning = line.toLowerCase().includes("warning") || line.toLowerCase().includes("warn")
              const isSuccess = line.toLowerCase().includes("success") || line.toLowerCase().includes("✅")
              
              return (
                <div
                  key={index}
                  className={`log-line ${isError ? "log-error" : isWarning ? "log-warning" : isSuccess ? "log-success" : ""}`}
                >
                  <span className="log-line-number">{index + 1}</span>
                  <span className="log-line-content">{line}</span>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}

export default LogsPage


