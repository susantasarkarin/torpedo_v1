import { useState, useCallback } from 'react';
import { API_BASE_URL } from '../../../../config';

/**
 * Custom hook for managing survey filter settings
 * Handles saving and loading filter preferences from the backend
 */
function useSurveyFilters(token) {
  const [filters, setFilters] = useState({
    min_loi: null,
    max_loi: null,
    min_payout: null,
    country: null,
    category: null,
  });

  const [savedFilters, setSavedFilters] = useState(null);
  const [savingFilters, setSavingFilters] = useState(false);
  const [error, setError] = useState(null);

  const updateFilters = useCallback((newFilters) => {
    setFilters((prevFilters) => ({
      ...prevFilters,
      ...newFilters,
    }));
  }, []);

  const loadFilterSettings = useCallback(async () => {
    if (!token) {
      setError('No authentication token');
      return;
    }

    try {
      const response = await fetch('/cpx/filter-settings', {
        method: 'GET',
        headers: {
          'Authorization': token,
          'Content-Type': 'application/json',
        },
      });

      if (!response.ok) {
        if (response.status === 401) {
          console.log('No saved filters yet');
          return;
        }
        throw new Error(`HTTP ${response.status}`);
      }

      const data = await response.json();
      const savedSettings = data.filters || {};

      // Apply saved filters if they exist
      if (Object.keys(savedSettings).length > 0) {
        setFilters(savedSettings);
        setSavedFilters(savedSettings);
        console.log('✅ Loaded saved filter settings:', savedSettings);
      }
    } catch (err) {
      console.error('Error loading filter settings:', err);
      // Don't fail if we can't load saved filters
    }
  }, [token]);

  const saveFilterSettings = useCallback(
    async (filterData) => {
      if (!token) {
        setError('No authentication token');
        return;
      }

      setSavingFilters(true);
      setError(null);

      try {
        const response = await fetch(`${API_BASE_URL}/cpx/filter-settings`, {
          method: 'POST',
          headers: {
            'Authorization': token,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            ...filterData,
            lastUpdated: new Date().toISOString(),
          }),
        });

        if (!response.ok) {
          if (response.status === 401) {
            throw new Error('Unauthorized - please login again');
          }
          throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const data = await response.json();
        setSavedFilters({ ...filterData, lastUpdated: new Date().toISOString() });
        console.log('✅ Filter settings saved:', data);
      } catch (err) {
        console.error('Error saving filter settings:', err);
        setError(err.message || 'Failed to save filter settings');
      } finally {
        setSavingFilters(false);
      }
    },
    [token]
  );

  return {
    filters,
    updateFilters,
    savedFilters,
    savingFilters,
    error,
    loadFilterSettings,
    saveFilterSettings,
  };
}

export default useSurveyFilters;
