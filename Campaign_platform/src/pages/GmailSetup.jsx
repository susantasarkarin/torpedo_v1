"use client"

import { useState, useEffect, useCallback, useRef } from "react"
import { useNavigate } from "react-router-dom"
import { API_BASE_URL } from "../config"

function GmailSetup() {
  const navigate = useNavigate()
  const [mailboxes, setMailboxes] = useState([])
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState(null)
  const [configStatus, setConfigStatus] = useState(null)
  
  // Add mailbox form
  const [showAddForm, setShowAddForm] = useState(false)
  const [newEmail, setNewEmail] = useState("")
  const [newDisplayName, setNewDisplayName] = useState("")
  const [adding, setAdding] = useState(false)
  
  // Service account upload
  const [showUploadModal, setShowUploadModal] = useState(false)
  const [serviceAccountFile, setServiceAccountFile] = useState(null)
  const [uploading, setUploading] = useState(false)
  
  // Sync progress tracking - per mailbox
  const [syncProgress, setSyncProgress] = useState({}) // { mailboxId: { status, total, synced, percent, message } }
  const [classifying, setClassifying] = useState(false)
  const syncIntervalRef = useRef({})

  const getAuthHeader = useCallback(() => {
    const sessionId = localStorage.getItem("session_id")
    if (!sessionId) {
      navigate("/admin/login")
      return null
    }
    return sessionId
  }, [navigate])

  // Check configuration status
  const fetchConfigStatus = useCallback(async () => {
    const auth = getAuthHeader()
    if (!auth) return
    
    try {
      const res = await fetch(`${API_BASE_URL}/gmail-ws/config/status`, {
        headers: { Authorization: auth }
      })
      if (res.ok) {
        const data = await res.json()
        setConfigStatus(data)
      }
    } catch (err) {
      console.error("Error fetching config status:", err)
    }
  }, [getAuthHeader])

  // Fetch existing mailboxes
  const fetchMailboxes = useCallback(async () => {
    const auth = getAuthHeader()
    if (!auth) return
    
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE_URL}/gmail-ws/mailboxes`, {
        headers: { Authorization: auth }
      })
      if (res.ok) {
        const data = await res.json()
        setMailboxes(data.mailboxes || [])
      }
    } catch (err) {
      console.error("Error fetching mailboxes:", err)
    } finally {
      setLoading(false)
    }
  }, [getAuthHeader])

  useEffect(() => {
    fetchConfigStatus()
    fetchMailboxes()
  }, [fetchConfigStatus, fetchMailboxes])

  // Cleanup sync intervals on unmount
  useEffect(() => {
    return () => {
      Object.values(syncIntervalRef.current).forEach(clearInterval)
    }
  }, [])

  // Auto-classify all emails
  const runAutoClassification = async () => {
    const auth = getAuthHeader()
    if (!auth) return
    
    setClassifying(true)
    setMessage({ type: "info", text: "🤖 Starting AI classification of all downloaded emails..." })
    
    try {
      const res = await fetch(`${API_BASE_URL}/gemini/classify-batch`, {
        method: "POST",
        headers: { 
          Authorization: auth,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ limit: 100, extract_leads: true })
      })
      
      if (res.ok) {
        setMessage({ type: "success", text: "✅ AI classification started! Emails are being processed in the background." })
      } else {
        const err = await res.json()
        setMessage({ type: "error", text: err.detail || "Classification failed to start" })
      }
    } catch (err) {
      console.error("Classification error:", err)
      setMessage({ type: "error", text: "Failed to start classification" })
    } finally {
      setClassifying(false)
    }
  }

  // Upload service account credentials
  const handleUploadServiceAccount = async () => {
    if (!serviceAccountFile) {
      setMessage({ type: "error", text: "Please select a service account JSON file" })
      return
    }
    
    const auth = getAuthHeader()
    if (!auth) return
    
    setUploading(true)
    try {
      const fileContent = await serviceAccountFile.text()
      const credentials = JSON.parse(fileContent)
      
      const res = await fetch(`${API_BASE_URL}/gmail-ws/config/service-account`, {
        method: "POST",
        headers: { 
          Authorization: auth,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ credentials })
      })
      
      if (res.ok) {
        setMessage({ type: "success", text: "Service account configured successfully!" })
        setShowUploadModal(false)
        setServiceAccountFile(null)
        fetchConfigStatus()
      } else {
        const err = await res.json()
        setMessage({ type: "error", text: err.detail || "Failed to upload credentials" })
      }
    } catch (err) {
      console.error("Error:", err)
      setMessage({ type: "error", text: "Invalid JSON file" })
    } finally {
      setUploading(false)
    }
  }

  // Add new mailbox with auto-sync and classification
  const handleAddMailbox = async (e) => {
    e.preventDefault()
    
    if (!newEmail.trim()) {
      setMessage({ type: "error", text: "Please enter an email address" })
      return
    }
    
    const auth = getAuthHeader()
    if (!auth) return
    
    setAdding(true)
    setMessage({ type: "info", text: `Connecting to ${newEmail}...` })
    
    try {
      const res = await fetch(`${API_BASE_URL}/gmail-ws/mailboxes`, {
        method: "POST",
        headers: { 
          Authorization: auth,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          email: newEmail.trim(),
          display_name: newDisplayName.trim() || null
        })
      })
      
      const data = await res.json()
      
      if (res.ok && data.success !== false) {
        const mailboxId = data.mailbox?.id || data.id
        setMessage({ type: "success", text: `✅ Mailbox ${newEmail} connected! Starting email download...` })
        setNewEmail("")
        setNewDisplayName("")
        setShowAddForm(false)
        await fetchMailboxes()
        
        // Auto-start sync with progress tracking
        if (mailboxId) {
          handleSyncWithProgress(mailboxId, true) // true = auto-classify after
        }
      } else {
        // Better error messaging for connection issues
        const errorDetail = data.detail || ""
        let errorMessage = "Failed to add mailbox"
        
        if (errorDetail.includes("Cannot access mailbox")) {
          errorMessage = "Cannot access this mailbox. Please ensure domain-wide delegation is configured correctly."
        } else if (errorDetail.includes("Access denied") || errorDetail.includes("403")) {
          errorMessage = "Access denied. Check that the service account has domain-wide delegation permissions."
        } else if (errorDetail.includes("not found") || errorDetail.includes("404")) {
          errorMessage = "User not found in domain. Verify the email address is correct."
        } else if (errorDetail) {
          errorMessage = errorDetail
        }
        
        setMessage({ type: "error", text: errorMessage })
      }
    } catch (err) {
      console.error("Error:", err)
      // Improved error handling for network issues
      if (err.name === "TypeError" && err.message.includes("fetch")) {
        setMessage({ type: "error", text: "Network error: Unable to connect to server. Please check your connection." })
      } else {
        setMessage({ type: "error", text: "Failed to connect mailbox. Please try again." })
      }
    } finally {
      setAdding(false)
    }
  }

  // Disconnect mailbox
  const handleDisconnect = async (mailboxId) => {
    const auth = getAuthHeader()
    if (!auth) return
    
    if (!confirm("Are you sure you want to remove this mailbox?")) return
    
    try {
      const res = await fetch(`${API_BASE_URL}/gmail-ws/mailboxes/${mailboxId}`, {
        method: "DELETE",
        headers: { Authorization: auth }
      })
      
      if (res.ok) {
        setMessage({ type: "success", text: "Mailbox removed" })
        fetchMailboxes()
      } else {
        setMessage({ type: "error", text: "Failed to remove mailbox" })
      }
    } catch (err) {
      console.error("Error:", err)
      setMessage({ type: "error", text: "Connection error" })
    }
  }

  // Sync mailbox with progress tracking
  const handleSyncWithProgress = async (mailboxId, autoClassifyAfter = false, skipRefresh = false) => {
    const auth = getAuthHeader()
    if (!auth) return
    
    // Find mailbox to get email info
    const mailbox = mailboxes.find(m => m.id === mailboxId)
    const emailAddress = mailbox?.email || mailboxId
    
    // Initialize progress
    setSyncProgress(prev => ({
      ...prev,
      [mailboxId]: { 
        status: "checking", 
        total: 0, 
        synced: 0, 
        percent: 0, 
        message: "Checking mailbox..." 
      }
    }))
    
    try {
      // First, test connection to get total message count
      const testRes = await fetch(`${API_BASE_URL}/gmail-ws/mailboxes/${mailboxId}/test`, {
        method: "POST",
        headers: { Authorization: auth }
      })
      
      let totalMessages = 0
      if (testRes.ok) {
        const testData = await testRes.json()
        if (testData.success) {
          totalMessages = testData.messages_total || 0
          setSyncProgress(prev => ({
            ...prev,
            [mailboxId]: { 
              status: "syncing", 
              total: totalMessages, 
              synced: 0, 
              percent: 0,
              message: `Starting download of ${totalMessages.toLocaleString()} emails...` 
            }
          }))
        }
      }
      
      // Start the sync (use full_sync for reliable download)
      const res = await fetch(`${API_BASE_URL}/gmail-ws/mailboxes/${mailboxId}/sync`, {
        method: "POST",
        headers: { 
          Authorization: auth,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ full_sync: true, max_results: 50000 })
      })
      
      if (res.ok) {
        const data = await res.json()
        const newEmails = data.new_emails || 0
        const syncedCount = data.synced || data.email_count || newEmails
        
        setSyncProgress(prev => ({
          ...prev,
          [mailboxId]: { 
            status: "complete", 
            total: totalMessages || syncedCount, 
            synced: syncedCount, 
            percent: 100,
            message: `✅ Downloaded ${syncedCount.toLocaleString()} emails` 
          }
        }))
        
        setMessage({ 
          type: "success", 
          text: `✅ Synced ${newEmails.toLocaleString()} new emails from ${emailAddress}` 
        })
        
        // Only refresh mailboxes if not part of bulk operation
        if (!skipRefresh) {
          fetchMailboxes()
        }
        
        // Auto-classify after sync if requested
        if (autoClassifyAfter && newEmails > 0) {
          setTimeout(() => {
            runAutoClassification()
          }, 1000)
        }
        
        // Clear progress after 5 seconds
        setTimeout(() => {
          setSyncProgress(prev => {
            const newState = { ...prev }
            delete newState[mailboxId]
            return newState
          })
        }, 5000)
        
      } else {
        const err = await res.json()
        // Handle both string and object error details
        const errorMessage = typeof err.detail === 'string' 
          ? err.detail 
          : (Array.isArray(err.detail) 
              ? err.detail.map(e => e.msg || e.message || JSON.stringify(e)).join(', ')
              : JSON.stringify(err.detail) || "Sync failed")
        setSyncProgress(prev => ({
          ...prev,
          [mailboxId]: { 
            status: "error", 
            total: totalMessages, 
            synced: 0, 
            percent: 0,
            message: `❌ ${errorMessage}` 
          }
        }))
        setMessage({ type: "error", text: errorMessage })
      }
    } catch (err) {
      console.error("Error:", err)
      setSyncProgress(prev => ({
        ...prev,
        [mailboxId]: { 
          status: "error", 
          total: 0, 
          synced: 0, 
          percent: 0,
          message: "❌ Sync error - check connection" 
        }
      }))
      setMessage({ type: "error", text: "Sync error" })
    }
  }

  // Wrapper for manual sync (without auto-classify)
  const handleSync = (mailboxId) => {
    handleSyncWithProgress(mailboxId, false)
  }

  // Sync all mailboxes with auto-classification
  const handleSyncAll = async () => {
    setMessage({ type: "info", text: "🔄 Starting sync of all mailboxes..." })
    
    // Sync all mailboxes without refreshing the list each time (skipRefresh = true)
    for (const mailbox of mailboxes) {
      await handleSyncWithProgress(mailbox.id, false, true)
    }
    
    // Refresh mailbox list once after all syncs complete
    fetchMailboxes()
    
    // Run classification after sync (creates AI summaries and classifies)
    setMessage({ type: "info", text: "🤖 Sync complete! Now creating AI summaries and classifying emails..." })
    await runAutoClassification()
  }

  // Test connection
  const handleTestConnection = async (mailboxId) => {
    const auth = getAuthHeader()
    if (!auth) return
    
    try {
      const res = await fetch(`${API_BASE_URL}/gmail-ws/mailboxes/${mailboxId}/test`, {
        method: "POST",
        headers: { Authorization: auth }
      })
      
      if (res.ok) {
        const data = await res.json()
        if (data.success) {
          setMessage({ type: "success", text: `Connection successful! ${data.messages_total} messages in mailbox.` })
        } else {
          setMessage({ type: "error", text: data.error || "Connection test failed" })
        }
      } else {
        setMessage({ type: "error", text: "Test failed" })
      }
    } catch (err) {
      setMessage({ type: "error", text: "Connection error" })
    }
  }

  return (
    <div style={styles.container}>
      <div style={styles.card}>
        <div style={styles.header}>
          <h1 style={styles.title}>📧 Gmail Workspace Integration</h1>
          <p style={styles.subtitle}>
            Connect Google Workspace mailboxes using Service Account delegation
          </p>
        </div>

        {message && (
          <div style={{
            ...styles.message,
            backgroundColor: message.type === "success" ? "#d1fae5" : message.type === "info" ? "#dbeafe" : "#fee2e2",
            color: message.type === "success" ? "#065f46" : message.type === "info" ? "#1e40af" : "#991b1b"
          }}>
            {message.text}
            <button 
              onClick={() => setMessage(null)} 
              style={styles.dismissBtn}
            >×</button>
          </div>
        )}

        {/* Service Account Status */}
        <div style={styles.configSection}>
          <div style={styles.configHeader}>
            <h2 style={styles.sectionTitle}>🔐 Service Account Configuration</h2>
            {configStatus?.configured ? (
              <span style={styles.configuredBadge}>✅ Configured</span>
            ) : (
              <span style={styles.notConfiguredBadge}>⚠️ Not Configured</span>
            )}
          </div>
          
          {configStatus?.configured ? (
            <div style={styles.configInfo}>
              <p><strong>Service Account:</strong> {configStatus.service_account_email}</p>
              <p><strong>Project:</strong> {configStatus.project_id}</p>
              <button
                style={styles.reconfigureBtn}
                onClick={() => setShowUploadModal(true)}
              >
                🔄 Update Credentials
              </button>
            </div>
          ) : (
            <div style={styles.configSetup}>
              <p style={styles.configInstructions}>
                To enable Gmail integration, you need to:
              </p>
              <ol style={styles.setupSteps}>
                <li>Create a Service Account in Google Cloud Console</li>
                <li>Enable the Gmail API</li>
                <li>Enable Domain-Wide Delegation</li>
                <li>Add the service account to Google Workspace Admin</li>
                <li>Upload the service account JSON key below</li>
              </ol>
              <button
                style={styles.uploadBtn}
                onClick={() => setShowUploadModal(true)}
              >
                📤 Upload Service Account Key
              </button>
            </div>
          )}
        </div>

        {/* Add Mailbox Section */}
        {configStatus?.configured && (
          <div style={styles.addSection}>
            {!showAddForm ? (
              <button
                style={styles.addMailboxBtn}
                onClick={() => setShowAddForm(true)}
              >
                ➕ Add Mailbox
              </button>
            ) : (
              <form onSubmit={handleAddMailbox} style={styles.addForm}>
                <h3 style={styles.formTitle}>Add New Mailbox</h3>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Email Address *</label>
                  <input
                    type="email"
                    value={newEmail}
                    onChange={(e) => setNewEmail(e.target.value)}
                    placeholder="user@yourdomain.com"
                    style={styles.input}
                    required
                  />
                </div>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Display Name (optional)</label>
                  <input
                    type="text"
                    value={newDisplayName}
                    onChange={(e) => setNewDisplayName(e.target.value)}
                    placeholder="John Doe"
                    style={styles.input}
                  />
                </div>
                <div style={styles.formActions}>
                  <button
                    type="submit"
                    style={styles.submitBtn}
                    disabled={adding}
                  >
                    {adding ? "Adding..." : "Add Mailbox"}
                  </button>
                  <button
                    type="button"
                    style={styles.cancelBtn}
                    onClick={() => {
                      setShowAddForm(false)
                      setNewEmail("")
                      setNewDisplayName("")
                    }}
                  >
                    Cancel
                  </button>
                </div>
              </form>
            )}
          </div>
        )}

        {/* Connected Mailboxes */}
        <div style={styles.section}>
          <div style={styles.sectionHeader}>
            <h2 style={styles.sectionTitle}>📬 Connected Mailboxes</h2>
            {mailboxes.length > 0 && configStatus?.configured && (
              <div style={styles.sectionActions}>
                <button
                  style={styles.syncAllBtn}
                  onClick={handleSyncAll}
                  disabled={Object.keys(syncProgress).length > 0 || classifying}
                >
                  {classifying ? "⏳ Classifying..." : "🔄 Sync & Classify All"}
                </button>
              </div>
            )}
          </div>
          
          {loading ? (
            <div style={styles.loading}>Loading...</div>
          ) : !configStatus?.configured ? (
            <div style={styles.empty}>
              <p>Configure service account first to add mailboxes.</p>
            </div>
          ) : mailboxes.length === 0 ? (
            <div style={styles.empty}>
              <p>No mailboxes connected yet.</p>
              <p style={styles.emptyHint}>
                Add a Google Workspace email address to start syncing.
              </p>
            </div>
          ) : (
            <div style={styles.mailboxList}>
              {mailboxes.map((mailbox) => {
                const progress = syncProgress[mailbox.id]
                const isSyncing = progress && progress.status === "syncing"
                const isChecking = progress && progress.status === "checking"
                
                return (
                <div key={mailbox.id} style={styles.mailboxCard}>
                  <div style={styles.mailboxInfo}>
                    <div style={styles.mailboxEmail}>
                      <span style={styles.emailIcon}>📬</span>
                      {mailbox.email}
                      {mailbox.display_name && (
                        <span style={styles.displayName}>({mailbox.display_name})</span>
                      )}
                    </div>
                    <div style={styles.mailboxMeta}>
                      <span style={styles.metaItem}>
                        📊 {mailbox.gmail_total ? (
                          <>{(mailbox.gmail_total).toLocaleString()} total in Gmail, {(mailbox.email_count || 0).toLocaleString()} synced</>
                        ) : (
                          <>{(mailbox.email_count || 0).toLocaleString()} emails</>
                        )}
                      </span>
                      {mailbox.last_sync_at && (
                        <span style={styles.metaItem}>
                          🔄 Last sync: {new Date(mailbox.last_sync_at).toLocaleString()}
                        </span>
                      )}
                      {mailbox.sync_error && (
                        <span style={styles.errorBadge}>
                          ⚠️ {mailbox.sync_error}
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
                    
                    {/* Progress Bar */}
                    {progress && (
                      <div style={styles.progressContainer}>
                        <div style={styles.progressInfo}>
                          <span style={styles.progressMessage}>
                            {progress.message}
                          </span>
                          {progress.total > 0 && (
                            <span style={styles.progressStats}>
                              {progress.synced.toLocaleString()} / {progress.total.toLocaleString()}
                            </span>
                          )}
                        </div>
                        <div style={styles.progressBarOuter}>
                          <div 
                            style={{
                              ...styles.progressBarInner,
                              width: `${progress.percent}%`,
                              backgroundColor: progress.status === "error" ? "#ef4444" : 
                                             progress.status === "complete" ? "#22c55e" : "#3b82f6"
                            }}
                          />
                        </div>
                      </div>
                    )}
                  </div>
                  <div style={styles.mailboxActions}>
                    <button
                      style={styles.testBtn}
                      onClick={() => handleTestConnection(mailbox.id)}
                      title="Test connection"
                      disabled={isSyncing || isChecking}
                    >
                      🔌 Test
                    </button>
                    <button
                      style={{
                        ...styles.syncBtn,
                        opacity: (isSyncing || isChecking) ? 0.7 : 1
                      }}
                      onClick={() => handleSync(mailbox.id)}
                      disabled={isSyncing || isChecking}
                    >
                      {isSyncing ? "⏳ Syncing..." : isChecking ? "⏳ Checking..." : "🔄 Sync"}
                    </button>
                    <button
                      style={styles.disconnectBtn}
                      onClick={() => handleDisconnect(mailbox.id)}
                      disabled={isSyncing || isChecking}
                    >
                      ❌
                    </button>
                  </div>
                </div>
              )})}
            </div>
          )}
        </div>

        {/* Help Section */}
        <div style={styles.helpSection}>
          <h3 style={styles.helpTitle}>How Service Account Delegation Works</h3>
          <ul style={styles.helpList}>
            <li>🔐 <strong>Single Credential:</strong> One service account accesses all mailboxes - no individual OAuth required</li>
            <li>🏢 <strong>Domain-Wide:</strong> Admin grants access once, all users in domain are accessible</li>
            <li>📋 <strong>Metadata Only:</strong> We store email metadata (subject, sender, date). Full content fetched on-demand.</li>
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

      {/* Upload Modal */}
      {showUploadModal && (
        <div style={styles.modalOverlay}>
          <div style={styles.modal}>
            <h2 style={styles.modalTitle}>Upload Service Account Key</h2>
            <p style={styles.modalText}>
              Upload the JSON key file downloaded from Google Cloud Console.
            </p>
            <div style={styles.fileUpload}>
              <input
                type="file"
                accept=".json"
                onChange={(e) => setServiceAccountFile(e.target.files[0])}
                style={styles.fileInput}
              />
              {serviceAccountFile && (
                <p style={styles.fileName}>📄 {serviceAccountFile.name}</p>
              )}
            </div>
            <div style={styles.modalActions}>
              <button
                style={styles.uploadConfirmBtn}
                onClick={handleUploadServiceAccount}
                disabled={uploading || !serviceAccountFile}
              >
                {uploading ? "Uploading..." : "Upload & Configure"}
              </button>
              <button
                style={styles.modalCancelBtn}
                onClick={() => {
                  setShowUploadModal(false)
                  setServiceAccountFile(null)
                }}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
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
    maxWidth: "900px",
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
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center"
  },
  dismissBtn: {
    background: "none",
    border: "none",
    fontSize: "1.25rem",
    cursor: "pointer",
    opacity: 0.7
  },
  configSection: {
    padding: "1.5rem",
    backgroundColor: "#f8fafc",
    borderRadius: "8px",
    marginBottom: "2rem",
    border: "1px solid #e5e7eb"
  },
  configHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: "1rem"
  },
  configuredBadge: {
    padding: "0.25rem 0.75rem",
    backgroundColor: "#d1fae5",
    color: "#065f46",
    borderRadius: "9999px",
    fontSize: "0.875rem",
    fontWeight: "500"
  },
  notConfiguredBadge: {
    padding: "0.25rem 0.75rem",
    backgroundColor: "#fef3c7",
    color: "#92400e",
    borderRadius: "9999px",
    fontSize: "0.875rem",
    fontWeight: "500"
  },
  configInfo: {
    color: "#374151",
    fontSize: "0.875rem"
  },
  reconfigureBtn: {
    marginTop: "1rem",
    padding: "0.5rem 1rem",
    backgroundColor: "white",
    color: "#374151",
    border: "1px solid #d1d5db",
    borderRadius: "6px",
    cursor: "pointer",
    fontSize: "0.875rem"
  },
  configSetup: {
    color: "#374151"
  },
  configInstructions: {
    marginBottom: "0.5rem"
  },
  setupSteps: {
    margin: "0 0 1rem",
    paddingLeft: "1.5rem",
    color: "#6b7280",
    fontSize: "0.875rem",
    lineHeight: "1.75"
  },
  uploadBtn: {
    padding: "0.75rem 1.5rem",
    backgroundColor: "#3b82f6",
    color: "white",
    border: "none",
    borderRadius: "8px",
    cursor: "pointer",
    fontSize: "1rem",
    fontWeight: "500"
  },
  addSection: {
    marginBottom: "2rem"
  },
  addMailboxBtn: {
    width: "100%",
    padding: "1rem",
    backgroundColor: "#f0fdf4",
    color: "#166534",
    border: "2px dashed #86efac",
    borderRadius: "8px",
    cursor: "pointer",
    fontSize: "1rem",
    fontWeight: "500",
    transition: "all 0.2s"
  },
  addForm: {
    padding: "1.5rem",
    backgroundColor: "#f8fafc",
    borderRadius: "8px",
    border: "1px solid #e5e7eb"
  },
  formTitle: {
    margin: "0 0 1rem",
    fontSize: "1rem",
    color: "#374151"
  },
  formGroup: {
    marginBottom: "1rem"
  },
  label: {
    display: "block",
    marginBottom: "0.375rem",
    fontSize: "0.875rem",
    color: "#374151",
    fontWeight: "500"
  },
  input: {
    width: "100%",
    padding: "0.625rem 0.75rem",
    border: "1px solid #d1d5db",
    borderRadius: "6px",
    fontSize: "1rem",
    boxSizing: "border-box"
  },
  formActions: {
    display: "flex",
    gap: "0.75rem"
  },
  submitBtn: {
    padding: "0.625rem 1.25rem",
    backgroundColor: "#3b82f6",
    color: "white",
    border: "none",
    borderRadius: "6px",
    cursor: "pointer",
    fontSize: "0.875rem",
    fontWeight: "500"
  },
  cancelBtn: {
    padding: "0.625rem 1.25rem",
    backgroundColor: "white",
    color: "#374151",
    border: "1px solid #d1d5db",
    borderRadius: "6px",
    cursor: "pointer",
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
  displayName: {
    color: "#6b7280",
    fontWeight: "400"
  },
  emailIcon: {
    fontSize: "1.25rem"
  },
  mailboxMeta: {
    display: "flex",
    gap: "1rem",
    flexWrap: "wrap",
    alignItems: "center"
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
  errorBadge: {
    padding: "0.125rem 0.5rem",
    backgroundColor: "#fee2e2",
    color: "#991b1b",
    borderRadius: "4px",
    fontSize: "0.75rem"
  },
  mailboxActions: {
    display: "flex",
    gap: "0.5rem"
  },
  testBtn: {
    padding: "0.5rem 0.75rem",
    backgroundColor: "#eff6ff",
    color: "#1e40af",
    border: "none",
    borderRadius: "6px",
    cursor: "pointer",
    fontSize: "0.875rem"
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
    padding: "0.5rem 0.75rem",
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
  },
  // Modal styles
  modalOverlay: {
    position: "fixed",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: "rgba(0,0,0,0.5)",
    display: "flex",
    justifyContent: "center",
    alignItems: "center",
    zIndex: 1000
  },
  modal: {
    backgroundColor: "white",
    borderRadius: "12px",
    padding: "2rem",
    maxWidth: "500px",
    width: "90%",
    boxShadow: "0 20px 25px rgba(0,0,0,0.15)"
  },
  modalTitle: {
    margin: "0 0 0.5rem",
    fontSize: "1.25rem",
    color: "#1f2937"
  },
  modalText: {
    color: "#6b7280",
    marginBottom: "1.5rem"
  },
  fileUpload: {
    padding: "1.5rem",
    backgroundColor: "#f8fafc",
    borderRadius: "8px",
    border: "2px dashed #d1d5db",
    marginBottom: "1.5rem",
    textAlign: "center"
  },
  fileInput: {
    width: "100%"
  },
  fileName: {
    marginTop: "0.5rem",
    color: "#374151",
    fontSize: "0.875rem"
  },
  modalActions: {
    display: "flex",
    gap: "0.75rem",
    justifyContent: "flex-end"
  },
  uploadConfirmBtn: {
    padding: "0.75rem 1.5rem",
    backgroundColor: "#3b82f6",
    color: "white",
    border: "none",
    borderRadius: "8px",
    cursor: "pointer",
    fontSize: "1rem",
    fontWeight: "500"
  },
  modalCancelBtn: {
    padding: "0.75rem 1.5rem",
    backgroundColor: "white",
    color: "#374151",
    border: "1px solid #d1d5db",
    borderRadius: "8px",
    cursor: "pointer",
    fontSize: "1rem"
  },
  // Section header with actions
  sectionHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: "1rem",
    flexWrap: "wrap",
    gap: "0.5rem"
  },
  sectionActions: {
    display: "flex",
    gap: "0.5rem"
  },
  syncAllBtn: {
    padding: "0.5rem 1rem",
    backgroundColor: "#3b82f6",
    color: "white",
    border: "none",
    borderRadius: "6px",
    cursor: "pointer",
    fontSize: "0.875rem",
    fontWeight: "500"
  },
  classifyBtn: {
    padding: "0.5rem 1rem",
    backgroundColor: "#8b5cf6",
    color: "white",
    border: "none",
    borderRadius: "6px",
    cursor: "pointer",
    fontSize: "0.875rem",
    fontWeight: "500"
  },
  // Progress bar styles
  progressContainer: {
    marginTop: "0.75rem",
    padding: "0.5rem 0"
  },
  progressInfo: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: "0.375rem"
  },
  progressMessage: {
    fontSize: "0.813rem",
    color: "#374151"
  },
  progressStats: {
    fontSize: "0.813rem",
    color: "#6b7280",
    fontWeight: "500"
  },
  progressBarOuter: {
    width: "100%",
    height: "8px",
    backgroundColor: "#e5e7eb",
    borderRadius: "9999px",
    overflow: "hidden"
  },
  progressBarInner: {
    height: "100%",
    borderRadius: "9999px",
    transition: "width 0.3s ease-in-out"
  }
}

export default GmailSetup
