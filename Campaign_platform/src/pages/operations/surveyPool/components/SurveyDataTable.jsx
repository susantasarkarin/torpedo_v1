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
                      ) : trafficStats[survey.survey_id] ? (
                        <>
                          <div className="stats-header">
                            <h4>📊 Traffic Statistics for Survey {survey.survey_id}</h4>
                          </div>
                          <div className="stats-summary">
                            <div className="stat-box">
                              <span className="stat-label">Total</span>
                              <span className="stat-number">{trafficStats[survey.survey_id].total || 0}</span>
                            </div>
                            {Object.entries(trafficStats[survey.survey_id].by_status || {}).map(([status, count]) => (
                              <div key={status} className="stat-box" data-status={status.toLowerCase()}>
                                <span className="stat-label">{status}</span>
                                <span className="stat-number">{count}</span>
                              </div>
                            ))}
                          </div>
                        </>
                      ) : (
                        <div className="stats-empty">No traffic data available for this survey</div>
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
  padding: 16px;
  border-left: 3px solid #667eea;
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
  min-width: 100px;
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

.stat-box[data-status="new"] .stat-number { color: #17a2b8; }
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
`;

// Inject styles
if (typeof document !== 'undefined') {
  const styleSheet = document.createElement('style');
  styleSheet.textContent = styles;
  document.head.appendChild(styleSheet);
}
