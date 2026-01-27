"use client"
import { useEffect, useMemo, useState } from "react"
import { useLocation, useNavigate } from "react-router-dom"
import { API_BASE_URL } from "../../config"
import { buildApiUrl } from "../../config"

// Helper functions to map between client UI format and customer API format
const customerToClient = (customer) => ({
  _id: customer._id,
  clientNo: customer._id?.substring(0, 7) || 'N/A',  // Use first 7 chars of _id as clientNo
  name: customer.company_name || customer.name || "",
  contactPerson: customer.phone || "",
  email: customer.email || "",
  address: customer.billing_address?.line1 || "",
  clientVariable: customer.notes || "",
  currency: customer.currency || "INR",
  clientType: customer.customer_type === "business" ? "Offline" : customer.customer_type === "api" ? "API" : "Online",
  status: customer.status === "active" ? "Active" : "Inactive",
  linked_contacts: customer.linked_contacts || [],
  linked_contacts_count: customer.linked_contacts_count || 0,
});

const clientToCustomer = (clientData) => ({
  name: clientData.name,
  customer_type: clientData.clientType === "Offline" ? "business" : clientData.clientType === "API" ? "api" : "individual",
  company_name: clientData.name,
  email: clientData.email,
  phone: clientData.contactPerson,
  gst_treatment: "unregistered",
  gstin: "",
  pan: "",
  billing_address: {
    line1: clientData.address || "",
    line2: "",
    city: "",
    state: "",
    pincode: "",
    country: "India",
  },
  shipping_address: {
    line1: clientData.address || "",
    line2: "",
    city: "",
    state: "",
    pincode: "",
    country: "India",
  },
  same_as_billing: true,
  payment_terms: 30,
  credit_limit: 0,
  currency: clientData.currency || "INR",
  opening_balance: 0,
  notes: clientData.clientVariable || "",
  status: clientData.status === "Active" ? "active" : "inactive",
});

function ClientsPage() {
   const navigate = useNavigate();
  const [clients, setClients] = useState([])
  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [search, setSearch] = useState("")
  const [currentPage, setCurrentPage] = useState(1)
  const [recordsPerPage, setRecordsPerPage] = useState(10)
  
  // Sales accounts for linking
  const [salesAccounts, setSalesAccounts] = useState([])
  const [clientAccountLinks, setClientAccountLinks] = useState({}) // Maps client_id -> sales_account_id

  const emptyForm = {
    name: "",
    contactPerson: "",
    email: "",
    address: "",
    clientVariable: "",
    currency: "",
    clientType: "Offline",
    status: "Active",
  }
  const [formData, setFormData] = useState(emptyForm)

  // Fetch clients function - now uses finance customers API
  const fetchClients = async () => {
    const sessionId = localStorage.getItem("session_id");
    if (!sessionId) {
      navigate("/login");
      return;
    }

    try {
      const res = await fetch(buildApiUrl(`/finance/finance/customers/`), {
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
      if (!res.ok) throw new Error(data.detail || "Failed to load clients");
      // Map customers to client format for UI
      const mappedClients = (Array.isArray(data) ? data : data.customers || []).map(customerToClient);
      setClients(mappedClients);
    } catch (e) {
      setError(e.message || "Failed to load clients");
    }
  };

  // Fetch on mount
  useEffect(() => {
    fetchClients();
    fetchSalesAccounts();
  }, []);

  // Fetch sales accounts for linking dropdown
  const fetchSalesAccounts = async () => {
    try {
      const res = await fetch(buildApiUrl(`/sales/accounts`));
      if (res.ok) {
        const data = await res.json();
        setSalesAccounts(data || []);
        
        // Build a map of client links from sales accounts
        const links = {};
        (data || []).forEach(acc => {
          if (acc.linked_operations_client_id) {
            links[acc.linked_operations_client_id] = acc._id;
          }
        });
        setClientAccountLinks(links);
      }
    } catch (e) {
      console.error("Failed to fetch sales accounts:", e);
    }
  };

  // Handle linking a client to a sales account
  const handleLinkSalesAccount = async (clientId, salesAccountId) => {
    try {
      if (!salesAccountId) {
        // Unlink: find the current sales account and remove the link
        const currentAccountId = clientAccountLinks[clientId];
        if (currentAccountId) {
          await fetch(buildApiUrl(`/sales/accounts/${currentAccountId}/unlink-operations-client`), {
            method: "DELETE"
          });
          setClientAccountLinks(prev => {
            const updated = {...prev};
            delete updated[clientId];
            return updated;
          });
        }
      } else {
        // First unlink from any previous account
        const currentAccountId = clientAccountLinks[clientId];
        if (currentAccountId && currentAccountId !== salesAccountId) {
          await fetch(buildApiUrl(`/sales/accounts/${currentAccountId}/unlink-operations-client`), {
            method: "DELETE"
          });
        }
        
        // Link to new account
        await fetch(buildApiUrl(`/sales/accounts/${salesAccountId}/link-operations-client`), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ client_id: clientId })
        });
        
        setClientAccountLinks(prev => ({...prev, [clientId]: salesAccountId}));
      }
    } catch (e) {
      console.error("Failed to link sales account:", e);
      setError("Failed to update sales account link");
    }
  };

  // Auto-refresh when window regains focus or tab becomes visible
  useEffect(() => {
    const handleFocus = () => {
      console.log('Window focused, refreshing clients...');
      fetchClients();
    };

    const handleVisibilityChange = () => {
      if (!document.hidden) {
        console.log('Tab visible, refreshing clients...');
        fetchClients();
      }
    };

    window.addEventListener('focus', handleFocus);
    document.addEventListener('visibilitychange', handleVisibilityChange);

    return () => {
      window.removeEventListener('focus', handleFocus);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, []);


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
  const openEdit = (c) => {
    setEditingId(c._id)
    setFormData({
      clientNo: c.clientNo || "",
      name: c.name || "",
      contactPerson: c.contactPerson || "",
      email: c.email || "",
      address: c.address || "",
      clientVariable: c.clientVariable || "",
      currency: c.currency || "",
      clientType: c.clientType || "Offline",
      status: c.status || "Active",
    })
    setShowForm(true)
  }

  // Create or Update client - now uses finance customers API
  const saveClient = async () => {
    // Validate required fields
    if (!formData.name || !formData.name.trim()) {
      setError("❌ Client Name is required");
      return;
    }
    if (!formData.email || !formData.email.trim()) {
      setError("❌ Email Address is required");
      return;
    }
    if (!formData.contactPerson || !formData.contactPerson.trim()) {
      setError("❌ Phone Number is required");
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
      // Convert client form data to customer API format
      const payload = clientToCustomer(formData);

      const url = editingId
        ? buildApiUrl(`/finance/finance/customers/${editingId}`)
        : buildApiUrl(`/finance/finance/customers/`);
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

      if (!res.ok) throw new Error(data.detail || "Failed to save client");

      // Refresh the list to get updated data
      await fetchClients();

      setShowForm(false);
      setEditingId(null);
      setFormData(emptyForm);
    } catch (e) {
      setError(e.message || "Save failed");
    } finally {
      setLoading(false);
    }
  };

  // Delete client - now uses finance customers API
  const deleteClient = async (id) => {
    if (!window.confirm("Delete this client?")) return;

    const sessionId = localStorage.getItem("session_id");
    if (!sessionId) {
      navigate("/login");
      return;
    }

    try {
      const res = await fetch(buildApiUrl(`/finance/finance/customers/${id}`), {
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
      if (!res.ok) throw new Error(data.detail || "Failed to delete client");

      setClients((prev) => prev.filter((c) => c._id !== id));
    } catch (e) {
      setError(e.message || "Delete failed");
    }
  };

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return clients;
    return clients.filter((c) =>
      ["clientNo", "name", "email", "contactPerson", "address", "clientVariable"].some((field) =>
        String(c[field] || "").toLowerCase().includes(q)
      )
    );
  }, [clients, search]);

  const totalPages = Math.ceil(filtered.length / recordsPerPage);
  const startIdx = (currentPage - 1) * recordsPerPage;
  const endIdx = startIdx + recordsPerPage;
  const paginatedClients = filtered.slice(startIdx, endIdx);

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
          <h2 style={styles.title}>Clients</h2>
          <p style={styles.subtitle}>Manage your survey clients and their information</p>
        </div>
        <div style={{ display: 'flex', gap: '10px' }}>
          <button 
            style={{ ...styles.btnSecondary, padding: '8px 16px' }} 
            onClick={fetchClients}
            title="Refresh to see latest changes from Accounts and Customers"
          >
            🔄 Refresh
          </button>
          <button style={styles.btnPrimary} onClick={openCreate}>
            + Add New Client
          </button>
        </div>
      </div>

      {error && <div style={styles.errorAlert}>{error}</div>}

      {/* Search and Stats */}
      <div style={styles.searchSection}>
        <input
          style={styles.searchInput}
          type="text"
          placeholder="Search clients by number, name, email..."
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
          <span>Total: <strong>{clients.length}</strong></span>
          <span>Active: <strong>{clients.filter(c => c.status === "Active").length}</strong></span>
          <span>Inactive: <strong>{clients.filter(c => c.status === "Inactive").length}</strong></span>
        </div>
      </div>

      {/* Clients Table */}
      <div style={styles.tableContainer}>
        <table style={styles.table}>
          <thead style={styles.thead}>
            <tr>
              <th style={styles.th}>Client No</th>
              <th style={styles.th}>Client Name</th>
              <th style={styles.th}>Email</th>
              <th style={styles.th}>Phone</th>
              <th style={styles.th}>Contacts</th>
              <th style={styles.th}>Status</th>
              <th style={styles.th}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {paginatedClients.map(c => (
              <tr key={c._id} style={styles.tr}>
                <td style={styles.td}>
                  <span style={styles.clientNo}>{c.clientNo || 'N/A'}</span>
                </td>
                <td style={styles.td}>{c.name}</td>
                <td style={styles.td}>{c.email}</td>
                <td style={styles.td}>{c.contactPerson}</td>
                <td style={styles.td}>
                  {c.linked_contacts_count > 0 ? (
                    <span 
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '4px',
                        padding: '4px 8px',
                        background: '#e0f2fe',
                        color: '#0369a1',
                        borderRadius: '12px',
                        fontSize: '12px',
                        fontWeight: '500',
                        cursor: 'pointer',
                      }}
                      onClick={() => navigate('/admin/sales/contacts')}
                      title={c.linked_contacts.map(ct => ct.name || ct.email).join(', ')}
                    >
                      👤 {c.linked_contacts_count} contact{c.linked_contacts_count > 1 ? 's' : ''}
                    </span>
                  ) : (
                    <span style={{ color: '#9ca3af', fontSize: '12px' }}>—</span>
                  )}
                </td>
                <td style={styles.td}>
                  <span style={{
                    ...styles.statusBadge,
                    ...(c.status === 'Active' ? styles.statusActive : styles.statusInactive)
                  }}>
                    {c.status || "Active"}
                  </span>
                </td>
                <td style={styles.td}>
                  <div style={styles.actionButtons}>
                    <button style={styles.btnEdit} onClick={() => openEdit(c)}>✏️</button>
                    <button style={styles.btnDelete} onClick={() => deleteClient(c._id)}>🗑️</button>
                  </div>
                </td>
              </tr>
            ))}
            {paginatedClients.length === 0 && filtered.length === 0 && (
              <tr>
                <td colSpan={7} style={styles.emptyState}>
                  No clients found.
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
              <h3 style={styles.modalTitle}>{editingId ? "Edit Client" : "Add New Client"}</h3>
              <button style={styles.closeBtn} onClick={() => setShowForm(false)}>×</button>
            </div>

            <div style={styles.modalBody}>
              {editingId && formData.clientNo && (
                <div style={styles.formGroup}>
                  <label style={styles.label}>Client No</label>
                  <input
                    style={{...styles.input, backgroundColor: '#f3f4f6', cursor: 'not-allowed'}}
                    value={formData.clientNo}
                    disabled
                    readOnly
                  />
                </div>
              )}

              <div style={styles.formGroup}>
                <label style={styles.label}>Client Name <span style={styles.required}>*</span></label>
                <input
                  style={styles.input}
                  name="name"
                  placeholder="Enter client name"
                  value={formData.name}
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
                <label style={styles.label}>Phone Number <span style={styles.required}>*</span></label>
                <input
                  style={styles.input}
                  name="contactPerson"
                  placeholder="Enter phone number"
                  value={formData.contactPerson}
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
                <label style={styles.label}>Client Variable</label>
                <input
                  style={styles.input}
                  name="clientVariable"
                  placeholder="Enter client variable"
                  value={formData.clientVariable}
                  onChange={handleChange}
                />
              </div>

              <div style={styles.formGroup}>
                <label style={styles.label}>Currency</label>
                <input
                  style={styles.input}
                  name="currency"
                  placeholder="Enter currency (e.g., USD, EUR)"
                  value={formData.currency}
                  onChange={handleChange}
                />
              </div>

              <div style={styles.formRow}>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Client Type</label>
                  <select
                    style={styles.select}
                    name="clientType"
                    value={formData.clientType}
                    onChange={handleChange}
                  >
                    <option>Offline</option>
                    <option>Online</option>
                    <option>API</option>
                  </select>
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
                  </select>
                </div>
              </div>

              {editingId && (
                <div style={styles.formGroup}>
                  <label style={styles.label}>Sales Account</label>
                  <select
                    style={styles.select}
                    value={clientAccountLinks[editingId] || ""}
                    onChange={(e) => handleLinkSalesAccount(editingId, e.target.value)}
                    title="Link to Sales Account"
                  >
                    <option value="">-- Select Sales Account --</option>
                    {salesAccounts.map(acc => (
                      <option key={acc._id} value={acc._id}>
                        {acc.account_name || acc.company_name || 'Unnamed'}
                      </option>
                    ))}
                  </select>
                </div>
              )}
            </div>

            <div style={styles.modalFooter}>
              <button style={styles.btnCancel} onClick={() => setShowForm(false)} disabled={loading}>
                Cancel
              </button>
              <button style={styles.btnSave} onClick={saveClient} disabled={loading}>
                {loading ? "Saving..." : editingId ? "Save Changes" : "Add Client"}
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
  clientNo: {
    fontWeight: '600',
    color: '#059669',
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
  linkSelect: {
    padding: '0.4rem 0.6rem',
    border: '1px solid #d1d5db',
    borderRadius: '0.375rem',
    fontSize: '0.85rem',
    backgroundColor: 'white',
    cursor: 'pointer',
    minWidth: '160px',
    color: '#374151',
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

export default ClientsPage