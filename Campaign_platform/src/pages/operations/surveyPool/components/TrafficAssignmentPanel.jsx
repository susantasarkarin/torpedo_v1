import React, { useState } from 'react';
import { API_BASE_URL } from '../../../../config';

export default function TrafficAssignmentPanel({ survey, token, onAssignmentComplete }) {
  const [batchSize, setBatchSize] = useState(100);
  const [assigning, setAssigning] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [validationError, setValidationError] = useState('');
  const [preview, setPreview] = useState(null);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [availableTraffic, setAvailableTraffic] = useState(null);

  // Fetch available traffic count when survey changes
  React.useEffect(() => {
    if (survey && token) {
      fetchAvailableTraffic();
    }
  }, [survey?.survey_id, token]);

  const fetchAvailableTraffic = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/traffic/available`, {
        method: 'GET',
        headers: {
          'Authorization': token,
          'Content-Type': 'application/json',
        },
      });

      if (response.ok) {
        const data = await response.json();
        setAvailableTraffic(data.available || 0);
      }
    } catch (err) {
      console.error('Error fetching available traffic:', err);
    }
  };

  const validateBatchSize = (value) => {
    const size = parseInt(value);
    
    if (!value || isNaN(size)) {
      setValidationError('Batch size is required');
      return false;
    }
    
    if (size <= 0) {
      setValidationError('Batch size must be greater than 0');
      return false;
    }
    
    if (size > 1000) {
      setValidationError('Batch size cannot exceed 1000');
      return false;
    }
    
    if (availableTraffic !== null && size > availableTraffic) {
      setValidationError(`Only ${availableTraffic} unassigned records available`);
      return false;
    }
    
    setValidationError('');
    return true;
  };

  const handleBatchSizeChange = (e) => {
    const value = e.target.value;
    setBatchSize(value);
    validateBatchSize(value);
    setPreview(null); // Clear preview when batch size changes
  };

  const handlePreview = async () => {
    if (!validateBatchSize(batchSize)) {
      return;
    }

    setLoadingPreview(true);
    setError(null);

    try {
      const response = await fetch(`${API_BASE_URL}/cpx/assign-traffic/preview`, {
        method: 'POST',
        headers: {
          'Authorization': token,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          survey_id: survey.survey_id,
          batch_size: parseInt(batchSize),
        }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Failed to generate preview');
      }

      const data = await response.json();
      setPreview(data);
    } catch (err) {
      console.error('Preview error:', err);
      setError(err.message);
    } finally {
      setLoadingPreview(false);
    }
  };

  const handleAssignTraffic = async () => {
    if (!survey || !survey.survey_id) {
      setError('No survey selected');
      return;
    }

    if (!validateBatchSize(batchSize)) {
      return;
    }

    setAssigning(true);
    setError(null);
    setResult(null);
    setPreview(null);

    try {
      const response = await fetch(`${API_BASE_URL}/cpx/assign-traffic`, {
        method: 'POST',
        headers: {
          'Authorization': token,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          survey_id: survey.survey_id,
          batch_size: parseInt(batchSize),
        }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Failed to assign traffic');
      }

      const data = await response.json();
      setResult(data);

      if (onAssignmentComplete) {
        onAssignmentComplete(data);
      }
    } catch (err) {
      console.error('Assignment error:', err);
      setError(err.message);
    } finally {
      setAssigning(false);
    }
  };

  return (
    <div className="traffic-assignment-panel">
      <h3>🎯 Traffic Assignment</h3>
      
      {survey && (
        <div className="survey-info">
          <p><strong>Survey ID:</strong> {survey.survey_id}</p>
          <p><strong>LOI:</strong> {survey.loi} min</p>
          <p><strong>Payout:</strong> ${survey.payout?.toFixed(2)}</p>
          {availableTraffic !== null && (
            <p><strong>Available Traffic:</strong> <span className="available-count">{availableTraffic.toLocaleString()}</span> unassigned records</p>
          )}
        </div>
      )}

      <div className="assignment-controls">
        <label>
          <span>Batch Size:</span>
          <input
            type="number"
            min="1"
            max="1000"
            value={batchSize}
            onChange={handleBatchSizeChange}
            disabled={assigning || loadingPreview}
            className={validationError ? 'input-error' : ''}
          />
          {validationError && (
            <span className="validation-error">{validationError}</span>
          )}
        </label>

        <div className="action-buttons">
          <button
            className="preview-button"
            onClick={handlePreview}
            disabled={assigning || loadingPreview || !survey || !!validationError}
          >
            {loadingPreview ? '⏳ Loading...' : '👁️ Preview'}
          </button>

          <button
            className="assign-button"
            onClick={handleAssignTraffic}
            disabled={assigning || loadingPreview || !survey || !!validationError}
          >
            {assigning ? '⏳ Assigning...' : '📤 Assign Traffic'}
          </button>
        </div>
      </div>

      {error && (
        <div className="assignment-error">
          <strong>❌ Error:</strong> {error}
        </div>
      )}

      {preview && (
        <div className="assignment-preview">
          <h4>📋 Assignment Preview</h4>
          <p className="preview-info">
            <strong>{preview.available_count || 0}</strong> unassigned records will be assigned to Survey <strong>{survey.survey_id}</strong>
          </p>
          {preview.sample_records && preview.sample_records.length > 0 && (
            <details className="preview-details">
              <summary>Sample Records ({preview.sample_records.length})</summary>
              <ul className="preview-list">
                {preview.sample_records.map((record, index) => (
                  <li key={index}>
                    <code>VID: {record.vid} | CC: {record.cc} | RID: {record.rid}</code>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}

      {result && (
        <div className="assignment-result">
          <h4>✅ Assignment Complete</h4>
          <div className="result-stats">
            <div className="stat-item">
              <span className="stat-label">Total Records:</span>
              <span className="stat-value">{result.total_records}</span>
            </div>
            <div className="stat-item">
              <span className="stat-label">Assigned:</span>
              <span className="stat-value success">{result.assigned}</span>
            </div>
            <div className="stat-item">
              <span className="stat-label">Failed:</span>
              <span className="stat-value error">{result.failed}</span>
            </div>
          </div>

          {result.redirect_urls && result.redirect_urls.length > 0 && (
            <details className="redirect-urls">
              <summary>Sample Redirect URLs ({result.redirect_urls.length})</summary>
              <ul>
                {result.redirect_urls.map((item, index) => (
                  <li key={index}>
                    <code>{item.redirect_url}</code>
                  </li>
                ))}
              </ul>
            </details>
          )}

          <p className="result-message">{result.message}</p>
        </div>
      )}

      <style jsx>{`
        .traffic-assignment-panel {
          background: #f8f9fa;
          border: 1px solid #dee2e6;
          border-radius: 8px;
          padding: 20px;
          margin: 20px 0;
        }

        .traffic-assignment-panel h3 {
          margin: 0 0 15px 0;
          color: #495057;
        }

        .survey-info {
          background: white;
          padding: 12px;
          border-radius: 6px;
          margin-bottom: 15px;
          font-size: 14px;
        }

        .survey-info p {
          margin: 5px 0;
        }

        .assignment-controls {
          display: flex;
          gap: 15px;
          align-items: flex-end;
          margin-bottom: 15px;
        }

        .assignment-controls label {
          display: flex;
          flex-direction: column;
          gap: 5px;
        }

        .assignment-controls input {
          padding: 8px 12px;
          border: 1px solid #ced4da;
          border-radius: 4px;
          width: 120px;
        }

        .assign-button {
          padding: 10px 20px;
          background: #007bff;
          color: white;
          border: none;
          border-radius: 4px;
          cursor: pointer;
          font-weight: 500;
        }

        .assign-button:hover:not(:disabled) {
          background: #0056b3;
        }

        .assign-button:disabled {
          background: #6c757d;
          cursor: not-allowed;
        }

        .assignment-error {
          background: #f8d7da;
          color: #721c24;
          padding: 12px;
          border-radius: 6px;
          margin-top: 10px;
        }

        .assignment-result {
          background: #d4edda;
          border: 1px solid #c3e6cb;
          border-radius: 6px;
          padding: 15px;
          margin-top: 15px;
        }

        .assignment-result h4 {
          margin: 0 0 12px 0;
          color: #155724;
        }

        .result-stats {
          display: grid;
          grid-template-columns: repeat(3, 1fr);
          gap: 10px;
          margin-bottom: 15px;
        }

        .stat-item {
          background: white;
          padding: 10px;
          border-radius: 4px;
          text-align: center;
        }

        .stat-label {
          display: block;
          font-size: 12px;
          color: #666;
          margin-bottom: 5px;
        }

        .stat-value {
          display: block;
          font-size: 20px;
          font-weight: bold;
        }

        .stat-value.success {
          color: #28a745;
        }

        .stat-value.error {
          color: #dc3545;
        }

        .redirect-urls {
          background: white;
          padding: 10px;
          border-radius: 4px;
          margin-bottom: 10px;
        }

        .redirect-urls summary {
          cursor: pointer;
          font-weight: 500;
          margin-bottom: 10px;
        }

        .redirect-urls ul {
          list-style: none;
          padding: 0;
          margin: 0;
        }

        .redirect-urls li {
          padding: 5px 0;
          font-size: 12px;
        }

        .redirect-urls code {
          background: #f8f9fa;
          padding: 2px 6px;
          border-radius: 3px;
          font-family: monospace;
          word-break: break-all;
        }

        .result-message {
          margin: 10px 0 0 0;
          font-style: italic;
          color: #155724;
        }
      `}</style>
    </div>
  );
}
