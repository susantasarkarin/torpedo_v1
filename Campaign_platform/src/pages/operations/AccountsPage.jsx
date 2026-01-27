import React, { useState, useEffect } from "react";
import { API_BASE_URL as API_URL } from "../../config";
import "./AccountsPage.css";
import { buildApiUrl } from "../../config"

function AccountsPage() {
  const [accounts, setAccounts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [editingAccount, setEditingAccount] = useState(null);
  const [syncing, setSyncing] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");
  const [filterType, setFilterType] = useState("");
  const [formData, setFormData] = useState({
    name: "",
    account_type: "client",
    status: "active",
    email: "",
    phone: "",
    primary_contact: "",
    industry: "",
    gst_treatment: "unregistered",
    gstin: "",
    pan: "",
    payment_terms: 30,
    currency: "INR",
    notes: "",
  });

  const token = sessionStorage.getItem("session_token");

  useEffect(() => {
    fetchAccounts();
  }, [filterType]);

  const fetchAccounts = async () => {
    setLoading(true);
    try {
      let url = buildApiUrl(`/operations/accounts/`);
      const params = new URLSearchParams();
      if (filterType) params.append("account_type", filterType);
      if (params.toString()) url += `?${params.toString()}`;

      const res = await fetch(url, {
        headers: { Authorization: token },
      });
      if (res.ok) {
        const data = await res.json();
        setAccounts(data.accounts || []);
      }
    } catch (err) {
      console.error("Error fetching accounts:", err);
    } finally {
      setLoading(false);
    }
  };

  const handleSyncFromClients = async () => {
    setSyncing(true);
    try {
      const res = await fetch(buildApiUrl(`/operations/accounts/sync-from-clients`), {
        method: "POST",
        headers: { Authorization: token },
      });
      if (res.ok) {
        const data = await res.json();
        alert(`Synced ${data.synced} new accounts, skipped ${data.skipped} existing`);
        fetchAccounts();
      }
    } catch (err) {
      console.error("Error syncing accounts:", err);
      alert("Error syncing accounts");
    } finally {
      setSyncing(false);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      const url = editingAccount
        ? buildApiUrl(`/operations/accounts/${editingAccount._id}`)
        : buildApiUrl(`/operations/accounts/`);
      const method = editingAccount ? "PUT" : "POST";

      const res = await fetch(url, {
        method,
        headers: {
          "Content-Type": "application/json",
          Authorization: token,
        },
        body: JSON.stringify(formData),
      });

      if (res.ok) {
        setShowModal(false);
        setEditingAccount(null);
        resetForm();
        fetchAccounts();
      } else {
        const data = await res.json();
        alert(data.detail || "Error saving account");
      }
    } catch (err) {
      console.error("Error saving account:", err);
      alert("Error saving account");
    }
  };

  const handleLinkToCustomer = async (accountId) => {
    try {
      const res = await fetch(buildApiUrl(`/operations/accounts/${accountId}/link-customer`), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: token,
        },
        body: JSON.stringify({}),
      });

      if (res.ok) {
        const data = await res.json();
        alert(`Account linked to customer: ${data.customer_id}`);
        fetchAccounts();
      } else {
        const data = await res.json();
        alert(data.detail || "Error linking account");
      }
    } catch (err) {
      console.error("Error linking account:", err);
    }
  };

  const resetForm = () => {
    setFormData({
      name: "",
      account_type: "client",
      status: "active",
      email: "",
      phone: "",
      primary_contact: "",
      industry: "",
      gst_treatment: "unregistered",
      gstin: "",
      pan: "",
      payment_terms: 30,
      currency: "INR",
      notes: "",
    });
  };

  const openEditModal = (account) => {
    setEditingAccount(account);
    setFormData({
      name: account.name || "",
      account_type: account.account_type || "client",
      status: account.status || "active",
      email: account.email || "",
      phone: account.phone || "",
      primary_contact: account.primary_contact || "",
      industry: account.industry || "",
      gst_treatment: account.gst_treatment || "unregistered",
      gstin: account.gstin || "",
      pan: account.pan || "",
      payment_terms: account.payment_terms || 30,
      currency: account.currency || "INR",
      notes: account.notes || "",
    });
    setShowModal(true);
  };

  const filteredAccounts = accounts.filter((acc) =>
    acc.name?.toLowerCase().includes(searchTerm.toLowerCase()) ||
    acc.email?.toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <div className="accounts-page">
      <div className="page-header">
        <div>
          <h1>Unified Accounts</h1>
          <p>Manage clients and customers across Operations and Finance</p>
        </div>
        <div className="header-actions">
          <button
            className="btn btn-secondary"
            onClick={handleSyncFromClients}
            disabled={syncing}
          >
            {syncing ? "Syncing..." : "🔄 Sync from Projects"}
          </button>
          <button
            className="btn btn-primary"
            onClick={() => {
              resetForm();
              setEditingAccount(null);
              setShowModal(true);
            }}
          >
            + New Account
          </button>
        </div>
      </div>

      <div className="filters-bar">
        <input
          type="text"
          placeholder="Search accounts..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          className="search-input"
        />
        <select
          value={filterType}
          onChange={(e) => setFilterType(e.target.value)}
          className="filter-select"
        >
          <option value="">All Types</option>
          <option value="client">Clients</option>
          <option value="customer">Customers</option>
          <option value="vendor">Vendors</option>
          <option value="both">Both</option>
        </select>
      </div>

      {loading ? (
        <div className="loading">Loading accounts...</div>
      ) : (
        <div className="accounts-table-container">
          <table className="accounts-table">
            <thead>
              <tr>
                <th>Account</th>
                <th>Type</th>
                <th>Status</th>
                <th>Contact</th>
                <th>Projects</th>
                <th>Invoiced</th>
                <th>Receivables</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredAccounts.length === 0 ? (
                <tr>
                  <td colSpan="8" className="empty-state">
                    No accounts found. Click "Sync from Projects" to import clients.
                  </td>
                </tr>
              ) : (
                filteredAccounts.map((account) => (
                  <tr key={account._id}>
                    <td>
                      <div className="account-name">
                        <strong>{account.name}</strong>
                        {account.account_number && (
                          <span className="account-number">{account.account_number}</span>
                        )}
                      </div>
                    </td>
                    <td>
                      <span className={`type-badge ${account.account_type}`}>
                        {account.account_type}
                      </span>
                    </td>
                    <td>
                      <span className={`status-badge ${account.status}`}>
                        {account.status}
                      </span>
                    </td>
                    <td>
                      <div className="contact-info">
                        {account.email && <div>{account.email}</div>}
                        {account.phone && <div>{account.phone}</div>}
                      </div>
                    </td>
                    <td>
                      <span className="metric">
                        {account.active_projects || 0} / {account.total_projects || 0}
                      </span>
                    </td>
                    <td>
                      <span className="metric">
                        ₹{(account.total_invoiced || 0).toLocaleString()}
                      </span>
                    </td>
                    <td>
                      <span className={`metric ${account.total_receivables > 0 ? 'warning' : ''}`}>
                        ₹{(account.total_receivables || 0).toLocaleString()}
                      </span>
                    </td>
                    <td>
                      <div className="action-buttons">
                        <button
                          className="btn-icon"
                          onClick={() => openEditModal(account)}
                          title="Edit"
                        >
                          ✏️
                        </button>
                        {!account.finance_customer_id && (
                          <button
                            className="btn-icon"
                            onClick={() => handleLinkToCustomer(account._id)}
                            title="Link to Finance Customer"
                          >
                            🔗
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Modal */}
      {showModal && (
        <div className="modal-overlay" onClick={() => setShowModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>{editingAccount ? "Edit Account" : "New Account"}</h2>
              <button className="modal-close" onClick={() => setShowModal(false)}>
                ✕
              </button>
            </div>
            <form onSubmit={handleSubmit} className="account-form">
              <div className="form-row">
                <div className="form-group">
                  <label>Account Name *</label>
                  <input
                    type="text"
                    value={formData.name}
                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                    required
                  />
                </div>
                <div className="form-group">
                  <label>Type</label>
                  <select
                    value={formData.account_type}
                    onChange={(e) => setFormData({ ...formData, account_type: e.target.value })}
                  >
                    <option value="client">Client (Operations)</option>
                    <option value="customer">Customer (Finance)</option>
                    <option value="vendor">Vendor</option>
                    <option value="both">Both</option>
                  </select>
                </div>
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label>Email</label>
                  <input
                    type="email"
                    value={formData.email}
                    onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                  />
                </div>
                <div className="form-group">
                  <label>Phone</label>
                  <input
                    type="text"
                    value={formData.phone}
                    onChange={(e) => setFormData({ ...formData, phone: e.target.value })}
                  />
                </div>
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label>Primary Contact</label>
                  <input
                    type="text"
                    value={formData.primary_contact}
                    onChange={(e) => setFormData({ ...formData, primary_contact: e.target.value })}
                  />
                </div>
                <div className="form-group">
                  <label>Industry</label>
                  <input
                    type="text"
                    value={formData.industry}
                    onChange={(e) => setFormData({ ...formData, industry: e.target.value })}
                  />
                </div>
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label>GST Treatment</label>
                  <select
                    value={formData.gst_treatment}
                    onChange={(e) => setFormData({ ...formData, gst_treatment: e.target.value })}
                  >
                    <option value="unregistered">Unregistered</option>
                    <option value="registered_regular">Registered - Regular</option>
                    <option value="registered_composition">Registered - Composition</option>
                    <option value="overseas">Overseas</option>
                    <option value="sez">SEZ</option>
                  </select>
                </div>
                <div className="form-group">
                  <label>GSTIN</label>
                  <input
                    type="text"
                    value={formData.gstin}
                    onChange={(e) => setFormData({ ...formData, gstin: e.target.value.toUpperCase() })}
                    maxLength={15}
                  />
                </div>
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label>Payment Terms (Days)</label>
                  <input
                    type="number"
                    value={formData.payment_terms}
                    onChange={(e) => setFormData({ ...formData, payment_terms: parseInt(e.target.value) || 30 })}
                  />
                </div>
                <div className="form-group">
                  <label>Status</label>
                  <select
                    value={formData.status}
                    onChange={(e) => setFormData({ ...formData, status: e.target.value })}
                  >
                    <option value="active">Active</option>
                    <option value="inactive">Inactive</option>
                    <option value="prospect">Prospect</option>
                  </select>
                </div>
              </div>

              <div className="form-group">
                <label>Notes</label>
                <textarea
                  value={formData.notes}
                  onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
                  rows={3}
                />
              </div>

              <div className="form-actions">
                <button type="button" className="btn btn-secondary" onClick={() => setShowModal(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary">
                  {editingAccount ? "Update Account" : "Create Account"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

export default AccountsPage;
