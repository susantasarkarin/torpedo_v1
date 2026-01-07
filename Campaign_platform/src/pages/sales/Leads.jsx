/**
 * Leads Page - Sales Pipeline
 * Redesigned to match AI Database styling
 */
"use client"
import { useEffect, useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
import { API_BASE_URL } from "../../config"
import { getLeadStages, getStageById, getStageStyle as getPipelineStageStyle } from "../../utils/salesPipeline"
import "../../styles/SalesPages.css"

function Leads() {
  const navigate = useNavigate();
  const [leads, setLeads] = useState([])
  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [search, setSearch] = useState("")
  const [currentPage, setCurrentPage] = useState(1)
  const [recordsPerPage, setRecordsPerPage] = useState(10)
  const [selectedIds, setSelectedIds] = useState([])

  // Lead stages (pre-qualification)
  const leadStages = getLeadStages()

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
    stage: "lead_generation",
  }
  const [formData, setFormData] = useState(emptyForm)

  // Fetch leads
  useEffect(() => {
    const run = async () => {
      const sessionId = localStorage.getItem("session_id");
      if (!sessionId) {
        navigate("/login");
        return;
      }

      try {
        // Fetch from /leads endpoint with lead_stage=leads filter
        const res = await fetch(`${API_BASE_URL}/leads?lead_stage=leads&limit=200`, {
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
        if (!res.ok) throw new Error(data.detail || "Failed to load leads");
        setLeads(data.leads || []);
      } catch (e) {
        setError(e.message || "Failed to load leads");
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
  const openEdit = (lead) => {
    setEditingId(lead._id)
    setFormData({
      name: lead.name || "",
      firstName: lead.firstName || lead.first_name || "",
      lastName: lead.lastName || lead.last_name || "",
      email: lead.email || "",
      emailStatus: lead.emailStatus || lead.email_status || "Valid",
      title: lead.title || "",
      linkedin: lead.linkedin || lead.linkedin_url || "",
      location: lead.location || "",
      companyName: lead.companyName || lead.company_name || "",
      companyDomain: lead.companyDomain || lead.company_domain || "",
      companyWebsite: lead.companyWebsite || lead.company_website || "",
      companyEmployeeCount: lead.companyEmployeeCount || lead.company_employee_count || "",
      companyEmployeeCountRange: lead.companyEmployeeCountRange || lead.company_employee_count_range || "",
      companyFounded: lead.companyFounded || lead.company_founded || "",
      companyIndustry: lead.companyIndustry || lead.company_industry || "",
      companyType: lead.companyType || lead.company_type || "",
      companyHeadquarters: lead.companyHeadquarters || lead.company_headquarters || "",
      companyRevenueRange: lead.companyRevenueRange || lead.company_revenue_range || "",
      companyLinkedinUrl: lead.companyLinkedinUrl || lead.company_linkedin_url || "",
      companyCrunchbaseUrl: lead.companyCrunchbaseUrl || lead.company_crunchbase_url || "",
      companyFundingRounds: lead.companyFundingRounds || lead.company_funding_rounds || "",
      companyLastFundingRoundAmount: lead.companyLastFundingRoundAmount || lead.company_last_funding_round_amount || "",
      companyLogoPrimary: lead.companyLogoPrimary || lead.company_logo_primary || "",
      companyLogoSecondary: lead.companyLogoSecondary || lead.company_logo_secondary || "",
      stage: lead.stage || "lead_generation",
    })
    setShowForm(true)
  }

  // Create or Update lead
  const saveLead = async () => {
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
        ? `${API_BASE_URL}/leads/${editingId}`
        : `${API_BASE_URL}/leads/`;
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

      if (!res.ok) throw new Error(data.detail || "Failed to save lead");

      if (editingId) {
        setLeads((prev) =>
          prev.map((l) => (l._id === editingId ? { ...l, ...payload } : l))
        );
      } else {
        setLeads((prev) => [...prev, data.lead]);
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

  // Delete lead
  const deleteLead = async (id) => {
    if (!window.confirm("Delete this lead?")) return;

    const sessionId = localStorage.getItem("session_id");
    if (!sessionId) {
      navigate("/login");
      return;
    }

    try {
      const res = await fetch(`${API_BASE_URL}/leads/${id}`, {
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
      if (!res.ok) throw new Error(data.detail || "Failed to delete lead");

      setLeads((prev) => prev.filter((l) => l._id !== id));
    } catch (e) {
      setError(e.message || "Delete failed");
    }
  };

  // Move lead to contacts
  const moveToContacts = async (id) => {
    if (!window.confirm("Move this lead to Contacts (Discovery Call stage)?")) return;

    const sessionId = localStorage.getItem("session_id");
    if (!sessionId) {
      navigate("/login");
      return;
    }

    try {
      const res = await fetch(`${API_BASE_URL}/leads/${id}/move-to-contacts`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: sessionId,
        },
        body: JSON.stringify({ stage: "discovery_call" }),
      });

      if (res.status === 401) {
        alert("Session expired. Please login again.");
        localStorage.removeItem("session_id");
        navigate("/login");
        return;
      }

      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to move lead");

      setLeads((prev) => prev.filter((l) => l._id !== id));
      alert("✅ Lead moved to Contacts successfully!");
    } catch (e) {
      setError(e.message || "Move failed");
    }
  };

  // Bulk delete leads
  const bulkDeleteLeads = async () => {
    if (selectedIds.length === 0) return;
    if (!window.confirm(`Delete ${selectedIds.length} selected leads?`)) return;

    const sessionId = localStorage.getItem("session_id");
    if (!sessionId) {
      navigate("/login");
      return;
    }

    try {
      const res = await fetch(`${API_BASE_URL}/leads/bulk-delete`, {
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
      if (!res.ok) throw new Error(data.detail || "Failed to delete leads");

      setLeads((prev) => prev.filter((l) => !selectedIds.includes(l._id)));
      setSelectedIds([]);
      alert(`✅ ${data.deleted_count} leads deleted successfully!`);
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
    const currentPageIds = paginatedLeads.map((l) => l._id);
    const allSelected = currentPageIds.every((id) => selectedIds.includes(id));
    if (allSelected) {
      setSelectedIds((prev) => prev.filter((id) => !currentPageIds.includes(id)));
    } else {
      setSelectedIds((prev) => [...new Set([...prev, ...currentPageIds])]);
    }
  };

  const filtered = useMemo(() => {
    // Server already filters by lead_stage=leads, just apply search filter
    const q = search.trim().toLowerCase();
    if (!q) return leads;
    return leads.filter((l) =>
      ["name", "firstName", "lastName", "email", "title", "companyName", "company_name", "companyIndustry", "company_industry", "location"].some((field) =>
        String(l[field] || "").toLowerCase().includes(q)
      )
    );
  }, [leads, search]);

  const totalPages = Math.ceil(filtered.length / recordsPerPage);
  const startIdx = (currentPage - 1) * recordsPerPage;
  const endIdx = startIdx + recordsPerPage;
  const paginatedLeads = filtered.slice(startIdx, endIdx);

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
      backgroundColor: stageStyle?.backgroundColor || "#f3f4f6",
      color: stageStyle?.color || "#374151",
    };
  };

  return (
    <div className="sales-page">
      {/* Page Header */}
      <div className="page-header">
        <div className="header-left">
          <h1>Leads</h1>
          <p className="subtitle">Track and manage your sales leads with comprehensive company data</p>
        </div>
        <div className="header-actions">
          {selectedIds.length > 0 && (
            <button className="btn btn-danger" onClick={bulkDeleteLeads}>
              🗑️ Delete ({selectedIds.length})
            </button>
          )}
          <button className="btn btn-outline" onClick={() => navigate('/admin/sales/leads/import')}>
            📥 Import CSV
          </button>
          <button className="btn btn-primary" onClick={openCreate}>
            + Add New Lead
          </button>
        </div>
      </div>

      {error && <div className="error-alert">{error}</div>}

      {/* Stats Row */}
      <div className="stats-row">
        <div className="stat-card primary">
          <div className="stat-value">{leads.length}</div>
          <div className="stat-label">Total Leads</div>
        </div>
        {leadStages.map(stage => (
          <div key={stage.id} className="stat-card">
            <div className="stat-value">{leads.filter(l => l.stage === stage.id).length}</div>
            <div className="stat-label">{stage.icon} {stage.label}</div>
          </div>
        ))}
      </div>

      {/* Filters Bar */}
      <div className="filters-bar">
        <input
          className="search-input"
          type="text"
          placeholder="Search leads by name, company, title..."
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

      {/* Leads Table */}
      <div className="table-container">
        <table className="data-table">
          <thead>
            <tr>
              <th className="checkbox-col">
                <input 
                  type="checkbox" 
                  checked={paginatedLeads.length > 0 && paginatedLeads.every(l => selectedIds.includes(l._id))}
                  onChange={toggleSelectAll}
                />
              </th>
              <th>Name</th>
              <th>Email</th>
              <th>Title</th>
              <th>Company</th>
              <th>Stage</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {paginatedLeads.map(lead => {
              const stageInfo = getStageById(lead.stage)
              return (
                <tr 
                  key={lead._id} 
                  className={selectedIds.includes(lead._id) ? "selected" : ""}
                >
                  <td className="checkbox-col" onClick={(e) => e.stopPropagation()}>
                    <input 
                      type="checkbox" 
                      checked={selectedIds.includes(lead._id)}
                      onChange={() => toggleSelect(lead._id)}
                    />
                  </td>
                  <td className="name-cell">
                    <span 
                      className="name-link"
                      onClick={() => navigate(`/admin/sales/campaign/ai-leads/${lead._id}`)}
                    >
                      {lead.name || `${lead.firstName || ''} ${lead.lastName || ''}`.trim() || '-'}
                    </span>
                  </td>
                  <td>
                    <div>
                      {lead.email}
                      {lead.emailStatus && (
                        <span className={`status-badge ${getEmailStatusClass(lead.emailStatus)}`} style={{ marginLeft: '8px' }}>
                          {lead.emailStatus}
                        </span>
                      )}
                    </div>
                  </td>
                  <td>{lead.title || '-'}</td>
                  <td>{lead.companyName || lead.company_name || '-'}</td>
                  <td>
                    <span className="stage-badge" style={getStageBadgeStyle(lead.stage)}>
                      {stageInfo?.icon} {stageInfo?.label || lead.stage || 'New'}
                    </span>
                  </td>
                  <td>
                    <div className="actions-cell">
                      {lead.linkedin && (
                        <a 
                          href={lead.linkedin}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="action-btn-linkedin"
                          onClick={(e) => e.stopPropagation()}
                        >
                          in
                        </a>
                      )}
                      <button 
                        className="action-btn"
                        title="Move to Contacts"
                        onClick={(e) => { e.stopPropagation(); moveToContacts(lead._id); }}
                      >
                        →
                      </button>
                      <button 
                        className="action-btn edit"
                        onClick={(e) => { e.stopPropagation(); openEdit(lead); }}
                      >
                        ✏️
                      </button>
                      <button 
                        className="action-btn delete"
                        onClick={(e) => { e.stopPropagation(); deleteLead(lead._id); }}
                      >
                        🗑️
                      </button>
                    </div>
                  </td>
                </tr>
              )
            })}
            {paginatedLeads.length === 0 && (
              <tr>
                <td colSpan={7} className="empty-state">
                  <h3>No leads found</h3>
                  <p>Add a new lead or import from CSV to get started.</p>
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
              <h3>{editingId ? "Edit Lead" : "Add New Lead"}</h3>
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

              <h4 className="section-title">Lead Stage</h4>

              <div className="form-group">
                <label className="form-label">Stage</label>
                <select
                  className="form-select"
                  name="stage"
                  value={formData.stage}
                  onChange={handleChange}
                >
                  {leadStages.map(stage => (
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
                  <label className="form-label">Employee Count Range</label>
                  <input
                    className="form-input"
                    name="companyEmployeeCountRange"
                    placeholder="e.g., 50-200"
                    value={formData.companyEmployeeCountRange}
                    onChange={handleChange}
                  />
                </div>
              </div>

              <div className="form-row">
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
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label className="form-label">Founded Year</label>
                  <input
                    className="form-input"
                    name="companyFounded"
                    placeholder="e.g., 2015"
                    value={formData.companyFounded}
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

              <div className="form-row">
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
                <div className="form-group">
                  <label className="form-label">Crunchbase URL</label>
                  <input
                    className="form-input"
                    name="companyCrunchbaseUrl"
                    placeholder="Enter Crunchbase URL"
                    value={formData.companyCrunchbaseUrl}
                    onChange={handleChange}
                  />
                </div>
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label className="form-label">Funding Rounds</label>
                  <input
                    className="form-input"
                    name="companyFundingRounds"
                    placeholder="e.g., Series A, B"
                    value={formData.companyFundingRounds}
                    onChange={handleChange}
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">Last Funding Amount</label>
                  <input
                    className="form-input"
                    name="companyLastFundingRoundAmount"
                    placeholder="e.g., $5M"
                    value={formData.companyLastFundingRoundAmount}
                    onChange={handleChange}
                  />
                </div>
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label className="form-label">Primary Logo URL</label>
                  <input
                    className="form-input"
                    name="companyLogoPrimary"
                    placeholder="Enter primary logo URL"
                    value={formData.companyLogoPrimary}
                    onChange={handleChange}
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">Secondary Logo URL</label>
                  <input
                    className="form-input"
                    name="companyLogoSecondary"
                    placeholder="Enter secondary logo URL"
                    value={formData.companyLogoSecondary}
                    onChange={handleChange}
                  />
                </div>
              </div>
            </div>

            <div className="modal-footer">
              <button className="btn btn-outline" onClick={() => setShowForm(false)}>Cancel</button>
              <button className="btn btn-primary" onClick={saveLead} disabled={loading}>
                {loading ? "Saving..." : (editingId ? "Update Lead" : "Add Lead")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default Leads
