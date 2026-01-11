"use client"

import { useState, useEffect, useCallback } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { API_BASE_URL } from "../config"

function GmailSetup() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [mailboxes, setMailboxes] = useState([])
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState(null)
  const [connecting, setConnecting] = useState(false)

  // Check for OAuth callback
  useEffect(() => {
    const state = searchParams.get("state")
    if (state) {
      // OAuth callback received - the backend should have processed it
      setMessage({ type: "success", text: "Gmail account connected successfully!" })
      navigate("/admin/gmail-setup", { replace: true })
    }
  }, [searchParams, navigate])

  const getAuthHeader = useCallback(() => {
    const sessionId = localStorage.getItem("session_id")
    if (!sessionId) {
      navigate("/admin/login")
      return null
    }
    return sessionId
  }, [navigate])

  // Fetch existing mailboxes
  const fetchMailboxes = useCallback(async () => {
    const auth = getAuthHeader()
    if (!auth) return
    
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE_URL}/gmail/mailboxes`, {
        headers: { Authorization: auth }
      })
      if (res.ok) {
        const data = await res.json()
        setMailboxes(data)
      }
    } catch (err) {
      console.error("Error fetching mailboxes:", err)
    } finally {
      setLoading(false)
    }
  }, [getAuthHeader])

  useEffect(() => {
    fetchMailboxes()
  }, [fetchMailboxes])

  // Connect new Gmail account
  const handleConnect = async () => {
    const auth = getAuthHeader()
    if (!auth) return
    
    setConnecting(true)
    try {
      const res = await fetch(`${API_BASE_URL}/gmail/auth/url`, {
        headers: { Authorization: auth }
      })
      
      if (res.ok) {
        const data = await res.json()
        // Redirect to Google OAuth
        window.location.href = data.auth_url
      } else {
        setMessage({ type: "error", text: "Failed to generate auth URL" })
      }
    } catch (err) {
      console.error("Error:", err)
      setMessage({ type: "error", text: "Connection error" })
    } finally {
      setConnecting(false)
    }
  }

  // Disconnect mailbox
  const handleDisconnect = async (mailboxId) => {
    const auth = getAuthHeader()
    if (!auth) return
    
    if (!confirm("Are you sure you want to disconnect this Gmail account?")) return
    
    try {
      const res = await fetch(`${API_BASE_URL}/gmail/mailboxes/${mailboxId}`, {
        method: "DELETE",
        headers: { Authorization: auth }
      })
      
      if (res.ok) {
        setMessage({ type: "success", text: "Gmail account disconnected" })
        fetchMailboxes()
      } else {
        setMessage({ type: "error", text: "Failed to disconnect" })
      }
    } catch (err) {
      console.error("Error:", err)
      setMessage({ type: "error", text: "Connection error" })
    }
  }

  // Sync mailbox
  const handleSync = async (mailboxId) => {
    const auth = getAuthHeader()
    if (!auth) return
    
    try {
      const res = await fetch(`${API_BASE_URL}/gmail/mailboxes/${mailboxId}/sync`, {
        method: "POST",
        headers: { Authorization: auth }
      })
      
      if (res.ok) {
        const data = await res.json()
        setMessage({ 
          type: "success", 
          text: `Synced ${data.new_emails} new emails, ${data.updated_emails} updated` 
        })
        fetchMailboxes()
      } else {
        setMessage({ type: "error", text: "Sync failed" })
      }
    } catch (err) {
      console.error("Error:", err)
      setMessage({ type: "error", text: "Sync error" })
    }
  }

  return (
    <div style={styles.container}>
      <div style={styles.card}>
        <div style={styles.header}>
          <h1 style={styles.title}>📧 Gmail Integration</h1>
          <p style={styles.subtitle}>
            Connect your Gmail account to sync emails and enable AI-powered classification
          </p>
        </div>

        {message && (
          <div style={{
            ...styles.message,
            backgroundColor: message.type === "success" ? "#d1fae5" : "#fee2e2",
            color: message.type === "success" ? "#065f46" : "#991b1b"
          }}>
            {message.text}
          </div>
        )}

        {/* Connect Button */}
        <div style={styles.connectSection}>
          <button
            style={styles.connectBtn}
            onClick={handleConnect}
            disabled={connecting}
          >
            <img 
              src="https://www.google.com/favicon.ico" 
              alt="Google" 
              style={{ width: 20, height: 20, marginRight: 10 }}
            />
            {connecting ? "Connecting..." : "Connect Gmail Account"}
          </button>
          <p style={styles.hint}>
            Click to authorize Torpedo to access your Gmail account (read-only access to email metadata)
          </p>
        </div>

        {/* Connected Accounts */}
        <div style={styles.section}>
          <h2 style={styles.sectionTitle}>Connected Accounts</h2>
          
          {loading ? (
            <div style={styles.loading}>Loading...</div>
          ) : mailboxes.length === 0 ? (
            <div style={styles.empty}>
              <p>No Gmail accounts connected yet.</p>
              <p style={styles.emptyHint}>
                Connect your Gmail to start syncing and classifying emails with AI.
              </p>
            </div>
          ) : (
            <div style={styles.mailboxList}>
              {mailboxes.map((mailbox) => (
                <div key={mailbox.id} style={styles.mailboxCard}>
                  <div style={styles.mailboxInfo}>
                    <div style={styles.mailboxEmail}>
                      <span style={styles.emailIcon}>📬</span>
                      {mailbox.email}
                    </div>
                    <div style={styles.mailboxMeta}>
                      <span style={styles.metaItem}>
                        📊 {mailbox.total_emails || 0} emails
                      </span>
                      {mailbox.last_sync && (
                        <span style={styles.metaItem}>
                          🔄 Last sync: {new Date(mailbox.last_sync).toLocaleString()}
                        </span>
                      )}
                      <span style={{
                        ...styles.statusBadge,
                        backgroundColor: mailbox.is_active ? "#d1fae5" : "#fee2e2",
                        color: mailbox.is_active ? "#065f46" : "#991b1b"
                      }}>
                        {mailbox.is_active ? "Active" : "Inactive"}
                      </span>
                    </div>
                  </div>
                  <div style={styles.mailboxActions}>
                    <button
                      style={styles.syncBtn}
                      onClick={() => handleSync(mailbox.id)}
                    >
                      🔄 Sync Now
                    </button>
                    <button
                      style={styles.disconnectBtn}
                      onClick={() => handleDisconnect(mailbox.id)}
                    >
                      ❌ Disconnect
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Help Section */}
        <div style={styles.helpSection}>
          <h3 style={styles.helpTitle}>How it works</h3>
          <ul style={styles.helpList}>
            <li>🔐 <strong>Secure OAuth:</strong> We use Google's official OAuth flow - we never see your password</li>
            <li>📋 <strong>Metadata Only:</strong> We only store email metadata (subject, sender, date). Full content is fetched on-demand.</li>
            <li>🤖 <strong>AI Classification:</strong> Our AI automatically categorizes emails by type, department, and priority</li>
            <li>🔄 <strong>Auto Sync:</strong> Emails sync automatically every 15 minutes</li>
          </ul>
        </div>

        {/* Navigation */}
        <div style={styles.navSection}>
          <button
            style={styles.navBtn}
            onClick={() => navigate("/admin/mail-pool")}
          >
            📬 Go to Inbox
          </button>
          <button
            style={styles.navBtnSecondary}
            onClick={() => navigate("/admin/my-profile")}
          >
            👤 Back to Profile
          </button>
        </div>
      </div>
    </div>
  )
}

const styles = {
  container: {
    padding: "2rem",
    backgroundColor: "#f8fafc",
    minHeight: "100vh",
    display: "flex",
    justifyContent: "center"
  },
  card: {
    backgroundColor: "white",
    borderRadius: "12px",
    boxShadow: "0 4px 6px rgba(0,0,0,0.1)",
    padding: "2rem",
    maxWidth: "800px",
    width: "100%"
  },
  header: {
    textAlign: "center",
    marginBottom: "2rem"
  },
  title: {
    margin: 0,
    fontSize: "1.75rem",
    color: "#1f2937"
  },
  subtitle: {
    margin: "0.5rem 0 0",
    color: "#6b7280"
  },
  message: {
    padding: "1rem",
    borderRadius: "8px",
    marginBottom: "1.5rem",
    textAlign: "center"
  },
  connectSection: {
    textAlign: "center",
    marginBottom: "2rem",
    padding: "2rem",
    backgroundColor: "#f8fafc",
    borderRadius: "8px"
  },
  connectBtn: {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    padding: "0.875rem 2rem",
    backgroundColor: "white",
    border: "2px solid #e5e7eb",
    borderRadius: "8px",
    fontSize: "1rem",
    fontWeight: "500",
    color: "#374151",
    cursor: "pointer",
    transition: "all 0.2s"
  },
  hint: {
    marginTop: "0.75rem",
    color: "#6b7280",
    fontSize: "0.875rem"
  },
  section: {
    marginBottom: "2rem"
  },
  sectionTitle: {
    fontSize: "1.125rem",
    color: "#374151",
    marginBottom: "1rem"
  },
  loading: {
    textAlign: "center",
    padding: "2rem",
    color: "#6b7280"
  },
  empty: {
    textAlign: "center",
    padding: "2rem",
    backgroundColor: "#f8fafc",
    borderRadius: "8px"
  },
  emptyHint: {
    color: "#6b7280",
    fontSize: "0.875rem"
  },
  mailboxList: {
    display: "flex",
    flexDirection: "column",
    gap: "1rem"
  },
  mailboxCard: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    padding: "1rem 1.5rem",
    backgroundColor: "#f8fafc",
    borderRadius: "8px",
    border: "1px solid #e5e7eb"
  },
  mailboxInfo: {
    flex: 1
  },
  mailboxEmail: {
    display: "flex",
    alignItems: "center",
    gap: "0.5rem",
    fontSize: "1rem",
    fontWeight: "500",
    color: "#1f2937",
    marginBottom: "0.5rem"
  },
  emailIcon: {
    fontSize: "1.25rem"
  },
  mailboxMeta: {
    display: "flex",
    gap: "1rem",
    flexWrap: "wrap"
  },
  metaItem: {
    fontSize: "0.875rem",
    color: "#6b7280"
  },
  statusBadge: {
    padding: "0.125rem 0.5rem",
    borderRadius: "4px",
    fontSize: "0.75rem",
    fontWeight: "500"
  },
  mailboxActions: {
    display: "flex",
    gap: "0.5rem"
  },
  syncBtn: {
    padding: "0.5rem 1rem",
    backgroundColor: "#3b82f6",
    color: "white",
    border: "none",
    borderRadius: "6px",
    cursor: "pointer",
    fontSize: "0.875rem"
  },
  disconnectBtn: {
    padding: "0.5rem 1rem",
    backgroundColor: "white",
    color: "#991b1b",
    border: "1px solid #fee2e2",
    borderRadius: "6px",
    cursor: "pointer",
    fontSize: "0.875rem"
  },
  helpSection: {
    padding: "1.5rem",
    backgroundColor: "#eff6ff",
    borderRadius: "8px",
    marginBottom: "2rem"
  },
  helpTitle: {
    margin: "0 0 1rem",
    color: "#1e40af",
    fontSize: "1rem"
  },
  helpList: {
    margin: 0,
    paddingLeft: "0",
    listStyle: "none",
    display: "flex",
    flexDirection: "column",
    gap: "0.75rem",
    color: "#374151",
    fontSize: "0.875rem"
  },
  navSection: {
    display: "flex",
    gap: "1rem",
    justifyContent: "center"
  },
  navBtn: {
    padding: "0.75rem 1.5rem",
    backgroundColor: "#3b82f6",
    color: "white",
    border: "none",
    borderRadius: "8px",
    fontSize: "1rem",
    cursor: "pointer"
  },
  navBtnSecondary: {
    padding: "0.75rem 1.5rem",
    backgroundColor: "white",
    color: "#374151",
    border: "1px solid #e5e7eb",
    borderRadius: "8px",
    fontSize: "1rem",
    cursor: "pointer"
  }
}

export default GmailSetup
