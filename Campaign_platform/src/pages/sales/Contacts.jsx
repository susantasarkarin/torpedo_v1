/**
 * Contacts Page - Sales Pipeline
 * Redesigned to match AI Database styling
 */
"use client"
import { useEffect, useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
import { API_BASE_URL } from "../../config"
import { getStageStyle as getPipelineStageStyle, getContactStages, getStageById } from "../../utils/salesPipeline"
import "./Contacts.css"
import "../../styles/SalesPages.css"
import { buildApiUrl } from "../../config"
import { confirmAction, notify } from "../../utils/notify"
import { authFetch } from "../../utils/api"
import LeadTable from "../../components/leads/LeadTable"

function Contacts() {
  const navigate = useNavigate();
  const [contacts, setContacts] = useState([])
  const [total, setTotal] = useState(0)
  const [totalPages, setTotalPages] = useState(1)
  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [search, setSearch] = useState("")
  const [currentPage, setCurrentPage] = useState(1)
  const [recordsPerPage, setRecordsPerPage] = useState(10)
  const [selectedIds, setSelectedIds] = useState([])
  const [stageFilter, setStageFilter] = useState("")
  const [showFilters, setShowFilters] = useState(false)
  const [sort, setSort] = useState({ by: null, order: null })

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
    const fetchContacts = async () => {
      const sessionId = localStorage.getItem("session_id");
      if (!sessionId) {
        navigate("/login");
        return;
      }
      setLoading(true);
      setError(null);
      try {
        const params = new URLSearchParams({
          view: "contacts",
          page: String(currentPage),
          limit: String(recordsPerPage),
        });
        if (search) params.set("search", search);
        if (stageFilter) params.set("lead_stage", stageFilter);
        if (sort.by) { params.set("sort_by", sort.by); params.set("sort_order", sort.order); }
        const res = await authFetch(buildApiUrl(`/leads?${params}`), {
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
        setContacts(data.leads || []);
        setTotal(data.total || 0);
        setTotalPages(data.pages || 1);
      } catch (e) {
        setError(e.message || "Failed to load contacts");
      } finally {
        setLoading(false);
      }
    };
    fetchContacts();
  }, [navigate, currentPage, recordsPerPage, search, stageFilter, sort]);

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
      firstName: contact.firstName || contact.first_name || "",
      lastName: contact.lastName || contact.last_name || "",
      email: contact.email || "",
      emailStatus: contact.emailStatus || contact.email_status || "Valid",
      title: contact.title || "",
      linkedin: contact.linkedin || contact.linkedin_url || "",
      location: contact.location || "",
      companyName: contact.companyName || contact.company_name || "",
      companyDomain: contact.companyDomain || contact.company_domain || "",
      companyWebsite: contact.companyWebsite || contact.company_website || "",
      companyEmployeeCount: contact.companyEmployeeCount || contact.company_employee_count || "",
      companyEmployeeCountRange: contact.companyEmployeeCountRange || contact.company_employee_count_range || "",
      companyFounded: contact.companyFounded || contact.company_founded || "",
      companyIndustry: contact.companyIndustry || contact.company_industry || "",
      companyType: contact.companyType || contact.company_type || "",
      companyHeadquarters: contact.companyHeadquarters || contact.company_headquarters || "",
      companyRevenueRange: contact.companyRevenueRange || contact.company_revenue_range || "",
      companyLinkedinUrl: contact.companyLinkedinUrl || contact.company_linkedin_url || "",
      companyCrunchbaseUrl: contact.companyCrunchbaseUrl || contact.company_crunchbase_url || "",
      companyFundingRounds: contact.companyFundingRounds || contact.company_funding_rounds || "",
      companyLastFundingRoundAmount: contact.companyLastFundingRoundAmount || contact.company_last_funding_round_amount || "",
      companyLogoPrimary: contact.companyLogoPrimary || contact.company_logo_primary || "",
      companyLogoSecondary: contact.companyLogoSecondary || contact.company_logo_secondary || "",
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
        ? buildApiUrl(`/contacts/${editingId}`)
        : buildApiUrl(`/contacts/`);
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
        notify("Session expired. Please login again.");
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
    if (!(await confirmAction("Delete this contact?"))) return;

    const sessionId = localStorage.getItem("session_id");
    if (!sessionId) {
      navigate("/login");
      return;
    }

    try {
      const res = await authFetch(buildApiUrl(`/contacts/${id}`), {
        method: "DELETE",
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
    if (!(await confirmAction(`Delete ${selectedIds.length} selected contacts?`))) return;

    const sessionId = localStorage.getItem("session_id");
    if (!sessionId) {
      navigate("/login");
      return;
    }

    try {
      const res = await authFetch(buildApiUrl(`/contacts/bulk-delete`), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: sessionId,
        },
        body: JSON.stringify({ ids: selectedIds }),
      });

      if (res.status === 401) {
        notify("Session expired. Please login again.");
        localStorage.removeItem("session_id");
        navigate("/login");
        return;
      }

      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to delete contacts");

      setContacts((prev) => prev.filter((c) => !selectedIds.includes(c._id)));
      setSelectedIds([]);
      notify(`✅ ${data.deleted_count} contacts deleted successfully!`);
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

  // Server-side pagination: contacts is already paginated from backend
  const paginatedContacts = contacts;

  const handleSearch = (value) => {
    setSearch(value);
    setCurrentPage(1);
  };

  const handleRecordsPerPageChange = (value) => {
    setRecordsPerPage(parseInt(value));
    setCurrentPage(1);
  };

  // Same lead cells as Sales > Leads, plus what only a contact has: a client
  // link, its pipeline stage, and row actions.
  const contactColumns = [
    "lead",
    "email",
    {
      key: "company", label: "Company / Client", width: 200,
      render: (contact) => (
        <>
          <div className="cell-clip" title={contact.company_name || ""}>{contact.companyName || contact.company_name || "—"}</div>
          {contact.linked_customer ? (
            <span
              className="client-link-badge"
              title={`Linked to Client: ${contact.linked_customer.company_name || contact.linked_customer.name}`}
              style={{ display: "inline-block", marginTop: 2, padding: "1px 6px", fontSize: "0.75rem", background: "#16a34a", color: "white", borderRadius: 4, fontWeight: 500 }}
              onClick={(e) => { e.stopPropagation(); navigate("/admin/operations/clients"); }}
            >
              🔗 Client
            </span>
          ) : contact.pending_customer_company ? (
            <span
              title={`${contact.pending_customer_company} is not a client yet — no linked client record`}
              style={{ display: "inline-block", marginTop: 2, padding: "1px 6px", fontSize: "0.75rem", background: "#e8e4dc", color: "#5c5c5c", borderRadius: 4, fontWeight: 500 }}
            >
              ○ Prospect
            </span>
          ) : null}
        </>
      ),
    },
    {
      key: "stage", label: "Stage", width: 160,
      render: (contact) => {
        const stageInfo = getStageById(contact.stage);
        return (
          <span className="stage-badge cell-clip" style={{ ...getStageBadgeStyle(contact.stage), display: "inline-block", maxWidth: "100%" }}>
            {stageInfo?.icon} {stageInfo?.label || contact.stage || "Discovery Call"}
          </span>
        );
      },
    },
    "icp",
    "reply",
    {
      key: "actions", label: "Actions", width: 120, sortable: false, required: true,
      render: (contact) => (
        <div className="actions-cell" onClick={(e) => e.stopPropagation()}>
          {(contact.linkedin || contact.linkedin_url) && (
            <a href={contact.linkedin || contact.linkedin_url} target="_blank" rel="noopener noreferrer" className="action-btn-linkedin">in</a>
          )}
          <button className="action-btn edit" onClick={() => openEdit(contact)} aria-label="Edit contact">✏️</button>
          <button className="action-btn delete" onClick={() => deleteContact(contact._id)} aria-label="Delete contact">🗑️</button>
        </div>
      ),
    },
  ];

  // Get stage badge style
  const getStageBadgeStyle = (stageId) => {
    const stageStyle = getPipelineStageStyle(stageId);
    return {
      backgroundColor: stageStyle?.bg || stageStyle?.backgroundColor || "#f5f3ef",
      color: stageStyle?.color || "#4a4a4a",
    };
  };

  return (
    <div className="sales-page">
      {/* Page Header */}
      <div className="page-header">
        <div className="header-left">
          <h1 className="cx-page-title">Contacts</h1>
          <p className="subtitle">{total.toLocaleString()} contacts in the sales pipeline (discovery call onwards)</p>
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
              onClick={async () => {
                if ((await confirmAction('⚠️ Clear all old contacts that are missing the new fields? This cannot be undone!'))) {
                  const oldContacts = contacts.filter(c => !c.name && !c.firstName && !c.companyName);
                  oldContacts.forEach(c => deleteContact(c._id));
                }
              }}
            >
              🗑️ Clear Old ({contacts.filter(c => !c.name && !c.firstName && !c.companyName).length})
            </button>
          )}
          <button className="btn btn-secondary" onClick={() => navigate("/admin/sales/contacts/import")}>
            Import
          </button>
          <button className="btn btn-primary" onClick={openCreate}>
            + Add New Contact
          </button>
        </div>
      </div>

      {error && <div className="error-alert">{error}</div>}

      {/* Table — always mounted so the search box keeps focus while rows reload */}
      <LeadTable
        leads={paginatedContacts}
        columns={contactColumns}
        storageKey="sales_contacts_col_widths"
        onRowClick={contact => navigate(`/admin/sales/campaign/ai-leads/${contact._id}`)}
        onStatusUpdated={(id, status) => setContacts(prev => prev.map(c => c._id === id ? { ...c, lead_status: status } : c))}
        selection={{
          isSelected: id => selectedIds.includes(id),
          onToggle: toggleSelect,
          onToggleAll: toggleSelectAll,
          allSelected: paginatedContacts.length > 0 && paginatedContacts.every(c => selectedIds.includes(c._id)),
        }}
        sort={sort}
        onSort={(by, order) => { setSort({ by, order }); setCurrentPage(1) }}
        toolbar={
          <>
            <input
              type="text"
              placeholder="Search name, email, company…"
              value={search}
              onChange={e => handleSearch(e.target.value)}
              style={{ minWidth: 240 }}
              aria-label="Search contacts"
            />
            <button type="button" className={`toolbar-btn ${showFilters || stageFilter ? "active" : ""}`}
                    onClick={() => setShowFilters(v => !v)} aria-expanded={showFilters}>
              Filters ▾{stageFilter ? " (1)" : ""}
            </button>
            {loading && <span style={{ color: "#6f6f6f", fontSize: "0.85rem" }}>Loading…</span>}
          </>
        }
        filterPanel={showFilters && (
          <div className="lead-table-filters">
            <select value={stageFilter} onChange={e => { setStageFilter(e.target.value); setCurrentPage(1) }} aria-label="Stage">
              <option value="">All Stages</option>
              {contactStages.map(stage => (
                <option key={stage.id} value={stage.id}>{stage.icon} {stage.label}</option>
              ))}
            </select>
            <select value={recordsPerPage} onChange={e => handleRecordsPerPageChange(e.target.value)} aria-label="Rows per page">
              <option value={10}>10 per page</option>
              <option value={20}>20 per page</option>
              <option value={50}>50 per page</option>
              <option value={100}>100 per page</option>
              <option value={200}>200 per page</option>
            </select>
          </div>
        )}
        empty={
          <div style={{ textAlign: "center", padding: 64, color: "#5c5c5c" }}>
            <h3>{loading ? "Loading contacts…" : "No contacts found"}</h3>
            {!loading && <p>Move leads from the Leads page to get started!</p>}
          </div>
        }
      />

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="pagination-bar">
          <button
            className="btn btn-outline"
            onClick={() => setCurrentPage(Math.max(1, currentPage - 1))}
            disabled={currentPage === 1}
          >
             Previous
          </button>
          <span className="page-info">
            Page <strong>{currentPage}</strong> of <strong>{totalPages}</strong>
            {" "}
            <span style={{ marginLeft: 8 }}>
              ({total.toLocaleString()} contacts)
            </span>
          </span>
          <button
            className="btn btn-outline"
            onClick={() => setCurrentPage(Math.min(totalPages, currentPage + 1))}
            disabled={currentPage === totalPages}
          >
            Next 
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
                {loading ? "Saving…" : (editingId ? "Update Contact" : "Add Contact")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default Contacts
