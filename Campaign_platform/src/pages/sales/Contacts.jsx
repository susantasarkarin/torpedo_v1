"use client"
import { useEffect, useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
import { API_BASE_URL } from "../../config"
import { SALES_STAGES, getStageStyle as getPipelineStageStyle, getContactStages, getStageById } from "../../utils/salesPipeline"

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
        const res = await fetch(`${API_BASE_URL}/contacts/`, {
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
        setContacts(data.contacts || []);
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

  // Stage badge colors - use the shared pipeline styles
  const getStageStyle = (stageId) => {
    return getPipelineStageStyle(stageId)
  }

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <div>
          <h2 style={styles.title}>Contacts</h2>
          <p style={styles.subtitle}>Manage qualified leads through the sales pipeline stages</p>
        </div>
        <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
          {selectedIds.length > 0 && (
            <button 
              style={{...styles.btnPrimary, backgroundColor: '#dc2626'}} 
              onClick={bulkDeleteContacts}
            >
              🗑️ Delete ({selectedIds.length})
            </button>
          )}
          {contacts.length > 0 && contacts.some(c => !c.name && !c.firstName && !c.companyName) && (
            <button 
              style={{...styles.btnPrimary, backgroundColor: '#dc3545'}} 
              onClick={() => {
                if (window.confirm('⚠️ Clear all old contacts that are missing the new fields? This cannot be undone!')) {
                  const oldContacts = contacts.filter(c => !c.name && !c.firstName && !c.companyName);
                  oldContacts.forEach(c => deleteContact(c._id));
                }
              }}
            >
              🗑️ Clear Old Contacts ({contacts.filter(c => !c.name && !c.firstName && !c.companyName).length})
            </button>
          )}
          <button style={styles.btnPrimary} onClick={openCreate}>
            + Add New Contact
          </button>
        </div>
      </div>

      {error && <div style={styles.errorAlert}>{error}</div>}

      {/* Search and Stats */}
      <div style={styles.searchSection}>
        <input
          style={styles.searchInput}
          type="text"
          placeholder="Search contacts by name, email, company..."
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
          <span>Total: <strong>{contacts.length}</strong></span>
          {contactStages.map(stage => (
            <span key={stage.id}>{stage.icon} {stage.label}: <strong>{contacts.filter(c => c.stage === stage.id).length}</strong></span>
          ))}
        </div>
      </div>

      {/* Contacts Table */}
      <div style={styles.tableContainer}>
        <table style={styles.table}>
          <thead style={styles.thead}>
            <tr>
              <th style={{...styles.th, width: '40px'}}>
                <input 
                  type="checkbox" 
                  checked={paginatedContacts.length > 0 && paginatedContacts.every(c => selectedIds.includes(c._id))}
                  onChange={toggleSelectAll}
                  style={{ cursor: 'pointer' }}
                />
              </th>
              <th style={styles.th}>Name</th>
              <th style={styles.th}>Email</th>
              <th style={styles.th}>Title</th>
              <th style={styles.th}>Company</th>
              <th style={styles.th}>Industry</th>
              <th style={styles.th}>Stage</th>
              <th style={styles.th}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {paginatedContacts.map(contact => {
              const stageStyle = getStageStyle(contact.stage)
              return (
                <tr key={contact._id} style={{...styles.tr, backgroundColor: selectedIds.includes(contact._id) ? '#eff6ff' : 'transparent'}}>
                  <td style={styles.td}>
                    <input 
                      type="checkbox" 
                      checked={selectedIds.includes(contact._id)}
                      onChange={() => toggleSelect(contact._id)}
                      style={{ cursor: 'pointer' }}
                    />
                  </td>
                  <td style={styles.td}>
                    {contact.name || `${contact.firstName} ${contact.lastName}`.trim() || '-'}
                  </td>
                  <td style={styles.td}>
                    <div>
                      {contact.email}
                      {contact.emailStatus && (
                        <span style={{
                          ...styles.statusBadge,
                          ...(contact.emailStatus === 'Valid' ? styles.statusValid : styles.statusInvalid),
                          marginLeft: '0.5rem'
                        }}>
                          {contact.emailStatus}
                        </span>
                      )}
                    </div>
                  </td>
                  <td style={styles.td}>{contact.title || '-'}</td>
                  <td style={styles.td}>{contact.companyName || '-'}</td>
                  <td style={styles.td}>{contact.companyIndustry || '-'}</td>
                  <td style={styles.td}>
                    <span style={{
                      ...styles.statusBadge,
                      backgroundColor: stageStyle.bg,
                      color: stageStyle.color
                    }}>
                      {getStageById(contact.stage)?.icon} {getStageById(contact.stage)?.label || contact.stage || 'Discovery Call'}
                    </span>
                  </td>
                  <td style={styles.td}>
                    <div style={styles.actionButtons}>
                      <button style={styles.btnEdit} onClick={() => openEdit(contact)}>✏️</button>
                      <button style={styles.btnDelete} onClick={() => deleteContact(contact._id)}>🗑️</button>
                    </div>
                  </td>
                </tr>
              )
            })}
            {paginatedContacts.length === 0 && filtered.length === 0 && (
              <tr>
                <td colSpan={8} style={styles.emptyState}>
                  No contacts found. Move leads from the Leads page to get started!
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
              <h3 style={styles.modalTitle}>{editingId ? "Edit Contact" : "Add New Contact"}</h3>
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

              <h4 style={styles.sectionTitle}>Sales Stage</h4>

              <div style={styles.formGroup}>
                <label style={styles.label}>Stage <span style={styles.required}>*</span></label>
                <select
                  style={styles.select}
                  name="stage"
                  value={formData.stage}
                  onChange={handleChange}
                >
                  {SALES_STAGES.map(stage => (
                    <option key={stage.id} value={stage.id}>{stage.icon} {stage.label}</option>
                  ))}
                </select>
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

              <div style={styles.formGroup}>
                <label style={styles.label}>Company Email</label>
                <input
                  style={styles.input}
                  type="email"
                  name="companyEmail"
                  placeholder="Enter company email"
                  value={formData.companyEmail}
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
              <button style={styles.btnSave} onClick={saveContact} disabled={loading}>
                {loading ? "Saving..." : editingId ? "Save Changes" : "Add Contact"}
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

export default Contacts
