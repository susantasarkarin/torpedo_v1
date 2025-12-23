import React, { useState, useEffect } from 'react';
import { API_BASE_URL } from '../../../../config';

export default function TrafficStats({ token, refreshTrigger }) {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const fetchStats = async () => {
    if (!token) return;

    setLoading(true);
    setError(null);

    try {
      const response = await fetch(`${API_BASE_URL}/api/traffic/stats`, {
        method: 'GET',
        headers: {
          'Authorization': token,
          'Content-Type': 'application/json',
        },
      });

      if (!response.ok) {
        throw new Error('Failed to fetch traffic stats');
      }

      const data = await response.json();
      setStats(data);
    } catch (err) {
      console.error('Stats error:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStats();
  }, [token, refreshTrigger]);

  if (loading && !stats) {
    return (
      <div className="traffic-stats loading">
        <p>⏳ Loading traffic stats...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="traffic-stats error">
        <p>❌ Error loading stats: {error}</p>
        <button onClick={fetchStats}>Retry</button>
      </div>
    );
  }

  if (!stats) {
    return null;
  }

  const statusOrder = ['INCOMPLETE', 'COMPLETE', 'TERMINATED', 'QUOTAFULL'];
  const statusColors = {
    INCOMPLETE: '#ffc107',
    COMPLETE: '#28a745',
    TERMINATED: '#dc3545',
    QUOTAFULL: '#6c757d',
  };

  return (
    <div className="traffic-stats">
      <div className="stats-header">
        <h3>📊 Traffic Statistics</h3>
        <button className="refresh-btn" onClick={fetchStats} disabled={loading}>
          {loading ? '⏳' : '🔄'} Refresh
        </button>
      </div>

      <div className="stats-total">
        <span className="total-label">Total Traffic Records:</span>
        <span className="total-value">{stats.total.toLocaleString()}</span>
      </div>

      <div className="stats-grid">
        {statusOrder.map((status) => {
          const count = stats.by_status[status] || 0;
          const percentage = stats.total > 0 ? ((count / stats.total) * 100).toFixed(1) : 0;
          
          return (
            <div key={status} className="stat-card" style={{ borderLeftColor: statusColors[status] }}>
              <div className="stat-status">{status}</div>
              <div className="stat-count">{count.toLocaleString()}</div>
              <div className="stat-percentage">{percentage}%</div>
            </div>
          );
        })}
      </div>

      <style jsx>{`
        .traffic-stats {
          background: white;
          border: 1px solid #dee2e6;
          border-radius: 8px;
          padding: 20px;
          margin: 20px 0;
        }

        .traffic-stats.loading,
        .traffic-stats.error {
          text-align: center;
          padding: 40px 20px;
        }

        .traffic-stats.error button {
          margin-top: 10px;
          padding: 8px 16px;
          background: #007bff;
          color: white;
          border: none;
          border-radius: 4px;
          cursor: pointer;
        }

        .stats-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 20px;
        }

        .stats-header h3 {
          margin: 0;
          color: #495057;
        }

        .refresh-btn {
          padding: 6px 12px;
          background: #6c757d;
          color: white;
          border: none;
          border-radius: 4px;
          cursor: pointer;
          font-size: 14px;
        }

        .refresh-btn:hover:not(:disabled) {
          background: #5a6268;
        }

        .refresh-btn:disabled {
          opacity: 0.6;
          cursor: not-allowed;
        }

        .stats-total {
          background: #f8f9fa;
          padding: 15px;
          border-radius: 6px;
          margin-bottom: 20px;
          text-align: center;
          font-size: 18px;
        }

        .total-label {
          color: #6c757d;
          margin-right: 10px;
        }

        .total-value {
          font-weight: bold;
          color: #212529;
          font-size: 24px;
        }

        .stats-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
          gap: 15px;
        }

        .stat-card {
          background: #f8f9fa;
          border-left: 4px solid;
          border-radius: 6px;
          padding: 15px;
          text-align: center;
        }

        .stat-status {
          font-size: 12px;
          font-weight: 600;
          text-transform: uppercase;
          color: #6c757d;
          margin-bottom: 8px;
        }

        .stat-count {
          font-size: 28px;
          font-weight: bold;
          color: #212529;
          margin-bottom: 5px;
        }

        .stat-percentage {
          font-size: 14px;
          color: #6c757d;
        }
      `}</style>
    </div>
  );
}
