import React from 'react';

export default function SurveyFilterPanel({
  filters,
  onFilterChange,
  onSaveFilters,
  saving,
}) {
  const handleInputChange = (e) => {
    const { name, value } = e.target;
    onFilterChange({
      [name]: value === '' ? null : isNaN(value) ? value : Number(value),
    });
  };

  return (
    <div className="survey-filter-panel">
      <div className="filter-panel-header">🔍 Survey Filters</div>

      <div className="filter-grid">
        <div className="filter-group">
          <label className="filter-label">Min Length of Interview (LOI)</label>
          <input
            type="number"
            name="min_loi"
            value={filters.min_loi || ''}
            onChange={handleInputChange}
            placeholder="e.g., 5"
            className="filter-input"
            min="0"
          />
        </div>

        <div className="filter-group">
          <label className="filter-label">Max Length of Interview (LOI)</label>
          <input
            type="number"
            name="max_loi"
            value={filters.max_loi || ''}
            onChange={handleInputChange}
            placeholder="e.g., 20"
            className="filter-input"
            min="0"
          />
        </div>

        <div className="filter-group">
          <label className="filter-label">Min Payout ($)</label>
          <input
            type="number"
            name="min_payout"
            value={filters.min_payout || ''}
            onChange={handleInputChange}
            placeholder="e.g., 1.50"
            className="filter-input"
            min="0"
            step="0.10"
          />
        </div>

        <div className="filter-group">
          <label className="filter-label">Country</label>
          <select
            name="country"
            value={filters.country || ''}
            onChange={handleInputChange}
            className="filter-select"
          >
            <option value="">All Countries</option>
            <option value="US">United States</option>
            <option value="CA">Canada</option>
            <option value="GB">United Kingdom</option>
            <option value="AU">Australia</option>
            <option value="DE">Germany</option>
            <option value="FR">France</option>
            <option value="IN">India</option>
            <option value="NZ">New Zealand</option>
          </select>
        </div>
      </div>

      <div className="filter-actions">
        <button
          className="save-filters-btn"
          onClick={onSaveFilters}
          disabled={saving}
        >
          {saving ? '💾 Saving...' : '💾 Save Filters'}
        </button>
      </div>
    </div>
  );
}
