/**
 * Surveys Hook
 * Fetches and manages available surveys for panelists
 */

import { useState, useEffect, useCallback } from 'react';
import { getAvailableSurveys, startSurvey as apiStartSurvey } from '../services/panelApi';

export function useSurveys() {
  const [surveys, setSurveys] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchSurveys = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getAvailableSurveys();
      setSurveys(data);
    } catch (err) {
      setError(err.message || 'Failed to load surveys');
      setSurveys([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSurveys();
  }, [fetchSurveys]);

  const startSurvey = useCallback(async (surveyId) => {
    try {
      const data = await apiStartSurvey(surveyId);
      return data;
    } catch (err) {
      throw new Error(err.message || 'Failed to start survey');
    }
  }, []);

  const refetch = useCallback(() => {
    fetchSurveys();
  }, [fetchSurveys]);

  return {
    surveys,
    loading,
    error,
    refetch,
    startSurvey,
  };
}

export default useSurveys;
