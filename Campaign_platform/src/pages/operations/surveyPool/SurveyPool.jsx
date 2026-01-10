import React, { useState, useEffect, useMemo } from 'react';
import { useAuth } from '../../../hooks/useAuth';
import { API_BASE_URL } from '../../../config';
import './SurveyPool.css';

export default function SurveyPool() {
  const { user, token } = useAuth();
  const [activeTab, setActiveTab] = useState('cpx'); // 'cpx' or 'cint'
  const [surveys, setSurveys] = useState([]);
  const [cintSurveys, setCintSurveys] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [cintLastUpdated, setCintLastUpdated] = useState(null);
  const [recordsPerPage, setRecordsPerPage] = useState(20);
  const [currentPage, setCurrentPage] = useState(1);
  const [cintCurrentPage, setCintCurrentPage] = useState(1);
  const [selectedSurvey, setSelectedSurvey] = useState(null);
  const [showDetailsModal, setShowDetailsModal] = useState(false);
  const [trafficStats, setTrafficStats] = useState({}); // survey_id -> {clicks, completes}
  const [clients, setClients] = useState([]); // List of clients for client name lookup
  const [cpxTotal, setCpxTotal] = useState(0); // Total CPX surveys from API
  const [cintTotal, setCintTotal] = useState(0); // Total CINT surveys from API

  // Fetch surveys on mount
  useEffect(() => {
    if (token) {
      fetchSurveys();
      fetchCintSurveys();
      fetchTrafficStats();
      fetchClients();
    }
  }, [token]);

  // Auto-refresh every 30 seconds
  useEffect(() => {
    if (!token) return;
    const interval = setInterval(() => {
      if (activeTab === 'cpx') {
        fetchSurveys();
      } else {
        fetchCintSurveys();
      }
      fetchTrafficStats();
    }, 30000); // 30 seconds
    return () => clearInterval(interval);
  }, [token, activeTab]);

  const fetchSurveys = async (pageSize = 20) => {
    setLoading(true);
    setError(null);
    
    try {
      // Fetch only the current page initially for faster load
      const response = await fetch(`${API_BASE_URL}/cpx/surveys?page=${currentPage}&page_size=${pageSize}`, {
        headers: {
          'Authorization': token,
          'Content-Type': 'application/json',
        },
      });

      if (!response.ok) {
        throw new Error('Failed to fetch surveys');
      }

      const data = await response.json();
      setSurveys(data.surveys || []);
      setCpxTotal(data.total || data.surveys?.length || 0);
      if (data.last_updated) {
        setLastUpdated(data.last_updated);
      }
    } catch (err) {
      console.error('Error fetching surveys:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // Fetch Cint surveys from cache
  const fetchCintSurveys = async (pageSize = 100) => {
    setLoading(true);
    setError(null);
    
    try {
      // Fetch with larger page size to get all surveys
      // Note: API_BASE_URL already ends with /api, so we use /cint/surveys
      const response = await fetch(`${API_BASE_URL}/cint/surveys?page=1&page_size=1000`, {
        headers: {
          'Authorization': token,
          'Content-Type': 'application/json',
        },
      });

      if (!response.ok) {
        throw new Error('Failed to fetch Cint surveys');
      }

      const data = await response.json();
      setCintSurveys(data.surveys || []);
      setCintTotal(data.total || data.surveys?.length || 0);
      setCintLastUpdated(new Date().toISOString());
    } catch (err) {
      console.error('Error fetching Cint surveys:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // Fetch traffic stats for all surveys
  const fetchTrafficStats = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/traffic/surveys-stats`, {
        headers: {
          'Authorization': token,
          'Content-Type': 'application/json',
        },
      });

      if (response.ok) {
        const data = await response.json();
        setTrafficStats(data.surveys_stats || {});
      }
    } catch (err) {
      console.error('Error fetching traffic stats:', err);
    }
  };

  // Fetch clients for client name lookup
  const fetchClients = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/finance/finance/customers/`, {
        headers: {
          'Authorization': token,
          'Content-Type': 'application/json',
        },
      });

      if (response.ok) {
        const data = await response.json();
        setClients(Array.isArray(data) ? data : data.customers || []);
      }
    } catch (err) {
      console.error('Error fetching clients:', err);
    }
  };

  // Get client by provider/source name (e.g., "CPX" matches client "CPX Research")
  const getClientByProvider = (survey) => {
    const source = survey.provider || survey.source || 'CPX';
    // Look for a client whose company_name or name contains the source (e.g., "CPX Research" contains "CPX")
    const client = clients.find(c => {
      const clientName = (c.company_name || c.name || '').toLowerCase();
      return clientName.includes(source.toLowerCase()) || 
             clientName.includes('cpx research') ||
             source.toLowerCase().includes(clientName.split(' ')[0]?.toLowerCase());
    });
    return client;
  };

  // Get client by name (for projects that store client name directly)
  const getClientByName = (clientName) => {
    if (!clientName) return null;
    const lowerName = clientName.toLowerCase();
    return clients.find(c => {
      const name = (c.company_name || c.name || '').toLowerCase();
      return name === lowerName || name.includes(lowerName) || lowerName.includes(name);
    });
  };

  // Get client name - handles both CPX surveys and Projects
  const getClientName = (survey) => {
    // For CINT surveys, account_name contains the buyer name
    if (survey.account_name) {
      return survey.account_name;
    }
    
    // For projects, client_name is stored directly
    if (survey.client_name) {
      return survey.client_name;
    }
    
    // If survey has a direct client_id, use that
    if (survey.client_id) {
      const client = clients.find(c => c._id === survey.client_id);
      if (client) return client.company_name || client.name || 'N/A';
    }
    
    // Otherwise, look up by provider/source name (for CPX surveys)
    const client = getClientByProvider(survey);
    return client?.company_name || client?.name || 'N/A';
  };

  // Map customer_type to display type
  const mapCustomerType = (customerType) => {
    if (customerType === 'business') return 'Offline';
    if (customerType === 'api') return 'API';
    return 'Online';
  };

  // Get client type from the Clients module
  const getClientType = (survey) => {
    // For CINT surveys (has account_name field), return "ONLINE"
    if (survey.account_name) {
      return 'ONLINE';
    }
    
    // For CPX/API surveys, return "API" (they come from API)
    if (survey.provider === 'CPX' || survey.source === 'CPX') {
      return 'ONLINE';
    }
    
    // For projects, look up client by client_name
    if (survey.client_name) {
      const client = getClientByName(survey.client_name);
      if (client) {
        return mapCustomerType(client.customer_type);
      }
      return 'Offline'; // Default for projects
    }
    
    // If survey has a direct client_id, use that client's type
    if (survey.client_id) {
      const client = clients.find(c => c._id === survey.client_id);
      if (client) {
        return mapCustomerType(client.customer_type);
      }
    }
    
    // Otherwise, look up by provider/source name
    const client = getClientByProvider(survey);
    if (client) {
      return mapCustomerType(client.customer_type);
    }
    
    // Default fallback
    return 'Online';
  };

  // Manual refresh handler
  const handleRefresh = async () => {
    setLoading(true);
    try {
      const response = await fetch(`${API_BASE_URL}/cpx/refresh`, {
        method: 'POST',
        headers: {
          'Authorization': token,
          'Content-Type': 'application/json',
        },
      });

      if (!response.ok) {
        throw new Error('Failed to refresh CPX inventory');
      }

      // Fetch latest surveys and stats
      await fetchSurveys();
      await fetchTrafficStats();
      setCurrentPage(1);
    } catch (err) {
      console.error('Error refreshing CPX inventory:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // Manual refresh handler for Cint
  const handleRefreshCint = async () => {
    setLoading(true);
    try {
      // Note: Cint surveys are automatically updated via webhook every 15 seconds
      // This just refreshes the local cache
      await fetchCintSurveys();
      setCintCurrentPage(1);
    } catch (err) {
      console.error('Error refreshing Cint surveys:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // Apply survey filters - delete CINT surveys that don't meet criteria from Settings
  const handleApplyFilters = async () => {
    if (!window.confirm('⚠️ Apply survey filters from Settings?\\n\\nThis will DELETE all CINT surveys that do not meet the criteria (max LOI, min CPI).\\n\\nThis action cannot be undone!')) {
      return;
    }
    
    setLoading(true);
    try {
      const response = await fetch(`${API_BASE_URL}/cint/surveys/apply-filters`, {
        method: 'POST',
        headers: {
          'Authorization': token,
          'Content-Type': 'application/json',
        },
      });

      if (!response.ok) {
        throw new Error('Failed to apply filters');
      }

      const data = await response.json();
      
      if (data.success) {
        alert(`✅ ${data.message}\\n\\nTotal before: ${data.total_before}\\nTotal after: ${data.total_after}\\nDeleted: ${data.deleted_count}`);
        // Refresh the CINT surveys list
        await fetchCintSurveys();
      } else {
        throw new Error(data.message || 'Unknown error');
      }
    } catch (err) {
      console.error('Error applying filters:', err);
      setError(err.message);
      alert(`❌ Error: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  // Client-side pagination for CPX
  const paginatedSurveys = useMemo(() => {
    const startIndex = (currentPage - 1) * recordsPerPage;
    const endIndex = startIndex + recordsPerPage;
    return surveys.slice(startIndex, endIndex);
  }, [surveys, currentPage, recordsPerPage]);

  const totalPages = Math.ceil(surveys.length / recordsPerPage);

  // Client-side pagination for Cint
  const paginatedCintSurveys = useMemo(() => {
    const startIndex = (cintCurrentPage - 1) * recordsPerPage;
    const endIndex = startIndex + recordsPerPage;
    return cintSurveys.slice(startIndex, endIndex);
  }, [cintSurveys, cintCurrentPage, recordsPerPage]);

  const cintTotalPages = Math.ceil(cintSurveys.length / recordsPerPage);

  // Get current surveys to display based on active tab
  const displaySurveys = activeTab === 'cpx' ? paginatedSurveys : paginatedCintSurveys;
  const displayTotalPages = activeTab === 'cpx' ? totalPages : cintTotalPages;
  const displayTotal = activeTab === 'cpx' ? surveys.length : cintSurveys.length;
  const displayLastUpdated = activeTab === 'cpx' ? lastUpdated : cintLastUpdated;
  const currentPageNum = activeTab === 'cpx' ? currentPage : cintCurrentPage;

  // Handle survey click to show details
  const handleSurveyClick = (survey) => {
    setSelectedSurvey(survey);
    setShowDetailsModal(true);
  };

  // Close details modal
  const closeDetailsModal = () => {
    setShowDetailsModal(false);
    setSelectedSurvey(null);
  };

  // Format date/time for display
  const formatDateTime = (dateString) => {
    if (!dateString) return 'N/A';
    const date = new Date(dateString);
    return date.toLocaleString('en-IN', {
      timeZone: 'Asia/Kolkata',
      day: '2-digit',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: true
    });
  };

  // Get survey name - for CPX surveys, use survey_id as name; for Cint, use survey_id
  const getSurveyName = (survey) => {
    // For CINT surveys, use survey_id as the name/link
    if (survey.account_name) {
      return survey.survey_id || survey._id || 'N/A';
    }
    const source = survey.provider || survey.source || 'CPX';
    if (source === 'CPX') {
      return survey.survey_id || survey._id || 'N/A';
    }
    return survey.name || survey.survey_name || survey.title || 'N/A';
  };

  // Extract country code from country_language (e.g., "eng_us" -> "US", "eng_gb" -> "GB")
  const getCountryCode = (survey) => {
    // First check direct country or country_code fields
    if (survey.country && survey.country.length <= 3) {
      return survey.country.toUpperCase();
    }
    if (survey.country_code && survey.country_code.length <= 3) {
      return survey.country_code.toUpperCase();
    }
    
    // For CINT surveys, parse country_language field (e.g., "eng_us" -> "US")
    const countryLanguage = survey.country_language;
    if (countryLanguage && typeof countryLanguage === 'string') {
      // Format is typically "lang_country" e.g., "eng_us", "eng_gb", "eng_in"
      const parts = countryLanguage.split('_');
      if (parts.length >= 2) {
        return parts[parts.length - 1].toUpperCase(); // Get last part and uppercase
      }
      // If format is different, just uppercase it
      return countryLanguage.toUpperCase();
    }
    
    return 'N/A';
  };

  // Get LOI (Length of Interview) in minutes
  const getLOI = (survey) => {
    // For CINT surveys, use bid_length_of_interview
    if (survey.bid_length_of_interview && survey.bid_length_of_interview > 0) {
      return survey.bid_length_of_interview;
    }
    // Fallback to length_of_interview or loi
    return survey.length_of_interview || survey.loi || 'N/A';
  };

  // Get Payout/CPI in USD
  const getPayout = (survey) => {
    // For CINT surveys, revenue_per_interview is an object {value, currency_code}
    if (survey.revenue_per_interview) {
      const rpi = survey.revenue_per_interview;
      if (typeof rpi === 'object' && rpi.value) {
        return `$${parseFloat(rpi.value).toFixed(2)}`;
      }
      if (typeof rpi === 'number') {
        return `$${rpi.toFixed(2)}`;
      }
    }
    // Fallback to payout or cpi fields
    if (survey.payout !== undefined && survey.payout !== null) {
      return `$${parseFloat(survey.payout).toFixed(2)}`;
    }
    if (survey.cpi !== undefined && survey.cpi !== null) {
      return `$${parseFloat(survey.cpi).toFixed(2)}`;
    }
    return '$0.00';
  };

  // Calculate conversion rate properly (stored as decimal, display as percentage)
  const getConversionRate = (survey) => {
    // For CINT surveys, use 'conversion' field (0.0 to 1.0)
    if (survey.conversion !== undefined && survey.conversion !== null) {
      const rate = parseFloat(survey.conversion);
      if (rate > 1) {
        return `${rate.toFixed(1)}%`;
      }
      return `${(rate * 100).toFixed(1)}%`;
    }
    
    // Fallback to conversion_rate
    const rate = survey.conversion_rate;
    if (rate === null || rate === undefined) return 'N/A';
    // If rate is already > 1, it's likely already a percentage
    if (rate > 1) {
      return `${rate.toFixed(1)}%`;
    }
    // Otherwise multiply by 100 to get percentage
    return `${(rate * 100).toFixed(1)}%`;
  };

  // Get date/time for survey (handles CINT and CPX formats)
  const getSurveyDateTime = (survey) => {
    // For CINT surveys, use received_at or last_updated_at
    return survey.received_at || survey.last_updated_at || survey.last_updated || survey.inserted_at;
  };

  if (!user) {
    return <div className="survey-pool-container">Please login to access Survey Pool.</div>;
  }

  return (
    <div className="survey-pool-container">
      <div className="survey-pool-header">
        <div>
          <h1>📋 Survey Pool</h1>
          <p>CPX & Cint Research survey inventory</p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
          {displayLastUpdated && (
            <span style={{ fontSize: '0.85rem', color: '#666' }}>
              Last updated: {new Date(displayLastUpdated).toLocaleString()}
            </span>
          )}
          {activeTab === 'cint' && (
            <button
              onClick={handleApplyFilters}
              disabled={loading}
              className="refresh-btn"
              style={{ background: '#dc2626', borderColor: '#dc2626' }}
              title="Delete CINT surveys that don't meet the filter criteria from Settings"
            >
              {loading ? '⏳ Applying...' : '🗑️ Apply Filters'}
            </button>
          )}
          <button
            onClick={activeTab === 'cpx' ? handleRefresh : handleRefreshCint}
            disabled={loading}
            className="refresh-btn"
          >
            {loading ? '⏳ Refreshing...' : '🔄 Refresh'}
          </button>
        </div>
      </div>

      {/* Survey Source Tabs */}
      <div className="survey-tabs" style={{ borderBottom: '1px solid #ddd', marginBottom: '1rem' }}>
        <button
          className={`tab-btn ${activeTab === 'cpx' ? 'active' : ''}`}
          onClick={() => {
            setActiveTab('cpx');
            setCurrentPage(1);
          }}
          style={{
            padding: '10px 20px',
            border: 'none',
            background: 'none',
            cursor: 'pointer',
            borderBottom: activeTab === 'cpx' ? '3px solid #667eea' : 'none',
            color: activeTab === 'cpx' ? '#667eea' : '#666',
            fontWeight: activeTab === 'cpx' ? 'bold' : 'normal',
            fontSize: '15px',
          }}
        >
          📊 CPX Research ({cpxTotal || surveys.length})
        </button>
        <button
          className={`tab-btn ${activeTab === 'cint' ? 'active' : ''}`}
          onClick={() => {
            setActiveTab('cint');
            setCintCurrentPage(1);
          }}
          style={{
            padding: '10px 20px',
            border: 'none',
            background: 'none',
            cursor: 'pointer',
            borderBottom: activeTab === 'cint' ? '3px solid #667eea' : 'none',
            color: activeTab === 'cint' ? '#667eea' : '#666',
            fontWeight: activeTab === 'cint' ? 'bold' : 'normal',
            fontSize: '15px',
          }}
        >
          🎯 Cint Research ({cintTotal || cintSurveys.length})
        </button>
      </div>

      {/* Loading State */}
      {loading && displaySurveys.length === 0 && !error && (
        <div className="survey-pool-loading">
          <div className="loading-spinner"></div>
          <p>⏳ Loading surveys...</p>
        </div>
      )}

      {/* Error State */}
      {error && (
        <div className="survey-pool-error">
          <p>❌ Failed to fetch surveys</p>
          <p className="error-detail">{error}</p>
          <button onClick={activeTab === 'cpx' ? handleRefresh : handleRefreshCint} className="retry-btn">
            🔄 Retry
          </button>
        </div>
      )}

      {/* Survey Table */}
      {displaySurveys.length > 0 && (
        <>
          <div className="survey-table-container">
            <table className="survey-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Client Name</th>
                  <th>Client Type</th>
                  <th>Country</th>
                  <th>LOI (min)</th>
                  <th>Payout</th>
                  <th>Conversion</th>
                  <th>Clicks</th>
                  <th>Completes</th>
                  <th>Date/Time</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {displaySurveys.map((survey, index) => {
                  const surveyId = survey.survey_id || survey._id;
                  const stats = trafficStats[surveyId] || { clicks: 0, completes: 0 };
                  return (
                  <tr key={survey._id || survey.survey_id || index}>
                    <td>
                      <span 
                        className="survey-link" 
                        onClick={() => handleSurveyClick(survey)}
                        style={{ cursor: 'pointer', color: '#667eea', textDecoration: 'underline' }}
                      >
                        {getSurveyName(survey)}
                      </span>
                    </td>
                    <td>{getClientName(survey)}</td>
                    <td>
                      <span className="source-badge">
                        {getClientType(survey)}
                      </span>
                    </td>
                    <td>{getCountryCode(survey)}</td>
                    <td>{getLOI(survey)}</td>
                    <td>{getPayout(survey)}</td>
                    <td>{getConversionRate(survey)}</td>
                    <td>{stats.clicks}</td>
                    <td>{stats.completes}</td>
                    <td>{formatDateTime(getSurveyDateTime(survey))}</td>
                    <td>
                      <span className={`status-badge ${(survey.status === 'active' || survey.is_active) ? 'active' : 'inactive'}`}>
                        {(survey.status || survey.is_active) ? 'active' : 'inactive'}
                      </span>
                    </td>
                  </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Pagination Controls */}
          {displayTotal > recordsPerPage && (
            <div className="survey-pool-pagination">
              <div className="pagination-info">
                Showing {(currentPageNum - 1) * recordsPerPage + 1} to{' '}
                {Math.min(currentPageNum * recordsPerPage, displayTotal)} of {displayTotal} surveys
              </div>

              <div className="pagination-controls">
                <select
                  value={recordsPerPage}
                  onChange={(e) => {
                    setRecordsPerPage(Number(e.target.value));
                    if (activeTab === 'cpx') setCurrentPage(1);
                    else setCintCurrentPage(1);
                  }}
                  className="records-per-page"
                >
                  <option value={10}>10 per page</option>
                  <option value={20}>20 per page</option>
                  <option value={50}>50 per page</option>
                  <option value={100}>100 per page</option>
                </select>

                <div className="pagination-buttons">
                  <button
                    onClick={() => activeTab === 'cpx' ? setCurrentPage(1) : setCintCurrentPage(1)}
                    disabled={currentPageNum === 1 || loading}
                    className="pagination-btn"
                  >
                    ⬅️ First
                  </button>
                  <button
                    onClick={() => activeTab === 'cpx' ? setCurrentPage(currentPageNum - 1) : setCintCurrentPage(cintCurrentPage - 1)}
                    disabled={currentPageNum === 1 || loading}
                    className="pagination-btn"
                  >
                    ← Previous
                  </button>

                  <span className="pagination-page-info">
                    Page {currentPageNum} of {displayTotalPages}
                  </span>

                  <button
                    onClick={() => activeTab === 'cpx' ? setCurrentPage(currentPageNum + 1) : setCintCurrentPage(cintCurrentPage + 1)}
                    disabled={currentPageNum === displayTotalPages || loading}
                    className="pagination-btn"
                  >
                    Next →
                  </button>
                  <button
                    onClick={() => activeTab === 'cpx' ? setCurrentPage(displayTotalPages) : setCintCurrentPage(cintTotalPages)}
                    disabled={currentPageNum === displayTotalPages || loading}
                    className="pagination-btn"
                  >
                    Last ➡️
                  </button>
                </div>
              </div>
            </div>
          )}
        </>
      )}

      {displaySurveys.length === 0 && !error && !loading && (
        <div className="survey-pool-empty">
          <div className="empty-icon">📭</div>
          <p className="empty-title">No surveys available</p>
          <p className="empty-subtitle">Refresh to check for new surveys from {activeTab === 'cpx' ? 'CPX Research' : 'Cint Research'}.</p>
        </div>
      )}

      {/* Survey Details Modal */}
      {showDetailsModal && selectedSurvey && (
        <div className="survey-details-modal-overlay" onClick={closeDetailsModal}>
          <div className="survey-details-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>📋 Survey Details</h2>
              <button className="modal-close-btn" onClick={closeDetailsModal}>✕</button>
            </div>
            <div className="modal-body">
              <div className="detail-grid">
                <div className="detail-item">
                  <span className="detail-label">Survey ID</span>
                  <span className="detail-value">{selectedSurvey.survey_id || selectedSurvey._id}</span>
                </div>
                <div className="detail-item">
                  <span className="detail-label">Name</span>
                  <span className="detail-value">{selectedSurvey.survey_name || getSurveyName(selectedSurvey)}</span>
                </div>
                <div className="detail-item">
                  <span className="detail-label">Source</span>
                  <span className="detail-value" style={{ 
                    color: selectedSurvey.account_name ? '#10b981' : '#667eea',
                    fontWeight: 'bold'
                  }}>
                    {selectedSurvey.account_name ? '🎯 CINT Research' : '📊 CPX Research'}
                  </span>
                </div>
                <div className="detail-item">
                  <span className="detail-label">Country</span>
                  <span className="detail-value">{getCountryCode(selectedSurvey)}</span>
                </div>
                <div className="detail-item">
                  <span className="detail-label">Length of Interview</span>
                  <span className="detail-value">{getLOI(selectedSurvey)} minutes</span>
                </div>
                <div className="detail-item">
                  <span className="detail-label">Payout</span>
                  <span className="detail-value" style={{ color: '#10b981', fontWeight: 'bold' }}>{getPayout(selectedSurvey)}</span>
                </div>
                <div className="detail-item">
                  <span className="detail-label">Conversion Rate</span>
                  <span className="detail-value">{getConversionRate(selectedSurvey)}</span>
                </div>
                <div className="detail-item">
                  <span className="detail-label">Category/Industry</span>
                  <span className="detail-value">{selectedSurvey.industry || selectedSurvey.category || 'N/A'}</span>
                </div>
                <div className="detail-item">
                  <span className="detail-label">Status</span>
                  <span className={`status-badge ${selectedSurvey.is_active || selectedSurvey.is_live ? 'active' : 'inactive'}`}>
                    {selectedSurvey.is_active || selectedSurvey.is_live ? '✅ Active' : '❌ Inactive'}
                  </span>
                </div>
                <div className="detail-item">
                  <span className="detail-label">Date/Time Added</span>
                  <span className="detail-value">{formatDateTime(getSurveyDateTime(selectedSurvey))}</span>
                </div>
                
                {/* CINT-specific fields */}
                {selectedSurvey.account_name && (
                  <>
                    <div className="detail-item">
                      <span className="detail-label">Buyer/Account</span>
                      <span className="detail-value">{selectedSurvey.account_name}</span>
                    </div>
                    {selectedSurvey.buyer_id && (
                      <div className="detail-item">
                        <span className="detail-label">Buyer ID</span>
                        <span className="detail-value">{selectedSurvey.buyer_id}</span>
                      </div>
                    )}
                    {selectedSurvey.bid_incidence !== undefined && (
                      <div className="detail-item">
                        <span className="detail-label">Incidence Rate</span>
                        <span className="detail-value">{selectedSurvey.bid_incidence}%</span>
                      </div>
                    )}
                    {selectedSurvey.total_remaining !== undefined && (
                      <div className="detail-item">
                        <span className="detail-label">Quota Remaining</span>
                        <span className="detail-value">{selectedSurvey.total_remaining}</span>
                      </div>
                    )}
                    {selectedSurvey.study_type && (
                      <div className="detail-item">
                        <span className="detail-label">Study Type</span>
                        <span className="detail-value">{selectedSurvey.study_type}</span>
                      </div>
                    )}
                    {selectedSurvey.collects_pii !== undefined && (
                      <div className="detail-item">
                        <span className="detail-label">Collects PII</span>
                        <span className="detail-value">{selectedSurvey.collects_pii ? 'Yes' : 'No'}</span>
                      </div>
                    )}
                    {selectedSurvey.revenue_per_click !== undefined && (
                      <div className="detail-item">
                        <span className="detail-label">Revenue Per Click</span>
                        <span className="detail-value">${parseFloat(selectedSurvey.revenue_per_click).toFixed(2)}</span>
                      </div>
                    )}
                    {selectedSurvey.mobile_conversion !== undefined && (
                      <div className="detail-item">
                        <span className="detail-label">Mobile Conversion</span>
                        <span className="detail-value">{(selectedSurvey.mobile_conversion * 100).toFixed(1)}%</span>
                      </div>
                    )}
                  </>
                )}
              </div>
              
              {selectedSurvey.title && selectedSurvey.title !== getSurveyName(selectedSurvey) && (
                <div className="detail-item full-width">
                  <span className="detail-label">Title</span>
                  <span className="detail-value">{selectedSurvey.title}</span>
                </div>
              )}
              
              {/* CPX Live Link - Direct link from CPX API */}
              {selectedSurvey.live_link && !selectedSurvey.account_name && (
                <div className="detail-item full-width" style={{ marginTop: '16px' }}>
                  <span className="detail-label">🔗 Live Link (CPX)</span>
                  <div className="entry-link-container">
                    <input 
                      type="text" 
                      readOnly 
                      value={selectedSurvey.live_link} 
                      className="entry-link-input"
                      onClick={(e) => e.target.select()}
                    />
                    <button 
                      className="copy-link-btn"
                      onClick={() => navigator.clipboard.writeText(selectedSurvey.live_link)}
                      title="Copy to clipboard"
                    >
                      📋 Copy
                    </button>
                    <a 
                      href={selectedSurvey.live_link} 
                      target="_blank" 
                      rel="noopener noreferrer"
                      className="open-link-btn"
                      title="Open in new tab"
                    >
                      🔗 Open
                    </a>
                  </div>
                </div>
              )}
              
              {/* CPX Entry Link Template */}
              {selectedSurvey.entry_link && !selectedSurvey.account_name && (
                <div className="detail-item full-width">
                  <span className="detail-label">🎯 Entry Link Template (CPX)</span>
                  <div className="entry-link-container">
                    <input 
                      type="text" 
                      readOnly 
                      value={selectedSurvey.entry_link} 
                      className="entry-link-input"
                      onClick={(e) => e.target.select()}
                    />
                    <button 
                      className="copy-link-btn"
                      onClick={() => navigator.clipboard.writeText(selectedSurvey.entry_link)}
                      title="Copy to clipboard"
                    >
                      📋 Copy
                    </button>
                  </div>
                  <div style={{ color: '#888', marginTop: '8px', fontSize: '0.85rem', lineHeight: '1.5' }}>
                    <strong>Replace placeholders:</strong>
                    <ul style={{ margin: '4px 0 0 16px', padding: 0, listStyle: 'none' }}>
                      <li>• <code>{'{ext_user_id}'}</code> - Unique user ID (mandatory)</li>
                      <li>• <code>{'{secure_hash}'}</code> - MD5 hash of (ext_user_id + secure_key)</li>
                    </ul>
                    <div style={{ marginTop: '8px', padding: '8px', background: '#f0f0f5', borderRadius: '4px', fontSize: '0.8rem' }}>
                      <strong>Parameter Details:</strong>
                      <table style={{ width: '100%', marginTop: '4px', fontSize: '0.75rem' }}>
                        <tbody>
                          <tr><td><code>&ext_user_id=</code></td><td><strong>Mandatory</strong> - Unique per user</td></tr>
                          <tr><td><code>&app_id=10754</code></td><td><strong>Mandatory</strong> - Already included</td></tr>
                          <tr><td><code>&secure_hash=</code></td><td><strong>Recommended</strong> - md5(ext_user_id-app_secure_hash)</td></tr>
                          <tr><td><code>&username=</code></td><td>Recommended - User's username</td></tr>
                          <tr><td><code>&email=</code></td><td>Recommended - For duplicate matching</td></tr>
                          <tr><td><code>&subid_1=</code> / <code>&subid_2=</code></td><td>Optional - Custom tracking info</td></tr>
                        </tbody>
                      </table>
                    </div>
                  </div>
                </div>
              )}
              
              {/* CINT Entry Link Section */}
              {selectedSurvey.account_name && (
                <div className="detail-item full-width" style={{ marginTop: '16px', padding: '16px', background: '#f8fafc', borderRadius: '8px' }}>
                  <span className="detail-label" style={{ color: '#10b981', fontSize: '1rem' }}>🎯 CINT Entry Link</span>
                  <div style={{ marginTop: '12px' }}>
                    <div className="entry-link-container">
                      <input 
                        type="text" 
                        readOnly 
                        value={`https://samplicio.us/s/default.aspx?SID=${selectedSurvey.survey_id}&PID={panelist_id}`}
                        className="entry-link-input"
                        onClick={(e) => e.target.select()}
                      />
                      <button 
                        className="copy-link-btn"
                        onClick={() => navigator.clipboard.writeText(`https://samplicio.us/s/default.aspx?SID=${selectedSurvey.survey_id}&PID={panelist_id}`)}
                        title="Copy to clipboard"
                      >
                        📋 Copy
                      </button>
                    </div>
                    <div style={{ color: '#666', marginTop: '12px', fontSize: '0.85rem', lineHeight: '1.6' }}>
                      <strong>CINT/Lucid Parameters:</strong>
                      <ul style={{ margin: '8px 0 0 16px', padding: 0, listStyle: 'none' }}>
                        <li>• <code>SID</code> - Survey ID: <strong>{selectedSurvey.survey_id}</strong></li>
                        <li>• <code>PID</code> - Replace <code>{'{panelist_id}'}</code> with your unique panelist/respondent ID</li>
                        <li>• <code>[%MID%]</code> - Session ID (auto-replaced by CINT in redirects)</li>
                        <li>• <code>[%REVENUE%]</code> - Payout amount (auto-replaced in success redirects)</li>
                      </ul>
                      <div style={{ marginTop: '12px', padding: '8px', background: '#e0f2fe', borderRadius: '4px', fontSize: '0.8rem' }}>
                        💡 <strong>Tip:</strong> Configure redirect URLs via POST /cint/entry-links/{selectedSurvey.survey_id} to set success, failure, and quota-full callbacks.
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
