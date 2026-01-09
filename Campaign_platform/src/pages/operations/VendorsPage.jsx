"use client";

import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { API_BASE_URL } from "../../config"; // adjust path if needed
import "./VendorsPage.css";

function VendorsPage() {
  const navigate = useNavigate(); // ✅ must be defined first
  const [vendors, setVendors] = useState([]);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState("");
  const [currentPage, setCurrentPage] = useState(1);
  const [recordsPerPage, setRecordsPerPage] = useState(10);

  const emptyForm = {
    vid: "",
    vendorName: "",
    vendorEmail: "",
    vendorVariable: "",
    vendorType: "Panel",
    status: "Active",
    completeRD: [],
    terminateRD: [],
    quotaFullRD: [],
  };

  const [formData, setFormData] = useState(emptyForm);

  // 🔹 Fetch Vendors (with session + 401 handling)
  useEffect(() => {
    const sessionId = localStorage.getItem("session_id");
    if (!sessionId) {
      navigate("/login");
      return;
    }

    const fetchVendors = async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/vendors/`, {
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
        if (!res.ok) throw new Error(data.detail || "Failed to load vendors");
        setVendors(data.vendors || []);
      } catch (e) {
        setError(e.message || "Failed to load vendors");
      }
    };
    fetchVendors();
  }, [navigate]);

  // 🔹 Create or Update Vendor
  const saveVendor = async () => {
    // Validate required fields
    if (!formData.vendorName || !formData.vendorName.trim()) {
      setError("❌ Vendor Name is required");
      return;
    }
    if (!formData.vendorVariable || !formData.vendorVariable.trim()) {
      setError("❌ Vendor Variable is required");
      return;
    }
    if (!formData.vendorType || !formData.vendorType.trim()) {
      setError("❌ Vendor Type is required");
      return;
    }
    if (!formData.status || !formData.status.trim()) {
      setError("❌ Status is required");
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
      const payload = {
        ...formData,
        completeRD: formData.completeRD.filter(Boolean),
        terminateRD: formData.terminateRD.filter(Boolean),
        quotaFullRD: formData.quotaFullRD.filter(Boolean),
      };
      delete payload.vid;

      const url = editingId
        ? `${API_BASE_URL}/vendors/${editingId}`
        : `${API_BASE_URL}/vendors/`;
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
      if (!res.ok) throw new Error(data.detail || "Failed to save vendor");

      if (editingId) {
        setVendors((prev) =>
          prev.map((v) => (v._id === editingId ? { ...v, ...payload } : v))
        );
      } else {
        setVendors((prev) => [...prev, data.vendor]);
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

  // 🔹 Delete Vendor
  const deleteVendor = async (id) => {
    if (!window.confirm("Delete this vendor?")) return;
    const sessionId = localStorage.getItem("session_id");
    if (!sessionId) {
      navigate("/login");
      return;
    }

    try {
      const res = await fetch(`${API_BASE_URL}/vendors/${id}`, {
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
      if (!res.ok) throw new Error(data.detail || "Failed to delete vendor");
      setVendors((prev) => prev.filter((v) => v._id !== id));
    } catch (e) {
      setError(e.message || "Delete failed");
    }
  };

  // 🔹 Open modals
  const openCreate = () => {
    setEditingId(null);
    setFormData(emptyForm);
    setShowForm(true);
  };

  const openEdit = (v) => {
    setEditingId(v._id);
    setFormData({
      vid: v.vid || "",
      vendorName: v.vendorName || "",
      vendorEmail: v.vendorEmail || "",
      vendorVariable: v.vendorVariable || "",
      vendorType: v.vendorType || "Panel",
      status: v.status || "Active",
      completeRD: Array.isArray(v.completeRD)
        ? v.completeRD
        : [v.completeRD].filter(Boolean),
      terminateRD: Array.isArray(v.terminateRD)
        ? v.terminateRD
        : [v.terminateRD].filter(Boolean),
      quotaFullRD: Array.isArray(v.quotaFullRD)
        ? v.quotaFullRD
        : [v.quotaFullRD].filter(Boolean),
    });
    setShowForm(true);
  };

  // 🔹 Search filter
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return vendors;
    return vendors.filter((v) =>
      ["vid", "vendorName", "vendorEmail", "vendorVariable", "vendorType"].some(
        (field) => String(v[field] || "").toLowerCase().includes(q)
      )
    );
  }, [vendors, search]);

  const totalPages = Math.ceil(filtered.length / recordsPerPage);
  const startIdx = (currentPage - 1) * recordsPerPage;
  const endIdx = startIdx + recordsPerPage;
  const paginatedVendors = filtered.slice(startIdx, endIdx);

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
          <h2 style={styles.title}>Vendors</h2>
          <p style={styles.subtitle}>Manage your survey vendors and their information</p>
        </div>
        <button style={styles.btnPrimary} onClick={openCreate}>
          + Add New Vendor
        </button>
      </div>

      {error && (
        <div style={styles.errorAlert}>
          {error}
        </div>
      )}

      <div style={styles.searchSection}>
        <input
          style={styles.searchInput}
          value={search}
          onChange={(e) => handleSearch(e.target.value)}
          placeholder="Search vendors by VID, name, email, variable, type..."
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
          <span>Total Vendors: <strong>{vendors.length}</strong></span>
          <span>Active: <strong>{vendors.filter(v => v.status === 'Active').length}</strong></span>
          <span>Inactive: <strong>{vendors.filter(v => v.status === 'Inactive').length}</strong></span>
        </div>
      </div>

      <div style={styles.tableContainer}>
        <table style={styles.table}>
          <thead style={styles.thead}>
            <tr>
              <th style={styles.th}>Vendor No</th>
              <th style={styles.th}>VID</th>
              <th style={styles.th}>Vendor Name</th>
              <th style={styles.th}>Email</th>
              <th style={styles.th}>Variable</th>
              <th style={styles.th}>Type</th>
              <th style={styles.th}>Status</th>
              <th style={styles.th}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {paginatedVendors.map(v => (
              <tr key={v._id} style={styles.tr}>
                <td style={styles.td}>
                  <span style={styles.vid}>{v.vendorNo || 'N/A'}</span>
                </td>
                <td style={styles.td}>
                  <span style={styles.vid}>{v.vid || 'N/A'}</span>
                </td>
                <td style={styles.td}>{v.vendorName}</td>
                <td style={styles.td}>{v.vendorEmail}</td>
                <td style={styles.td}>{v.vendorVariable}</td>
                <td style={styles.td}>
                  <span style={{
                    ...styles.typeBadge,
                    ...(v.vendorType === 'Panel' ? styles.typePanel : 
                        v.vendorType === 'Affiliate' ? styles.typeAffiliate : 
                        styles.typeAPI)
                  }}>
                    {v.vendorType}
                  </span>
                </td>
                <td style={styles.td}>
                  <span style={{
                    ...styles.statusBadge,
                    ...(v.status === 'Active' ? styles.statusActive : styles.statusInactive)
                  }}>
                    {v.status}
                  </span>
                </td>
                <td style={styles.td}>
                  <div style={styles.actionButtons}>
                    <button style={styles.btnEdit} onClick={() => openEdit(v)}>✏️</button>
                    <button style={styles.btnDelete} onClick={() => deleteVendor(v._id)}>🗑️</button>
                  </div>
                </td>
              </tr>
            ))}
            {paginatedVendors.length === 0 && filtered.length === 0 && (
              <tr>
                <td colSpan={7} style={styles.emptyState}>
                  No vendors found.
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
              <h3 style={styles.modalTitle}>{editingId ? "Edit Vendor" : "Add New Vendor"}</h3>
              <button style={styles.closeBtn} onClick={() => setShowForm(false)}>×</button>
            </div>

            <div style={styles.modalBody}>
              <div style={styles.section}>
                <h4 style={styles.sectionTitle}>Basic Information</h4>
                
                <div style={styles.formGroup}>
                  <label style={styles.label}>VID {!editingId && "(Auto-generated)"}</label>
                  <input
                    style={{...styles.input, backgroundColor: editingId ? '#f3f4f6' : '#fff', cursor: editingId ? 'not-allowed' : 'default'}}
                    value={editingId ? (formData.vid || "") : ""}
                    disabled={editingId}
                    readOnly
                    placeholder={!editingId ? "Will be auto-generated" : ""}
                  />
                </div>

                <div style={styles.formGroup}>
                  <label style={styles.label}>Vendor Name <span style={styles.required}>*</span></label>
                  <input
                    style={styles.input}
                    name="vendorName"
                    value={formData.vendorName}
                    onChange={e => setFormData({ ...formData, vendorName: e.target.value })}
                    placeholder="Enter vendor name"
                  />
                </div>

                <div style={styles.formRow}>
                  <div style={styles.formGroup}>
                    <label style={styles.label}>Vendor Variable <span style={styles.required}>*</span></label>
                    <input
                      style={styles.input}
                      name="vendorVariable"
                      value={formData.vendorVariable}
                      onChange={e => setFormData({ ...formData, vendorVariable: e.target.value })}
                      placeholder="Variable name"
                      required
                    />
                  </div>

                  <div style={styles.formGroup}>
                    <label style={styles.label}>Vendor Type <span style={styles.required}>*</span></label>
                    <select
                      style={styles.select}
                      name="vendorType"
                      value={formData.vendorType}
                      onChange={e => setFormData({ ...formData, vendorType: e.target.value })}
                    >
                      <option>Panel</option>
                      <option>DIY Platform</option>
                      <option>API</option>
                    </select>
                  </div>
                </div>

                <div style={styles.formGroup}>
                  <label style={styles.label}>Status <span style={styles.required}>*</span></label>
                  <select
                    style={styles.select}
                    name="status"
                    value={formData.status}
                    onChange={e => setFormData({ ...formData, status: e.target.value })}
                    required
                  >
                    <option>Active</option>
                    <option>Inactive</option>
                  </select>
                </div>
              </div>

              <div style={styles.section}>
                <h4 style={styles.sectionTitle}>Redirect Links</h4>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Complete RD (one per line)</label>
                  <textarea
                    style={styles.textarea}
                    value={formData.completeRD.join("\n")}
                    onChange={e => setFormData({ ...formData, completeRD: e.target.value.split("\n") })}
                    placeholder="Enter complete redirect URLs, one per line"
                    rows="4"
                  />
                </div>

                <div style={styles.formGroup}>
                  <label style={styles.label}>Terminate RD (one per line)</label>
                  <textarea
                    style={styles.textarea}
                    value={formData.terminateRD.join("\n")}
                    onChange={e => setFormData({ ...formData, terminateRD: e.target.value.split("\n") })}
                    placeholder="Enter terminate redirect URLs, one per line"
                    rows="4"
                  />
                </div>

                <div style={styles.formGroup}>
                  <label style={styles.label}>Quota Full RD (one per line)</label>
                  <textarea
                    style={styles.textarea}
                    value={formData.quotaFullRD.join("\n")}
                    onChange={e => setFormData({ ...formData, quotaFullRD: e.target.value.split("\n") })}
                    placeholder="Enter quota full redirect URLs, one per line"
                    rows="4"
                  />
                </div>
              </div>
            </div>

            <div style={styles.modalFooter}>
              <button style={styles.btnCancel} onClick={() => setShowForm(false)} disabled={loading}>
                Cancel
              </button>
              <button style={styles.btnSave} onClick={saveVendor} disabled={loading}>
                {loading ? "Saving..." : editingId ? "Save Changes" : "Add Vendor"}
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
  vid: {
    fontWeight: '600',
    color: '#0d6efd',
    fontFamily: 'monospace',
    fontSize: '0.95rem',
  },
  statusBadge: {
    display: 'inline-block',
    padding: '0.375rem 0.75rem',
    borderRadius: '0.375rem',
    fontSize: '0.8rem',
    fontWeight: '600',
    textTransform: 'capitalize',
  },
  statusActive: {
    backgroundColor: '#d1fae5',
    color: '#065f46',
  },
  statusInactive: {
    backgroundColor: '#e5e7eb',
    color: '#6b7280',
  },
  typeBadge: {
    display: 'inline-block',
    padding: '0.375rem 0.75rem',
    borderRadius: '0.375rem',
    fontSize: '0.8rem',
    fontWeight: '600',
  },
  typePanel: {
    backgroundColor: '#dbeafe',
    color: '#1e40af',
  },
  typeAffiliate: {
    backgroundColor: '#fce7f3',
    color: '#9f1239',
  },
  typeAPI: {
    backgroundColor: '#e0e7ff',
    color: '#3730a3',
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
    maxWidth: '700px',
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
  section: {
    marginBottom: '2rem',
    paddingBottom: '1.5rem',
    borderBottom: '1px solid #e5e7eb',
  },
  sectionTitle: {
    fontSize: '1.1rem',
    fontWeight: '600',
    color: '#1a1a1a',
    marginBottom: '1rem',
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
  textarea: {
    padding: '0.75rem',
    border: '1px solid #d1d5db',
    borderRadius: '0.5rem',
    fontSize: '0.95rem',
    transition: 'all 0.2s',
    fontFamily: 'inherit',
    resize: 'vertical',
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

export default VendorsPage