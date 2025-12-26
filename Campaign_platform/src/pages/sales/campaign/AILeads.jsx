/**
 * AI Lead Database
 * Path: /admin/sales/campaign/ai-leads
 * Light theme matching app styling
 */

import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { API_BASE_URL } from "../../../config";
import "./AILeads.css";

// ============== FILTER OPTIONS ==============

const SENIORITY_OPTIONS = ["C-Level", "VP", "Director", "Manager", "IC", "Unknown"];
const DEPARTMENT_OPTIONS = ["Sales", "Marketing", "Engineering", "Operations", "Finance", "HR", "Product", "Other"];
const PERSONA_OPTIONS = ["Decision Maker", "Influencer", "Gatekeeper", "Practitioner"];
const COMPANY_SIZE_OPTIONS = ["Startup", "SMB", "Mid-Market", "Enterprise"];

function AILeads() {
  const navigate = useNavigate();
  const sessionId = localStorage.getItem("session_id");

  // Data State
  const [leads, setLeads] = useState([]);
  const [rawLeads, setRawLeads] = useState([]);
  const [statistics, setStatistics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selectedIds, setSelectedIds] = useState(new Set());

  // View State
  const [activeTab, setActiveTab] = useState("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [currentPage, setCurrentPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);

  // Filters
  const [filters, setFilters] = useState({
    seniority_level: "",
    department: "",
    persona: "",
    company_size: "",
    min_confidence: "",
  });

  // Import Modal State
  const [showImportModal, setShowImportModal] = useState(false);
  const [importMethod, setImportMethod] = useState("google-search");
  const [importData, setImportData] = useState("");
  const [csvFile, setCsvFile] = useState(null);
  const [googleSearchQuery, setGoogleSearchQuery] = useState("");
  const [googleSearchResults, setGoogleSearchResults] = useState(10);
  const [importing, setImporting] = useState(false);
  const [classifying, setClassifying] = useState(false);
  const [importError, setImportError] = useState("");

  // ============== FETCH DATA ==============

  const fetchLeads = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (searchQuery) params.append("search", searchQuery);
      if (filters.seniority_level) params.append("seniority_level", filters.seniority_level);
      if (filters.department) params.append("department", filters.department);
      if (filters.persona) params.append("persona", filters.persona);
      if (filters.company_size) params.append("company_size", filters.company_size);
      if (filters.min_confidence) params.append("min_confidence", filters.min_confidence);
      params.append("page", currentPage);
      params.append("limit", 50);

      const res = await fetch(`${API_BASE_URL}/leads?${params.toString()}`, {
        headers: { Authorization: sessionId },
      });

      if (!res.ok) throw new Error("Failed to fetch leads");
      const data = await res.json();
      setLeads(data.leads || []);
      setTotalPages(data.pages || 1);
    } catch (err) {
      console.error("Error fetching leads:", err);
    }
  }, [filters, currentPage, searchQuery, sessionId]);

  const fetchRawLeads = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/leads/raw`, {
        headers: { Authorization: sessionId },
      });
      if (!res.ok) throw new Error("Failed to fetch raw leads");
      const data = await res.json();
      setRawLeads(data.leads || []);
    } catch (err) {
      console.error("Error fetching raw leads:", err);
    }
  }, [sessionId]);

  const fetchStatistics = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/leads/statistics`, {
        headers: { Authorization: sessionId },
      });
      if (!res.ok) throw new Error("Failed to fetch statistics");
      const data = await res.json();
      setStatistics(data);
    } catch (err) {
      console.error("Error fetching statistics:", err);
    }
  }, [sessionId]);

  useEffect(() => {
    const loadData = async () => {
      setLoading(true);
      await Promise.all([fetchLeads(), fetchRawLeads(), fetchStatistics()]);
      setLoading(false);
    };
    loadData();
  }, [fetchLeads, fetchRawLeads, fetchStatistics]);

  useEffect(() => {
    if (!loading) fetchLeads();
  }, [filters, currentPage, searchQuery]);

  // ============== IMPORT HANDLER ==============

  const handleImport = async () => {
    setImporting(true);
    setImportError("");
    
    try {
      let res;
      
      if (importMethod === "json") {
        if (!importData.trim()) {
          setImportError("Please enter JSON data");
          setImporting(false);
          return;
        }
        const leadsToImport = JSON.parse(importData);
        res = await fetch(`${API_BASE_URL}/leads/import`, {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: sessionId },
          body: JSON.stringify({ leads: Array.isArray(leadsToImport) ? leadsToImport : [leadsToImport] }),
        });
      } else if (importMethod === "csv") {
        if (!csvFile) {
          setImportError("Please select a CSV file");
          setImporting(false);
          return;
        }
        const formData = new FormData();
        formData.append("file", csvFile);
        res = await fetch(`${API_BASE_URL}/leads/import/csv`, {
          method: "POST",
          headers: { Authorization: sessionId },
          body: formData,
        });
      } else if (importMethod === "google-search") {
        if (!googleSearchQuery.trim()) {
          setImportError("Please enter a search query");
          setImporting(false);
          return;
        }
        res = await fetch(`${API_BASE_URL}/leads/import/google-search`, {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: sessionId },
          body: JSON.stringify({ query: googleSearchQuery, num_results: googleSearchResults }),
        });
      }

      if (!res.ok) {
        const error = await res.json();
        throw new Error(error.detail || "Import failed");
      }

      const result = await res.json();
      alert(result.message || `Imported ${result.imported} leads`);
      setShowImportModal(false);
      setImportData("");
      setCsvFile(null);
      setGoogleSearchQuery("");
      fetchRawLeads();
      fetchStatistics();
    } catch (err) {
      setImportError(err.message);
    } finally {
      setImporting(false);
    }
  };

  // ============== CLASSIFY HANDLER ==============

  const handleClassify = async (leadIds = null) => {
    setClassifying(true);
    try {
      const res = await fetch(`${API_BASE_URL}/leads/classify`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: sessionId },
        body: JSON.stringify({ lead_ids: leadIds, batch_size: 10 }),
      });

      if (!res.ok) throw new Error("Classification failed");
      const result = await res.json();
      alert(result.message);

      setTimeout(() => {
        fetchLeads();
        fetchRawLeads();
        fetchStatistics();
      }, 2000);
    } catch (err) {
      alert("Classification error: " + err.message);
    } finally {
      setClassifying(false);
    }
  };

  // ============== SELECTION ==============

  const toggleSelectAll = () => {
    const currentList = getDisplayLeads();
    if (selectedIds.size === currentList.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(currentList.map(l => l._id)));
    }
  };

  const toggleSelect = (id) => {
    const newSet = new Set(selectedIds);
    if (newSet.has(id)) newSet.delete(id);
    else newSet.add(id);
    setSelectedIds(newSet);
  };

  // ============== FILTER HANDLERS ==============

  const handleFilterChange = (key, value) => {
    setFilters(prev => ({ ...prev, [key]: value }));
    setCurrentPage(1);
  };

  const clearFilters = () => {
    setFilters({
      seniority_level: "",
      department: "",
      persona: "",
      company_size: "",
      min_confidence: "",
    });
    setSearchQuery("");
    setCurrentPage(1);
  };

  // ============== GET DISPLAY DATA ==============

  const getDisplayLeads = () => {
    if (activeTab === "pending") {
      return rawLeads.filter(l => l.classification_status === "Pending");
    } else if (activeTab === "classified") {
      return leads;
    }
    return rawLeads;
  };

  const displayLeads = getDisplayLeads();

  // ============== HELPER FUNCTIONS ==============

  const getConfidenceClass = (score) => {
    if (!score) return "low";
    if (score >= 0.8) return "high";
    if (score >= 0.5) return "medium";
    return "low";
  };

  // ============== RENDER ==============

  if (loading) {
    return (
      <div className="ai-leads-page">
        <div className="loading-container">
          <div className="loading-spinner"></div>
          <span>Loading leads...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="ai-leads-page">
      {/* Page Header */}
      <div className="page-header">
        <div className="header-left">
          <h1>🤖 AI Lead Database</h1>
          <p className="subtitle">Import, classify, and manage LinkedIn leads with AI</p>
        </div>
        <div className="header-actions">
          <button className="btn btn-outline" onClick={() => navigate(-1)}>
            ← Back
          </button>
          <button className="btn btn-primary" onClick={() => setShowImportModal(true)}>
            📥 Import Leads
          </button>
          <button 
            className="btn btn-success"
            onClick={() => handleClassify()}
            disabled={classifying}
          >
            {classifying ? "⏳ Classifying..." : "🤖 Classify All"}
          </button>
        </div>
      </div>

      {/* Stats Cards */}
      <div className="stats-row">
        <div className="stat-card">
          <div className="stat-value">{statistics?.raw?.total || 0}</div>
          <div className="stat-label">Total Leads</div>
        </div>
        <div className="stat-card warning">
          <div className="stat-value">{statistics?.raw?.pending || 0}</div>
          <div className="stat-label">Pending</div>
        </div>
        <div className="stat-card info">
          <div className="stat-value">{statistics?.raw?.processing || 0}</div>
          <div className="stat-label">Processing</div>
        </div>
        <div className="stat-card success">
          <div className="stat-value">{statistics?.raw?.classified || 0}</div>
          <div className="stat-label">Classified</div>
        </div>
        <div className="stat-card primary">
          <div className="stat-value">{statistics?.enriched?.high_confidence || 0}</div>
          <div className="stat-label">High Confidence</div>
        </div>
      </div>

      {/* Tabs */}
      <div className="tabs-row">
        <button 
          className={`tab-btn ${activeTab === "all" ? "active" : ""}`}
          onClick={() => setActiveTab("all")}
        >
          All Leads ({rawLeads.length})
        </button>
        <button 
          className={`tab-btn ${activeTab === "pending" ? "active" : ""}`}
          onClick={() => setActiveTab("pending")}
        >
          Pending ({rawLeads.filter(l => l.classification_status === "Pending").length})
        </button>
        <button 
          className={`tab-btn ${activeTab === "classified" ? "active" : ""}`}
          onClick={() => setActiveTab("classified")}
        >
          Classified ({leads.length})
        </button>
      </div>

      {/* Filters Bar */}
      <div className="filters-bar">
        <input
          type="text"
          className="search-input"
          placeholder="🔍 Search leads..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
        />
        <select
          className="filter-select"
          value={filters.seniority_level}
          onChange={(e) => handleFilterChange("seniority_level", e.target.value)}
        >
          <option value="">All Seniority</option>
          {SENIORITY_OPTIONS.map(opt => (
            <option key={opt} value={opt}>{opt}</option>
          ))}
        </select>
        <select
          className="filter-select"
          value={filters.department}
          onChange={(e) => handleFilterChange("department", e.target.value)}
        >
          <option value="">All Departments</option>
          {DEPARTMENT_OPTIONS.map(opt => (
            <option key={opt} value={opt}>{opt}</option>
          ))}
        </select>
        <select
          className="filter-select"
          value={filters.persona}
          onChange={(e) => handleFilterChange("persona", e.target.value)}
        >
          <option value="">All Personas</option>
          {PERSONA_OPTIONS.map(opt => (
            <option key={opt} value={opt}>{opt}</option>
          ))}
        </select>
        <button className="btn btn-outline btn-sm" onClick={clearFilters}>
          Clear
        </button>
      </div>

      {/* Selection Bar */}
      {selectedIds.size > 0 && (
        <div className="selection-bar">
          <span>{selectedIds.size} lead(s) selected</span>
          <button className="btn btn-sm btn-primary" onClick={() => handleClassify(Array.from(selectedIds))}>
            🤖 Classify Selected
          </button>
          <button className="btn btn-sm btn-outline" onClick={() => setSelectedIds(new Set())}>
            ✕ Clear
          </button>
        </div>
      )}

      {/* Data Table */}
      <div className="table-wrapper">
        {displayLeads.length === 0 ? (
          <div className="empty-state">
            <div className="empty-icon">📋</div>
            <h2>No leads found</h2>
            <p>Import some leads to get started.</p>
            <button className="btn btn-primary" onClick={() => setShowImportModal(true)}>
              📥 Import Leads
            </button>
          </div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th className="checkbox-col">
                  <input
                    type="checkbox"
                    checked={selectedIds.size === displayLeads.length && displayLeads.length > 0}
                    onChange={toggleSelectAll}
                  />
                </th>
                <th>Name</th>
                <th>Job Title</th>
                <th>Company</th>
                {activeTab === "classified" ? (
                  <>
                    <th>Seniority</th>
                    <th>Department</th>
                    <th>Confidence</th>
                  </>
                ) : (
                  <th>Status</th>
                )}
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {displayLeads.map((lead) => (
                <tr key={lead._id} className={selectedIds.has(lead._id) ? "selected" : ""}>
                  <td className="checkbox-col">
                    <input
                      type="checkbox"
                      checked={selectedIds.has(lead._id)}
                      onChange={() => toggleSelect(lead._id)}
                    />
                  </td>
                  <td className="name-cell">
                    <a href={lead.linkedin_url} target="_blank" rel="noopener noreferrer">
                      {lead.name}
                    </a>
                  </td>
                  <td>{lead.title || lead.job_title || "-"}</td>
                  <td>{lead.company_name || lead.inferred_company || "-"}</td>
                  {activeTab === "classified" ? (
                    <>
                      <td><span className="badge badge-blue">{lead.seniority_level}</span></td>
                      <td><span className="badge badge-purple">{lead.department}</span></td>
                      <td>
                        <span className={`confidence-pill ${getConfidenceClass(lead.confidence_score)}`}>
                          {Math.round((lead.confidence_score || 0) * 100)}%
                        </span>
                      </td>
                    </>
                  ) : (
                    <td>
                      <span className={`status-pill ${lead.classification_status?.toLowerCase()}`}>
                        {lead.classification_status}
                      </span>
                    </td>
                  )}
                  <td className="actions-cell">
                    <a href={lead.linkedin_url} target="_blank" rel="noopener noreferrer" className="action-link">
                      View ↗
                    </a>
                    {lead.classification_status === "Pending" && (
                      <button className="action-btn" onClick={() => handleClassify([lead._id])}>
                        Classify
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && activeTab === "classified" && (
        <div className="pagination-bar">
          <button 
            className="btn btn-outline btn-sm"
            disabled={currentPage === 1} 
            onClick={() => setCurrentPage(p => p - 1)}
          >
            ← Previous
          </button>
          <span className="page-info">Page {currentPage} of {totalPages}</span>
          <button 
            className="btn btn-outline btn-sm"
            disabled={currentPage === totalPages} 
            onClick={() => setCurrentPage(p => p + 1)}
          >
            Next →
          </button>
        </div>
      )}

      {/* Import Modal */}
      {showImportModal && (
        <div className="modal-overlay" onClick={() => setShowImportModal(false)}>
          <div className="modal-box" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>📥 Import Leads</h2>
              <button className="modal-close-btn" onClick={() => setShowImportModal(false)}>×</button>
            </div>

            <div className="modal-body">
              {/* Import Method Tabs */}
              <div className="import-method-tabs">
                <button 
                  className={`method-tab ${importMethod === "google-search" ? "active" : ""}`}
                  onClick={() => setImportMethod("google-search")}
                >
                  🔍 Google Search
                </button>
                <button 
                  className={`method-tab ${importMethod === "csv" ? "active" : ""}`}
                  onClick={() => setImportMethod("csv")}
                >
                  📄 CSV Upload
                </button>
                <button 
                  className={`method-tab ${importMethod === "json" ? "active" : ""}`}
                  onClick={() => setImportMethod("json")}
                >
                  📋 JSON
                </button>
              </div>

              {/* Error Display */}
              {importError && (
                <div className="error-alert">{importError}</div>
              )}

              {/* Google Search */}
              {importMethod === "google-search" && (
                <div className="import-form">
                  <label>Search LinkedIn Profiles</label>
                  <input
                    type="text"
                    className="form-input"
                    placeholder='e.g., "VP Sales" "Software" India'
                    value={googleSearchQuery}
                    onChange={(e) => setGoogleSearchQuery(e.target.value)}
                  />
                  <div className="form-row-inline">
                    <label>Number of Results:</label>
                    <input
                      type="number"
                      className="form-input small"
                      min="1"
                      max="100"
                      value={googleSearchResults}
                      onChange={(e) => setGoogleSearchResults(parseInt(e.target.value))}
                    />
                  </div>
                  <p className="form-hint">
                    💡 Searches LinkedIn profiles via Google Custom Search API. 
                    Configure your API key in Settings → Google API Settings.
                  </p>
                </div>
              )}

              {/* CSV Upload */}
              {importMethod === "csv" && (
                <div className="import-form">
                  <label>Upload CSV File</label>
                  <div className="file-upload-box">
                    <input
                      type="file"
                      accept=".csv"
                      id="csv-file-input"
                      onChange={(e) => setCsvFile(e.target.files[0])}
                    />
                    <label htmlFor="csv-file-input" className="file-upload-label">
                      {csvFile ? `✅ ${csvFile.name}` : "📁 Click to select CSV file"}
                    </label>
                  </div>
                  <p className="form-hint">
                    Expected columns: name, title, linkedin_url, snippet
                  </p>
                </div>
              )}

              {/* JSON */}
              {importMethod === "json" && (
                <div className="import-form">
                  <label>Paste JSON Data</label>
                  <textarea
                    className="form-textarea"
                    placeholder='[{"name": "John Smith", "title": "VP Sales", "linkedin_url": "https://linkedin.com/in/...", "snippet": "10+ years experience"}]'
                    value={importData}
                    onChange={(e) => setImportData(e.target.value)}
                  />
                </div>
              )}
            </div>

            <div className="modal-footer">
              <button className="btn btn-outline" onClick={() => setShowImportModal(false)}>
                Cancel
              </button>
              <button className="btn btn-primary" onClick={handleImport} disabled={importing}>
                {importing ? "⏳ Importing..." : "📥 Import Leads"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default AILeads;
