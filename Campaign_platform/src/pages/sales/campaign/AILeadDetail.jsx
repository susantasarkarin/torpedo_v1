/**
 * AI Lead Detail Page - Zoho CRM Style
 * Path: /admin/sales/campaign/ai-leads/:leadId
 */

import React, { useState, useEffect, useRef } from "react";
import { useNavigate, useParams } from "react-router-dom";
import DOMPurify from "dompurify";
import { API_BASE_URL } from "../../../config";
import "./AILeadDetail.css";
import { buildApiUrl } from "../../../config"

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
  
  // Convert Modal State
  const [showConvertModal, setShowConvertModal] = useState(false);
  const [convertingStage, setConvertingStage] = useState(false);
  
  // Lead Stage Options
  const LEAD_STAGE_OPTIONS = [
    { value: "ai_database", label: "AI Database", icon: "🤖", color: "#6366f1" },
    { value: "leads", label: "Leads", icon: "🎯", color: "#10b981" },
    { value: "contacts", label: "Contacts", icon: "👥", color: "#f59e0b" }
  ];
  
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
  
  // Rich text editor ref
  const emailBodyRef = useRef(null);
  
  // Rich text editor commands
  const execEmailCommand = (command, value = null) => {
    document.execCommand(command, false, value);
    emailBodyRef.current?.focus();
  };
  
  const insertEmailLink = () => {
    const url = prompt("Enter URL:");
    if (url) execEmailCommand("createLink", url);
  };
  
  const insertEmailImage = () => {
    const url = prompt("Enter image URL:");
    if (url) execEmailCommand("insertImage", url);
  };

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
      const res = await fetch(buildApiUrl(`/leads/enriched/${leadId}`), {
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
      const res = await fetch(buildApiUrl(`/api/v1/email-sync/accounts`), {
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
      const res = await fetch(buildApiUrl(`/settings/email-signature/${encodeURIComponent(email)}`), {
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
      const res = await fetch(buildApiUrl(`/leads/enriched/${leadId}`), {
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

  const handleConvertStage = async (newStage) => {
    const sessionId = localStorage.getItem("session_id");
    if (!sessionId) return;

    setConvertingStage(true);
    try {
      const res = await fetch(buildApiUrl(`/leads/enriched/${leadId}`), {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          Authorization: sessionId,
        },
        body: JSON.stringify({ lead_stage: newStage }),
      });

      // Check content type before parsing
      const contentType = res.headers.get("content-type");
      if (!contentType || !contentType.includes("application/json")) {
        const text = await res.text();
        throw new Error(`Server error: ${res.status} ${res.statusText}`);
      }

      if (res.ok) {
        const data = await res.json();
        setLead({ ...lead, lead_stage: newStage });
        setShowConvertModal(false);
        const stageLabel = LEAD_STAGE_OPTIONS.find(s => s.value === newStage)?.label || newStage;
        alert(`Lead moved to ${stageLabel} successfully!`);
      } else {
        const errData = await res.json();
        alert(errData.detail || "Failed to convert lead");
      }
    } catch (e) {
      alert("Failed to convert lead: " + e.message);
    } finally {
      setConvertingStage(false);
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

      const res = await fetch(buildApiUrl(`/api/v1/email-sync/send`), {
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
          <button className="action-btn secondary" onClick={() => setShowConvertModal(true)}>Convert</button>
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

              {/* Human Intervention Banner — shown when all bounce recovery attempts are exhausted */}
              {lead.bounce_recovery_status === "needs_human_intervention" && (
                <div className="human-intervention-banner">
                  <span className="intervention-icon">⚠️</span>
                  <div className="intervention-body">
                    <strong>Email Bounce — Human Review Required</strong>
                    <p>All automated recovery attempts were exhausted for this lead. Please manually verify or update the email address.</p>
                    {lead.bounce_recovery_emails_tried?.length > 0 && (
                      <details className="tried-emails">
                        <summary>Emails attempted ({lead.bounce_recovery_emails_tried.length})</summary>
                        <ul>
                          {lead.bounce_recovery_emails_tried.map((e, i) => (
                            <li key={i}><code>{e}</code></li>
                          ))}
                        </ul>
                      </details>
                    )}
                  </div>
                  <button
                    className="section-edit-btn intervention-edit-btn"
                    onClick={() => { setEditingSection('lead'); setEditFormData({...lead}); }}
                  >
                    ✏️ Update Email
                  </button>
                </div>
              )}

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
                    <span className="label">Lead Stage</span>
                    <span className="value">
                      <span className={`stage-badge ${lead.lead_stage || 'ai_database'}`}>
                        {LEAD_STAGE_OPTIONS.find(s => s.value === (lead.lead_stage || 'ai_database'))?.icon}{' '}
                        {LEAD_STAGE_OPTIONS.find(s => s.value === (lead.lead_stage || 'ai_database'))?.label || 'AI Database'}
                      </span>
                    </span>
                  </div>
                  <div className="info-row">
                    <span className="label">Email</span>
                    <span className="value link">{lead.email || "—"}</span>
                  </div>
                  <div className="info-row">
                    <span className="label">Lead Name</span>
                    <span className="value">{[lead.first_name, lead.last_name].filter(Boolean).join(" ") || lead.name || "—"}</span>
                  </div>
                  <div className="info-row">
                    <span className="label">LinkedIn</span>
                    <span className="value">{lead.linkedin_url ? <a href={lead.linkedin_url} target="_blank" rel="noopener noreferrer" className="url-link">{lead.linkedin_url} ↗</a> : "—"}</span>
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
                  {lead.company_founded && <div className="info-row"><span className="label">Company Founded</span><span className="value">{lead.company_founded}</span></div>}
                  {lead.company_headquarters && <div className="info-row"><span className="label">Company Headquarters</span><span className="value">{lead.company_headquarters}</span></div>}
                  {lead.company_linkedin_url && <div className="info-row"><span className="label">Company LinkedIn</span><span className="value"><a href={lead.company_linkedin_url} target="_blank" rel="noopener noreferrer" className="url-link">{lead.company_linkedin_url} ↗</a></span></div>}
                  {(lead.company_employee_count_range || lead.company_employee_count) && <div className="info-row"><span className="label">Employee Count</span><span className="value">{lead.company_employee_count_range || lead.company_employee_count}</span></div>}
                  {(lead.company_industry || lead.industry) && <div className="info-row"><span className="label">Industry</span><span className="value">{lead.company_industry || lead.industry}</span></div>}
                  {lead.company_size && <div className="info-row"><span className="label">Company Size</span><span className="value">{lead.company_size}</span></div>}
                  {lead.company_type && <div className="info-row"><span className="label">Company Type</span><span className="value">{lead.company_type}</span></div>}
                  {lead.company_revenue_range && <div className="info-row"><span className="label">Revenue Range</span><span className="value">{lead.company_revenue_range}</span></div>}
                  {lead.company_domain && <div className="info-row"><span className="label">Company Domain</span><span className="value">{lead.company_domain}</span></div>}
                  {lead.company_website && <div className="info-row"><span className="label">Company Website</span><span className="value"><a href={lead.company_website.startsWith("http") ? lead.company_website : `https://${lead.company_website}`} target="_blank" rel="noopener noreferrer">{lead.company_website} ↗</a></span></div>}
                  {lead.company_name && !lead.company_domain && !lead.company_website && <div className="info-row"><span className="label">Company</span><span className="value">{lead.company_name}</span></div>}
                  {!lead.company_founded && !lead.company_headquarters && !lead.company_linkedin_url && !lead.company_employee_count_range && !lead.company_employee_count && !lead.company_industry && !lead.industry && !lead.company_size && !lead.company_type && !lead.company_revenue_range && !lead.company_domain && !lead.company_website && (
                    <div className="info-row empty-notice"><span className="value" style={{color:"#aaa",fontStyle:"italic"}}>No company details available</span></div>
                  )}
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
                  {lead.icp_segment && lead.icp_segment !== 'unknown' && <div className="info-row"><span className="label">ICP Segment</span><span className="value highlight">{lead.icp_segment}</span></div>}
                  {lead.classification_basket && <div className="info-row"><span className="label">ICP Basket</span><span className="value highlight">{lead.classification_basket} — {lead.classification_basket_name || ''}</span></div>}
                  {lead.fit_tier_label && <div className="info-row"><span className="label">Fit Tier</span><span className="value">{lead.fit_tier_label}</span></div>}
                  {lead.persona_label && <div className="info-row"><span className="label">Persona</span><span className="value">{lead.persona_label}</span></div>}
                  {lead.confidence_score > 0 && <div className="info-row"><span className="label">Confidence Score</span><span className="value highlight">{Math.round(lead.confidence_score * 100)}%</span></div>}
                  {lead.region && <div className="info-row"><span className="label">Region</span><span className="value">{lead.region}</span></div>}
                  {lead.icp_tags?.length > 0 && <div className="info-row"><span className="label">ICP Tags</span><span className="value">{lead.icp_tags.join(", ")}</span></div>}
                  {lead.created_at && <div className="info-row"><span className="label">Created At</span><span className="value">{formatDate(lead.created_at)}</span></div>}
                  {lead.updated_at && <div className="info-row"><span className="label">Last Updated</span><span className="value">{formatDate(lead.updated_at)}</span></div>}
                  {lead.classified_at && <div className="info-row"><span className="label">Classified At</span><span className="value">{formatDate(lead.classified_at)}</span></div>}
                </div>
              </div>

              {/* Bio / Description Section */}
              {lead.snippet && (
                <div className="info-section">
                  <h3>Bio / Description</h3>
                  <p className="snippet-text">{lead.snippet}</p>
                </div>
              )}

              {/* Notes Section - AI Summary (Email Conversation Summary) */}
              <div className="related-section" id="section-notes">
                <div className="section-header">
                  <h3>Notes</h3>
                  <select className="sort-select">
                    <option>Recent First ▼</option>
                  </select>
                </div>
                <div className="notes-content">
                  {lead.conversation_summary ? (
                    <div className="ai-summary-note">
                      <div className="note-header">
                        <span className="note-icon">🤖</span>
                        <span className="note-title">AI Summary</span>
                        <span className="note-date">{formatDate(lead.summary_updated_at || lead.updated_at)}</span>
                      </div>
                      <div className="note-body">
                        {lead.conversation_summary}
                      </div>
                    </div>
                  ) : (
                    <p className="empty-state">No email conversation summary available</p>
                  )}
                </div>
              </div>

              {/* Connected Records Section */}
              <div className="related-section" id="section-connected">
                <div className="section-header">
                  <h3>Connected Records</h3>
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
              {lead.timeline && lead.timeline.length > 0 ? (
                <div className="timeline-list">
                  {lead.timeline.map((event, idx) => (
                    <div key={idx} className={`timeline-item ${event.type}`}>
                      <div className="timeline-icon">{event.icon}</div>
                      <div className="timeline-connector"></div>
                      <div className="timeline-details">
                        <div className="timeline-header">
                          <span className="timeline-title">{event.title}</span>
                          <span className="timeline-date">{formatDate(event.date)}</span>
                        </div>
                        <div className="timeline-description">
                          {event.subject && <strong>{event.subject}</strong>}
                          <p>{event.description}</p>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="timeline-empty">
                  <p>No timeline events yet</p>
                </div>
              )}
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

      {/* Email Compose Modal - Gmail Style */}
      {showEmailModal && (
        <div className="gmail-compose-overlay">
          <div className="gmail-compose-modal" onClick={(e) => e.stopPropagation()}>
            {/* Tabs Bar */}
            <div className="compose-tabs-bar">
              <div className="compose-tab active">
                <span className="tab-label">New Message</span>
                <button className="tab-close" onClick={() => setShowEmailModal(false)}>×</button>
              </div>
            </div>
            
            {/* Header */}
            <div className="compose-header">
              <div className="compose-header-left">
                <div className="sender-info">
                  <img 
                    src={selectedAccount?.avatar || `https://ui-avatars.com/api/?name=${encodeURIComponent(selectedAccount?.name || 'User')}&background=4a90d9&color=fff`} 
                    alt="" 
                    className="sender-avatar-img"
                  />
                  <select 
                    className="sender-select"
                    value={selectedAccount?.email || ""}
                    onChange={handleAccountChange}
                  >
                    {imapAccounts.map((acc) => (
                      <option key={acc.email} value={acc.email}>
                        {acc.name || acc.email} &lt;{acc.email}&gt;
                      </option>
                    ))}
                  </select>
                </div>
              </div>
              <div className="compose-header-right">
                <button className="template-btn">
                  Insert Template
                  <span className="dropdown-arrow">▼</span>
                </button>
              </div>
              <div className="compose-window-controls">
                <button className="window-btn minimize">−</button>
                <button className="window-btn expand">⬜</button>
                <button className="window-btn close" onClick={() => setShowEmailModal(false)}>×</button>
              </div>
            </div>
            
            {/* Reply To */}
            <div className="compose-field reply-to-field">
              <span className="field-label">Reply To</span>
              <span className="field-value">{selectedAccount?.name || selectedAccount?.email} &lt;{selectedAccount?.email}&gt;</span>
            </div>
            
            {/* To Field */}
            <div className="compose-field to-field">
              <span className="field-label">To</span>
              <div className="recipients-container">
                {emailFormData.to && (
                  <span className="recipient-chip">
                    {emailFormData.to.split('@')[0]}
                    <button className="chip-remove">×</button>
                  </span>
                )}
                <input
                  type="text"
                  className="recipient-input"
                  value={emailFormData.to ? "" : emailFormData.to}
                  onChange={(e) => setEmailFormData({...emailFormData, to: e.target.value})}
                  placeholder=""
                />
              </div>
            </div>
            
            {/* Subject */}
            <div className="compose-field subject-field">
              <span className="field-label">Subject</span>
              <input
                type="text"
                className="subject-input"
                value={emailFormData.subject}
                onChange={(e) => setEmailFormData({...emailFormData, subject: e.target.value})}
                placeholder=""
              />
            </div>
            
            {/* Rich Text Toolbar */}
            <div className="compose-toolbar">
              <button type="button" className="toolbar-btn bold" onClick={() => execEmailCommand("bold")} title="Bold"><b>B</b></button>
              <button type="button" className="toolbar-btn italic" onClick={() => execEmailCommand("italic")} title="Italic"><i>I</i></button>
              <button type="button" className="toolbar-btn underline" onClick={() => execEmailCommand("underline")} title="Underline"><u>U</u></button>
              <button type="button" className="toolbar-btn strikethrough" onClick={() => execEmailCommand("strikeThrough")} title="Strikethrough"><s>S</s></button>
              <select className="toolbar-select font-family" onChange={(e) => execEmailCommand("fontName", e.target.value)}>
                <option value="Arial">Arial</option>
                <option value="Times New Roman">Times New Roman</option>
                <option value="Georgia">Georgia</option>
                <option value="Verdana">Verdana</option>
              </select>
              <select className="toolbar-select font-size" onChange={(e) => execEmailCommand("fontSize", e.target.value)} defaultValue="3">
                <option value="1">10</option>
                <option value="2">11</option>
                <option value="3">12</option>
                <option value="4">14</option>
                <option value="5">18</option>
                <option value="6">24</option>
              </select>
              <span className="toolbar-separator"></span>
              <input type="color" className="toolbar-color" title="Text Color" onChange={(e) => execEmailCommand("foreColor", e.target.value)} />
              <button type="button" className="toolbar-btn align" onClick={() => execEmailCommand("justifyLeft")} title="Align">≡ ▼</button>
              <button type="button" className="toolbar-btn list-ordered" onClick={() => execEmailCommand("insertOrderedList")} title="Numbered List">1.</button>
              <button type="button" className="toolbar-btn list-bullet" onClick={() => execEmailCommand("insertUnorderedList")} title="Bullet List">•</button>
              <button type="button" className="toolbar-btn indent-less" onClick={() => execEmailCommand("outdent")} title="Decrease Indent">⇤</button>
              <button type="button" className="toolbar-btn indent-more" onClick={() => execEmailCommand("indent")} title="Increase Indent">⇥</button>
              <span className="toolbar-separator"></span>
              <button type="button" className="toolbar-btn superscript" onClick={() => execEmailCommand("superscript")} title="Superscript">x²</button>
              <button type="button" className="toolbar-btn subscript" onClick={() => execEmailCommand("subscript")} title="Subscript">x₂</button>
              <button type="button" className="toolbar-btn clear-format" onClick={() => execEmailCommand("removeFormat")} title="Clear Formatting">Tx</button>
              <span className="toolbar-separator"></span>
              <button type="button" className="toolbar-btn link" onClick={insertEmailLink} title="Insert Link">🔗</button>
              <button type="button" className="toolbar-btn table" onClick={() => {}} title="Insert Table">▦</button>
              <button type="button" className="toolbar-btn image" onClick={insertEmailImage} title="Insert Image">🖼</button>
              <button type="button" className="toolbar-btn hr" onClick={() => execEmailCommand("insertHorizontalRule")} title="Horizontal Line">―</button>
              <button type="button" className="toolbar-btn code" onClick={() => execEmailCommand("formatBlock", "pre")} title="Code Block">&lt;/&gt;</button>
              <button type="button" className="toolbar-btn quote" onClick={() => execEmailCommand("formatBlock", "blockquote")} title="Quote">"</button>
              <button type="button" className="toolbar-btn emoji" title="Insert Emoji">😊 ▼</button>
              <span className="toolbar-spacer"></span>
              <span className="plain-text-toggle">Plain text</span>
            </div>
            
            {/* Email Body */}
            <div className="compose-body">
              <div
                ref={emailBodyRef}
                className="compose-editor"
                contentEditable
                onInput={(e) => setEmailFormData({...emailFormData, body: e.currentTarget.innerHTML})}
                dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(emailFormData.body) }}
              />
              
              {/* Signature */}
              {signature && (
                <div className="compose-signature" dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(signature) }} />
              )}
            </div>
            
            {/* Footer */}
            <div className="compose-footer">
              <div className="footer-left">
                <button className="footer-btn attach" title="Attach file">📎</button>
                <button className="footer-btn link" title="Insert link">🔗</button>
              </div>
              <div className="footer-right">
                <button className="footer-btn ai" title="AI Assistant">✨</button>
                <button className="schedule-btn" title="Schedule send">
                  <span className="schedule-icon">⏱</span>
                  Schedule
                </button>
                <button className="send-btn-gmail" onClick={handleSendEmail} disabled={sendingEmail}>
                  {sendingEmail ? "Sending..." : "Send"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Convert Stage Modal */}
      {showConvertModal && (
        <div className="modal-overlay" onClick={() => setShowConvertModal(false)}>
          <div className="modal-container convert-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Move Lead to Stage</h2>
              <button className="modal-close" onClick={() => setShowConvertModal(false)}>×</button>
            </div>
            <div className="modal-body">
              <p className="convert-description">
                Select the stage to move <strong>{lead.name || lead.email}</strong> to:
              </p>
              <div className="stage-options">
                {LEAD_STAGE_OPTIONS.map((stage) => (
                  <button
                    key={stage.value}
                    className={`stage-option-btn ${lead.lead_stage === stage.value || (!lead.lead_stage && stage.value === 'ai_database') ? 'current' : ''}`}
                    onClick={() => handleConvertStage(stage.value)}
                    disabled={convertingStage || lead.lead_stage === stage.value || (!lead.lead_stage && stage.value === 'ai_database')}
                  >
                    <span className="stage-icon">{stage.icon}</span>
                    <span className="stage-label">{stage.label}</span>
                    {(lead.lead_stage === stage.value || (!lead.lead_stage && stage.value === 'ai_database')) && (
                      <span className="current-badge">Current</span>
                    )}
                  </button>
                ))}
              </div>
            </div>
            <div className="modal-footer">
              <button className="btn-secondary" onClick={() => setShowConvertModal(false)}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default AILeadDetail;
