/**
 * AGENT 5 — FRONTEND ADMIN UI ENGINEER
 * Lead Management Component
 * Path: /admin/sales/campaign/list/Add Contacts/Database Connection
 */

import { useState, useEffect, useMemo, useCallback } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { API_BASE_URL } from "../../../config";
import "./DatabaseConnection.css";

// ============== ENUMS (match backend) ==============

const SENIORITY_LEVELS = ["C-Level", "VP", "Director", "Manager", "IC", "Unknown"];
const DEPARTMENTS = ["Sales", "Marketing", "Engineering", "Operations", "Finance", "HR", "Product", "Other"];
const PERSONAS = ["Decision Maker", "Influencer", "Gatekeeper", "Practitioner"];
const COMPANY_SIZES = ["Startup", "SMB", "Mid-Market", "Enterprise"];
const REGIONS = ["US", "EU", "APAC", "LATAM", "Other"];

// ============== MAIN COMPONENT ==============

function DatabaseConnection() {
  const navigate = useNavigate();
  const location = useLocation();
  const { selectedList, campaign } = location.state || {};

  // State
  const [leads, setLeads] = useState([]);
  const [rawLeads, setRawLeads] = useState([]);
  const [statistics, setStatistics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedLeadIds, setSelectedLeadIds] = useState(new Set());
  const [showImportModal, setShowImportModal] = useState(false);
  const [importData, setImportData] = useState("");
  const [importing, setImporting] = useState(false);
  const [classifying, setClassifying] = useState(false);
  const [currentPage, setCurrentPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [viewMode, setViewMode] = useState("enriched"); // "enriched" | "raw"
  
  // Import modal state
  const [importMethod, setImportMethod] = useState("json"); // "json" | "csv" | "google-search" | "google-sheets"
  const [csvFile, setCsvFile] = useState(null);
  const [googleSearchQuery, setGoogleSearchQuery] = useState("");
  const [googleSearchResults, setGoogleSearchResults] = useState(10);
  const [googleSheetId, setGoogleSheetId] = useState("");
  const [googleSheetName, setGoogleSheetName] = useState("Sheet1");

  // Filters
  const [filters, setFilters] = useState({
    search: "",
    seniority_level: "",
    department: "",
    persona: "",
    company_size: "",
    region: "",
    min_confidence: "",
  });

  const sessionId = localStorage.getItem("session_id");

  // ============== FETCH FUNCTIONS ==============

  const fetchLeads = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (filters.search) params.append("search", filters.search);
      if (filters.seniority_level) params.append("seniority_level", filters.seniority_level);
      if (filters.department) params.append("department", filters.department);
      if (filters.persona) params.append("persona", filters.persona);
      if (filters.company_size) params.append("company_size", filters.company_size);
      if (filters.region) params.append("region", filters.region);
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
      setError(err.message);
    }
  }, [filters, currentPage, sessionId]);

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

  // Initial load
  useEffect(() => {
    const loadData = async () => {
      setLoading(true);
      await Promise.all([fetchLeads(), fetchRawLeads(), fetchStatistics()]);
      setLoading(false);
    };
    loadData();
  }, [fetchLeads, fetchRawLeads, fetchStatistics]);

  // Refetch on filter change
  useEffect(() => {
    if (!loading) {
      fetchLeads();
    }
  }, [filters, currentPage]);

  // ============== IMPORT LEADS ==============

  const handleImport = async () => {
    setImporting(true);
    setError(null);

    try {
      let res;
      
      switch (importMethod) {
        case "json":
          if (!importData.trim()) {
            setError("Please enter JSON data");
            setImporting(false);
            return;
          }
          // Parse JSON input
          let leadsToImport;
          try {
            leadsToImport = JSON.parse(importData);
            if (!Array.isArray(leadsToImport)) {
              leadsToImport = [leadsToImport];
            }
          } catch {
            setError("Invalid JSON format");
            setImporting(false);
            return;
          }

          res = await fetch(`${API_BASE_URL}/leads/import`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Authorization: sessionId,
            },
            body: JSON.stringify({ leads: leadsToImport }),
          });
          break;
          
        case "csv":
          if (!csvFile) {
            setError("Please select a CSV file");
            setImporting(false);
            return;
          }
          const formData = new FormData();
          formData.append("file", csvFile);
          formData.append("delimiter", ",");
          
          res = await fetch(`${API_BASE_URL}/leads/import/csv`, {
            method: "POST",
            headers: { Authorization: sessionId },
            body: formData,
          });
          break;
          
        case "google-search":
          if (!googleSearchQuery.trim()) {
            setError("Please enter a search query");
            setImporting(false);
            return;
          }
          res = await fetch(`${API_BASE_URL}/leads/import/google-search`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Authorization: sessionId,
            },
            body: JSON.stringify({
              query: googleSearchQuery,
              num_results: googleSearchResults,
            }),
          });
          break;
          
        case "google-sheets":
          if (!googleSheetId.trim()) {
            setError("Please enter a Google Sheet ID");
            setImporting(false);
            return;
          }
          res = await fetch(`${API_BASE_URL}/leads/import/google-sheets`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Authorization: sessionId,
            },
            body: JSON.stringify({
              spreadsheet_id: googleSheetId,
              sheet_name: googleSheetName,
            }),
          });
          break;
          
        default:
          setError("Invalid import method");
          setImporting(false);
          return;
      }

      if (!res.ok) {
        const errorData = await res.json();
        throw new Error(errorData.detail || "Import failed");
      }

      const result = await res.json();
      alert(`${result.message || `Imported: ${result.imported || 0}`}`);

      // Reset form
      setImportData("");
      setCsvFile(null);
      setGoogleSearchQuery("");
      setGoogleSheetId("");
      setShowImportModal(false);
      fetchRawLeads();
      fetchStatistics();
    } catch (err) {
      setError(err.message);
    } finally {
      setImporting(false);
    }
  };

  // ============== CLASSIFY LEADS ==============

  const handleClassify = async (leadIds = null) => {
    setClassifying(true);
    setError(null);

    try {
      const res = await fetch(`${API_BASE_URL}/leads/classify`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: sessionId,
        },
        body: JSON.stringify({
          lead_ids: leadIds,
          batch_size: 10,
        }),
      });

      if (!res.ok) throw new Error("Classification failed");

      const result = await res.json();
      alert(result.message);

      // Refresh data after short delay (async processing)
      setTimeout(() => {
        fetchLeads();
        fetchRawLeads();
        fetchStatistics();
      }, 2000);
    } catch (err) {
      setError(err.message);
    } finally {
      setClassifying(false);
    }
  };

  // ============== ATTACH TO CAMPAIGN ==============

  const handleAttachToCampaign = async () => {
    if (selectedLeadIds.size === 0) {
      alert("Please select at least one lead");
      return;
    }

    if (!campaign?._id) {
      alert("No campaign selected");
      return;
    }

    try {
      const res = await fetch(`${API_BASE_URL}/leads/campaigns/${campaign._id}/attach`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: sessionId,
        },
        body: JSON.stringify({
          lead_ids: Array.from(selectedLeadIds),
        }),
      });

      if (!res.ok) throw new Error("Failed to attach leads");

      const result = await res.json();
      alert(result.message);
      setSelectedLeadIds(new Set());
    } catch (err) {
      setError(err.message);
    }
  };

  // ============== SELECTION HANDLERS ==============

  const toggleSelectAll = () => {
    if (selectedLeadIds.size === leads.length) {
      setSelectedLeadIds(new Set());
    } else {
      setSelectedLeadIds(new Set(leads.map((l) => l._id)));
    }
  };

  const toggleSelectLead = (leadId) => {
    const newSelected = new Set(selectedLeadIds);
    if (newSelected.has(leadId)) {
      newSelected.delete(leadId);
    } else {
      newSelected.add(leadId);
    }
    setSelectedLeadIds(newSelected);
  };

  // ============== FILTER HANDLERS ==============

  const handleFilterChange = (key, value) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
    setCurrentPage(1);
  };

  const clearFilters = () => {
    setFilters({
      search: "",
      seniority_level: "",
      department: "",
      persona: "",
      company_size: "",
      region: "",
      min_confidence: "",
    });
    setCurrentPage(1);
  };

  // ============== CONFIDENCE DISPLAY ==============

  const getConfidenceClass = (score) => {
    if (score >= 0.8) return "high";
    if (score >= 0.5) return "medium";
    return "low";
  };

  // ============== RENDER ==============

  if (loading) {
    return (
      <div className="leads-container">
        <div className="loading-overlay">
          <div className="loading-spinner"></div>
          <span>Loading leads...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="leads-container">
      {/* Header */}
      <div className="leads-header">
        <div>
          <h1 className="leads-title">LinkedIn Lead Database</h1>
          <p className="leads-subtitle">AI-powered lead classification and segmentation</p>
        </div>
        <div className="leads-actions">
          <button className="btn-secondary" onClick={() => navigate(-1)}>
            ← Back
          </button>
          <button className="btn-secondary" onClick={() => setShowImportModal(true)}>
            📥 Import Leads
          </button>
          <button
            className="btn-primary"
            onClick={() => handleClassify()}
            disabled={classifying}
          >
            {classifying ? (
              <>
                <div className="loading-spinner"></div> Classifying...
              </>
            ) : (
              "🤖 Classify Pending"
            )}
          </button>
        </div>
      </div>

      {/* Error Display */}
      {error && (
        <div className="error-banner" style={{ background: "#3b0d0d", padding: "12px", borderRadius: "8px", marginBottom: "16px", color: "#fca5a5" }}>
          {error}
        </div>
      )}

      {/* Statistics Cards */}
      {statistics && (
        <div className="stats-grid">
          <div className="stat-card">
            <div className="stat-value">{statistics.raw?.total || 0}</div>
            <div className="stat-label">Total Leads</div>
          </div>
          <div className="stat-card pending">
            <div className="stat-value">{statistics.raw?.pending || 0}</div>
            <div className="stat-label">Pending</div>
          </div>
          <div className="stat-card processing">
            <div className="stat-value">{statistics.raw?.processing || 0}</div>
            <div className="stat-label">Processing</div>
          </div>
          <div className="stat-card classified">
            <div className="stat-value">{statistics.raw?.classified || 0}</div>
            <div className="stat-label">Classified</div>
          </div>
          <div className="stat-card failed">
            <div className="stat-value">{statistics.raw?.failed || 0}</div>
            <div className="stat-label">Failed</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{statistics.enriched?.high_confidence || 0}</div>
            <div className="stat-label">High Confidence</div>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="filters-section">
        <div className="filters-header">
          <h3 className="filters-title">Filters</h3>
          <button className="clear-filters-btn" onClick={clearFilters}>
            Clear All
          </button>
        </div>
        <div className="filters-grid">
          <div className="filter-group">
            <label className="filter-label">Search</label>
            <input
              type="text"
              className="filter-input"
              placeholder="Name, title, industry..."
              value={filters.search}
              onChange={(e) => handleFilterChange("search", e.target.value)}
            />
          </div>
          <div className="filter-group">
            <label className="filter-label">Seniority</label>
            <select
              className="filter-select"
              value={filters.seniority_level}
              onChange={(e) => handleFilterChange("seniority_level", e.target.value)}
            >
              <option value="">All Levels</option>
              {SENIORITY_LEVELS.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>
          <div className="filter-group">
            <label className="filter-label">Department</label>
            <select
              className="filter-select"
              value={filters.department}
              onChange={(e) => handleFilterChange("department", e.target.value)}
            >
              <option value="">All Departments</option>
              {DEPARTMENTS.map((d) => (
                <option key={d} value={d}>{d}</option>
              ))}
            </select>
          </div>
          <div className="filter-group">
            <label className="filter-label">Persona</label>
            <select
              className="filter-select"
              value={filters.persona}
              onChange={(e) => handleFilterChange("persona", e.target.value)}
            >
              <option value="">All Personas</option>
              {PERSONAS.map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </div>
          <div className="filter-group">
            <label className="filter-label">Region</label>
            <select
              className="filter-select"
              value={filters.region}
              onChange={(e) => handleFilterChange("region", e.target.value)}
            >
              <option value="">All Regions</option>
              {REGIONS.map((r) => (
                <option key={r} value={r}>{r}</option>
              ))}
            </select>
          </div>
          <div className="filter-group">
            <label className="filter-label">Min Confidence</label>
            <select
              className="filter-select"
              value={filters.min_confidence}
              onChange={(e) => handleFilterChange("min_confidence", e.target.value)}
            >
              <option value="">Any</option>
              <option value="0.9">90%+</option>
              <option value="0.8">80%+</option>
              <option value="0.7">70%+</option>
              <option value="0.5">50%+</option>
            </select>
          </div>
        </div>
      </div>

      {/* Selected Bar */}
      {selectedLeadIds.size > 0 && (
        <div className="selected-bar">
          <span className="selected-count">{selectedLeadIds.size} lead(s) selected</span>
          <div className="selected-actions">
            <button className="btn-secondary" onClick={() => setSelectedLeadIds(new Set())}>
              Clear Selection
            </button>
            {campaign && (
              <button className="btn-success" onClick={handleAttachToCampaign}>
                Attach to Campaign
              </button>
            )}
          </div>
        </div>
      )}

      {/* View Toggle */}
      <div style={{ marginBottom: "16px", display: "flex", gap: "8px" }}>
        <button
          className={viewMode === "enriched" ? "btn-primary" : "btn-secondary"}
          onClick={() => setViewMode("enriched")}
        >
          Classified Leads ({leads.length})
        </button>
        <button
          className={viewMode === "raw" ? "btn-primary" : "btn-secondary"}
          onClick={() => setViewMode("raw")}
        >
          Raw Leads ({rawLeads.length})
        </button>
      </div>

      {/* Leads Table */}
      {viewMode === "enriched" ? (
        <div className="leads-table-container">
          {leads.length > 0 ? (
            <>
              <table className="leads-table">
                <thead>
                  <tr>
                    <th className="checkbox-col">
                      <input
                        type="checkbox"
                        className="lead-checkbox"
                        checked={selectedLeadIds.size === leads.length && leads.length > 0}
                        onChange={toggleSelectAll}
                      />
                    </th>
                    <th>Name</th>
                    <th>Title</th>
                    <th>Classification</th>
                    <th>Industry</th>
                    <th>Confidence</th>
                    <th>LinkedIn</th>
                  </tr>
                </thead>
                <tbody>
                  {leads.map((lead) => (
                    <tr key={lead._id}>
                      <td>
                        <input
                          type="checkbox"
                          className="lead-checkbox"
                          checked={selectedLeadIds.has(lead._id)}
                          onChange={() => toggleSelectLead(lead._id)}
                        />
                      </td>
                      <td className="name-cell">{lead.name}</td>
                      <td className="title-cell" title={lead.title}>{lead.title}</td>
                      <td>
                        <span className="classification-badge seniority">{lead.seniority_level}</span>
                        <span className="classification-badge department">{lead.department}</span>
                        <span className="classification-badge persona">{lead.persona}</span>
                      </td>
                      <td>
                        <span className="classification-badge industry">{lead.industry}</span>
                        <span className="classification-badge region">{lead.region}</span>
                      </td>
                      <td>
                        <div className="confidence-score">
                          <div className="confidence-bar">
                            <div
                              className={`confidence-fill ${getConfidenceClass(lead.confidence_score)}`}
                              style={{ width: `${lead.confidence_score * 100}%` }}
                            ></div>
                          </div>
                          <span className="confidence-value">{Math.round(lead.confidence_score * 100)}%</span>
                        </div>
                      </td>
                      <td>
                        <a
                          href={lead.linkedin_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="linkedin-link"
                        >
                          View →
                        </a>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              {/* Pagination */}
              <div className="pagination">
                <button
                  className="pagination-btn"
                  disabled={currentPage === 1}
                  onClick={() => setCurrentPage((p) => p - 1)}
                >
                  ← Previous
                </button>
                <span className="pagination-info">
                  Page {currentPage} of {totalPages}
                </span>
                <button
                  className="pagination-btn"
                  disabled={currentPage === totalPages}
                  onClick={() => setCurrentPage((p) => p + 1)}
                >
                  Next →
                </button>
              </div>
            </>
          ) : (
            <div className="empty-state">
              <div className="empty-icon">🔍</div>
              <h2 className="empty-title">No classified leads found</h2>
              <p className="empty-description">
                Import leads and run AI classification to see results here.
              </p>
            </div>
          )}
        </div>
      ) : (
        /* Raw Leads Table */
        <div className="leads-table-container">
          {rawLeads.length > 0 ? (
            <table className="leads-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Title</th>
                  <th>Source</th>
                  <th>Status</th>
                  <th>Attempts</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {rawLeads.map((lead) => (
                  <tr key={lead._id}>
                    <td className="name-cell">{lead.name}</td>
                    <td className="title-cell">{lead.title}</td>
                    <td>{lead.source}</td>
                    <td>
                      <span className={`status-badge ${lead.classification_status?.toLowerCase()}`}>
                        <span className="status-dot"></span>
                        {lead.classification_status}
                      </span>
                    </td>
                    <td>{lead.classification_attempts || 0}/3</td>
                    <td>
                      {lead.classification_status !== "Classified" && (
                        <button
                          className="btn-secondary"
                          style={{ padding: "4px 12px", fontSize: "12px" }}
                          onClick={() => handleClassify([lead._id])}
                          disabled={classifying}
                        >
                          🤖 Classify
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="empty-state">
              <div className="empty-icon">📋</div>
              <h2 className="empty-title">No raw leads imported</h2>
              <p className="empty-description">
                Click "Import Leads" to add LinkedIn leads for classification.
              </p>
            </div>
          )}
        </div>
      )}

      {/* Import Modal */}
      {showImportModal && (
        <div className="modal-overlay" onClick={() => setShowImportModal(false)}>
          <div className="modal-content import-modal-wide" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2 className="modal-title">Import LinkedIn Leads</h2>
              <button className="modal-close" onClick={() => setShowImportModal(false)}>
                ×
              </button>
            </div>
            <div className="modal-body">
              {/* Import Method Tabs */}
              <div className="import-method-tabs">
                <button
                  className={`import-tab ${importMethod === "json" ? "active" : ""}`}
                  onClick={() => setImportMethod("json")}
                >
                  📋 JSON
                </button>
                <button
                  className={`import-tab ${importMethod === "csv" ? "active" : ""}`}
                  onClick={() => setImportMethod("csv")}
                >
                  📄 CSV
                </button>
                <button
                  className={`import-tab ${importMethod === "google-search" ? "active" : ""}`}
                  onClick={() => setImportMethod("google-search")}
                >
                  🔍 Google Search
                </button>
                <button
                  className={`import-tab ${importMethod === "google-sheets" ? "active" : ""}`}
                  onClick={() => setImportMethod("google-sheets")}
                >
                  📊 Google Sheets
                </button>
              </div>

              {/* JSON Import */}
              {importMethod === "json" && (
                <>
                  <textarea
                    className="import-textarea"
                    placeholder='Paste JSON array of leads...

Example:
[
  {
    "name": "John Smith",
    "title": "VP of Sales",
    "linkedin_url": "https://linkedin.com/in/johnsmith",
    "snippet": "10+ years in enterprise sales"
  }
]'
                    value={importData}
                    onChange={(e) => setImportData(e.target.value)}
                  />
                  <div className="import-help">
                    <p>Required fields: <code>name</code>, <code>title</code>, <code>linkedin_url</code>, <code>snippet</code></p>
                  </div>
                </>
              )}

              {/* CSV Import */}
              {importMethod === "csv" && (
                <div className="csv-upload-section">
                  <div className="file-upload-area">
                    <input
                      type="file"
                      accept=".csv"
                      id="csv-file"
                      onChange={(e) => setCsvFile(e.target.files[0])}
                      style={{ display: "none" }}
                    />
                    <label htmlFor="csv-file" className="file-upload-label">
                      {csvFile ? (
                        <>✅ {csvFile.name}</>
                      ) : (
                        <>📁 Click to select CSV file</>
                      )}
                    </label>
                  </div>
                  <div className="import-help">
                    <p><strong>Expected columns:</strong> name, title, linkedin_url, snippet</p>
                    <p>First row should be headers. The columns can be in any order.</p>
                  </div>
                </div>
              )}

              {/* Google Search Import */}
              {importMethod === "google-search" && (
                <div className="google-search-section">
                  <div className="form-group">
                    <label>Search Query</label>
                    <input
                      type="text"
                      className="filter-input"
                      placeholder='e.g., "VP of Sales" "Software" site:linkedin.com/in'
                      value={googleSearchQuery}
                      onChange={(e) => setGoogleSearchQuery(e.target.value)}
                    />
                  </div>
                  <div className="form-group">
                    <label>Number of Results</label>
                    <input
                      type="number"
                      className="filter-input"
                      min="1"
                      max="100"
                      value={googleSearchResults}
                      onChange={(e) => setGoogleSearchResults(parseInt(e.target.value))}
                    />
                  </div>
                  <div className="import-help">
                    <p><strong>Note:</strong> Requires Google API Key and CSE ID configured in Settings.</p>
                    <p>Search automatically targets LinkedIn profiles.</p>
                  </div>
                </div>
              )}

              {/* Google Sheets Import */}
              {importMethod === "google-sheets" && (
                <div className="google-sheets-section">
                  <div className="form-group">
                    <label>Spreadsheet ID</label>
                    <input
                      type="text"
                      className="filter-input"
                      placeholder="e.g., 1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"
                      value={googleSheetId}
                      onChange={(e) => setGoogleSheetId(e.target.value)}
                    />
                    <small className="hint">Find this in the Google Sheets URL after /d/</small>
                  </div>
                  <div className="form-group">
                    <label>Sheet Name</label>
                    <input
                      type="text"
                      className="filter-input"
                      placeholder="Sheet1"
                      value={googleSheetName}
                      onChange={(e) => setGoogleSheetName(e.target.value)}
                    />
                  </div>
                  <div className="import-help">
                    <p><strong>Note:</strong> Sheet must be set to "Anyone with link can view".</p>
                    <p><strong>Expected columns:</strong> name, title, linkedin_url, snippet</p>
                  </div>
                </div>
              )}
            </div>
            <div className="modal-footer">
              <button className="btn-secondary" onClick={() => setShowImportModal(false)}>
                Cancel
              </button>
              <button
                className="btn-primary"
                onClick={handleImport}
                disabled={importing}
              >
                {importing ? "Importing..." : "Import Leads"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default DatabaseConnection;
