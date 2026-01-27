import { useState, useEffect, useMemo } from "react";
import { API_BASE_URL as API_URL, buildApiUrl } from "../config";
import "./Operations.css";

const token = () => sessionStorage.getItem("session_token") || localStorage.getItem("session_id");

function Operations() {
  const [activeTab, setActiveTab] = useState("dashboard");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Dashboard data
  const [kpis, setKpis] = useState(null);
  const [recentActivity, setRecentActivity] = useState([]);

  // RFQ data
  const [rfqs, setRfqs] = useState([]);
  const [rfqStats, setRfqStats] = useState({ pending: 0, inProgress: 0, quoted: 0 });
  const [rfqSearch, setRfqSearch] = useState("");
  const [rfqStatusFilter, setRfqStatusFilter] = useState("");
  const [rfqPage, setRfqPage] = useState(1);

  // Projects data
  const [projects, setProjects] = useState([]);
  const [projectSearch, setProjectSearch] = useState("");
  const [projectStatusFilter, setProjectStatusFilter] = useState("");

  // Accounts data
  const [accounts, setAccounts] = useState([]);
  const [accountSearch, setAccountSearch] = useState("");

  // Vendor emails
  const [vendorEmails, setVendorEmails] = useState([]);

  useEffect(() => {
    fetchDashboardData();
    fetchRFQs();
    fetchProjects();
    fetchAccounts();
    fetchVendorEmails();
  }, []);

  // ==================== FETCH FUNCTIONS ====================

  const fetchDashboardData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [kpiRes, activityRes] = await Promise.all([
        fetch(buildApiUrl(`/operations/dashboard/kpis`), { headers: { Authorization: token() } }),
        fetch(buildApiUrl(`/operations/dashboard/recent-activity?limit=8`), { headers: { Authorization: token() } })
      ]);

      if (kpiRes.ok) setKpis(await kpiRes.json());
      if (activityRes.ok) {
        const data = await activityRes.json();
        setRecentActivity(data.activities || []);
      }
    } catch (err) {
      console.error("Dashboard error:", err);
      setError("Failed to load dashboard");
    } finally {
      setLoading(false);
    }
  };

  const fetchRFQs = async () => {
    try {
      const res = await fetch(buildApiUrl(`/rfq/?limit=100`), { headers: { Authorization: token() } });
      if (res.ok) {
        const data = await res.json();
        setRfqs(data.rfqs || []);
        // Calculate stats
        const pending = data.rfqs?.filter(r => r.status === "pending").length || 0;
        const inProgress = data.rfqs?.filter(r => r.status === "in_progress").length || 0;
        const quoted = data.rfqs?.filter(r => r.status === "quoted").length || 0;
        setRfqStats({ pending, inProgress, quoted });
      }
    } catch (err) {
      console.error("RFQ fetch error:", err);
    }
  };

  const fetchProjects = async () => {
    try {
      const res = await fetch(buildApiUrl(`/operations/projects/?limit=50`), { headers: { Authorization: token() } });
      if (res.ok) {
        const data = await res.json();
        setProjects(data.projects || []);
      }
    } catch (err) {
      console.error("Projects fetch error:", err);
    }
  };

  const fetchAccounts = async () => {
    try {
      const res = await fetch(buildApiUrl(`/operations/accounts/`), { headers: { Authorization: token() } });
      if (res.ok) {
        const data = await res.json();
        setAccounts(data.accounts || []);
      }
    } catch (err) {
      console.error("Accounts fetch error:", err);
    }
  };

  const fetchVendorEmails = async () => {
    try {
      const res = await fetch(buildApiUrl(`/unified-inbox/emails?category=vendor_communication&limit=10`), { headers: { Authorization: token() } });
      if (res.ok) {
        const data = await res.json();
        setVendorEmails(data.emails || []);
      }
    } catch (err) {
      console.error("Vendor emails fetch error:", err);
    }
  };

  // ==================== HELPERS ====================

  const formatCurrency = (num, currency = "INR") => {
    if (num === undefined || num === null) return "—";
    const symbols = { USD: "$", INR: "₹", EUR: "€", GBP: "£" };
    return `${symbols[currency] || ""}${Number(num).toLocaleString()}`;
  };

  const formatNumber = (num) => {
    if (num === undefined || num === null) return "—";
    return Number(num).toLocaleString();
  };

  const formatDate = (dateStr) => {
    if (!dateStr) return "—";
    const date = new Date(dateStr);
    return date.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
  };

  const formatTimeAgo = (dateStr) => {
    if (!dateStr) return "";
    const date = new Date(dateStr);
    const now = new Date();
    const diff = (now - date) / 1000;
    if (diff < 60) return "Just now";
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    if (diff < 604800) return `${Math.floor(diff / 86400)}d ago`;
    return formatDate(dateStr);
  };

  const getInitials = (name) => {
    if (!name) return "?";
    return name.split(" ").map(n => n[0]).join("").toUpperCase().slice(0, 2);
  };

  // ==================== FILTERED DATA ====================

  const filteredRfqs = useMemo(() => {
    return rfqs.filter(rfq => {
      const matchesSearch = !rfqSearch || 
        rfq.rfq_id?.toLowerCase().includes(rfqSearch.toLowerCase()) ||
        rfq.title?.toLowerCase().includes(rfqSearch.toLowerCase()) ||
        rfq.sender_name?.toLowerCase().includes(rfqSearch.toLowerCase()) ||
        rfq.contact_email?.toLowerCase().includes(rfqSearch.toLowerCase());
      const matchesStatus = !rfqStatusFilter || rfq.status === rfqStatusFilter;
      return matchesSearch && matchesStatus;
    });
  }, [rfqs, rfqSearch, rfqStatusFilter]);

  const filteredProjects = useMemo(() => {
    return projects.filter(proj => {
      const matchesSearch = !projectSearch ||
        proj.projectName?.toLowerCase().includes(projectSearch.toLowerCase()) ||
        proj.client?.toLowerCase().includes(projectSearch.toLowerCase());
      const matchesStatus = !projectStatusFilter || proj.projectStatus === projectStatusFilter;
      return matchesSearch && matchesStatus;
    });
  }, [projects, projectSearch, projectStatusFilter]);

  const filteredAccounts = useMemo(() => {
    return accounts.filter(acc => {
      return !accountSearch ||
        acc.name?.toLowerCase().includes(accountSearch.toLowerCase()) ||
        acc.email?.toLowerCase().includes(accountSearch.toLowerCase());
    });
  }, [accounts, accountSearch]);

  // ==================== RENDER TABS ====================

  const renderDashboard = () => {
    if (loading) {
      return (
        <div className="loading-container">
          <div className="loading-spinner"></div>
          <p style={{ marginTop: "1rem", color: "#6b7280" }}>Loading dashboard...</p>
        </div>
      );
    }

    const kpiCards = kpis ? [
      { 
        title: "Active Projects", 
        value: kpis.projects?.active || 0, 
        subtitle: `${kpis.projects?.total || 0} total`,
        icon: "📊",
        color: "#3b82f6",
        trend: kpis.projects?.growth_percent ? `${kpis.projects.growth_percent > 0 ? '+' : ''}${kpis.projects.growth_percent}%` : null,
        trendUp: (kpis.projects?.growth_percent || 0) > 0
      },
      { 
        title: "Pending RFQs", 
        value: rfqStats.pending, 
        subtitle: `${rfqStats.inProgress} in progress`,
        icon: "📋",
        color: "#f59e0b"
      },
      { 
        title: "Revenue", 
        value: formatCurrency(kpis.revenue?.total_invoiced || 0), 
        subtitle: `${formatCurrency(kpis.revenue?.total_outstanding || 0)} outstanding`,
        icon: "💰",
        color: "#10b981"
      },
      { 
        title: "Completion Rate", 
        value: `${kpis.traffic?.completion_rate || 0}%`, 
        subtitle: `${formatNumber(kpis.traffic?.completed || 0)} completes`,
        icon: "✅",
        color: "#8b5cf6"
      },
      { 
        title: "Clients", 
        value: kpis.clients?.total || 0, 
        subtitle: `${kpis.projects?.this_month || 0} new projects`,
        icon: "👥",
        color: "#ec4899"
      },
      { 
        title: "Collection Rate", 
        value: `${kpis.revenue?.collection_rate || 0}%`, 
        subtitle: `${formatCurrency(kpis.revenue?.total_received || 0)} received`,
        icon: "📈",
        color: "#06b6d4"
      },
    ] : [];

    const quickActions = [
      { icon: "📋", label: "New RFQ", color: "#f59e0b", onClick: () => setActiveTab("rfqs") },
      { icon: "📊", label: "View Projects", color: "#3b82f6", onClick: () => setActiveTab("projects") },
      { icon: "👥", label: "Accounts", color: "#8b5cf6", onClick: () => setActiveTab("accounts") },
      { icon: "📧", label: "Vendor Comms", color: "#10b981", onClick: () => setActiveTab("vendors") },
    ];

    return (
      <>
        {/* KPI Cards */}
        <div className="kpi-grid">
          {kpiCards.map((kpi, idx) => (
            <div key={idx} className="kpi-card">
              <div className="kpi-card-header">
                <span className="kpi-title">{kpi.title}</span>
                <div className="kpi-icon" style={{ backgroundColor: `${kpi.color}20`, color: kpi.color }}>
                  {kpi.icon}
                </div>
              </div>
              <div className="kpi-value" style={{ color: kpi.color }}>{kpi.value}</div>
              <div className="kpi-subtitle">{kpi.subtitle}</div>
              {kpi.trend && (
                <div className={`kpi-trend ${kpi.trendUp ? 'up' : 'down'}`}>
                  {kpi.trendUp ? '↑' : '↓'} {kpi.trend} this month
                </div>
              )}
            </div>
          ))}
        </div>

        {/* Quick Actions */}
        <div className="section-card" style={{ marginBottom: "1.5rem" }}>
          <div className="section-header">
            <h3 className="section-title">Quick Actions</h3>
          </div>
          <div className="section-body">
            <div className="quick-actions-grid">
              {quickActions.map((action, idx) => (
                <div key={idx} className="quick-action-card" onClick={action.onClick}>
                  <div className="quick-action-icon" style={{ backgroundColor: `${action.color}20` }}>
                    {action.icon}
                  </div>
                  <span className="quick-action-label">{action.label}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="content-grid">
          {/* Recent Activity */}
          <div className="section-card">
            <div className="section-header">
              <h3 className="section-title">Recent Activity</h3>
              <button className="btn btn-sm btn-secondary" onClick={fetchDashboardData}>↻ Refresh</button>
            </div>
            <div className="section-body">
              {recentActivity.length > 0 ? (
                <div className="activity-timeline">
                  {recentActivity.map((activity, idx) => (
                    <div key={idx} className="activity-item">
                      <div 
                        className="activity-icon" 
                        style={{ 
                          backgroundColor: activity.type === 'invoice' ? '#dbeafe' : '#dcfce7',
                          color: activity.type === 'invoice' ? '#3b82f6' : '#10b981'
                        }}
                      >
                        {activity.type === 'invoice' ? '📄' : '📊'}
                      </div>
                      <div className="activity-content">
                        <div className="activity-title">{activity.title}</div>
                        <div className="activity-meta">
                          <span>{activity.subtitle}</span>
                          <span>{formatTimeAgo(activity.timestamp)}</span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="empty-state">
                  <div className="empty-icon">📭</div>
                  <p className="empty-text">No recent activity</p>
                </div>
              )}
            </div>
          </div>

          {/* Project Status Breakdown */}
          <div className="section-card">
            <div className="section-header">
              <h3 className="section-title">Project Status</h3>
            </div>
            <div className="section-body">
              {kpis?.projects?.status_breakdown && Object.keys(kpis.projects.status_breakdown).length > 0 ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                  {Object.entries(kpis.projects.status_breakdown).map(([status, count]) => {
                    const colors = {
                      'Active': '#10b981',
                      'Live': '#10b981',
                      'In Progress': '#3b82f6',
                      'Completed': '#6b7280',
                      'Closed': '#6b7280',
                      'Pending': '#f59e0b'
                    };
                    const color = colors[status] || '#9ca3af';
                    const total = kpis.projects.total || 1;
                    const percent = Math.round((count / total) * 100);
                    
                    return (
                      <div key={status}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.25rem' }}>
                          <span style={{ fontSize: '0.875rem', color: '#374151' }}>{status || 'Unknown'}</span>
                          <span style={{ fontSize: '0.875rem', fontWeight: '600', color }}>{count}</span>
                        </div>
                        <div style={{ height: '6px', background: '#e5e7eb', borderRadius: '3px', overflow: 'hidden' }}>
                          <div style={{ height: '100%', width: `${percent}%`, background: color, borderRadius: '3px' }}></div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="empty-state">
                  <p className="empty-text">No project data available</p>
                </div>
              )}
            </div>
          </div>
        </div>
      </>
    );
  };

  const renderRFQs = () => {
    return (
      <>
        {/* RFQ Stats */}
        <div className="kpi-grid" style={{ marginBottom: "1.5rem" }}>
          <div className="kpi-card">
            <div className="kpi-card-header">
              <span className="kpi-title">Pending</span>
              <div className="kpi-icon" style={{ backgroundColor: '#fef3c720', color: '#f59e0b' }}>⏳</div>
            </div>
            <div className="kpi-value" style={{ color: '#f59e0b' }}>{rfqStats.pending}</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-card-header">
              <span className="kpi-title">In Progress</span>
              <div className="kpi-icon" style={{ backgroundColor: '#dbeafe20', color: '#3b82f6' }}>🔄</div>
            </div>
            <div className="kpi-value" style={{ color: '#3b82f6' }}>{rfqStats.inProgress}</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-card-header">
              <span className="kpi-title">Quoted</span>
              <div className="kpi-icon" style={{ backgroundColor: '#dcfce720', color: '#10b981' }}>✅</div>
            </div>
            <div className="kpi-value" style={{ color: '#10b981' }}>{rfqStats.quoted}</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-card-header">
              <span className="kpi-title">Total RFQs</span>
              <div className="kpi-icon" style={{ backgroundColor: '#f3f4f6', color: '#6b7280' }}>📋</div>
            </div>
            <div className="kpi-value">{rfqs.length}</div>
          </div>
        </div>

        {/* Filters */}
        <div className="filters-bar">
          <input
            type="text"
            className="search-input"
            placeholder="Search RFQs..."
            value={rfqSearch}
            onChange={(e) => setRfqSearch(e.target.value)}
          />
          <select
            className="filter-select"
            value={rfqStatusFilter}
            onChange={(e) => setRfqStatusFilter(e.target.value)}
          >
            <option value="">All Status</option>
            <option value="pending">Pending</option>
            <option value="in_progress">In Progress</option>
            <option value="quoted">Quoted</option>
            <option value="won">Won</option>
            <option value="lost">Lost</option>
          </select>
          <button className="btn btn-secondary" onClick={fetchRFQs}>↻ Refresh</button>
        </div>

        {/* RFQ Table */}
        <div className="section-card">
          <div className="section-body" style={{ padding: 0, overflowX: 'auto' }}>
            {filteredRfqs.length > 0 ? (
              <table className="rfq-table">
                <thead>
                  <tr>
                    <th>RFQ ID</th>
                    <th>Title</th>
                    <th>From</th>
                    <th>Value</th>
                    <th>Priority</th>
                    <th>Status</th>
                    <th>Received</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredRfqs.slice((rfqPage - 1) * 15, rfqPage * 15).map((rfq) => (
                    <tr key={rfq.rfq_id}>
                      <td><span className="rfq-id">{rfq.rfq_id}</span></td>
                      <td><span className="rfq-title" title={rfq.title}>{rfq.title}</span></td>
                      <td>
                        <div className="rfq-sender">
                          <span className="rfq-sender-name">{rfq.sender_name || 'Unknown'}</span>
                          <span className="rfq-sender-email">{rfq.contact_email}</span>
                        </div>
                      </td>
                      <td>
                        {rfq.final_value ? (
                          <span className="value-display">
                            {formatCurrency(rfq.final_value, rfq.final_currency)}
                          </span>
                        ) : '—'}
                      </td>
                      <td>
                        <span className={`priority-badge ${rfq.priority || 'medium'}`}>
                          {rfq.priority || 'medium'}
                        </span>
                      </td>
                      <td>
                        <span className={`status-badge ${rfq.status?.replace('_', '-') || 'pending'}`}>
                          {rfq.status?.replace('_', ' ') || 'pending'}
                        </span>
                      </td>
                      <td>{formatDate(rfq.received_date || rfq.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="empty-state">
                <div className="empty-icon">📋</div>
                <p className="empty-title">No RFQs Found</p>
                <p className="empty-text">RFQs will appear here when received via email</p>
              </div>
            )}
          </div>
          
          {/* Pagination */}
          {filteredRfqs.length > 15 && (
            <div className="pagination">
              <button 
                className="pagination-btn" 
                disabled={rfqPage === 1}
                onClick={() => setRfqPage(p => p - 1)}
              >
                ← Prev
              </button>
              <span className="pagination-info">
                Page {rfqPage} of {Math.ceil(filteredRfqs.length / 15)}
              </span>
              <button 
                className="pagination-btn"
                disabled={rfqPage >= Math.ceil(filteredRfqs.length / 15)}
                onClick={() => setRfqPage(p => p + 1)}
              >
                Next →
              </button>
            </div>
          )}
        </div>
      </>
    );
  };

  const renderProjects = () => {
    return (
      <>
        {/* Filters */}
        <div className="filters-bar">
          <input
            type="text"
            className="search-input"
            placeholder="Search projects..."
            value={projectSearch}
            onChange={(e) => setProjectSearch(e.target.value)}
          />
          <select
            className="filter-select"
            value={projectStatusFilter}
            onChange={(e) => setProjectStatusFilter(e.target.value)}
          >
            <option value="">All Status</option>
            <option value="Active">Active</option>
            <option value="Live">Live</option>
            <option value="In Progress">In Progress</option>
            <option value="Pending">Pending</option>
            <option value="Completed">Completed</option>
            <option value="Closed">Closed</option>
          </select>
          <button className="btn btn-secondary" onClick={fetchProjects}>↻ Refresh</button>
        </div>

        {/* Project Grid */}
        {filteredProjects.length > 0 ? (
          <div className="project-grid">
            {filteredProjects.map((proj) => (
              <div key={proj._id} className="project-card">
                <div className="project-header">
                  <div>
                    <div className="project-name">{proj.projectName || 'Unnamed Project'}</div>
                    <div className="project-client">{proj.client || 'No client'}</div>
                  </div>
                  <span className={`status-badge ${proj.projectStatus?.toLowerCase().replace(' ', '-') || 'pending'}`}>
                    {proj.projectStatus || 'Unknown'}
                  </span>
                </div>
                <div className="project-stats">
                  <div className="project-stat">
                    <div className="project-stat-value">{formatCurrency(proj.projectValue || 0)}</div>
                    <div className="project-stat-label">Value</div>
                  </div>
                  <div className="project-stat">
                    <div className="project-stat-value">{proj.sampleSize || '—'}</div>
                    <div className="project-stat-label">Sample</div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="section-card">
            <div className="section-body">
              <div className="empty-state">
                <div className="empty-icon">📊</div>
                <p className="empty-title">No Projects Found</p>
                <p className="empty-text">Create your first project to get started</p>
              </div>
            </div>
          </div>
        )}
      </>
    );
  };

  const renderAccounts = () => {
    return (
      <>
        <div className="filters-bar">
          <input
            type="text"
            className="search-input"
            placeholder="Search accounts..."
            value={accountSearch}
            onChange={(e) => setAccountSearch(e.target.value)}
          />
          <button className="btn btn-secondary" onClick={fetchAccounts}>↻ Refresh</button>
          <button className="btn btn-primary">+ New Account</button>
        </div>

        <div className="section-card">
          <div className="section-body" style={{ padding: 0, overflowX: 'auto' }}>
            {filteredAccounts.length > 0 ? (
              <table className="rfq-table">
                <thead>
                  <tr>
                    <th>Account</th>
                    <th>Email</th>
                    <th>Type</th>
                    <th>Projects</th>
                    <th>Total Invoiced</th>
                    <th>Outstanding</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredAccounts.map((acc) => (
                    <tr key={acc._id}>
                      <td>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                          <div className="vendor-avatar" style={{ width: '36px', height: '36px', fontSize: '0.875rem' }}>
                            {getInitials(acc.name)}
                          </div>
                          <span style={{ fontWeight: 500 }}>{acc.name}</span>
                        </div>
                      </td>
                      <td style={{ color: '#6b7280' }}>{acc.email || '—'}</td>
                      <td>
                        <span className={`status-badge ${acc.account_type || 'client'}`}>
                          {acc.account_type || 'client'}
                        </span>
                      </td>
                      <td>{acc.total_projects || 0}</td>
                      <td>{formatCurrency(acc.total_invoiced || 0)}</td>
                      <td style={{ color: acc.total_receivables > 0 ? '#f59e0b' : 'inherit' }}>
                        {formatCurrency(acc.total_receivables || 0)}
                      </td>
                      <td>
                        <span className={`status-badge ${acc.status || 'active'}`}>
                          {acc.status || 'active'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="empty-state">
                <div className="empty-icon">👥</div>
                <p className="empty-title">No Accounts Found</p>
                <p className="empty-text">Sync from clients or create a new account</p>
              </div>
            )}
          </div>
        </div>
      </>
    );
  };

  const renderVendorCommunications = () => {
    return (
      <>
        <div className="filters-bar">
          <input
            type="text"
            className="search-input"
            placeholder="Search vendor communications..."
          />
          <button className="btn btn-secondary" onClick={fetchVendorEmails}>↻ Refresh</button>
        </div>

        <div className="section-card">
          <div className="section-body">
            {vendorEmails.length > 0 ? (
              <div className="vendor-comm-list">
                {vendorEmails.map((email, idx) => (
                  <div key={idx} className="vendor-comm-item">
                    <div className="vendor-avatar">
                      {getInitials(email.sender_name || email.from)}
                    </div>
                    <div className="vendor-details">
                      <div className="vendor-name">{email.sender_name || email.from}</div>
                      <div className="vendor-last-msg">{email.subject}</div>
                    </div>
                    <div className="vendor-meta">
                      <div className="vendor-time">{formatTimeAgo(email.date)}</div>
                      {!email.is_read && <div className="vendor-unread">New</div>}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="empty-state">
                <div className="empty-icon">📧</div>
                <p className="empty-title">No Vendor Communications</p>
                <p className="empty-text">Vendor emails will appear here once classified</p>
              </div>
            )}
          </div>
        </div>
      </>
    );
  };

  // ==================== MAIN RENDER ====================

  const tabs = [
    { id: "dashboard", label: "Dashboard", icon: "📊" },
    { id: "rfqs", label: "RFQs", icon: "📋", badge: rfqStats.pending > 0 ? rfqStats.pending : null },
    { id: "projects", label: "Projects", icon: "📁" },
    { id: "accounts", label: "Accounts", icon: "👥" },
    { id: "vendors", label: "Vendor Comms", icon: "📧" },
  ];

  return (
    <div className="operations-container">
      {/* Header */}
      <div className="operations-header">
        <div className="operations-header-left">
          <h1>⚙️ Operations Dashboard</h1>
          <p>Manage RFQs, projects, accounts, and vendor communications</p>
        </div>
        <div className="operations-header-actions">
          <button className="btn btn-secondary">📥 Export</button>
          <button className="btn btn-primary">+ New RFQ</button>
        </div>
      </div>

      {/* Tabs */}
      <div className="operations-tabs">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            className={`operations-tab ${activeTab === tab.id ? 'active' : ''}`}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.icon} {tab.label}
            {tab.badge && <span className="tab-badge">{tab.badge}</span>}
          </button>
        ))}
      </div>

      {/* Error */}
      {error && (
        <div style={{ 
          padding: "1rem", 
          background: "#fef2f2", 
          color: "#dc2626", 
          borderRadius: "8px", 
          marginBottom: "1rem" 
        }}>
          {error}
        </div>
      )}

      {/* Tab Content */}
      {activeTab === "dashboard" && renderDashboard()}
      {activeTab === "rfqs" && renderRFQs()}
      {activeTab === "projects" && renderProjects()}
      {activeTab === "accounts" && renderAccounts()}
      {activeTab === "vendors" && renderVendorCommunications()}
    </div>
  );
}

export default Operations;
