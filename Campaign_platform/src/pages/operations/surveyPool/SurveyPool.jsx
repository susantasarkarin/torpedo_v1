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
                  <th>Country</th>
                  <th>LOI (min)</th>
                  <th>Payout</th>
                  <th>Conversion</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {paginatedSurveys.map((survey, index) => (
                  <tr key={survey._id || survey.survey_id || index}>
                    <td>{survey.survey_id || survey._id}</td>
                    <td>{survey.name || survey.survey_name || 'N/A'}</td>
                    <td>{survey.country || survey.country_code || 'N/A'}</td>
                    <td>{survey.loi || 'N/A'}</td>
                    <td>${survey.payout?.toFixed(2) || survey.cpi?.toFixed(2) || '0.00'}</td>
                    <td>{survey.conversion_rate ? `${(survey.conversion_rate * 100).toFixed(1)}%` : 'N/A'}</td>
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
    </div>
  );
}
