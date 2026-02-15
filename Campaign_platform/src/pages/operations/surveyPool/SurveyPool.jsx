import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { useAuth } from '../../../hooks/useAuth';
import { API_BASE_URL } from '../../../config';
import { buildApiUrl } from "../../../config"
// Temporarily disabled for debugging
// import useSurveyWebSocket from '../../../hooks/useSurveyWebSocket';
import './SurveyPool.css';

// Cint country_language ID to country code mapping
const CINT_COUNTRY_LANGUAGE_MAP = {
  1: 'UK', 2: 'FR', 3: 'DE', 4: 'NL', 5: 'AU', 6: 'CA', 7: 'NZ', 8: 'IE', 9: 'US',
  10: 'ES', 11: 'IT', 12: 'BR', 13: 'MX', 14: 'AR', 15: 'CL', 16: 'CO', 17: 'PE',
  18: 'AT', 19: 'CH', 20: 'BE', 21: 'SE', 22: 'NO', 23: 'DK', 24: 'KR', 25: 'JP',
  26: 'CN', 27: 'IN', 28: 'BE', 29: 'PL', 30: 'RU', 31: 'TR', 32: 'ZA', 33: 'SG',
  34: 'MY', 35: 'TH', 36: 'PH', 37: 'ID', 38: 'VN', 39: 'TW', 40: 'HK', 41: 'AE',
  42: 'SA', 43: 'EG', 44: 'NG', 45: 'KE', 46: 'GH', 47: 'PT', 48: 'FI', 49: 'CZ',
  50: 'HU', 51: 'RO', 52: 'GR', 53: 'UA', 54: 'IL', 55: 'PK', 56: 'BD', 57: 'LK',
  86: 'KZ', 146: 'EU',
};

export default function SurveyPool() {
  const { user, token } = useAuth();
  const [surveys, setSurveys] = useState([]); // Unified pool - all surveys
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [recordsPerPage, setRecordsPerPage] = useState(20);
  const [currentPage, setCurrentPage] = useState(1);
  const [selectedSurvey, setSelectedSurvey] = useState(null);
  const [showDetailsModal, setShowDetailsModal] = useState(false);
  const [trafficStats, setTrafficStats] = useState({}); // survey_id -> {clicks, completes}
  const [clients, setClients] = useState([]); // List of clients for client name lookup
  const [totalSurveys, setTotalSurveys] = useState(0); // Total surveys count
  
  // Pool management state
  const [poolStats, setPoolStats] = useState(null); // Survey pool statistics
  const [syncing, setSyncing] = useState(false); // Sync in progress
  const [showActiveOnly, setShowActiveOnly] = useState(false); // Filter to show only active surveys
  const [showPoolPanel, setShowPoolPanel] = useState(true); // Toggle pool management panel (expanded by default)

  // Cint entry link state
  const [cintEntryLink, setCintEntryLink] = useState(null); // Current entry link for selected Cint survey
  const [loadingEntryLink, setLoadingEntryLink] = useState(false); // Loading state for entry link fetch
  const [creatingEntryLink, setCreatingEntryLink] = useState(false); // Creating entry link in progress

  // WebSocket hooks temporarily disabled for debugging
  // const { 
  //   surveys: cintSurveys, 
  //   isConnected: cintConnected 
  // } = useSurveyWebSocket('cint');
  
  // Temporary fallback values
  const cintSurveys = [];
  const cintConnected = false;

  // Fetch Cint entry link when a Cint survey is selected
  useEffect(() => {
    if (selectedSurvey && selectedSurvey.account_name && showDetailsModal) {
      // This is a Cint survey - fetch its entry link
      fetchCintEntryLink(selectedSurvey.survey_id);
    } else {
      // Clear entry link state when modal closes or CPX survey selected
      setCintEntryLink(null);
    }
  }, [selectedSurvey, showDetailsModal]);

  // Fetch Cint entry link from API
  const fetchCintEntryLink = async (surveyId) => {
    if (!token || !surveyId) return;
    
    setLoadingEntryLink(true);
    setCintEntryLink(null);
    
    try {
      const response = await fetch(
        buildApiUrl(`/api/cint/entry-links/${surveyId}`),
        {
          headers: {
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'application/json',
          },
        }
      );
      
      if (response.ok) {
        const data = await response.json();
        const link = data?.link || data?.data?.link || null;
        if (data.success && link) {
          setCintEntryLink(link);
        }
      } else if (response.status !== 404) {
        console.error('Failed to fetch Cint entry link:', response.status);
      }
      // 404 is expected if no entry link exists yet
    } catch (err) {
      console.error('Error fetching Cint entry link:', err);
    } finally {
      setLoadingEntryLink(false);
    }
  };

  // Create Cint entry link via API with proper redirect URLs
  const createCintEntryLink = async (surveyId) => {
    if (!token || !surveyId) return;
    
    setCreatingEntryLink(true);
    
    // Backend base URL for callbacks (production)
    const callbackBase = 'https://torpedo.cogentixresearch.com';
    const frontendBase = 'https://surveyfieldwork.com';
    
    try {
      const response = await fetch(
        buildApiUrl(`/api/cint/entry-links/${surveyId}`),
        {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            supplier_link_type_code: 'OWS',
            tracking_type_code: 'NONE',
            default_link: `${frontendBase}/survey`,
            success_link: `${callbackBase}/cint-response?status=complete&mid=[%MID%]&revenue=[%REVENUE%]`,
            failure_link: `${callbackBase}/cint-response?status=terminate&mid=[%MID%]`,
            over_quota_link: `${callbackBase}/cint-response?status=quota_full&mid=[%MID%]`,
            quality_termination_link: `${callbackBase}/cint-response?status=quality_terminate&mid=[%MID%]`,
          }),
        }
      );
      
      if (response.ok) {
        const data = await response.json();
        const link = data?.link || data?.data?.link || null;
        if (data.success && link) {
          setCintEntryLink(link);
        } else {
          // Refetch to get the created link
          await fetchCintEntryLink(surveyId);
        }
      } else {
        const errorData = await response.json().catch(() => ({}));
        console.error('Failed to create Cint entry link:', errorData);
        alert(`Failed to create entry link: ${errorData.detail || response.statusText}`);
      }
    } catch (err) {
      console.error('Error creating Cint entry link:', err);
      alert('Error creating entry link. Please try again.');
    } finally {
      setCreatingEntryLink(false);
    }
  };

  // Merge WebSocket surveys with existing state
  useEffect(() => {
    if (cintSurveys.length > 0) {
      setSurveys(prev => {
        // Create a map of existing surveys by id
        const surveyMap = new Map(prev.map(s => [s.id || s.survey_id, s]));
        
        // Update/add CINT surveys
        cintSurveys.forEach(s => {
          const id = s.id || s.survey_id;
          surveyMap.set(id, { ...s, source: 'CINT' });
        });
        
        const merged = Array.from(surveyMap.values());
        setTotalSurveys(merged.length);
        return merged;
      });
      setLastUpdated(new Date().toISOString());
    }
  }, [cintSurveys]);

  // Fetch surveys on mount
  useEffect(() => {
    if (token) {
      fetchAllSurveys();
      fetchTrafficStats();
      fetchClients();
    }
  }, [token]);

  // Auto-refresh every 2 minutes as fallback (WebSocket is primary)
  useEffect(() => {
    if (!token) return;
    const interval = setInterval(() => {
      // Only fetch if WebSocket is not connected
      if (!cintConnected) {
        fetchAllSurveys();
      }
      fetchTrafficStats(); // Always refresh traffic stats
    }, 120000); // 2 minutes fallback
    return () => clearInterval(interval);
  }, [token, cintConnected]);

  // Fetch all surveys from both CPX and CINT, combine into unified pool
  const fetchAllSurveys = async () => {
    setLoading(true);
    setError(null);
    
    try {
      // Fetch CINT surveys (mounted at /api/cint in backend)
      const cintQuery = `/api/cint/surveys?page=1&page_size=1000&show_all=true`;
      const cintResponse = await fetch(buildApiUrl(cintQuery), {
        headers: {
          'Authorization': token,
          'Content-Type': 'application/json',
        },
      });

      let allSurveys = [];

      let cintData = null;
      if (cintResponse.ok) {
        cintData = await cintResponse.json();
      } else {
        try {
          const fallbackUrl = `https://torpedo.cogentixresearch.com${cintQuery}`;
          const fallbackResponse = await fetch(fallbackUrl, {
            headers: {
              'Authorization': token,
              'Content-Type': 'application/json',
            },
          });
          if (fallbackResponse.ok) {
            cintData = await fallbackResponse.json();
          } else {
            console.warn('CINT fetch failed:', cintResponse.status, fallbackResponse.status);
          }
        } catch (fallbackError) {
          console.warn('CINT fallback fetch failed:', fallbackError);
        }
      }

      if (cintData) {
        const cintSurveys = (cintData.surveys || []).map(s => ({ ...s, source: 'CINT' }));
        allSurveys = allSurveys.concat(cintSurveys);
      }

      setSurveys(allSurveys);
      setTotalSurveys(allSurveys.length);
      setLastUpdated(new Date().toISOString());
    } catch (err) {
      console.error('Error fetching surveys:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // Fetch traffic stats for all surveys
  const fetchTrafficStats = async () => {
    try {
      const response = await fetch(buildApiUrl(`/traffic/surveys-stats`), {
        headers: {
          'Authorization': token,
          'Content-Type': 'application/json',
        },
      });

      if (response.ok) {
        const data = await response.json();
        setTrafficStats(data.surveys_stats || {});
      }
    } catch (err) {
      console.error('Error fetching traffic stats:', err);
    }
  };

  // Fetch clients for client name lookup
  const fetchClients = async () => {
    try {
      const response = await fetch(buildApiUrl(`/finance/finance/customers/`), {
        headers: {
          'Authorization': token,
          'Content-Type': 'application/json',
        },
      });

      if (response.ok) {
        const data = await response.json();
        setClients(Array.isArray(data) ? data : data.customers || []);
      }
    } catch (err) {
      console.error('Error fetching clients:', err);
    }
  };

  // Fetch pool statistics
  const fetchPoolStats = async () => {
    try {
      const response = await fetch(buildApiUrl(`/survey-pool/stats`), {
        headers: {
          'Authorization': token,
          'Content-Type': 'application/json',
        },
      });

      if (response.ok) {
        const data = await response.json();
        setPoolStats(data.data || null);
      }
    } catch (err) {
      console.error('Error fetching pool stats:', err);
    }
  };

  // Sync and activate surveys based on filters
  const syncSurveys = async ({ silent = false } = {}) => {
    setSyncing(true);
    let cintResult = null;
    
    try {
      const cintSyncResponse = await fetch(buildApiUrl(`/api/cint/sync-active-status`), {
        method: 'POST',
        headers: {
          'Authorization': token,
          'Content-Type': 'application/json',
        },
      }).catch(err => {
        console.log('CINT sync not available:', err);
        return null;
      });

      // Process CINT result
      if (cintSyncResponse && cintSyncResponse.ok) {
        cintResult = await cintSyncResponse.json();
        console.log('CINT Survey sync complete:', cintResult);
      }

      // Build combined summary message
      let summaryLines = ['✅ Sync Complete!\n'];
      
      if (cintResult && cintResult.success) {
        summaryLines.push('🎯 CINT Research:');
        summaryLines.push(`   • Total: ${cintResult.total}`);
        summaryLines.push(`   • Active: ${cintResult.active}`);
        summaryLines.push(`   • Inactive: ${cintResult.inactive}`);
        summaryLines.push('');
      }
      
      // Show filter criteria from whichever sync returned filters
      const filters = cintResult?.filters_applied;
      if (filters) {
        summaryLines.push('⚙️ Filter Criteria:');
        summaryLines.push(`   • Min CPI: $${filters.min_cpi}`);
      }

      if (!silent && cintResult?.success) {
        alert(summaryLines.join('\n'));
      } else if (!cintResult) {
        setError('Failed to sync CINT surveys');
      }
      
      // Refresh surveys after sync
      await fetchAllSurveys();
      await fetchPoolStats();
      
    } catch (err) {
      console.error('Error syncing surveys:', err);
      setError(err.message);
    } finally {
      setSyncing(false);
    }
  };

  // Toggle a survey's active status in the pool
  const toggleSurveyActive = async (survey, activate) => {
    const provider = survey.source || survey.provider || 'CPX';
    const surveyId = survey.survey_id || survey.id || survey._id;
    
    try {
      const response = await fetch(buildApiUrl(`/survey-pool/toggle/${provider}/${surveyId}`), {
        method: 'POST',
        headers: {
          'Authorization': token,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ activate }),
      });

      if (response.ok) {
        // Update local state
        setSurveys(prev => prev.map(s => {
          const id = s.survey_id || s.id || s._id;
          if (id === surveyId) {
            return { ...s, is_active_in_pool: activate };
          }
          return s;
        }));
        await fetchPoolStats();
      }
    } catch (err) {
      console.error('Error toggling survey:', err);
    }
  };

  // Fetch pool stats on mount
  useEffect(() => {
    if (token) {
      fetchPoolStats();
    }
  }, [token]);

  // Auto-sync when switching to active-only view so active flags are populated
  useEffect(() => {
    if (showActiveOnly && token && !syncing) {
      syncSurveys({ silent: true });
    }
  }, [showActiveOnly, token, syncing]);

  // Get client by provider/source name (e.g., "CPX" matches client "CPX Research")
  const getClientByProvider = (survey) => {
    const source = survey.provider || survey.source || 'CPX';
    // Look for a client whose company_name or name contains the source (e.g., "CPX Research" contains "CPX")
    const client = clients.find(c => {
      const clientName = (c.company_name || c.name || '').toLowerCase();
      return clientName.includes(source.toLowerCase()) || 
             clientName.includes('cpx research') ||
             source.toLowerCase().includes(clientName.split(' ')[0]?.toLowerCase());
    });
    return client;
  };

  // Get client by name (for projects that store client name directly)
  const getClientByName = (clientName) => {
    if (!clientName) return null;
    const lowerName = clientName.toLowerCase();
    return clients.find(c => {
      const name = (c.company_name || c.name || '').toLowerCase();
      return name === lowerName || name.includes(lowerName) || lowerName.includes(name);
    });
  };

  // Get client name - handles both CPX surveys and Projects
  const getClientName = (survey) => {
    // For CINT surveys, account_name contains the buyer name
    if (survey.account_name) {
      return survey.account_name;
    }
    
    // For projects, client_name is stored directly
    if (survey.client_name) {
      return survey.client_name;
    }
    
    // If survey has a direct client_id, use that
    if (survey.client_id) {
      const client = clients.find(c => c._id === survey.client_id);
      if (client) return client.company_name || client.name || 'N/A';
    }
    
    // Otherwise, look up by provider/source name (for CPX surveys)
    const client = getClientByProvider(survey);
    return client?.company_name || client?.name || 'N/A';
  };

  // Map customer_type to display type
  const mapCustomerType = (customerType) => {
    if (customerType === 'business') return 'Offline';
    if (customerType === 'api') return 'API';
    return 'Online';
  };

  // Get client type from the Clients module
  const getClientType = (survey) => {
    // For CINT surveys (has account_name field), return "ONLINE"
    if (survey.account_name) {
      return 'ONLINE';
    }
    
    // For CPX/API surveys, return "API" (they come from API)
    if (survey.provider === 'CPX' || survey.source === 'CPX') {
      return 'ONLINE';
    }
    
    // For projects, look up client by client_name
    if (survey.client_name) {
      const client = getClientByName(survey.client_name);
      if (client) {
        return mapCustomerType(client.customer_type);
      }
      return 'Offline'; // Default for projects
    }
    
    // If survey has a direct client_id, use that client's type
    if (survey.client_id) {
      const client = clients.find(c => c._id === survey.client_id);
      if (client) {
        return mapCustomerType(client.customer_type);
      }
    }
    
    // Otherwise, look up by provider/source name
    const client = getClientByProvider(survey);
    if (client) {
      return mapCustomerType(client.customer_type);
    }
    
    // Default fallback
    return 'Online';
  };

  // Filter surveys based on active_only toggle
  const filteredSurveys = useMemo(() => {
    if (!showActiveOnly) return surveys;

    return surveys.filter((survey) => {
      if (survey.is_active_in_pool === true) {
        return true;
      }

      const source = (survey.source || survey.provider || '').toUpperCase();
      if (source === 'CINT') {
        return survey.is_live === true && survey.message_reason !== 'deactivated';
      }

      return false;
    });
  }, [surveys, showActiveOnly]);

  // Client-side pagination
  const paginatedSurveys = useMemo(() => {
    const startIndex = (currentPage - 1) * recordsPerPage;
    const endIndex = startIndex + recordsPerPage;
    return filteredSurveys.slice(startIndex, endIndex);
  }, [filteredSurveys, currentPage, recordsPerPage]);

  const totalPages = Math.ceil(filteredSurveys.length / recordsPerPage);

  // Handle survey click to show details
  const handleSurveyClick = (survey) => {
    setSelectedSurvey(survey);
    setShowDetailsModal(true);
  };

  // Close details modal
  const closeDetailsModal = () => {
    setShowDetailsModal(false);
    setSelectedSurvey(null);
  };

  // Format date/time for display
  const formatDateTime = (dateString) => {
    if (!dateString) return 'N/A';
    const date = new Date(dateString);
    return date.toLocaleString('en-IN', {
      timeZone: 'Asia/Kolkata',
      day: '2-digit',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: true
    });
  };

  // Get survey name - for CINT show study number (survey_id), for CPX show survey_name
  const getSurveyName = (survey) => {
    // For CINT surveys (those with account_name), show survey_id as study number
    if (survey.account_name || (survey.survey_id && !survey.name)) {
      return survey.survey_id || survey._id || 'N/A';
    }
    // For CPX surveys, show survey name
    return survey.survey_name || survey.name || survey.survey_id || survey._id || 'N/A';
  };

  // Extract country code from country_language - last 2 alphabets in caps (e.g., eng_us -> US)
  const getCountryCode = (survey) => {
    const countryLanguage = survey.country_language;
    
    // Priority: Extract last 2 characters from country_language string (e.g., "eng_us" -> "US")
    if (countryLanguage && typeof countryLanguage === 'string') {
      // Get last 2 characters and uppercase them
      const lastTwo = countryLanguage.slice(-2).toUpperCase();
      if (lastTwo && /^[A-Z]{2}$/.test(lastTwo)) {
        return lastTwo;
      }
      // Fallback: try splitting by underscore
      const parts = countryLanguage.split('_');
      if (parts.length >= 2) {
        return parts[parts.length - 1].toUpperCase();
      }
      return countryLanguage.toUpperCase();
    }
    
    // For CINT surveys with numeric country_language ID - use mapping
    if (countryLanguage && typeof countryLanguage === 'number') {
      return CINT_COUNTRY_LANGUAGE_MAP[countryLanguage] || `ID:${countryLanguage}`;
    }
    
    // Fallback to direct country or country_code fields
    if (survey.country && typeof survey.country === 'string' && survey.country.length <= 3) {
      return survey.country.toUpperCase();
    }
    if (survey.country_code && typeof survey.country_code === 'string' && survey.country_code.length <= 3) {
      return survey.country_code.toUpperCase();
    }
    
    return 'N/A';
  };

  // Get LOI (Length of Interview) in minutes - check all possible field names
  const getLOI = (survey) => {
    // Check all possible LOI field names
    const loi = survey.loi || 
                survey.length_of_interview || 
                survey.bid_length_of_interview ||
                survey.LOI ||
                survey.survey_loi;
    
    // Ensure it's a valid number
    if (loi !== undefined && loi !== null && !isNaN(loi) && loi > 0) {
      return Math.round(loi);
    }
    return 'N/A';
  };

  // Get Payout/CPI in USD
  const getPayout = (survey) => {
    // For CINT surveys, revenue_per_interview is an object {value, currency_code}
    if (survey.revenue_per_interview) {
      const rpi = survey.revenue_per_interview;
      if (typeof rpi === 'object' && rpi.value) {
        return `$${parseFloat(rpi.value).toFixed(2)}`;
      }
      if (typeof rpi === 'number') {
        return `$${rpi.toFixed(2)}`;
      }
    }
    // Fallback to payout or cpi fields
    if (survey.payout !== undefined && survey.payout !== null) {
      return `$${parseFloat(survey.payout).toFixed(2)}`;
    }
    if (survey.cpi !== undefined && survey.cpi !== null) {
      return `$${parseFloat(survey.cpi).toFixed(2)}`;
    }
    return '$0.00';
  };

  // Calculate conversion rate - use bid_incidence or incidence_rate for CINT surveys
  const getConversionRate = (survey) => {
    // For CINT surveys, try 'bid_incidence' first, then 'incidence_rate' (percentage value)
    const incidence = survey.bid_incidence ?? survey.incidence_rate;
    if (incidence !== undefined && incidence !== null && incidence > 0) {
      const rate = parseFloat(incidence);
      // Values typically already a percentage (e.g., 60 = 60%)
      if (rate <= 1) {
        return `${(rate * 100).toFixed(1)}%`;
      }
      return `${rate.toFixed(1)}%`;
    }
    
    // Fallback to conversion or conversion_rate
    if (survey.conversion !== undefined && survey.conversion !== null) {
      const rate = parseFloat(survey.conversion);
      if (rate > 1) {
        return `${rate.toFixed(1)}%`;
      }
      return `${(rate * 100).toFixed(1)}%`;
    }
    
    const rate = survey.conversion_rate;
    if (rate === null || rate === undefined) return 'N/A';
    if (rate > 1) {
      return `${rate.toFixed(1)}%`;
    }
    return `${(rate * 100).toFixed(1)}%`;
  };

  // Get date/time for survey (handles CINT and CPX formats)
  const getSurveyDateTime = (survey) => {
    // For CINT surveys, use received_at or last_updated_at
    return survey.received_at || survey.last_updated_at || survey.last_updated || survey.inserted_at;
  };

  // Get survey status - determines if survey is active/live based on filter criteria
  const getSurveyStatus = (survey) => {
    // First check is_active_in_pool which is set by sync-active-status based on filter criteria
    if (survey.is_active_in_pool === true) {
      return 'ACTIVE';
    }
    if (survey.is_active_in_pool === false) {
      return 'INACTIVE';
    }
    
    const source = survey.source || survey.provider || '';
    
    // For CINT surveys, check is_active and is_live fields
    if (source.toUpperCase() === 'CINT') {
      if (survey.is_active === true || survey.is_live === true) {
        return 'ACTIVE';
      }
      if (survey.message_reason === 'deactivated') {
        return 'INACTIVE';
      }
      // Default to active if we have the survey in the pool
      return survey.is_active !== false ? 'ACTIVE' : 'INACTIVE';
    }
    
    // For CPX surveys, check if they have a valid live_link (means they're active)
    if (source.toUpperCase() === 'CPX') {
      // If survey has a live_link, it's active
      if (survey.live_link && survey.live_link.length > 0) {
        return 'ACTIVE';
      }
      // If survey is in the pool and passed filters, consider it active
      return 'ACTIVE';
    }
    
    // Fallback: check status/is_active fields
    if (survey.status === 'active' || survey.is_active === true) {
      return 'ACTIVE';
    }
    
    return 'INACTIVE';
  };

  if (!user) {
    return <div className="survey-pool-container">Please login to access Survey Pool.</div>;
  }

  return (
    <div className="survey-pool-container">
      {/* Pool Management Panel */}
      <div className="pool-management-panel">
        <div className="pool-stats-header">
          <h3>📊 Survey Pool Management</h3>
          <button 
            className="toggle-panel-btn"
            onClick={() => setShowPoolPanel(!showPoolPanel)}
          >
            {showPoolPanel ? '▲ Hide' : '▼ Show'}
          </button>
        </div>
        
        {showPoolPanel && (
          <div className="pool-stats-content">
            {/* Pool Statistics */}
            {poolStats && (
              <div className="pool-stats-grid">
                <div className="stat-card cint">
                  <h4>CINT Research</h4>
                  <div className="stat-numbers">
                    <span className="active">{poolStats.cint?.active || 0} Active</span>
                    <span className="total">/ {poolStats.cint?.total || 0} Total</span>
                  </div>
                </div>
                <div className="stat-card total">
                  <h4>Total Pool</h4>
                  <div className="stat-numbers">
                    <span className="active">{poolStats.cint?.active || 0} Active</span>
                    <span className="total">/ {poolStats.cint?.total || 0} Total</span>
                  </div>
                </div>
              </div>
            )}
            
            {/* Sync Controls */}
            <div className="pool-controls">
              <div className="sync-actions">
                <button 
                  className={`sync-btn ${syncing ? 'syncing' : ''}`}
                  onClick={syncSurveys}
                  disabled={syncing}
                >
                  {syncing ? '🔄 Syncing...' : '🔄 Sync & Activate Surveys'}
                </button>
                <a 
                  href="/admin/settings" 
                  className="settings-link"
                  title="Configure survey filter criteria"
                >
                  ⚙️ Filter Settings
                </a>
              </div>
              <p className="sync-info">
                Syncs all surveys from CINT and activates those matching filter criteria from <a href="/admin/settings" style={{ color: '#667eea' }}>Settings</a>.
                {poolStats?.last_sync && (
                  <span className="last-sync">
                    Last sync: {new Date(poolStats.last_sync).toLocaleString()}
                  </span>
                )}
              </p>
            </div>
            
            {/* Filter Toggle */}
            <div className="filter-toggle">
              <label>
                <input 
                  type="checkbox"
                  checked={showActiveOnly}
                  onChange={(e) => setShowActiveOnly(e.target.checked)}
                />
                Show only active surveys (for traffic routing)
              </label>
            </div>
          </div>
        )}
      </div>

      {/* Loading State */}
      {loading && paginatedSurveys.length === 0 && !error && (
        <div className="survey-pool-loading">
          <div className="loading-spinner"></div>
          <p>⏳ Loading surveys...</p>
        </div>
      )}

      {/* Error State */}
      {error && (
        <div className="survey-pool-error">
          <p>❌ Failed to fetch surveys</p>
          <p className="error-detail">{error}</p>
          <button onClick={() => window.location.reload()} className="retry-btn">
            🔄 Retry
          </button>
        </div>
      )}

      {/* Survey Table */}
      {paginatedSurveys.length > 0 && (
        <>
          <div className="survey-table-container">
            <table className="survey-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Source</th>
                  <th>Client Name</th>
                  <th>Client Type</th>
                  <th>Country</th>
                  <th>LOI (min)</th>
                  <th>Payout</th>
                  <th>Conversion</th>
                  <th>Clicks</th>
                  <th>Completes</th>
                  <th>Date/Time</th>
                  <th>Pool Status</th>
                </tr>
              </thead>
              <tbody>
                {paginatedSurveys.map((survey, index) => {
                  const surveyId = survey.survey_id || survey._id;
                  const stats = trafficStats[surveyId] || { clicks: 0, completes: 0 };
                  const surveySource = survey.source || (survey.account_name ? 'CINT' : 'CPX');
                  return (
                  <tr key={survey._id || survey.survey_id || index}>
                    <td>
                      <span 
                        className="survey-link" 
                        onClick={() => handleSurveyClick(survey)}
                        style={{ cursor: 'pointer', color: '#667eea', textDecoration: 'underline' }}
                      >
                        {getSurveyName(survey)}
                      </span>
                    </td>
                    <td>
                      <span style={{ 
                        padding: '2px 8px', 
                        borderRadius: '4px', 
                        fontSize: '0.8rem',
                        background: surveySource === 'CPX' ? '#e0e7ff' : '#d1fae5',
                        color: surveySource === 'CPX' ? '#667eea' : '#10b981',
                        fontWeight: 'bold'
                      }}>
                        {surveySource}
                      </span>
                    </td>
                    <td>{getClientName(survey)}</td>
                    <td>
                      <span className="source-badge">
                        {getClientType(survey)}
                      </span>
                    </td>
                    <td>{getCountryCode(survey)}</td>
                    <td>{getLOI(survey)}</td>
                    <td>{getPayout(survey)}</td>
                    <td>{getConversionRate(survey)}</td>
                    <td>{stats.clicks}</td>
                    <td>{stats.completes}</td>
                    <td>{formatDateTime(getSurveyDateTime(survey))}</td>
                    <td>
                      <button
                        className={`pool-toggle-btn ${survey.is_active_in_pool ? 'active' : 'inactive'}`}
                        onClick={() => toggleSurveyActive(survey, !survey.is_active_in_pool)}
                        title={survey.is_active_in_pool ? 'Click to deactivate from traffic routing' : 'Click to activate for traffic routing'}
                      >
                        {survey.is_active_in_pool ? '✅ Active' : '⏸️ Inactive'}
                      </button>
                    </td>
                  </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Pagination Controls */}
          {filteredSurveys.length > recordsPerPage && (
            <div className="survey-pool-pagination">
              <div className="pagination-info">
                Showing {(currentPage - 1) * recordsPerPage + 1} to{' '}
                {Math.min(currentPage * recordsPerPage, filteredSurveys.length)} of {filteredSurveys.length} surveys
                {showActiveOnly && <span className="filter-note"> (Active Only)</span>}
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

      {paginatedSurveys.length === 0 && !error && !loading && (
        <div className="survey-pool-empty">
          <div className="empty-icon">📭</div>
          <p className="empty-title">No surveys available</p>
          <p className="empty-subtitle">Refresh to check for new surveys from CPX & CINT Research.</p>
        </div>
      )}

      {/* Survey Details Modal */}
      {showDetailsModal && selectedSurvey && (
        <div className="survey-details-modal-overlay" onClick={closeDetailsModal}>
          <div className="survey-details-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>📋 Survey Details</h2>
              <button className="modal-close-btn" onClick={closeDetailsModal}>✕</button>
            </div>
            <div className="modal-body">
              <div className="detail-grid">
                <div className="detail-item">
                  <span className="detail-label">Survey ID</span>
                  <span className="detail-value">{selectedSurvey.survey_id || selectedSurvey._id}</span>
                </div>
                <div className="detail-item">
                  <span className="detail-label">Name</span>
                  <span className="detail-value">{selectedSurvey.survey_name || getSurveyName(selectedSurvey)}</span>
                </div>
                <div className="detail-item">
                  <span className="detail-label">Source</span>
                  <span className="detail-value" style={{ 
                    color: selectedSurvey.account_name ? '#10b981' : '#667eea',
                    fontWeight: 'bold'
                  }}>
                    {selectedSurvey.account_name ? '🎯 CINT Research' : '📊 CPX Research'}
                  </span>
                </div>
                <div className="detail-item">
                  <span className="detail-label">Country</span>
                  <span className="detail-value">{getCountryCode(selectedSurvey)}</span>
                </div>
                <div className="detail-item">
                  <span className="detail-label">Length of Interview</span>
                  <span className="detail-value">{getLOI(selectedSurvey)} minutes</span>
                </div>
                <div className="detail-item">
                  <span className="detail-label">Payout</span>
                  <span className="detail-value" style={{ color: '#10b981', fontWeight: 'bold' }}>{getPayout(selectedSurvey)}</span>
                </div>
                <div className="detail-item">
                  <span className="detail-label">Conversion Rate</span>
                  <span className="detail-value">{getConversionRate(selectedSurvey)}</span>
                </div>
                <div className="detail-item">
                  <span className="detail-label">Category/Industry</span>
                  <span className="detail-value">{selectedSurvey.industry || selectedSurvey.category || 'N/A'}</span>
                </div>
                <div className="detail-item">
                  <span className="detail-label">Status</span>
                  <span className={`status-badge ${getSurveyStatus(selectedSurvey) === 'ACTIVE' ? 'active' : 'inactive'}`}>
                    {getSurveyStatus(selectedSurvey) === 'ACTIVE' ? '✅ Active' : '❌ Inactive'}
                  </span>
                </div>
                <div className="detail-item">
                  <span className="detail-label">Date/Time Added</span>
                  <span className="detail-value">{formatDateTime(getSurveyDateTime(selectedSurvey))}</span>
                </div>
                
                {/* CINT-specific fields */}
                {selectedSurvey.account_name && (
                  <>
                    <div className="detail-item">
                      <span className="detail-label">Buyer/Account</span>
                      <span className="detail-value">{selectedSurvey.account_name}</span>
                    </div>
                    {selectedSurvey.buyer_id && (
                      <div className="detail-item">
                        <span className="detail-label">Buyer ID</span>
                        <span className="detail-value">{selectedSurvey.buyer_id}</span>
                      </div>
                    )}
                    {selectedSurvey.bid_incidence !== undefined && (
                      <div className="detail-item">
                        <span className="detail-label">Incidence Rate</span>
                        <span className="detail-value">{selectedSurvey.bid_incidence}%</span>
                      </div>
                    )}
                    {selectedSurvey.total_remaining !== undefined && (
                      <div className="detail-item">
                        <span className="detail-label">Quota Remaining</span>
                        <span className="detail-value">{selectedSurvey.total_remaining}</span>
                      </div>
                    )}
                    {selectedSurvey.study_type && (
                      <div className="detail-item">
                        <span className="detail-label">Study Type</span>
                        <span className="detail-value">{selectedSurvey.study_type}</span>
                      </div>
                    )}
                    {selectedSurvey.collects_pii !== undefined && (
                      <div className="detail-item">
                        <span className="detail-label">Collects PII</span>
                        <span className="detail-value">{selectedSurvey.collects_pii ? 'Yes' : 'No'}</span>
                      </div>
                    )}
                    {selectedSurvey.revenue_per_click !== undefined && (
                      <div className="detail-item">
                        <span className="detail-label">Revenue Per Click</span>
                        <span className="detail-value">${parseFloat(selectedSurvey.revenue_per_click).toFixed(2)}</span>
                      </div>
                    )}
                    {selectedSurvey.mobile_conversion !== undefined && (
                      <div className="detail-item">
                        <span className="detail-label">Mobile Conversion</span>
                        <span className="detail-value">{(selectedSurvey.mobile_conversion * 100).toFixed(1)}%</span>
                      </div>
                    )}
                  </>
                )}
              </div>
              
              {selectedSurvey.title && selectedSurvey.title !== getSurveyName(selectedSurvey) && (
                <div className="detail-item full-width">
                  <span className="detail-label">Title</span>
                  <span className="detail-value">{selectedSurvey.title}</span>
                </div>
              )}
              
              {/* CPX Live Link - Direct link from CPX API */}
              {selectedSurvey.live_link && !selectedSurvey.account_name && (
                <div className="detail-item full-width" style={{ marginTop: '16px' }}>
                  <span className="detail-label">🔗 Live Link (CPX)</span>
                  <div className="entry-link-container">
                    <input 
                      type="text" 
                      readOnly 
                      value={selectedSurvey.live_link} 
                      className="entry-link-input"
                      onClick={(e) => e.target.select()}
                    />
                    <button 
                      className="copy-link-btn"
                      onClick={() => navigator.clipboard.writeText(selectedSurvey.live_link)}
                      title="Copy to clipboard"
                    >
                      📋 Copy
                    </button>
                    <a 
                      href={selectedSurvey.live_link} 
                      target="_blank" 
                      rel="noopener noreferrer"
                      className="open-link-btn"
                      title="Open in new tab"
                    >
                      🔗 Open
                    </a>
                  </div>
                </div>
              )}
              
              {/* CPX Entry Link Template */}
              {selectedSurvey.entry_link && !selectedSurvey.account_name && (
                <div className="detail-item full-width">
                  <span className="detail-label">🎯 Entry Link Template (CPX)</span>
                  <div className="entry-link-container">
                    <input 
                      type="text" 
                      readOnly 
                      value={selectedSurvey.entry_link} 
                      className="entry-link-input"
                      onClick={(e) => e.target.select()}
                    />
                    <button 
                      className="copy-link-btn"
                      onClick={() => navigator.clipboard.writeText(selectedSurvey.entry_link)}
                      title="Copy to clipboard"
                    >
                      📋 Copy
                    </button>
                  </div>
                  <div style={{ color: '#888', marginTop: '8px', fontSize: '0.85rem', lineHeight: '1.5' }}>
                    <strong>Replace placeholders:</strong>
                    <ul style={{ margin: '4px 0 0 16px', padding: 0, listStyle: 'none' }}>
                      <li>• <code>{'{ext_user_id}'}</code> - Unique user ID (mandatory)</li>
                      <li>• <code>{'{secure_hash}'}</code> - MD5 hash of (ext_user_id + secure_key)</li>
                    </ul>
                    <div style={{ marginTop: '8px', padding: '8px', background: '#f0f0f5', borderRadius: '4px', fontSize: '0.8rem' }}>
                      <strong>Parameter Details:</strong>
                      <table style={{ width: '100%', marginTop: '4px', fontSize: '0.75rem' }}>
                        <tbody>
                          <tr><td><code>&ext_user_id=</code></td><td><strong>Mandatory</strong> - Unique per user</td></tr>
                          <tr><td><code>&app_id=10754</code></td><td><strong>Mandatory</strong> - Already included</td></tr>
                          <tr><td><code>&secure_hash=</code></td><td><strong>Recommended</strong> - md5(ext_user_id-app_secure_hash)</td></tr>
                          <tr><td><code>&username=</code></td><td>Recommended - User's username</td></tr>
                          <tr><td><code>&email=</code></td><td>Recommended - For duplicate matching</td></tr>
                          <tr><td><code>&subid_1=</code> / <code>&subid_2=</code></td><td>Optional - Custom tracking info</td></tr>
                        </tbody>
                      </table>
                    </div>
                  </div>
                </div>
              )}
              
              {/* CINT Entry Link Section */}
              {selectedSurvey.account_name && (
                <div className="detail-item full-width" style={{ marginTop: '16px', padding: '16px', background: '#f8fafc', borderRadius: '8px' }}>
                  <span className="detail-label" style={{ color: '#10b981', fontSize: '1rem' }}>🎯 CINT Entry Link</span>
                  <div style={{ marginTop: '12px' }}>
                    {loadingEntryLink ? (
                      <div style={{ padding: '12px', color: '#666', display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span className="loading-spinner" style={{ width: '16px', height: '16px', border: '2px solid #e5e7eb', borderTopColor: '#10b981', borderRadius: '50%', animation: 'spin 1s linear infinite' }}></span>
                        Loading entry link...
                      </div>
                    ) : cintEntryLink?.live_link ? (
                      <>
                        {/* Live Link Section */}
                        <div className="entry-link-section">
                          <span className="entry-link-label">🚀 Live Link (Production)</span>
                          <div className="entry-link-container">
                            <input 
                              type="text" 
                              readOnly 
                              value={cintEntryLink.live_link}
                              className="entry-link-input"
                              onClick={(e) => e.target.select()}
                            />
                            <button 
                              className="copy-link-btn"
                              onClick={() => {
                                navigator.clipboard.writeText(cintEntryLink.live_link);
                                // Optional: show brief feedback
                              }}
                              title="Copy to clipboard"
                            >
                              📋 Copy
                            </button>
                            <a 
                              href={cintEntryLink.live_link} 
                              target="_blank" 
                              rel="noopener noreferrer"
                              className="open-link-btn"
                              title="Test live link in new tab"
                            >
                              🚀 Test
                            </a>
                          </div>
                        </div>

                        {/* Test Link Section (if available) */}
                        {cintEntryLink.test_link && (
                          <div className="entry-link-section" style={{ marginTop: '12px' }}>
                            <span className="entry-link-label test-mode">🧪 Test Link (Sandbox)</span>
                            <div className="entry-link-container">
                              <input 
                                type="text" 
                                readOnly 
                                value={cintEntryLink.test_link}
                                className="entry-link-input"
                                onClick={(e) => e.target.select()}
                              />
                              <button 
                                className="copy-link-btn"
                                onClick={() => {
                                  navigator.clipboard.writeText(cintEntryLink.test_link);
                                }}
                                title="Copy to clipboard"
                              >
                                📋 Copy
                              </button>
                              <a 
                                href={cintEntryLink.test_link} 
                                target="_blank" 
                                rel="noopener noreferrer"
                                className="open-link-btn test-mode"
                                title="Test sandbox link"
                              >
                                🧪 Test
                              </a>
                            </div>
                          </div>
                        )}
                      </>
                    ) : (
                      <div style={{ padding: '12px', background: '#fef3c7', borderRadius: '6px', border: '1px solid #fcd34d' }}>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
                            <span style={{ color: '#92400e' }}>⚠️ Entry link not yet available.</span>
                            <button
                              onClick={() => createCintEntryLink(selectedSurvey.survey_id)}
                              disabled={creatingEntryLink}
                              style={{
                                padding: '6px 14px',
                                background: creatingEntryLink ? '#9ca3af' : '#10b981',
                                color: 'white',
                                border: 'none',
                                borderRadius: '4px',
                                cursor: creatingEntryLink ? 'not-allowed' : 'pointer',
                                fontSize: '0.85rem',
                                fontWeight: '500'
                              }}
                            >
                              {creatingEntryLink ? '⏳ Creating...' : '➕ Create Entry Link'}
                            </button>
                          </div>
                          <p style={{ color: '#78716c', fontSize: '0.8rem', margin: 0, lineHeight: '1.4' }}>
                            Cint surveys require allocation before entry links can be created. If creation fails with 404, 
                            the survey may still be in "opportunity" status. Entry links are auto-created when surveys become available.
                          </p>
                        </div>
                      </div>
                    )}
                    <div style={{ color: '#666', marginTop: '12px', fontSize: '0.85rem', lineHeight: '1.6' }}>
                      <strong>CINT/Lucid Parameters:</strong>
                      <ul style={{ margin: '8px 0 0 16px', padding: 0, listStyle: 'none' }}>
                        <li>• <code>SID</code> - Survey ID: <strong>{selectedSurvey.survey_id}</strong></li>
                        <li>• <code>PID</code> - Panelist ID (passed in URL)</li>
                        <li>• <code>[%MID%]</code> - Session ID (auto-replaced by CINT in redirects)</li>
                        <li>• <code>[%REVENUE%]</code> - Payout amount (auto-replaced in success redirects)</li>
                      </ul>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
