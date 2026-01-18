/**
 * Rewards Hook
 * Fetches and manages rewards data for panelists
 */

import { useState, useEffect, useCallback } from 'react';
import { getRewardsBalance, getRewardsHistory } from '../services/panelApi';

export function useRewards() {
  const [balance, setBalance] = useState({ balance: 0, currency: 'INR', pending: 0 });
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchBalance = useCallback(async () => {
    try {
      const data = await getRewardsBalance();
      setBalance(data);
    } catch (err) {
      console.error('Failed to fetch rewards balance:', err);
    }
  }, []);

  const fetchHistory = useCallback(async (skip = 0, limit = 20) => {
    try {
      const data = await getRewardsHistory(skip, limit);
      setHistory(data);
    } catch (err) {
      console.error('Failed to fetch rewards history:', err);
    }
  }, []);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      await Promise.all([fetchBalance(), fetchHistory()]);
    } catch (err) {
      setError(err.message || 'Failed to load rewards data');
    } finally {
      setLoading(false);
    }
  }, [fetchBalance, fetchHistory]);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  const refetch = useCallback(() => {
    fetchAll();
  }, [fetchAll]);

  return {
    balance,
    history,
    loading,
    error,
    refetch,
    fetchBalance,
    fetchHistory,
  };
}

export default useRewards;
