import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { useAuth } from '../../../hooks/useAuth';
import { API_BASE_URL } from '../../../config';
import useSurveyPoolData from './hooks/useSurveyPoolData';
import useSurveyFilters from './hooks/useSurveyFilters';
import SurveyFilterPanel from './components/SurveyFilterPanel';
import SurveyDataTable from './components/SurveyDataTable';
import SurveyPoolStats from './components/SurveyPoolStats';
import TrafficAssignmentPanel from './components/TrafficAssignmentPanel';
import './SurveyPool.css';

export default function SurveyPool() {
  const { user, token } = useAuth();
  const [recordsPerPage, setRecordsPerPage] = useState(20);
  const [currentPage, setCurrentPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [selectedSurvey, setSelectedSurvey] = useState(null);
  const [trafficRefreshTrigger, setTrafficRefreshTrigger] = useState(0);

  // Hooks for data and filters
  const {
    surveys,
    totalSurveys,
    isLoading: dataLoading,
    error: dataError,
    fetchSurveys,
    refreshSurveys,
  } = useSurveyPoolData(token);

  const {
    filters,
    updateFilters,
    savedFilters,
    savingFilters,
    loadFilterSettings,
    saveFilterSettings,
  } = useSurveyFilters(token);

  // Load filter settings on mount
  useEffect(() => {
    if (token) {
      loadFilterSettings();
    }
  }, [token]);

  // Fetch ALL surveys without filters (filters applied client-side)
  useEffect(() => {
    if (token) {
      setLoading(true);
      fetchSurveys({
        page: 1,
        page_size: 100, // Max allowed by backend API (le=100)
      }).then((data) => {
        if (data?.last_updated) {
          setLastUpdated(data.last_updated);
        }
      }).finally(() => setLoading(false));
    }
  }, [token]);

  // Client-side filtering of surveys
  const filteredSurveys = useMemo(() => {
    let filtered = [...surveys];

    // Apply min LOI filter
    if (filters.min_loi) {
      filtered = filtered.filter(s => s.loi >= filters.min_loi);
    }

    // Apply max LOI filter
    if (filters.max_loi) {
      filtered = filtered.filter(s => s.loi <= filters.max_loi);
    }

    // Apply min payout filter
    if (filters.min_payout) {
      filtered = filtered.filter(s => s.payout >= filters.min_payout);
    }

    // Apply country filter
    if (filters.country) {
      filtered = filtered.filter(s => s.country === filters.country);
    }

    return filtered;
  }, [surveys, filters]);

  // Client-side pagination
  const paginatedSurveys = useMemo(() => {
    const startIndex = (currentPage - 1) * recordsPerPage;
    const endIndex = startIndex + recordsPerPage;
    return filteredSurveys.slice(startIndex, endIndex);
  }, [filteredSurveys, currentPage, recordsPerPage]);

  // Reset to page 1 when filters change
  useEffect(() => {
    setCurrentPage(1);
  }, [filters]);

  // Manual refresh handler
  const handleManualRefresh = useCallback(async () => {
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

      const data = await response.json();
      console.log('✅ CPX refresh complete:', data);

      // Fetch latest surveys (all surveys, no filters)
      const surveyData = await fetchSurveys({
        page: 1,
        page_size: 1000,
      });
      
      if (surveyData?.last_updated) {
        setLastUpdated(surveyData.last_updated);
      }
      setCurrentPage(1);
    } catch (err) {
      console.error('Error refreshing CPX inventory:', err);
    } finally {
      setLoading(false);
    }
  }, [token, filters, recordsPerPage]);

  // Handle filter save
  const handleSaveFilters = useCallback(async () => {
    try {
      await saveFilterSettings(filters);
      console.log('✅ Filters saved successfully');
    } catch (err) {
      console.error('Error saving filters:', err);
    }
  }, [filters]);

  // Calculate pagination based on filtered surveys
  const totalFilteredSurveys = filteredSurveys.length;
  const totalPages = Math.ceil(totalFilteredSurveys / recordsPerPage);

  if (!user) {
    return <div className="survey-pool-container">Please login to access Survey Pool.</div>;
  }

  return (
    <div className="survey-pool-container">
      <div className="survey-pool-header">
        <h1>📋 Survey Pool</h1>
        <p>Manage CPX Research survey inventory and filtering</p>
      </div>

      {/* Stats Section */}
      <SurveyPoolStats
        totalSurveys={totalSurveys}
        filteredSurveys={totalFilteredSurveys}
        lastUpdated={lastUpdated}
        onManualRefresh={handleManualRefresh}
        refreshing={loading}
      />

      {/* Filter Panel */}
      <SurveyFilterPanel
        filters={filters}
        onFilterChange={updateFilters}
        onSaveFilters={handleSaveFilters}
        saving={savingFilters}
      />

      {/* Loading State */}
      {loading && surveys.length === 0 && !dataError && (
        <div className="survey-pool-loading">
          <div className="loading-spinner"></div>
          <p>⏳ Loading surveys...</p>
        </div>
      )}

      {/* Error State */}
      {dataError && (
        <div className="survey-pool-error">
          <p>❌ Failed to fetch surveys</p>
          <p className="error-detail">{dataError}</p>
          <button onClick={handleManualRefresh} className="retry-btn">
            🔄 Retry
          </button>
        </div>
      )}

      {/* Survey Data Table */}
      {paginatedSurveys.length > 0 && (
        <>
          <SurveyDataTable 
            surveys={paginatedSurveys}
            token={token}
            onSurveySelect={setSelectedSurvey}
            selectedSurveyId={selectedSurvey?._id}
          />

          {/* Traffic Assignment Panel */}
          {selectedSurvey && (
            <TrafficAssignmentPanel
              survey={selectedSurvey}
              token={token}
              onAssignmentComplete={() => {
                setTrafficRefreshTrigger(prev => prev + 1);
                setSelectedSurvey(null);
              }}
            />
          )}

          {/* Pagination Controls */}
          {totalFilteredSurveys > recordsPerPage && (
          <div className="survey-pool-pagination">
            <div className="pagination-info">
              Showing {(currentPage - 1) * recordsPerPage + 1} to{' '}
              {Math.min(currentPage * recordsPerPage, totalFilteredSurveys)} of {totalFilteredSurveys} surveys
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

      {filteredSurveys.length === 0 && surveys.length > 0 && !dataError && !loading && (
        <div className="survey-pool-empty">
          <div className="empty-icon">🔍</div>
          <p className="empty-title">No surveys match your filters</p>
          <p className="empty-subtitle">Try adjusting your filter criteria to see more results.</p>
        </div>
      )}

      {surveys.length === 0 && !dataError && !loading && (
        <div className="survey-pool-empty">
          <div className="empty-icon">📭</div>
          <p className="empty-title">No surveys available</p>
          <p className="empty-subtitle">Refresh to check for new surveys from CPX Research.</p>
        </div>
      )}
    </div>
  );
}
