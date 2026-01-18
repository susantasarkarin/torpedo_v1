/**
 * Panel Authentication Context
 * Manages authentication state for Survey Panel users (panelists)
 */

import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import {
  getPanelSessionId,
  getPanelistData,
  panelLogin as apiLogin,
  panelSignup as apiSignup,
  panelLogout as apiLogout,
  clearPanelSession,
  getProfileCompletion,
} from '../services/panelApi';

const PanelAuthContext = createContext(null);

export function PanelAuthProvider({ children }) {
  const [panelist, setPanelist] = useState(null);
  const [loading, setLoading] = useState(true);
  const [profileCompletion, setProfileCompletion] = useState(0);

  // Initialize auth state from localStorage
  useEffect(() => {
    const sessionId = getPanelSessionId();
    const panelistData = getPanelistData();

    if (sessionId && panelistData) {
      setPanelist(panelistData);
      // Fetch profile completion in background
      getProfileCompletion()
        .then((data) => setProfileCompletion(data.completion))
        .catch(() => {}); // Ignore errors on initial load
    }
    setLoading(false);
  }, []);

  const login = useCallback(async (email, password) => {
    const data = await apiLogin(email, password);
    setPanelist({
      id: data.panelist_id,
      email: data.email,
      firstName: data.first_name,
      lastName: data.last_name,
      rewardsBalance: data.rewards_balance,
    });
    return data;
  }, []);

  const signup = useCallback(async (signupData) => {
    const data = await apiSignup(signupData);
    setPanelist({
      id: data.panelist_id,
      email: data.email,
      firstName: data.first_name,
      lastName: data.last_name,
      rewardsBalance: data.rewards_balance,
    });
    return data;
  }, []);

  const logout = useCallback(async () => {
    await apiLogout();
    setPanelist(null);
    setProfileCompletion(0);
    // Navigate using window.location for simplicity
    window.location.href = '/panel/login';
  }, []);

  const refreshProfileCompletion = useCallback(async () => {
    try {
      const data = await getProfileCompletion();
      setProfileCompletion(data.completion);
      return data;
    } catch (error) {
      console.error('Failed to refresh profile completion:', error);
      return null;
    }
  }, []);

  const updatePanelistData = useCallback((updates) => {
    setPanelist((prev) => {
      if (!prev) return prev;
      const updated = { ...prev, ...updates };
      // Also update localStorage
      localStorage.setItem('panelist_data', JSON.stringify(updated));
      return updated;
    });
  }, []);

  const isAuthenticated = !!panelist && !!getPanelSessionId();

  const value = {
    panelist,
    loading,
    isAuthenticated,
    profileCompletion,
    login,
    signup,
    logout,
    refreshProfileCompletion,
    updatePanelistData,
  };

  return (
    <PanelAuthContext.Provider value={value}>
      {children}
    </PanelAuthContext.Provider>
  );
}

export function usePanelAuth() {
  const context = useContext(PanelAuthContext);
  if (!context) {
    throw new Error('usePanelAuth must be used within a PanelAuthProvider');
  }
  return context;
}

export default PanelAuthContext;
