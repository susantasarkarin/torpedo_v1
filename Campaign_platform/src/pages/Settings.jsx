"use client"

import { useState, useEffect } from "react"
import { API_BASE_URL, buildApiUrl } from "../config"
import { confirmAction } from "../utils/notify"
import { formatDate } from "../utils/format"
import { authFetch } from "../utils/api"
// Temporarily disabled for debugging
// import { useSyncStatus } from "../contexts/SyncStatusContext"
import "./Settings.css"

// Helper to get auth token - handles both storage methods
const getAuthToken = () => localStorage.getItem("session_id")

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
  // Global sync status - temporarily disabled for debugging
  // const { isSyncActive } = useSyncStatus()
  const isSyncActive = false; // Temporary fallback

  // App Settings state
  const [appSettings, setAppSettings] = useState({
    mongo_uri: "",
    cpx_app_id: "",
    cpx_ext_user_id: "",
    cpx_secure_hash_key: "",
    cpx_api_timeout: 30,
    anthropic_api_key: "",
    google_sheets_service_account: "",
  })
  const [maskedSettings, setMaskedSettings] = useState({})

  // Survey Filter state
  const [surveyFilters, setSurveyFilters] = useState({
    max_loi: 20,
    min_cpi: 1.0,
    min_incidence: 60,
    deletion_period_days: 7,
    auto_refresh_enabled: true,
    refresh_interval_seconds: 60,
  })

  // Gmail Settings state - Rate Limits for outgoing emails
  const [rateLimits, setRateLimits] = useState({
    max_per_day: 500,
    max_per_hour: 50,
    max_per_minute: 5,
    cooldown_seconds: 10,
    enabled: true,
  })

  // Gmail Workspace Signatures
  const [workspaceSignatures, setWorkspaceSignatures] = useState([])
  const [signaturesLoading, setSignaturesLoading] = useState(false)

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

  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState({ type: "", text: "" })
  const [activeTab, setActiveTab] = useState("app") // "app", "allocation", "ai-config"
  const [testingMongo, setTestingMongo] = useState(false)
  const [testingCpx, setTestingCpx] = useState(false)
  const [rateLimitsLoading, setRateLimitsLoading] = useState(true)
  const [allocationError, setAllocationError] = useState(null)

  // Mail Operations state

  // Cost Analytics state

  // AI Prompts state
  const [aiPrompts, setAiPrompts] = useState([])
  const [aiPromptsLoading, setAiPromptsLoading] = useState(false)
  const [editingPrompt, setEditingPrompt] = useState(null)
  const [testPromptResult, setTestPromptResult] = useState(null)
  const [testingPrompt, setTestingPrompt] = useState(false)
  const [savingPrompt, setSavingPrompt] = useState(false)

  // AI Database state

  // AI Config (Business Unit) state
  const [buUnits, setBuUnits] = useState([])
  const [buSelected, setBuSelected] = useState(null)
  const [buContent, setBuContent] = useState("")
  const [buLoading, setBuLoading] = useState(false)
  const [buSaving, setBuSaving] = useState(false)
  const [buDeleting, setBuDeleting] = useState(false)
  const [buDirty, setBuDirty] = useState(false)
  const [buToast, setBuToast] = useState(null)
  const [showBuNewForm, setShowBuNewForm] = useState(false)
  const [newBuSlug, setNewBuSlug] = useState("")

  useEffect(() => {
    loadAllSettings()
  }, [])

  useEffect(() => {
    if (activeTab === "allocation") {
      loadAllocationSettings()
    }
    if (activeTab === "ai-config") {
      loadBuConfigs()
    }
  }, [activeTab])

  // Load Gmail Workspace Signatures
  const loadWorkspaceSignatures = async () => {
    setSignaturesLoading(true)
    try {
      const token = getAuthToken()
      const response = await authFetch(buildApiUrl(`/gmail-ws/signatures`), {
        headers: { Authorization: token }
      })
      if (response.ok) {
        const data = await response.json()
        setWorkspaceSignatures(data.signatures || [])
      }
    } catch (error) {
      console.error("Error loading workspace signatures:", error)
    } finally {
      setSignaturesLoading(false)
    }
  }

  // Load Rate Limits
  const loadRateLimits = async () => {
    setRateLimitsLoading(true)
    try {
      const token = getAuthToken()
      const response = await authFetch(buildApiUrl(`/gmail/rate-limits`), {
        headers: { Authorization: token }
      })
      if (response.ok) {
        const data = await response.json()
        if (data.rate_limits) {
          setRateLimits(data.rate_limits)
        }
      }
    } catch (error) {
      console.error("Error loading rate limits:", error)
    } finally {
      setRateLimitsLoading(false)
    }
  }

  // Save Rate Limits
  const saveRateLimitsHandler = async () => {
    setSaving(true)
    setMessage({ type: "", text: "" })

    try {
      const token = getAuthToken()
      const response = await authFetch(buildApiUrl(`/gmail/rate-limits`), {
        method: "POST",
        headers: {
          Authorization: token,
          "Content-Type": "application/json"
        },
        body: JSON.stringify(rateLimits)
      })

      if (response.ok) {
        setMessage({ type: "success", text: "Rate limits saved!" })
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

  // Handle rate limit change
  const handleRateLimitChange = (key, value) => {
    setRateLimits(prev => ({ ...prev, [key]: value }))
  }



  // ============== AI PROMPTS FUNCTIONS ==============

  const loadAiPrompts = async () => {
    setAiPromptsLoading(true)
    try {
      const token = getAuthToken()
      const res = await authFetch(buildApiUrl(`/settings/ai-prompts`), {
        headers: { Authorization: token }
      })
      if (res.ok) {
        const data = await res.json()
        setAiPrompts(data.prompts || [])
      } else {
        console.error("Failed to load AI prompts:", res.status)
      }
    } catch (error) {
      console.error("Error loading AI prompts:", error)
    } finally {
      setAiPromptsLoading(false)
    }
  }

  const openPromptEditor = (prompt) => {
    setEditingPrompt({ ...prompt })
    setTestPromptResult(null)
  }

  const closePromptEditor = () => {
    setEditingPrompt(null)
    setTestPromptResult(null)
  }

  const handlePromptChange = (field, value) => {
    setEditingPrompt(prev => ({ ...prev, [field]: value }))
  }

  const savePrompt = async () => {
    if (!editingPrompt) return
    setSavingPrompt(true)
    try {
      const token = getAuthToken()
      const res = await authFetch(buildApiUrl(`/settings/ai-prompts/${editingPrompt.prompt_key}`), {
        method: "PUT",
        headers: {
          Authorization: token,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          system_prompt: editingPrompt.system_prompt,
          user_prompt_template: editingPrompt.user_prompt_template,
          name: editingPrompt.name,
          description: editingPrompt.description
        })
      })
      if (res.ok) {
        const data = await res.json()
        setMessage({ type: "success", text: `Prompt saved as version ${data.version}` })
        loadAiPrompts()
        closePromptEditor()
      } else {
        const error = await res.json()
        setMessage({ type: "error", text: getErrorMessage(error, "Failed to save prompt") })
      }
    } catch (error) {
      setMessage({ type: "error", text: error.message })
    } finally {
      setSavingPrompt(false)
    }
  }

  const testPrompt = async () => {
    if (!editingPrompt) return
    setTestingPrompt(true)
    setTestPromptResult(null)
    try {
      const token = getAuthToken()
      const res = await authFetch(buildApiUrl(`/settings/ai-prompts/${editingPrompt.prompt_key}/test`), {
        method: "POST",
        headers: {
          Authorization: token,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          system_prompt: editingPrompt.system_prompt,
          user_prompt_template: editingPrompt.user_prompt_template
        })
      })
      if (res.ok) {
        const data = await res.json()
        setTestPromptResult(data)
      } else {
        const error = await res.json()
        setTestPromptResult({ success: false, error: getErrorMessage(error) })
      }
    } catch (error) {
      setTestPromptResult({ success: false, error: error.message })
    } finally {
      setTestingPrompt(false)
    }
  }


  // ============== AI DATABASE FUNCTIONS ==============














  const loadAllocationSettings = async () => {
    setAllocationError(null)
    try {
      const token = getAuthToken()
      const response = await authFetch(buildApiUrl(`/survey-allocation/settings`), {
        headers: { Authorization: token }
      })
      if (response.ok) {
        const contentType = response.headers.get("content-type") || ""
        if (!contentType.includes("application/json")) {
          setAllocationError("Server returned an unexpected response. The survey allocation API may be unavailable.")
          return
        }
        const data = await response.json()
        setAllocationSettings(prev => ({ ...prev, ...data.settings }))
      } else {
        setAllocationError(`Failed to load allocation settings (HTTP ${response.status})`)
      }
    } catch (error) {
      console.error("Error loading allocation settings:", error)
      setAllocationError("Failed to load allocation settings. Check your connection.")
    }
  }

  const saveAllocationSettings = async () => {
    setSaving(true)
    setMessage({ type: "", text: "" })

    try {
      const token = getAuthToken()
      const response = await authFetch(buildApiUrl(`/survey-allocation/settings`), {
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
    setLoading(false) // Show page immediately with defaults; update when data arrives
    try {
      const token = getAuthToken()

      // Load app settings, survey filters, and rate limits in parallel
      const [appRes, filterRes] = await Promise.all([
        authFetch(buildApiUrl(`/settings/app`), {
          headers: { Authorization: token }
        }),
        authFetch(buildApiUrl(`/settings/survey-filters`), {
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

      // Load rate limits separately (non-blocking)
      loadRateLimits()
    } catch (error) {
      console.error("Error loading settings:", error)
      setMessage({ type: "error", text: "Failed to load settings" })
    }
  }



  // Combined save function for merged settings page
  const saveAllSettings = async () => {
    setSaving(true)
    setMessage({ type: "", text: "" })

    try {
      const token = getAuthToken()

      // Save app settings and survey filters in parallel
      const [appResponse, filterResponse] = await Promise.all([
        authFetch(buildApiUrl(`/settings/app`), {
          method: "POST",
          headers: { Authorization: token, "Content-Type": "application/json" },
          body: JSON.stringify(appSettings)
        }),
        authFetch(buildApiUrl(`/settings/survey-filters`), {
          method: "POST",
          headers: { Authorization: token, "Content-Type": "application/json" },
          body: JSON.stringify(surveyFilters)
        })
      ])

      const errors = []
      if (!appResponse.ok) {
        const err = await appResponse.json().catch(() => ({}))
        errors.push(getErrorMessage(err, "Failed to save application settings"))
      }
      if (!filterResponse.ok) {
        const err = await filterResponse.json().catch(() => ({}))
        errors.push(getErrorMessage(err, "Failed to save filter settings"))
      }

      if (errors.length > 0) {
        setMessage({ type: "error", text: errors.join(" | ") })
      } else {
        setMessage({ type: "success", text: "All settings saved successfully!" })
        loadAllSettings() // Reload to get updated masked values
      }
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
      const response = await authFetch(buildApiUrl(`/settings/test-mongo`), {
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
      const response = await authFetch(buildApiUrl(`/settings/test-cpx`), {
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






  // ============== MAIL OPERATIONS FUNCTIONS ==============








  if (loading) {
    return (
      <div className="settings-loading">
        <div className="spinner"></div>
        <p>Loading settings…</p>
      </div>
    )
  }

  // ── BU Config (AI Config) functions ──
  const buAuthHeaders = () => {
    const t = getAuthToken()
    return t ? { Authorization: t } : {}
  }
  const showBuToast = (type, msg) => {
    setBuToast({ type, msg })
    setTimeout(() => setBuToast(null), 3500)
  }
  const loadBuConfigs = async () => {
    setBuLoading(true)
    try {
      const res = await authFetch(`/api/sales-outreach/bu-configs`, { headers: buAuthHeaders() })
      if (!res.ok) throw new Error("Failed to load")
      const data = await res.json()
      const units = data.business_units || []
      setBuUnits(units)
      setBuSelected(prev => {
        if (prev) return prev
        if (units.length) { setBuContent(units[0].content); return units[0].slug }
        return null
      })
    } catch {
      showBuToast("error", "Could not load business unit configs")
    } finally {
      setBuLoading(false)
    }
  }
  const selectBuUnit = async (unit) => {
    if (buDirty && !(await confirmAction("You have unsaved changes. Switch anyway?"))) return
    setBuSelected(unit.slug)
    setBuContent(unit.content)
    setBuDirty(false)
    setShowBuNewForm(false)
  }
  const saveBuConfig = async () => {
    if (!buSelected) return
    setBuSaving(true)
    try {
      const res = await authFetch(`/api/sales-outreach/bu-configs/${buSelected}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", ...buAuthHeaders() },
        body: JSON.stringify({ content: buContent }),
      })
      if (!res.ok) throw new Error("Save failed")
      setBuDirty(false)
      setBuUnits(prev => prev.map(u => u.slug === buSelected ? { ...u, content: buContent } : u))
      showBuToast("success", "Business unit config saved")
    } catch {
      showBuToast("error", "Failed to save — check your connection")
    } finally {
      setBuSaving(false)
    }
  }
  const deleteBuConfig = async () => {
    if (!buSelected) return
    if (!(await confirmAction(`Delete "${buSelected}" permanently? This cannot be undone.`))) return
    setBuDeleting(true)
    try {
      const res = await authFetch(`/api/sales-outreach/bu-configs/${buSelected}`, {
        method: "DELETE",
        headers: buAuthHeaders(),
      })
      if (!res.ok) throw new Error("Delete failed")
      showBuToast("success", "Business unit deleted")
      setBuSelected(null)
      setBuContent("")
      setBuDirty(false)
      await loadBuConfigs()
    } catch {
      showBuToast("error", "Failed to delete")
    } finally {
      setBuDeleting(false)
    }
  }
  const createBuConfig = async () => {
    const slug = newBuSlug.trim().toLowerCase().replace(/[^a-z0-9_]/g, "_")
    if (!slug) return showBuToast("error", "Slug cannot be empty")
    const template = `BUSINESS UNIT: [Name] — [Tagline]\nSLUG: ${slug}\n\nDESCRIPTION:\n[What this business unit does — 2-3 sentences]\n\nCORE CAPABILITIES:\n- [Capability 1]\n- [Capability 2]\n\nIDEAL CUSTOMER PROFILE:\n- [Target role/company 1]\n\nPAIN POINTS WE SOLVE:\n- [Pain point 1]\n\nVALUE PROPOSITION:\n[Why leads should care]\n\nSENDER: [Full Name], [Title], [BU Name]`
    try {
      const res = await authFetch(`/api/sales-outreach/bu-configs`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...buAuthHeaders() },
        body: JSON.stringify({ slug, content: template }),
      })
      if (res.status === 409) return showBuToast("error", `"${slug}" already exists`)
      if (!res.ok) throw new Error("Create failed")
      setNewBuSlug("")
      setShowBuNewForm(false)
      await loadBuConfigs()
      setBuSelected(slug)
      setBuContent(template)
      setBuDirty(false)
      showBuToast("success", `Created "${slug}" — edit and save below`)
    } catch {
      showBuToast("error", "Failed to create business unit")
    }
  }

  return (
    <div className="settings-container">
      <div className="settings-header">
        <h1 className="cx-page-title">Settings</h1>
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
          className={`tab-button ${activeTab === "ai-config" ? "active" : ""}`}
          onClick={() => setActiveTab("ai-config")}
        >
          <span className="tab-icon">🧠</span>
          AI Config
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
                  <label>Anthropic API Key</label>
                  <input
                    type="password"
                    placeholder={maskedSettings.anthropic_api_key_masked || "sk-ant-..."}
                    value={appSettings.anthropic_api_key}
                    onChange={(e) => handleAppSettingChange("anthropic_api_key", e.target.value)}
                  />
                  <p className="setting-hint">
                    Claude key used for lead extraction and AI workflows.
                    Get it from <a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noopener noreferrer">Anthropic Console</a>.
                  </p>
                </div>
              </div>

              {/* Survey Filter Settings */}
              <div className="settings-group">
                <h3>📋 Survey Filters</h3>
                <div className="setting-row">
                  <label>Max LOI / Min CPI / Min Incidence</label>
                  <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
                    <div className="input-with-unit">
                      <input
                        type="number"
                        min="1"
                        max="120"
                        value={surveyFilters.max_loi}
                        onChange={(e) => handleFilterChange("max_loi", parseInt(e.target.value))}
                      />
                      <span className="unit">min LOI</span>
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
                    <div className="input-with-unit">
                      <input
                        type="number"
                        min="0"
                        max="100"
                        value={surveyFilters.min_incidence}
                        onChange={(e) => handleFilterChange("min_incidence", parseInt(e.target.value))}
                      />
                      <span className="unit">% IR</span>
                    </div>
                  </div>
                  <p className="setting-hint">Filter surveys: Max LOI (minutes), Min Payout ($), Min Incidence Rate (%)</p>
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

              {/* Email Rate Limits Section */}
              <div className="settings-group">
                <h3>⏱️ Email Rate Limits {rateLimitsLoading && <span style={{ fontSize: '0.875rem', color: '#6b6b6b', fontWeight: 400 }}>Loading…</span>}</h3>

                <div className="setting-row" style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                  <input
                    type="checkbox"
                    checked={rateLimits.enabled}
                    onChange={(e) => handleRateLimitChange("enabled", e.target.checked)}
                    style={{ width: '18px', height: '18px' }}
                    disabled={rateLimitsLoading}
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

                <button
                  className="save-button-small"
                  onClick={saveRateLimitsHandler}
                  disabled={saving}
                  style={{ marginTop: '0.5rem' }}
                >
                  {saving ? "Saving…" : "Save Rate Limits"}
                </button>
              </div>

              {/* Email Signatures Section */}
              <div className="settings-group">
                <div className="group-header">
                  <h3>✉️ Email Signatures</h3>
                  <button
                    className="refresh-button"
                    onClick={loadWorkspaceSignatures}
                    disabled={signaturesLoading}
                  >
                    {signaturesLoading ? "Loading…" : "🔄 Import from Gmail"}
                  </button>
                </div>

                {workspaceSignatures.length === 0 ? (
                  <p className="no-data-message">
                    Click "Import from Gmail" to fetch signatures from your Gmail Workspace mailboxes.
                  </p>
                ) : (
                  <div className="signatures-list">
                    {workspaceSignatures.map((sig, idx) => (
                      <div key={idx} className="signature-item">
                        <div className="signature-header">
                          <strong>{sig.email}</strong>
                          {sig.is_primary && <span className="badge primary">Primary</span>}
                          {sig.display_name && <span className="signature-name">{sig.display_name}</span>}
                        </div>
                        {sig.signature_html ? (
                          <div
                            className="signature-preview"
                            dangerouslySetInnerHTML={{ __html: sig.signature_html }}
                          />
                        ) : (
                          <p className="no-signature">No signature configured</p>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>

            </div>{/* End settings-grid */}

            <div className="settings-actions">
              <button
                className="save-button"
                onClick={saveAllSettings}
                disabled={saving}
              >
                {saving ? "Saving…" : "Save All Settings"}
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

            {allocationError && (
              <div className="settings-message error" style={{ marginBottom: '1rem' }}>
                ⚠ {allocationError}
                <button
                  onClick={loadAllocationSettings}
                  style={{ marginLeft: '1rem', background: 'none', border: '1px solid currentColor', padding: '2px 8px', borderRadius: '4px', cursor: 'pointer', fontSize: '0.875rem' }}
                >
                  Retry
                </button>
              </div>
            )}

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
                {saving ? "Saving…" : "Save Allocation Settings"}
              </button>
            </div>
          </div>
        )}

        {activeTab === "ai-config" && (
          <div className="settings-section">
            <h2>AI Reference Material</h2>
            <p className="section-description">
              Business unit descriptions used by Claude for routing and email drafting.
              The AI picks the best-fit BU and writes a gap analysis, then drafts the personalised outreach email using the chosen BU file.
            </p>

            {buToast && (
              <div className={`settings-message ${buToast.type === "success" ? "success" : "error"}`}>
                {buToast.type === "success" ? "✓" : "⚠"} {buToast.msg}
              </div>
            )}

            <div className="settings-group">
              <div className="group-header">
                <h3>Business Units</h3>
                <div style={{ display: "flex", gap: "0.5rem" }}>
                  <button className="refresh-button" onClick={loadBuConfigs} disabled={buLoading}>
                    {buLoading ? "Loading…" : "↻ Refresh"}
                  </button>
                  <button className="save-button-small" onClick={() => setShowBuNewForm(v => !v)}>
                    + New Business Unit
                  </button>
                </div>
              </div>

              {showBuNewForm && (
                <div style={{ padding: "1rem", backgroundColor: "#f9fafb", borderRadius: "8px", marginBottom: "1rem", border: "1px solid #e5e7eb" }}>
                  <div className="setting-row">
                    <label>Slug <small style={{ color: "#6b6b6b", fontWeight: 400 }}>(lowercase, used as filename)</small></label>
                    <div style={{ display: "flex", gap: "0.75rem", alignItems: "center" }}>
                      <input
                        type="text"
                        value={newBuSlug}
                        onChange={e => setNewBuSlug(e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "_"))}
                        placeholder="e.g. data_quality"
                        style={{ maxWidth: "260px" }}
                      />
                      <button className="save-button-small" onClick={createBuConfig} disabled={!newBuSlug.trim()}>Create</button>
                      <button className="refresh-button" onClick={() => setShowBuNewForm(false)}>Cancel</button>
                    </div>
                    <small style={{ color: "#4b5563", marginTop: "4px" }}>A template will be pre-filled — edit and save to activate.</small>
                  </div>
                </div>
              )}

              <div style={{ display: "flex", gap: 0, height: "520px", border: "1px solid #e5e7eb", borderRadius: "8px", overflow: "hidden" }}>
                {/* BU list sidebar */}
                <div style={{ width: "210px", borderRight: "1px solid #e5e7eb", overflowY: "auto", flexShrink: 0, backgroundColor: "#f9fafb" }}>
                  {buUnits.length === 0 && !buLoading && (
                    <p style={{ padding: "1rem", fontSize: "0.875rem", color: "#6b6b6b", fontStyle: "italic" }}>No configs yet.<br />Create one above →</p>
                  )}
                  {buUnits.map(unit => (
                    <button
                      key={unit.slug}
                      onClick={() => selectBuUnit(unit)}
                      style={{
                        width: "100%",
                        padding: "0.75rem 1rem",
                        textAlign: "left",
                        background: buSelected === unit.slug ? "#fff7ed" : "transparent",
                        borderLeft: `3px solid ${buSelected === unit.slug ? "#e8890b" : "transparent"}`,
                        border: "none",
                        borderBottom: "1px solid #f3f4f6",
                        cursor: "pointer",
                        fontSize: "0.875rem",
                        color: buSelected === unit.slug ? "#c47209" : "#4a4a4a",
                        fontWeight: buSelected === unit.slug ? "600" : "400",
                        transition: "all 0.15s",
                      }}
                    >
                      {unit.name || unit.slug}
                    </button>
                  ))}
                </div>

                {/* Editor area */}
                <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
                  {buSelected ? (
                    <>
                      {/* Toolbar */}
                      <div style={{ padding: "0.625rem 1rem", borderBottom: "1px solid #e5e7eb", display: "flex", alignItems: "center", justifyContent: "space-between", backgroundColor: "#f9fafb" }}>
                        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
                          <span style={{ fontWeight: "600", fontSize: "0.9rem", color: "#1a1a1a" }}>
                            {buUnits.find(u => u.slug === buSelected)?.name || buSelected}
                          </span>
                          <span style={{ fontFamily: "monospace", fontSize: "0.875rem", background: "#e5e7eb", padding: "2px 8px", borderRadius: "4px", color: "#4b5563" }}>
                            {buSelected}.txt
                          </span>
                          {buDirty && (
                            <span style={{ fontSize: "0.875rem", color: "#d97706", fontWeight: "500" }}>● unsaved</span>
                          )}
                        </div>
                        <div style={{ display: "flex", gap: "0.5rem" }}>
                          <button
                            className="refresh-button"
                            onClick={deleteBuConfig}
                            disabled={buDeleting}
                            style={{ color: "#dc2626" }}
                          >
                            {buDeleting ? "Deleting…" : "Delete"}
                          </button>
                          <button
                            className="save-button-small"
                            onClick={saveBuConfig}
                            disabled={buSaving || !buDirty}
                          >
                            {buSaving ? "Saving…" : "Save"}
                          </button>
                        </div>
                      </div>
                      {/* Textarea */}
                      <textarea
                        value={buContent}
                        onChange={e => { setBuContent(e.target.value); setBuDirty(true) }}
                        style={{
                          flex: 1,
                          resize: "none",
                          border: "none",
                          outline: "none",
                          padding: "1rem",
                          fontFamily: "monospace",
                          fontSize: "0.875rem",
                          lineHeight: "1.7",
                          color: "#1a1a1a",
                          backgroundColor: "white",
                        }}
                      />
                    </>
                  ) : (
                    <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: "#6b6b6b" }}>
                      <p>Select a business unit from the left to edit</p>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}

        {activeTab === "ai-prompts" && (
          <div className="settings-section">
            <h2>🤖 AI Prompt Management</h2>
            <p className="section-description">
              Customize system prompts for various AI agents
            </p>

            <div className="settings-grid">
              {aiPromptsLoading ? (
                <p>Loading prompts…</p>
              ) : aiPrompts.length === 0 ? (
                <p>No prompts found. Create one using the backend API or initialize defaults.</p>
              ) : (
                aiPrompts.map(prompt => (
                  <div key={prompt.id} className="settings-group">
                    <div className="group-header" style={{ marginBottom: '1rem' }}>
                      <h3>{prompt.name}</h3>
                      <button
                        className="save-button-small"
                        onClick={() => openPromptEditor(prompt)}
                      >
                        Edit Prompt
                      </button>
                    </div>
                    <p style={{ marginBottom: '0.5rem' }}><strong>Agent:</strong> {prompt.agent_type}</p>
                    <p style={{ color: '#666', fontSize: '0.9rem' }}>{prompt.description}</p>
                    <div style={{ marginTop: '0.5rem', fontSize: '0.875rem', color: '#6b6b6b' }}>
                      Version: {prompt.version} • Updated: {formatDate(prompt.updated_at)}
                    </div>
                  </div>
                ))
              )}
            </div>

            {editingPrompt && (
              <div className="settings-modal-overlay">
                <div className="settings-modal">
                  <h3>Edit Prompt: {editingPrompt.name}</h3>

                  <div className="setting-row">
                    <label>Description</label>
                    <input
                      type="text"
                      value={editingPrompt.description}
                      onChange={e => handlePromptChange('description', e.target.value)}
                    />
                  </div>

                  <div className="setting-row">
                    <label>System Prompt / Content</label>
                    <textarea
                      rows={15}
                      value={editingPrompt.content}
                      onChange={e => handlePromptChange('content', e.target.value)}
                      style={{ fontFamily: 'monospace', fontSize: '0.9rem', width: '100%' }}
                    />
                  </div>

                  <div className="settings-actions" style={{ justifyContent: 'space-between' }}>
                    <button className="refresh-button" onClick={closePromptEditor}>Cancel</button>
                    <div style={{ display: 'flex', gap: '1rem' }}>
                      <button className="save-button" onClick={testPrompt} style={{ backgroundColor: '#8b5cf6' }}>
                        {testingPrompt ? "Testing..." : "🧪 Test Prompt"}
                      </button>
                      <button className="save-button" onClick={savePrompt} disabled={savingPrompt}>
                        {savingPrompt ? "Saving…" : "💾 Save Changes"}
                      </button>
                    </div>
                  </div>

                  {testPromptResult && (
                    <div style={{ marginTop: '1rem', padding: '1rem', background: '#f8f9fa', borderRadius: '4px', maxHeight: '200px', overflow: 'auto' }}>
                      <strong>Test Result:</strong>
                      <pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(testPromptResult, null, 2)}</pre>
                    </div>
                  )}

                </div>
              </div>
            )}

          </div>
        )}
      </div>
    </div>
  )
}

export default Settings

