import { useState, useCallback } from 'react';
import { API_BASE_URL } from '../../../../config';
import { buildApiUrl } from "../../../../config"

/**
 * Custom hook for managing survey pool data
 * Handles fetching, refreshing, and pagination of CPX surveys
 */
function useSurveyPoolData(token) {
  const [surveys, setSurveys] = useState([]);
  const [totalSurveys, setTotalSurveys] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);

  const fetchSurveys = useCallback(
    async (filters = {}) => {
      if (!token) {
        setError('No authentication token');
        return;
      }

      setIsLoading(true);
      setError(null);

      try {
        const queryParams = new URLSearchParams();

        // Add filter parameters
        if (filters.min_loi) queryParams.append('min_loi', filters.min_loi);
        if (filters.max_loi) queryParams.append('max_loi', filters.max_loi);
        if (filters.min_payout) queryParams.append('min_payout', filters.min_payout);
        if (filters.country) queryParams.append('country', filters.country);
        if (filters.category) queryParams.append('category', filters.category);

        // Add pagination parameters
        const page = filters.page || 1;
        const page_size = filters.page_size || 20;
        queryParams.append('page', page);
        queryParams.append('page_size', page_size);

        const response = await fetch(buildApiUrl(`/cpx/surveys?${queryParams}`), {
          method: 'GET',
          headers: {
            'Authorization': token,
            'Content-Type': 'application/json',
          },
        });

        if (!response.ok) {
          if (response.status === 401) {
            throw new Error('Unauthorized - please login again');
          }
          throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const data = await response.json();
        console.log('Survey data received:', data);
        setSurveys(data.surveys || []);
        setTotalSurveys(data.total || 0);
        
        // Return the data for further use (e.g., last_updated)
        return data;
      } catch (err) {
        console.error('Error fetching surveys:', err);
        setError(err.message || 'Failed to fetch surveys');
        setSurveys([]);
        setTotalSurveys(0);
      } finally {
        setIsLoading(false);
      }
    },
    [token]
  );

  const refreshSurveys = useCallback(async () => {
    if (!token) {
      setError('No authentication token');
      return;
    }

    try {
      const response = await fetch(buildApiUrl(`/cpx/refresh`), {
        method: 'POST',
        headers: {
          'Authorization': token,
          'Content-Type': 'application/json',
        },
      });

      if (!response.ok) {
        throw new Error(`Refresh failed: ${response.statusText}`);
      }

      const data = await response.json();
      console.log('CPX refresh complete:', data);
    } catch (err) {
      console.error('Error refreshing surveys:', err);
      setError(err.message || 'Failed to refresh surveys');
    }
  }, [token]);

  return {
    surveys,
    totalSurveys,
    isLoading,
    error,
    fetchSurveys,
    refreshSurveys,
  };
}

export default useSurveyPoolData;
