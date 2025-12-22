"use client"

import { useEffect, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { API_BASE_URL } from "../../config"
import { getStageById, getStageStyle as getPipelineStageStyle } from "../../utils/salesPipeline"

const styles = {
  container: {
    padding: "1.5rem",
    maxWidth: "1000px",
    margin: "0 auto",
  },
  backButton: {
    display: "flex",
    alignItems: "center",
    gap: "0.5rem",
    color: "#6b7280",
    background: "none",
    border: "none",
    cursor: "pointer",
    padding: "0.5rem 0",
    marginBottom: "1rem",
    fontSize: "0.875rem",
  },
  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "flex-start",
    marginBottom: "2rem",
  },
  title: {
    fontSize: "1.75rem",
    fontWeight: "700",
    color: "#111827",
    margin: 0,
  },
  subtitle: {
    color: "#6b7280",
    marginTop: "0.25rem",
    fontSize: "0.9rem",
  },
  actionButtons: {
    display: "flex",
    gap: "0.75rem",
  },
  btnPrimary: {
    padding: "0.625rem 1.25rem",
    backgroundColor: "#0d6efd",
    color: "#fff",
    border: "none",
    borderRadius: "6px",
    cursor: "pointer",
    fontWeight: "500",
    display: "flex",
    alignItems: "center",
    gap: "0.5rem",
  },
  btnSecondary: {
    padding: "0.625rem 1.25rem",
    backgroundColor: "#fff",
    color: "#374151",
    border: "1px solid #d1d5db",
    borderRadius: "6px",
    cursor: "pointer",
    fontWeight: "500",
  },
  btnSuccess: {
    padding: "0.625rem 1.25rem",
    backgroundColor: "#16a34a",
    color: "#fff",
    border: "none",
    borderRadius: "6px",
    cursor: "pointer",
    fontWeight: "500",
  },
  btnDanger: {
    padding: "0.625rem 1.25rem",
    backgroundColor: "#dc2626",
    color: "#fff",
    border: "none",
    borderRadius: "6px",
    cursor: "pointer",
    fontWeight: "500",
  },
  card: {
    background: "#fff",
    borderRadius: "12px",
    boxShadow: "0 1px 3px rgba(0,0,0,0.1)",
    border: "1px solid #e5e7eb",
    padding: "1.5rem",
    marginBottom: "1.5rem",
  },
  cardTitle: {
    fontSize: "1.1rem",
    fontWeight: "600",
    color: "#111827",
    margin: "0 0 1rem 0",
    display: "flex",
    alignItems: "center",
    gap: "0.5rem",
  },
  infoGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(250px, 1fr))",
    gap: "1rem",
  },
  infoItem: {
    padding: "0.75rem",
    backgroundColor: "#f9fafb",
    borderRadius: "8px",
  },
  infoLabel: {
    fontSize: "0.75rem",
    fontWeight: "600",
    color: "#6b7280",
    textTransform: "uppercase",
    letterSpacing: "0.5px",
    marginBottom: "0.25rem",
  },
  infoValue: {
    fontSize: "0.95rem",
    color: "#111827",
    wordBreak: "break-word",
  },
  statusBadge: {
    display: "inline-block",
    padding: "0.25rem 0.75rem",
    borderRadius: "12px",
    fontSize: "0.75rem",
    fontWeight: "600",
  },
  statusValid: {
    backgroundColor: "#dcfce7",
    color: "#166534",
  },
  statusInvalid: {
    backgroundColor: "#fee2e2",
    color: "#991b1b",
  },
  loading: {
    display: "flex",
    justifyContent: "center",
    alignItems: "center",
    padding: "4rem",
    color: "#6b7280",
  },
  error: {
    padding: "1rem",
    backgroundColor: "#fef2f2",
    border: "1px solid #fecaca",
    borderRadius: "8px",
    color: "#dc2626",
    marginBottom: "1rem",
  },
  linkValue: {
    color: "#0d6efd",
    textDecoration: "none",
  },
}

function LeadDetail() {
  const { leadId } = useParams()
  const navigate = useNavigate()
  const [lead, setLead] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetchLead()
  }, [leadId])

  const fetchLead = async () => {
    const sessionId = localStorage.getItem("session_id")
    if (!sessionId) {
      navigate("/login")
      return
    }

    setLoading(true)
    setError(null)

    try {
      const res = await fetch(`${API_BASE_URL}/leads/${leadId}`, {
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

      if (res.status === 404) {
        setError("Lead not found")
        setLoading(false)
        return
      }

      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || "Failed to load lead")
      setLead(data.lead)
    } catch (e) {
      setError(e.message || "Failed to load lead")
    } finally {
      setLoading(false)
    }
  }

  const moveToContacts = async () => {
    if (!window.confirm("Move this lead to Contacts (Discovery Call stage)?")) return

    const sessionId = localStorage.getItem("session_id")
    try {
      const res = await fetch(`${API_BASE_URL}/leads/${leadId}/move-to-contacts`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: sessionId,
        },
        body: JSON.stringify({ stage: "discovery_call" }),
      })

      if (res.ok) {
        alert("✅ Lead moved to Contacts successfully!")
        navigate("/admin/sales/leads")
      } else {
        const data = await res.json()
        alert(data.detail || "Failed to move lead")
      }
    } catch (e) {
      alert("Failed to move lead: " + e.message)
    }
  }

  const deleteLead = async () => {
    if (!window.confirm("Are you sure you want to delete this lead?")) return

    const sessionId = localStorage.getItem("session_id")
    try {
      const res = await fetch(`${API_BASE_URL}/leads/${leadId}`, {
        method: "DELETE",
        headers: {
          "Content-Type": "application/json",
          Authorization: sessionId,
        },
      })

      if (res.ok) {
        alert("Lead deleted successfully")
        navigate("/admin/sales/leads")
      } else {
        const data = await res.json()
        alert(data.detail || "Failed to delete lead")
      }
    } catch (e) {
      alert("Failed to delete lead: " + e.message)
    }
  }

  const formatDate = (dateStr) => {
    if (!dateStr) return "N/A"
    return new Date(dateStr).toLocaleString()
  }

  const renderInfoItem = (label, value, isLink = false) => {
    if (!value) return null
    return (
      <div style={styles.infoItem}>
        <div style={styles.infoLabel}>{label}</div>
        <div style={styles.infoValue}>
          {isLink ? (
            <a href={value} target="_blank" rel="noopener noreferrer" style={styles.linkValue}>
              {value}
            </a>
          ) : (
            value
          )}
        </div>
      </div>
    )
  }

  if (loading) {
    return (
      <div style={styles.container}>
        <div style={styles.loading}>
          <span>⏳ Loading lead details...</span>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div style={styles.container}>
        <button style={styles.backButton} onClick={() => navigate("/admin/sales/leads")}>
          ◀ Back to Leads
        </button>
        <div style={styles.error}>❌ {error}</div>
      </div>
    )
  }

  if (!lead) return null

  const displayName = lead.name || `${lead.firstName || ""} ${lead.lastName || ""}`.trim() || "Unnamed Lead"
  const stageInfo = getStageById(lead.stage)
  const stageStyle = getPipelineStageStyle(lead.stage)

  return (
    <div style={styles.container}>
      <button style={styles.backButton} onClick={() => navigate("/admin/sales/leads")}>
        ◀ Back to Leads
      </button>

      <div style={styles.header}>
        <div>
          <h1 style={styles.title}>{displayName}</h1>
          <p style={styles.subtitle}>
            {lead.title && `${lead.title} • `}
            {lead.companyName || "No company"}
            <span
              style={{
                ...styles.statusBadge,
                backgroundColor: stageStyle.bg,
                color: stageStyle.color,
                marginLeft: "0.75rem",
              }}
            >
              {stageInfo?.icon} {stageInfo?.label || lead.stage || 'Lead Generation'}
            </span>
            {lead.emailStatus && (
              <span
                style={{
                  ...styles.statusBadge,
                  ...(lead.emailStatus === "Valid" ? styles.statusValid : styles.statusInvalid),
                  marginLeft: "0.5rem",
                }}
              >
                {lead.emailStatus}
              </span>
            )}
          </p>
        </div>
        <div style={styles.actionButtons}>
          <button style={styles.btnSuccess} onClick={moveToContacts}>
            ➡️ Move to Contacts
          </button>
          <button style={styles.btnDanger} onClick={deleteLead}>
            🗑️ Delete
          </button>
        </div>
      </div>

      {/* Personal Information */}
      <div style={styles.card}>
        <h3 style={styles.cardTitle}>👤 Personal Information</h3>
        <div style={styles.infoGrid}>
          {renderInfoItem("Full Name", lead.name)}
          {renderInfoItem("First Name", lead.firstName)}
          {renderInfoItem("Last Name", lead.lastName)}
          {renderInfoItem("Email", lead.email)}
          {renderInfoItem("Email Status", lead.emailStatus)}
          {renderInfoItem("Job Title", lead.title)}
          {renderInfoItem("LinkedIn", lead.linkedin, true)}
          {renderInfoItem("Location", lead.location)}
        </div>
      </div>

      {/* Company Information */}
      <div style={styles.card}>
        <h3 style={styles.cardTitle}>🏢 Company Information</h3>
        <div style={styles.infoGrid}>
          {renderInfoItem("Company Name", lead.companyName)}
          {renderInfoItem("Domain", lead.companyDomain)}
          {renderInfoItem("Website", lead.companyWebsite, true)}
          {renderInfoItem("Industry", lead.companyIndustry)}
          {renderInfoItem("Company Type", lead.companyType)}
          {renderInfoItem("Headquarters", lead.companyHeadquarters)}
          {renderInfoItem("Employee Count", lead.companyEmployeeCount)}
          {renderInfoItem("Employee Range", lead.companyEmployeeCountRange)}
          {renderInfoItem("Year Founded", lead.companyFounded)}
          {renderInfoItem("Revenue Range", lead.companyRevenueRange)}
          {renderInfoItem("Company LinkedIn", lead.companyLinkedinUrl, true)}
          {renderInfoItem("Crunchbase", lead.companyCrunchbaseUrl, true)}
          {renderInfoItem("Funding Rounds", lead.companyFundingRounds)}
          {renderInfoItem("Last Funding Amount", lead.companyLastFundingRoundAmount)}
        </div>
      </div>

      {/* Metadata */}
      <div style={styles.card}>
        <h3 style={styles.cardTitle}>📋 Record Information</h3>
        <div style={styles.infoGrid}>
          {renderInfoItem("Lead ID", lead._id)}
          {renderInfoItem("Source", lead.source || "Manual")}
          {renderInfoItem("Added On", formatDate(lead.addedOn))}
          {renderInfoItem("Created At", formatDate(lead.createdAt))}
          {renderInfoItem("Updated At", formatDate(lead.updatedAt))}
        </div>
      </div>
    </div>
  )
}

export default LeadDetail
