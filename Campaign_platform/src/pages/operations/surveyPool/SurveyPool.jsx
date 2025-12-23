import React, { useState, useEffect, useMemo } from 'react';
import { useAuth } from '../../../hooks/useAuth';
import { API_BASE_URL } from '../../../config';
import './SurveyPool.css';

export default function SurveyPool() {
  const { user, token } = useAuth();
  const [surveys, setSurveys] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [recordsPerPage, setRecordsPerPage] = useState(20);
  const [currentPage, setCurrentPage] = useState(1);
  const [selectedSurvey, setSelectedSurvey] = useState(null);
  const [showDetailsModal, setShowDetailsModal] = useState(false);

  // Fetch surveys on mount
  useEffect(() => {
    if (token) {
      fetchSurveys();
    }
  }, [token]);

  const fetchSurveys = async () => {
    setLoading(true);
    setError(null);
    
    try {
      const response = await fetch(`${API_BASE_URL}/cpx/surveys?page=1&page_size=100`, {
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

      // Fetch latest surveys
      await fetchSurveys();
      setCurrentPage(1);
    } catch (err) {
      console.error('Error refreshing CPX inventory:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // Client-side pagination
  const paginatedSurveys = useMemo(() => {
    const startIndex = (currentPage - 1) * recordsPerPage;
    const endIndex = startIndex + recordsPerPage;
    return surveys.slice(startIndex, endIndex);
  }, [surveys, currentPage, recordsPerPage]);

  const totalPages = Math.ceil(surveys.length / recordsPerPage);

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

  // Get survey name - for CPX surveys, use survey_id as name
  const getSurveyName = (survey) => {
    const source = survey.provider || survey.source || 'CPX';
    if (source === 'CPX') {
      return survey.survey_id || survey._id || 'N/A';
    }
    return survey.name || survey.survey_name || survey.title || 'N/A';
  };

  // Calculate conversion rate properly (stored as decimal, display as percentage)
  const getConversionRate = (survey) => {
    const rate = survey.conversion_rate;
    if (rate === null || rate === undefined) return 'N/A';
    // If rate is already > 1, it's likely already a percentage
    if (rate > 1) {
      return `${rate.toFixed(1)}%`;
    }
    // Otherwise multiply by 100 to get percentage
    return `${(rate * 100).toFixed(1)}%`;
  };

  if (!user) {
    return <div className="survey-pool-container">Please login to access Survey Pool.</div>;
  }

  return (
    <div className="survey-pool-container">
      <div className="survey-pool-header">
        <div>
          <h1>📋 Survey Pool</h1>
          <p>CPX Research survey inventory</p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
          {lastUpdated && (
            <span style={{ fontSize: '0.85rem', color: '#666' }}>
              Last updated: {new Date(lastUpdated).toLocaleString()}
            </span>
          )}
          <button
            onClick={handleRefresh}
            disabled={loading}
            className="refresh-btn"
          >
            {loading ? '⏳ Refreshing...' : '🔄 Refresh'}
          </button>
        </div>
      </div>

      {/* Loading State */}
      {loading && surveys.length === 0 && !error && (
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
          <button onClick={handleRefresh} className="retry-btn">
            🔄 Retry
          </button>
        </div>
      )}

      {/* Survey Table */}
      {paginatedSurveys.length > 0 && (
        <>
          <div className="survey-table-container">
            <table className="survey-table">
              <thead>
                <tr>
                  <th>Survey ID</th>
                  <th>Name</th>
                  <th>Source</th>
                  <th>Country</th>
                  <th>LOI (min)</th>
                  <th>Payout</th>
                  <th>Conversion</th>
                  <th>Date/Time</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {paginatedSurveys.map((survey, index) => (
                  <tr key={survey._id || survey.survey_id || index}>
                    <td>
                      <span 
                        className="survey-link" 
                        onClick={() => handleSurveyClick(survey)}
                        style={{ cursor: 'pointer', color: '#667eea', textDecoration: 'underline' }}
                      >
                        {survey.survey_id || survey._id}
                      </span>
                    </td>
                    <td>
                      <span 
                        className="survey-link" 
                        onClick={() => handleSurveyClick(survey)}
                        style={{ cursor: 'pointer', color: '#667eea', textDecoration: 'underline' }}
                      >
                        {getSurveyName(survey)}
                      </span>
                    </td>
                    <td>
                      <span className="source-badge">
                        {survey.provider || survey.source || 'CPX'}
                      </span>
                    </td>
                    <td>{survey.country || survey.country_code || 'N/A'}</td>
                    <td>{survey.loi || 'N/A'}</td>
                    <td>${survey.payout?.toFixed(2) || survey.cpi?.toFixed(2) || '0.00'}</td>
                    <td>{getConversionRate(survey)}</td>
                    <td>{formatDateTime(survey.last_updated || survey.inserted_at)}</td>
                    <td>
                      <span className={`status-badge ${survey.status === 'active' ? 'active' : 'inactive'}`}>
                        {survey.status || 'active'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination Controls */}
          {surveys.length > recordsPerPage && (
            <div className="survey-pool-pagination">
              <div className="pagination-info">
                Showing {(currentPage - 1) * recordsPerPage + 1} to{' '}
                {Math.min(currentPage * recordsPerPage, surveys.length)} of {surveys.length} surveys
              </div>

              <div className="pagination-controls">
                <select
                  value={recordsPerPage}
                  onChange={(e) => {
                    setRecordsPerPage(Number(e.target.value));
                    setCurrentPage(1);
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
                    onClick={() => setCurrentPage(1)}
                    disabled={currentPage === 1 || loading}
                    className="pagination-btn"
                  >
                    ⬅️ First
                  </button>
                  <button
                    onClick={() => setCurrentPage(currentPage - 1)}
                    disabled={currentPage === 1 || loading}
                    className="pagination-btn"
                  >
                    ← Previous
                  </button>

                  <span className="pagination-page-info">
                    Page {currentPage} of {totalPages}
                  </span>

                  <button
                    onClick={() => setCurrentPage(currentPage + 1)}
                    disabled={currentPage === totalPages || loading}
                    className="pagination-btn"
                  >
                    Next →
                  </button>
                  <button
                    onClick={() => setCurrentPage(totalPages)}
                    disabled={currentPage === totalPages || loading}
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

      {surveys.length === 0 && !error && !loading && (
        <div className="survey-pool-empty">
          <div className="empty-icon">📭</div>
          <p className="empty-title">No surveys available</p>
          <p className="empty-subtitle">Refresh to check for new surveys from CPX Research.</p>
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
                  <span className="detail-value">{getSurveyName(selectedSurvey)}</span>
                </div>
                <div className="detail-item">
                  <span className="detail-label">Source</span>
                  <span className="detail-value">{selectedSurvey.provider || selectedSurvey.source || 'CPX'}</span>
                </div>
                <div className="detail-item">
                  <span className="detail-label">Country</span>
                  <span className="detail-value">{selectedSurvey.country || selectedSurvey.country_code || 'N/A'}</span>
                </div>
                <div className="detail-item">
                  <span className="detail-label">Length of Interview</span>
                  <span className="detail-value">{selectedSurvey.loi || 'N/A'} minutes</span>
                </div>
                <div className="detail-item">
                  <span className="detail-label">Payout</span>
                  <span className="detail-value">${selectedSurvey.payout?.toFixed(2) || selectedSurvey.cpi?.toFixed(2) || '0.00'}</span>
                </div>
                <div className="detail-item">
                  <span className="detail-label">Conversion Rate</span>
                  <span className="detail-value">{getConversionRate(selectedSurvey)}</span>
                </div>
                <div className="detail-item">
                  <span className="detail-label">Category</span>
                  <span className="detail-value">{selectedSurvey.category || 'N/A'}</span>
                </div>
                <div className="detail-item">
                  <span className="detail-label">Status</span>
                  <span className="detail-value">{selectedSurvey.status || 'active'}</span>
                </div>
                <div className="detail-item">
                  <span className="detail-label">Date/Time Added</span>
                  <span className="detail-value">{formatDateTime(selectedSurvey.last_updated || selectedSurvey.inserted_at)}</span>
                </div>
              </div>
              {selectedSurvey.title && selectedSurvey.title !== getSurveyName(selectedSurvey) && (
                <div className="detail-item full-width">
                  <span className="detail-label">Title</span>
                  <span className="detail-value">{selectedSurvey.title}</span>
                </div>
              )}
              
              {/* Live Link - Direct link from CPX API */}
              {selectedSurvey.live_link && (
                <div className="detail-item full-width">
                  <span className="detail-label">🔗 Live Link</span>
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
              
              {/* Entry Link - Generated link with placeholder for ext_user_id */}
              {selectedSurvey.entry_link && (
                <div className="detail-item full-width">
                  <span className="detail-label">🎯 Entry Link (Template)</span>
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
                    <ul style={{ margin: '4px 0 0 16px', padding: 0 }}>
                      <li><code>{'{ext_user_id}'}</code> - Unique user ID (mandatory)</li>
                      <li><code>{'{secure_hash}'}</code> - MD5 hash of (ext_user_id + secure_key)</li>
                    </ul>
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
