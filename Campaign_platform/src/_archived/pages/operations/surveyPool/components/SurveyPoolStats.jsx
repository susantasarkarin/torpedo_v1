import React from 'react';

export default function SurveyPoolStats({
  totalSurveys,
  filteredSurveys,
  lastUpdated,
  onManualRefresh,
  refreshing,
}) {
  const isFiltered = filteredSurveys !== undefined && filteredSurveys !== totalSurveys;

  const formatDateIST = (dateString) => {
    if (!dateString) return 'Never';
    
    const date = new Date(dateString);
    // Convert to IST (UTC+5:30)
    const istDate = new Date(date.toLocaleString('en-US', { timeZone: 'Asia/Kolkata' }));
    const now = new Date();
    const diffMs = now - istDate;
    const diffMins = Math.floor(diffMs / 60000);

    if (diffMins < 1) return 'just now';
    if (diffMins < 60) return `${diffMins}m ago`;

    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours}h ago`;

    return istDate.toLocaleDateString('en-IN', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: true,
    });
  };

  return (
    <div className="survey-pool-stats">
      <div className="stat-card">
        <div>
          <div className="stat-label">Total Surveys</div>
          <div className="stat-value">{totalSurveys.toLocaleString()}</div>
        </div>
      </div>

      {isFiltered && (
        <div className="stat-card">
          <div>
            <div className="stat-label">Filtered Results</div>
            <div className="stat-value" style={{ color: '#667eea' }}>{filteredSurveys.toLocaleString()}</div>
          </div>
        </div>
      )}

      <div className="stat-card">
        <div>
          <div className="stat-label">Last Updated (IST)</div>
          <div className="stat-value">{formatDateIST(lastUpdated)}</div>
        </div>
      </div>

      <div className="stat-card stat-actions">
        <button
          className="refresh-btn"
          onClick={onManualRefresh}
          disabled={refreshing}
        >
          {refreshing ? '⏳ Refreshing...' : '🔄 Refresh Now'}
        </button>
        <div className="stat-note">Auto-refresh: Every 60s</div>
      </div>
    </div>
  );
}
