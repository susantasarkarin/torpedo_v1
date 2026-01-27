/**
 * CLAY-LIKE WORKBOOK INTERFACE
 * Spreadsheet-style list building with independent column execution
 * 
 * Features:
 * - Rows = entities (people, companies)
 * - Columns = execution steps (enrichment, AI transform, computed logic)
 * - Each column: independent execution, caching, retries, locking
 * - Manual cell overrides that persist across automation
 * - Real-time execution state tracking with audit logs
 * - Cost tracking and budget controls
 */

import React, { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { API_BASE_URL, buildApiUrl } from '../../../config';
import './Workbook.css';

// ============== COLUMN TYPE ICONS & LABELS ==============

const COLUMN_TYPE_INFO = {
  static_field: { icon: '📌', label: 'Static Field', color: '#6b7280' },
  enrichment: { icon: '✨', label: 'Enrichment', color: '#3b82f6' },
  ai_transform: { icon: '🤖', label: 'AI Transform', color: '#8b5cf6' },
  computed: { icon: '⚙️', label: 'Computed', color: '#10b981' },
  email_finder: { icon: '📧', label: 'Email Finder', color: '#f59e0b' },
  dedup_group: { icon: '🔗', label: 'Dedup Group', color: '#ef4444' },
  validation: { icon: '✓', label: 'Validation', color: '#14b8a6' },
};

const EXECUTION_STATE_INFO = {
  not_run: { icon: '⚫', label: 'Not Run', color: '#d1d5db' },
  queued: { icon: '📋', label: 'Queued', color: '#fbbf24' },
  running: { icon: '🔄', label: 'Running', color: '#3b82f6' },
  completed: { icon: '✅', label: 'Completed', color: '#10b981' },
  failed: { icon: '❌', label: 'Failed', color: '#ef4444' },
  partial_failed: { icon: '⚠️', label: 'Partial Failed', color: '#f59e0b' },
  cancelled: { icon: '⏹️', label: 'Cancelled', color: '#6b7280' },
};

// ============== CELL VALUE DISPLAY ==============

function CellDisplay({ cellValue, column, isEditing, onEdit }) {
  if (!cellValue) {
    return <span className="cell-empty">-</span>;
  }

  // Determine which value to display: manual override > enriched > extracted
  const displayValue = cellValue.final_value;
  const isOverride = cellValue.manual_override !== null && cellValue.manual_override !== undefined;

  return (
    <div className={`cell-display ${isOverride ? 'cell-override' : ''}`} title={cellValue.source}>
      <span className="cell-value">
        {typeof displayValue === 'object' ? JSON.stringify(displayValue) : String(displayValue)}
      </span>
      
      {isOverride && <span className="override-indicator" title="Manual override">✏️</span>}
      
      <div className="cell-metadata">
        <small>Source: {cellValue.source}</small>
        <small>Confidence: {(cellValue.confidence_score * 100).toFixed(0)}%</small>
        {cellValue.cost > 0 && <small>Cost: ${cellValue.cost.toFixed(4)}</small>}
      </div>
    </div>
  );
}

// ============== COLUMN EXECUTION CONTROL ==============

function ColumnExecutionPanel({ column, onExecute, onRetry, onLock, onUnlock, loading }) {
  return (
    <div className="column-control-panel">
      <div className="execution-state">
        {EXECUTION_STATE_INFO[column.state] && (
          <>
            <span>{EXECUTION_STATE_INFO[column.state].icon}</span>
            <span>{EXECUTION_STATE_INFO[column.state].label}</span>
          </>
        )}
      </div>

      <div className="control-buttons">
        {column.state === 'not_run' && (
          <button
            className="btn btn-sm btn-primary"
            onClick={onExecute}
            disabled={loading}
            title="Execute this column across all rows"
          >
            ▶ Execute
          </button>
        )}

        {['failed', 'partial_failed'].includes(column.state) && (
          <button
            className="btn btn-sm btn-warning"
            onClick={onRetry}
            disabled={loading}
            title="Retry failed cells"
          >
            🔄 Retry
          </button>
        )}

        {column.state === 'completed' && (
          <button
            className="btn btn-sm btn-outline"
            onClick={onRetry}
            disabled={loading}
            title="Re-run all cells in this column"
          >
            🔄 Re-run
          </button>
        )}

        {!column.is_locked ? (
          <button
            className="btn btn-sm btn-outline"
            onClick={onLock}
            title="Lock column to prevent automation overwrites"
          >
            🔓 Unlock
          </button>
        ) : (
          <button
            className="btn btn-sm btn-danger"
            onClick={onUnlock}
            title="Unlock column for automation"
          >
            🔒 Locked
          </button>
        )}
      </div>

      <div className="cost-info">
        <small>Cost: ${column.actual_cost_incurred?.toFixed(4)}</small>
      </div>
    </div>
  );
}

// ============== MAIN WORKBOOK COMPONENT ==============

function Workbook() {
  const { campaignId, workbookId } = useParams();
  const navigate = useNavigate();
  const sessionId = localStorage.getItem('session_id');

  // Data states
  const [workbook, setWorkbook] = useState(null);
  const [columns, setColumns] = useState([]);
  const [rows, setRows] = useState([]);
  const [cells, setCells] = useState({});

  // UI states
  const [loading, setLoading] = useState(true);
  const [executingColumn, setExecutingColumn] = useState(null);
  const [selectedCell, setSelectedCell] = useState(null);
  const [editingCell, setEditingCell] = useState(null);

  // Fetch workbook data
  const fetchWorkbook = useCallback(async () => {
    try {
      const res = await fetch(
        buildApiUrl(`/leads/workbooks/${workbookId}`),
        { headers: { Authorization: sessionId } }
      );
      
      if (!res.ok) throw new Error('Failed to fetch workbook');
      
      const data = await res.json();
      setWorkbook(data.workbook);
      setColumns(data.columns || []);
      setRows(data.rows || []);
      setCells(data.cells || {});
    } catch (err) {
      console.error('Error fetching workbook:', err);
    } finally {
      setLoading(false);
    }
  }, [workbookId, sessionId]);

  useEffect(() => {
    fetchWorkbook();
  }, [fetchWorkbook]);

  // Execute column
  const handleExecuteColumn = async (columnId) => {
    setExecutingColumn(columnId);
    
    try {
      const res = await fetch(
        buildApiUrl(`/leads/workbooks/${workbookId}/columns/${columnId}/execute`),
        {
          method: 'POST',
          headers: { Authorization: sessionId },
        }
      );

      if (!res.ok) throw new Error('Execution failed');

      const data = await res.json();
      
      // Update cells with results
      setCells(prev => ({ ...prev, ...data.updated_cells }));
      
      // Update column state
      setColumns(prev => prev.map(c =>
        c.column_id === columnId
          ? { ...c, state: 'completed', actual_cost_incurred: data.cost }
          : c
      ));
    } catch (err) {
      console.error('Execution error:', err);
      setColumns(prev => prev.map(c =>
        c.column_id === columnId
          ? { ...c, state: 'failed' }
          : c
      ));
    } finally {
      setExecutingColumn(null);
    }
  };

  // Retry column
  const handleRetryColumn = async (columnId) => {
    setExecutingColumn(columnId);
    
    try {
      const res = await fetch(
        buildApiUrl(`/leads/workbooks/${workbookId}/columns/${columnId}/retry`),
        {
          method: 'POST',
          headers: { Authorization: sessionId },
        }
      );

      if (!res.ok) throw new Error('Retry failed');

      const data = await res.json();
      setCells(prev => ({ ...prev, ...data.updated_cells }));
    } catch (err) {
      console.error('Retry error:', err);
    } finally {
      setExecutingColumn(null);
    }
  };

  // Lock/unlock column
  const handleLockColumn = async (columnId) => {
    try {
      const res = await fetch(
        buildApiUrl(`/leads/workbooks/${workbookId}/columns/${columnId}/lock`),
        {
          method: 'POST',
          headers: { Authorization: sessionId },
        }
      );

      if (!res.ok) throw new Error('Lock failed');

      setColumns(prev => prev.map(c =>
        c.column_id === columnId
          ? { ...c, is_locked: true }
          : c
      ));
    } catch (err) {
      console.error('Lock error:', err);
    }
  };

  const handleUnlockColumn = async (columnId) => {
    try {
      const res = await fetch(
        buildApiUrl(`/leads/workbooks/${workbookId}/columns/${columnId}/unlock`),
        {
          method: 'POST',
          headers: { Authorization: sessionId },
        }
      );

      if (!res.ok) throw new Error('Unlock failed');

      setColumns(prev => prev.map(c =>
        c.column_id === columnId
          ? { ...c, is_locked: false }
          : c
      ));
    } catch (err) {
      console.error('Unlock error:', err);
    }
  };

  // Set cell override
  const handleCellOverride = async (rowId, columnId, value) => {
    try {
      const res = await fetch(
        buildApiUrl(`/leads/workbooks/${workbookId}/cells/${rowId}/${columnId}/override`),
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: sessionId,
          },
          body: JSON.stringify({ override_value: value }),
        }
      );

      if (!res.ok) throw new Error('Override failed');

      const data = await res.json();
      const cellId = `${rowId}_${columnId}`;
      setCells(prev => ({
        ...prev,
        [cellId]: data.updated_cell,
      }));
    } catch (err) {
      console.error('Override error:', err);
    }
  };

  if (loading) {
    return (
      <div className="workbook-page">
        <div className="loading-container">
          <div className="loading-spinner"></div>
          <span>Loading workbook...</span>
        </div>
      </div>
    );
  }

  if (!workbook) {
    return (
      <div className="workbook-page">
        <div className="empty-state">
          <div className="empty-icon">📋</div>
          <h2>Workbook not found</h2>
          <button className="btn btn-primary" onClick={() => navigate(-1)}>
            ← Back
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="workbook-page">
      {/* Header */}
      <div className="workbook-header">
        <div className="header-left">
          <button className="btn btn-outline" onClick={() => navigate(-1)}>
            ← Back
          </button>
          <h1>{workbook.name}</h1>
          <span className="workbook-status">{workbook.status}</span>
        </div>
        
        <div className="header-stats">
          <div className="stat-badge">
            <span className="stat-value">{rows.length}</span>
            <span className="stat-label">Rows</span>
          </div>
          <div className="stat-badge">
            <span className="stat-value">{columns.length}</span>
            <span className="stat-label">Columns</span>
          </div>
          <div className="stat-badge cost-badge">
            <span className="stat-value">${columns.reduce((sum, c) => sum + (c.actual_cost_incurred || 0), 0).toFixed(2)}</span>
            <span className="stat-label">Total Cost</span>
          </div>
        </div>
      </div>

      {/* Column Info Bar */}
      <div className="columns-info-bar">
        <h3>Execution Steps</h3>
        <div className="columns-list">
          {columns.map(column => (
            <div key={column.column_id} className="column-info-item">
              <div className="column-type">
                {COLUMN_TYPE_INFO[column.column_type]?.icon}
              </div>
              <div className="column-name">
                <strong>{column.name}</strong>
                <small>{COLUMN_TYPE_INFO[column.column_type]?.label}</small>
              </div>
              <div className="column-state">
                {EXECUTION_STATE_INFO[column.state]?.icon}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Main Workbook Table */}
      <div className="workbook-container">
        <div className="workbook-scroll">
          <table className="workbook-table">
            <thead>
              <tr>
                {/* Row Header */}
                <th className="row-header-col">
                  <div className="header-cell">
                    <span>Row #</span>
                  </div>
                </th>

                {/* Column Headers with Control Panels */}
                {columns.map(column => (
                  <th key={column.column_id} className={`column-header ${column.is_locked ? 'locked' : ''}`}>
                    <div className="header-cell">
                      <div className="column-title">
                        <span>{COLUMN_TYPE_INFO[column.column_type]?.icon}</span>
                        <span>{column.name}</span>
                        {column.is_locked && <span title="Column locked">🔒</span>}
                      </div>
                      
                      <ColumnExecutionPanel
                        column={column}
                        onExecute={() => handleExecuteColumn(column.column_id)}
                        onRetry={() => handleRetryColumn(column.column_id)}
                        onLock={() => handleLockColumn(column.column_id)}
                        onUnlock={() => handleUnlockColumn(column.column_id)}
                        loading={executingColumn === column.column_id}
                      />
                    </div>
                  </th>
                ))}
              </tr>
            </thead>

            <tbody>
              {rows.map(row => (
                <tr key={row.row_id} className="data-row">
                  {/* Row Header Cell */}
                  <td className="row-header-cell">
                    <div className="row-index">{row.row_index + 1}</div>
                    <div className="row-status">{row.status}</div>
                  </td>

                  {/* Data Cells */}
                  {columns.map(column => {
                    const cellId = `${row.row_id}_${column.column_id}`;
                    const cellValue = cells[cellId];

                    return (
                      <td
                        key={cellId}
                        className={`data-cell ${selectedCell === cellId ? 'selected' : ''}`}
                        onClick={() => setSelectedCell(cellId)}
                      >
                        <div className="cell-wrapper">
                          {editingCell === cellId ? (
                            <input
                              type="text"
                              className="cell-input"
                              defaultValue={cellValue?.final_value || ''}
                              onBlur={(e) => {
                                handleCellOverride(row.row_id, column.column_id, e.target.value);
                                setEditingCell(null);
                              }}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') {
                                  handleCellOverride(row.row_id, column.column_id, e.target.value);
                                  setEditingCell(null);
                                }
                              }}
                              autoFocus
                            />
                          ) : (
                            <>
                              <CellDisplay
                                cellValue={cellValue}
                                column={column}
                                isEditing={editingCell === cellId}
                                onEdit={() => setEditingCell(cellId)}
                              />
                              {cellValue && (
                                <span
                                  className="cell-edit-btn"
                                  onClick={() => setEditingCell(cellId)}
                                  title="Click to edit (manual override)"
                                >
                                  ✏️
                                </span>
                              )}
                            </>
                          )}
                          
                          {cellValue && (
                            <div className={`cell-state-indicator ${cellValue.execution_state}`}>
                              {EXECUTION_STATE_INFO[cellValue.execution_state]?.icon}
                            </div>
                          )}
                        </div>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Details Panel */}
      {selectedCell && (
        <div className="details-panel">
          <div className="details-header">
            <h3>Cell Details</h3>
            <button className="close-btn" onClick={() => setSelectedCell(null)}>×</button>
          </div>

          <div className="details-content">
            {cells[selectedCell] && (
              <>
                <div className="detail-group">
                  <label>Value</label>
                  <div className="detail-value">
                    {cells[selectedCell].final_value}
                  </div>
                </div>

                <div className="detail-group">
                  <label>Source</label>
                  <span>{cells[selectedCell].source}</span>
                </div>

                <div className="detail-group">
                  <label>Confidence</label>
                  <div className="confidence-bar">
                    <div
                      className="confidence-fill"
                      style={{ width: `${(cells[selectedCell].confidence_score || 0) * 100}%` }}
                    />
                  </div>
                  <span>{((cells[selectedCell].confidence_score || 0) * 100).toFixed(0)}%</span>
                </div>

                <div className="detail-group">
                  <label>Cost</label>
                  <span>${cells[selectedCell].cost?.toFixed(4)}</span>
                </div>

                {cells[selectedCell].manual_override !== null && cells[selectedCell].manual_override !== undefined && (
                  <div className="detail-group override-indicator">
                    <label>Manual Override</label>
                    <span>✏️ User-set value (never overwritten)</span>
                  </div>
                )}

                <div className="detail-group">
                  <label>Extracted Value</label>
                  <small>{cells[selectedCell].extracted_value || '-'}</small>
                </div>

                <div className="detail-group">
                  <label>Enriched Value</label>
                  <small>{cells[selectedCell].enriched_value || '-'}</small>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default Workbook;
