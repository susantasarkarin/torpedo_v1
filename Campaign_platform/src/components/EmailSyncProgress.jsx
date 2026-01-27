import React, { useState, useEffect, useCallback } from 'react'
import { API_BASE_URL, buildApiUrl } from '../config'
import './EmailSyncProgress.css'

/**
 * EmailSyncProgress - Shows real-time email sync progress with visual progress bars
 * 
 * Features:
 * - System health overview
 * - Per-mailbox sync status
 * - Visual progress bars for backfill
 * - Live email counts
 * - Worker status indicators
 */
const EmailSyncProgress = ({ refreshInterval = 3000 }) => {
  const [health, setHealth] = useState(null)
  const [mailboxes, setMailboxes] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [expanded, setExpanded] = useState({})

  // Get auth token
  const getAuthToken = () => {
    return localStorage.getItem("authToken") || sessionStorage.getItem("authToken") || ""
  }

  // Fetch system health
  const fetchHealth = useCallback(async () => {
    try {
      const token = getAuthToken()
      const response = await fetch(buildApiUrl(`/api/v1/email-sync/health`), {
        headers: { Authorization: token }
      })
      if (response.ok) {
        const data = await response.json()
        setHealth(data)
      }
    } catch (err) {
      console.error('Failed to fetch health:', err)
    }
  }, [])

  // Fetch mailbox list with status
  const fetchMailboxes = useCallback(async () => {
    try {
      const token = getAuthToken()
      const response = await fetch(buildApiUrl(`/api/v1/email-sync/mailboxes?active_only=false`), {
        headers: { Authorization: token }
      })
      if (response.ok) {
        const data = await response.json()
        
        // Fetch detailed status for each mailbox
        const detailedMailboxes = await Promise.all(
          data.map(async (mb) => {
            try {
              const detailRes = await fetch(
                buildApiUrl(`/api/v1/email-sync/mailboxes/${mb.mailbox_id}`),
                { headers: { Authorization: token } }
              )
              if (detailRes.ok) {
                return await detailRes.json()
              }
            } catch (e) {
              console.error(`Failed to fetch details for ${mb.mailbox_id}`)
            }
            return mb
          })
        )
        
        setMailboxes(detailedMailboxes)
        setLoading(false)
      }
    } catch (err) {
      console.error('Failed to fetch mailboxes:', err)
      setError('Failed to load mailboxes')
      setLoading(false)
    }
  }, [])

  // Start workers
  const startWorkers = async () => {
    try {
      const token = getAuthToken()
      await fetch(buildApiUrl(`/api/v1/email-sync/start`), {
        method: 'POST',
        headers: { Authorization: token }
      })
      fetchHealth()
    } catch (err) {
      console.error('Failed to start workers:', err)
    }
  }

  // Stop workers
  const stopWorkers = async () => {
    try {
      const token = getAuthToken()
      await fetch(buildApiUrl(`/api/v1/email-sync/stop`), {
        method: 'POST',
        headers: { Authorization: token }
      })
      fetchHealth()
    } catch (err) {
      console.error('Failed to stop workers:', err)
    }
  }

  // Trigger backfill for a mailbox
  const triggerBackfill = async (mailboxId) => {
    try {
      const token = getAuthToken()
      await fetch(buildApiUrl(`/api/v1/email-sync/mailboxes/${mailboxId}/backfill`), {
        method: 'POST',
        headers: { Authorization: token }
      })
      fetchMailboxes()
    } catch (err) {
      console.error('Failed to trigger backfill:', err)
    }
  }

  // Trigger incremental sync
  const triggerSync = async (mailboxId) => {
    try {
      const token = getAuthToken()
      await fetch(buildApiUrl(`/api/v1/email-sync/mailboxes/${mailboxId}/sync`), {
        method: 'POST',
        headers: { Authorization: token }
      })
      fetchMailboxes()
    } catch (err) {
      console.error('Failed to trigger sync:', err)
    }
  }

  // Initial fetch and polling
  useEffect(() => {
    fetchHealth()
    fetchMailboxes()

    const interval = setInterval(() => {
      fetchHealth()
      fetchMailboxes()
    }, refreshInterval)

    return () => clearInterval(interval)
  }, [fetchHealth, fetchMailboxes, refreshInterval])

  // Get status color
  const getStatusColor = (status) => {
    const colors = {
      'idle': '#10b981',
      'backfill_pending': '#f59e0b',
      'backfill_running': '#3b82f6',
      'backfill_completed': '#10b981',
      'incremental_running': '#3b82f6',
      'error': '#ef4444',
      'paused': '#6b7280'
    }
    return colors[status] || '#6b7280'
  }

  // Get status icon
  const getStatusIcon = (status) => {
    const icons = {
      'idle': '✅',
      'backfill_pending': '⏳',
      'backfill_running': '📥',
      'backfill_completed': '✅',
      'incremental_running': '🔄',
      'error': '❌',
      'paused': '⏸️'
    }
    return icons[status] || '❓'
  }

  // Format status text
  const formatStatus = (status) => {
    return status?.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()) || 'Unknown'
  }

  // Calculate progress percentage
  const getProgressPercent = (mailbox) => {
    if (!mailbox.backfill_progress) return 0
    const { messages_synced, total_messages } = mailbox.backfill_progress
    if (!total_messages || total_messages === 0) return 0
    return Math.min(100, Math.round((messages_synced / total_messages) * 100))
  }

  // Toggle mailbox expansion
  const toggleExpand = (mailboxId) => {
    setExpanded(prev => ({ ...prev, [mailboxId]: !prev[mailboxId] }))
  }

  if (loading) {
    return (
      <div className="email-sync-progress">
        <div className="sync-loading">
          <div className="spinner"></div>
          <span>Loading email sync status...</span>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="email-sync-progress">
        <div className="sync-error">
          <span>❌ {error}</span>
          <button onClick={() => { setError(null); fetchMailboxes(); }}>Retry</button>
        </div>
      </div>
    )
  }

  return (
    <div className="email-sync-progress">
      {/* System Health Overview */}
      <div className="sync-health-card">
        <div className="health-header">
          <h3>📧 Email Sync System</h3>
          <div className="health-status">
            <span className={`health-indicator ${health?.healthy ? 'healthy' : 'unhealthy'}`}>
              {health?.healthy ? '🟢 Running' : '🔴 Stopped'}
            </span>
          </div>
        </div>

        {health && (
          <div className="health-stats">
            <div className="stat-item">
              <span className="stat-label">Mailboxes</span>
              <span className="stat-value">{health.mailboxes?.active || 0} / {health.mailboxes?.total || 0}</span>
            </div>
            <div className="stat-item">
              <span className="stat-label">Emails Synced</span>
              <span className="stat-value">{health.emails?.total?.toLocaleString() || 0}</span>
            </div>
            <div className="stat-item">
              <span className="stat-label">Pending Categorization</span>
              <span className="stat-value">{health.emails?.pending_categorization || 0}</span>
            </div>
          </div>
        )}

        {/* Worker Controls */}
        <div className="worker-controls">
          <div className="workers-status">
            {health?.workers && Object.entries(health.workers).map(([name, worker]) => (
              <span key={name} className={`worker-badge ${worker.running ? 'running' : 'stopped'}`}>
                {worker.running ? '🟢' : '⚫'} {name}
              </span>
            ))}
          </div>
          <div className="worker-buttons">
            <button 
              className="btn-start"
              onClick={startWorkers}
              disabled={health?.healthy}
            >
              ▶️ Start Workers
            </button>
            <button 
              className="btn-stop"
              onClick={stopWorkers}
              disabled={!health?.healthy}
            >
              ⏹️ Stop Workers
            </button>
          </div>
        </div>
      </div>

      {/* Mailbox List */}
      <div className="mailbox-list">
        <h4>📬 Mailboxes ({mailboxes.length})</h4>
        
        {mailboxes.length === 0 ? (
          <div className="no-mailboxes">
            <p>No mailboxes registered yet.</p>
            <p className="hint">Use the API to register a mailbox for sync.</p>
          </div>
        ) : (
          mailboxes.map(mailbox => (
            <div 
              key={mailbox.mailbox_id} 
              className={`mailbox-card ${expanded[mailbox.mailbox_id] ? 'expanded' : ''}`}
            >
              {/* Mailbox Header */}
              <div className="mailbox-header" onClick={() => toggleExpand(mailbox.mailbox_id)}>
                <div className="mailbox-info">
                  <span className="mailbox-icon">
                    {mailbox.provider === 'gmail' ? '📧' : '📮'}
                  </span>
                  <div className="mailbox-details">
                    <span className="mailbox-email">{mailbox.email}</span>
                    <span className="mailbox-name">{mailbox.display_name}</span>
                  </div>
                </div>
                <div className="mailbox-status">
                  <span 
                    className="status-badge"
                    style={{ backgroundColor: getStatusColor(mailbox.sync_status) }}
                  >
                    {getStatusIcon(mailbox.sync_status)} {formatStatus(mailbox.sync_status)}
                  </span>
                  <span className="expand-icon">{expanded[mailbox.mailbox_id] ? '▼' : '▶'}</span>
                </div>
              </div>

              {/* Progress Bar (always visible during backfill) */}
              {(mailbox.sync_status === 'backfill_running' || mailbox.sync_status === 'backfill_pending') && (
                <div className="backfill-progress">
                  <div className="progress-info">
                    <span className="progress-label">
                      {mailbox.sync_status === 'backfill_pending' ? 'Waiting to start...' : 'Backfill in progress...'}
                    </span>
                    <span className="progress-percent">{getProgressPercent(mailbox)}%</span>
                  </div>
                  <div className="progress-bar-container">
                    <div 
                      className="progress-bar animated"
                      style={{ width: `${getProgressPercent(mailbox)}%` }}
                    >
                      <div className="progress-glow"></div>
                    </div>
                  </div>
                  <div className="progress-details">
                    <span>
                      📧 {mailbox.backfill_progress?.messages_synced?.toLocaleString() || 0} 
                      {mailbox.backfill_progress?.total_messages ? 
                        ` / ${mailbox.backfill_progress.total_messages.toLocaleString()}` : ''
                      } emails
                    </span>
                    {mailbox.backfill_progress?.started_at && (
                      <span>
                        ⏱️ Started: {new Date(mailbox.backfill_progress.started_at).toLocaleTimeString()}
                      </span>
                    )}
                  </div>
                </div>
              )}

              {/* Expanded Details */}
              {expanded[mailbox.mailbox_id] && (
                <div className="mailbox-expanded">
                  <div className="expanded-stats">
                    <div className="stat-row">
                      <span>📧 Total Emails:</span>
                      <strong>{mailbox.email_count?.toLocaleString() || 0}</strong>
                    </div>
                    <div className="stat-row">
                      <span>🔄 Last Sync:</span>
                      <strong>
                        {mailbox.last_sync_at 
                          ? new Date(mailbox.last_sync_at).toLocaleString()
                          : 'Never'
                        }
                      </strong>
                    </div>
                    <div className="stat-row">
                      <span>📝 Provider:</span>
                      <strong>{mailbox.provider?.toUpperCase()}</strong>
                    </div>
                    {mailbox.aliases && mailbox.aliases.length > 0 && (
                      <div className="stat-row aliases">
                        <span>📬 Aliases:</span>
                        <div className="alias-list">
                          {mailbox.aliases.map((alias, idx) => (
                            <span key={idx} className="alias-tag">
                              {alias.alias_email}
                              {alias.is_primary && <span className="primary-badge">Primary</span>}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                    {mailbox.error && (
                      <div className="stat-row error">
                        <span>❌ Error:</span>
                        <strong className="error-text">{mailbox.error}</strong>
                      </div>
                    )}
                  </div>

                  {/* Rate Limit Info */}
                  {mailbox.rate_limit && (
                    <div className="rate-limit-info">
                      <span className="rate-label">Rate Limit:</span>
                      <span className={`rate-status ${mailbox.rate_limit.allowed ? 'ok' : 'limited'}`}>
                        {mailbox.rate_limit.allowed ? '✅ OK' : '⚠️ Throttled'}
                      </span>
                    </div>
                  )}

                  {/* Action Buttons */}
                  <div className="mailbox-actions">
                    <button 
                      className="btn-action backfill"
                      onClick={() => triggerBackfill(mailbox.mailbox_id)}
                      disabled={mailbox.sync_status === 'backfill_running'}
                    >
                      📥 Full Backfill
                    </button>
                    <button 
                      className="btn-action sync"
                      onClick={() => triggerSync(mailbox.mailbox_id)}
                      disabled={!mailbox.backfill_progress?.completed_at}
                    >
                      🔄 Sync Now
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  )
}

export default EmailSyncProgress
