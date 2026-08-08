import React, { useEffect, useMemo, useState, useCallback, useRef } from "react";
import { useAuth } from "../../hooks/useAuth";
import { buildApiUrl } from "../../config";
import { fetchAllClients } from "../../utils/api"
import "./PotentialClients.css";

const STORAGE_KEY = "potential_clients_v1";

function PotentialClients() {
  const { user, token } = useAuth();
  const [surveys, setSurveys] = useState([]);
  const [clients, setClients] = useState([]);
  const [persistedClients, setPersistedClients] = useState(() => {
    // Seed from localStorage as initial value while backend loads
    if (typeof window === "undefined") return [];
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      const parsed = JSON.parse(raw || "[]");
      if (Array.isArray(parsed)) {
        return parsed.filter((entry) => entry && entry.key && entry.name);
      }
    } catch (err) {
      console.warn("Failed to load persisted clients from localStorage:", err);
    }
    return [];
  });
  const rosterSavedToBackend = useRef(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState("");
  
  // Enrichment state
  const [enrichedLeads, setEnrichedLeads] = useState({});
  const [enrichingCompany, setEnrichingCompany] = useState(null);
  const [selectedClient, setSelectedClient] = useState(null);
  const [showEnrichmentPanel, setShowEnrichmentPanel] = useState(false);
  const [enrichmentStats, setEnrichmentStats] = useState(null);
  const [autoEnriching, setAutoEnriching] = useState(false);

  useEffect(() => {
    if (token) {
      fetchAllSurveys();
      fetchClients();
      loadRosterFromBackend();
    }
  }, [token]);

  // Load the shared roster from the backend (overwrites localStorage seed)
  const loadRosterFromBackend = async () => {
    try {
      const res = await fetch(buildApiUrl("/api/operations/potential-clients/roster"), {
        headers: { Authorization: token, "Content-Type": "application/json" },
      });
      if (res.ok) {
        const data = await res.json();
        const backendRoster = Array.isArray(data.roster) ? data.roster.filter((e) => e && e.key && e.name) : [];
        if (backendRoster.length > 0) {
          setPersistedClients(backendRoster);
          rosterSavedToBackend.current = true;
        }
      }
    } catch (err) {
      console.warn("Failed to load roster from backend, using localStorage fallback:", err);
    }
  };

  useEffect(() => {
    if (!surveys.length) return;

    const nextMap = new Map(persistedClients.map((entry) => [entry.key, entry]));
    let hasChanges = false;

    surveys.forEach((survey) => {
      const rawName = getClientName(survey);
      const normalized = normalizeClientName(rawName);
      if (!normalized) return;

      const key = normalized.toLowerCase();
      if (!nextMap.has(key)) {
        nextMap.set(key, { key, name: normalized });
        hasChanges = true;
      }
    });

    if (hasChanges) {
      const updated = Array.from(nextMap.values());
      setPersistedClients(updated);
      // Persist to localStorage as fallback
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(updated));
      } catch (err) {
        console.warn("Failed to persist clients to localStorage:", err);
      }
      // Persist to backend (shared across all users/devices)
      if (token) {
        fetch(buildApiUrl("/api/operations/potential-clients/roster"), {
          method: "PUT",
          headers: { Authorization: token, "Content-Type": "application/json" },
          body: JSON.stringify({ clients: updated }),
        }).catch((err) => console.warn("Failed to save roster to backend:", err));
      }
    }
  }, [surveys, clients, persistedClients]);

  const fetchAllSurveys = async () => {
    setLoading(true);
    setError(null);

    try {
      const cpxResponse = await fetch(buildApiUrl("/cpx/surveys?page=1&page_size=1000&show_all=true"), {
        headers: {
          Authorization: token,
          "Content-Type": "application/json",
        },
      });

      const cintQuery = "/api/cint/surveys?page=1&page_size=1000&show_all=true";
      const cintResponse = await fetch(buildApiUrl(cintQuery), {
        headers: {
          Authorization: token,
          "Content-Type": "application/json",
        },
      });

      let allSurveys = [];

      if (cpxResponse.ok) {
        const cpxData = await cpxResponse.json();
        const cpxSurveys = (cpxData.surveys || []).map((s) => ({ ...s, source: "CPX" }));
        allSurveys = allSurveys.concat(cpxSurveys);
      }

      let cintData = null;
      if (cintResponse.ok) {
        cintData = await cintResponse.json();
      } else {
        try {
          const fallbackUrl = `https://torpedo.cogentixresearch.com${cintQuery}`;
          const fallbackResponse = await fetch(fallbackUrl, {
            headers: {
              Authorization: token,
              "Content-Type": "application/json",
            },
          });
          if (fallbackResponse.ok) {
            cintData = await fallbackResponse.json();
          }
        } catch (fallbackError) {
          console.warn("CINT fallback fetch failed:", fallbackError);
        }
      }

      if (cintData) {
        const cintSurveys = (cintData.surveys || []).map((s) => ({ ...s, source: "CINT" }));
        allSurveys = allSurveys.concat(cintSurveys);
      }

      setSurveys(allSurveys);
    } catch (err) {
      console.error("Error fetching surveys:", err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const fetchClients = async () => {
    try {
      setClients(await fetchAllClients());
    } catch (err) {
      console.error("Error fetching clients:", err);
    }
  };

  const getClientByProvider = (survey) => {
    const source = survey.provider || survey.source || "CPX";
    const client = clients.find((c) => {
      const clientName = (c.company_name || c.name || "").toLowerCase();
      return (
        clientName.includes(source.toLowerCase()) ||
        clientName.includes("cpx research") ||
        source.toLowerCase().includes(clientName.split(" ")[0]?.toLowerCase())
      );
    });
    return client;
  };

  const getClientName = (survey) => {
    if (survey.account_name) {
      return survey.account_name;
    }

    if (survey.client_name) {
      return survey.client_name;
    }

    if (survey.client_id) {
      const client = clients.find((c) => c._id === survey.client_id);
      if (client) return client.company_name || client.name || "N/A";
    }

    const client = getClientByProvider(survey);
    return client?.company_name || client?.name || "N/A";
  };

  const normalizeClientName = (name) => {
    if (!name || name === "N/A") return null;
    const trimmed = String(name).trim();
    return trimmed ? trimmed : null;
  };

  const currentCounts = useMemo(() => {
    const counts = new Map();

    surveys.forEach((survey) => {
      const name = normalizeClientName(getClientName(survey));
      if (!name) return;
      const key = name.toLowerCase();
      counts.set(key, (counts.get(key) || 0) + 1);
    });

    return counts;
  }, [surveys, clients]);

  const clientStats = useMemo(() => {
    let items = persistedClients
      .map((entry) => ({
        name: entry.name,
        count: currentCounts.get(entry.key) || 0,
      }))
      .sort((a, b) => a.name.localeCompare(b.name));

    if (search.trim()) {
      const term = search.trim().toLowerCase();
      items = items.filter((item) => item.name.toLowerCase().includes(term));
    }

    return items;
  }, [persistedClients, currentCounts, search]);

  // Fetch enriched leads data
  const fetchEnrichedLeads = useCallback(async () => {
    try {
      const response = await fetch(buildApiUrl("/api/operations/potential-clients/enriched?limit=500"), {
        headers: {
          Authorization: token,
          "Content-Type": "application/json",
        },
      });

      if (response.ok) {
        const data = await response.json();
        const leadsMap = {};
        (data.leads || []).forEach((lead) => {
          if (lead.company) {
            leadsMap[lead.company.toLowerCase()] = lead;
          }
        });
        setEnrichedLeads(leadsMap);
        setEnrichmentStats(data.stats);
      }
    } catch (err) {
      console.error("Error fetching enriched leads:", err);
    }
  }, [token]);

  // Fetch enriched data when component mounts
  useEffect(() => {
    if (token) {
      fetchEnrichedLeads();
    }
  }, [token, fetchEnrichedLeads]);

  // Enrich a single company
  const enrichCompany = async (companyName) => {
    setEnrichingCompany(companyName);
    try {
      const response = await fetch(buildApiUrl("/api/operations/potential-clients/enrich"), {
        method: "POST",
        headers: {
          Authorization: token,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          company_name: companyName,
          force_refresh: false,
        }),
      });

      if (response.ok) {
        const data = await response.json();
        setEnrichedLeads((prev) => ({
          ...prev,
          [companyName.toLowerCase()]: data,
        }));
        setSelectedClient(data);
        setShowEnrichmentPanel(true);
      } else {
        const errorData = await response.json();
        alert(`Enrichment failed: ${errorData.detail || "Unknown error"}`);
      }
    } catch (err) {
      console.error("Error enriching company:", err);
      alert(`Enrichment error: ${err.message}`);
    } finally {
      setEnrichingCompany(null);
    }
  };

  // Auto-enrich all new companies
  const autoEnrichAll = async () => {
    const companyNames = clientStats.map((c) => c.name);
    if (companyNames.length === 0) return;

    setAutoEnriching(true);
    try {
      const response = await fetch(buildApiUrl("/api/operations/potential-clients/auto-enrich"), {
        method: "POST",
        headers: {
          Authorization: token,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ company_names: companyNames }),
      });

      if (response.ok) {
        const data = await response.json();
        alert(`Auto-enrichment complete!\nEnriched: ${data.enriched}\nRemaining: ${data.remaining}`);
        fetchEnrichedLeads();
      }
    } catch (err) {
      console.error("Error auto-enriching:", err);
      alert(`Auto-enrichment error: ${err.message}`);
    } finally {
      setAutoEnriching(false);
    }
  };

  // View enriched data for a client
  const viewEnrichment = (clientName) => {
    const enriched = enrichedLeads[clientName.toLowerCase()];
    if (enriched) {
      setSelectedClient(enriched);
      setShowEnrichmentPanel(true);
    }
  };

  // Check if a client is enriched
  const isEnriched = (clientName) => {
    return !!enrichedLeads[clientName.toLowerCase()];
  };

  if (!user) {
    return <div className="potential-clients-page">Please login to access Potential Clients.</div>;
  }

  return (
    <div className="potential-clients-page">
      <div className="page-header">
        <div>
          <h1>Potential Client</h1>
          <p>Unique client names extracted from the Study Pool.</p>
        </div>
        <div className="header-actions">
          <button 
            className="auto-enrich-button" 
            onClick={autoEnrichAll} 
            disabled={autoEnriching || loading}
            title="Auto-enrich all new companies using AI web search"
          >
            {autoEnriching ? "Auto Enriching..." : "Auto Enrich All"}
          </button>
          <button className="refresh-button" onClick={fetchAllSurveys} disabled={loading}>
            {loading ? "Refreshing..." : "Refresh"}
          </button>
        </div>
      </div>

      {enrichmentStats && (
        <div className="enrichment-stats-bar">
          <span>Enriched: {enrichmentStats.total_enriched}</span>
          <span>High Confidence: {enrichmentStats.high_confidence_count}</span>
          <span>Last 24h: {enrichmentStats.enrichments_last_24h}</span>
        </div>
      )}

      <div className="page-controls">
        <input
          type="text"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search client name"
          className="search-input"
        />
        <div className="count-pill">{clientStats.length} clients</div>
      </div>

      {error && (
        <div className="error-card">
          <div>Failed to load clients.</div>
          <div className="error-detail">{error}</div>
        </div>
      )}

      <div className="table-card">
        <table className="data-table">
          <thead>
            <tr>
              <th>Client Name</th>
              <th>Surveys</th>
              <th>Enrichment</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {clientStats.map((client) => {
              const enriched = enrichedLeads[client.name.toLowerCase()];
              return (
                <tr key={client.name} className={enriched ? "enriched-row" : ""}>
                  <td>
                    <span 
                      className="client-name-link"
                      onClick={() => enriched ? viewEnrichment(client.name) : enrichCompany(client.name)}
                    >
                      {client.name}
                    </span>
                  </td>
                  <td>{client.count}</td>
                  <td>
                    {enriched ? (
                      <span className="enrichment-badge enriched">
                        ✓ {Math.round((enriched.confidence_score || 0) * 100)}%
                      </span>
                    ) : (
                      <span className="enrichment-badge not-enriched">Not Enriched</span>
                    )}
                  </td>
                  <td>
                    {enrichingCompany === client.name ? (
                      <span className="enriching-spinner">Enriching...</span>
                    ) : enriched ? (
                      <button 
                        className="view-button" 
                        onClick={() => viewEnrichment(client.name)}
                      >
                        View
                      </button>
                    ) : (
                      <button 
                        className="enrich-button" 
                        onClick={() => enrichCompany(client.name)}
                      >
                        Enrich
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
            {!loading && clientStats.length === 0 && (
              <tr>
                <td colSpan={4} className="empty-row">
                  No client names found in the Study Pool.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Enrichment Panel Modal */}
      {showEnrichmentPanel && selectedClient && (
        <div className="enrichment-modal-overlay" onClick={() => setShowEnrichmentPanel(false)}>
          <div className="enrichment-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>{selectedClient.company}</h2>
              <button className="close-button" onClick={() => setShowEnrichmentPanel(false)}>×</button>
            </div>
            
            <div className="modal-content">
              <div className="enrichment-section">
                <h3>Lead Information</h3>
                <div className="field-grid">
                  <div className="field">
                    <label>Lead Stage</label>
                    <span>{selectedClient.lead_stage || "—"}</span>
                  </div>
                  <div className="field">
                    <label>Lead Name</label>
                    <span>{selectedClient.lead_name || "—"}</span>
                  </div>
                  <div className="field">
                    <label>Email</label>
                    <span>{selectedClient.email || "—"}</span>
                  </div>
                  <div className="field">
                    <label>LinkedIn</label>
                    <span>
                      {selectedClient.linkedin_url ? (
                        <a href={selectedClient.linkedin_url} target="_blank" rel="noopener noreferrer">
                          View Profile
                        </a>
                      ) : "—"}
                    </span>
                  </div>
                  <div className="field">
                    <label>Title</label>
                    <span>{selectedClient.title || "—"}</span>
                  </div>
                  <div className="field">
                    <label>Location</label>
                    <span>{selectedClient.location || "—"}</span>
                  </div>
                  <div className="field">
                    <label>Lead Source</label>
                    <span>{selectedClient.lead_source || "Cint API client list"}</span>
                  </div>
                  <div className="field">
                    <label>Seniority Level</label>
                    <span>{selectedClient.seniority_level || "—"}</span>
                  </div>
                  <div className="field">
                    <label>Department</label>
                    <span>{selectedClient.department || "—"}</span>
                  </div>
                  <div className="field">
                    <label>Persona</label>
                    <span>{selectedClient.persona || "—"}</span>
                  </div>
                  <div className="field">
                    <label>Buying Role</label>
                    <span>{selectedClient.buying_role || "—"}</span>
                  </div>
                </div>
              </div>

              <div className="enrichment-section">
                <h3>Company Details</h3>
                <div className="field-grid">
                  <div className="field">
                    <label>Company Founded</label>
                    <span>{selectedClient.company_founded || "—"}</span>
                  </div>
                  <div className="field">
                    <label>Headquarters</label>
                    <span>{selectedClient.company_headquarters || "—"}</span>
                  </div>
                  <div className="field">
                    <label>Company LinkedIn</label>
                    <span>
                      {selectedClient.company_linkedin_url ? (
                        <a href={selectedClient.company_linkedin_url} target="_blank" rel="noopener noreferrer">
                          View Company
                        </a>
                      ) : "—"}
                    </span>
                  </div>
                  <div className="field">
                    <label>Employee Count</label>
                    <span>{selectedClient.company_employee_count_range || "—"}</span>
                  </div>
                  <div className="field">
                    <label>Industry</label>
                    <span>{selectedClient.company_industry || "—"}</span>
                  </div>
                  <div className="field">
                    <label>Company Size</label>
                    <span>{selectedClient.company_size || "—"}</span>
                  </div>
                  <div className="field">
                    <label>Company Type</label>
                    <span>{selectedClient.company_type || "—"}</span>
                  </div>
                  <div className="field">
                    <label>Revenue Range</label>
                    <span>{selectedClient.company_revenue_range || "—"}</span>
                  </div>
                  <div className="field">
                    <label>Domain</label>
                    <span>{selectedClient.company_domain || "—"}</span>
                  </div>
                  <div className="field">
                    <label>Website</label>
                    <span>
                      {selectedClient.company_website ? (
                        <a href={selectedClient.company_website} target="_blank" rel="noopener noreferrer">
                          {selectedClient.company_website}
                        </a>
                      ) : "—"}
                    </span>
                  </div>
                </div>
              </div>

              {selectedClient.summary && (
                <div className="enrichment-section">
                  <h3>Summary</h3>
                  <p>{selectedClient.summary}</p>
                </div>
              )}

              <div className="enrichment-meta">
                <span>Confidence: {Math.round((selectedClient.confidence_score || 0) * 100)}%</span>
                <span>Source: {selectedClient.enrichment_source}</span>
                {selectedClient.enriched_at && (
                  <span>Updated: {new Date(selectedClient.enriched_at).toLocaleDateString()}</span>
                )}
              </div>

              {selectedClient.citations && selectedClient.citations.length > 0 && (
                <div className="enrichment-section">
                  <h3>Sources</h3>
                  <ul className="citations-list">
                    {selectedClient.citations.slice(0, 5).map((cite, idx) => (
                      <li key={idx}>
                        <a href={cite.url} target="_blank" rel="noopener noreferrer">
                          {cite.title || cite.url}
                        </a>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>

            <div className="modal-footer">
              <button 
                className="refresh-enrichment-button"
                onClick={() => enrichCompany(selectedClient.company)}
                disabled={enrichingCompany === selectedClient.company}
              >
                {enrichingCompany === selectedClient.company ? "Refreshing..." : "Refresh Data"}
              </button>
              <button className="close-modal-button" onClick={() => setShowEnrichmentPanel(false)}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default PotentialClients;
