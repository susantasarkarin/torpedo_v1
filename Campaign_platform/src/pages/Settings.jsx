"use client"

import { useState, useEffect } from "react"
import { API_BASE_URL } from "../config"
import EmailSyncProgress from "../components/EmailSyncProgress"
import "./Settings.css"

// Helper to get auth token - handles both storage methods
const getAuthToken = () => localStorage.getItem("session_id") || getAuthToken()

// Helper to extract error message from various error response formats
const getErrorMessage = (error, fallback = "An error occurred") => {
  if (!error) return fallback
  
  // If it's a string, return it directly
  if (typeof error === "string") return error
  
  // FastAPI validation error format: { detail: [{ type, loc, msg, input }, ...] }
  if (error.detail) {
    if (typeof error.detail === "string") return error.detail
    if (Array.isArray(error.detail)) {
      // Extract messages from validation errors
      return error.detail.map(e => e.msg || e.message || JSON.stringify(e)).join(", ")
    }
    if (typeof error.detail === "object") {
      return error.detail.msg || error.detail.message || JSON.stringify(error.detail)
    }
  }
  
  // Standard error format
  if (error.message) return error.message
  if (error.msg) return error.msg
  
  return fallback
}

function Settings() {
  // App Settings state
  const [appSettings, setAppSettings] = useState({
    mongo_uri: "",
    cpx_app_id: "",
    cpx_ext_user_id: "",
    cpx_secure_hash_key: "",
    cpx_api_timeout: 30,
    openai_api_key: "",
    anthropic_api_key: "",
    google_api_key: "",
    google_cse_id: "",
    google_sheets_service_account: "",
  })
  const [maskedSettings, setMaskedSettings] = useState({})
  
  // Survey Filter state
  const [surveyFilters, setSurveyFilters] = useState({
    max_loi: 20,
    min_cpi: 1.0,
    deletion_period_days: 7,
    auto_refresh_enabled: true,
    refresh_interval_seconds: 60,
  })

  // Gmail Settings state
  const [gmailAccounts, setGmailAccounts] = useState([])
  const [rateLimits, setRateLimits] = useState({
    max_per_day: 500,
    max_per_hour: 50,
    max_per_minute: 5,
    cooldown_seconds: 10,
    enabled: true,
  })

  // Survey Allocation Settings state
  const [allocationSettings, setAllocationSettings] = useState({
    batch_size: 100,
    buffer_multiplier: 1.2,
    max_incomplete_rate: 40.0,
    min_incidence_rate: 10.0,
    minimum_entrants_for_evaluation: 50,
    auto_pause_enabled: true,
    pause_cooldown_minutes: 30,
    prefer_high_ir_surveys: true,
    prefer_high_cpi_surveys: false,
  })
  const [newAccount, setNewAccount] = useState({ 
    email: "", 
    password: "",  // App password for IMAP
    display_name: "", 
    imap_server: "",  // Auto-detected if empty
    imap_port: 993,
    smtp_server: "",
    smtp_port: 587,
    use_ssl: true,
    is_default: false,
    skip_validation: false  // Skip IMAP connection test
  })
  const [newAlias, setNewAlias] = useState({ email: "", name: "", account_id: "" })
  const [showAddAccount, setShowAddAccount] = useState(false)
  const [showAddAlias, setShowAddAlias] = useState(null) // account_id when open
  const [gmailLoading, setGmailLoading] = useState(false)
  
  // Historical import state
  const [importProgress, setImportProgress] = useState({}) // { email: { status, progress, ... } }
  const [idleStatus, setIdleStatus] = useState({ available: false, accounts: {} })
  const [importDays, setImportDays] = useState({}) // { email: days }
  
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState({ type: "", text: "" })
  const [activeTab, setActiveTab] = useState("app") // "app", "filters", "gmail", or "allocation"
  const [testingMongo, setTestingMongo] = useState(false)
  const [testingCpx, setTestingCpx] = useState(false)

  useEffect(() => {
    loadAllSettings()
  }, [])

  useEffect(() => {
    if (activeTab === "gmail") {
      loadGmailSettings()
    }
    if (activeTab === "allocation") {
      loadAllocationSettings()
    }
  }, [activeTab])

  const loadGmailSettings = async () => {
    setGmailLoading(true)
    try {
      const token = getAuthToken()
      
      // Load Email/IMAP accounts from leads endpoint
      const accountsRes = await fetch(`${API_BASE_URL}/leads/gmail/accounts`, {
        headers: { Authorization: token }
      })
      if (accountsRes.ok) {
        const data = await accountsRes.json()
        // Map IMAP accounts to expected format
        const accounts = (data.accounts || []).map(acc => ({
          id: acc._id || acc.email,
          email: acc.email,
          name: acc.display_name,
          is_default: acc.is_default,
          is_authenticated: acc.is_active,  // IMAP accounts are "authenticated" if active
          imap_server: acc.imap_server,
          last_sync: acc.last_sync,
          historical_import_days: acc.historical_import_days || 30,
          aliases: acc.aliases || []  // Include aliases
        }))
        setGmailAccounts(accounts)
        
        // Initialize import days from accounts
        const daysMap = {}
        accounts.forEach(acc => {
          daysMap[acc.email] = acc.historical_import_days || 30
        })
        setImportDays(daysMap)
      }
      
      // Load IDLE status
      await loadIdleStatus()
    } catch (error) {
      console.error("Error loading email settings:", error)
    } finally {
      setGmailLoading(false)
    }
  }

  // Load IDLE watcher status
  const loadIdleStatus = async () => {
    try {
      const token = getAuthToken()
      const response = await fetch(`${API_BASE_URL}/gmail/idle/status`, {
        headers: { Authorization: token }
      })
      if (response.ok) {
        const data = await response.json()
        setIdleStatus(data)
      }
    } catch (error) {
      console.error("Error loading IDLE status:", error)
    }
  }

  // Start/stop IDLE watchers for all accounts
  const toggleIdleWatchers = async (start) => {
    try {
      const token = getAuthToken()
      const endpoint = start ? "/gmail/idle/start" : "/gmail/idle/stop"
      const response = await fetch(`${API_BASE_URL}${endpoint}`, {
        method: "POST",
        headers: { Authorization: token }
      })
      if (response.ok) {
        setMessage({ 
          type: "success", 
          text: start ? "Real-time email monitoring started" : "Real-time email monitoring stopped" 
        })
        await loadIdleStatus()
      } else {
        const error = await response.json()
        setMessage({ type: "error", text: getErrorMessage(error, "Failed to toggle IDLE watchers") })
      }
    } catch (error) {
      console.error("Error toggling IDLE:", error)
      setMessage({ type: "error", text: "Failed to toggle real-time monitoring" })
    }
  }

  // Start historical import for an account
  const startHistoricalImport = async (email) => {
    try {
      const token = getAuthToken()
      const days = importDays[email] || 30
      
      const response = await fetch(`${API_BASE_URL}/gmail/import/historical/${encodeURIComponent(email)}`, {
        method: "POST",
        headers: { 
          Authorization: token,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ days })
      })
      
      if (response.ok) {
        setMessage({ type: "success", text: `Import started for ${email}` })
        // Start polling for progress
        pollImportProgress(email)
      } else {
        const error = await response.json()
        setMessage({ type: "error", text: getErrorMessage(error, "Failed to start import") })
      }
    } catch (error) {
      console.error("Error starting import:", error)
      setMessage({ type: "error", text: "Failed to start import" })
    }
  }

  // Poll import progress for an account
  const pollImportProgress = async (email) => {
    const checkProgress = async () => {
      try {
        const token = getAuthToken()
        const response = await fetch(`${API_BASE_URL}/gmail/import/progress/${encodeURIComponent(email)}`, {
          headers: { Authorization: token }
        })
        
        if (response.ok) {
          const data = await response.json()
          setImportProgress(prev => ({ ...prev, [email]: data }))
          
          // Continue polling if still in progress (check all running statuses)
          if (data.status === "in_progress" || data.status === "started" || data.status === "running") {
            setTimeout(checkProgress, 1500) // Poll slightly faster for better UX
          }
        }
      } catch (error) {
        console.error("Error polling progress:", error)
      }
    }
    
    checkProgress()
  }

  // Update import days setting for an account
  const updateImportDaysSetting = async (email, days) => {
    setImportDays(prev => ({ ...prev, [email]: days }))
    
    try {
      const token = getAuthToken()
      await fetch(`${API_BASE_URL}/gmail/imap-accounts/${encodeURIComponent(email)}/settings`, {
        method: "PUT",
        headers: { 
          Authorization: token,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ historical_import_days: days })
      })
    } catch (error) {
      console.error("Error updating import days:", error)
    }
  }

  const loadAllocationSettings = async () => {
    try {
      const token = getAuthToken()
      const response = await fetch(`${API_BASE_URL}/survey-allocation/settings`, {
        headers: { Authorization: token }
      })
      if (response.ok) {
        const data = await response.json()
        setAllocationSettings(prev => ({ ...prev, ...data.settings }))
      }
    } catch (error) {
      console.error("Error loading allocation settings:", error)
    }
  }

  const saveAllocationSettings = async () => {
    setSaving(true)
    setMessage({ type: "", text: "" })
    
    try {
      const token = getAuthToken()
      const response = await fetch(`${API_BASE_URL}/survey-allocation/settings`, {
        method: "POST",
        headers: {
          Authorization: token,
          "Content-Type": "application/json"
        },
        body: JSON.stringify(allocationSettings)
      })
      
      if (response.ok) {
        setMessage({ type: "success", text: "Allocation settings saved successfully!" })
      } else {
        const error = await response.json()
        setMessage({ type: "error", text: getErrorMessage(error, "Failed to save allocation settings") })
      }
    } catch (error) {
      console.error("Error saving allocation settings:", error)
      setMessage({ type: "error", text: "Failed to save allocation settings" })
    } finally {
      setSaving(false)
    }
  }

  const handleAllocationSettingChange = (key, value) => {
    setAllocationSettings(prev => ({ ...prev, [key]: value }))
  }

  const loadAllSettings = async () => {
    setLoading(true)
    try {
      const token = getAuthToken()
      
      // Load app settings and survey filters in parallel
      const [appRes, filterRes] = await Promise.all([
        fetch(`${API_BASE_URL}/settings/app`, {
          headers: { Authorization: token }
        }),
        fetch(`${API_BASE_URL}/settings/survey-filters`, {
          headers: { Authorization: token }
        })
      ])
      
      if (appRes.ok) {
        const data = await appRes.json()
        setAppSettings(prev => ({ ...prev, ...data.settings }))
        setMaskedSettings(data.settings)
      }
      
      if (filterRes.ok) {
        const data = await filterRes.json()
        setSurveyFilters(prev => ({ ...prev, ...data.filters }))
      }
    } catch (error) {
      console.error("Error loading settings:", error)
      setMessage({ type: "error", text: "Failed to load settings" })
    } finally {
      setLoading(false)
    }
  }

  const saveAppSettings = async () => {
    setSaving(true)
    setMessage({ type: "", text: "" })
    
    try {
      const token = getAuthToken()
      
      // Only send non-empty values
      const settingsToSave = {}
      Object.entries(appSettings).forEach(([key, value]) => {
        if (value !== "" && value !== null && !key.endsWith("_masked")) {
          settingsToSave[key] = value
        }
      })
      
      const response = await fetch(`${API_BASE_URL}/settings/app`, {
        method: "POST",
        headers: {
          Authorization: token,
          "Content-Type": "application/json"
        },
        body: JSON.stringify(settingsToSave)
      })
      
      if (response.ok) {
        setMessage({ type: "success", text: "Application settings saved successfully!" })
        loadAllSettings() // Reload to get updated masked values
      } else {
        const error = await response.json()
        setMessage({ type: "error", text: getErrorMessage(error, "Failed to save settings") })
      }
    } catch (error) {
      console.error("Error saving settings:", error)
      setMessage({ type: "error", text: "Failed to save settings" })
    } finally {
      setSaving(false)
    }
  }

  const saveSurveyFilters = async () => {
    setSaving(true)
    setMessage({ type: "", text: "" })
    
    try {
      const token = getAuthToken()
      
      const response = await fetch(`${API_BASE_URL}/settings/survey-filters`, {
        method: "POST",
        headers: {
          Authorization: token,
          "Content-Type": "application/json"
        },
        body: JSON.stringify(surveyFilters)
      })
      
      if (response.ok) {
        setMessage({ type: "success", text: "Survey filter settings saved successfully!" })
      } else {
        const error = await response.json()
        setMessage({ type: "error", text: getErrorMessage(error, "Failed to save filters") })
      }
    } catch (error) {
      console.error("Error saving filters:", error)
      setMessage({ type: "error", text: "Failed to save filters" })
    } finally {
      setSaving(false)
    }
  }

  // Combined save function for merged settings page
  const saveAllSettings = async () => {
    setSaving(true)
    setMessage({ type: "", text: "" })
    
    try {
      const token = getAuthToken()
      
      // Save app settings
      const appResponse = await fetch(`${API_BASE_URL}/settings/app`, {
        method: "POST",
        headers: {
          Authorization: token,
          "Content-Type": "application/json"
        },
        body: JSON.stringify(appSettings)
      })
      
      if (!appResponse.ok) {
        const error = await appResponse.json()
        setMessage({ type: "error", text: getErrorMessage(error, "Failed to save application settings") })
        return
      }
      
      // Save survey filters
      const filterResponse = await fetch(`${API_BASE_URL}/settings/survey-filters`, {
        method: "POST",
        headers: {
          Authorization: token,
          "Content-Type": "application/json"
        },
        body: JSON.stringify(surveyFilters)
      })
      
      if (!filterResponse.ok) {
        const error = await filterResponse.json()
        setMessage({ type: "error", text: getErrorMessage(error, "Failed to save filter settings") })
        return
      }
      
      setMessage({ type: "success", text: "All settings saved successfully!" })
      loadAllSettings() // Reload to get updated masked values
    } catch (error) {
      console.error("Error saving settings:", error)
      setMessage({ type: "error", text: "Failed to save settings" })
    } finally {
      setSaving(false)
    }
  }

  const testMongoConnection = async () => {
    setTestingMongo(true)
    setMessage({ type: "", text: "" })
    
    try {
      const token = getAuthToken()
      const response = await fetch(`${API_BASE_URL}/settings/test-mongo`, {
        method: "POST",
        headers: {
          Authorization: token,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ mongo_uri: appSettings.mongo_uri })
      })
      
      const data = await response.json()
      setMessage({ 
        type: data.success ? "success" : "error", 
        text: data.message 
      })
    } catch (error) {
      setMessage({ type: "error", text: "Connection test failed" })
    } finally {
      setTestingMongo(false)
    }
  }

  const testCpxCredentials = async () => {
    setTestingCpx(true)
    setMessage({ type: "", text: "" })
    
    try {
      const token = getAuthToken()
      const response = await fetch(`${API_BASE_URL}/settings/test-cpx`, {
        method: "POST",
        headers: {
          Authorization: token,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          cpx_app_id: appSettings.cpx_app_id,
          cpx_ext_user_id: appSettings.cpx_ext_user_id,
          cpx_secure_hash_key: appSettings.cpx_secure_hash_key
        })
      })
      
      const data = await response.json()
      setMessage({ 
        type: data.success ? "success" : "error", 
        text: data.message 
      })
    } catch (error) {
      setMessage({ type: "error", text: "Credential test failed" })
    } finally {
      setTestingCpx(false)
    }
  }

  const handleAppSettingChange = (key, value) => {
    setAppSettings(prev => ({ ...prev, [key]: value }))
  }

  const handleFilterChange = (key, value) => {
    setSurveyFilters(prev => ({ ...prev, [key]: value }))
  }

  const handleRateLimitChange = (key, value) => {
    setRateLimits(prev => ({ ...prev, [key]: value }))
  }

  // Gmail account management functions
  const initiateGmailAuth = async () => {
    try {
      const token = getAuthToken()
      const response = await fetch(`${API_BASE_URL}/gmail/auth/url`, {
        headers: { Authorization: token }
      })
      if (response.ok) {
        const data = await response.json()
        // Open OAuth window
        window.open(data.auth_url, "_blank", "width=600,height=700")
      } else {
        setMessage({ type: "error", text: "Failed to get authentication URL" })
      }
    } catch (error) {
      setMessage({ type: "error", text: "Failed to initiate Gmail authentication" })
    }
  }

  const authenticateAccount = async (accountId) => {
    try {
      const token = getAuthToken()
      const response = await fetch(`${API_BASE_URL}/gmail/auth/url?account_id=${accountId}`, {
        headers: { Authorization: token }
      })
      if (response.ok) {
        const data = await response.json()
        // Open OAuth window
        window.open(data.auth_url, "_blank", "width=600,height=700")
        setMessage({ type: "success", text: "Complete authentication in the popup window, then refresh this page." })
      } else {
        setMessage({ type: "error", text: "Failed to get authentication URL" })
      }
    } catch (error) {
      setMessage({ type: "error", text: "Failed to initiate authentication" })
    }
  }

  const addGmailAccount = async () => {
    if (!newAccount.email) {
      setMessage({ type: "error", text: "Email is required" })
      return
    }
    if (!newAccount.password) {
      setMessage({ type: "error", text: "App password is required" })
      return
    }
    
    setSaving(true)
    try {
      const token = getAuthToken()
      const response = await fetch(`${API_BASE_URL}/leads/gmail/accounts`, {
        method: "POST",
        headers: {
          Authorization: token,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          email: newAccount.email,
          password: newAccount.password,
          display_name: newAccount.display_name || newAccount.email.split("@")[0],
          imap_server: newAccount.imap_server || null,
          imap_port: newAccount.imap_port,
          smtp_server: newAccount.smtp_server || null,
          smtp_port: newAccount.smtp_port,
          use_ssl: newAccount.use_ssl,
          is_default: newAccount.is_default,
          skip_validation: newAccount.skip_validation
        })
      })
      
      if (response.ok) {
        setMessage({ type: "success", text: newAccount.skip_validation ? "Email account saved (validation skipped)" : "Email account added and verified successfully" })
        setNewAccount({ 
          email: "", 
          password: "",
          display_name: "", 
          imap_server: "",
          imap_port: 993,
          smtp_server: "",
          smtp_port: 587,
          use_ssl: true,
          is_default: false,
          skip_validation: false
        })
        setShowAddAccount(false)
        loadGmailSettings()
      } else {
        const error = await response.json()
        setMessage({ type: "error", text: getErrorMessage(error, "Failed to add account. Check your credentials.") })
      }
    } catch (error) {
      setMessage({ type: "error", text: "Failed to add Gmail account" })
    } finally {
      setSaving(false)
    }
  }

  const removeGmailAccount = async (accountEmail) => {
    if (!window.confirm("Are you sure you want to remove this email account?")) {
      return
    }
    
    try {
      const token = getAuthToken()
      const response = await fetch(`${API_BASE_URL}/leads/gmail/accounts/${encodeURIComponent(accountEmail)}`, {
        method: "DELETE",
        headers: { Authorization: token }
      })
      
      if (response.ok) {
        setMessage({ type: "success", text: "Email account removed" })
        loadGmailSettings()
      } else {
        setMessage({ type: "error", text: "Failed to remove account" })
      }
    } catch (error) {
      setMessage({ type: "error", text: "Failed to remove account" })
    }
  }

  const testEmailAccount = async (accountEmail) => {
    try {
      const token = getAuthToken()
      const response = await fetch(`${API_BASE_URL}/leads/gmail/accounts/${encodeURIComponent(accountEmail)}/test`, {
        method: "POST",
        headers: { Authorization: token }
      })
      
      const data = await response.json()
      if (data.success) {
        setMessage({ type: "success", text: `Connection test successful for ${accountEmail}` })
      } else {
        setMessage({ type: "error", text: data.message || "Connection test failed" })
      }
    } catch (error) {
      setMessage({ type: "error", text: "Failed to test connection" })
    }
  }

  const addAlias = async (accountEmail) => {
    if (!newAlias.email) {
      setMessage({ type: "error", text: "Alias email is required" })
      return
    }
    
    setSaving(true)
    try {
      const token = getAuthToken()
      const response = await fetch(`${API_BASE_URL}/leads/gmail/accounts/${encodeURIComponent(accountEmail)}/aliases`, {
        method: "POST",
        headers: {
          Authorization: token,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ email: newAlias.email, name: newAlias.name })
      })
      
      if (response.ok) {
        setMessage({ type: "success", text: "Alias added successfully" })
        setNewAlias({ email: "", name: "", account_id: "" })
        setShowAddAlias(null)
        loadGmailSettings()
      } else {
        const error = await response.json()
        setMessage({ type: "error", text: getErrorMessage(error, "Failed to add alias") })
      }
    } catch (error) {
      setMessage({ type: "error", text: "Failed to add alias" })
    } finally {
      setSaving(false)
    }
  }

  const removeAlias = async (accountEmail, aliasEmail) => {
    try {
      const token = getAuthToken()
      const response = await fetch(
        `${API_BASE_URL}/leads/gmail/accounts/${encodeURIComponent(accountEmail)}/aliases/${encodeURIComponent(aliasEmail)}`,
        {
          method: "DELETE",
          headers: { Authorization: token }
        }
      )
      
      if (response.ok) {
        setMessage({ type: "success", text: "Alias removed" })
        loadGmailSettings()
      } else {
        setMessage({ type: "error", text: "Failed to remove alias" })
      }
    } catch (error) {
      setMessage({ type: "error", text: "Failed to remove alias" })
    }
  }

  const syncAliases = async (accountEmail) => {
    setGmailLoading(true)
    setMessage({ type: "info", text: "Scanning sent emails to detect aliases... This may take a moment." })
    
    try {
      const token = getAuthToken()
      const response = await fetch(`${API_BASE_URL}/leads/gmail/accounts/${encodeURIComponent(accountEmail)}/aliases/sync`, {
        method: "POST",
        headers: { Authorization: token }
      })
      
      if (response.ok) {
        const data = await response.json()
        if (data.added > 0) {
          setMessage({ type: "success", text: `✅ Found and added ${data.added} aliases! Total: ${data.total_aliases}` })
        } else {
          setMessage({ type: "info", text: "No new aliases found. All detected aliases are already added." })
        }
        loadGmailSettings()
      } else {
        const error = await response.json()
        setMessage({ type: "error", text: getErrorMessage(error, "Failed to sync aliases") })
      }
    } catch (error) {
      console.error("Error syncing aliases:", error)
      setMessage({ type: "error", text: "Failed to sync aliases. Check console for details." })
    } finally {
      setGmailLoading(false)
    }
  }

  const saveRateLimits = async () => {
    setSaving(true)
    setMessage({ type: "", text: "" })
    
    try {
      const token = getAuthToken()
      const response = await fetch(`${API_BASE_URL}/gmail/rate-limits`, {
        method: "POST",
        headers: {
          Authorization: token,
          "Content-Type": "application/json"
        },
        body: JSON.stringify(rateLimits)
      })
      
      if (response.ok) {
        setMessage({ type: "success", text: "Rate limits saved successfully!" })
      } else {
        const error = await response.json()
        setMessage({ type: "error", text: getErrorMessage(error, "Failed to save rate limits") })
      }
    } catch (error) {
      setMessage({ type: "error", text: "Failed to save rate limits" })
    } finally {
      setSaving(false)
    }
  }

  const setDefaultAccount = async (accountId) => {
    try {
      const token = getAuthToken()
      const response = await fetch(`${API_BASE_URL}/gmail/accounts/${accountId}/set-default`, {
        method: "POST",
        headers: { Authorization: token }
      })
      
      if (response.ok) {
        setMessage({ type: "success", text: "Default account updated" })
        loadGmailSettings()
      } else {
        setMessage({ type: "error", text: "Failed to set default account" })
      }
    } catch (error) {
      setMessage({ type: "error", text: "Failed to set default account" })
    }
  }

  if (loading) {
    return (
      <div className="settings-loading">
        <div className="spinner"></div>
        <p>Loading settings...</p>
      </div>
    )
  }

  return (
    <div className="settings-container">
      <div className="settings-header">
        <h1>Settings</h1>
        <p className="settings-subtitle">Manage application configuration and survey filters</p>
      </div>

      {message.text && (
        <div className={`settings-message ${message.type}`}>
          {message.type === "success" ? "✓" : "⚠"} {message.text}
        </div>
      )}

      <div className="settings-tabs">
        <button 
          className={`tab-button ${activeTab === "app" ? "active" : ""}`}
          onClick={() => setActiveTab("app")}
        >
          <span className="tab-icon">⚙️</span>
          Settings
        </button>
        <button 
          className={`tab-button ${activeTab === "allocation" ? "active" : ""}`}
          onClick={() => setActiveTab("allocation")}
        >
          <span className="tab-icon">📊</span>
          Survey Allocation
        </button>
        <button 
          className={`tab-button ${activeTab === "gmail" ? "active" : ""}`}
          onClick={() => setActiveTab("gmail")}
        >
          <span className="tab-icon">📬</span>
          Gmail & Rate Limits
        </button>
        <button 
          className={`tab-button ${activeTab === "emailsync" ? "active" : ""}`}
          onClick={() => setActiveTab("emailsync")}
        >
          <span className="tab-icon">🔄</span>
          Email Sync
        </button>
      </div>

      <div className="settings-content">
        {activeTab === "app" && (
          <div className="settings-section">
            <h2>Application Configuration</h2>
            <p className="section-description">
              Configure API keys, database connections, and service credentials.
            </p>

            <div className="settings-grid">
              <div className="settings-group">
                <h3>🗄️ Database Settings</h3>
                <div className="setting-row">
                  <label>MongoDB URI</label>
                  <div className="input-with-button">
                    <input
                      type="text"
                      placeholder={maskedSettings.mongo_uri || "mongodb://localhost:27017/"}
                      value={appSettings.mongo_uri}
                      onChange={(e) => handleAppSettingChange("mongo_uri", e.target.value)}
                    />
                    <button 
                      className="test-button"
                      onClick={testMongoConnection}
                      disabled={testingMongo}
                    >
                      {testingMongo ? "Testing..." : "Test"}
                    </button>
                  </div>
                </div>
              </div>

              <div className="settings-group">
                <h3>📊 CPX Research Settings</h3>
                <div className="setting-row">
                  <label>App ID</label>
                  <input
                    type="text"
                    placeholder={maskedSettings.cpx_app_id || "10754"}
                    value={appSettings.cpx_app_id}
                    onChange={(e) => handleAppSettingChange("cpx_app_id", e.target.value)}
                  />
                </div>
                <div className="setting-row">
                  <label>External User ID</label>
                  <input
                    type="text"
                    placeholder={maskedSettings.cpx_ext_user_id || "user_id"}
                    value={appSettings.cpx_ext_user_id}
                    onChange={(e) => handleAppSettingChange("cpx_ext_user_id", e.target.value)}
                  />
                </div>
                <div className="setting-row">
                  <label>Secure Hash Key</label>
                  <div className="input-with-button">
                    <input
                      type="password"
                      placeholder={maskedSettings.cpx_secure_hash_key_masked || "Enter secure hash key"}
                      value={appSettings.cpx_secure_hash_key}
                      onChange={(e) => handleAppSettingChange("cpx_secure_hash_key", e.target.value)}
                    />
                    <button 
                      className="test-button"
                      onClick={testCpxCredentials}
                      disabled={testingCpx}
                    >
                      {testingCpx ? "Testing..." : "Test"}
                    </button>
                  </div>
                </div>
                <div className="setting-row">
                  <label>API Timeout</label>
                  <div className="input-with-unit">
                    <input
                      type="number"
                      min="5"
                      max="120"
                      value={appSettings.cpx_api_timeout}
                      onChange={(e) => handleAppSettingChange("cpx_api_timeout", parseInt(e.target.value))}
                    />
                    <span className="unit">seconds</span>
                  </div>
                </div>
              </div>

              <div className="settings-group">
                <h3>🤖 AI / LLM Settings</h3>
                <div className="setting-row">
                  <label>OpenAI API Key</label>
                  <input
                    type="password"
                    placeholder={maskedSettings.openai_api_key_masked || "sk-..."}
                    value={appSettings.openai_api_key}
                    onChange={(e) => handleAppSettingChange("openai_api_key", e.target.value)}
                  />
                  <p className="setting-hint">Used for AI features (GPT-4o-mini). Get from <a href="https://platform.openai.com/api-keys" target="_blank" rel="noopener noreferrer">OpenAI</a></p>
                </div>
                <div className="setting-row">
                  <label>Anthropic API Key</label>
                  <input
                    type="password"
                    placeholder={maskedSettings.anthropic_api_key_masked || "sk-ant-..."}
                    value={appSettings.anthropic_api_key}
                    onChange={(e) => handleAppSettingChange("anthropic_api_key", e.target.value)}
                  />
                  <p className="setting-hint">Used for premium AI classification (Claude). Get from <a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noopener noreferrer">Anthropic Console</a></p>
                </div>
              </div>

              <div className="settings-group">
                <h3>🔍 Google API Settings</h3>
                <div className="setting-row">
                  <label>Google API Key</label>
                  <input
                    type="password"
                    placeholder={maskedSettings.google_api_key_masked || "AIza..."}
                    value={appSettings.google_api_key}
                    onChange={(e) => handleAppSettingChange("google_api_key", e.target.value)}
                  />
                  <p className="setting-hint">From <a href="https://console.cloud.google.com/apis/credentials" target="_blank" rel="noopener noreferrer">Google Cloud Console</a></p>
                </div>
                <div className="setting-row">
                  <label>Custom Search Engine ID</label>
                  <input
                    type="text"
                    placeholder={maskedSettings.google_cse_id_masked || "Your CSE ID"}
                    value={appSettings.google_cse_id}
                    onChange={(e) => handleAppSettingChange("google_cse_id", e.target.value)}
                  />
                  <p className="setting-hint">From <a href="https://programmablesearchengine.google.com/" target="_blank" rel="noopener noreferrer">Google Programmable Search</a></p>
                </div>
              </div>

              <div className="settings-group settings-grid-full">
                <h3>📄 Google Sheets Service Account</h3>
                <div className="setting-row">
                  <label>Service Account JSON</label>
                  <textarea
                    placeholder={maskedSettings.google_sheets_service_account_masked || '{"type": "service_account", ...}'}
                    value={appSettings.google_sheets_service_account}
                    onChange={(e) => handleAppSettingChange("google_sheets_service_account", e.target.value)}
                    rows={3}
                    style={{ fontFamily: 'monospace', fontSize: '11px', width: '100%', padding: '0.6rem', borderRadius: '6px', border: '1px solid #d1d5db' }}
                  />
                  <p className="setting-hint">Full JSON key for Sheets API. Download from <a href="https://console.cloud.google.com/iam-admin/serviceaccounts" target="_blank" rel="noopener noreferrer">Service Accounts</a></p>
                </div>
              </div>

            {/* Google CSE Rate Limiting for Cost Control */}
            <div className="settings-group">
              <h3>💰 Google Search Rate Limiting</h3>
              <div className="setting-row" style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                <input
                  type="checkbox"
                  checked={appSettings.google_cse_rate_limit_enabled !== false}
                  onChange={(e) => handleAppSettingChange("google_cse_rate_limit_enabled", e.target.checked)}
                  style={{ width: '18px', height: '18px' }}
                />
                <label style={{ margin: 0 }}>Enable Rate Limiting</label>
                <span style={{ color: appSettings.google_cse_rate_limit_enabled !== false ? '#10b981' : '#ef4444', fontSize: '0.8rem', fontWeight: 500 }}>
                  {appSettings.google_cse_rate_limit_enabled !== false ? '✓ Active' : '✗ Off'}
                </span>
              </div>
              <div className="setting-row">
                <label>Daily / Hourly Limits</label>
                <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
                  <div className="input-with-unit">
                    <input
                      type="number"
                      min="10"
                      max="10000"
                      value={appSettings.google_cse_daily_limit || 400}
                      onChange={(e) => handleAppSettingChange("google_cse_daily_limit", parseInt(e.target.value))}
                    />
                    <span className="unit">/day</span>
                  </div>
                  <div className="input-with-unit">
                    <input
                      type="number"
                      min="5"
                      max="500"
                      value={appSettings.google_cse_hourly_limit || 50}
                      onChange={(e) => handleAppSettingChange("google_cse_hourly_limit", parseInt(e.target.value))}
                    />
                    <span className="unit">/hour</span>
                  </div>
                </div>
                <p className="setting-hint">Est. cost: ${(((appSettings.google_cse_daily_limit || 400) - 100) * 30 * 5 / 1000).toFixed(0)}/mo</p>
              </div>
              <div className="setting-row">
                <label>Query Delay / Budget</label>
                <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
                  <div className="input-with-unit">
                    <input
                      type="number"
                      min="1"
                      max="60"
                      value={appSettings.google_cse_query_delay || 3}
                      onChange={(e) => handleAppSettingChange("google_cse_query_delay", parseInt(e.target.value))}
                    />
                    <span className="unit">sec</span>
                  </div>
                  <div className="input-with-unit">
                    <input
                      type="number"
                      min="0"
                      max="500"
                      step="5"
                      value={appSettings.google_cse_monthly_budget || 50}
                      onChange={(e) => handleAppSettingChange("google_cse_monthly_budget", parseFloat(e.target.value))}
                    />
                    <span className="unit">$/mo</span>
                  </div>
                </div>
              </div>
            </div>

              {/* Survey Filter Settings */}
              <div className="settings-group">
                <h3>📋 Survey Filters</h3>
                <div className="setting-row">
                  <label>Max LOI / Min CPI</label>
                  <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
                    <div className="input-with-unit">
                      <input
                        type="number"
                        min="1"
                        max="120"
                        value={surveyFilters.max_loi}
                        onChange={(e) => handleFilterChange("max_loi", parseInt(e.target.value))}
                      />
                      <span className="unit">min</span>
                    </div>
                    <div className="input-with-unit">
                      <input
                        type="number"
                        min="0.01"
                        max="100"
                        step="0.01"
                        value={surveyFilters.min_cpi}
                        onChange={(e) => handleFilterChange("min_cpi", parseFloat(e.target.value))}
                      />
                      <span className="unit">$ CPI</span>
                    </div>
                  </div>
                  <p className="setting-hint">Filter out surveys exceeding LOI or below CPI</p>
                </div>
                <div className="setting-row">
                  <label>Deletion Period</label>
                  <div className="input-with-unit">
                    <input
                      type="number"
                      min="1"
                      max="30"
                      value={surveyFilters.deletion_period_days}
                      onChange={(e) => handleFilterChange("deletion_period_days", parseInt(e.target.value))}
                    />
                    <span className="unit">days</span>
                  </div>
                  <p className="setting-hint">Auto-delete old surveys</p>
                </div>
                <div className="setting-row" style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                  <input
                    type="checkbox"
                    checked={surveyFilters.auto_refresh_enabled}
                    onChange={(e) => handleFilterChange("auto_refresh_enabled", e.target.checked)}
                    style={{ width: '18px', height: '18px' }}
                  />
                  <label style={{ margin: 0 }}>Auto Refresh</label>
                  <div className="input-with-unit">
                    <input
                      type="number"
                      min="30"
                      max="3600"
                      value={surveyFilters.refresh_interval_seconds}
                      onChange={(e) => handleFilterChange("refresh_interval_seconds", parseInt(e.target.value))}
                      disabled={!surveyFilters.auto_refresh_enabled}
                      style={{ width: '80px' }}
                    />
                    <span className="unit">sec</span>
                  </div>
                </div>
              </div>

            </div>{/* End settings-grid */}

            <div className="settings-actions">
              <button 
                className="save-button"
                onClick={saveAllSettings}
                disabled={saving}
              >
                {saving ? "Saving..." : "Save All Settings"}
              </button>
            </div>
          </div>
        )}

        {activeTab === "allocation" && (
          <div className="settings-section">
            <h2>Survey Allocation & Quality Control</h2>
            <p className="section-description">
              Configure allocation batch sizes, quality thresholds, and auto-pause rules.
            </p>

            <div className="settings-grid">
              <div className="settings-group">
                <h3>📦 Batch Settings</h3>
                <div className="setting-row">
                  <label>Batch Size</label>
                  <div className="input-with-unit">
                    <input
                      type="number"
                      min="1"
                      max="1000"
                      value={allocationSettings.batch_size}
                      onChange={(e) => handleAllocationSettingChange("batch_size", parseInt(e.target.value))}
                  />
                  <span className="unit">allocs</span>
                </div>
              </div>
              <div className="setting-row">
                <label>Buffer Multiplier</label>
                <div className="input-with-unit">
                  <input
                    type="number"
                    min="1.0"
                    max="2.0"
                    step="0.1"
                    value={allocationSettings.buffer_multiplier}
                    onChange={(e) => handleAllocationSettingChange("buffer_multiplier", parseFloat(e.target.value))}
                  />
                  <span className="unit">x</span>
                </div>
                <p className="setting-hint">Extra buffer (1.2 = 20% more)</p>
              </div>
            </div>

              <div className="settings-group">
                <h3>📈 Quality Thresholds</h3>
                <div className="setting-row">
                  <label>Max Incomplete Rate</label>
                  <div className="input-with-unit">
                    <input
                      type="number"
                      min="0"
                      max="100"
                      value={allocationSettings.max_incomplete_rate}
                      onChange={(e) => handleAllocationSettingChange("max_incomplete_rate", parseFloat(e.target.value))}
                    />
                    <span className="unit">%</span>
                  </div>
                </div>
                <div className="setting-row">
                  <label>Min Incidence Rate</label>
                  <div className="input-with-unit">
                    <input
                      type="number"
                      min="0"
                      max="100"
                      value={allocationSettings.min_incidence_rate}
                      onChange={(e) => handleAllocationSettingChange("min_incidence_rate", parseFloat(e.target.value))}
                    />
                    <span className="unit">%</span>
                  </div>
                </div>
                <div className="setting-row">
                  <label>Min Entrants for Eval</label>
                  <div className="input-with-unit">
                    <input
                      type="number"
                      min="10"
                      max="500"
                      value={allocationSettings.minimum_entrants_for_evaluation}
                      onChange={(e) => handleAllocationSettingChange("minimum_entrants_for_evaluation", parseInt(e.target.value))}
                    />
                    <span className="unit">users</span>
                  </div>
                </div>
              </div>

              <div className="settings-group">
                <h3>⏸️ Auto-Pause</h3>
                <div className="setting-row" style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                  <input
                    type="checkbox"
                    checked={allocationSettings.auto_pause_enabled}
                    onChange={(e) => handleAllocationSettingChange("auto_pause_enabled", e.target.checked)}
                    style={{ width: '18px', height: '18px' }}
                  />
                  <label style={{ margin: 0 }}>Enable Auto-Pause</label>
                </div>
                <div className="setting-row">
                  <label>Cooldown Period</label>
                  <div className="input-with-unit">
                    <input
                      type="number"
                      min="5"
                      max="1440"
                      value={allocationSettings.pause_cooldown_minutes}
                      onChange={(e) => handleAllocationSettingChange("pause_cooldown_minutes", parseInt(e.target.value))}
                      disabled={!allocationSettings.auto_pause_enabled}
                    />
                    <span className="unit">min</span>
                  </div>
                  <p className="setting-hint">Time before auto-resume</p>
                </div>
              </div>

              <div className="settings-group">
                <h3>🎯 Allocation Preferences</h3>
                <div className="setting-row" style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                  <input
                    type="checkbox"
                    checked={allocationSettings.prefer_high_ir_surveys}
                    onChange={(e) => handleAllocationSettingChange("prefer_high_ir_surveys", e.target.checked)}
                    style={{ width: '18px', height: '18px' }}
                  />
                  <label style={{ margin: 0 }}>Prefer High IR Surveys</label>
                </div>
                <div className="setting-row" style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                  <input
                    type="checkbox"
                    checked={allocationSettings.prefer_high_cpi_surveys}
                    onChange={(e) => handleAllocationSettingChange("prefer_high_cpi_surveys", e.target.checked)}
                    style={{ width: '18px', height: '18px' }}
                  />
                  <label style={{ margin: 0 }}>Prefer High CPI Surveys</label>
                </div>
              </div>
            </div>{/* End settings-grid */}

            <div className="settings-actions">
              <button 
                className="save-button"
                onClick={saveAllocationSettings}
                disabled={saving}
              >
                {saving ? "Saving..." : "Save Allocation Settings"}
              </button>
            </div>
          </div>
        )}

        {activeTab === "gmail" && (
          <div className="settings-section">
            <h2>Email Account Settings (IMAP/SMTP)</h2>
            <p className="section-description">
              Manage email accounts for lead extraction. For Gmail, use an App Password.
            </p>

            {gmailLoading ? (
              <div className="settings-loading-inline">
                <div className="spinner-small"></div>
                <span>Loading Gmail settings...</span>
              </div>
            ) : (
              <>
                <div className="settings-grid">
                {/* Gmail Accounts Section */}
                <div className="settings-group settings-grid-full">
                  <div className="group-header">
                    <h3>📧 Email Accounts</h3>
                    <button 
                      className="add-button"
                      onClick={() => setShowAddAccount(!showAddAccount)}
                    >
                      {showAddAccount ? "Cancel" : "+ Add Account"}
                    </button>
                  </div>
                  
                  {showAddAccount && (
                    <div className="add-form">
                      <div className="setting-row">
                        <label>Email Address *</label>
                        <input
                          type="email"
                          placeholder="example@gmail.com"
                          value={newAccount.email}
                          onChange={(e) => setNewAccount(prev => ({ ...prev, email: e.target.value }))}
                        />
                      </div>
                      <div className="setting-row">
                        <label>App Password *</label>
                        <input
                          type="password"
                          placeholder="App password (not your regular password)"
                          value={newAccount.password}
                          onChange={(e) => setNewAccount(prev => ({ ...prev, password: e.target.value }))}
                        />
                        <small className="field-hint">
                          For Gmail: Create an App Password at <a href="https://myaccount.google.com/apppasswords" target="_blank" rel="noopener noreferrer">Google Account Settings</a>
                        </small>
                      </div>
                      <div className="setting-row">
                        <label>Display Name</label>
                        <input
                          type="text"
                          placeholder="John Doe"
                          value={newAccount.display_name}
                          onChange={(e) => setNewAccount(prev => ({ ...prev, display_name: e.target.value }))}
                        />
                      </div>
                      
                      <details className="advanced-settings">
                        <summary>Advanced IMAP/SMTP Settings</summary>
                        <div className="advanced-content">
                          <div className="setting-row">
                            <label>IMAP Server</label>
                            <input
                              type="text"
                              placeholder="Auto-detected (e.g., imap.gmail.com)"
                              value={newAccount.imap_server}
                              onChange={(e) => setNewAccount(prev => ({ ...prev, imap_server: e.target.value }))}
                            />
                          </div>
                          <div className="setting-row">
                            <label>IMAP Port</label>
                            <input
                              type="number"
                              value={newAccount.imap_port}
                              onChange={(e) => setNewAccount(prev => ({ ...prev, imap_port: parseInt(e.target.value) || 993 }))}
                            />
                          </div>
                          <div className="setting-row">
                            <label>SMTP Server</label>
                            <input
                              type="text"
                              placeholder="Auto-detected (e.g., smtp.gmail.com)"
                              value={newAccount.smtp_server}
                              onChange={(e) => setNewAccount(prev => ({ ...prev, smtp_server: e.target.value }))}
                            />
                          </div>
                          <div className="setting-row">
                            <label>SMTP Port</label>
                            <input
                              type="number"
                              value={newAccount.smtp_port}
                              onChange={(e) => setNewAccount(prev => ({ ...prev, smtp_port: parseInt(e.target.value) || 587 }))}
                            />
                          </div>
                          <div className="setting-row checkbox-row">
                            <label className="checkbox-label">
                              <input
                                type="checkbox"
                                checked={newAccount.use_ssl}
                                onChange={(e) => setNewAccount(prev => ({ ...prev, use_ssl: e.target.checked }))}
                              />
                              <span>Use SSL/TLS</span>
                            </label>
                          </div>
                        </div>
                      </details>
                      
                      <div className="setting-row checkbox-row">
                        <label className="checkbox-label">
                          <input
                            type="checkbox"
                            checked={newAccount.is_default}
                            onChange={(e) => setNewAccount(prev => ({ ...prev, is_default: e.target.checked }))}
                          />
                          <span>Set as default account</span>
                        </label>
                      </div>
                      <div className="setting-row checkbox-row" style={{ backgroundColor: '#fef3c7', padding: '12px', borderRadius: '8px', border: '1px solid #f59e0b' }}>
                        <label className="checkbox-label">
                          <input
                            type="checkbox"
                            checked={newAccount.skip_validation}
                            onChange={(e) => setNewAccount(prev => ({ ...prev, skip_validation: e.target.checked }))}
                          />
                          <span style={{ fontWeight: '500' }}>Skip connection test (save credentials without validating)</span>
                        </label>
                        <p style={{ fontSize: '12px', color: '#92400e', marginTop: '6px', marginLeft: '24px' }}>
                          ⚠️ Use this if IMAP is blocked by firewall/VPN. Credentials will be saved and you can test later.
                        </p>
                      </div>
                      <div className="form-actions">
                        <button 
                          className="save-button-small"
                          onClick={addGmailAccount}
                          disabled={saving || !newAccount.email || !newAccount.password}
                        >
                          {saving ? "Adding..." : "Add Account"}
                        </button>
                      </div>
                    </div>
                  )}

                  {gmailAccounts.length === 0 ? (
                    <p className="empty-message">No email accounts configured. Add one to get started.</p>
                  ) : (
                    <div className="accounts-list">
                      {gmailAccounts.map((account) => (
                        <div key={account.id} className="account-card">
                          <div className="account-header">
                            <div className="account-info">
                              <span className="account-email">{account.email}</span>
                              {account.name && <span className="account-name">({account.name})</span>}
                              {account.is_default && <span className="default-badge">Default</span>}
                              <span className={`status-badge ${account.is_authenticated ? "authenticated" : "not-authenticated"}`}>
                                {account.is_authenticated ? "✓ Active" : "⚠ Inactive"}
                              </span>
                              {account.imap_server && <span className="server-info">({account.imap_server})</span>}
                            </div>
                            <div className="account-actions">
                              <button 
                                className="action-button"
                                onClick={() => testEmailAccount(account.email)}
                                title="Test IMAP connection"
                              >
                                🔌
                              </button>
                              <button 
                                className="action-button delete"
                                onClick={() => removeGmailAccount(account.email)}
                                title="Remove account"
                              >
                                🗑️
                              </button>
                            </div>
                          </div>
                          
                          {account.last_sync && (
                            <div className="account-meta">
                              <span className="last-sync">Last sync: {new Date(account.last_sync).toLocaleString()}</span>
                            </div>
                          )}
                          
                          {/* Historical Import Section */}
                          <div className="import-section">
                            <div className="import-controls">
                              <label className="import-label">Import History:</label>
                              <select
                                className="import-days-select"
                                value={importDays[account.email] || 30}
                                onChange={(e) => updateImportDaysSetting(account.email, parseInt(e.target.value))}
                              >
                                <option value={7}>Last 7 days</option>
                                <option value={30}>Last 30 days</option>
                                <option value={90}>Last 90 days</option>
                                <option value={180}>Last 6 months</option>
                                <option value={365}>Last 1 year</option>
                                <option value={730}>Last 2 years</option>
                                <option value={0}>All emails</option>
                              </select>
                              <button
                                className="import-button"
                                onClick={() => startHistoricalImport(account.email)}
                                disabled={importProgress[account.email]?.status === "in_progress" || importProgress[account.email]?.status === "running"}
                              >
                                {(importProgress[account.email]?.status === "in_progress" || importProgress[account.email]?.status === "running") ? "⏳ Importing..." : "📥 Import"}
                              </button>
                            </div>
                            
                            {/* Import Progress */}
                            {importProgress[account.email] && importProgress[account.email].status !== "not_started" && (
                              <div className="import-progress">
                                <div className="progress-status">
                                  <span className={`progress-badge ${importProgress[account.email].status}`}>
                                    {importProgress[account.email].status === "in_progress" && "⏳ Importing..."}
                                    {importProgress[account.email].status === "completed" && "✅ Completed"}
                                    {importProgress[account.email].status === "error" && "❌ Error"}
                                    {importProgress[account.email].status === "running" && "⏳ Importing..."}
                                  </span>
                                  {importProgress[account.email].processed_count !== undefined && importProgress[account.email].total_count > 0 && (
                                    <span className="progress-count">
                                      {importProgress[account.email].phase === "classifying" ? "🔄 Classifying: " : ""}
                                      {importProgress[account.email].processed_count} / {importProgress[account.email].total_count} emails 
                                      ({Math.round((importProgress[account.email].processed_count / importProgress[account.email].total_count) * 100)}%)
                                    </span>
                                  )}
                                  {importProgress[account.email].processed_count !== undefined && !importProgress[account.email].total_count && (
                                    <span className="progress-count">
                                      {importProgress[account.email].phase === "connecting" && "🔌 Connecting to IMAP..."}
                                      {importProgress[account.email].phase === "fetching" && "📥 Downloading emails via IMAP..."}
                                      {!importProgress[account.email].phase && "📥 Fetching emails..."}
                                    </span>
                                  )}
                                </div>
                                {(importProgress[account.email].status === "in_progress" || importProgress[account.email].status === "running") && (
                                  <div className="progress-bar-container">
                                    <div 
                                      className="progress-bar"
                                      style={{ 
                                        width: `${importProgress[account.email].total_count 
                                          ? (importProgress[account.email].processed_count / importProgress[account.email].total_count) * 100 
                                          : 5}%` 
                                      }}
                                    ></div>
                                  </div>
                                )}
                                {importProgress[account.email].leads_created !== undefined && (
                                  <div className="progress-stats">
                                    <span>📧 Leads created: {importProgress[account.email].leads_created}</span>
                                    <span>📋 RFQs detected: {importProgress[account.email].rfqs_created || 0}</span>
                                  </div>
                                )}
                              </div>
                            )}
                          </div>
                          
                          {/* Email Aliases Section */}
                          <div className="aliases-section">
                            <div className="aliases-header">
                              <span className="aliases-title">📧 Email Aliases</span>
                              <div className="aliases-actions">
                                <button
                                  className="action-button"
                                  onClick={() => syncAliases(account.email)}
                                  title="Auto-detect aliases from sent emails"
                                  disabled={gmailLoading}
                                >
                                  {gmailLoading ? "⏳" : "🔍"}
                                </button>
                                <button
                                  className="action-button"
                                  onClick={() => setShowAddAlias(showAddAlias === account.email ? null : account.email)}
                                  title="Add alias manually"
                                >
                                  ➕
                                </button>
                              </div>
                            </div>
                            
                            {/* Alias List */}
                            {account.aliases && account.aliases.length > 0 ? (
                              <div className="aliases-list">
                                {account.aliases.map((alias, idx) => (
                                  <div key={idx} className="alias-item">
                                    <span className="alias-email">{alias.email}</span>
                                    {alias.name && <span className="alias-name">({alias.name})</span>}
                                    {alias.is_primary && <span className="primary-badge">Primary</span>}
                                    {alias.source === "auto_detected" && <span className="detected-badge">Auto</span>}
                                    <button
                                      className="action-button delete small"
                                      onClick={() => removeAlias(account.email, alias.email)}
                                      title="Remove alias"
                                    >
                                      ✕
                                    </button>
                                  </div>
                                ))}
                              </div>
                            ) : (
                              <p className="no-aliases">No aliases configured. Click 🔍 to auto-detect from sent emails or ➕ to add manually.</p>
                            )}
                            
                            {/* Add Alias Form */}
                            {showAddAlias === account.email && (
                              <div className="add-alias-form">
                                <input
                                  type="email"
                                  placeholder="alias@example.com"
                                  value={newAlias.email}
                                  onChange={(e) => setNewAlias(prev => ({ ...prev, email: e.target.value }))}
                                  className="alias-input"
                                />
                                <input
                                  type="text"
                                  placeholder="Display Name (optional)"
                                  value={newAlias.name}
                                  onChange={(e) => setNewAlias(prev => ({ ...prev, name: e.target.value }))}
                                  className="alias-input"
                                />
                                <button
                                  className="save-button-small"
                                  onClick={() => addAlias(account.email)}
                                  disabled={saving || !newAlias.email}
                                >
                                  {saving ? "Adding..." : "Add"}
                                </button>
                                <button
                                  className="cancel-button-small"
                                  onClick={() => {
                                    setShowAddAlias(null)
                                    setNewAlias({ email: "", name: "", account_id: "" })
                                  }}
                                >
                                  Cancel
                                </button>
                              </div>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* Real-time Monitoring Section */}
                <div className="settings-group">
                  <h3>🔄 Real-time Monitoring (IMAP IDLE)</h3>
                  
                  <div className="idle-status-section">
                    <div className="idle-status-info">
                      <span className={`idle-status-badge ${idleStatus.available ? (idleStatus.running ? "running" : "stopped") : "unavailable"}`}>
                        {!idleStatus.available ? "⚠ Not Available" : (idleStatus.running ? "🟢 Running" : "🔴 Stopped")}
                      </span>
                      {idleStatus.running && idleStatus.active_watchers && (
                        <span className="watcher-count">{idleStatus.active_watchers} account(s)</span>
                      )}
                    </div>
                    <div className="idle-actions">
                      <button
                        className="idle-button start"
                        onClick={() => toggleIdleWatchers(true)}
                        disabled={!idleStatus.available || idleStatus.running}
                      >
                        ▶ Start
                      </button>
                      <button
                        className="idle-button stop"
                        onClick={() => toggleIdleWatchers(false)}
                        disabled={!idleStatus.available || !idleStatus.running}
                      >
                        ⏹ Stop
                      </button>
                    </div>
                  </div>
                </div>

                {/* Rate Limits Section */}
                <div className="settings-group">
                  <h3>⏱️ Email Rate Limits</h3>
                  
                  <div className="setting-row" style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                    <input
                      type="checkbox"
                      checked={rateLimits.enabled}
                      onChange={(e) => handleRateLimitChange("enabled", e.target.checked)}
                      style={{ width: '18px', height: '18px' }}
                    />
                    <label style={{ margin: 0 }}>Enable Rate Limiting</label>
                  </div>
                  
                  <div className="setting-row">
                    <label>Daily / Hourly / Per Minute</label>
                    <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                      <div className="input-with-unit">
                        <input
                          type="number"
                          min="1"
                          max="2000"
                          value={rateLimits.max_per_day}
                          onChange={(e) => handleRateLimitChange("max_per_day", parseInt(e.target.value))}
                          disabled={!rateLimits.enabled}
                          style={{ width: '80px' }}
                        />
                        <span className="unit">/day</span>
                      </div>
                      <div className="input-with-unit">
                        <input
                          type="number"
                          min="1"
                          max="500"
                          value={rateLimits.max_per_hour}
                          onChange={(e) => handleRateLimitChange("max_per_hour", parseInt(e.target.value))}
                          disabled={!rateLimits.enabled}
                          style={{ width: '70px' }}
                        />
                        <span className="unit">/hr</span>
                      </div>
                      <div className="input-with-unit">
                        <input
                          type="number"
                          min="1"
                          max="30"
                          value={rateLimits.max_per_minute}
                          onChange={(e) => handleRateLimitChange("max_per_minute", parseInt(e.target.value))}
                          disabled={!rateLimits.enabled}
                          style={{ width: '60px' }}
                        />
                        <span className="unit">/min</span>
                      </div>
                    </div>
                  </div>
                  
                  <div className="setting-row">
                    <label>Cooldown</label>
                    <div className="input-with-unit">
                      <input
                        type="number"
                        min="0"
                        max="300"
                        value={rateLimits.cooldown_seconds}
                        onChange={(e) => handleRateLimitChange("cooldown_seconds", parseInt(e.target.value))}
                        disabled={!rateLimits.enabled}
                        style={{ width: '70px' }}
                      />
                      <span className="unit">sec</span>
                    </div>
                    <p className="setting-hint">Delay between sending emails</p>
                  </div>
                </div>
                </div>{/* End settings-grid */}

                <div className="settings-actions">
                  <button 
                    className="save-button"
                    onClick={saveRateLimits}
                    disabled={saving}
                  >
                    {saving ? "Saving..." : "Save Rate Limit Settings"}
                  </button>
                </div>
              </>
            )}
          </div>
        )}

        {/* Email Sync Tab */}
        {activeTab === "emailsync" && (
          <div className="settings-section">
            <h2>Email Sync Progress</h2>
            <p className="section-description">
              Monitor email synchronization status, view backfill progress, and manage sync workers.
            </p>
            <EmailSyncProgress refreshInterval={2000} />
          </div>
        )}
      </div>
    </div>
  )
}

export default Settings