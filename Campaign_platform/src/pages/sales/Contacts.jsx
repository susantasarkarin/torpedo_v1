/**
 * Contacts Page - Sales Pipeline
 * Redesigned to match AI Database styling
 */
"use client"
import { useEffect, useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
import { API_BASE_URL } from "../../config"
import { SALES_STAGES, getStageStyle as getPipelineStageStyle, getContactStages, getStageById } from "../../utils/salesPipeline"
import "../../styles/SalesPages.css"

function Contacts() {
  const navigate = useNavigate();
  const [contacts, setContacts] = useState([])
  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [search, setSearch] = useState("")
  const [currentPage, setCurrentPage] = useState(1)
  const [recordsPerPage, setRecordsPerPage] = useState(10)
  const [selectedIds, setSelectedIds] = useState([])

  // Contact stages (post-qualification)
  const contactStages = getContactStages()

  const emptyForm = {
    name: "",
    firstName: "",
    lastName: "",
    email: "",
    emailStatus: "Valid",
    title: "",
    linkedin: "",
    location: "",
    companyName: "",
    companyEmail: "",
    companyDomain: "",
    companyWebsite: "",
    companyEmployeeCount: "",
    companyEmployeeCountRange: "",
    companyFounded: "",
    companyIndustry: "",
    companyType: "",
    companyHeadquarters: "",
    companyRevenueRange: "",
    companyLinkedinUrl: "",
    companyCrunchbaseUrl: "",
    companyFundingRounds: "",
    companyLastFundingRoundAmount: "",
    companyLogoPrimary: "",
    companyLogoSecondary: "",
    stage: "discovery_call",
  }
  const [formData, setFormData] = useState(emptyForm)

  // Fetch contacts
  useEffect(() => {
    const run = async () => {
      const sessionId = localStorage.getItem("session_id");
      if (!sessionId) {
        navigate("/login");
        return;
      }

      try {
        // Fetch from /leads endpoint with lead_stage=contacts filter
        const res = await fetch(`${API_BASE_URL}/leads?lead_stage=contacts&limit=200`, {
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

        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to load contacts");
        setContacts(data.leads || []);
      } catch (e) {
        setError(e.message || "Failed to load contacts");
      }
    };
    run();
  }, [navigate]);

  // Handle form input
  const handleChange = (e) => {
    setFormData({ ...formData, [e.target.name]: e.target.value })
  }

  // Open modal for create
  const openCreate = () => {
    setEditingId(null)
    setFormData(emptyForm)
    setShowForm(true)
  }

  // Open modal for edit
  const openEdit = (contact) => {
    setEditingId(contact._id)
    setFormData({
      name: contact.name || "",
      firstName: contact.firstName || "",
      lastName: contact.lastName || "",
      email: contact.email || "",
      emailStatus: contact.emailStatus || "Valid",
      title: contact.title || "",
      linkedin: contact.linkedin || "",
      location: contact.location || "",
      companyName: contact.companyName || "",
      companyDomain: contact.companyDomain || "",
      companyWebsite: contact.companyWebsite || "",
      companyEmployeeCount: contact.companyEmployeeCount || "",
      companyEmployeeCountRange: contact.companyEmployeeCountRange || "",
      companyFounded: contact.companyFounded || "",
      companyIndustry: contact.companyIndustry || "",
      companyType: contact.companyType || "",
      companyHeadquarters: contact.companyHeadquarters || "",
      companyRevenueRange: contact.companyRevenueRange || "",
      companyLinkedinUrl: contact.companyLinkedinUrl || "",
      companyCrunchbaseUrl: contact.companyCrunchbaseUrl || "",
      companyFundingRounds: contact.companyFundingRounds || "",
      companyLastFundingRoundAmount: contact.companyLastFundingRoundAmount || "",
      companyLogoPrimary: contact.companyLogoPrimary || "",
      companyLogoSecondary: contact.companyLogoSecondary || "",
      stage: contact.stage || "discovery_call",
    })
    setShowForm(true)
  }

  // Create or Update contact
  const saveContact = async () => {
    if (!formData.email || !formData.email.trim()) {
      setError("❌ Email is required");
      return;
    }

    setLoading(true);
    setError(null);

    const sessionId = localStorage.getItem("session_id");
    if (!sessionId) {
      navigate("/login");
      return;
    }

    try {
      const payload = { ...formData };

      const url = editingId
        ? `${API_BASE_URL}/contacts/${editingId}`
        : `${API_BASE_URL}/contacts/`;
      const method = editingId ? "PUT" : "POST";

      const res = await fetch(url, {
        method,
        headers: {
          "Content-Type": "application/json",
          Authorization: sessionId,
        },
        body: JSON.stringify(payload),
      });

      if (res.status === 401) {
        alert("Session expired. Please login again.");
        localStorage.removeItem("session_id");
        navigate("/login");
        return;
      }

      const data = await res.json();

      if (!res.ok) throw new Error(data.detail || "Failed to save contact");

      if (editingId) {
        setContacts((prev) =>
          prev.map((c) => (c._id === editingId ? { ...c, ...payload } : c))
        );
      } else {
        setContacts((prev) => [...prev, data.contact]);
      }

      setShowForm(false);
      setEditingId(null);
      setFormData(emptyForm);
    } catch (e) {
      setError(e.message || "Save failed");
    } finally {
      setLoading(false);
    }
  };

  // Delete contact
  const deleteContact = async (id) => {
    if (!window.confirm("Delete this contact?")) return;

    const sessionId = localStorage.getItem("session_id");
    if (!sessionId) {
      navigate("/login");
      return;
    }

    try {
      const res = await fetch(`${API_BASE_URL}/contacts/${id}`, {
        method: "DELETE",
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

      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "Failed to delete contact");

      setContacts((prev) => prev.filter((c) => c._id !== id));
    } catch (e) {
      setError(e.message || "Delete failed");
    }
  };

  // Bulk delete contacts
  const bulkDeleteContacts = async () => {
    if (selectedIds.length === 0) return;
    if (!window.confirm(`Delete ${selectedIds.length} selected contacts?`)) return;

    const sessionId = localStorage.getItem("session_id");
    if (!sessionId) {
      navigate("/login");
      return;
    }

    try {
      const res = await fetch(`${API_BASE_URL}/contacts/bulk-delete`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: sessionId,
        },
        body: JSON.stringify({ ids: selectedIds }),
      });

      if (res.status === 401) {
        alert("Session expired. Please login again.");
        localStorage.removeItem("session_id");
        navigate("/login");
        return;
      }

      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to delete contacts");

      setContacts((prev) => prev.filter((c) => !selectedIds.includes(c._id)));
      setSelectedIds([]);
      alert(`✅ ${data.deleted_count} contacts deleted successfully!`);
    } catch (e) {
      setError(e.message || "Bulk delete failed");
    }
  };

  // Toggle selection
  const toggleSelect = (id) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  // Toggle select all (current page)
  const toggleSelectAll = () => {
    const currentPageIds = paginatedContacts.map((c) => c._id);
    const allSelected = currentPageIds.every((id) => selectedIds.includes(id));
    if (allSelected) {
      setSelectedIds((prev) => prev.filter((id) => !currentPageIds.includes(id)));
    } else {
      setSelectedIds((prev) => [...new Set([...prev, ...currentPageIds])]);
    }
  };

  const filtered = useMemo(() => {
    // Server already filters by lead_stage=contacts, just apply search filter
    const q = search.trim().toLowerCase();
    if (!q) return contacts;
    return contacts.filter((c) =>
      ["name", "firstName", "lastName", "email", "title", "companyName", "companyIndustry", "location", "stage"].some((field) =>
        String(c[field] || "").toLowerCase().includes(q)
      )
    );
  }, [contacts, search]);

  const totalPages = Math.ceil(filtered.length / recordsPerPage);
  const startIdx = (currentPage - 1) * recordsPerPage;
  const endIdx = startIdx + recordsPerPage;
  const paginatedContacts = filtered.slice(startIdx, endIdx);

  const handleSearch = (value) => {
    setSearch(value);
    setCurrentPage(1);
  };

  const handleRecordsPerPageChange = (value) => {
    setRecordsPerPage(parseInt(value));
    setCurrentPage(1);
  };

  // Get email status badge class
  const getEmailStatusClass = (status) => {
    const s = (status || "").toLowerCase();
    if (s === "valid" || s === "verified") return "valid";
    if (s === "invalid" || s === "bounced") return "invalid";
    return "unknown";
  };

  // Get stage badge style
  const getStageBadgeStyle = (stageId) => {
    const stageStyle = getPipelineStageStyle(stageId);
    return {
      backgroundColor: stageStyle?.bg || stageStyle?.backgroundColor || "#f3f4f6",
      color: stageStyle?.color || "#374151",
    };
  };

  return (
    <div className="sales-page">
      {/* Page Header */}
      <div className="page-header">
        <div className="header-left">
          <h1>Contacts</h1>
          <p className="subtitle">Manage qualified leads through the sales pipeline stages</p>
        </div>
        <div className="header-actions">
          {selectedIds.length > 0 && (
            <button className="btn btn-danger" onClick={bulkDeleteContacts}>
              🗑️ Delete ({selectedIds.length})
            </button>
          )}
          {contacts.length > 0 && contacts.some(c => !c.name && !c.firstName && !c.companyName) && (
            <button 
              className="btn btn-danger"
              onClick={() => {
                if (window.confirm('⚠️ Clear all old contacts that are missing the new fields? This cannot be undone!')) {
                  const oldContacts = contacts.filter(c => !c.name && !c.firstName && !c.companyName);
                  oldContacts.forEach(c => deleteContact(c._id));
                }
              }}
            >
              🗑️ Clear Old ({contacts.filter(c => !c.name && !c.firstName && !c.companyName).length})
            </button>
          )}
          <button className="btn btn-primary" onClick={openCreate}>
            + Add New Contact
          </button>
        </div>
      </div>

      {error && <div className="error-alert">{error}</div>}

      {/* Stats Row */}
      <div className="stats-row">
        <div className="stat-card primary">
          <div className="stat-value">{contacts.length}</div>
          <div className="stat-label">Total Contacts</div>
        </div>
        {contactStages.map(stage => (
          <div key={stage.id} className="stat-card">
            <div className="stat-value">{contacts.filter(c => c.stage === stage.id).length}</div>
            <div className="stat-label">{stage.icon} {stage.label}</div>
          </div>
        ))}
      </div>

      {/* Filters Bar */}
      <div className="filters-bar">
        <input
          className="search-input"
          type="text"
          placeholder="Search contacts by name, email, company..."
          value={search}
          onChange={e => handleSearch(e.target.value)}
        />
        <select
          className="records-select"
          value={recordsPerPage}
          onChange={e => handleRecordsPerPageChange(e.target.value)}
        >
          <option value={10}>10 per page</option>
          <option value={20}>20 per page</option>
          <option value={50}>50 per page</option>
          <option value={100}>100 per page</option>
          <option value={200}>200 per page</option>
        </select>
      </div>

      {/* Contacts Table */}
      <div className="table-container">
        <table className="data-table">
          <thead>
            <tr>
              <th className="checkbox-col">
                <input 
                  type="checkbox" 
                  checked={paginatedContacts.length > 0 && paginatedContacts.every(c => selectedIds.includes(c._id))}
                  onChange={toggleSelectAll}
                />
              </th>
              <th>Name</th>
              <th>Email</th>
              <th>Title</th>
              <th>Company</th>
              <th>Industry</th>
              <th>Stage</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {paginatedContacts.map(contact => {
              const stageInfo = getStageById(contact.stage);
              return (
                <tr 
                  key={contact._id} 
                  className={selectedIds.includes(contact._id) ? "selected" : ""}
                >
                  <td className="checkbox-col" onClick={(e) => e.stopPropagation()}>
                    <input 
                      type="checkbox" 
                      checked={selectedIds.includes(contact._id)}
                      onChange={() => toggleSelect(contact._id)}
                    />
                  </td>
                  <td className="name-cell">
                    <span 
                      className="name-link"
                      onClick={() => navigate(`/admin/sales/contacts/${contact._id}`)}
                    >
                      {contact.name || `${contact.firstName || ''} ${contact.lastName || ''}`.trim() || '-'}
                    </span>
                  </td>
                  <td>
                    <div>
                      {contact.email}
                      {contact.emailStatus && (
                        <span className={`status-badge ${getEmailStatusClass(contact.emailStatus)}`} style={{ marginLeft: '8px' }}>
                          {contact.emailStatus}
                        </span>
                      )}
                    </div>
                  </td>
                  <td>{contact.title || '-'}</td>
                  <td>{contact.companyName || '-'}</td>
                  <td>{contact.companyIndustry || '-'}</td>
                  <td>
                    <span className="stage-badge" style={getStageBadgeStyle(contact.stage)}>
                      {stageInfo?.icon} {stageInfo?.label || contact.stage || 'Discovery Call'}
                    </span>
                  </td>
                  <td>
                    <div className="actions-cell">
                      {contact.linkedin && (
                        <a 
                          href={contact.linkedin}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="action-btn-linkedin"
                          onClick={(e) => e.stopPropagation()}
                        >
                          in
                        </a>
                      )}
                      <button 
                        className="action-btn edit"
                        onClick={(e) => { e.stopPropagation(); openEdit(contact); }}
                      >
                        ✏️
                      </button>
                      <button 
                        className="action-btn delete"
                        onClick={(e) => { e.stopPropagation(); deleteContact(contact._id); }}
                      >
                        🗑️
                      </button>
                    </div>
                  </td>
                </tr>
              )
            })}
            {paginatedContacts.length === 0 && (
              <tr>
                <td colSpan={8} className="empty-state">
                  <h3>No contacts found</h3>
                  <p>Move leads from the Leads page to get started!</p>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

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
            onClick={() => setCurrentPage(Math.min(totalPages, currentPage + 1))}
            disabled={currentPage === totalPages}
          >
            Next →
          </button>
        </div>
      )}

      {/* Add/Edit Modal */}
      {showForm && (
        <div className="modal-overlay" onClick={(e) => {
          if (e.target === e.currentTarget) setShowForm(false)
        }}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>{editingId ? "Edit Contact" : "Add New Contact"}</h3>
              <button className="modal-close-btn" onClick={() => setShowForm(false)}>×</button>
            </div>

            <div className="modal-body">
              <h4 className="section-title">Personal Information</h4>
              
              <div className="form-group">
                <label className="form-label">Full Name</label>
                <input
                  className="form-input"
                  name="name"
                  placeholder="Enter full name"
                  value={formData.name}
                  onChange={handleChange}
                />
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label className="form-label">First Name</label>
                  <input
                    className="form-input"
                    name="firstName"
                    placeholder="Enter first name"
                    value={formData.firstName}
                    onChange={handleChange}
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">Last Name</label>
                  <input
                    className="form-input"
                    name="lastName"
                    placeholder="Enter last name"
                    value={formData.lastName}
                    onChange={handleChange}
                  />
                </div>
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label className="form-label">Email <span className="required">*</span></label>
                  <input
                    className="form-input"
                    name="email"
                    type="email"
                    placeholder="Enter email address"
                    value={formData.email}
                    onChange={handleChange}
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">Email Status</label>
                  <select
                    className="form-select"
                    name="emailStatus"
                    value={formData.emailStatus}
                    onChange={handleChange}
                  >
                    <option>Valid</option>
                    <option>Invalid</option>
                    <option>Unknown</option>
                  </select>
                </div>
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label className="form-label">Title</label>
                  <input
                    className="form-input"
                    name="title"
                    placeholder="Enter job title"
                    value={formData.title}
                    onChange={handleChange}
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">Location</label>
                  <input
                    className="form-input"
                    name="location"
                    placeholder="Enter location"
                    value={formData.location}
                    onChange={handleChange}
                  />
                </div>
              </div>

              <div className="form-group">
                <label className="form-label">LinkedIn Profile</label>
                <input
                  className="form-input"
                  name="linkedin"
                  placeholder="Enter LinkedIn URL"
                  value={formData.linkedin}
                  onChange={handleChange}
                />
              </div>

              <h4 className="section-title">Pipeline Stage</h4>

              <div className="form-group">
                <label className="form-label">Stage</label>
                <select
                  className="form-select"
                  name="stage"
                  value={formData.stage}
                  onChange={handleChange}
                >
                  {contactStages.map(stage => (
                    <option key={stage.id} value={stage.id}>{stage.icon} {stage.label}</option>
                  ))}
                </select>
              </div>

              <h4 className="section-title">Company Information</h4>

              <div className="form-group">
                <label className="form-label">Company Name</label>
                <input
                  className="form-input"
                  name="companyName"
                  placeholder="Enter company name"
                  value={formData.companyName}
                  onChange={handleChange}
                />
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label className="form-label">Company Domain</label>
                  <input
                    className="form-input"
                    name="companyDomain"
                    placeholder="e.g., example.com"
                    value={formData.companyDomain}
                    onChange={handleChange}
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">Company Website</label>
                  <input
                    className="form-input"
                    name="companyWebsite"
                    placeholder="Enter website URL"
                    value={formData.companyWebsite}
                    onChange={handleChange}
                  />
                </div>
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label className="form-label">Employee Count</label>
                  <input
                    className="form-input"
                    name="companyEmployeeCount"
                    placeholder="Enter employee count"
                    value={formData.companyEmployeeCount}
                    onChange={handleChange}
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">Industry</label>
                  <input
                    className="form-input"
                    name="companyIndustry"
                    placeholder="Enter industry"
                    value={formData.companyIndustry}
                    onChange={handleChange}
                  />
                </div>
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label className="form-label">Company Type</label>
                  <input
                    className="form-input"
                    name="companyType"
                    placeholder="e.g., Private, Public"
                    value={formData.companyType}
                    onChange={handleChange}
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">Headquarters</label>
                  <input
                    className="form-input"
                    name="companyHeadquarters"
                    placeholder="Enter headquarters location"
                    value={formData.companyHeadquarters}
                    onChange={handleChange}
                  />
                </div>
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label className="form-label">Revenue Range</label>
                  <input
                    className="form-input"
                    name="companyRevenueRange"
                    placeholder="e.g., $10M - $50M"
                    value={formData.companyRevenueRange}
                    onChange={handleChange}
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">Company LinkedIn URL</label>
                  <input
                    className="form-input"
                    name="companyLinkedinUrl"
                    placeholder="Enter company LinkedIn URL"
                    value={formData.companyLinkedinUrl}
                    onChange={handleChange}
                  />
                </div>
              </div>
            </div>

            <div className="modal-footer">
              <button className="btn btn-outline" onClick={() => setShowForm(false)}>Cancel</button>
              <button className="btn btn-primary" onClick={saveContact} disabled={loading}>
                {loading ? "Saving..." : (editingId ? "Update Contact" : "Add Contact")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default Contacts
