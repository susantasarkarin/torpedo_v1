import React, { useState, useEffect } from 'react';
import { API_BASE_URL } from '../../../../config';

export default function SurveyDataTable({ surveys, token, onSurveySelect, selectedSurveyId }) {
  const [expandedSurveyId, setExpandedSurveyId] = useState(null);
  const [trafficStats, setTrafficStats] = useState({});
  const [loadingStats, setLoadingStats] = useState({});

  const handleRowClick = (survey) => {
    if (onSurveySelect) {
      onSurveySelect(survey);
    }
  };

  const toggleExpand = async (e, surveyId) => {
    e.stopPropagation();
    
    if (expandedSurveyId === surveyId) {
      setExpandedSurveyId(null);
      return;
    }

    setExpandedSurveyId(surveyId);

    // Fetch traffic stats for this survey if not already loaded
    if (!trafficStats[surveyId] && token) {
      setLoadingStats(prev => ({ ...prev, [surveyId]: true }));
      
      try {
        const response = await fetch(
          `${API_BASE_URL}/api/traffic/stats?survey_id=${surveyId}`,
          {
            method: 'GET',
            headers: {
              'Authorization': token,
              'Content-Type': 'application/json',
            },
          }
        );

        if (response.ok) {
          const data = await response.json();
          setTrafficStats(prev => ({ ...prev, [surveyId]: data }));
        }
      } catch (err) {
        console.error('Error fetching traffic stats:', err);
      } finally {
        setLoadingStats(prev => ({ ...prev, [surveyId]: false }));
      }
    }
  };

  return (
    <div className="survey-data-table">
      <div className="table-wrapper">
        <table>
          <thead>
            <tr>
              <th style={{ width: '40px' }}></th>
              <th style={{ width: '100px' }}>Survey ID</th>
              <th style={{ width: '250px' }}>Title</th>
              <th style={{ width: '80px' }}>LOI</th>
              <th style={{ width: '80px' }}>Payout</th>
              <th style={{ width: '90px' }}>Country</th>
              <th style={{ width: '120px' }}>Category</th>
              <th style={{ width: '100px' }}>Provider</th>
              <th style={{ width: '140px' }}>Last Updated</th>
            </tr>
          </thead>
          <tbody>
            {surveys.map((survey) => (
              <React.Fragment key={survey._id || survey.survey_id}>
                <tr 
                  onClick={() => handleRowClick(survey)}
                  className={`${onSurveySelect ? 'clickable-row' : ''} ${selectedSurveyId === survey._id ? 'selected-row' : ''}`}
                  style={onSurveySelect ? { cursor: 'pointer' } : {}}
                >
                  <td>
                    <button
                      className="expand-btn"
                      onClick={(e) => toggleExpand(e, survey.survey_id)}
                      title="View traffic stats"
                    >
                      {expandedSurveyId === survey.survey_id ? '▼' : '▶'}
                    </button>
                  </td>
                  <td>
                    <span className="survey-id">{survey.survey_id}</span>
                  </td>
                <td>
                  <span className="survey-title" title={survey.title}>
                    {survey.title}
                  </span>
                </td>
                <td>
                  <span className="survey-loi">{survey.loi} min</span>
                </td>
                <td>
                  <span className="survey-payout">${survey.payout.toFixed(2)}</span>
                </td>
                <td>
                  <span className="survey-country">{survey.country}</span>
                </td>
                <td>
                  <span className="survey-category">{survey.category}</span>
                </td>
                <td>
                  <span className="survey-provider">{survey.provider}</span>
                </td>
                <td>
                  <span className="survey-last-updated">
                    {formatDate(survey.last_updated)}
                  </span>
                </td>
              </tr>
              {expandedSurveyId === survey.survey_id && (
                <tr className="expanded-row">
                  <td colSpan="9">
                    <div className="traffic-stats-inline">
                      {loadingStats[survey.survey_id] ? (
                        <div className="stats-loading">⏳ Loading traffic stats...</div>
                      ) : (
                        <>
                          {/* Survey Details Section */}
                          <div className="survey-details-section">
                            <h4>📋 Survey Details</h4>
                            <div className="survey-details-grid">
                              <div className="detail-item">
                                <span className="detail-label">Survey ID</span>
                                <span className="detail-value">{survey.survey_id}</span>
                              </div>
                              <div className="detail-item">
                                <span className="detail-label">Title</span>
                                <span className="detail-value">{survey.title || 'N/A'}</span>
                              </div>
                              <div className="detail-item">
                                <span className="detail-label">Length of Interview</span>
                                <span className="detail-value">{survey.loi} minutes</span>
                              </div>
                              <div className="detail-item">
                                <span className="detail-label">Payout</span>
                                <span className="detail-value">${survey.payout?.toFixed(2) || '0.00'}</span>
                              </div>
                              <div className="detail-item">
                                <span className="detail-label">Country</span>
                                <span className="detail-value">{survey.country || 'N/A'}</span>
                              </div>
                              <div className="detail-item">
                                <span className="detail-label">Category</span>
                                <span className="detail-value">{survey.category || 'N/A'}</span>
                              </div>
                              <div className="detail-item">
                                <span className="detail-label">Provider</span>
                                <span className="detail-value">{survey.provider || 'CPX'}</span>
                              </div>
                              <div className="detail-item">
                                <span className="detail-label">Conversion Rate</span>
                                <span className="detail-value">{survey.conversion_rate ? `${(survey.conversion_rate * 100).toFixed(1)}%` : 'N/A'}</span>
                              </div>
                            </div>
                            
                            {/* Entry Link Section */}
                            {survey.live_link && (
                              <div className="entry-link-section">
                                <span className="entry-link-label">🔗 Live Link</span>
                                <div className="entry-link-container">
                                  <input 
                                    type="text" 
                                    readOnly 
                                    value={survey.live_link} 
                                    className="entry-link-input"
                                    onClick={(e) => e.target.select()}
                                  />
                                  <button 
                                    className="copy-link-btn"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      navigator.clipboard.writeText(survey.live_link);
                                    }}
                                    title="Copy to clipboard"
                                  >
                                    📋
                                  </button>
                                  <a 
                                    href={survey.live_link} 
                                    target="_blank" 
                                    rel="noopener noreferrer"
                                    className="open-link-btn"
                                    onClick={(e) => e.stopPropagation()}
                                    title="Open in new tab"
                                  >
                                    🔗
                                  </a>
                                </div>
                              </div>
                            )}
                            
                            {survey.entry_link && (
                              <div className="entry-link-section">
                                <span className="entry-link-label">🎯 Entry Link (Template)</span>
                                <div className="entry-link-container">
                                  <input 
                                    type="text" 
                                    readOnly 
                                    value={survey.entry_link} 
                                    className="entry-link-input"
                                    onClick={(e) => e.target.select()}
                                  />
                                  <button 
                                    className="copy-link-btn"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      navigator.clipboard.writeText(survey.entry_link);
                                    }}
                                    title="Copy to clipboard"
                                  >
                                    📋
                                  </button>
                                </div>
                                <div style={{ color: '#888', marginTop: '6px', fontSize: '0.8rem', lineHeight: '1.4' }}>
                                  <strong>Replace:</strong> {'{ext_user_id}'} (unique ID), {'{secure_hash}'} (MD5)
                                </div>
                              </div>
                            )}
                          </div>

                          {/* Traffic Statistics Section */}
                          <div className="traffic-stats-section">
                            <h4>📊 Traffic Statistics</h4>
                            <div className="stats-summary">
                              <div className="stat-box">
                                <span className="stat-label">Total Entrants</span>
                                <span className="stat-number">{trafficStats[survey.survey_id]?.total || 0}</span>
                              </div>
                              <div className="stat-box" data-status="complete">
                                <span className="stat-label">Completes</span>
                                <span className="stat-number">{trafficStats[survey.survey_id]?.by_status?.COMPLETE || 0}</span>
                              </div>
                              <div className="stat-box" data-status="terminated">
                                <span className="stat-label">Terminates</span>
                                <span className="stat-number">{trafficStats[survey.survey_id]?.by_status?.TERMINATED || 0}</span>
                              </div>
                              <div className="stat-box" data-status="quotafull">
                                <span className="stat-label">Quota Full</span>
                                <span className="stat-number">{trafficStats[survey.survey_id]?.by_status?.QUOTAFULL || 0}</span>
                              </div>
                              <div className="stat-box" data-status="incomplete">
                                <span className="stat-label">Incomplete</span>
                                <span className="stat-number">{trafficStats[survey.survey_id]?.by_status?.INCOMPLETE || 0}</span>
                              </div>
                            </div>
                          </div>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              )}
              </React.Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function formatDate(dateString) {
  if (!dateString) return 'N/A';
  const date = new Date(dateString);
  // Convert to IST (Asia/Kolkata timezone)
  return date.toLocaleString('en-IN', {
    timeZone: 'Asia/Kolkata',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: true,
  });
}

// Inline styles for expanded traffic stats
const styles = `
.expand-btn {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 12px;
  color: #667eea;
  padding: 4px 8px;
  transition: transform 0.2s;
}

.expand-btn:hover {
  transform: scale(1.2);
}

.expanded-row {
  background: #f8f9fa;
}

.traffic-stats-inline {
  padding: 20px;
  border-left: 3px solid #667eea;
}

.survey-details-section {
  margin-bottom: 24px;
}

.survey-details-section h4,
.traffic-stats-section h4 {
  margin: 0 0 16px 0;
  font-size: 14px;
  font-weight: 600;
  color: #495057;
  display: flex;
  align-items: center;
  gap: 8px;
}

.survey-details-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 12px;
}

.detail-item {
  background: white;
  padding: 12px 16px;
  border-radius: 6px;
  border: 1px solid #dee2e6;
}

.detail-item .detail-label {
  display: block;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  color: #6c757d;
  margin-bottom: 4px;
}

.detail-item .detail-value {
  display: block;
  font-size: 14px;
  font-weight: 500;
  color: #212529;
}

.traffic-stats-section {
  margin-top: 16px;
}

.stats-header h4 {
  margin: 0 0 12px 0;
  font-size: 14px;
  font-weight: 600;
  color: #495057;
}

.stats-summary {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.stat-box {
  background: white;
  padding: 12px 16px;
  border-radius: 6px;
  border: 1px solid #dee2e6;
  min-width: 120px;
  text-align: center;
}

.stat-box .stat-label {
  display: block;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  color: #6c757d;
  margin-bottom: 4px;
}

.stat-box .stat-number {
  display: block;
  font-size: 20px;
  font-weight: 700;
  color: #212529;
}

.stat-box[data-status="incomplete"] .stat-number { color: #ffc107; }
.stat-box[data-status="complete"] .stat-number { color: #28a745; }
.stat-box[data-status="terminated"] .stat-number { color: #dc3545; }
.stat-box[data-status="quotafull"] .stat-number { color: #6c757d; }

.stats-loading, .stats-empty {
  text-align: center;
  padding: 20px;
  color: #6c757d;
  font-style: italic;
}

/* Entry Link Section Styles */
.entry-link-section {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid #dee2e6;
}

.entry-link-label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  color: #495057;
  margin-bottom: 8px;
}

.entry-link-container {
  display: flex;
  gap: 8px;
  align-items: center;
}

.entry-link-input {
  flex: 1;
  padding: 10px 12px;
  font-size: 13px;
  font-family: 'Courier New', monospace;
  background: white;
  border: 1px solid #dee2e6;
  border-radius: 6px;
  color: #667eea;
  cursor: text;
}

.entry-link-input:focus {
  outline: none;
  border-color: #667eea;
  box-shadow: 0 0 0 2px rgba(102, 126, 234, 0.2);
}

.copy-link-btn,
.open-link-btn {
  padding: 8px 12px;
  background: #667eea;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-size: 16px;
  transition: background 0.2s;
}

.copy-link-btn:hover,
.open-link-btn:hover {
  background: #5a6fd6;
}

.open-link-btn {
  text-decoration: none;
  display: flex;
  align-items: center;
  justify-content: center;
}
`;

// Inject styles
if (typeof document !== 'undefined') {
  const styleSheet = document.createElement('style');
  styleSheet.textContent = styles;
  document.head.appendChild(styleSheet);
}
