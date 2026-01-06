/**
 * AI Lead Detail Page - Zoho CRM Style
 * Path: /admin/sales/campaign/ai-leads/:leadId
 */

import React, { useState, useEffect } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { API_BASE_URL } from "../../../config";
import "./AILeadDetail.css";

function AILeadDetail() {
  const { leadId } = useParams();
  const navigate = useNavigate();
  const [lead, setLead] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState("overview");
  const [activeSection, setActiveSection] = useState("notes");
  
  // Section Edit State (per-section editing)
  const [editingSection, setEditingSection] = useState(null); // 'lead', 'company', 'ai', etc.
  const [editFormData, setEditFormData] = useState({});
  const [saving, setSaving] = useState(false);
  
  // Email Compose Modal State
  const [showEmailModal, setShowEmailModal] = useState(false);
  const [emailFormData, setEmailFormData] = useState({
    to: "",
    cc: "",
    bcc: "",
    subject: "",
    body: "",
    replyTo: ""
  });
  const [sendingEmail, setSendingEmail] = useState(false);
  const [imapAccounts, setImapAccounts] = useState([]);
  const [selectedAccount, setSelectedAccount] = useState(null);
  const [signature, setSignature] = useState("");

  useEffect(() => {
    fetchLead();
    fetchImapAccounts();
  }, [leadId]);

  const fetchLead = async () => {
    const sessionId = localStorage.getItem("session_id");
    if (!sessionId) {
      navigate("/login");
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const res = await fetch(`${API_BASE_URL}/leads/enriched/${leadId}`, {
        headers: {
          "Content-Type": "application/json",
          Authorization: sessionId,
        },
      });

      if (res.status === 401) {
        alert("Session expired. Please login again.");
        localStorage.removeItem("session_id");
        navigate("/login");
        return;
      }

      if (res.status === 404) {
        setError("Lead not found");
        setLoading(false);
        return;
      }

      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to load lead");
      setLead(data.lead);
      setEditFormData(data.lead);
    } catch (e) {
      setError(e.message || "Failed to load lead");
    } finally {
      setLoading(false);
    }
  };

  const fetchImapAccounts = async () => {
    const sessionId = localStorage.getItem("session_id");
    if (!sessionId) return;

    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/email-sync/accounts`, {
        headers: {
          "Content-Type": "application/json",
          Authorization: sessionId,
        },
      });
      if (res.ok) {
        const data = await res.json();
        setImapAccounts(data.accounts || []);
        if (data.accounts?.length > 0) {
          setSelectedAccount(data.accounts[0]);
          fetchSignature(data.accounts[0].email);
        }
      }
    } catch (e) {
      console.error("Failed to fetch IMAP accounts:", e);
    }
  };

  const fetchSignature = async (email) => {
    const sessionId = localStorage.getItem("session_id");
    if (!sessionId || !email) return;

    try {
      const res = await fetch(`${API_BASE_URL}/settings/email-signature/${encodeURIComponent(email)}`, {
        headers: {
          "Content-Type": "application/json",
          Authorization: sessionId,
        },
      });
      if (res.ok) {
        const data = await res.json();
        setSignature(data.signature || "");
      }
    } catch (e) {
      console.error("Failed to fetch signature:", e);
    }
  };

  const handleAccountChange = (e) => {
    const account = imapAccounts.find(acc => acc.email === e.target.value);
    setSelectedAccount(account);
    if (account) {
      fetchSignature(account.email);
    }
  };

  const handleSaveLead = async () => {
    const sessionId = localStorage.getItem("session_id");
    if (!sessionId) return;

    setSaving(true);
    try {
      const res = await fetch(`${API_BASE_URL}/leads/enriched/${leadId}`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          Authorization: sessionId,
        },
        body: JSON.stringify(editFormData),
      });

      if (res.ok) {
        const data = await res.json();
        setLead(data.lead || editFormData);
        setEditingSection(null);
        alert("Lead updated successfully!");
      } else {
        const errData = await res.json();
        alert(errData.detail || "Failed to save lead");
      }
    } catch (e) {
      alert("Failed to save lead: " + e.message);
    } finally {
      setSaving(false);
    }
  };

  const openEmailModal = () => {
    setEmailFormData({
      to: lead.email || "",
      cc: "",
      bcc: "",
      subject: "",
      body: "",
      replyTo: selectedAccount?.email || ""
    });
    setShowEmailModal(true);
  };

  const handleSendEmail = async () => {
    const sessionId = localStorage.getItem("session_id");
    if (!sessionId || !selectedAccount) {
      alert("Please select an email account");
      return;
    }

    if (!emailFormData.to || !emailFormData.subject) {
      alert("Please fill in To and Subject fields");
      return;
    }

    setSendingEmail(true);
    try {
      const fullBody = signature ? `${emailFormData.body}\n\n${signature}` : emailFormData.body;

      const res = await fetch(`${API_BASE_URL}/api/v1/email-sync/send`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: sessionId,
        },
        body: JSON.stringify({
          account_email: selectedAccount.email,
          to: emailFormData.to.split(",").map(e => e.trim()),
          cc: emailFormData.cc ? emailFormData.cc.split(",").map(e => e.trim()) : [],
          bcc: emailFormData.bcc ? emailFormData.bcc.split(",").map(e => e.trim()) : [],
          subject: emailFormData.subject,
          body: fullBody,
          reply_to: emailFormData.replyTo,
          lead_id: leadId
        }),
      });

      if (res.ok) {
        alert("Email sent successfully!");
        setShowEmailModal(false);
        fetchLead();
      } else {
        const errData = await res.json();
        alert(errData.detail || "Failed to send email");
      }
    } catch (e) {
      alert("Failed to send email: " + e.message);
    } finally {
      setSendingEmail(false);
    }
  };

  const scrollToSection = (sectionId) => {
    setActiveSection(sectionId);
    const element = document.getElementById(`section-${sectionId}`);
    if (element) {
      element.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  };

  const formatDate = (dateStr) => {
    if (!dateStr) return "—";
    const date = new Date(dateStr);
    return date.toLocaleDateString("en-US", {
      weekday: "short",
      day: "numeric",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  const getDaysSinceUpdate = (dateStr) => {
    if (!dateStr) return null;
    const date = new Date(dateStr);
    const now = new Date();
    const diffTime = Math.abs(now - date);
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
    return diffDays;
  };

  if (loading) {
    return (
      <div className="lead-detail-zoho">
        <div className="loading-state">
          <div className="spinner"></div>
          <span>Loading lead details...</span>
        </div>
      </div>
    );
  }

  if (error || !lead) {
    return (
      <div className="lead-detail-zoho">
        <div className="error-state">
          <h2>❌ {error || "Lead Not Found"}</h2>
          <button className="btn-primary" onClick={() => navigate(-1)}>
            ← Go Back
          </button>
        </div>
      </div>
    );
  }

  const lastUpdate = getDaysSinceUpdate(lead.updated_at || lead.created_at);

  return (
    <div className="lead-detail-zoho">
      {/* Top Header Bar */}
      <div className="top-header">
        <div className="header-left">
          <button className="back-btn" onClick={() => navigate(-1)}>←</button>
          <div className="lead-identity">
            <h1>{lead.name || `${lead.first_name || ""} ${lead.last_name || ""}`.trim() || "Unknown"}</h1>
            <span className="company-tag">- {lead.company_name || "Unknown Company"}</span>
          </div>
          <button className="add-tags-btn">🏷️ Add Tags</button>
        </div>
        <div className="header-actions">
          {lead.email && (
            <button className="action-btn primary" onClick={openEmailModal}>
              Send Email
            </button>
          )}
          <button className="action-btn secondary">Convert</button>
          {lead.linkedin_url && (
            <a href={lead.linkedin_url} target="_blank" rel="noopener noreferrer" className="action-btn linkedin">
              LinkedIn
            </a>
          )}
        </div>
      </div>

      {/* Main Layout */}
      <div className="main-layout">
        {/* Left Sidebar */}
        <aside className="left-sidebar">
          <div className="sidebar-section">
            <h3>Related List</h3>
            <ul className="related-list">
              <li className={activeSection === "notes" ? "active" : ""} onClick={() => scrollToSection("notes")}>Notes</li>
              <li className={activeSection === "connected" ? "active" : ""} onClick={() => scrollToSection("connected")}>Connected Records</li>
              <li className={activeSection === "cadences" ? "active" : ""} onClick={() => scrollToSection("cadences")}>Cadences</li>
              <li className={activeSection === "attachments" ? "active" : ""} onClick={() => scrollToSection("attachments")}>Attachments</li>
              <li className={activeSection === "activities" ? "active" : ""} onClick={() => scrollToSection("activities")}>Open Activities</li>
              <li className={activeSection === "closed" ? "active" : ""} onClick={() => scrollToSection("closed")}>Closed Activities</li>
              <li className={activeSection === "meetings" ? "active" : ""} onClick={() => scrollToSection("meetings")}>Invited Meetings</li>
              <li className={activeSection === "emails" ? "active" : ""} onClick={() => scrollToSection("emails")}>
                Emails {lead.emails?.length > 0 && <span className="count-badge">{lead.emails.length}</span>}
              </li>
            </ul>
          </div>
          <div className="sidebar-section">
            <h3>Links</h3>
            <ul className="links-list">
              {lead.linkedin_url ? (
                <li>
                  <a href={lead.linkedin_url} target="_blank" rel="noopener noreferrer">
                    🔗 LinkedIn Profile
                  </a>
                </li>
              ) : (
                <li className="no-links">No Links Found</li>
              )}
              {lead.company_linkedin_url && (
                <li>
                  <a href={lead.company_linkedin_url} target="_blank" rel="noopener noreferrer">
                    🏢 Company LinkedIn
                  </a>
                </li>
              )}
              {lead.company_website && (
                <li>
                  <a href={lead.company_website.startsWith("http") ? lead.company_website : `https://${lead.company_website}`} target="_blank" rel="noopener noreferrer">
                    🌐 Company Website
                  </a>
                </li>
              )}
            </ul>
          </div>
        </aside>

        {/* Main Content */}
        <main className="main-content">
          {/* Tabs */}
          <div className="content-header">
            <div className="tabs">
              <button className={`tab ${activeTab === "overview" ? "active" : ""}`} onClick={() => setActiveTab("overview")}>
                Overview
              </button>
              <button className={`tab ${activeTab === "timeline" ? "active" : ""}`} onClick={() => setActiveTab("timeline")}>
                Timeline
              </button>
            </div>
            <div className="last-update">
              🕐 Last Update : {lastUpdate ? `${lastUpdate} day(s) ago` : "—"}
            </div>
          </div>

          {/* Overview Content */}
          {activeTab === "overview" && (
            <div className="overview-content">
              {/* Lead Information Section */}
              <div className="info-section">
                <div className="section-title-row">
                  <h3>Lead Information</h3>
                  <button className="section-edit-btn" onClick={() => { setEditingSection('lead'); setEditFormData({...lead}); }}>
                    ✏️ Edit
                  </button>
                </div>
                <div className="info-grid">
                  <div className="info-row">
                    <span className="label">Email</span>
                    <span className="value link">{lead.email || "—"}</span>
                  </div>
                  <div className="info-row">
                    <span className="label">Lead Name</span>
                    <span className="value">{lead.last_name || lead.name || "—"}</span>
                  </div>
                  <div className="info-row">
                    <span className="label">LinkedIn</span>
                    <span className="value">{lead.linkedin_url ? <a href={lead.linkedin_url} target="_blank" rel="noopener noreferrer">View Profile ↗</a> : "—"}</span>
                  </div>
                  <div className="info-row">
                    <span className="label">Title</span>
                    <span className="value">{lead.title || "—"}</span>
                  </div>
                  <div className="info-row">
                    <span className="label">Company</span>
                    <span className="value">{lead.company_name || "—"}</span>
                  </div>
                  <div className="info-row">
                    <span className="label">Location</span>
                    <span className="value">{lead.location || "—"}</span>
                  </div>
                  <div className="info-row">
                    <span className="label">Lead Source</span>
                    <span className="value">{lead.source === "web_search" ? "Web Search" : lead.source === "csv" ? "CSV Import" : lead.source || "—"}</span>
                  </div>
                  <div className="info-row">
                    <span className="label">Email Status</span>
                    <span className="value">{lead.email_status || "—"}</span>
                  </div>
                  <div className="info-row">
                    <span className="label">Seniority Level</span>
                    <span className="value">{lead.seniority_level || "—"}</span>
                  </div>
                  <div className="info-row">
                    <span className="label">Department</span>
                    <span className="value">{lead.department || "—"}</span>
                  </div>
                  <div className="info-row">
                    <span className="label">Persona</span>
                    <span className="value">{lead.persona || "—"}</span>
                  </div>
                  <div className="info-row">
                    <span className="label">Buying Role</span>
                    <span className="value">{lead.buying_role || "—"}</span>
                  </div>
                </div>
              </div>

              {/* Company Details Section */}
              <div className="info-section">
                <div className="section-title-row">
                  <h3>Company Details</h3>
                  <button className="section-edit-btn" onClick={() => { setEditingSection('company'); setEditFormData({...lead}); }}>
                    ✏️ Edit
                  </button>
                </div>
                <div className="info-grid">
                  <div className="info-row">
                    <span className="label">Company Founded</span>
                    <span className="value">{lead.company_founded || "—"}</span>
                  </div>
                  <div className="info-row">
                    <span className="label">Company Headquarters</span>
                    <span className="value">{lead.company_headquarters || "—"}</span>
                  </div>
                  <div className="info-row">
                    <span className="label">Company LinkedIn Url</span>
                    <span className="value">{lead.company_linkedin_url ? <a href={lead.company_linkedin_url} target="_blank" rel="noopener noreferrer">View ↗</a> : "—"}</span>
                  </div>
                  <div className="info-row">
                    <span className="label">Company Employee Count Range</span>
                    <span className="value">{lead.company_employee_count_range || lead.company_employee_count || "—"}</span>
                  </div>
                  <div className="info-row">
                    <span className="label">Company Industry</span>
                    <span className="value">{lead.company_industry || lead.industry || "—"}</span>
                  </div>
                  <div className="info-row">
                    <span className="label">Company Size</span>
                    <span className="value">{lead.company_size || "—"}</span>
                  </div>
                  <div className="info-row">
                    <span className="label">Company Type</span>
                    <span className="value">{lead.company_type || "—"}</span>
                  </div>
                  <div className="info-row">
                    <span className="label">Company Revenue Range</span>
                    <span className="value">{lead.company_revenue_range || "—"}</span>
                  </div>
                  <div className="info-row">
                    <span className="label">Company Domain</span>
                    <span className="value">{lead.company_domain || "—"}</span>
                  </div>
                  <div className="info-row">
                    <span className="label">Company Website</span>
                    <span className="value">{lead.company_website ? <a href={lead.company_website.startsWith("http") ? lead.company_website : `https://${lead.company_website}`} target="_blank" rel="noopener noreferrer">{lead.company_website} ↗</a> : "—"}</span>
                  </div>
                </div>
              </div>

              {/* AI Classification Section */}
              <div className="info-section">
                <div className="section-title-row">
                  <h3>AI Classification</h3>
                  <button className="section-edit-btn" onClick={() => { setEditingSection('ai'); setEditFormData({...lead}); }}>
                    ✏️ Edit
                  </button>
                </div>
                <div className="info-grid">
                  <div className="info-row">
                    <span className="label">Confidence Score</span>
                    <span className="value highlight">{lead.confidence_score ? `${Math.round(lead.confidence_score * 100)}%` : "—"}</span>
                  </div>
                  <div className="info-row">
                    <span className="label">Region</span>
                    <span className="value">{lead.region || "—"}</span>
                  </div>
                  <div className="info-row">
                    <span className="label">Created At</span>
                    <span className="value">{formatDate(lead.created_at)}</span>
                  </div>
                  <div className="info-row">
                    <span className="label">Last Updated</span>
                    <span className="value">{formatDate(lead.updated_at)}</span>
                  </div>
                </div>
              </div>

              {/* Bio / Description Section */}
              {lead.snippet && (
                <div className="info-section">
                  <h3>Bio / Description</h3>
                  <p className="snippet-text">{lead.snippet}</p>
                </div>
              )}

              {/* Notes Section */}
              <div className="related-section" id="section-notes">
                <div className="section-header">
                  <h3>Notes</h3>
                  <select className="sort-select">
                    <option>Recent First ▼</option>
                  </select>
                </div>
                <div className="add-note">
                  <input type="text" placeholder="Add a note" />
                </div>
              </div>

              {/* Connected Records Section */}
              <div className="related-section" id="section-connected">
                <div className="section-header">
                  <h3>Connected Records</h3>
                </div>
                <p className="empty-state">No records found</p>
              </div>

              {/* Cadences Section */}
              <div className="related-section" id="section-cadences">
                <div className="section-header">
                  <h3>Cadences</h3>
                </div>
                <p className="empty-state">No records found</p>
              </div>

              {/* Attachments Section */}
              <div className="related-section" id="section-attachments">
                <div className="section-header">
                  <h3>Attachments</h3>
                  <button className="section-btn">Attach ▼</button>
                </div>
                <p className="empty-state">No Attachment</p>
              </div>

              {/* Open Activities Section */}
              <div className="related-section" id="section-activities">
                <div className="section-header">
                  <h3>Open Activities</h3>
                  <button className="section-btn">Add New ▼</button>
                </div>
                <p className="empty-state">No records found</p>
              </div>

              {/* Closed Activities Section */}
              <div className="related-section" id="section-closed">
                <div className="section-header">
                  <h3>Closed Activities</h3>
                </div>
                <p className="empty-state">No records found</p>
              </div>

              {/* Invited Meetings Section */}
              <div className="related-section" id="section-meetings">
                <div className="section-header">
                  <h3>Invited Meetings</h3>
                </div>
                <p className="empty-state">No records found</p>
              </div>

              {/* Emails Section */}
              <div className="related-section emails-section" id="section-emails">
                <div className="section-header">
                  <h3>Emails</h3>
                  <div className="section-header-actions">
                    <select className="filter-select">
                      <option>ALL</option>
                      <option>Sent</option>
                      <option>Received</option>
                    </select>
                  </div>
                </div>
                <div className="email-tabs">
                  <button className="email-tab active">Mails</button>
                  <button className="email-tab">Drafts</button>
                  <button className="email-tab">Scheduled</button>
                </div>
                <div className="emails-table">
                  <table>
                    <thead>
                      <tr>
                        <th></th>
                        <th>Subject</th>
                        <th>Date</th>
                        <th>Source</th>
                        <th>Sent By</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {lead.emails && lead.emails.length > 0 ? (
                        lead.emails.map((email, idx) => (
                          <tr key={idx}>
                            <td className="email-icon">
                              {email.has_attachment ? "📎" : "✉️"}
                            </td>
                            <td className="email-subject">
                              <div className="subject-line">
                                <span className="subject-text">{email.subject}</span>
                                {email.has_reply && <span className="reply-icon">↩</span>}
                              </div>
                              <div className="recipient-preview">{email.recipients || email.to}</div>
                            </td>
                            <td className="email-date">{formatDate(email.date)}</td>
                            <td className="email-source">{email.source || "IMAP"}</td>
                            <td className="email-sender">{email.sent_by || email.from}</td>
                            <td className="email-status">
                              <span className={`status-badge ${email.status?.toLowerCase()}`}>
                                {email.status || "—"}
                              </span>
                            </td>
                          </tr>
                        ))
                      ) : (
                        <tr>
                          <td colSpan="6" className="empty-state">No emails found</td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {/* Timeline Tab */}
          {activeTab === "timeline" && (
            <div className="timeline-content">
              <div className="timeline-empty">
                <p>No timeline events yet</p>
              </div>
            </div>
          )}
        </main>
      </div>

      {/* Edit Lead Modal */}
      {editingSection && (
        <div className="modal-overlay" onClick={() => setEditingSection(null)}>
          <div className="modal-container edit-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Edit {editingSection === 'lead' ? 'Lead Information' : editingSection === 'company' ? 'Company Details' : editingSection === 'ai' ? 'AI Classification' : 'Lead'}</h2>
              <button className="modal-close" onClick={() => setEditingSection(null)}>×</button>
            </div>
            <div className="modal-body">
              <div className="form-grid">
                <div className="form-group">
                  <label>First Name</label>
                  <input
                    type="text"
                    value={editFormData.first_name || ""}
                    onChange={(e) => setEditFormData({...editFormData, first_name: e.target.value})}
                  />
                </div>
                <div className="form-group">
                  <label>Last Name</label>
                  <input
                    type="text"
                    value={editFormData.last_name || ""}
                    onChange={(e) => setEditFormData({...editFormData, last_name: e.target.value})}
                  />
                </div>
                <div className="form-group">
                  <label>Email</label>
                  <input
                    type="email"
                    value={editFormData.email || ""}
                    onChange={(e) => setEditFormData({...editFormData, email: e.target.value})}
                  />
                </div>
                <div className="form-group">
                  <label>Title</label>
                  <input
                    type="text"
                    value={editFormData.title || ""}
                    onChange={(e) => setEditFormData({...editFormData, title: e.target.value})}
                  />
                </div>
                <div className="form-group">
                  <label>Company Name</label>
                  <input
                    type="text"
                    value={editFormData.company_name || ""}
                    onChange={(e) => setEditFormData({...editFormData, company_name: e.target.value})}
                  />
                </div>
                <div className="form-group">
                  <label>Location</label>
                  <input
                    type="text"
                    value={editFormData.location || ""}
                    onChange={(e) => setEditFormData({...editFormData, location: e.target.value})}
                  />
                </div>
                <div className="form-group">
                  <label>LinkedIn URL</label>
                  <input
                    type="url"
                    value={editFormData.linkedin_url || ""}
                    onChange={(e) => setEditFormData({...editFormData, linkedin_url: e.target.value})}
                  />
                </div>
                <div className="form-group">
                  <label>Department</label>
                  <input
                    type="text"
                    value={editFormData.department || ""}
                    onChange={(e) => setEditFormData({...editFormData, department: e.target.value})}
                  />
                </div>
                <div className="form-group">
                  <label>Seniority Level</label>
                  <input
                    type="text"
                    value={editFormData.seniority_level || ""}
                    onChange={(e) => setEditFormData({...editFormData, seniority_level: e.target.value})}
                  />
                </div>
                <div className="form-group">
                  <label>Email Status</label>
                  <select
                    value={editFormData.email_status || ""}
                    onChange={(e) => setEditFormData({...editFormData, email_status: e.target.value})}
                  >
                    <option value="">Select...</option>
                    <option value="valid">Valid</option>
                    <option value="invalid">Invalid</option>
                    <option value="pending">Pending</option>
                    <option value="catch-all">Catch-all</option>
                  </select>
                </div>
                <div className="form-group full-width">
                  <label>Company Website</label>
                  <input
                    type="url"
                    value={editFormData.company_website || ""}
                    onChange={(e) => setEditFormData({...editFormData, company_website: e.target.value})}
                  />
                </div>
              </div>
            </div>
            <div className="modal-footer">
              <button className="btn-secondary" onClick={() => setEditingSection(null)}>Cancel</button>
              <button className="btn-primary" onClick={handleSaveLead} disabled={saving}>
                {saving ? "Saving..." : "Save Changes"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Email Compose Modal */}
      {showEmailModal && (
        <div className="modal-overlay" onClick={() => setShowEmailModal(false)}>
          <div className="modal-container email-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header email-modal-header">
              <h2>New Message</h2>
              <div className="modal-header-actions">
                <button className="modal-minimize">−</button>
                <button className="modal-expand">□</button>
                <button className="modal-close" onClick={() => setShowEmailModal(false)}>×</button>
              </div>
            </div>
            <div className="modal-body email-modal-body">
              {/* From Account Selector */}
              <div className="email-field">
                <div className="email-field-row">
                  <div className="sender-avatar">
                    {selectedAccount?.email?.[0]?.toUpperCase() || "?"}
                  </div>
                  <select 
                    className="account-select"
                    value={selectedAccount?.email || ""}
                    onChange={handleAccountChange}
                  >
                    {imapAccounts.map((acc) => (
                      <option key={acc.email} value={acc.email}>
                        {acc.name || acc.email} &lt;{acc.email}&gt;
                      </option>
                    ))}
                  </select>
                  <button className="insert-template-btn">Insert Template</button>
                </div>
              </div>

              {/* To Field */}
              <div className="email-field">
                <label>To</label>
                <div className="email-input-row">
                  <input
                    type="text"
                    value={emailFormData.to}
                    onChange={(e) => setEmailFormData({...emailFormData, to: e.target.value})}
                    placeholder="Enter recipient email"
                  />
                  <span className="cc-bcc-toggle">Bcc Cc</span>
                </div>
              </div>

              {/* Reply To Field */}
              <div className="email-field">
                <label>Reply To</label>
                <select
                  value={emailFormData.replyTo}
                  onChange={(e) => setEmailFormData({...emailFormData, replyTo: e.target.value})}
                >
                  {imapAccounts.map((acc) => (
                    <option key={acc.email} value={acc.email}>
                      {acc.name || acc.email} &lt;{acc.email}&gt;
                    </option>
                  ))}
                </select>
              </div>

              {/* Subject Field */}
              <div className="email-field">
                <label>Subject</label>
                <input
                  type="text"
                  value={emailFormData.subject}
                  onChange={(e) => setEmailFormData({...emailFormData, subject: e.target.value})}
                  placeholder="Enter subject"
                />
              </div>

              {/* Email Toolbar */}
              <div className="email-toolbar">
                <button className="toolbar-btn"><b>B</b></button>
                <button className="toolbar-btn"><i>I</i></button>
                <button className="toolbar-btn"><u>U</u></button>
                <button className="toolbar-btn"><s>S</s></button>
                <span className="toolbar-divider">|</span>
                <button className="toolbar-btn">F</button>
                <select className="font-size-select">
                  <option>10</option>
                  <option>12</option>
                  <option>14</option>
                  <option>16</option>
                </select>
                <span className="toolbar-divider">|</span>
                <button className="toolbar-btn">A</button>
                <button className="toolbar-btn">≡</button>
                <button className="toolbar-btn">☰</button>
                <button className="toolbar-btn">⊞</button>
                <button className="toolbar-btn">🔗</button>
                <button className="toolbar-btn">📷</button>
                <span className="toolbar-right">Plain text</span>
              </div>

              {/* Email Body */}
              <div className="email-body-container">
                <textarea
                  className="email-body"
                  value={emailFormData.body}
                  onChange={(e) => setEmailFormData({...emailFormData, body: e.target.value})}
                  placeholder="Compose your email..."
                />
                
                {/* Signature Preview */}
                {signature && (
                  <div className="signature-preview" dangerouslySetInnerHTML={{ __html: signature }} />
                )}
              </div>
            </div>
            <div className="modal-footer email-modal-footer">
              <button className="attach-btn">📎</button>
              <div className="footer-right">
                <button className="schedule-btn">⏱ Schedule</button>
                <button className="send-btn" onClick={handleSendEmail} disabled={sendingEmail}>
                  {sendingEmail ? "Sending..." : "Send"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default AILeadDetail;
