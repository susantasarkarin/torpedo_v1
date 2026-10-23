"use client"
import { useEffect, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { API_BASE_URL } from "../../config"
import { buildApiUrl } from "../../config"
import { notify } from "../../utils/notify"
import { authFetch } from "../../utils/api"

function CompanyDetail() {
  const navigate = useNavigate();
  const { companyName } = useParams(); // Get company name from URL
  const [contacts, setContacts] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  // Fetch contacts for this company
  useEffect(() => {
    const fetchCompanyContacts = async () => {
      const sessionId = localStorage.getItem("session_id");
      if (!sessionId) {
        navigate("/login");
        return;
      }

      setLoading(true);
      try {
        const res = await authFetch(buildApiUrl(`/contacts/`), {
          headers: {
            "Content-Type": "application/json",
            Authorization: sessionId,
          },
        });

        if (res.status === 401) {
          notify("Session expired. Please login again.");
          localStorage.removeItem("session_id");
          navigate("/login");
          return;
        }

        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to load contacts");
        
        // Filter contacts by company name
        const companyContacts = (data.contacts || []).filter(
          c => c.companyName === decodeURIComponent(companyName)
        );
        setContacts(companyContacts);
      } catch (e) {
        setError(e.message || "Failed to load contacts");
      } finally {
        setLoading(false);
      }
    };
    
    fetchCompanyContacts();
  }, [navigate, companyName]);

  const getStageStyle = (stage) => {
    const colors = {
      RFQ: { bg: "#fdf4e7", text: "#d17f08" },
      Proposal: { bg: "#fef3c7", text: "#92400e" },
      Negotiation: { bg: "#e9d5ff", text: "#6b21a8" },
      Won: { bg: "#dcfce7", text: "#166534" },
      Lost: { bg: "#fee2e2", text: "#991b1b" },
    };
    const style = colors[stage] || { bg: "#f5f3ef", text: "#4a4a4a" };
    return {
      backgroundColor: style.bg,
      color: style.text,
      padding: "4px 12px",
      borderRadius: "12px",
      fontSize: "14px",
      fontWeight: "600",
      display: "inline-block",
    };
  };

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <div>
          <button 
            style={styles.backButton} 
            onClick={() => navigate("/admin/sales/account")}
          >
            ← Back to Accounts
          </button>
          <h2 className="cx-page-title" style={styles.title}>{decodeURIComponent(companyName)}</h2>
          <p style={styles.subtitle}>People from this company</p>
        </div>
      </div>

      {error && <div style={styles.errorAlert}>{error}</div>}

      {loading ? (
        <div style={styles.loadingText}>Loading contacts…</div>
      ) : contacts.length === 0 ? (
        <div style={styles.emptyState}>
          <p>No contacts found for this company</p>
        </div>
      ) : (
        <div style={styles.tableContainer}>
          <table style={styles.table}>
            <thead>
              <tr>
                <th style={styles.th}>Name</th>
                <th style={styles.th}>Email</th>
                <th style={styles.th}>Title</th>
                <th style={styles.th}>Phone/Location</th>
                <th style={styles.th}>Stage</th>
                <th style={styles.th}>LinkedIn</th>
                <th style={styles.th}>Company Details</th>
              </tr>
            </thead>
            <tbody>
              {contacts.map((contact) => (
                <tr key={contact._id} style={styles.tr}>
                  <td style={styles.td}>
                    <div style={styles.nameCell}>
                      <div style={styles.name}>{contact.name || `${contact.firstName} ${contact.lastName}`}</div>
                      {contact.firstName && (
                        <div style={styles.subText}>{contact.firstName} {contact.lastName}</div>
                      )}
                    </div>
                  </td>
                  <td style={styles.td}>
                    <div>{contact.email}</div>
                    {contact.emailStatus && (
                      <span style={{
                        ...styles.badge,
                        backgroundColor: contact.emailStatus === "Valid" ? "#dcfce7" : "#fee2e2",
                        color: contact.emailStatus === "Valid" ? "#166534" : "#991b1b",
                      }}>
                        {contact.emailStatus}
                      </span>
                    )}
                  </td>
                  <td style={styles.td}>{contact.title || "—"}</td>
                  <td style={styles.td}>
                    <div>{contact.location || "—"}</div>
                  </td>
                  <td style={styles.td}>
                    <span style={getStageStyle(contact.stage)}>
                      {contact.stage}
                    </span>
                  </td>
                  <td style={styles.td}>
                    {contact.linkedin ? (
                      <a 
                        href={contact.linkedin} 
                        target="_blank" 
                        rel="noopener noreferrer"
                        style={styles.link}
                      >
                        LinkedIn
                      </a>
                    ) : "—"}
                  </td>
                  <td style={styles.td}>
                    <div style={styles.companyDetails}>
                      {contact.companyEmail && (
                        <div style={styles.subText}>📧 {contact.companyEmail}</div>
                      )}
                      {contact.companyWebsite && (
                        <div style={styles.subText}>🌐 {contact.companyWebsite}</div>
                      )}
                      {contact.companyIndustry && (
                        <div style={styles.subText}>🏢 {contact.companyIndustry}</div>
                      )}
                      {contact.companyEmployeeCountRange && (
                        <div style={styles.subText}>👥 {contact.companyEmployeeCountRange}</div>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div style={styles.statsSection}>
        <div style={styles.stat}>
          <span style={styles.statLabel}>Total Contacts:</span>
          <span style={styles.statValue}>{contacts.length}</span>
        </div>
        <div style={styles.stat}>
          <span style={styles.statLabel}>RFQ:</span>
          <span style={styles.statValue}>{contacts.filter(c => c.stage === "RFQ").length}</span>
        </div>
        <div style={styles.stat}>
          <span style={styles.statLabel}>Proposal:</span>
          <span style={styles.statValue}>{contacts.filter(c => c.stage === "Proposal").length}</span>
        </div>
        <div style={styles.stat}>
          <span style={styles.statLabel}>Won:</span>
          <span style={styles.statValue}>{contacts.filter(c => c.stage === "Won").length}</span>
        </div>
      </div>
    </div>
  )
}

const styles = {
  container: {
    padding: "20px",
    maxWidth: "1400px",
    margin: "0 auto",
  },
  header: {
    marginBottom: "24px",
  },
  backButton: {
    background: "none",
    border: "1px solid #e8e4dc",
    padding: "6px 12px",
    borderRadius: "6px",
    cursor: "pointer",
    marginBottom: "12px",
    fontSize: "14px",
  },
  title: {
    fontSize: "28px",
    fontWeight: "700",
    color: "#1a1a1a",
    margin: "8px 0",
  },
  subtitle: {
    fontSize: "14px",
    color: "#5c5c5c",
    margin: "4px 0",
  },
  errorAlert: {
    backgroundColor: "#fee2e2",
    color: "#991b1b",
    padding: "12px 16px",
    borderRadius: "8px",
    marginBottom: "16px",
  },
  loadingText: {
    textAlign: "center",
    padding: "40px",
    color: "#5c5c5c",
  },
  emptyState: {
    textAlign: "center",
    padding: "60px 20px",
    color: "#5c5c5c",
    backgroundColor: "#faf9f7",
    borderRadius: "8px",
  },
  tableContainer: {
    overflowX: "auto",
    backgroundColor: "#fff",
    borderRadius: "8px",
    boxShadow: "0 1px 3px rgba(0,0,0,0.1)",
    marginBottom: "20px",
  },
  table: {
    width: "100%",
    borderCollapse: "collapse",
  },
  th: {
    backgroundColor: "#faf9f7",
    padding: "12px 16px",
    textAlign: "left",
    fontWeight: "600",
    fontSize: "14px",
    color: "#4a4a4a",
    textTransform: "uppercase",
    letterSpacing: "0.5px",
    borderBottom: "2px solid #e8e4dc",
  },
  tr: {
    borderBottom: "1px solid #e8e4dc",
  },
  td: {
    padding: "12px 16px",
    fontSize: "14px",
    color: "#1a1a1a",
  },
  nameCell: {
    display: "flex",
    flexDirection: "column",
    gap: "4px",
  },
  name: {
    fontWeight: "600",
  },
  subText: {
    fontSize: "14px",
    color: "#5c5c5c",
  },
  badge: {
    padding: "2px 8px",
    borderRadius: "12px",
    fontSize: "14px",
    fontWeight: "600",
    marginLeft: "8px",
  },
  link: {
    color: "#a15f06",
    textDecoration: "none",
  },
  companyDetails: {
    display: "flex",
    flexDirection: "column",
    gap: "4px",
  },
  statsSection: {
    display: "flex",
    gap: "24px",
    padding: "20px",
    backgroundColor: "#faf9f7",
    borderRadius: "8px",
  },
  stat: {
    display: "flex",
    gap: "8px",
    alignItems: "center",
  },
  statLabel: {
    fontSize: "14px",
    color: "#5c5c5c",
  },
  statValue: {
    fontSize: "18px",
    fontWeight: "700",
    color: "#1a1a1a",
  },
};

export default CompanyDetail;
