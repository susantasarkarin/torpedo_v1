"use client"

import { useState, useEffect, useCallback } from "react"
import { API_BASE_URL } from "../../config"
import {
  LogIn,
  Send,
  Users,
  BarChart3,
  Clock,
  AlertCircle,
  CheckCircle,
  XCircle,
  Search,
  Plus,
  MessageSquare,
  Loader,
  RefreshCw,
  Calendar,
  TrendingUp
} from "lucide-react"

// ============== STYLES ==============
const styles = {
  page: {
    height: "100vh",
    backgroundColor: "#f8fafc",
    padding: "16px",
    overflow: "auto",
    display: "flex",
    flexDirection: "column"
  },
  header: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: "16px",
    flexShrink: 0
  },
  title: {
    fontSize: "24px",
    fontWeight: "700",
    color: "#1e293b",
    margin: 0
  },
  subtitle: {
    fontSize: "12px",
    color: "#64748b",
    marginTop: "4px"
  },
  container: {
    display: "flex",
    flexDirection: "column",
    gap: "16px",
    flex: 1,
    minHeight: 0
  },
  section: {
    backgroundColor: "white",
    border: "1px solid #e2e8f0",
    borderRadius: "8px",
    padding: "16px",
    boxShadow: "0 1px 3px rgba(0, 0, 0, 0.1)"
  },
  sectionTitle: {
    fontSize: "14px",
    fontWeight: "600",
    color: "#1e293b",
    marginBottom: "12px",
    display: "flex",
    alignItems: "center",
    gap: "8px"
  },
  sessionStatus: {
    display: "flex",
    alignItems: "center",
    gap: "12px",
    padding: "12px",
    backgroundColor: "#f1f5f9",
    borderRadius: "6px",
    marginBottom: "12px"
  },
  statusBadge: {
    padding: "4px 8px",
    borderRadius: "4px",
    fontSize: "11px",
    fontWeight: "600",
    color: "white"
  },
  statusActive: {
    backgroundColor: "#10b981"
  },
  statusExpired: {
    backgroundColor: "#f59e0b"
  },
  statusInactive: {
    backgroundColor: "#6b7280"
  },
  button: {
    padding: "8px 16px",
    borderRadius: "6px",
    border: "none",
    fontSize: "12px",
    fontWeight: "600",
    cursor: "pointer",
    display: "flex",
    alignItems: "center",
    gap: "8px",
    transition: "all 0.2s"
  },
  buttonPrimary: {
    backgroundColor: "#0084ff",
    color: "white"
  },
  buttonSecondary: {
    backgroundColor: "#e2e8f0",
    color: "#1e293b"
  },
  statsGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
    gap: "12px",
    marginBottom: "12px"
  },
  statCard: {
    backgroundColor: "#f8fafc",
    border: "1px solid #e2e8f0",
    borderRadius: "6px",
    padding: "12px",
    textAlign: "center"
  },
  statValue: {
    fontSize: "20px",
    fontWeight: "700",
    color: "#0084ff",
    marginBottom: "4px"
  },
  statLabel: {
    fontSize: "11px",
    color: "#64748b",
    fontWeight: "500"
  },
  table: {
    width: "100%",
    borderCollapse: "collapse",
    fontSize: "12px"
  },
  tableHeader: {
    backgroundColor: "#f1f5f9",
    borderBottom: "2px solid #cbd5e1"
  },
  tableHeaderCell: {
    padding: "8px",
    textAlign: "left",
    fontWeight: "600",
    color: "#475569"
  },
  tableRow: {
    borderBottom: "1px solid #e2e8f0",
    hover: {
      backgroundColor: "#f8fafc"
    }
  },
  tableCell: {
    padding: "8px",
    color: "#475569"
  },
  rateLimitBar: {
    width: "100%",
    height: "6px",
    backgroundColor: "#e2e8f0",
    borderRadius: "3px",
    overflow: "hidden",
    marginTop: "4px"
  },
  rateLimitFill: {
    height: "100%",
    backgroundColor: "#0084ff",
    transition: "width 0.3s"
  },
  modal: {
    position: "fixed",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: "rgba(0, 0, 0, 0.5)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    zIndex: 1000
  },
  modalContent: {
    backgroundColor: "white",
    borderRadius: "8px",
    padding: "20px",
    maxWidth: "500px",
    width: "90%",
    maxHeight: "80vh",
    overflow: "auto"
  },
  formGroup: {
    marginBottom: "12px"
  },
  formLabel: {
    fontSize: "12px",
    fontWeight: "600",
    color: "#1e293b",
    marginBottom: "4px",
    display: "block"
  },
  formInput: {
    width: "100%",
    padding: "8px",
    border: "1px solid #cbd5e1",
    borderRadius: "4px",
    fontSize: "12px",
    fontFamily: "inherit"
  },
  activityLog: {
    maxHeight: "300px",
    overflowY: "auto",
    fontSize: "11px"
  },
  activityItem: {
    padding: "8px",
    borderBottom: "1px solid #e2e8f0",
    color: "#475569"
  },
  activityTime: {
    color: "#94a3b8",
    marginRight: "8px"
  }
}

// ============== SESSION STATUS COMPONENT ==============
function SessionStatus({ status, email, onLogin, onLogout, isLoading }) {
  const getStatusColor = () => {
    switch (status) {
      case "active":
        return styles.statusActive
      case "expired":
        return styles.statusExpired
      default:
        return styles.statusInactive
    }
  }

  const getStatusLabel = () => {
    switch (status) {
      case "active":
        return "✓ Logged In"
      case "expired":
        return "⚠ Session Expired"
      default:
        return "○ Not Connected"
    }
  }

  return (
    <div style={styles.sessionStatus}>
      <div style={{ flex: 1 }}>
        <div style={{ ...styles.statusBadge, ...getStatusColor() }}>
          {getStatusLabel()}
        </div>
        {email && <div style={{ fontSize: "11px", color: "#64748b", marginTop: "4px" }}>{email}</div>}
      </div>
      <div style={{ display: "flex", gap: "8px" }}>
        {status === "active" ? (
          <button
            style={{ ...styles.button, ...styles.buttonSecondary }}
            onClick={onLogout}
            disabled={isLoading}
          >
            <LogIn size={14} /> Logout
          </button>
        ) : (
          <button
            style={{ ...styles.button, ...styles.buttonPrimary }}
            onClick={onLogin}
            disabled={isLoading}
          >
            {isLoading ? <Loader size={14} /> : <LogIn size={14} />}
            {isLoading ? "Logging in..." : "Login with Browser"}
          </button>
        )}
      </div>
    </div>
  )
}

// ============== DAILY STATS COMPONENT ==============
function DailyStatsCards({ stats, rateLimits }) {
  return (
    <div style={styles.statsGrid}>
      <div style={styles.statCard}>
        <Users size={16} style={{ margin: "0 auto 6px", color: "#0084ff" }} />
        <div style={styles.statValue}>{stats.connections_sent || 0}</div>
        <div style={styles.statLabel}>Connections Sent</div>
        <div style={{ ...styles.rateLimitBar, marginTop: "8px" }}>
          <div
            style={{
              ...styles.rateLimitFill,
              width: `${((stats.connections_sent || 0) / rateLimits.daily_connection_limit) * 100}%`,
              backgroundColor: ((stats.connections_sent || 0) / rateLimits.daily_connection_limit) > 0.8 ? "#f59e0b" : "#0084ff"
            }}
          />
        </div>
        <div style={{ fontSize: "10px", color: "#64748b", marginTop: "4px" }}>
          {rateLimits.daily_connection_limit - (stats.connections_sent || 0)} remaining
        </div>
      </div>

      <div style={styles.statCard}>
        <CheckCircle size={16} style={{ margin: "0 auto 6px", color: "#10b981" }} />
        <div style={styles.statValue}>{stats.connections_accepted || 0}</div>
        <div style={styles.statLabel}>Accepted</div>
        <div style={{ fontSize: "10px", color: "#64748b", marginTop: "8px" }}>
          {stats.connections_sent ? `${Math.round((stats.connections_accepted / stats.connections_sent) * 100)}%` : "0%"} rate
        </div>
      </div>

      <div style={styles.statCard}>
        <MessageSquare size={16} style={{ margin: "0 auto 6px", color: "#8b5cf6" }} />
        <div style={styles.statValue}>{stats.messages_sent || 0}</div>
        <div style={styles.statLabel}>Messages Sent</div>
        <div style={{ ...styles.rateLimitBar, marginTop: "8px" }}>
          <div
            style={{
              ...styles.rateLimitFill,
              width: `${((stats.messages_sent || 0) / rateLimits.daily_message_limit) * 100}%`,
              backgroundColor: ((stats.messages_sent || 0) / rateLimits.daily_message_limit) > 0.8 ? "#f59e0b" : "#8b5cf6"
            }}
          />
        </div>
        <div style={{ fontSize: "10px", color: "#64748b", marginTop: "4px" }}>
          {rateLimits.daily_message_limit - (stats.messages_sent || 0)} remaining
        </div>
      </div>

      <div style={styles.statCard}>
        <TrendingUp size={16} style={{ margin: "0 auto 6px", color: "#06b6d4" }} />
        <div style={styles.statValue}>{stats.acceptance_rate || 0}%</div>
        <div style={styles.statLabel}>Acceptance Rate</div>
      </div>
    </div>
  )
}

// ============== CONNECTIONS TABLE COMPONENT ==============
function ConnectionsQueueTable({ connections, onSendMessage, onRetry }) {
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={styles.table}>
        <thead style={styles.tableHeader}>
          <tr>
            <th style={styles.tableHeaderCell}>Lead Name</th>
            <th style={styles.tableHeaderCell}>LinkedIn URL</th>
            <th style={styles.tableHeaderCell}>Status</th>
            <th style={styles.tableHeaderCell}>Date Sent</th>
            <th style={styles.tableHeaderCell}>Actions</th>
          </tr>
        </thead>
        <tbody>
          {connections.length === 0 ? (
            <tr>
              <td colSpan="5" style={{ ...styles.tableCell, textAlign: "center", padding: "20px" }}>
                No connections queued. <a href="#" style={{ color: "#0084ff" }}>Send a connection request →</a>
              </td>
            </tr>
          ) : (
            connections.map((conn, idx) => (
              <tr key={idx} style={styles.tableRow}>
                <td style={styles.tableCell}>{conn.lead_name || "Unknown"}</td>
                <td style={styles.tableCell}>
                  <a href={conn.linkedin_url} target="_blank" rel="noopener noreferrer" style={{ color: "#0084ff", textDecoration: "none" }}>
                    View Profile
                  </a>
                </td>
                <td style={styles.tableCell}>
                  {conn.status === "accepted" && <span style={{ color: "#10b981" }}>✓ Accepted</span>}
                  {conn.status === "pending" && <span style={{ color: "#f59e0b" }}>⏳ Pending</span>}
                  {conn.status === "rejected" && <span style={{ color: "#ef4444" }}>✕ Rejected</span>}
                </td>
                <td style={styles.tableCell}>{new Date(conn.sent_at).toLocaleDateString()}</td>
                <td style={styles.tableCell}>
                  <button
                    style={{ ...styles.button, ...styles.buttonSecondary, padding: "4px 8px", fontSize: "10px" }}
                    onClick={() => onSendMessage(conn)}
                  >
                    <MessageSquare size={12} /> Message
                  </button>
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}

// ============== CONNECTIONS LIST COMPONENT ==============
function ConnectionsList({ connections, searchTerm, setSearchTerm }) {
  const filtered = connections.filter(conn =>
    conn.name?.toLowerCase().includes(searchTerm.toLowerCase()) ||
    conn.company?.toLowerCase().includes(searchTerm.toLowerCase())
  )

  return (
    <div>
      <div style={{ marginBottom: "12px", display: "flex", gap: "8px" }}>
        <div style={{ flex: 1, position: "relative" }}>
          <Search size={14} style={{ position: "absolute", left: "8px", top: "7px", color: "#94a3b8" }} />
          <input
            type="text"
            placeholder="Search by name or company..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            style={{
              ...styles.formInput,
              paddingLeft: "32px",
              fontSize: "12px"
            }}
          />
        </div>
      </div>

      <div style={{ overflowX: "auto", maxHeight: "350px", overflowY: "auto" }}>
        <table style={styles.table}>
          <thead style={styles.tableHeader}>
            <tr>
              <th style={styles.tableHeaderCell}>Name</th>
              <th style={styles.tableHeaderCell}>Company</th>
              <th style={styles.tableHeaderCell}>Title</th>
              <th style={styles.tableHeaderCell}>Last Contacted</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr>
                <td colSpan="4" style={{ ...styles.tableCell, textAlign: "center", padding: "20px" }}>
                  No 1st-degree connections found
                </td>
              </tr>
            ) : (
              filtered.map((conn, idx) => (
                <tr key={idx} style={styles.tableRow}>
                  <td style={styles.tableCell}>{conn.name || "Unknown"}</td>
                  <td style={styles.tableCell}>{conn.company || "-"}</td>
                  <td style={styles.tableCell}>{conn.title || "-"}</td>
                  <td style={styles.tableCell}>{conn.last_contacted ? new Date(conn.last_contacted).toLocaleDateString() : "-"}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ============== MESSAGE COMPOSER MODAL ==============
function MessageComposerModal({ isOpen, connection, onSend, onClose, templates }) {
  const [selectedTemplate, setSelectedTemplate] = useState("")
  const [customMessage, setCustomMessage] = useState("")
  const [isSending, setIsSending] = useState(false)

  const handleSend = async () => {
    if (!customMessage.trim()) {
      alert("Message cannot be empty")
      return
    }

    setIsSending(true)
    try {
      const response = await fetch(`${API_BASE_URL}/linkedin/send-message`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          lead_id: connection.lead_id,
          message: customMessage,
          connection_id: connection.connection_id
        })
      })

      if (response.ok) {
        alert("Message sent successfully!")
        onClose()
        setCustomMessage("")
      } else {
        alert("Failed to send message")
      }
    } catch (error) {
      console.error("Error sending message:", error)
      alert("Error sending message")
    } finally {
      setIsSending(false)
    }
  }

  if (!isOpen || !connection) return null

  return (
    <div style={styles.modal}>
      <div style={styles.modalContent}>
        <h2 style={{ marginTop: 0, marginBottom: "16px" }}>Message {connection.lead_name}</h2>

        <div style={styles.formGroup}>
          <label style={styles.formLabel}>Use Template (optional)</label>
          <select
            value={selectedTemplate}
            onChange={(e) => {
              setSelectedTemplate(e.target.value)
              if (e.target.value) {
                const template = templates.find(t => t.id === e.target.value)
                if (template) setCustomMessage(template.content)
              }
            }}
            style={{ ...styles.formInput, cursor: "pointer" }}
          >
            <option value="">-- Choose a template --</option>
            {templates.map(t => (
              <option key={t.id} value={t.id}>{t.name}</option>
            ))}
          </select>
        </div>

        <div style={styles.formGroup}>
          <label style={styles.formLabel}>Message</label>
          <textarea
            value={customMessage}
            onChange={(e) => setCustomMessage(e.target.value)}
            placeholder="Type your message here..."
            style={{
              ...styles.formInput,
              minHeight: "120px",
              resize: "vertical",
              fontFamily: "inherit"
            }}
          />
          <div style={{ fontSize: "10px", color: "#94a3b8", marginTop: "4px" }}>
            {customMessage.length} / 300 characters
          </div>
        </div>

        <div style={{ display: "flex", gap: "8px", justifyContent: "flex-end" }}>
          <button style={{ ...styles.button, ...styles.buttonSecondary }} onClick={onClose} disabled={isSending}>
            Cancel
          </button>
          <button
            style={{ ...styles.button, ...styles.buttonPrimary }}
            onClick={handleSend}
            disabled={isSending || !customMessage.trim()}
          >
            {isSending ? <Loader size={14} /> : <Send size={14} />}
            {isSending ? "Sending..." : "Send Message"}
          </button>
        </div>
      </div>
    </div>
  )
}

// ============== ACTIVITY LOG COMPONENT ==============
function ActivityLog({ activities }) {
  return (
    <div style={styles.activityLog}>
      {activities.length === 0 ? (
        <div style={{ ...styles.activityItem, textAlign: "center", color: "#94a3b8" }}>
          No recent activity
        </div>
      ) : (
        activities.map((activity, idx) => (
          <div key={idx} style={styles.activityItem}>
            <span style={styles.activityTime}>{new Date(activity.timestamp).toLocaleTimeString()}</span>
            <span>{activity.action}</span>
            {activity.details && <span style={{ color: "#94a3b8" }}> - {activity.details}</span>}
          </div>
        ))
      )}
    </div>
  )
}

// ============== MAIN COMPONENT ==============
export default function LinkedInDashboard() {
  const [sessionStatus, setSessionStatus] = useState("not_connected")
  const [sessionEmail, setSessionEmail] = useState(null)
  const [connections, setConnections] = useState([])
  const [allConnections, setAllConnections] = useState([])
  const [dailyStats, setDailyStats] = useState({
    connections_sent: 0,
    connections_accepted: 0,
    messages_sent: 0,
    messages_replied: 0,
    acceptance_rate: 0
  })
  const [rateLimits, setRateLimits] = useState({
    daily_connection_limit: 100,
    daily_message_limit: 50
  })
  const [activities, setActivities] = useState([])
  const [messageModal, setMessageModal] = useState({ isOpen: false, connection: null })
  const [searchTerm, setSearchTerm] = useState("")
  const [templates, setTemplates] = useState([])
  const [isLoading, setIsLoading] = useState(false)
  const [isRefreshing, setIsRefreshing] = useState(false)

  // Check session status on mount
  useEffect(() => {
    checkSessionStatus()
    fetchDailyStats()
    fetchConnections()
    fetchAllConnections()
    fetchTemplates()
    const interval = setInterval(fetchDailyStats, 60000) // Refresh every minute
    return () => clearInterval(interval)
  }, [])

  // Fetch session status
  const checkSessionStatus = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/linkedin/session/status`)
      const data = await response.json()
      setSessionStatus(data.status || "not_connected")
      setSessionEmail(data.email || null)
    } catch (error) {
      console.error("Error checking session status:", error)
      setSessionStatus("not_connected")
    }
  }

  // Fetch daily stats
  const fetchDailyStats = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/linkedin/stats/daily`)
      const data = await response.json()
      setDailyStats(data.stats || {})
      setRateLimits(data.rate_limits || rateLimits)
    } catch (error) {
      console.error("Error fetching daily stats:", error)
    }
  }

  // Fetch connection queue
  const fetchConnections = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/linkedin/connections/queue`)
      const data = await response.json()
      setConnections(data.connections || [])
    } catch (error) {
      console.error("Error fetching connections:", error)
    }
  }

  // Fetch 1st-degree connections
  const fetchAllConnections = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/linkedin/connections/list`)
      const data = await response.json()
      setAllConnections(data.connections || [])
    } catch (error) {
      console.error("Error fetching connections list:", error)
    }
  }

  // Fetch message templates
  const fetchTemplates = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/linkedin/templates`)
      const data = await response.json()
      setTemplates(data.templates || [])
    } catch (error) {
      console.error("Error fetching templates:", error)
    }
  }

  // Start login session
  const startLogin = async () => {
    setIsLoading(true)
    try {
      const response = await fetch(`${API_BASE_URL}/linkedin/session/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" }
      })

      if (response.ok) {
        // Poll for session status
        let attempts = 0
        const pollInterval = setInterval(async () => {
          attempts++
          await checkSessionStatus()
          if (sessionStatus === "active" || attempts > 60) {
            clearInterval(pollInterval)
            if (sessionStatus === "active") {
              setActivities(prev => [
                { timestamp: new Date(), action: "✓ Login successful", details: sessionEmail },
                ...prev
              ])
            }
          }
        }, 2000)
      } else {
        alert("Failed to start login process")
      }
    } catch (error) {
      console.error("Error starting login:", error)
      alert("Error starting login")
    } finally {
      setIsLoading(false)
    }
  }

  // Logout
  const handleLogout = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/linkedin/session/logout`, {
        method: "POST"
      })

      if (response.ok) {
        setSessionStatus("not_connected")
        setSessionEmail(null)
        setActivities(prev => [
          { timestamp: new Date(), action: "✓ Logged out successfully" },
          ...prev
        ])
      }
    } catch (error) {
      console.error("Error logging out:", error)
    }
  }

  return (
    <div style={styles.page}>
      <div style={styles.header}>
        <div>
          <h1 style={styles.title}>LinkedIn Automation Dashboard</h1>
          <p style={styles.subtitle}>Manage connections, messages, and track daily limits</p>
        </div>
        <button
          style={{ ...styles.button, ...styles.buttonSecondary }}
          onClick={() => {
            setIsRefreshing(true)
            Promise.all([
              fetchDailyStats(),
              fetchConnections(),
              fetchAllConnections()
            ]).finally(() => setIsRefreshing(false))
          }}
          disabled={isRefreshing}
        >
          {isRefreshing ? <Loader size={16} /> : <RefreshCw size={16} />}
          {isRefreshing ? "Refreshing..." : "Refresh"}
        </button>
      </div>

      <div style={styles.container}>
        {/* Session Status */}
        <div style={styles.section}>
          <div style={styles.sectionTitle}>
            <LogIn size={16} /> Session Status
          </div>
          <SessionStatus
            status={sessionStatus}
            email={sessionEmail}
            onLogin={startLogin}
            onLogout={handleLogout}
            isLoading={isLoading}
          />
        </div>

        {/* Daily Stats */}
        <div style={styles.section}>
          <div style={styles.sectionTitle}>
            <BarChart3 size={16} /> Daily Statistics (Today)
          </div>
          <DailyStatsCards stats={dailyStats} rateLimits={rateLimits} />
        </div>

        {/* Connections Queue */}
        <div style={styles.section}>
          <div style={styles.sectionTitle}>
            <Users size={16} /> Connection Queue Management
          </div>
          <ConnectionsQueueTable
            connections={connections}
            onSendMessage={(conn) => setMessageModal({ isOpen: true, connection: conn })}
            onRetry={() => fetchConnections()}
          />
        </div>

        {/* 1st Degree Connections */}
        <div style={styles.section}>
          <div style={styles.sectionTitle}>
            <Users size={16} /> 1st-Degree Connections ({allConnections.length})
          </div>
          <ConnectionsList
            connections={allConnections}
            searchTerm={searchTerm}
            setSearchTerm={setSearchTerm}
          />
        </div>

        {/* Activity Log */}
        <div style={styles.section}>
          <div style={styles.sectionTitle}>
            <Clock size={16} /> Recent Activity
          </div>
          <ActivityLog activities={activities.slice(0, 10)} />
        </div>
      </div>

      {/* Message Composer Modal */}
      <MessageComposerModal
        isOpen={messageModal.isOpen}
        connection={messageModal.connection}
        onSend={() => fetchConnections()}
        onClose={() => setMessageModal({ isOpen: false, connection: null })}
        templates={templates}
      />
    </div>
  )
}
