"use client"
import { useEffect, useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
import { API_BASE_URL } from "../../config"

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
        const res = await fetch(`${API_BASE_URL}/leads/`, {
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
      firstName: lead.firstName || "",
      lastName: lead.lastName || "",
      email: lead.email || "",
      emailStatus: lead.emailStatus || "Valid",
      title: lead.title || "",
      linkedin: lead.linkedin || "",
      location: lead.location || "",
      companyName: lead.companyName || "",
      companyDomain: lead.companyDomain || "",
      companyWebsite: lead.companyWebsite || "",
      companyEmployeeCount: lead.companyEmployeeCount || "",
      companyEmployeeCountRange: lead.companyEmployeeCountRange || "",
      companyFounded: lead.companyFounded || "",
      companyIndustry: lead.companyIndustry || "",
      companyType: lead.companyType || "",
      companyHeadquarters: lead.companyHeadquarters || "",
      companyRevenueRange: lead.companyRevenueRange || "",
      companyLinkedinUrl: lead.companyLinkedinUrl || "",
      companyCrunchbaseUrl: lead.companyCrunchbaseUrl || "",
      companyFundingRounds: lead.companyFundingRounds || "",
      companyLastFundingRoundAmount: lead.companyLastFundingRoundAmount || "",
      companyLogoPrimary: lead.companyLogoPrimary || "",
      companyLogoSecondary: lead.companyLogoSecondary || "",
    })
    setShowForm(true)
  }

  // Create or Update lead
  const saveLead = async () => {
    // Validate required fields
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

  // Move lead to contacts (RFQ stage)
  const moveToContacts = async (id) => {
    if (!window.confirm("Move this lead to Contacts (RFQ stage)?")) return;

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
        body: JSON.stringify({ stage: "RFQ" }),
      });

      if (res.status === 401) {
        alert("Session expired. Please login again.");
        localStorage.removeItem("session_id");
        navigate("/login");
        return;
      }

      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to move lead");

      // Remove from leads list
      setLeads((prev) => prev.filter((l) => l._id !== id));
      alert("✅ Lead moved to Contacts successfully!");
    } catch (e) {
      setError(e.message || "Move failed");
    }
  };

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return leads;
    return leads.filter((l) =>
      ["name", "firstName", "lastName", "email", "title", "companyName", "companyIndustry", "location"].some((field) =>
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

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <div>
          <h2 style={styles.title}>Leads</h2>
          <p style={styles.subtitle}>Track and manage your sales leads with comprehensive company data</p>
        </div>
        <button style={styles.btnPrimary} onClick={openCreate}>
          + Add New Lead
        </button>
      </div>

      {error && <div style={styles.errorAlert}>{error}</div>}

      {/* Search and Stats */}
      <div style={styles.searchSection}>
        <input
          style={styles.searchInput}
          type="text"
          placeholder="Search leads by name, company, title..."
          value={search}
          onChange={e => handleSearch(e.target.value)}
        />
        <select
          style={styles.recordsPerPageSelect}
          value={recordsPerPage}
          onChange={e => handleRecordsPerPageChange(e.target.value)}
        >
          <option value={10}>10 per page</option>
          <option value={20}>20 per page</option>
          <option value={50}>50 per page</option>
          <option value={100}>100 per page</option>
          <option value={200}>200 per page</option>
        </select>
        <div style={styles.stats}>
          <span>Total: <strong>{leads.length}</strong></span>
          <span>Valid Email: <strong>{leads.filter(l => l.emailStatus === "Valid").length}</strong></span>
          <span>Qualified: <strong>{leads.filter(l => l.status === "Qualified").length}</strong></span>
        </div>
      </div>

      {/* Leads Table */}
      <div style={styles.tableContainer}>
        <table style={styles.table}>
          <thead style={styles.thead}>
            <tr>
              <th style={styles.th}>Name</th>
              <th style={styles.th}>Email</th>
              <th style={styles.th}>Title</th>
              <th style={styles.th}>Company</th>
              <th style={styles.th}>Industry</th>
              <th style={styles.th}>Location</th>
              <th style={styles.th}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {paginatedLeads.map(lead => (
              <tr key={lead._id} style={styles.tr}>
                <td style={styles.td}>
                  {lead.name || `${lead.firstName} ${lead.lastName}`.trim() || '-'}
                </td>
                <td style={styles.td}>
                  <div>
                    {lead.email}
                    {lead.emailStatus && (
                      <span style={{
                        ...styles.statusBadge,
                        ...(lead.emailStatus === 'Valid' ? styles.statusValid : styles.statusInvalid),
                        marginLeft: '0.5rem'
                      }}>
                        {lead.emailStatus}
                      </span>
                    )}
                  </div>
                </td>
                <td style={styles.td}>{lead.title || '-'}</td>
                <td style={styles.td}>{lead.companyName || '-'}</td>
                <td style={styles.td}>{lead.companyIndustry || '-'}</td>
                <td style={styles.td}>{lead.location || '-'}</td>
                <td style={styles.td}>
                  <div style={styles.actionButtons}>
                    <button style={styles.btnMoveToRFQ} onClick={() => moveToContacts(lead._id)} title="Move to Contacts (RFQ)">
                      ➡️
                    </button>
                    <button style={styles.btnEdit} onClick={() => openEdit(lead)}>✏️</button>
                    <button style={styles.btnDelete} onClick={() => deleteLead(lead._id)}>🗑️</button>
                  </div>
                </td>
              </tr>
            ))}
            {paginatedLeads.length === 0 && filtered.length === 0 && (
              <tr>
                <td colSpan={7} style={styles.emptyState}>
                  No leads found.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div style={styles.paginationContainer}>
          <button
            style={{...styles.paginationBtn, ...(currentPage === 1 ? styles.paginationBtnDisabled : {})}}
            onClick={() => setCurrentPage(Math.max(1, currentPage - 1))}
            disabled={currentPage === 1}
          >
            ← Previous
          </button>
          <div style={styles.pageInfo}>
            Page <strong>{currentPage}</strong> of <strong>{totalPages}</strong>
          </div>
          <button
            style={{...styles.paginationBtn, ...(currentPage === totalPages ? styles.paginationBtnDisabled : {})}}
            onClick={() => setCurrentPage(Math.min(totalPages, currentPage + 1))}
            disabled={currentPage === totalPages}
          >
            Next →
          </button>
        </div>
      )}

      {/* Add/Edit Modal */}
      {showForm && (
        <div style={styles.modal} onClick={(e) => {
          if (e.target === e.currentTarget) setShowForm(false)
        }}>
          <div style={styles.modalContent} onClick={(e) => e.stopPropagation()}>
            <div style={styles.modalHeader}>
              <h3 style={styles.modalTitle}>{editingId ? "Edit Lead" : "Add New Lead"}</h3>
              <button style={styles.closeBtn} onClick={() => setShowForm(false)}>×</button>
            </div>

            <div style={styles.modalBody}>
              <h4 style={styles.sectionTitle}>Personal Information</h4>
              
              <div style={styles.formGroup}>
                <label style={styles.label}>Full Name</label>
                <input
                  style={styles.input}
                  name="name"
                  placeholder="Enter full name"
                  value={formData.name}
                  onChange={handleChange}
                />
              </div>

              <div style={styles.formRow}>
                <div style={styles.formGroup}>
                  <label style={styles.label}>First Name</label>
                  <input
                    style={styles.input}
                    name="firstName"
                    placeholder="Enter first name"
                    value={formData.firstName}
                    onChange={handleChange}
                  />
                </div>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Last Name</label>
                  <input
                    style={styles.input}
                    name="lastName"
                    placeholder="Enter last name"
                    value={formData.lastName}
                    onChange={handleChange}
                  />
                </div>
              </div>

              <div style={styles.formRow}>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Email <span style={styles.required}>*</span></label>
                  <input
                    style={styles.input}
                    name="email"
                    type="email"
                    placeholder="Enter email address"
                    value={formData.email}
                    onChange={handleChange}
                  />
                </div>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Email Status</label>
                  <select
                    style={styles.select}
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

              <div style={styles.formRow}>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Title</label>
                  <input
                    style={styles.input}
                    name="title"
                    placeholder="Enter job title"
                    value={formData.title}
                    onChange={handleChange}
                  />
                </div>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Location</label>
                  <input
                    style={styles.input}
                    name="location"
                    placeholder="Enter location"
                    value={formData.location}
                    onChange={handleChange}
                  />
                </div>
              </div>

              <div style={styles.formGroup}>
                <label style={styles.label}>LinkedIn Profile</label>
                <input
                  style={styles.input}
                  name="linkedin"
                  placeholder="Enter LinkedIn URL"
                  value={formData.linkedin}
                  onChange={handleChange}
                />
              </div>

              <h4 style={styles.sectionTitle}>Company Information</h4>

              <div style={styles.formGroup}>
                <label style={styles.label}>Company Name</label>
                <input
                  style={styles.input}
                  name="companyName"
                  placeholder="Enter company name"
                  value={formData.companyName}
                  onChange={handleChange}
                />
              </div>

              <div style={styles.formRow}>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Company Domain</label>
                  <input
                    style={styles.input}
                    name="companyDomain"
                    placeholder="e.g., example.com"
                    value={formData.companyDomain}
                    onChange={handleChange}
                  />
                </div>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Company Website</label>
                  <input
                    style={styles.input}
                    name="companyWebsite"
                    placeholder="Enter website URL"
                    value={formData.companyWebsite}
                    onChange={handleChange}
                  />
                </div>
              </div>

              <div style={styles.formRow}>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Employee Count</label>
                  <input
                    style={styles.input}
                    name="companyEmployeeCount"
                    placeholder="Enter employee count"
                    value={formData.companyEmployeeCount}
                    onChange={handleChange}
                  />
                </div>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Employee Count Range</label>
                  <input
                    style={styles.input}
                    name="companyEmployeeCountRange"
                    placeholder="e.g., 50-200"
                    value={formData.companyEmployeeCountRange}
                    onChange={handleChange}
                  />
                </div>
              </div>

              <div style={styles.formRow}>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Industry</label>
                  <input
                    style={styles.input}
                    name="companyIndustry"
                    placeholder="Enter industry"
                    value={formData.companyIndustry}
                    onChange={handleChange}
                  />
                </div>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Company Type</label>
                  <input
                    style={styles.input}
                    name="companyType"
                    placeholder="e.g., Private, Public"
                    value={formData.companyType}
                    onChange={handleChange}
                  />
                </div>
              </div>

              <div style={styles.formRow}>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Founded Year</label>
                  <input
                    style={styles.input}
                    name="companyFounded"
                    placeholder="e.g., 2015"
                    value={formData.companyFounded}
                    onChange={handleChange}
                  />
                </div>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Headquarters</label>
                  <input
                    style={styles.input}
                    name="companyHeadquarters"
                    placeholder="Enter headquarters location"
                    value={formData.companyHeadquarters}
                    onChange={handleChange}
                  />
                </div>
              </div>

              <div style={styles.formGroup}>
                <label style={styles.label}>Revenue Range</label>
                <input
                  style={styles.input}
                  name="companyRevenueRange"
                  placeholder="e.g., $10M - $50M"
                  value={formData.companyRevenueRange}
                  onChange={handleChange}
                />
              </div>

              <div style={styles.formRow}>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Company LinkedIn URL</label>
                  <input
                    style={styles.input}
                    name="companyLinkedinUrl"
                    placeholder="Enter company LinkedIn URL"
                    value={formData.companyLinkedinUrl}
                    onChange={handleChange}
                  />
                </div>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Crunchbase URL</label>
                  <input
                    style={styles.input}
                    name="companyCrunchbaseUrl"
                    placeholder="Enter Crunchbase URL"
                    value={formData.companyCrunchbaseUrl}
                    onChange={handleChange}
                  />
                </div>
              </div>

              <div style={styles.formRow}>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Funding Rounds</label>
                  <input
                    style={styles.input}
                    name="companyFundingRounds"
                    placeholder="e.g., Series A, B"
                    value={formData.companyFundingRounds}
                    onChange={handleChange}
                  />
                </div>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Last Funding Amount</label>
                  <input
                    style={styles.input}
                    name="companyLastFundingRoundAmount"
                    placeholder="e.g., $5M"
                    value={formData.companyLastFundingRoundAmount}
                    onChange={handleChange}
                  />
                </div>
              </div>

              <div style={styles.formRow}>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Company Logo (Primary URL)</label>
                  <input
                    style={styles.input}
                    name="companyLogoPrimary"
                    placeholder="Enter logo URL"
                    value={formData.companyLogoPrimary}
                    onChange={handleChange}
                  />
                </div>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Company Logo (Secondary URL)</label>
                  <input
                    style={styles.input}
                    name="companyLogoSecondary"
                    placeholder="Enter secondary logo URL"
                    value={formData.companyLogoSecondary}
                    onChange={handleChange}
                  />
                </div>
              </div>
            </div>

            <div style={styles.modalFooter}>
              <button style={styles.btnCancel} onClick={() => setShowForm(false)} disabled={loading}>
                Cancel
              </button>
              <button style={styles.btnSave} onClick={saveLead} disabled={loading}>
                {loading ? "Saving..." : editingId ? "Save Changes" : "Add Lead"}
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
    maxWidth: '1400px',
    margin: '0 auto',
    padding: '2rem',
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
    backgroundColor: '#f8f9fa',
    minHeight: '100vh',
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: '2rem',
  },
  title: {
    fontSize: '2rem',
    fontWeight: '700',
    margin: '0 0 0.5rem 0',
    color: '#1a1a1a',
  },
  subtitle: {
    color: '#6b7280',
    margin: '0',
    fontSize: '0.95rem',
  },
  btnPrimary: {
    padding: '0.75rem 1.5rem',
    backgroundColor: '#0d6efd',
    color: 'white',
    border: 'none',
    borderRadius: '0.5rem',
    fontSize: '0.95rem',
    fontWeight: '500',
    cursor: 'pointer',
    transition: 'all 0.2s',
  },
  errorAlert: {
    padding: '1rem',
    marginBottom: '1.5rem',
    backgroundColor: '#fee2e2',
    color: '#991b1b',
    borderRadius: '0.5rem',
    border: '1px solid #fecaca',
  },
  searchSection: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: '1.5rem',
    padding: '1.25rem',
    backgroundColor: 'white',
    borderRadius: '0.75rem',
    boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
  },
  searchInput: {
    flex: '1',
    maxWidth: '400px',
    padding: '0.75rem 1rem',
    border: '1px solid #d1d5db',
    borderRadius: '0.5rem',
    fontSize: '0.95rem',
  },
  recordsPerPageSelect: {
    padding: '0.75rem 1rem',
    border: '1px solid #d1d5db',
    borderRadius: '0.5rem',
    fontSize: '0.95rem',
    backgroundColor: 'white',
    cursor: 'pointer',
  },
  stats: {
    display: 'flex',
    gap: '2rem',
    fontSize: '0.9rem',
    color: '#6b7280',
  },
  tableContainer: {
    backgroundColor: 'white',
    borderRadius: '0.75rem',
    overflow: 'hidden',
    boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
  },
  table: {
    width: '100%',
    borderCollapse: 'collapse',
  },
  thead: {
    backgroundColor: '#f9fafb',
    borderBottom: '2px solid #e5e7eb',
  },
  th: {
    padding: '1rem',
    textAlign: 'left',
    fontSize: '0.75rem',
    fontWeight: '600',
    textTransform: 'uppercase',
    color: '#6b7280',
    letterSpacing: '0.05em',
  },
  tr: {
    borderBottom: '1px solid #e5e7eb',
    transition: 'background-color 0.15s',
  },
  td: {
    padding: '1rem',
    fontSize: '0.9rem',
    color: '#374151',
  },
  statusBadge: {
    display: 'inline-block',
    padding: '0.25rem 0.5rem',
    borderRadius: '0.25rem',
    fontSize: '0.7rem',
    fontWeight: '600',
    textTransform: 'capitalize',
  },
  statusValid: {
    backgroundColor: '#d1fae5',
    color: '#065f46',
  },
  statusInvalid: {
    backgroundColor: '#fee2e2',
    color: '#991b1b',
  },
  actionButtons: {
    display: 'flex',
    gap: '0.5rem',
  },
  btnMoveToRFQ: {
    padding: '0.5rem 0.75rem',
    backgroundColor: '#10b981',
    color: 'white',
    border: 'none',
    borderRadius: '0.375rem',
    cursor: 'pointer',
    fontSize: '1rem',
  },
  btnEdit: {
    padding: '0.5rem 0.75rem',
    backgroundColor: '#6b7280',
    color: 'white',
    border: 'none',
    borderRadius: '0.375rem',
    cursor: 'pointer',
    fontSize: '1rem',
  },
  btnDelete: {
    padding: '0.5rem 0.75rem',
    backgroundColor: '#ef4444',
    color: 'white',
    border: 'none',
    borderRadius: '0.375rem',
    cursor: 'pointer',
    fontSize: '1rem',
  },
  emptyState: {
    textAlign: 'center',
    padding: '3rem',
    color: '#9ca3af',
  },
  modal: {
    position: 'fixed',
    top: '0',
    left: '0',
    right: '0',
    bottom: '0',
    backgroundColor: 'rgba(0, 0, 0, 0.5)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: '1000',
    padding: '1rem',
  },
  modalContent: {
    backgroundColor: 'white',
    borderRadius: '0.75rem',
    width: '100%',
    maxWidth: '900px',
    maxHeight: '90vh',
    overflow: 'hidden',
    display: 'flex',
    flexDirection: 'column',
    boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.25)',
  },
  modalHeader: {
    padding: '1.5rem',
    borderBottom: '1px solid #e5e7eb',
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    backgroundColor: 'white',
  },
  modalTitle: {
    fontSize: '1.5rem',
    fontWeight: '600',
    color: '#1a1a1a',
    margin: '0',
  },
  closeBtn: {
    background: 'none',
    border: 'none',
    fontSize: '2rem',
    color: '#9ca3af',
    cursor: 'pointer',
    padding: '0',
    width: '2rem',
    height: '2rem',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    lineHeight: '1',
  },
  modalBody: {
    padding: '1.5rem',
    overflowY: 'auto',
    flex: '1',
  },
  sectionTitle: {
    fontSize: '1.1rem',
    fontWeight: '600',
    color: '#374151',
    marginTop: '1.5rem',
    marginBottom: '1rem',
    paddingBottom: '0.5rem',
    borderBottom: '2px solid #e5e7eb',
  },
  formRow: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: '1rem',
  },
  formGroup: {
    display: 'flex',
    flexDirection: 'column',
    marginBottom: '1rem',
  },
  label: {
    marginBottom: '0.5rem',
    fontSize: '0.875rem',
    fontWeight: '500',
    color: '#374151',
  },
  required: {
    color: '#ef4444',
  },
  input: {
    padding: '0.75rem',
    border: '1px solid #d1d5db',
    borderRadius: '0.5rem',
    fontSize: '0.95rem',
    transition: 'all 0.2s',
    backgroundColor: 'white',
  },
  select: {
    padding: '0.75rem',
    border: '1px solid #d1d5db',
    borderRadius: '0.5rem',
    fontSize: '0.95rem',
    transition: 'all 0.2s',
    cursor: 'pointer',
    backgroundColor: 'white',
  },
  modalFooter: {
    padding: '1rem 1.5rem',
    borderTop: '1px solid #e5e7eb',
    display: 'flex',
    justifyContent: 'flex-end',
    gap: '0.75rem',
    backgroundColor: 'white',
  },
  btnCancel: {
    padding: '0.75rem 1.5rem',
    backgroundColor: '#6b7280',
    color: 'white',
    border: 'none',
    borderRadius: '0.5rem',
    fontSize: '0.95rem',
    fontWeight: '500',
    cursor: 'pointer',
  },
  btnSave: {
    padding: '0.75rem 1.5rem',
    backgroundColor: '#0d6efd',
    color: 'white',
    border: 'none',
    borderRadius: '0.5rem',
    fontSize: '0.95rem',
    fontWeight: '500',
    cursor: 'pointer',
  },
  paginationContainer: {
    display: 'flex',
    justifyContent: 'center',
    alignItems: 'center',
    gap: '1rem',
    marginTop: '2rem',
    padding: '1rem',
    backgroundColor: 'white',
    borderRadius: '0.75rem',
    boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
  },
  paginationBtn: {
    padding: '0.5rem 1rem',
    backgroundColor: '#0d6efd',
    color: 'white',
    border: 'none',
    borderRadius: '0.375rem',
    fontSize: '0.9rem',
    fontWeight: '500',
    cursor: 'pointer',
    transition: 'all 0.2s',
  },
  paginationBtnDisabled: {
    backgroundColor: '#d1d5db',
    cursor: 'not-allowed',
    opacity: '0.6',
  },
  pageInfo: {
    fontSize: '0.9rem',
    color: '#6b7280',
    minWidth: '150px',
    textAlign: 'center',
  },
}

export default Leads
