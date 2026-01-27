/**
 * Classified Gmail Page - Manually Review & Move Emails to Leads
 * Shows classified emails from Gemini processing with options to move to leads
 */
"use client"
import { useEffect, useState, useMemo } from "react"
import { useNavigate } from "react-router-dom"
import { API_BASE_URL } from "../../config"
import "./ClassifiedGmail.css"
import { buildApiUrl } from "../../config"

function ClassifiedGmail() {
  const navigate = useNavigate()
  const [emails, setEmails] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [selectedEmails, setSelectedEmails] = useState([])
  const [search, setSearch] = useState("")
  const [filterSegment, setFilterSegment] = useState("")
  const [filterMoved, setFilterMoved] = useState("")
  const [currentPage, setCurrentPage] = useState(1)
  const [limit, setLimit] = useState(20)
  const [total, setTotal] = useState(0)
  const [showModal, setShowModal] = useState(false)
  const [selectedEmail, setSelectedEmail] = useState(null)
  const [moveTarget, setMoveTarget] = useState("CLIENT")
  const [moveCategory, setMoveCategory] = useState("")
  const [moveNotes, setMoveNotes] = useState("")
  const [stats, setStats] = useState(null)
  const [processingEmails, setProcessingEmails] = useState(false)

  const sessionId = localStorage.getItem("session_id")

  // Fetch classified emails with filters
  useEffect(() => {
    const run = async () => {
      if (!sessionId) {
        navigate("/login")
        return
      }

      setLoading(true)
      try {
        let url = buildApiUrl(`/classified-gmail/list?page=${currentPage}&limit=${limit}`)
        if (filterSegment) url += `&segment=${filterSegment}`
        if (filterMoved !== "") url += `&moved=${filterMoved === "true"}`

        const res = await fetch(url, {
          headers: {
            "Content-Type": "application/json",
            Authorization: sessionId,
          },
        })

        if (res.status === 401) {
          navigate("/login")
          return
        }

        const data = await res.json()
        if (!res.ok) throw new Error(data.detail || "Failed to load emails")

        setEmails(data.emails || [])
        setTotal(data.total || 0)
      } catch (e) {
        setError(e.message)
      } finally {
        setLoading(false)
      }
    }
    run()
  }, [currentPage, limit, filterSegment, filterMoved, sessionId, navigate])

  // Fetch statistics
  useEffect(() => {
    const run = async () => {
      if (!sessionId) return

      try {
        const res = await fetch(buildApiUrl(`/classified-gmail/stats?days=7`), {
          headers: {
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
    run()
  }, [sessionId])

  // Process batch of unclassified emails
  const processBatch = async (priorityOnly = false) => {
    if (!sessionId) {
      navigate("/login")
      return
    }

    setProcessingEmails(true)
    try {
      const res = await fetch(buildApiUrl(`/classified-gmail/batch/process`), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: sessionId,
        },
        body: JSON.stringify({
          limit: 100,
          priority_only: priorityOnly,
        }),
      })

      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || "Failed to process batch")

      alert(`✅ Successfully processed ${data.processed} emails`)
      // Refresh list
      setCurrentPage(1)
    } catch (e) {
      setError(e.message)
    } finally {
      setProcessingEmails(false)
    }
  }

  // Move single email to leads
  const moveEmailToLeads = async (emailId) => {
    if (!sessionId) {
      navigate("/login")
      return
    }

    if (!moveTarget) {
      alert("Please select a target segment")
      return
    }

    setLoading(true)
    try {
      const res = await fetch(
        buildApiUrl(`/classified-gmail/${emailId}/move-to-leads`),
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: sessionId,
          },
          body: JSON.stringify({
            segment: moveTarget,
            category: moveCategory,
            notes: moveNotes,
          }),
        }
      )

      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || "Failed to move email")

      alert(`✅ Email moved to ${moveTarget} leads`)
      setShowModal(false)
      setSelectedEmail(null)
      setMoveTarget("CLIENT")
      setMoveCategory("")
      setMoveNotes("")
      // Refresh list
      setCurrentPage(1)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  // Mark email as spam
  const markAsSpam = async (emailId) => {
    if (!window.confirm("Mark this email as spam?")) return

    if (!sessionId) {
      navigate("/login")
      return
    }

    setLoading(true)
    try {
      const res = await fetch(
        buildApiUrl(`/classified-gmail/${emailId}/mark-spam`),
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: sessionId,
          },
          body: JSON.stringify({ reason: "User marked as spam" }),
        }
      )

      if (!res.ok) throw new Error("Failed to mark as spam")

      alert("✅ Email marked as spam")
      setCurrentPage(1)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  // Get segment color
  const getSegmentColor = (segment) => {
    const colors = {
      CLIENT: "#4CAF50",
      VENDOR: "#2196F3",
      RECRUITER: "#FF9800",
      INTERNAL: "#9C27B0",
      SPAM: "#F44336",
    }
    return colors[segment] || "#757575"
  }

  // Get confidence badge
  const getConfidenceBadge = (score) => {
    if (score >= 0.8) return { color: "#4CAF50", label: "High" }
    if (score >= 0.6) return { color: "#FF9800", label: "Medium" }
    return { color: "#F44336", label: "Low" }
  }

  const totalPages = Math.ceil(total / limit)

  return (
    <div className="sales-page classified-gmail-page">
      {/* Page Header */}
      <div className="page-header">
        <div className="header-left">
          <h1>Classified Gmail</h1>
          <p className="subtitle">
            Review classified emails and move high-quality emails to leads
          </p>
        </div>
        <div className="header-actions">
          <button
            className="btn btn-primary"
            onClick={() => processBatch(false)}
            disabled={processingEmails}
          >
            {processingEmails ? "⏳ Processing..." : "🔄 Process Batch"}
          </button>
        </div>
      </div>

      {error && <div className="error-alert">{error}</div>}

      {/* Statistics Cards */}
      {stats && (
        <div className="stats-grid">
          <div className="stat-card">
            <div className="stat-value">{stats.total_classified}</div>
            <div className="stat-label">Total Classified</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{stats.total_moved_to_leads}</div>
            <div className="stat-label">Moved to Leads</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{stats.pending_moves}</div>
            <div className="stat-label">Pending Review</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">
              {stats.move_success_rate.toFixed(1)}%
            </div>
            <div className="stat-label">Success Rate</div>
          </div>
        </div>
      )}

      {/* Segment Breakdown */}
      {stats && (
        <div className="segment-breakdown">
          <h3>Classification Breakdown</h3>
          <div className="segment-cards">
            {stats.by_segment.map((seg) => (
              <div key={seg.segment} className="segment-card">
                <div className="segment-icon" style={{ backgroundColor: getSegmentColor(seg.segment) }}>
                  {seg.segment[0]}
                </div>
                <div className="segment-info">
                  <h4>{seg.segment}</h4>
                  <p className="segment-count">{seg.count} total</p>
                  <p className="segment-rate">
                    {seg.move_rate.toFixed(0)}% moved ({seg.moved}/{seg.count})
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Filters Bar */}
      <div className="filters-bar">
        <div className="filter-group">
          <label>Segment:</label>
          <select
            value={filterSegment}
            onChange={(e) => {
              setFilterSegment(e.target.value)
              setCurrentPage(1)
            }}
          >
            <option value="">All Segments</option>
            <option value="CLIENT">CLIENT</option>
            <option value="VENDOR">VENDOR</option>
            <option value="RECRUITER">RECRUITER</option>
            <option value="INTERNAL">INTERNAL</option>
            <option value="SPAM">SPAM</option>
          </select>
        </div>

        <div className="filter-group">
          <label>Status:</label>
          <select
            value={filterMoved}
            onChange={(e) => {
              setFilterMoved(e.target.value)
              setCurrentPage(1)
            }}
          >
            <option value="">All</option>
            <option value="false">Pending</option>
            <option value="true">Moved</option>
          </select>
        </div>

        <input
          className="search-input"
          type="text"
          placeholder="Search by email, sender, subject..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {/* Emails List */}
      {loading ? (
        <div className="loading">Loading classified emails...</div>
      ) : emails.length === 0 ? (
        <div className="empty-state">
          <h3>No classified emails found</h3>
          <p>
            Run the batch processor to classify emails from your mail pool.
          </p>
          <button
            className="btn btn-primary"
            onClick={() => processBatch(false)}
          >
            Process Emails
          </button>
        </div>
      ) : (
        <div className="emails-list">
          {emails.map((email) => {
            const confidence = getConfidenceBadge(email.confidence_score)
            return (
              <div key={email.id} className="email-card">
                <div className="email-header">
                  <div className="email-sender">
                    <span
                      className="segment-badge"
                      style={{ backgroundColor: getSegmentColor(email.segment) }}
                    >
                      {email.segment}
                    </span>
                    <div className="sender-info">
                      <h4>{email.sender_email}</h4>
                      <p className="email-subject">{email.subject}</p>
                    </div>
                  </div>
                  <div className="email-meta">
                    <span
                      className="confidence-badge"
                      style={{ backgroundColor: confidence.color }}
                    >
                      {confidence.label} ({(email.confidence_score * 100).toFixed(0)}%)
                    </span>
                    {email.sentiment && (
                      <span className="sentiment-badge">{email.sentiment}</span>
                    )}
                    {email.moved_to_leads && (
                      <span className="moved-badge">✓ Moved</span>
                    )}
                  </div>
                </div>

                <div className="email-body">
                  {email.summary && (
                    <p className="email-summary">{email.summary}</p>
                  )}

                  {email.contacts.length > 0 && (
                    <div className="email-contacts">
                      <h5>Contacts Found:</h5>
                      <ul>
                        {email.contacts.map((contact, idx) => (
                          <li key={idx}>
                            {contact.name}
                            {contact.title && ` • ${contact.title}`}
                            {contact.company && ` • ${contact.company}`}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>

                <div className="email-actions">
                  {!email.moved_to_leads && (
                    <>
                      <button
                        className="btn-action move"
                        onClick={() => {
                          setSelectedEmail(email)
                          setMoveTarget("CLIENT")
                          setMoveCategory("")
                          setMoveNotes("")
                          setShowModal(true)
                        }}
                      >
                        ➜ Move to Leads
                      </button>
                      <button
                        className="btn-action spam"
                        onClick={() => markAsSpam(email.id)}
                      >
                        🚫 Mark Spam
                      </button>
                    </>
                  )}
                  {email.moved_to_leads && (
                    <span className="moved-info">
                      ✓ Moved at{" "}
                      {new Date(email.moved_at).toLocaleDateString()} by{" "}
                      {email.moved_by}
                    </span>
                  )}
                </div>

                {email.notes && <p className="email-notes">📝 {email.notes}</p>}
              </div>
            )
          })}
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="pagination-bar">
          <button
            className="btn btn-outline"
            onClick={() => setCurrentPage(Math.max(1, currentPage - 1))}
            disabled={currentPage === 1}
          >
            ← Previous
          </button>
          <span className="page-info">
            Page <strong>{currentPage}</strong> of <strong>{totalPages}</strong>
          </span>
          <button
            className="btn btn-outline"
            onClick={() =>
              setCurrentPage(Math.min(totalPages, currentPage + 1))
            }
            disabled={currentPage === totalPages}
          >
            Next →
          </button>
        </div>
      )}

      {/* Move to Leads Modal */}
      {showModal && selectedEmail && (
        <div className="modal-overlay" onClick={() => setShowModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Move to Leads</h3>
              <button
                className="modal-close-btn"
                onClick={() => setShowModal(false)}
              >
                ×
              </button>
            </div>

            <div className="modal-body">
              <div className="email-preview">
                <h4>Email Details</h4>
                <p>
                  <strong>From:</strong> {selectedEmail.sender_email}
                </p>
                <p>
                  <strong>Subject:</strong> {selectedEmail.subject}
                </p>
                {selectedEmail.summary && (
                  <p>
                    <strong>Summary:</strong> {selectedEmail.summary}
                  </p>
                )}
              </div>

              <div className="form-group">
                <label>Target Segment *</label>
                <select
                  value={moveTarget}
                  onChange={(e) => setMoveTarget(e.target.value)}
                >
                  <option value="CLIENT">CLIENT - Prospect/Lead</option>
                  <option value="VENDOR">VENDOR - Vendor/Partner</option>
                  <option value="RECRUITER">RECRUITER - Recruitment</option>
                  <option value="INTERNAL">INTERNAL - Internal</option>
                </select>
              </div>

              <div className="form-group">
                <label>Category (optional)</label>
                <input
                  type="text"
                  placeholder="e.g., Technology, Finance"
                  value={moveCategory}
                  onChange={(e) => setMoveCategory(e.target.value)}
                />
              </div>

              <div className="form-group">
                <label>Notes (optional)</label>
                <textarea
                  placeholder="Add any additional notes..."
                  value={moveNotes}
                  onChange={(e) => setMoveNotes(e.target.value)}
                  rows={3}
                ></textarea>
              </div>

              <div className="modal-actions">
                <button
                  className="btn btn-outline"
                  onClick={() => setShowModal(false)}
                >
                  Cancel
                </button>
                <button
                  className="btn btn-primary"
                  onClick={() => moveEmailToLeads(selectedEmail.id)}
                  disabled={loading}
                >
                  {loading ? "Moving..." : "Move to Leads"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default ClassifiedGmail
