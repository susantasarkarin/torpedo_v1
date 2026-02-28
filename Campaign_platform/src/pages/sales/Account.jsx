/**
 * Accounts Page - Sales Pipeline
 * Redesigned to match AI Database styling
 */
"use client"
import { useEffect, useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
import { API_BASE_URL } from "../../config"
import "./Account.css"
import "../../styles/SalesPages.css"
import { buildApiUrl } from "../../config"

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
      const res = await fetch(buildApiUrl(`/api/sales/accounts`), {
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

  // Refresh data when window/tab gains focus
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

  // Create or Update account
  const saveAccount = async () => {
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
      const payload = uiAccountToAPIAccount(formData);

      const url = editingId
        ? buildApiUrl(`/api/sales/accounts/${editingId}`)
        : buildApiUrl(`/api/sales/accounts`);
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

  // Delete account
  const deleteAccount = async (id) => {
    if (!window.confirm("Delete this account?")) return;

    const sessionId = localStorage.getItem("session_id");
    if (!sessionId) {
      navigate("/login");
      return;
    }

    try {
      const res = await fetch(buildApiUrl(`/api/sales/accounts/${id}`), {
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
      let deletedCount = 0;
      for (const id of selectedIds) {
        const res = await fetch(buildApiUrl(`/api/sales/accounts/${id}`), {
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
    <div className="sales-page">
      {/* Page Header */}
      <div className="page-header">
        <div className="header-left">
          <h1>Accounts</h1>
          <p className="subtitle">Manage customer accounts and relationship data</p>
        </div>
        <div className="header-actions">
          {selectedIds.length > 0 && (
            <button className="btn btn-danger" onClick={bulkDeleteAccounts}>
              🗑️ Delete ({selectedIds.length})
            </button>
          )}
          <button className="btn btn-outline" onClick={fetchAccounts} title="Refresh to see latest changes">
            🔄 Refresh
          </button>
          <button className="btn btn-primary" onClick={openCreate}>
            + Add New Account
          </button>
        </div>
      </div>

      {error && <div className="error-alert">{error}</div>}

      {/* Stats Row */}
      <div className="stats-row">
        <div className="stat-card primary">
          <div className="stat-value">{accounts.length}</div>
          <div className="stat-label">Total Accounts</div>
        </div>
        <div className="stat-card success">
          <div className="stat-value">{accounts.filter(a => a.status === "Active").length}</div>
          <div className="stat-label">✓ Active</div>
        </div>
        <div className="stat-card danger">
          <div className="stat-value">{accounts.filter(a => a.status === "Inactive").length}</div>
          <div className="stat-label">✗ Inactive</div>
        </div>
      </div>

      {/* Filters Bar */}
      <div className="filters-bar">
        <input
          className="search-input"
          type="text"
          placeholder="Search accounts by name, email, contact..."
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

      {/* Accounts Table */}
      <div className="table-container">
        <table className="data-table">
          <thead>
            <tr>
              <th className="checkbox-col">
                <input 
                  type="checkbox" 
                  checked={paginatedAccounts.length > 0 && paginatedAccounts.every(a => selectedIds.includes(a._id))}
                  onChange={toggleSelectAll}
                />
              </th>
              <th>Account Name</th>
              <th>Primary Contact</th>
              <th>Email</th>
              <th>Phone</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {paginatedAccounts.map(account => (
              <tr 
                key={account._id} 
                className={selectedIds.includes(account._id) ? "selected" : ""}
              >
                <td className="checkbox-col" onClick={(e) => e.stopPropagation()}>
                  <input 
                    type="checkbox" 
                    checked={selectedIds.includes(account._id)}
                    onChange={() => toggleSelect(account._id)}
                  />
                </td>
                <td className="name-cell">
                  <span 
                    className="name-link"
                    onClick={() => navigate(`/admin/sales/account/${encodeURIComponent(account.name)}`)}
                    title="Click to view all contacts from this company"
                  >
                    {account.name}
                  </span>
                </td>
                <td>{account.contactPerson || '-'}</td>
                <td>{account.email}</td>
                <td>{account.phone || '-'}</td>
                <td>
                  <span className={`status-badge ${account.status === 'Active' ? 'active' : 'inactive'}`}>
                    {account.status || "Active"}
                  </span>
                </td>
                <td>
                  <div className="actions-cell">
                    <button 
                      className="action-btn edit"
                      onClick={(e) => { e.stopPropagation(); openEdit(account); }}
                    >
                      ✏️
                    </button>
                    <button 
                      className="action-btn delete"
                      onClick={(e) => { e.stopPropagation(); deleteAccount(account._id); }}
                    >
                      🗑️
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {paginatedAccounts.length === 0 && (
              <tr>
                <td colSpan={7} className="empty-state">
                  <h3>No accounts found</h3>
                  <p>Create a new account to get started.</p>
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
              <h3>{editingId ? "Edit Account" : "Add New Account"}</h3>
              <button className="modal-close-btn" onClick={() => setShowForm(false)}>×</button>
            </div>

            <div className="modal-body">
              <div className="form-group">
                <label className="form-label">Account Name <span className="required">*</span></label>
                <input
                  className="form-input"
                  name="name"
                  placeholder="Enter account name"
                  value={formData.name}
                  onChange={handleChange}
                />
              </div>

              <div className="form-group">
                <label className="form-label">Primary Contact</label>
                <input
                  className="form-input"
                  name="contactPerson"
                  placeholder="Enter contact person name"
                  value={formData.contactPerson}
                  onChange={handleChange}
                />
              </div>

              <div className="form-group">
                <label className="form-label">Email Address <span className="required">*</span></label>
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
                <label className="form-label">Phone Number</label>
                <input
                  className="form-input"
                  name="phone"
                  placeholder="Enter phone number"
                  value={formData.phone}
                  onChange={handleChange}
                />
              </div>

              <div className="form-group">
                <label className="form-label">Address</label>
                <input
                  className="form-input"
                  name="address"
                  placeholder="Enter address"
                  value={formData.address}
                  onChange={handleChange}
                />
              </div>

              <div className="form-group">
                <label className="form-label">Account Value</label>
                <input
                  className="form-input"
                  name="accountValue"
                  placeholder="Enter account value (optional)"
                  value={formData.accountValue}
                  onChange={handleChange}
                />
              </div>

              <div className="form-group">
                <label className="form-label">Status</label>
                <select
                  className="form-select"
                  name="status"
                  value={formData.status}
                  onChange={handleChange}
                >
                  <option value="Active">Active</option>
                  <option value="Inactive">Inactive</option>
                </select>
              </div>
            </div>

            <div className="modal-footer">
              <button className="btn btn-outline" onClick={() => setShowForm(false)}>Cancel</button>
              <button className="btn btn-primary" onClick={saveAccount} disabled={loading}>
                {loading ? "Saving..." : (editingId ? "Update Account" : "Add Account")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default Account
