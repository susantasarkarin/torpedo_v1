"use client"

import { useState, useEffect } from "react"
import { API_BASE_URL, buildApiUrl } from "../config"
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
    openai_api_key: "",      // PRIMARY - pay-as-you-go
    openai_api_key_1: "",    // Pipeline keys (rotated)
    openai_api_key_2: "",
    openai_api_key_3: "",
    openai_api_key_4: "",
    openai_api_key_5: "",
    openai_api_key_6: "",
    openai_api_key_7: "",
    openai_api_key_8: "",
    openai_api_key_9: "",
    openai_api_key_10: "",
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
  const [segregationStats, setSegregationStats] = useState(null)
  const [segregationLoading, setSegregationLoading] = useState(false)
  const [segregateDialogOpen, setSegregateDialogOpen] = useState(false)
  const [segregateForm, setSegregateForm] = useState({
    strategy: 'category',
    batch_size: 100,
    force_rescan: false,
  })

  // Cost Analytics state
  const [costAnalytics, setCostAnalytics] = useState(null)
  const [costAnalyticsLoading, setCostAnalyticsLoading] = useState(false)
  const [costAnalyticsDays, setCostAnalyticsDays] = useState(7)

  // AI Prompts state
  const [aiPrompts, setAiPrompts] = useState([])
  const [aiPromptsLoading, setAiPromptsLoading] = useState(false)
  const [editingPrompt, setEditingPrompt] = useState(null)
  const [testPromptResult, setTestPromptResult] = useState(null)
  const [testingPrompt, setTestingPrompt] = useState(false)
  const [savingPrompt, setSavingPrompt] = useState(false)

  // AI Database state
  const [aiDatabaseStatus, setAiDatabaseStatus] = useState(null)
  const [aiDatabaseCompanies, setAiDatabaseCompanies] = useState([])
  const [aiDatabaseLoading, setAiDatabaseLoading] = useState(false)
  const [aiDatabaseRefilling, setAiDatabaseRefilling] = useState(false)
  const [aiDatabaseProcessing, setAiDatabaseProcessing] = useState(false)
  const [aiDatabaseIndustry, setAiDatabaseIndustry] = useState('')
  const [aiDatabaseDesignation, setAiDatabaseDesignation] = useState('')
  const [aiDatabaseLocation, setAiDatabaseLocation] = useState('')
  const [aiDatabaseCount, setAiDatabaseCount] = useState(20)
  const [aiDatabaseFilter, setAiDatabaseFilter] = useState('all')

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
      const response = await fetch(buildApiUrl(`/gmail-ws/signatures`), {
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
      const response = await fetch(buildApiUrl(`/gmail/rate-limits`), {
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
      const response = await fetch(buildApiUrl(`/gmail/rate-limits`), {
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

  // Load Email Signatures
  const loadEmailSignatures = async () => {
    setSignaturesLoading(true)
    try {
      const token = getAuthToken()

      // Load accounts and signatures in parallel for faster loading
      const needsAccounts = gmailAccounts.length === 0
      const requests = [
        fetch(buildApiUrl(`/settings/email-signatures`), { headers: { Authorization: token } })
      ]
      if (needsAccounts) {
        requests.unshift(fetch(buildApiUrl(`/gmail/accounts`), { headers: { Authorization: token } }))
      }

      const responses = await Promise.all(requests)

      if (needsAccounts) {
        const accountsRes = responses[0]
        const sigRes = responses[1]
        if (accountsRes.ok) {
          const data = await accountsRes.json()
          const accounts = (data.accounts || []).map(acc => ({
            id: acc._id || acc.email,
            email: acc.email,
            display_name: acc.display_name || acc.name,
          }))
          setGmailAccounts(accounts)
        }
        if (sigRes.ok) {
          const data = await sigRes.json()
          setEmailSignatures(data.signatures || [])
        }
      } else {
        const sigRes = responses[0]
        if (sigRes.ok) {
          const data = await sigRes.json()
          setEmailSignatures(data.signatures || [])
        }
      }
    } catch (error) {
      console.error("Error loading signatures:", error)
    } finally {
      setSignaturesLoading(false)
    }
  }

  // Load Cost Analytics
  const loadCostAnalytics = async () => {
    setCostAnalyticsLoading(true)
    try {
      const token = getAuthToken()
      const res = await fetch(buildApiUrl(`/settings/cost-analytics?days=${costAnalyticsDays}`), {
        headers: { Authorization: token }
      })
      if (res.ok) {
        const data = await res.json()
        setCostAnalytics(data)
      } else {
        console.error("Failed to load cost analytics:", res.status)
      }
    } catch (error) {
      console.error("Error loading cost analytics:", error)
    } finally {
      setCostAnalyticsLoading(false)
    }
  }

  // ============== AI PROMPTS FUNCTIONS ==============

  const loadAiPrompts = async () => {
    setAiPromptsLoading(true)
    try {
      const token = getAuthToken()
      const res = await fetch(buildApiUrl(`/settings/ai-prompts`), {
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
      const res = await fetch(buildApiUrl(`/settings/ai-prompts/${editingPrompt.prompt_key}`), {
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
      const res = await fetch(buildApiUrl(`/settings/ai-prompts/${editingPrompt.prompt_key}/test`), {
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

  const rollbackPrompt = async (promptKey, version) => {
    if (!confirm(`Rollback to version ${version}?`)) return
    try {
      const token = getAuthToken()
      const res = await fetch(buildApiUrl(`/settings/ai-prompts/${promptKey}/rollback/${version}`), {
        method: "POST",
        headers: { Authorization: token }
      })
      if (res.ok) {
        const data = await res.json()
        setMessage({ type: "success", text: data.message })
        loadAiPrompts()
        closePromptEditor()
      } else {
        const error = await res.json()
        setMessage({ type: "error", text: getErrorMessage(error) })
      }
    } catch (error) {
      setMessage({ type: "error", text: error.message })
    }
  }

  // ============== AI DATABASE FUNCTIONS ==============

  const loadAiDatabase = async () => {
    setAiDatabaseLoading(true)
    try {
      const token = getAuthToken()
      const filter = aiDatabaseFilter !== 'all' ? `?status=${aiDatabaseFilter}` : ''

      // Load status and companies in parallel for faster loading
      const [statusRes, companiesRes] = await Promise.all([
        fetch(buildApiUrl(`/leads/ai-database/status`), {
          headers: { Authorization: token }
        }),
        fetch(buildApiUrl(`/leads/ai-database/companies${filter}`), {
          headers: { Authorization: token }
        })
      ])

      if (statusRes.ok) {
        const status = await statusRes.json()
        setAiDatabaseStatus(status)
      }
      if (companiesRes.ok) {
        const data = await companiesRes.json()
        setAiDatabaseCompanies(data.companies || [])
      }
    } catch (error) {
      console.error("Error loading AI database:", error)
    } finally {
      setAiDatabaseLoading(false)
    }
  }

  const refillAiDatabase = async () => {
    if (!aiDatabaseDesignation.trim() || !aiDatabaseIndustry.trim()) {
      setMessage({ type: "error", text: "Please enter both designation and industry to discover leads" })
      return
    }
    setAiDatabaseRefilling(true)
    try {
      const token = getAuthToken()
      const res = await fetch(buildApiUrl(`/leads/ai-database/discover-leads`), {
        method: "POST",
        headers: {
          Authorization: token,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          designation: aiDatabaseDesignation.trim(),
          industry: aiDatabaseIndustry.trim(),
          location: aiDatabaseLocation.trim() || "USA",
          count: aiDatabaseCount || 20
        })
      })
      if (res.ok) {
        const data = await res.json()
        setMessage({ type: "success", text: `Discovered ${data.contacts_found} contacts, imported ${data.leads_imported} leads (est. cost: ${data.cost_estimate})` })
        setAiDatabaseDesignation('')
        setAiDatabaseIndustry('')
        setAiDatabaseLocation('')
        loadAiDatabase()
      } else {
        const error = await res.json()
        setMessage({ type: "error", text: getErrorMessage(error, "Failed to discover leads") })
      }
    } catch (error) {
      setMessage({ type: "error", text: error.message })
    } finally {
      setAiDatabaseRefilling(false)
    }
  }

  const processAiDatabaseBatch = async () => {
    setAiDatabaseProcessing(true)
    try {
      const token = getAuthToken()
      const res = await fetch(buildApiUrl(`/leads/ai-database/process-batch`), {
        method: "POST",
        headers: {
          Authorization: token,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ batch_size: 10 })
      })
      if (res.ok) {
        const data = await res.json()
        setMessage({
          type: "success",
          text: `Processed ${data.processed} companies: ${data.leads_found} leads found, ${data.enriched} enriched`
        })
        loadAiDatabase()
      } else {
        const error = await res.json()
        setMessage({ type: "error", text: getErrorMessage(error, "Failed to process batch") })
      }
    } catch (error) {
      setMessage({ type: "error", text: error.message })
    } finally {
      setAiDatabaseProcessing(false)
    }
  }

  const clearAiDatabase = async (status) => {
    if (!confirm(`Clear all ${status || 'all'} companies from the database?`)) return
    try {
      const token = getAuthToken()
      const url = status ? buildApiUrl(`/leads/ai-database/clear?status=${status}`) : buildApiUrl(`/leads/ai-database/clear`)
      const res = await fetch(url, {
        method: "DELETE",
        headers: { Authorization: token }
      })
      if (res.ok) {
        const data = await res.json()
        setMessage({ type: "success", text: data.message })
        loadAiDatabase()
      } else {
        const error = await res.json()
        setMessage({ type: "error", text: getErrorMessage(error) })
      }
    } catch (error) {
      setMessage({ type: "error", text: error.message })
    }
  }

  // Handle email account selection for signature editing
  const handleSignatureEmailChange = async (email) => {
    setSelectedSignatureEmail(email)
    if (!email) {
      setSignatureHtml("")
      setSignatureText("")
      return
    }

    // Find existing signature for this email
    const existing = emailSignatures.find(s => s.email === email)
    if (existing) {
      setSignatureHtml(existing.signature_html || "")
      setSignatureText(existing.signature_text || "")
    } else {
      // Fetch from API
      try {
        const token = getAuthToken()
        const res = await fetch(buildApiUrl(`/settings/email-signature/${encodeURIComponent(email)}`), {
          headers: { Authorization: token }
        })
        if (res.ok) {
          const data = await res.json()
          setSignatureHtml(data.signature || "")
          setSignatureText(data.signature_text || "")
        }
      } catch (e) {
        console.error("Error fetching signature:", e)
      }
    }
  }

  // Save signature
  const handleSaveSignature = async () => {
    if (!selectedSignatureEmail) return

    setSavingSignature(true)
    try {
      const token = getAuthToken()
      const res = await fetch(buildApiUrl(`/settings/email-signature/${encodeURIComponent(selectedSignatureEmail)}`), {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          Authorization: token
        },
        body: JSON.stringify({
          signature_html: signatureHtml,
          signature_text: signatureText
        })
      })

      if (res.ok) {
        setMessage({ type: "success", text: "Signature saved successfully!" })
        loadEmailSignatures() // Refresh list
      } else {
        const data = await res.json()
        setMessage({ type: "error", text: getErrorMessage(data, "Failed to save signature") })
      }
    } catch (e) {
      setMessage({ type: "error", text: "Failed to save signature: " + e.message })
    } finally {
      setSavingSignature(false)
    }
  }

  // Delete signature
  const handleDeleteSignature = async () => {
    if (!selectedSignatureEmail) return
    if (!confirm(`Delete signature for ${selectedSignatureEmail}?`)) return

    setSavingSignature(true)
    try {
      const token = getAuthToken()
      const res = await fetch(buildApiUrl(`/settings/email-signature/${encodeURIComponent(selectedSignatureEmail)}`), {
        method: "DELETE",
        headers: { Authorization: token }
      })

      if (res.ok) {
        setMessage({ type: "success", text: "Signature deleted!" })
        setSignatureHtml("")
        setSignatureText("")
        loadEmailSignatures()
      } else {
        const data = await res.json()
        setMessage({ type: "error", text: getErrorMessage(data, "Failed to delete signature") })
      }
    } catch (e) {
      setMessage({ type: "error", text: "Failed to delete signature: " + e.message })
    } finally {
      setSavingSignature(false)
    }
  }

  const loadGmailSettings = async (force = false) => {
    // Skip loading if syncs are active to prevent frontend slowdown
    // Allow force refresh when explicitly requested by user action
    if (!force && isSyncActive) {
      console.log("Skipping Gmail settings refresh - sync in progress")
      return
    }

    setGmailLoading(true)
    try {
      const token = getAuthToken()

      // Load Email/IMAP accounts from leads endpoint
      const accountsRes = await fetch(buildApiUrl(`/leads/gmail/accounts`), {
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
      const response = await fetch(buildApiUrl(`/gmail/idle/status`), {
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
      const response = await fetch(buildApiUrl(`${endpoint}`), {
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

      const response = await fetch(buildApiUrl(`/gmail/import/historical/${encodeURIComponent(email)}`), {
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
        const response = await fetch(buildApiUrl(`/gmail/import/progress/${encodeURIComponent(email)}`), {
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
      await fetch(buildApiUrl(`/gmail/imap-accounts/${encodeURIComponent(email)}/settings`), {
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
    setAllocationError(null)
    try {
      const token = getAuthToken()
      const response = await fetch(buildApiUrl(`/survey-allocation/settings`), {
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
      const response = await fetch(buildApiUrl(`/survey-allocation/settings`), {
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
        fetch(buildApiUrl(`/settings/app`), {
          headers: { Authorization: token }
        }),
        fetch(buildApiUrl(`/settings/survey-filters`), {
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

      const response = await fetch(buildApiUrl(`/settings/app`), {
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

      const response = await fetch(buildApiUrl(`/settings/survey-filters`), {
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

      // Save app settings and survey filters in parallel
      const [appResponse, filterResponse] = await Promise.all([
        fetch(buildApiUrl(`/settings/app`), {
          method: "POST",
          headers: { Authorization: token, "Content-Type": "application/json" },
          body: JSON.stringify(appSettings)
        }),
        fetch(buildApiUrl(`/settings/survey-filters`), {
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
      const response = await fetch(buildApiUrl(`/settings/test-mongo`), {
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
      const response = await fetch(buildApiUrl(`/settings/test-cpx`), {
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

  // Gmail account management functions
  const initiateGmailAuth = async () => {
    try {
      const token = getAuthToken()
      const response = await fetch(buildApiUrl(`/gmail/auth/url`), {
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
      const response = await fetch(buildApiUrl(`/gmail/auth/url?account_id=${accountId}`), {
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
      const response = await fetch(buildApiUrl(`/leads/gmail/accounts`), {
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
      const response = await fetch(buildApiUrl(`/leads/gmail/accounts/${encodeURIComponent(accountEmail)}`), {
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
      const response = await fetch(buildApiUrl(`/leads/gmail/accounts/${encodeURIComponent(accountEmail)}/test`), {
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

  // ============== MAIL OPERATIONS FUNCTIONS ==============

  const fetchSegregationStats = async () => {
    setSegregationLoading(true)
    try {
      const token = getAuthToken()
      const response = await fetch(buildApiUrl(`/api/mail/segregation-stats`), {
        headers: { Authorization: token }
      })
      if (response.ok) {
        const data = await response.json()
        setSegregationStats(data)
        setMessage({ type: "success", text: "Stats loaded successfully" })
      } else {
        setMessage({ type: "error", text: "Failed to fetch stats" })
      }
    } catch (error) {
      setMessage({ type: "error", text: "Error loading stats: " + error.message })
    } finally {
      setSegregationLoading(false)
    }
  }

  const handleSegregateEmails = async () => {
    setSaving(true)
    try {
      const token = getAuthToken()
      const response = await fetch(buildApiUrl(`/api/mail/segregate`), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: token
        },
        body: JSON.stringify(segregateForm)
      })

      if (response.ok) {
        const data = await response.json()
        setMessage({ type: "success", text: `Successfully segregated ${data.processed || 0} emails` })
        setSegregateDialogOpen(false)
        await fetchSegregationStats()
      } else {
        const error = await response.json()
        setMessage({ type: "error", text: getErrorMessage(error, "Failed to segregate emails") })
      }
    } catch (error) {
      setMessage({ type: "error", text: "Error: " + error.message })
    } finally {
      setSaving(false)
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
      const response = await fetch(buildApiUrl(`/leads/gmail/accounts/${encodeURIComponent(accountEmail)}/aliases`), {
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
        buildApiUrl(`/leads/gmail/accounts/${encodeURIComponent(accountEmail)}/aliases/${encodeURIComponent(aliasEmail)}`),
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
      const response = await fetch(buildApiUrl(`/leads/gmail/accounts/${encodeURIComponent(accountEmail)}/aliases/sync`), {
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
      const response = await fetch(buildApiUrl(`/gmail/rate-limits`), {
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
      const response = await fetch(buildApiUrl(`/gmail/accounts/${accountId}/set-default`), {
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
      const res = await fetch(`/api/sales-outreach/bu-configs`, { headers: buAuthHeaders() })
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
  const selectBuUnit = (unit) => {
    if (buDirty && !window.confirm("You have unsaved changes. Switch anyway?")) return
    setBuSelected(unit.slug)
    setBuContent(unit.content)
    setBuDirty(false)
    setShowBuNewForm(false)
  }
  const saveBuConfig = async () => {
    if (!buSelected) return
    setBuSaving(true)
    try {
      const res = await fetch(`/api/sales-outreach/bu-configs/${buSelected}`, {
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
    if (!window.confirm(`Delete "${buSelected}" permanently? This cannot be undone.`)) return
    setBuDeleting(true)
    try {
      const res = await fetch(`/api/sales-outreach/bu-configs/${buSelected}`, {
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
      const res = await fetch(`/api/sales-outreach/bu-configs`, {
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
                <p className="setting-hint" style={{ marginBottom: '1rem', padding: '0.75rem', background: '#f0fdf4', borderRadius: '6px', border: '1px solid #86efac' }}>
                  <strong>2-Provider Architecture:</strong> DeepSeek (PRIMARY - bulk tasks, $0.14/1M tokens) + OpenAI (PREMIUM - web search, tier 2)
                </p>
                <div className="setting-row">
                  <label>🚀 DeepSeek API Key (PRIMARY)</label>
                  <input
                    type="password"
                    placeholder={maskedSettings.deepseek_api_key_masked || "sk-..."}
                    value={appSettings.deepseek_api_key}
                    onChange={(e) => handleAppSettingChange("deepseek_api_key", e.target.value)}
                  />
                  <p className="setting-hint">
                    <strong>Primary provider</strong> for all bulk tasks. ~$0.14/1M tokens, 60 RPM (86,400/day).
                    Model: <code>deepseek-chat</code>. Get from <a href="https://platform.deepseek.com/" target="_blank" rel="noopener noreferrer">DeepSeek Platform</a>
                  </p>
                </div>
                <div className="setting-row">
                  <label>⭐ OpenAI API Key (PREMIUM)</label>
                  <input
                    type="password"
                    placeholder={maskedSettings.openai_api_key_masked || "sk-..."}
                    value={appSettings.openai_api_key}
                    onChange={(e) => handleAppSettingChange("openai_api_key", e.target.value)}
                  />
                  <p className="setting-hint">
                    For <strong>web search discovery</strong> and <strong>tier 2 analysis</strong>.
                    Models: <code>gpt-4o-mini</code> (default), <code>gpt-4o</code> (premium). Get from <a href="https://platform.openai.com/api-keys" target="_blank" rel="noopener noreferrer">OpenAI</a>
                  </p>
                </div>
                <div className="setting-row">
                  <label>� OpenAI Pipeline Keys (pay-as-you-go rotation)</label>
                  <p className="setting-hint" style={{ marginBottom: '0.75rem' }}>
                    Add up to 10 keys for pipeline rotation. Get from <a href="https://platform.openai.com/api-keys" target="_blank" rel="noopener noreferrer">OpenAI Platform</a>
                  </p>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '0.5rem' }}>
                    {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((num) => (
                      <div key={num} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <span style={{ minWidth: '20px', fontSize: '12px', color: '#6b7280' }}>#{num}</span>
                        <input
                          type="password"
                          placeholder={maskedSettings[`openai_api_key_${num}_masked`] || "sk-..."}
                          value={appSettings[`openai_api_key_${num}`] || ""}
                          onChange={(e) => handleAppSettingChange(`openai_api_key_${num}`, e.target.value)}
                          style={{ flex: 1 }}
                        />
                      </div>
                    ))}
                  </div>
                </div>
                <div style={{ marginTop: '1rem', padding: '0.75rem', background: '#f8fafc', borderRadius: '6px', fontSize: '13px' }}>
                  <strong>Task Routing (all OpenAI):</strong>
                  <ul style={{ margin: '0.5rem 0 0 1.5rem', padding: 0 }}>
                    <li>Email Classification → OpenAI gpt-4o-mini</li>
                    <li>Lead Classification → OpenAI gpt-4o-mini</li>
                    <li>Company Enrichment → OpenAI gpt-4o-mini</li>
                    <li>Email Drafting → OpenAI gpt-4o-mini</li>
                    <li>Web Search Discovery → OpenAI (with web_search tool)</li>
                  </ul>
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
                <h3>⏱️ Email Rate Limits {rateLimitsLoading && <span style={{ fontSize: '0.75rem', color: '#9ca3af', fontWeight: 400 }}>Loading...</span>}</h3>

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
                  {saving ? "Saving..." : "Save Rate Limits"}
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
                    {signaturesLoading ? "Loading..." : "🔄 Import from Gmail"}
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

            {allocationError && (
              <div className="settings-message error" style={{ marginBottom: '1rem' }}>
                ⚠ {allocationError}
                <button
                  onClick={loadAllocationSettings}
                  style={{ marginLeft: '1rem', background: 'none', border: '1px solid currentColor', padding: '2px 8px', borderRadius: '4px', cursor: 'pointer', fontSize: '0.85rem' }}
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
                {saving ? "Saving..." : "Save Allocation Settings"}
              </button>
            </div>
          </div>
        )}

        {activeTab === "ai-config" && (
          <div className="settings-section">
            <h2>AI Reference Material</h2>
            <p className="section-description">
              Business unit descriptions used by OpenAI for routing and email drafting.
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
                    {buLoading ? "Loading..." : "↻ Refresh"}
                  </button>
                  <button className="save-button-small" onClick={() => setShowBuNewForm(v => !v)}>
                    + New Business Unit
                  </button>
                </div>
              </div>

              {showBuNewForm && (
                <div style={{ padding: "1rem", backgroundColor: "#f9fafb", borderRadius: "8px", marginBottom: "1rem", border: "1px solid #e5e7eb" }}>
                  <div className="setting-row">
                    <label>Slug <small style={{ color: "#9ca3af", fontWeight: 400 }}>(lowercase, used as filename)</small></label>
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
                    <small style={{ color: "#6b7280", marginTop: "4px" }}>A template will be pre-filled — edit and save to activate.</small>
                  </div>
                </div>
              )}

              <div style={{ display: "flex", gap: 0, height: "520px", border: "1px solid #e5e7eb", borderRadius: "8px", overflow: "hidden" }}>
                {/* BU list sidebar */}
                <div style={{ width: "210px", borderRight: "1px solid #e5e7eb", overflowY: "auto", flexShrink: 0, backgroundColor: "#f9fafb" }}>
                  {buUnits.length === 0 && !buLoading && (
                    <p style={{ padding: "1rem", fontSize: "0.8rem", color: "#9ca3af", fontStyle: "italic" }}>No configs yet.<br />Create one above →</p>
                  )}
                  {buUnits.map(unit => (
                    <button
                      key={unit.slug}
                      onClick={() => selectBuUnit(unit)}
                      style={{
                        width: "100%",
                        padding: "0.75rem 1rem",
                        textAlign: "left",
                        background: buSelected === unit.slug ? "#eff6ff" : "transparent",
                        borderLeft: `3px solid ${buSelected === unit.slug ? "#4f46e5" : "transparent"}`,
                        border: "none",
                        borderBottom: "1px solid #f3f4f6",
                        cursor: "pointer",
                        fontSize: "0.875rem",
                        color: buSelected === unit.slug ? "#3730a3" : "#374151",
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
                          <span style={{ fontWeight: "600", fontSize: "0.9rem", color: "#111827" }}>
                            {buUnits.find(u => u.slug === buSelected)?.name || buSelected}
                          </span>
                          <span style={{ fontFamily: "monospace", fontSize: "0.75rem", background: "#e5e7eb", padding: "2px 8px", borderRadius: "4px", color: "#6b7280" }}>
                            {buSelected}.txt
                          </span>
                          {buDirty && (
                            <span style={{ fontSize: "0.75rem", color: "#d97706", fontWeight: "500" }}>● unsaved</span>
                          )}
                        </div>
                        <div style={{ display: "flex", gap: "0.5rem" }}>
                          <button
                            className="refresh-button"
                            onClick={deleteBuConfig}
                            disabled={buDeleting}
                            style={{ color: "#dc2626" }}
                          >
                            {buDeleting ? "Deleting..." : "Delete"}
                          </button>
                          <button
                            className="save-button-small"
                            onClick={saveBuConfig}
                            disabled={buSaving || !buDirty}
                          >
                            {buSaving ? "Saving..." : "Save"}
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
                          color: "#111827",
                          backgroundColor: "white",
                        }}
                      />
                    </>
                  ) : (
                    <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: "#9ca3af" }}>
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
                <p>Loading prompts...</p>
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
                    <div style={{ marginTop: '0.5rem', fontSize: '0.8rem', color: '#999' }}>
                      Version: {prompt.version} • Updated: {new Date(prompt.updated_at).toLocaleDateString()}
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
                        {savingPrompt ? "Saving..." : "💾 Save Changes"}
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

