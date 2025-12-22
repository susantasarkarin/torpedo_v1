"use client"

import { useState, useEffect } from "react"
import { API_BASE_URL } from "../config"
import "./Settings.css"

function Settings() {
  // App Settings state
  const [appSettings, setAppSettings] = useState({
    mongo_uri: "",
    cpx_app_id: "",
    cpx_ext_user_id: "",
    cpx_secure_hash_key: "",
    cpx_api_timeout: 30,
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
  const [newAccount, setNewAccount] = useState({ email: "", name: "", is_default: false })
  const [newAlias, setNewAlias] = useState({ email: "", name: "", account_id: "" })
  const [showAddAccount, setShowAddAccount] = useState(false)
  const [showAddAlias, setShowAddAlias] = useState(null) // account_id when open
  const [gmailLoading, setGmailLoading] = useState(false)
  
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState({ type: "", text: "" })
  const [activeTab, setActiveTab] = useState("app") // "app", "filters", or "gmail"
  const [testingMongo, setTestingMongo] = useState(false)
  const [testingCpx, setTestingCpx] = useState(false)

  useEffect(() => {
    loadAllSettings()
  }, [])

  useEffect(() => {
    if (activeTab === "gmail") {
      loadGmailSettings()
    }
  }, [activeTab])

  const loadGmailSettings = async () => {
    setGmailLoading(true)
    try {
      const token = sessionStorage.getItem("token")
      
      // Load Gmail accounts
      const accountsRes = await fetch(`${API_BASE_URL}/gmail/accounts`, {
        headers: { Authorization: token }
      })
      if (accountsRes.ok) {
        const data = await accountsRes.json()
        setGmailAccounts(data.accounts || [])
      }
      
      // Load rate limits
      const rateLimitsRes = await fetch(`${API_BASE_URL}/gmail/rate-limits`, {
        headers: { Authorization: token }
      })
      if (rateLimitsRes.ok) {
        const data = await rateLimitsRes.json()
        setRateLimits(prev => ({ ...prev, ...data.rate_limits }))
      }
    } catch (error) {
      console.error("Error loading Gmail settings:", error)
    } finally {
      setGmailLoading(false)
    }
  }

  const loadAllSettings = async () => {
    setLoading(true)
    try {
      const token = sessionStorage.getItem("token")
      
      // Load app settings
      const appRes = await fetch(`${API_BASE_URL}/settings/app`, {
        headers: { Authorization: token }
      })
      if (appRes.ok) {
        const data = await appRes.json()
        setAppSettings(prev => ({ ...prev, ...data.settings }))
        setMaskedSettings(data.settings)
      }
      
      // Load survey filters
      const filterRes = await fetch(`${API_BASE_URL}/settings/survey-filters`, {
        headers: { Authorization: token }
      })
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
      const token = sessionStorage.getItem("token")
      
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
        setMessage({ type: "error", text: error.detail || "Failed to save settings" })
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
      const token = sessionStorage.getItem("token")
      
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
        setMessage({ type: "error", text: error.detail || "Failed to save filters" })
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
      const token = sessionStorage.getItem("token")
      
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
        setMessage({ type: "error", text: error.detail || "Failed to save application settings" })
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
        setMessage({ type: "error", text: error.detail || "Failed to save filter settings" })
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
      const token = sessionStorage.getItem("token")
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
      const token = sessionStorage.getItem("token")
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
      const token = sessionStorage.getItem("token")
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
      const token = sessionStorage.getItem("token")
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
    
    setSaving(true)
    try {
      const token = sessionStorage.getItem("token")
      const response = await fetch(`${API_BASE_URL}/gmail/accounts`, {
        method: "POST",
        headers: {
          Authorization: token,
          "Content-Type": "application/json"
        },
        body: JSON.stringify(newAccount)
      })
      
      if (response.ok) {
        setMessage({ type: "success", text: "Gmail account added successfully" })
        setNewAccount({ email: "", name: "", is_default: false })
        setShowAddAccount(false)
        loadGmailSettings()
      } else {
        const error = await response.json()
        setMessage({ type: "error", text: error.detail || "Failed to add account" })
      }
    } catch (error) {
      setMessage({ type: "error", text: "Failed to add Gmail account" })
    } finally {
      setSaving(false)
    }
  }

  const removeGmailAccount = async (accountId) => {
    if (!window.confirm("Are you sure you want to remove this Gmail account?")) {
      return
    }
    
    try {
      const token = sessionStorage.getItem("token")
      const response = await fetch(`${API_BASE_URL}/gmail/accounts/${accountId}`, {
        method: "DELETE",
        headers: { Authorization: token }
      })
      
      if (response.ok) {
        setMessage({ type: "success", text: "Gmail account removed" })
        loadGmailSettings()
      } else {
        setMessage({ type: "error", text: "Failed to remove account" })
      }
    } catch (error) {
      setMessage({ type: "error", text: "Failed to remove account" })
    }
  }

  const addAlias = async (accountId) => {
    if (!newAlias.email) {
      setMessage({ type: "error", text: "Alias email is required" })
      return
    }
    
    setSaving(true)
    try {
      const token = sessionStorage.getItem("token")
      const response = await fetch(`${API_BASE_URL}/gmail/accounts/${accountId}/aliases`, {
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
        setMessage({ type: "error", text: error.detail || "Failed to add alias" })
      }
    } catch (error) {
      setMessage({ type: "error", text: "Failed to add alias" })
    } finally {
      setSaving(false)
    }
  }

  const removeAlias = async (accountId, aliasEmail) => {
    try {
      const token = sessionStorage.getItem("token")
      const response = await fetch(
        `${API_BASE_URL}/gmail/accounts/${accountId}/aliases/${encodeURIComponent(aliasEmail)}`,
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

  const syncAliases = async (accountId) => {
    setGmailLoading(true)
    try {
      const token = sessionStorage.getItem("token")
      const response = await fetch(`${API_BASE_URL}/gmail/accounts/${accountId}/aliases/sync`, {
        method: "POST",
        headers: { Authorization: token }
      })
      
      if (response.ok) {
        setMessage({ type: "success", text: "Aliases synced from Gmail" })
        loadGmailSettings()
      } else {
        setMessage({ type: "error", text: "Failed to sync aliases" })
      }
    } catch (error) {
      setMessage({ type: "error", text: "Failed to sync aliases" })
    } finally {
      setGmailLoading(false)
    }
  }

  const saveRateLimits = async () => {
    setSaving(true)
    setMessage({ type: "", text: "" })
    
    try {
      const token = sessionStorage.getItem("token")
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
        setMessage({ type: "error", text: error.detail || "Failed to save rate limits" })
      }
    } catch (error) {
      setMessage({ type: "error", text: "Failed to save rate limits" })
    } finally {
      setSaving(false)
    }
  }

  const setDefaultAccount = async (accountId) => {
    try {
      const token = sessionStorage.getItem("token")
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
          className={`tab-button ${activeTab === "gmail" ? "active" : ""}`}
          onClick={() => setActiveTab("gmail")}
        >
          <span className="tab-icon">📬</span>
          Gmail & Rate Limits
        </button>
      </div>

      <div className="settings-content">
        {activeTab === "app" && (
          <div className="settings-section">
            <h2>Application Configuration</h2>
            <p className="section-description">
              Configure API keys, database connections, and service credentials.
              Leave fields empty to keep existing values.
            </p>

            <div className="settings-group">
              <h3>️ Database Settings</h3>
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
                    {testingMongo ? "Testing..." : "Test Connection"}
                  </button>
                </div>
              </div>
            </div>

            <div className="settings-group">
              <h3> CPX Research Settings</h3>
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
                    {testingCpx ? "Testing..." : "Test Credentials"}
                  </button>
                </div>
              </div>
              <div className="setting-row">
                <label>API Timeout (seconds)</label>
                <input
                  type="number"
                  min="5"
                  max="120"
                  value={appSettings.cpx_api_timeout}
                  onChange={(e) => handleAppSettingChange("cpx_api_timeout", parseInt(e.target.value))}
                />
              </div>
            </div>

            {/* Survey Filter Settings - integrated into main settings */}
            <div className="settings-group">
              <h3>📋 Survey Filter Settings</h3>
              <p className="group-description">
                Configure filters for the Survey Pool. Surveys not meeting these criteria
                will be filtered out.
              </p>
              <div className="setting-row">
                <label>Max LOI (Length of Interview)</label>
                <div className="input-with-unit">
                  <input
                    type="number"
                    min="1"
                    max="120"
                    value={surveyFilters.max_loi}
                    onChange={(e) => handleFilterChange("max_loi", parseInt(e.target.value))}
                  />
                  <span className="unit">minutes</span>
                </div>
                <p className="setting-hint">Surveys with LOI greater than this will be excluded</p>
              </div>
              <div className="setting-row">
                <label>Min CPI (Cost Per Interview)</label>
                <div className="input-with-unit">
                  <input
                    type="number"
                    min="0.01"
                    max="100"
                    step="0.01"
                    value={surveyFilters.min_cpi}
                    onChange={(e) => handleFilterChange("min_cpi", parseFloat(e.target.value))}
                  />
                  <span className="unit">$ USD</span>
                </div>
                <p className="setting-hint">Surveys with payout less than this will be excluded</p>
              </div>
            </div>

            <div className="settings-group">
              <h3>🗑️ Cleanup Settings</h3>
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
                <p className="setting-hint">Surveys older than this will be automatically deleted</p>
              </div>
            </div>

            <div className="settings-group">
              <h3>🔄 Auto Refresh Settings</h3>
              <div className="setting-row checkbox-row">
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={surveyFilters.auto_refresh_enabled}
                    onChange={(e) => handleFilterChange("auto_refresh_enabled", e.target.checked)}
                  />
                  <span>Enable automatic survey refresh</span>
                </label>
              </div>
              <div className="setting-row">
                <label>Refresh Interval</label>
                <div className="input-with-unit">
                  <input
                    type="number"
                    min="30"
                    max="3600"
                    value={surveyFilters.refresh_interval_seconds}
                    onChange={(e) => handleFilterChange("refresh_interval_seconds", parseInt(e.target.value))}
                    disabled={!surveyFilters.auto_refresh_enabled}
                  />
                  <span className="unit">seconds</span>
                </div>
                <p className="setting-hint">How often to fetch new surveys from CPX API</p>
              </div>
            </div>

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

        {activeTab === "gmail" && (
          <div className="settings-section">
            <h2>Gmail Account & Rate Limit Settings</h2>
            <p className="section-description">
              Manage Gmail accounts, aliases, and email sending rate limits.
            </p>

            {gmailLoading ? (
              <div className="settings-loading-inline">
                <div className="spinner-small"></div>
                <span>Loading Gmail settings...</span>
              </div>
            ) : (
              <>
                {/* Gmail Accounts Section */}
                <div className="settings-group">
                  <div className="group-header">
                    <h3>📧 Gmail Accounts</h3>
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
                        <label>Display Name</label>
                        <input
                          type="text"
                          placeholder="John Doe"
                          value={newAccount.name}
                          onChange={(e) => setNewAccount(prev => ({ ...prev, name: e.target.value }))}
                        />
                      </div>
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
                      <div className="form-actions">
                        <button 
                          className="auth-button"
                          onClick={initiateGmailAuth}
                        >
                          🔐 Authenticate with Google
                        </button>
                        <button 
                          className="save-button-small"
                          onClick={addGmailAccount}
                          disabled={saving}
                        >
                          {saving ? "Adding..." : "Add Account"}
                        </button>
                      </div>
                    </div>
                  )}

                  {gmailAccounts.length === 0 ? (
                    <p className="empty-message">No Gmail accounts configured. Add one to get started.</p>
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
                                {account.is_authenticated ? "✓ Connected" : "⚠ Not Authenticated"}
                              </span>
                            </div>
                            <div className="account-actions">
                              {!account.is_authenticated && (
                                <button 
                                  className="action-button auth"
                                  onClick={() => authenticateAccount(account.id)}
                                  title="Authenticate with Google"
                                >
                                  🔐
                                </button>
                              )}
                              {!account.is_default && (
                                <button 
                                  className="action-button"
                                  onClick={() => setDefaultAccount(account.id)}
                                  title="Set as default"
                                >
                                  ⭐
                                </button>
                              )}
                              <button 
                                className="action-button sync"
                                onClick={() => syncAliases(account.id)}
                                title="Sync aliases from Gmail"
                              >
                                🔄
                              </button>
                              <button 
                                className="action-button delete"
                                onClick={() => removeGmailAccount(account.id)}
                                title="Remove account"
                              >
                                🗑️
                              </button>
                            </div>
                          </div>
                          
                          {/* Aliases Section */}
                          <div className="aliases-section">
                            <div className="aliases-header">
                              <span className="aliases-title">Aliases ({account.aliases?.length || 0})</span>
                              <button 
                                className="add-alias-button"
                                onClick={() => setShowAddAlias(showAddAlias === account.id ? null : account.id)}
                              >
                                {showAddAlias === account.id ? "Cancel" : "+ Add Alias"}
                              </button>
                            </div>
                            
                            {showAddAlias === account.id && (
                              <div className="add-alias-form">
                                <input
                                  type="email"
                                  placeholder="alias@example.com"
                                  value={newAlias.email}
                                  onChange={(e) => setNewAlias(prev => ({ ...prev, email: e.target.value }))}
                                />
                                <input
                                  type="text"
                                  placeholder="Display Name"
                                  value={newAlias.name}
                                  onChange={(e) => setNewAlias(prev => ({ ...prev, name: e.target.value }))}
                                />
                                <button 
                                  className="save-alias-button"
                                  onClick={() => addAlias(account.id)}
                                  disabled={saving}
                                >
                                  Add
                                </button>
                              </div>
                            )}
                            
                            {account.aliases && account.aliases.length > 0 ? (
                              <div className="aliases-list">
                                {account.aliases.map((alias, idx) => (
                                  <div key={idx} className="alias-item">
                                    <span className="alias-email">{alias.email}</span>
                                    {alias.name && <span className="alias-name">({alias.name})</span>}
                                    {alias.is_primary && <span className="primary-badge">Primary</span>}
                                    <button 
                                      className="remove-alias-button"
                                      onClick={() => removeAlias(account.id, alias.email)}
                                      title="Remove alias"
                                    >
                                      ×
                                    </button>
                                  </div>
                                ))}
                              </div>
                            ) : (
                              <p className="no-aliases">No aliases configured</p>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* Rate Limits Section */}
                <div className="settings-group">
                  <h3>⏱️ Email Rate Limits</h3>
                  <p className="group-description">
                    Control how many emails can be sent to prevent hitting Gmail's sending limits and improve deliverability.
                  </p>
                  
                  <div className="setting-row checkbox-row">
                    <label className="checkbox-label">
                      <input
                        type="checkbox"
                        checked={rateLimits.enabled}
                        onChange={(e) => handleRateLimitChange("enabled", e.target.checked)}
                      />
                      <span>Enable rate limiting</span>
                    </label>
                  </div>
                  
                  <div className="setting-row">
                    <label>Max Emails Per Day</label>
                    <div className="input-with-unit">
                      <input
                        type="number"
                        min="1"
                        max="2000"
                        value={rateLimits.max_per_day}
                        onChange={(e) => handleRateLimitChange("max_per_day", parseInt(e.target.value))}
                        disabled={!rateLimits.enabled}
                      />
                      <span className="unit">emails</span>
                    </div>
                    <p className="setting-hint">Gmail daily sending limit is 500 for regular accounts, 2000 for Workspace</p>
                  </div>
                  
                  <div className="setting-row">
                    <label>Max Emails Per Hour</label>
                    <div className="input-with-unit">
                      <input
                        type="number"
                        min="1"
                        max="500"
                        value={rateLimits.max_per_hour}
                        onChange={(e) => handleRateLimitChange("max_per_hour", parseInt(e.target.value))}
                        disabled={!rateLimits.enabled}
                      />
                      <span className="unit">emails</span>
                    </div>
                    <p className="setting-hint">Spread emails throughout the day for better deliverability</p>
                  </div>
                  
                  <div className="setting-row">
                    <label>Max Emails Per Minute</label>
                    <div className="input-with-unit">
                      <input
                        type="number"
                        min="1"
                        max="30"
                        value={rateLimits.max_per_minute}
                        onChange={(e) => handleRateLimitChange("max_per_minute", parseInt(e.target.value))}
                        disabled={!rateLimits.enabled}
                      />
                      <span className="unit">emails</span>
                    </div>
                    <p className="setting-hint">Prevents bursting too many emails at once</p>
                  </div>
                  
                  <div className="setting-row">
                    <label>Cooldown Between Emails</label>
                    <div className="input-with-unit">
                      <input
                        type="number"
                        min="0"
                        max="300"
                        value={rateLimits.cooldown_seconds}
                        onChange={(e) => handleRateLimitChange("cooldown_seconds", parseInt(e.target.value))}
                        disabled={!rateLimits.enabled}
                      />
                      <span className="unit">seconds</span>
                    </div>
                    <p className="setting-hint">Minimum delay between sending each email</p>
                  </div>
                </div>

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
      </div>
    </div>
  )
}

export default Settings
