"use client"
import { useEffect, useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
import { API_BASE_URL } from "../../config"

// Helper functions to map between account UI format and sales accounts API format
const apiAccountToUIAccount = (account) => ({
  _id: account._id,
  name: account.account_name || account.company_name || "",
  contactPerson: account.phone || "",
  email: account.email || "",
  phone: account.phone || "",
  address: account.address || "",
  accountValue: account.notes || "",
  status: account.status === "active" ? "Active" : "Inactive",
  createdAt: account.created_at,
  updatedAt: account.updated_at,
  linked_operations_client_id: account.linked_operations_client_id || null,
  linked_finance_customer_id: account.linked_finance_customer_id || null,
});

const uiAccountToAPIAccount = (accountData) => ({
  account_name: accountData.name,
  company_name: accountData.name,
  email: accountData.email,
  phone: accountData.phone || accountData.contactPerson || "",
  address: accountData.address || "",
  notes: accountData.accountValue || "",
  status: accountData.status === "Active" ? "active" : "inactive",
});

function Account() {
  const navigate = useNavigate();
  const [accounts, setAccounts] = useState([])
  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [search, setSearch] = useState("")
  const [currentPage, setCurrentPage] = useState(1)
  const [recordsPerPage, setRecordsPerPage] = useState(10)
  const [selectedIds, setSelectedIds] = useState([])

  const emptyForm = {
    name: "",
    contactPerson: "",
    email: "",
    phone: "",
    address: "",
    accountValue: "",
    status: "Active",
  }
  const [formData, setFormData] = useState(emptyForm)

  // Fetch accounts function - uses Sales Accounts API
  const fetchAccounts = async () => {
    const sessionId = localStorage.getItem("session_id");
    if (!sessionId) {
      navigate("/login");
      return;
    }

    try {
      const res = await fetch(`${API_BASE_URL}/sales/accounts`, {
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
      if (!res.ok) throw new Error(data.detail || "Failed to load accounts");
      // Map sales accounts to UI format
      const mappedAccounts = (Array.isArray(data) ? data : []).map(apiAccountToUIAccount);
      setAccounts(mappedAccounts);
    } catch (e) {
      setError(e.message || "Failed to load accounts");
    }
  };

  // Fetch accounts on mount
  useEffect(() => {
    fetchAccounts();
  }, [navigate]);

  // Refresh data when window/tab gains focus (user returns from another page)
  useEffect(() => {
    const handleFocus = () => {
      fetchAccounts();
    };
    
    window.addEventListener('focus', handleFocus);
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') {
        fetchAccounts();
      }
    });
    
    return () => {
      window.removeEventListener('focus', handleFocus);
      document.removeEventListener('visibilitychange', handleFocus);
    };
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
  const openEdit = (account) => {
    setEditingId(account._id)
    setFormData({
      name: account.name || "",
      contactPerson: account.contactPerson || "",
      email: account.email || "",
      phone: account.phone || "",
      address: account.address || "",
      accountValue: account.accountValue || "",
      status: account.status || "Active",
    })
    setShowForm(true)
  }

  // Create or Update account - now uses finance customers API
  const saveAccount = async () => {
    // Validate required fields
    if (!formData.name || !formData.name.trim()) {
      setError("❌ Account Name is required");
      return;
    }
    if (!formData.email || !formData.email.trim()) {
      setError("❌ Email Address is required");
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
      // Convert account form data to Sales Accounts API format
      const payload = uiAccountToAPIAccount(formData);

      const url = editingId
        ? `${API_BASE_URL}/sales/accounts/${editingId}`
        : `${API_BASE_URL}/sales/accounts`;
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

      if (!res.ok) throw new Error(data.detail || "Failed to save account");

      // Refresh the list to get updated data
      await fetchAccounts();

      setShowForm(false);
      setEditingId(null);
      setFormData(emptyForm);
    } catch (e) {
      setError(e.message || "Save failed");
    } finally {
      setLoading(false);
    }
  };

  // Delete account - uses Sales Accounts API
  const deleteAccount = async (id) => {
    if (!window.confirm("Delete this account?")) return;

    const sessionId = localStorage.getItem("session_id");
    if (!sessionId) {
      navigate("/login");
      return;
    }

    try {
      const res = await fetch(`${API_BASE_URL}/sales/accounts/${id}`, {
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
      if (!res.ok) throw new Error(data.detail || "Failed to delete account");

      setAccounts((prev) => prev.filter((a) => a._id !== id));
    } catch (e) {
      setError(e.message || "Delete failed");
    }
  };

  // Bulk delete accounts
  const bulkDeleteAccounts = async () => {
    if (selectedIds.length === 0) return;
    if (!window.confirm(`Delete ${selectedIds.length} selected accounts?`)) return;

    const sessionId = localStorage.getItem("session_id");
    if (!sessionId) {
      navigate("/login");
      return;
    }

    try {
      // Delete accounts one by one
      let deletedCount = 0;
      for (const id of selectedIds) {
        const res = await fetch(`${API_BASE_URL}/sales/accounts/${id}`, {
          method: "DELETE",
          headers: {
            "Content-Type": "application/json",
            Authorization: sessionId,
          },
        });
        if (res.ok) {
          deletedCount++;
        }
      }

      setAccounts((prev) => prev.filter((a) => !selectedIds.includes(a._id)));
      setSelectedIds([]);
      alert(`✅ ${deletedCount} accounts deleted successfully!`);
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
    const currentPageIds = paginatedAccounts.map((a) => a._id);
    const allSelected = currentPageIds.every((id) => selectedIds.includes(id));
    if (allSelected) {
      setSelectedIds((prev) => prev.filter((id) => !currentPageIds.includes(id)));
    } else {
      setSelectedIds((prev) => [...new Set([...prev, ...currentPageIds])]);
    }
  };

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return accounts;
    return accounts.filter((a) =>
      ["name", "email", "contactPerson", "phone", "address"].some((field) =>
        String(a[field] || "").toLowerCase().includes(q)
      )
    );
  }, [accounts, search]);

  const totalPages = Math.ceil(filtered.length / recordsPerPage);
  const startIdx = (currentPage - 1) * recordsPerPage;
  const endIdx = startIdx + recordsPerPage;
  const paginatedAccounts = filtered.slice(startIdx, endIdx);

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
          <h2 style={styles.title}>Accounts</h2>
          <p style={styles.subtitle}>Manage customer accounts and relationship data</p>
        </div>
        <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
          {selectedIds.length > 0 && (
            <button 
              style={{ ...styles.btnPrimary, backgroundColor: '#dc2626' }} 
              onClick={bulkDeleteAccounts}
            >
              🗑️ Delete ({selectedIds.length})
            </button>
          )}
          <button 
            style={{ ...styles.btnSecondary, padding: '8px 16px' }} 
            onClick={fetchAccounts}
            title="Refresh to see latest changes from Clients and Customers"
          >
            🔄 Refresh
          </button>
          <button style={styles.btnPrimary} onClick={openCreate}>
            + Add New Account
          </button>
        </div>
      </div>

      {error && <div style={styles.errorAlert}>{error}</div>}

      {/* Search and Stats */}
      <div style={styles.searchSection}>
        <input
          style={styles.searchInput}
          type="text"
          placeholder="Search accounts by name, email, contact..."
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
          <span>Total: <strong>{accounts.length}</strong></span>
          <span>Active: <strong>{accounts.filter(a => a.status === "Active").length}</strong></span>
          <span>Inactive: <strong>{accounts.filter(a => a.status === "Inactive").length}</strong></span>
        </div>
      </div>

      {/* Accounts Table */}
      <div style={styles.tableContainer}>
        <table style={styles.table}>
          <thead style={styles.thead}>
            <tr>
              <th style={{...styles.th, width: '40px'}}>
                <input 
                  type="checkbox" 
                  checked={paginatedAccounts.length > 0 && paginatedAccounts.every(a => selectedIds.includes(a._id))}
                  onChange={toggleSelectAll}
                  style={{ cursor: 'pointer' }}
                />
              </th>
              <th style={styles.th}>Account Name</th>
              <th style={styles.th}>Primary Contact</th>
              <th style={styles.th}>Email</th>
              <th style={styles.th}>Phone</th>
              <th style={styles.th}>Status</th>
              <th style={styles.th}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {paginatedAccounts.map(account => (
              <tr 
                key={account._id} 
                style={{
                  ...styles.tr, 
                  cursor: 'pointer',
                  transition: 'background-color 0.15s',
                  backgroundColor: selectedIds.includes(account._id) ? '#eff6ff' : 'transparent'
                }}
                onMouseEnter={(e) => { if (!selectedIds.includes(account._id)) e.currentTarget.style.backgroundColor = '#f9fafb' }}
                onMouseLeave={(e) => { if (!selectedIds.includes(account._id)) e.currentTarget.style.backgroundColor = 'transparent' }}
                onClick={() => navigate(`/admin/sales/account/${encodeURIComponent(account.name)}`)}
                title="Click to view all contacts from this company"
              >
                <td style={styles.td} onClick={(e) => e.stopPropagation()}>
                  <input 
                    type="checkbox" 
                    checked={selectedIds.includes(account._id)}
                    onChange={() => toggleSelect(account._id)}
                    style={{ cursor: 'pointer' }}
                  />
                </td>
                <td style={styles.td}>
                  <strong>{account.name}</strong>
                </td>
                <td style={styles.td}>{account.contactPerson || '-'}</td>
                <td style={styles.td}>{account.email}</td>
                <td style={styles.td}>{account.phone || '-'}</td>
                <td style={styles.td}>
                  <span style={{
                    ...styles.statusBadge,
                    ...(account.status === 'Active' ? styles.statusActive : styles.statusInactive)
                  }}>
                    {account.status || "Active"}
                  </span>
                </td>
                <td style={styles.td} onClick={(e) => e.stopPropagation()}>
                  <div style={styles.actionButtons}>
                    <button style={styles.btnEdit} onClick={() => openEdit(account)}>✏️</button>
                    <button style={styles.btnDelete} onClick={() => deleteAccount(account._id)}>🗑️</button>
                  </div>
                </td>
              </tr>
            ))}
            {paginatedAccounts.length === 0 && filtered.length === 0 && (
              <tr>
                <td colSpan={7} style={styles.emptyState}>
                  No accounts found.
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
              <h3 style={styles.modalTitle}>{editingId ? "Edit Account" : "Add New Account"}</h3>
              <button style={styles.closeBtn} onClick={() => setShowForm(false)}>×</button>
            </div>

            <div style={styles.modalBody}>
              <div style={styles.formGroup}>
                <label style={styles.label}>Account Name <span style={styles.required}>*</span></label>
                <input
                  style={styles.input}
                  name="name"
                  placeholder="Enter account name"
                  value={formData.name}
                  onChange={handleChange}
                />
              </div>

              <div style={styles.formGroup}>
                <label style={styles.label}>Primary Contact</label>
                <input
                  style={styles.input}
                  name="contactPerson"
                  placeholder="Enter contact person name"
                  value={formData.contactPerson}
                  onChange={handleChange}
                />
              </div>

              <div style={styles.formGroup}>
                <label style={styles.label}>Email Address <span style={styles.required}>*</span></label>
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
                <label style={styles.label}>Phone Number</label>
                <input
                  style={styles.input}
                  name="phone"
                  placeholder="Enter phone number"
                  value={formData.phone}
                  onChange={handleChange}
                />
              </div>

              <div style={styles.formGroup}>
                <label style={styles.label}>Address</label>
                <input
                  style={styles.input}
                  name="address"
                  placeholder="Enter address"
                  value={formData.address}
                  onChange={handleChange}
                />
              </div>

              <div style={styles.formGroup}>
                <label style={styles.label}>Account Value</label>
                <input
                  style={styles.input}
                  name="accountValue"
                  placeholder="Enter account value (optional)"
                  value={formData.accountValue}
                  onChange={handleChange}
                />
              </div>

              <div style={styles.formGroup}>
                <label style={styles.label}>Status</label>
                <select
                  style={styles.select}
                  name="status"
                  value={formData.status}
                  onChange={handleChange}
                >
                  <option>Active</option>
                  <option>Inactive</option>
                  <option>Pending</option>
                  <option>Negotiating</option>
                </select>
              </div>
            </div>

            <div style={styles.modalFooter}>
              <button style={styles.btnCancel} onClick={() => setShowForm(false)} disabled={loading}>
                Cancel
              </button>
              <button style={styles.btnSave} onClick={saveAccount} disabled={loading}>
                {loading ? "Saving..." : editingId ? "Save Changes" : "Add Account"}
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
    maxWidth: '600px',
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

export default Account
