"use client"

import { useState, useEffect } from "react"
import { API_BASE_URL } from "../config"
import "./Settings.css"

function Settings() {
  // App Settings state
  const [appSettings, setAppSettings] = useState({
    mailersend_api_key: "",
    sender_email: "",
    mongo_uri: "",
    session_secret: "",
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
  
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState({ type: "", text: "" })
  const [activeTab, setActiveTab] = useState("app") // "app" or "filters"
  const [testingMongo, setTestingMongo] = useState(false)
  const [testingCpx, setTestingCpx] = useState(false)

  useEffect(() => {
    loadAllSettings()
  }, [])

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
          Application Settings
        </button>
        <button 
          className={`tab-button ${activeTab === "filters" ? "active" : ""}`}
          onClick={() => setActiveTab("filters")}
        >
          <span className="tab-icon">🔍</span>
          Survey Filters
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
              <h3>📧 Email Settings</h3>
              <div className="setting-row">
                <label>MailerSend API Key</label>
                <input
                  type="password"
                  placeholder={maskedSettings.mailersend_api_key_masked || "Enter API key"}
                  value={appSettings.mailersend_api_key}
                  onChange={(e) => handleAppSettingChange("mailersend_api_key", e.target.value)}
                />
              </div>
              <div className="setting-row">
                <label>Sender Email</label>
                <input
                  type="email"
                  placeholder={maskedSettings.sender_email || "noreply@example.com"}
                  value={appSettings.sender_email}
                  onChange={(e) => handleAppSettingChange("sender_email", e.target.value)}
                />
              </div>
            </div>

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
                    {testingMongo ? "Testing..." : "Test Connection"}
                  </button>
                </div>
              </div>
            </div>

            <div className="settings-group">
              <h3>🔐 Security Settings</h3>
              <div className="setting-row">
                <label>Session Secret</label>
                <input
                  type="password"
                  placeholder={maskedSettings.session_secret_masked || "Enter session secret"}
                  value={appSettings.session_secret}
                  onChange={(e) => handleAppSettingChange("session_secret", e.target.value)}
                />
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

            <div className="settings-actions">
              <button 
                className="save-button"
                onClick={saveAppSettings}
                disabled={saving}
              >
                {saving ? "Saving..." : "Save Application Settings"}
              </button>
            </div>
          </div>
        )}

        {activeTab === "filters" && (
          <div className="settings-section">
            <h2>Survey Filter Settings</h2>
            <p className="section-description">
              Configure filters for the Survey Pool. Surveys not meeting these criteria
              will be filtered out.
            </p>

            <div className="settings-group">
              <h3>📋 Survey Criteria</h3>
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
                onClick={saveSurveyFilters}
                disabled={saving}
              >
                {saving ? "Saving..." : "Save Survey Filter Settings"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default Settings
