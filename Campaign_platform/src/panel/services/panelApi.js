/**
 * PANEL API SERVICE
 * Handles all API requests for the Survey Panel module.
 */

import { API_BASE_URL } from '../../config';
import { buildApiUrl } from "../../config"

// ============== SESSION MANAGEMENT ==============

export const getPanelSessionId = () => {
  return localStorage.getItem('panel_session_id') || null;
};

export const setPanelSessionId = (sessionId) => {
  if (sessionId) {
    localStorage.setItem('panel_session_id', sessionId);
  } else {
    localStorage.removeItem('panel_session_id');
  }
};

export const getPanelistData = () => {
  const data = localStorage.getItem('panelist_data');
  return data ? JSON.parse(data) : null;
};

export const setPanelistData = (data) => {
  if (data) {
    localStorage.setItem('panelist_data', JSON.stringify(data));
  } else {
    localStorage.removeItem('panelist_data');
  }
};

export const clearPanelSession = () => {
  localStorage.removeItem('panel_session_id');
  localStorage.removeItem('panelist_data');
};

export const isPanelAuthenticated = () => {
  return !!getPanelSessionId();
};

// ============== API REQUEST HELPER ==============

const panelRequest = async (endpoint, options = {}) => {
  const sessionId = getPanelSessionId();

  const headers = {
    'Content-Type': 'application/json',
    ...(sessionId && { 'X-Panel-Session-Id': sessionId }),
    ...options.headers,
  };

  // Panel API calls go to /api/panel/*, never the bare /panel/* path. nginx
  // used to proxy every /panel/* request to the backend, which meant the
  // SPA's own /panel/login, /panel/signup and /panel/dashboard pages were
  // unreachable by direct navigation — the backend answered GET /panel/login
  // with 405 and GET /panel/dashboard with 404. Now that /panel/* belongs to
  // the SPA, the API has to be addressed explicitly.
  const response = await fetch(buildApiUrl(`/api${endpoint}`), {
    ...options,
    headers,
  });

  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    const error = new Error(data.detail || 'Request failed');
    error.status = response.status;
    error.data = data;
    throw error;
  }

  return data;
};

// ============== AUTH ENDPOINTS ==============

export const panelLogin = async (email, password) => {
  const data = await panelRequest('/panel/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  });

  // Store session data
  setPanelSessionId(data.panel_session_id);
  setPanelistData({
    id: data.panelist_id,
    email: data.email,
    firstName: data.first_name,
    lastName: data.last_name,
    rewardsBalance: data.rewards_balance,
  });

  return data;
};

export const panelSignup = async (signupData) => {
  const data = await panelRequest('/panel/signup', {
    method: 'POST',
    body: JSON.stringify(signupData),
  });

  // Store session data after successful signup
  setPanelSessionId(data.panel_session_id);
  setPanelistData({
    id: data.panelist_id,
    email: data.email,
    firstName: data.first_name,
    lastName: data.last_name,
    rewardsBalance: data.rewards_balance,
  });

  return data;
};

export const panelLogout = async () => {
  try {
    await panelRequest('/panel/logout', { method: 'POST' });
  } catch (error) {
    console.error('Logout error:', error);
  } finally {
    clearPanelSession();
  }
};

export const forgotPassword = async (email) => {
  return panelRequest('/panel/forgot-password', {
    method: 'POST',
    body: JSON.stringify({ email }),
  });
};

export const resetPassword = async (token, newPassword) => {
  return panelRequest('/panel/reset-password', {
    method: 'POST',
    body: JSON.stringify({ token, new_password: newPassword }),
  });
};

// Re-sends the double opt-in email. The server answers identically whether or
// not the address exists, so callers can only show a generic confirmation.
export const resendVerification = async (email) => {
  return panelRequest('/panel/resend-verification', {
    method: 'POST',
    body: JSON.stringify({ email }),
  });
};

// ============== PROFILE ENDPOINTS ==============

export const getProfile = async () => {
  return panelRequest('/panel/profile');
};

export const updateProfile = async (profileData) => {
  return panelRequest('/panel/profile', {
    method: 'PUT',
    body: JSON.stringify(profileData),
  });
};

export const getProfileCompletion = async () => {
  return panelRequest('/panel/profile/completion');
};

// ============== SURVEY ENDPOINTS ==============

export const getAvailableSurveys = async () => {
  return panelRequest('/panel/surveys');
};

export const startSurvey = async (surveyId) => {
  return panelRequest(`/panel/surveys/${surveyId}/start`, {
    method: 'POST',
  });
};

// ============== REWARDS ENDPOINTS ==============

export const getRewardsBalance = async () => {
  return panelRequest('/panel/rewards/balance');
};

export const getRewardsHistory = async (skip = 0, limit = 20) => {
  return panelRequest(`/panel/rewards/history?skip=${skip}&limit=${limit}`);
};

export default {
  // Auth
  panelLogin,
  panelSignup,
  panelLogout,
  forgotPassword,
  resetPassword,
  resendVerification,

  // Session
  getPanelSessionId,
  isPanelAuthenticated,
  clearPanelSession,
  getPanelistData,
  
  // Profile
  getProfile,
  updateProfile,
  getProfileCompletion,
  
  // Surveys
  getAvailableSurveys,
  startSurvey,
  
  // Rewards
  getRewardsBalance,
  getRewardsHistory,
};
