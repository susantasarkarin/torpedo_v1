"use client"

import { useState, useEffect, useCallback } from "react"
import { useNavigate } from "react-router-dom"
import { API_BASE_URL, buildApiUrl } from "../config"

// Email category colors and icons
const CATEGORY_STYLES = {
  inbound_lead: { bg: "#d1fae5", text: "#065f46", icon: "🎯" },
  meeting_request: { bg: "#dbeafe", text: "#1e40af", icon: "📅" },
  demo_request: { bg: "#e0e7ff", text: "#3730a3", icon: "🖥️" },
  pricing_inquiry: { bg: "#fce7f3", text: "#9d174d", icon: "💰" },
  interested: { bg: "#d1fae5", text: "#065f46", icon: "✅" },
  rfq_request: { bg: "#fed7aa", text: "#9a3412", icon: "📋" },
  quote_response: { bg: "#fef3c7", text: "#92400e", icon: "💬" },
  negotiation: { bg: "#fce7f3", text: "#9d174d", icon: "🤝" },
  invoice: { bg: "#ccfbf1", text: "#0f766e", icon: "📄" },
  payment_confirmation: { bg: "#d1fae5", text: "#065f46", icon: "💳" },
  vendor_communication: { bg: "#e0f2fe", text: "#0369a1", icon: "🏢" },
  support_request: { bg: "#fef3c7", text: "#92400e", icon: "🆘" },
  complaint: { bg: "#fee2e2", text: "#991b1b", icon: "⚠️" },
  default: { bg: "#f3f4f6", text: "#374151", icon: "📧" }
}

// Department colors
const DEPARTMENT_STYLES = {
  sales: { bg: "#dbeafe", text: "#1e40af" },
  operations: { bg: "#fed7aa", text: "#9a3412" },
  finance: { bg: "#d1fae5", text: "#065f46" },
  support: { bg: "#fce7f3", text: "#9d174d" },
  none: { bg: "#f3f4f6", text: "#6b7280" }
}

// Priority colors
const PRIORITY_STYLES = {
  critical: { bg: "#fee2e2", text: "#991b1b" },
  high: { bg: "#fef3c7", text: "#92400e" },
  medium: { bg: "#e0f2fe", text: "#0369a1" },
  low: { bg: "#f3f4f6", text: "#6b7280" }
}

const formatDate = (dateStr) => {
  const date = new Date(dateStr)
  const now = new Date()
  const isToday = date.toDateString() === now.toDateString()
  
  if (isToday) {
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  }
  return date.toLocaleDateString([], { month: 'short', day: 'numeric' })
}

const getInitials = (name, email) => {
  if (name) {
    const parts = name.split(' ')
    return parts.length >= 2 
      ? (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
      : name[0].toUpperCase()
  }
  return email ? email[0].toUpperCase() : "?"
}

const getAvatarColor = (name) => {
  const colors = ["#1a73e8", "#ea4335", "#34a853", "#fbbc04", "#673ab7", "#e91e63"]
  const hash = (name || "").split("").reduce((a, b) => a + b.charCodeAt(0), 0)
  return colors[hash % colors.length]
}

function MailPool() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [emails, setEmails] = useState([])
  const [selectedEmail, setSelectedEmail] = useState(null)
  const [emailContent, setEmailContent] = useState(null)
  const [stats, setStats] = useState({ total: 0, unread: 0, unclassified: 0, by_category: {}, by_department: {} })
  const [mailboxes, setMailboxes] = useState([])
  
  // Filters
  const [filters, setFilters] = useState({
    mailbox_id: "",
    direction: "",
    category: "",
    department: "",
    search: "",
    page: 1,
    limit: 50
  })
  
  const [pagination, setPagination] = useState({ total: 0, total_pages: 0 })
  const [classifying, setClassifying] = useState(false)

  // Auth check
  const getAuthHeader = useCallback(() => {
    const sessionId = localStorage.getItem("session_id")
    if (!sessionId) {
      navigate("/admin/login")
      return null
    }
    return sessionId
  }, [navigate])

  // Fetch mailboxes
  const fetchMailboxes = useCallback(async () => {
    const auth = getAuthHeader()
    if (!auth) return
    
    try {
      const res = await fetch(buildApiUrl(`/gmail/mailboxes`), {
        headers: { Authorization: auth }
      })
      if (res.ok) {
        const data = await res.json()
        setMailboxes(data)
      }
    } catch (err) {
      console.error("Error fetching mailboxes:", err)
    }
  }, [getAuthHeader])

  // Fetch stats
  const fetchStats = useCallback(async () => {
    const auth = getAuthHeader()
    if (!auth) return
    
    try {
      const res = await fetch(buildApiUrl(`/gmail/stats${filters.mailbox_id ? `?mailbox_id=${filters.mailbox_id}` : ''}`), {
        headers: { Authorization: auth }
      })
      if (res.ok) {
        const data = await res.json()
        setStats(data)
      }
    } catch (err) {
      console.error("Error fetching stats:", err)
    }
  }, [getAuthHeader, filters.mailbox_id])

  // Fetch emails
  const fetchEmails = useCallback(async () => {
    const auth = getAuthHeader()
    if (!auth) return
    
    setLoading(true)
    try {
      const params = new URLSearchParams()
      if (filters.mailbox_id) params.append("mailbox_id", filters.mailbox_id)
      if (filters.direction) params.append("direction", filters.direction)
      if (filters.category) params.append("category", filters.category)
      if (filters.department) params.append("department", filters.department)
      if (filters.search) params.append("search", filters.search)
      params.append("page", filters.page)
      params.append("limit", filters.limit)
      
      const res = await fetch(buildApiUrl(`/gmail/emails?${params}`), {
        headers: { Authorization: auth }
      })
      
      if (res.ok) {
        const data = await res.json()
        setEmails(data.emails || [])
        setPagination({
          total: data.total,
          total_pages: data.total_pages
        })
      }
    } catch (err) {
      console.error("Error fetching emails:", err)
    } finally {
      setLoading(false)
    }
  }, [getAuthHeader, filters])

  // Fetch email content
  const fetchEmailContent = useCallback(async (emailId) => {
    const auth = getAuthHeader()
    if (!auth) return
    
    try {
      const res = await fetch(buildApiUrl(`/gmail/emails/${emailId}/content`), {
        headers: { Authorization: auth }
      })
      if (res.ok) {
        const data = await res.json()
        setEmailContent(data)
      }
    } catch (err) {
      console.error("Error fetching email content:", err)
    }
  }, [getAuthHeader])

  // Classify email
  const classifyEmail = async (emailId) => {
    const auth = getAuthHeader()
    if (!auth) return
    
    setClassifying(true)
    try {
      const res = await fetch(buildApiUrl(`/gmail/classify/${emailId}`), {
        method: "POST",
        headers: { Authorization: auth }
      })
      
      if (res.ok) {
        // Refresh the email list and stats
        fetchEmails()
        fetchStats()
      }
    } catch (err) {
      console.error("Error classifying email:", err)
    } finally {
      setClassifying(false)
    }
  }

  // Classify all unclassified
  const classifyBatch = async () => {
    const auth = getAuthHeader()
    if (!auth) return
    
    setClassifying(true)
    try {
      const res = await fetch(buildApiUrl(`/gmail/classify/batch?limit=100`), {
        method: "POST",
        headers: { Authorization: auth }
      })
      
      if (res.ok) {
        const data = await res.json()
        alert(`Classification started for ${data.count} emails`)
        // Refresh after a delay
        setTimeout(() => {
          fetchEmails()
          fetchStats()
        }, 3000)
      }
    } catch (err) {
      console.error("Error batch classifying:", err)
    } finally {
      setClassifying(false)
    }
  }

  // Sync emails
  const syncEmails = async (mailboxId) => {
    const auth = getAuthHeader()
    if (!auth) return
    
    try {
      const res = await fetch(buildApiUrl(`/gmail/mailboxes/${mailboxId}/sync`), {
        method: "POST",
        headers: { Authorization: auth }
      })
      
      if (res.ok) {
        const data = await res.json()
        alert(`Synced ${data.new_emails} new emails, ${data.updated_emails} updated`)
        fetchEmails()
        fetchStats()
      }
    } catch (err) {
      console.error("Error syncing:", err)
    }
  }

  // Initial load
  useEffect(() => {
    fetchMailboxes()
    fetchStats()
    fetchEmails()
  }, [])

  // Refetch when filters change
  useEffect(() => {
    fetchEmails()
  }, [filters])

  // Select email
  const handleSelectEmail = (email) => {
    setSelectedEmail(email)
    setEmailContent(null)
    fetchEmailContent(email.id)
  }

  const getCategoryStyle = (category) => CATEGORY_STYLES[category] || CATEGORY_STYLES.default
  const getDepartmentStyle = (dept) => DEPARTMENT_STYLES[dept] || DEPARTMENT_STYLES.none
  const getPriorityStyle = (priority) => PRIORITY_STYLES[priority] || PRIORITY_STYLES.medium

  return (
    <div style={styles.container}>
      {/* Header */}
      <div style={styles.header}>
        <div>
          <h1 style={styles.title}>📬 Email Inbox</h1>
          <p style={styles.subtitle}>
            {stats.total} emails • {stats.unread} unread • {stats.unclassified} unclassified
          </p>
        </div>
        <div style={styles.headerActions}>
          {stats.unclassified > 0 && (
            <button 
              style={styles.classifyBtn}
              onClick={classifyBatch}
              disabled={classifying}
            >
              {classifying ? "Classifying..." : `🤖 Classify ${stats.unclassified} emails`}
            </button>
          )}
          {mailboxes.length > 0 && (
            <button 
              style={styles.syncBtn}
              onClick={() => syncEmails(mailboxes[0].id)}
            >
              🔄 Sync
            </button>
          )}
        </div>
      </div>

      {/* Stats Cards */}
      <div style={styles.statsRow}>
        {Object.entries(stats.by_department || {}).map(([dept, count]) => (
          <div 
            key={dept} 
            style={{
              ...styles.statCard,
              backgroundColor: getDepartmentStyle(dept).bg,
              color: getDepartmentStyle(dept).text
            }}
          >
            <div style={styles.statCount}>{count}</div>
            <div style={styles.statLabel}>{dept}</div>
          </div>
        ))}
      </div>

      {/* Filters */}
      <div style={styles.filters}>
        <select
          style={styles.filterSelect}
          value={filters.direction}
          onChange={(e) => setFilters({...filters, direction: e.target.value, page: 1})}
        >
          <option value="">All Directions</option>
          <option value="inbound">📥 Inbound</option>
          <option value="outbound">📤 Outbound</option>
        </select>

        <select
          style={styles.filterSelect}
          value={filters.department}
          onChange={(e) => setFilters({...filters, department: e.target.value, page: 1})}
        >
          <option value="">All Departments</option>
          <option value="sales">🎯 Sales</option>
          <option value="operations">⚙️ Operations</option>
          <option value="finance">💰 Finance</option>
          <option value="support">🆘 Support</option>
        </select>

        <select
          style={styles.filterSelect}
          value={filters.category}
          onChange={(e) => setFilters({...filters, category: e.target.value, page: 1})}
        >
          <option value="">All Categories</option>
          <option value="inbound_lead">Inbound Lead</option>
          <option value="rfq_request">RFQ Request</option>
          <option value="invoice">Invoice</option>
          <option value="vendor_communication">Vendor</option>
          <option value="support_request">Support</option>
        </select>

        <input
          type="text"
          placeholder="🔍 Search emails..."
          style={styles.searchInput}
          value={filters.search}
          onChange={(e) => setFilters({...filters, search: e.target.value})}
          onKeyDown={(e) => e.key === 'Enter' && fetchEmails()}
        />
      </div>

      {/* Main Content */}
      <div style={styles.content}>
        {/* Email List */}
        <div style={styles.emailList}>
          {loading ? (
            <div style={styles.loading}>Loading emails...</div>
          ) : emails.length === 0 ? (
            <div style={styles.empty}>No emails found</div>
          ) : (
            emails.map((email) => (
              <div
                key={email.id}
                style={{
                  ...styles.emailRow,
                  backgroundColor: selectedEmail?.id === email.id ? "#e8f0fe" : 
                                   email.is_read ? "#fff" : "#f0f7ff"
                }}
                onClick={() => handleSelectEmail(email)}
              >
                {/* Avatar */}
                <div 
                  style={{
                    ...styles.avatar,
                    backgroundColor: getAvatarColor(email.from_name || email.from_email)
                  }}
                >
                  {getInitials(email.from_name, email.from_email)}
                </div>

                {/* Email Info */}
                <div style={styles.emailInfo}>
                  <div style={styles.emailTop}>
                    <span style={styles.emailFrom}>
                      {email.from_name || email.from_email}
                    </span>
                    <span style={styles.emailDate}>{formatDate(email.timestamp)}</span>
                  </div>
                  <div style={styles.emailSubject}>{email.subject}</div>
                  <div style={styles.emailSnippet}>{email.snippet}</div>
                  
                  {/* Tags */}
                  <div style={styles.emailTags}>
                    {email.ai_category && (
                      <span style={{
                        ...styles.tag,
                        backgroundColor: getCategoryStyle(email.ai_category).bg,
                        color: getCategoryStyle(email.ai_category).text
                      }}>
                        {getCategoryStyle(email.ai_category).icon} {email.ai_category.replace(/_/g, ' ')}
                      </span>
                    )}
                    {email.ai_department && email.ai_department !== 'none' && (
                      <span style={{
                        ...styles.tag,
                        backgroundColor: getDepartmentStyle(email.ai_department).bg,
                        color: getDepartmentStyle(email.ai_department).text
                      }}>
                        {email.ai_department}
                      </span>
                    )}
                    {email.ai_priority && email.ai_priority !== 'medium' && (
                      <span style={{
                        ...styles.tag,
                        backgroundColor: getPriorityStyle(email.ai_priority).bg,
                        color: getPriorityStyle(email.ai_priority).text
                      }}>
                        {email.ai_priority}
                      </span>
                    )}
                    {email.has_attachments && (
                      <span style={styles.attachmentIcon}>📎</span>
                    )}
                  </div>
                </div>
              </div>
            ))
          )}

          {/* Pagination */}
          {pagination.total_pages > 1 && (
            <div style={styles.pagination}>
              <button
                style={styles.pageBtn}
                disabled={filters.page <= 1}
                onClick={() => setFilters({...filters, page: filters.page - 1})}
              >
                ← Prev
              </button>
              <span style={styles.pageInfo}>
                Page {filters.page} of {pagination.total_pages}
              </span>
              <button
                style={styles.pageBtn}
                disabled={filters.page >= pagination.total_pages}
                onClick={() => setFilters({...filters, page: filters.page + 1})}
              >
                Next →
              </button>
            </div>
          )}
        </div>

        {/* Email Detail */}
        <div style={styles.emailDetail}>
          {selectedEmail ? (
            <>
              <div style={styles.detailHeader}>
                <h2 style={styles.detailSubject}>{selectedEmail.subject}</h2>
                <div style={styles.detailMeta}>
                  <div>
                    <strong>From:</strong> {selectedEmail.from_name} &lt;{selectedEmail.from_email}&gt;
                  </div>
                  <div>
                    <strong>To:</strong> {selectedEmail.to_emails?.join(", ")}
                  </div>
                  <div>
                    <strong>Date:</strong> {new Date(selectedEmail.timestamp).toLocaleString()}
                  </div>
                </div>
                
                {/* AI Classification */}
                {selectedEmail.ai_category ? (
                  <div style={styles.aiSection}>
                    <span style={styles.aiLabel}>🤖 AI Classification:</span>
                    <span style={{
                      ...styles.tag,
                      backgroundColor: getCategoryStyle(selectedEmail.ai_category).bg,
                      color: getCategoryStyle(selectedEmail.ai_category).text
                    }}>
                      {selectedEmail.ai_category.replace(/_/g, ' ')}
                    </span>
                    {selectedEmail.ai_summary && (
                      <p style={styles.aiSummary}>{selectedEmail.ai_summary}</p>
                    )}
                  </div>
                ) : (
                  <button
                    style={styles.classifyBtn}
                    onClick={() => classifyEmail(selectedEmail.id)}
                    disabled={classifying}
                  >
                    {classifying ? "Classifying..." : "🤖 Classify with AI"}
                  </button>
                )}
              </div>

              <div style={styles.detailBody}>
                {emailContent ? (
                  emailContent.body_html ? (
                    <div dangerouslySetInnerHTML={{ __html: emailContent.body_html }} />
                  ) : (
                    <pre style={styles.plainText}>{emailContent.body_plain}</pre>
                  )
                ) : (
                  <div style={styles.loading}>Loading content...</div>
                )}
              </div>

              {/* Attachments */}
              {emailContent?.attachments?.length > 0 && (
                <div style={styles.attachments}>
                  <strong>📎 Attachments:</strong>
                  <div style={styles.attachmentList}>
                    {emailContent.attachments.map((att, idx) => (
                      <div key={idx} style={styles.attachment}>
                        📄 {att.filename} ({Math.round(att.size / 1024)}KB)
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          ) : (
            <div style={styles.noSelection}>
              <div style={styles.noSelectionIcon}>📬</div>
              <p>Select an email to view</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

const styles = {
  container: {
    padding: "1.5rem",
    height: "100vh",
    display: "flex",
    flexDirection: "column",
    backgroundColor: "#f8fafc"
  },
  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: "1rem"
  },
  title: {
    margin: 0,
    fontSize: "1.5rem",
    color: "#1f2937"
  },
  subtitle: {
    margin: "0.25rem 0 0",
    color: "#6b7280",
    fontSize: "0.875rem"
  },
  headerActions: {
    display: "flex",
    gap: "0.75rem"
  },
  classifyBtn: {
    backgroundColor: "#8b5cf6",
    color: "white",
    border: "none",
    borderRadius: "6px",
    padding: "0.5rem 1rem",
    cursor: "pointer",
    fontWeight: "500"
  },
  syncBtn: {
    backgroundColor: "#3b82f6",
    color: "white",
    border: "none",
    borderRadius: "6px",
    padding: "0.5rem 1rem",
    cursor: "pointer",
    fontWeight: "500"
  },
  statsRow: {
    display: "flex",
    gap: "1rem",
    marginBottom: "1rem",
    overflowX: "auto"
  },
  statCard: {
    padding: "1rem 1.5rem",
    borderRadius: "8px",
    minWidth: "120px",
    textAlign: "center"
  },
  statCount: {
    fontSize: "1.5rem",
    fontWeight: "600"
  },
  statLabel: {
    fontSize: "0.75rem",
    textTransform: "uppercase",
    marginTop: "0.25rem"
  },
  filters: {
    display: "flex",
    gap: "0.75rem",
    marginBottom: "1rem",
    flexWrap: "wrap"
  },
  filterSelect: {
    padding: "0.5rem",
    borderRadius: "6px",
    border: "1px solid #d1d5db",
    backgroundColor: "white",
    minWidth: "150px"
  },
  searchInput: {
    padding: "0.5rem 1rem",
    borderRadius: "6px",
    border: "1px solid #d1d5db",
    flex: 1,
    minWidth: "200px"
  },
  content: {
    display: "flex",
    flex: 1,
    gap: "1rem",
    overflow: "hidden"
  },
  emailList: {
    width: "400px",
    backgroundColor: "white",
    borderRadius: "8px",
    boxShadow: "0 1px 3px rgba(0,0,0,0.1)",
    overflowY: "auto",
    flexShrink: 0
  },
  emailRow: {
    display: "flex",
    padding: "0.75rem 1rem",
    borderBottom: "1px solid #e5e7eb",
    cursor: "pointer",
    gap: "0.75rem",
    transition: "background-color 0.15s"
  },
  avatar: {
    width: "40px",
    height: "40px",
    borderRadius: "50%",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    color: "white",
    fontWeight: "600",
    fontSize: "0.875rem",
    flexShrink: 0
  },
  emailInfo: {
    flex: 1,
    overflow: "hidden"
  },
  emailTop: {
    display: "flex",
    justifyContent: "space-between",
    marginBottom: "0.25rem"
  },
  emailFrom: {
    fontWeight: "600",
    color: "#1f2937",
    fontSize: "0.875rem",
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap"
  },
  emailDate: {
    color: "#6b7280",
    fontSize: "0.75rem",
    flexShrink: 0
  },
  emailSubject: {
    color: "#374151",
    fontSize: "0.875rem",
    marginBottom: "0.25rem",
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap"
  },
  emailSnippet: {
    color: "#6b7280",
    fontSize: "0.75rem",
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
    marginBottom: "0.5rem"
  },
  emailTags: {
    display: "flex",
    gap: "0.25rem",
    flexWrap: "wrap"
  },
  tag: {
    padding: "0.125rem 0.5rem",
    borderRadius: "4px",
    fontSize: "0.625rem",
    fontWeight: "500"
  },
  attachmentIcon: {
    fontSize: "0.75rem"
  },
  pagination: {
    display: "flex",
    justifyContent: "center",
    alignItems: "center",
    gap: "1rem",
    padding: "1rem"
  },
  pageBtn: {
    padding: "0.5rem 1rem",
    border: "1px solid #d1d5db",
    borderRadius: "6px",
    backgroundColor: "white",
    cursor: "pointer"
  },
  pageInfo: {
    color: "#6b7280",
    fontSize: "0.875rem"
  },
  emailDetail: {
    flex: 1,
    backgroundColor: "white",
    borderRadius: "8px",
    boxShadow: "0 1px 3px rgba(0,0,0,0.1)",
    overflow: "auto",
    display: "flex",
    flexDirection: "column"
  },
  detailHeader: {
    padding: "1.5rem",
    borderBottom: "1px solid #e5e7eb"
  },
  detailSubject: {
    margin: "0 0 1rem",
    fontSize: "1.25rem",
    color: "#1f2937"
  },
  detailMeta: {
    display: "flex",
    flexDirection: "column",
    gap: "0.25rem",
    color: "#6b7280",
    fontSize: "0.875rem"
  },
  aiSection: {
    marginTop: "1rem",
    padding: "1rem",
    backgroundColor: "#f8fafc",
    borderRadius: "6px"
  },
  aiLabel: {
    fontWeight: "500",
    marginRight: "0.5rem"
  },
  aiSummary: {
    margin: "0.5rem 0 0",
    color: "#374151",
    fontSize: "0.875rem",
    fontStyle: "italic"
  },
  detailBody: {
    flex: 1,
    padding: "1.5rem",
    overflow: "auto"
  },
  plainText: {
    whiteSpace: "pre-wrap",
    fontFamily: "inherit",
    margin: 0
  },
  attachments: {
    padding: "1rem 1.5rem",
    borderTop: "1px solid #e5e7eb",
    backgroundColor: "#f8fafc"
  },
  attachmentList: {
    display: "flex",
    flexWrap: "wrap",
    gap: "0.5rem",
    marginTop: "0.5rem"
  },
  attachment: {
    padding: "0.5rem 1rem",
    backgroundColor: "white",
    borderRadius: "6px",
    border: "1px solid #e5e7eb",
    fontSize: "0.875rem"
  },
  noSelection: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    height: "100%",
    color: "#6b7280"
  },
  noSelectionIcon: {
    fontSize: "3rem",
    marginBottom: "1rem"
  },
  loading: {
    padding: "2rem",
    textAlign: "center",
    color: "#6b7280"
  },
  empty: {
    padding: "2rem",
    textAlign: "center",
    color: "#6b7280"
  }
}

export default MailPool
