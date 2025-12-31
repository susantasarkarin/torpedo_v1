"use client"

import { useState, useEffect, useCallback } from "react"
import { useNavigate } from "react-router-dom"
import { API_BASE_URL } from "../config"
import "./Settings.css"

// Segment colors for visual distinction
const SEGMENT_COLORS = {
  promotional: { bg: "#fef3c7", text: "#92400e", icon: "📢" },
  outreach: { bg: "#dbeafe", text: "#1e40af", icon: "📤" },
  discovery: { bg: "#d1fae5", text: "#065f46", icon: "🔍" },
  presentation: { bg: "#e0e7ff", text: "#3730a3", icon: "📊" },
  rfq_pricing: { bg: "#fce7f3", text: "#9d174d", icon: "💰" },
  negotiation: { bg: "#fed7aa", text: "#9a3412", icon: "🤝" },
  invoice: { bg: "#ccfbf1", text: "#0f766e", icon: "📄" },
  banking: { bg: "#f3e8ff", text: "#6b21a8", icon: "🏦" },
  others: { bg: "#f3f4f6", text: "#374151", icon: "📧" },
}

function MailPool() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  
  // Stats
  const [stats, setStats] = useState({
    total_emails: 0,
    emails_today: 0,
    emails_this_week: 0,
    total_accounts: 0,
    segments: {},
    accounts: []
  })
  
  // Emails list
  const [emails, setEmails] = useState([])
  const [pagination, setPagination] = useState({ page: 1, limit: 50, total: 0, total_pages: 0 })
  
  // Filters
  const [filterSegment, setFilterSegment] = useState("")
  const [filterSearch, setFilterSearch] = useState("")
  const [searchInput, setSearchInput] = useState("")
  
  // Activity data
  const [activity, setActivity] = useState([])
  
  // Active tab
  const [activeTab, setActiveTab] = useState("overview")

  // Fetch stats
  const fetchStats = useCallback(async () => {
    const sessionId = localStorage.getItem("session_id")
    if (!sessionId) {
      navigate("/admin/login")
      return
    }

    try {
      const res = await fetch(`${API_BASE_URL}/gmail/mail-pool/stats`, {
        headers: {
          "Content-Type": "application/json",
          Authorization: sessionId,
        },
      })

      if (res.status === 401) {
        localStorage.removeItem("session_id")
        navigate("/admin/login")
        return
      }

      const data = await res.json()
      if (data.success) {
        setStats(data.stats)
      }
    } catch (e) {
      console.error("Error fetching stats:", e)
    }
  }, [navigate])

  // Fetch emails
  const fetchEmails = useCallback(async (page = 1) => {
    const sessionId = localStorage.getItem("session_id")
    if (!sessionId) return

    try {
      let url = `${API_BASE_URL}/gmail/mail-pool/emails?page=${page}&limit=${pagination.limit}`
      if (filterSegment) url += `&segment=${filterSegment}`
      if (filterSearch) url += `&search=${encodeURIComponent(filterSearch)}`

      const res = await fetch(url, {
        headers: {
          "Content-Type": "application/json",
          Authorization: sessionId,
        },
      })

      const data = await res.json()
      if (data.success) {
        setEmails(data.emails)
        setPagination(data.pagination)
      }
    } catch (e) {
      console.error("Error fetching emails:", e)
    }
  }, [filterSegment, filterSearch, pagination.limit])

  // Fetch activity
  const fetchActivity = useCallback(async () => {
    const sessionId = localStorage.getItem("session_id")
    if (!sessionId) return

    try {
      const res = await fetch(`${API_BASE_URL}/gmail/mail-pool/activity?days=14`, {
        headers: {
          "Content-Type": "application/json",
          Authorization: sessionId,
        },
      })

      const data = await res.json()
      if (data.success) {
        setActivity(data.activity)
      }
    } catch (e) {
      console.error("Error fetching activity:", e)
    }
  }, [])

  // Initial load
  useEffect(() => {
    const loadData = async () => {
      setLoading(true)
      await Promise.all([fetchStats(), fetchEmails(), fetchActivity()])
      setLoading(false)
    }
    loadData()
  }, [fetchStats, fetchEmails, fetchActivity])

  // Reload emails when filters change
  useEffect(() => {
    fetchEmails(1)
  }, [filterSegment, filterSearch, fetchEmails])

  // Handle search
  const handleSearch = () => {
    setFilterSearch(searchInput)
  }

  // Format date
  const formatDate = (dateStr) => {
    if (!dateStr) return "N/A"
    try {
      const date = new Date(dateStr)
      const now = new Date()
      const diffMs = now - date
      const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))
      
      if (diffDays === 0) {
        return date.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" })
      } else if (diffDays === 1) {
        return "Yesterday"
      } else if (diffDays < 7) {
        return `${diffDays} days ago`
      } else {
        return date.toLocaleDateString("en-US", { month: "short", day: "numeric" })
      }
    } catch {
      return dateStr
    }
  }

  // Get segment badge
  const getSegmentBadge = (segment) => {
    const config = SEGMENT_COLORS[segment] || SEGMENT_COLORS.others
    return (
      <span
        style={{
          backgroundColor: config.bg,
          color: config.text,
          padding: "2px 8px",
          borderRadius: "12px",
          fontSize: "0.75rem",
          fontWeight: "500",
          display: "inline-flex",
          alignItems: "center",
          gap: "4px"
        }}
      >
        {config.icon} {segment?.replace("_", " ") || "other"}
      </span>
    )
  }

  // Calculate max for activity chart
  const maxActivity = Math.max(...activity.map(a => a.count), 1)

  if (loading) {
    return (
      <div className="settings-container">
        <div className="settings-header">
          <h1>📬 Mail Pool</h1>
        </div>
        <div style={{ padding: "2rem", textAlign: "center" }}>
          <div style={{ fontSize: "2rem", marginBottom: "1rem" }}>📧</div>
          Loading email activity...
        </div>
      </div>
    )
  }

  return (
    <div className="settings-container">
      <div className="settings-header">
        <h1>📬 Mail Pool</h1>
        <p>Consolidated view of all email activity across your organization</p>
      </div>

      {error && (
        <div className="settings-alert error">
          ❌ {error}
          <button onClick={() => setError(null)}>×</button>
        </div>
      )}

      {/* Stats Cards */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
        gap: "1rem",
        marginBottom: "1.5rem"
      }}>
        <div style={styles.statCard}>
          <div style={styles.statIcon}>📧</div>
          <div style={styles.statContent}>
            <div style={styles.statValue}>{stats.total_emails?.toLocaleString() || 0}</div>
            <div style={styles.statLabel}>Total Emails Synced</div>
          </div>
        </div>
        
        <div style={styles.statCard}>
          <div style={styles.statIcon}>📅</div>
          <div style={styles.statContent}>
            <div style={styles.statValue}>{stats.emails_today || 0}</div>
            <div style={styles.statLabel}>Today</div>
          </div>
        </div>
        
        <div style={styles.statCard}>
          <div style={styles.statIcon}>📊</div>
          <div style={styles.statContent}>
            <div style={styles.statValue}>{stats.emails_this_week || 0}</div>
            <div style={styles.statLabel}>This Week</div>
          </div>
        </div>
        
        <div style={styles.statCard}>
          <div style={styles.statIcon}>📮</div>
          <div style={styles.statContent}>
            <div style={styles.statValue}>{stats.total_accounts || 0}</div>
            <div style={styles.statLabel}>Connected Inboxes</div>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div style={styles.tabContainer}>
        <button
          style={{...styles.tab, ...(activeTab === "overview" ? styles.activeTab : {})}}
          onClick={() => setActiveTab("overview")}
        >
          📊 Overview
        </button>
        <button
          style={{...styles.tab, ...(activeTab === "emails" ? styles.activeTab : {})}}
          onClick={() => setActiveTab("emails")}
        >
          📧 All Emails
        </button>
        <button
          style={{...styles.tab, ...(activeTab === "accounts" ? styles.activeTab : {})}}
          onClick={() => setActiveTab("accounts")}
        >
          📮 Inboxes
        </button>
      </div>

      <div className="settings-content">
        {/* Overview Tab */}
        {activeTab === "overview" && (
          <>
            {/* Activity Chart */}
            <div className="settings-section">
              <h2>📈 Email Activity (Last 14 Days)</h2>
              <div style={styles.chartContainer}>
                {activity.length > 0 ? (
                  <div style={styles.chart}>
                    {activity.map((day, idx) => (
                      <div key={idx} style={styles.chartBar}>
                        <div
                          style={{
                            ...styles.chartBarFill,
                            height: `${(day.count / maxActivity) * 100}%`
                          }}
                          title={`${day.date}: ${day.count} emails`}
                        />
                        <div style={styles.chartLabel}>
                          {new Date(day.date).toLocaleDateString("en-US", { weekday: "short" })}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div style={{ textAlign: "center", padding: "2rem", color: "#6b7280" }}>
                    No activity data yet. Start syncing emails to see activity.
                  </div>
                )}
              </div>
            </div>

            {/* Segment Breakdown */}
            <div className="settings-section">
              <h2>🏷️ Email Segments</h2>
              <div style={styles.segmentGrid}>
                {Object.entries(stats.segments || {}).map(([segment, count]) => {
                  const config = SEGMENT_COLORS[segment] || SEGMENT_COLORS.others
                  return (
                    <div
                      key={segment}
                      style={{
                        ...styles.segmentCard,
                        backgroundColor: config.bg,
                        borderColor: config.text,
                        cursor: "pointer"
                      }}
                      onClick={() => {
                        setFilterSegment(segment)
                        setActiveTab("emails")
                      }}
                    >
                      <div style={{ fontSize: "1.5rem" }}>{config.icon}</div>
                      <div style={{ color: config.text, fontWeight: "600" }}>
                        {count.toLocaleString()}
                      </div>
                      <div style={{ color: config.text, fontSize: "0.85rem", textTransform: "capitalize" }}>
                        {segment.replace("_", " ")}
                      </div>
                    </div>
                  )
                })}
                {Object.keys(stats.segments || {}).length === 0 && (
                  <div style={{ gridColumn: "1 / -1", textAlign: "center", padding: "2rem", color: "#6b7280" }}>
                    No email segments yet. Import emails to see segment breakdown.
                  </div>
                )}
              </div>
            </div>
          </>
        )}

        {/* Emails Tab */}
        {activeTab === "emails" && (
          <div className="settings-section">
            <h2>📧 All Emails</h2>
            
            {/* Filters */}
            <div style={styles.filterBar}>
              <div style={styles.searchBox}>
                <input
                  type="text"
                  placeholder="Search emails..."
                  value={searchInput}
                  onChange={(e) => setSearchInput(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleSearch()}
                  style={styles.searchInput}
                />
                <button onClick={handleSearch} style={styles.searchButton}>
                  🔍
                </button>
              </div>
              
              <select
                value={filterSegment}
                onChange={(e) => setFilterSegment(e.target.value)}
                style={styles.filterSelect}
              >
                <option value="">All Segments</option>
                {Object.keys(SEGMENT_COLORS).map(seg => (
                  <option key={seg} value={seg}>
                    {seg.replace("_", " ").charAt(0).toUpperCase() + seg.replace("_", " ").slice(1)}
                  </option>
                ))}
              </select>
              
              {(filterSegment || filterSearch) && (
                <button
                  onClick={() => {
                    setFilterSegment("")
                    setFilterSearch("")
                    setSearchInput("")
                  }}
                  style={styles.clearButton}
                >
                  ✕ Clear Filters
                </button>
              )}
            </div>

            {/* Email List */}
            <div style={styles.emailList}>
              {emails.length > 0 ? (
                emails.map((email) => (
                  <div key={email.id} style={styles.emailRow}>
                    <div style={styles.emailAvatar}>
                      {email.name?.charAt(0)?.toUpperCase() || email.email?.charAt(0)?.toUpperCase() || "?"}
                    </div>
                    <div style={styles.emailContent}>
                      <div style={styles.emailHeader}>
                        <span style={styles.emailName}>
                          {email.name || email.email?.split("@")[0] || "Unknown"}
                        </span>
                        {email.company && (
                          <span style={styles.emailCompany}>@ {email.company}</span>
                        )}
                        <span style={styles.emailDate}>{formatDate(email.added_on)}</span>
                      </div>
                      <div style={styles.emailAddress}>{email.email}</div>
                      {email.snippet && (
                        <div style={styles.emailSnippet}>{email.snippet}</div>
                      )}
                    </div>
                    <div style={styles.emailMeta}>
                      {getSegmentBadge(email.segment)}
                      {email.has_rfq && (
                        <span style={styles.rfqBadge}>💰 RFQ</span>
                      )}
                    </div>
                  </div>
                ))
              ) : (
                <div style={{ textAlign: "center", padding: "3rem", color: "#6b7280" }}>
                  <div style={{ fontSize: "3rem", marginBottom: "1rem" }}>📭</div>
                  <p>No emails found matching your criteria.</p>
                  <p style={{ fontSize: "0.875rem" }}>Try adjusting your filters or import more emails.</p>
                </div>
              )}
            </div>

            {/* Pagination */}
            {pagination.total_pages > 1 && (
              <div style={styles.pagination}>
                <button
                  onClick={() => fetchEmails(pagination.page - 1)}
                  disabled={pagination.page === 1}
                  style={styles.pageButton}
                >
                  ← Previous
                </button>
                <span style={styles.pageInfo}>
                  Page {pagination.page} of {pagination.total_pages}
                  <span style={{ color: "#6b7280", marginLeft: "8px" }}>
                    ({pagination.total.toLocaleString()} total)
                  </span>
                </span>
                <button
                  onClick={() => fetchEmails(pagination.page + 1)}
                  disabled={pagination.page === pagination.total_pages}
                  style={styles.pageButton}
                >
                  Next →
                </button>
              </div>
            )}
          </div>
        )}

        {/* Accounts Tab */}
        {activeTab === "accounts" && (
          <div className="settings-section">
            <h2>📮 Connected Inboxes</h2>
            <p className="section-description">
              Overview of all connected email accounts and their sync status.
            </p>
            
            <div style={styles.accountsGrid}>
              {stats.accounts?.length > 0 ? (
                stats.accounts.map((account, idx) => (
                  <div key={idx} style={styles.accountCard}>
                    <div style={styles.accountHeader}>
                      <div style={styles.accountAvatar}>
                        {account.display_name?.charAt(0)?.toUpperCase() || account.email?.charAt(0)?.toUpperCase()}
                      </div>
                      <div>
                        <div style={styles.accountName}>{account.display_name}</div>
                        <div style={styles.accountEmail}>{account.email}</div>
                      </div>
                    </div>
                    <div style={styles.accountStats}>
                      <div style={styles.accountStat}>
                        <span style={styles.accountStatValue}>{account.total_emails?.toLocaleString() || 0}</span>
                        <span style={styles.accountStatLabel}>Total Emails</span>
                      </div>
                      <div style={styles.accountStat}>
                        <span style={styles.accountStatValue}>{account.today || 0}</span>
                        <span style={styles.accountStatLabel}>Today</span>
                      </div>
                    </div>
                    <div style={styles.accountFooter}>
                      <span style={{ color: "#6b7280", fontSize: "0.75rem" }}>
                        Last sync: {account.last_sync ? formatDate(account.last_sync) : "Never"}
                      </span>
                    </div>
                  </div>
                ))
              ) : (
                <div style={{ gridColumn: "1 / -1", textAlign: "center", padding: "3rem", color: "#6b7280" }}>
                  <div style={{ fontSize: "3rem", marginBottom: "1rem" }}>📭</div>
                  <p>No email accounts connected yet.</p>
                  <p style={{ fontSize: "0.875rem" }}>
                    Go to Settings → Gmail to add IMAP accounts.
                  </p>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// Styles
const styles = {
  statCard: {
    display: "flex",
    alignItems: "center",
    gap: "1rem",
    padding: "1.25rem",
    backgroundColor: "white",
    borderRadius: "12px",
    boxShadow: "0 1px 3px rgba(0,0,0,0.1)",
    border: "1px solid #e5e7eb"
  },
  statIcon: {
    fontSize: "2rem",
    width: "50px",
    height: "50px",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#f3f4f6",
    borderRadius: "10px"
  },
  statContent: {
    flex: 1
  },
  statValue: {
    fontSize: "1.75rem",
    fontWeight: "700",
    color: "#111827"
  },
  statLabel: {
    fontSize: "0.875rem",
    color: "#6b7280"
  },
  tabContainer: {
    display: "flex",
    gap: "0.5rem",
    marginBottom: "1.5rem",
    borderBottom: "2px solid #e5e7eb",
    paddingBottom: "0"
  },
  tab: {
    padding: "0.75rem 1.5rem",
    border: "none",
    background: "none",
    cursor: "pointer",
    fontSize: "0.95rem",
    fontWeight: "500",
    color: "#6b7280",
    borderBottom: "2px solid transparent",
    marginBottom: "-2px",
    transition: "all 0.2s"
  },
  activeTab: {
    color: "#2563eb",
    borderBottomColor: "#2563eb"
  },
  chartContainer: {
    padding: "1rem",
    backgroundColor: "#f9fafb",
    borderRadius: "8px"
  },
  chart: {
    display: "flex",
    alignItems: "flex-end",
    justifyContent: "space-between",
    height: "150px",
    gap: "8px"
  },
  chartBar: {
    flex: 1,
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    height: "100%",
    justifyContent: "flex-end"
  },
  chartBarFill: {
    width: "100%",
    maxWidth: "40px",
    backgroundColor: "#3b82f6",
    borderRadius: "4px 4px 0 0",
    minHeight: "4px",
    transition: "height 0.3s"
  },
  chartLabel: {
    fontSize: "0.7rem",
    color: "#6b7280",
    marginTop: "4px"
  },
  segmentGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))",
    gap: "1rem"
  },
  segmentCard: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    padding: "1rem",
    borderRadius: "10px",
    border: "1px solid",
    transition: "transform 0.2s",
    "&:hover": {
      transform: "translateY(-2px)"
    }
  },
  filterBar: {
    display: "flex",
    gap: "1rem",
    marginBottom: "1rem",
    flexWrap: "wrap",
    alignItems: "center"
  },
  searchBox: {
    display: "flex",
    flex: 1,
    minWidth: "250px"
  },
  searchInput: {
    flex: 1,
    padding: "0.5rem 1rem",
    border: "1px solid #e5e7eb",
    borderRadius: "6px 0 0 6px",
    fontSize: "0.95rem"
  },
  searchButton: {
    padding: "0.5rem 1rem",
    backgroundColor: "#2563eb",
    color: "white",
    border: "none",
    borderRadius: "0 6px 6px 0",
    cursor: "pointer"
  },
  filterSelect: {
    padding: "0.5rem 1rem",
    border: "1px solid #e5e7eb",
    borderRadius: "6px",
    fontSize: "0.95rem",
    backgroundColor: "white",
    cursor: "pointer"
  },
  clearButton: {
    padding: "0.5rem 1rem",
    backgroundColor: "#f3f4f6",
    border: "1px solid #e5e7eb",
    borderRadius: "6px",
    cursor: "pointer",
    fontSize: "0.875rem"
  },
  emailList: {
    display: "flex",
    flexDirection: "column",
    gap: "0.5rem"
  },
  emailRow: {
    display: "flex",
    alignItems: "flex-start",
    gap: "1rem",
    padding: "1rem",
    backgroundColor: "white",
    borderRadius: "8px",
    border: "1px solid #e5e7eb",
    transition: "background-color 0.2s",
    cursor: "pointer"
  },
  emailAvatar: {
    width: "40px",
    height: "40px",
    borderRadius: "50%",
    backgroundColor: "#3b82f6",
    color: "white",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontWeight: "600",
    fontSize: "1rem",
    flexShrink: 0
  },
  emailContent: {
    flex: 1,
    minWidth: 0
  },
  emailHeader: {
    display: "flex",
    alignItems: "center",
    gap: "0.5rem",
    marginBottom: "0.25rem"
  },
  emailName: {
    fontWeight: "600",
    color: "#111827"
  },
  emailCompany: {
    color: "#6b7280",
    fontSize: "0.875rem"
  },
  emailDate: {
    marginLeft: "auto",
    color: "#9ca3af",
    fontSize: "0.75rem"
  },
  emailAddress: {
    color: "#6b7280",
    fontSize: "0.875rem"
  },
  emailSnippet: {
    color: "#9ca3af",
    fontSize: "0.85rem",
    marginTop: "0.25rem",
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap"
  },
  emailMeta: {
    display: "flex",
    flexDirection: "column",
    gap: "0.5rem",
    alignItems: "flex-end"
  },
  rfqBadge: {
    backgroundColor: "#fce7f3",
    color: "#9d174d",
    padding: "2px 8px",
    borderRadius: "12px",
    fontSize: "0.75rem",
    fontWeight: "500"
  },
  pagination: {
    display: "flex",
    justifyContent: "center",
    alignItems: "center",
    gap: "1rem",
    marginTop: "1.5rem",
    padding: "1rem"
  },
  pageButton: {
    padding: "0.5rem 1rem",
    backgroundColor: "white",
    border: "1px solid #e5e7eb",
    borderRadius: "6px",
    cursor: "pointer",
    fontSize: "0.875rem"
  },
  pageInfo: {
    fontSize: "0.875rem",
    color: "#374151"
  },
  accountsGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))",
    gap: "1rem"
  },
  accountCard: {
    backgroundColor: "white",
    borderRadius: "12px",
    border: "1px solid #e5e7eb",
    padding: "1.25rem",
    boxShadow: "0 1px 3px rgba(0,0,0,0.05)"
  },
  accountHeader: {
    display: "flex",
    alignItems: "center",
    gap: "1rem",
    marginBottom: "1rem"
  },
  accountAvatar: {
    width: "48px",
    height: "48px",
    borderRadius: "50%",
    backgroundColor: "#2563eb",
    color: "white",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontWeight: "600",
    fontSize: "1.25rem"
  },
  accountName: {
    fontWeight: "600",
    color: "#111827"
  },
  accountEmail: {
    fontSize: "0.875rem",
    color: "#6b7280"
  },
  accountStats: {
    display: "flex",
    gap: "2rem",
    padding: "1rem 0",
    borderTop: "1px solid #f3f4f6",
    borderBottom: "1px solid #f3f4f6"
  },
  accountStat: {
    display: "flex",
    flexDirection: "column"
  },
  accountStatValue: {
    fontSize: "1.25rem",
    fontWeight: "700",
    color: "#111827"
  },
  accountStatLabel: {
    fontSize: "0.75rem",
    color: "#6b7280"
  },
  accountFooter: {
    paddingTop: "0.75rem"
  }
}

export default MailPool
