"use client"

import { useState, useEffect, useRef } from "react"
import { useNavigate } from "react-router-dom"
import { API_BASE_URL, buildApiUrl } from "../config"
import "./AIDatabase.css"
import Papa from "papaparse"

// Helper to get auth token
const getAuthToken = () => localStorage.getItem("session_id")

// Helper to extract error message
const getErrorMessage = (error, fallback = "An error occurred") => {
  if (!error) return fallback
  if (typeof error === "string") return error
  if (error.detail) {
    if (typeof error.detail === "string") return error.detail
    if (Array.isArray(error.detail)) {
      return error.detail.map(e => e.msg || e.message || JSON.stringify(e)).join(", ")
    }
  }
  if (error.message) return error.message
  return fallback
}

// Database fields for CSV mapping
const DB_FIELDS = [
  { key: "email", label: "Email", required: true },
  { key: "full_name", label: "Full Name" },
  { key: "first_name", label: "First Name" },
  { key: "last_name", label: "Last Name" },
  { key: "company_name", label: "Company Name" },
  { key: "job_title", label: "Job Title" },
  { key: "phone", label: "Phone" },
  { key: "linkedin_url", label: "LinkedIn URL" },
  { key: "website", label: "Website" },
  { key: "industry", label: "Industry" },
  { key: "country", label: "Country" },
  { key: "city", label: "City" }
]

// Column aliases for auto-matching
const COLUMN_ALIASES = {
  email: ["email", "email_address", "e-mail", "mail", "email address"],
  full_name: ["full_name", "fullname", "name", "full name", "contact_name", "contact name"],
  first_name: ["first_name", "firstname", "first", "first name", "given_name"],
  last_name: ["last_name", "lastname", "last", "last name", "surname", "family_name"],
  company_name: ["company", "company_name", "organization", "org", "company name", "employer"],
  job_title: ["title", "job_title", "position", "role", "job title", "designation"],
  phone: ["phone", "telephone", "mobile", "cell", "phone_number", "phone number"],
  linkedin_url: ["linkedin", "linkedin_url", "linkedin url", "linkedin_profile"],
  website: ["website", "url", "web", "site", "company_website"],
  industry: ["industry", "sector", "vertical"],
  country: ["country", "nation", "location_country"],
  city: ["city", "location", "location_city"]
}

function AIDatabase() {
  const navigate = useNavigate()
  
  // State
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState({ type: "", text: "" })
  const [activeTab, setActiveTab] = useState("all") // all, recents, favorites
  const [searchQuery, setSearchQuery] = useState("")
  const [aiPrompt, setAiPrompt] = useState("")
  
  // Discovery state
  const [discovering, setDiscovering] = useState(false)
  const [discoveryType, setDiscoveryType] = useState(null) // 'people', 'companies', 'local'
  
  // Modal state
  const [showModal, setShowModal] = useState(false)
  const [modalType, setModalType] = useState(null)
  const [modalData, setModalData] = useState({
    designation: "",
    industry: "",
    location: "",
    company: "",
    jobTitle: "",
    businessType: "",
    count: 20
  })

  // CSV Import state
  const [csvFile, setCsvFile] = useState(null)
  const [csvData, setCsvData] = useState([])
  const [csvColumns, setCsvColumns] = useState([])
  const [columnMapping, setColumnMapping] = useState({})
  const [csvImportStep, setCsvImportStep] = useState(1) // 1=upload, 2=map, 3=preview
  const [csvImporting, setCsvImporting] = useState(false)
  const fileInputRef = useRef(null)

  // Gmail Import state
  const [gmailAccounts, setGmailAccounts] = useState([])
  const [selectedGmailAccounts, setSelectedGmailAccounts] = useState([])
  const [gmailMaxEmails, setGmailMaxEmails] = useState(100)
  const [gmailImporting, setGmailImporting] = useState(false)
  const [gmailImportProgress, setGmailImportProgress] = useState(null)

  // Import Method state (tabs: web-search, csv, gmail, ai-discovery)
  const [importMethod, setImportMethod] = useState("web-search")
  const [showImportPanel, setShowImportPanel] = useState(false)
  
  // Web Search state
  const [webSearchDesignation, setWebSearchDesignation] = useState("")
  const [webSearchCountries, setWebSearchCountries] = useState([])
  const [webSearchSeniorities, setWebSearchSeniorities] = useState([])
  const [webSearchProgress, setWebSearchProgress] = useState(null)
  const [searchControl, setSearchControl] = useState({
    global_paused: false,
    paused_reason: "",
    circuit_breaker_open: false,
    active_jobs_count: 0
  })
  
  // AI Discovery state
  const [discoveryIndustry, setDiscoveryIndustry] = useState("")
  const [discoveryLocation, setDiscoveryLocation] = useState("")
  const [discoveryCriteria, setDiscoveryCriteria] = useState("")
  const [discoveryDesignation, setDiscoveryDesignation] = useState("")
  const [discoveryLoading, setDiscoveryLoading] = useState(false)
  const [discoveryError, setDiscoveryError] = useState("")
  
  // Workbooks/Files state
  const [workbooks, setWorkbooks] = useState([])
  const [workbooksLoading, setWorkbooksLoading] = useState(false)
  
  // Status state
  const [status, setStatus] = useState(null)

  useEffect(() => {
    loadWorkbooks()
    loadStatus()
    fetchGmailAccounts()
  }, [])

  const loadStatus = async () => {
    try {
      const token = getAuthToken()
      const res = await fetch(buildApiUrl(`/leads/ai-database/status`), {
        headers: { Authorization: token }
      })
      if (res.ok) {
        const data = await res.json()
        setStatus(data)
      }
    } catch (error) {
      console.error("Error loading status:", error)
    }
  }

  const fetchGmailAccounts = async () => {
    try {
      const token = getAuthToken()
      const res = await fetch(buildApiUrl(`/leads/gmail/accounts`), {
        headers: { Authorization: token }
      })
      if (res.ok) {
        const data = await res.json()
        setGmailAccounts(data.accounts || [])
      }
    } catch (error) {
      console.error("Error fetching Gmail accounts:", error)
    }
  }

  const loadWorkbooks = async () => {
    setWorkbooksLoading(true)
    try {
      const token = getAuthToken()
      const res = await fetch(buildApiUrl(`/leads/ai-database/workbooks`), {
        headers: { Authorization: token }
      })
      if (res.ok) {
        const data = await res.json()
        setWorkbooks(data.workbooks || [])
      } else {
        // Fallback: load companies as workbook items
        const companiesRes = await fetch(buildApiUrl(`/leads/ai-database/companies`), {
          headers: { Authorization: token }
        })
        if (companiesRes.ok) {
          const data = await companiesRes.json()
          // Transform companies to workbook format
          const transformed = (data.companies || []).slice(0, 20).map((c, idx) => ({
            _id: c._id || idx,
            name: c.company_name || c.name || "Untitled workbook",
            tags: c.industry ? [c.industry] : [],
            created_at: c.discovered_at || c.created_at,
            last_opened: c.last_accessed || c.discovered_at,
            owner: "You",
            access: "Edit",
            is_favorite: false,
            leads_count: c.leads_found || 0
          }))
          setWorkbooks(transformed)
        }
      }
    } catch (error) {
      console.error("Error loading workbooks:", error)
    } finally {
      setWorkbooksLoading(false)
    }
  }

  // Auto-match CSV columns to database fields
  const autoMatchColumns = (columns) => {
    const mapping = {}
    const normalize = (str) => str.toLowerCase().replace(/[\s\-\.]/g, "_").replace(/[^a-z0-9_]/g, "")
    
    columns.forEach((csvCol) => {
      const normalizedCsv = normalize(csvCol)
      for (const [dbField, aliases] of Object.entries(COLUMN_ALIASES)) {
        const normalizedAliases = aliases.map(a => normalize(a))
        if (normalizedAliases.some((alias) => normalizedCsv === alias || normalizedCsv.includes(alias) || alias.includes(normalizedCsv))) {
          if (!mapping[dbField]) {
            mapping[dbField] = csvCol
          }
          break
        }
      }
    })
    return mapping
  }

  // Handle CSV file selection
  const handleCsvFileSelect = async (file) => {
    if (!file) return
    if (!file.name.endsWith(".csv")) {
      setMessage({ type: "error", text: "Please select a CSV file" })
      return
    }
    setCsvFile(file)

    Papa.parse(file, {
      header: true,
      skipEmptyLines: true,
      complete: async (results) => {
        if (results.errors.length > 0) {
          setMessage({ type: "error", text: "Error parsing CSV: " + results.errors[0].message })
          return
        }
        const columns = results.meta.fields || []
        setCsvColumns(columns)
        setCsvData(results.data)
        
        const autoMapping = autoMatchColumns(columns)
        setColumnMapping(autoMapping)
        setCsvImportStep(2)
      },
      error: (err) => {
        setMessage({ type: "error", text: "Error reading file: " + err.message })
      }
    })
  }

  // Handle CSV column mapping change
  const handleMappingChange = (dbField, csvColumn) => {
    setColumnMapping((prev) => ({
      ...prev,
      [dbField]: csvColumn || undefined
    }))
  }

  // Handle CSV Import
  const handleCsvImport = async () => {
    if (!columnMapping.email) {
      setMessage({ type: "error", text: "Email field mapping is required" })
      return
    }

    setCsvImporting(true)
    setMessage({ type: "", text: "" })

    try {
      const token = getAuthToken()
      
      // Map CSV data to expected format
      const mappedData = csvData.map((row) => {
        const newRow = {}
        DB_FIELDS.forEach((field) => {
          const csvCol = columnMapping[field.key]
          if (csvCol && row[csvCol] !== undefined) {
            newRow[field.key] = row[csvCol]
          }
        })
        return newRow
      })

      // Convert back to CSV
      const csv = Papa.unparse(mappedData, { columns: DB_FIELDS.map(f => f.key) })
      const blob = new Blob([csv], { type: "text/csv" })
      const formData = new FormData()
      formData.append("file", blob, "import.csv")
      
      const res = await fetch(buildApiUrl(`/leads/import/csv`), {
        method: "POST",
        headers: { Authorization: token },
        body: formData
      })

      if (res.ok) {
        const data = await res.json()
        setMessage({ type: "success", text: `Successfully imported ${data.imported || csvData.length} leads!` })
        closeModal()
        setCsvImportStep(1)
        setCsvFile(null)
        setCsvData([])
        setCsvColumns([])
        setColumnMapping({})
        loadWorkbooks()
      } else {
        const error = await res.json()
        setMessage({ type: "error", text: getErrorMessage(error, "Import failed") })
      }
    } catch (error) {
      setMessage({ type: "error", text: error.message })
    } finally {
      setCsvImporting(false)
    }
  }

  // Handle Gmail Import (extract leads from synced emails)
  const handleGmailImport = async () => {
    setGmailImporting(true)
    setMessage({ type: "", text: "" })
    setGmailImportProgress({ status: "running", progress: 0, extracted: 0 })

    try {
      const token = getAuthToken()
      const res = await fetch(buildApiUrl(`/leads/emails/extract`), {
        method: "POST",
        headers: { 
          "Content-Type": "application/json", 
          Authorization: token 
        },
        body: JSON.stringify({
          account_emails: selectedGmailAccounts.length > 0 ? selectedGmailAccounts : null,
          max_emails: gmailMaxEmails
        })
      })

      if (res.ok) {
        const result = await res.json()
        setGmailImportProgress({
          status: "complete",
          progress: 100,
          extracted: result.leads_extracted || 0
        })
        setMessage({ 
          type: "success", 
          text: `Extracted ${result.leads_extracted || 0} leads from Gmail!` 
        })
        setTimeout(() => {
          closeModal()
          setGmailImportProgress(null)
          setSelectedGmailAccounts([])
          loadWorkbooks()
        }, 1500)
      } else {
        const error = await res.json()
        setMessage({ type: "error", text: getErrorMessage(error, "Gmail import failed") })
        setGmailImportProgress(null)
      }
    } catch (error) {
      setMessage({ type: "error", text: error.message })
      setGmailImportProgress(null)
    } finally {
      setGmailImporting(false)
    }
  }

  const openModal = (type) => {
    setModalType(type)
    setShowModal(true)
    // Reset states based on modal type
    if (type === "csv") {
      setCsvImportStep(1)
      setCsvFile(null)
      setCsvData([])
      setCsvColumns([])
      setColumnMapping({})
    } else if (type === "gmail") {
      setSelectedGmailAccounts([])
      setGmailImportProgress(null)
      fetchGmailAccounts()
    }
    setModalData({
      designation: "",
      industry: "",
      location: "",
      company: "",
      jobTitle: "",
      businessType: "",
      count: 20
    })
  }

  const closeModal = () => {
    setShowModal(false)
    setModalType(null)
  }

  const handleDiscovery = async () => {
    setDiscovering(true)
    setMessage({ type: "", text: "" })
    
    try {
      const token = getAuthToken()
      let endpoint = ""
      let body = {}
      
      switch (modalType) {
        case "people":
          endpoint = "/leads/ai-database/discover-leads"
          body = {
            designation: modalData.designation,
            industry: modalData.industry,
            location: modalData.location || "USA",
            count: modalData.count || 20
          }
          break
        case "companies":
          endpoint = "/leads/ai-database/discover-companies"
          body = {
            industry: modalData.industry,
            location: modalData.location || "USA",
            count: modalData.count || 20
          }
          break
        case "local":
          endpoint = "/leads/ai-database/discover-local"
          body = {
            business_type: modalData.businessType,
            location: modalData.location,
            count: modalData.count || 20
          }
          break
        default:
          // AI prompt discovery
          endpoint = "/leads/ai-database/discover-leads"
          body = {
            ai_prompt: aiPrompt,
            count: 20
          }
      }
      
      const res = await fetch(buildApiUrl(`${endpoint}`), {
        method: "POST",
        headers: {
          Authorization: token,
          "Content-Type": "application/json"
        },
        body: JSON.stringify(body)
      })
      
      if (res.ok) {
        const data = await res.json()
        const leadCount = data.contacts_found || data.leads_imported || data.count || 0
        setMessage({ 
          type: "success", 
          text: `Successfully discovered ${leadCount} leads! ${data.cost_estimate ? `(Cost: ${data.cost_estimate})` : ''}`
        })
        closeModal()
        loadWorkbooks()
        loadStatus()
      } else {
        const error = await res.json()
        setMessage({ type: "error", text: getErrorMessage(error, "Discovery failed") })
      }
    } catch (error) {
      setMessage({ type: "error", text: error.message })
    } finally {
      setDiscovering(false)
    }
  }

  const handleAIPromptSubmit = async (e) => {
    e.preventDefault()
    if (!aiPrompt.trim()) return
    
    setDiscovering(true)
    setMessage({ type: "", text: "" })
    
    try {
      const token = getAuthToken()
      
      // Parse the AI prompt to extract parameters
      const promptLower = aiPrompt.toLowerCase()
      let designation = ""
      let industry = ""
      let location = "USA"
      
      // Simple parsing logic
      if (promptLower.includes("ceo") || promptLower.includes("founder")) {
        designation = "CEO, Founder"
      } else if (promptLower.includes("vp") || promptLower.includes("vice president")) {
        designation = "VP, Vice President"
      } else if (promptLower.includes("director")) {
        designation = "Director"
      } else if (promptLower.includes("manager")) {
        designation = "Manager"
      }
      
      // Extract industry keywords
      const industries = ["saas", "fintech", "healthcare", "ecommerce", "ai", "tech", "automotive", "retail"]
      for (const ind of industries) {
        if (promptLower.includes(ind)) {
          industry = ind.charAt(0).toUpperCase() + ind.slice(1)
          break
        }
      }
      
      const res = await fetch(buildApiUrl(`/leads/ai-database/discover-leads`), {
        method: "POST",
        headers: {
          Authorization: token,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          designation: designation || "Executive",
          industry: industry || "Technology",
          location: location,
          count: 20,
          ai_prompt: aiPrompt
        })
      })
      
      if (res.ok) {
        const data = await res.json()
        setMessage({ 
          type: "success", 
          text: `Found ${data.contacts_found || data.leads_imported || 0} leads based on your query!`
        })
        setAiPrompt("")
        loadWorkbooks()
        loadStatus()
      } else {
        const error = await res.json()
        setMessage({ type: "error", text: getErrorMessage(error) })
      }
    } catch (error) {
      setMessage({ type: "error", text: error.message })
    } finally {
      setDiscovering(false)
    }
  }

  const createNewWorkbook = async () => {
    try {
      const token = getAuthToken()
      const res = await fetch(buildApiUrl(`/leads/ai-database/workbooks`), {
        method: "POST",
        headers: {
          Authorization: token,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          name: "Untitled workbook",
          created_at: new Date().toISOString()
        })
      })
      
      if (res.ok) {
        loadWorkbooks()
        setMessage({ type: "success", text: "New workbook created!" })
      }
    } catch (error) {
      // Create a local workbook entry as fallback
      const newWorkbook = {
        _id: Date.now().toString(),
        name: "Untitled workbook",
        tags: [],
        created_at: new Date().toISOString(),
        last_opened: new Date().toISOString(),
        owner: "You",
        access: "Edit",
        is_favorite: false,
        leads_count: 0
      }
      setWorkbooks([newWorkbook, ...workbooks])
    }
  }

  const toggleFavorite = async (workbookId) => {
    setWorkbooks(workbooks.map(w => 
      w._id === workbookId ? { ...w, is_favorite: !w.is_favorite } : w
    ))
  }

  const formatDate = (dateStr) => {
    if (!dateStr) return "-"
    const date = new Date(dateStr)
    const now = new Date()
    const diff = now - date
    const minutes = Math.floor(diff / 60000)
    const hours = Math.floor(diff / 3600000)
    const days = Math.floor(diff / 86400000)
    
    if (minutes < 60) return `${minutes} minutes ago`
    if (hours < 24) return `${hours} hours ago`
    if (days < 7) return `${days} days ago`
    return date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
  }

  const filteredWorkbooks = workbooks.filter(w => {
    if (activeTab === "favorites") return w.is_favorite
    if (activeTab === "recents") {
      const lastOpened = new Date(w.last_opened)
      const weekAgo = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000)
      return lastOpened > weekAgo
    }
    if (searchQuery) {
      return w.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
             (w.tags || []).some(t => t.toLowerCase().includes(searchQuery.toLowerCase()))
    }
    return true
  })

  return (
    <div className="ai-database-container">
      {/* Main Content */}
      <div className="ai-database-content">
        {/* AI Prompt Input */}
        <div className="ai-prompt-section">
          <form onSubmit={handleAIPromptSubmit} className="ai-prompt-form">
            <div className="ai-prompt-input-wrapper">
              <span className="ai-prompt-icon">✨</span>
              <input
                type="text"
                className="ai-prompt-input"
                placeholder="Tell us how you'd like to get started or pick a suggested use case below..."
                value={aiPrompt}
                onChange={(e) => setAiPrompt(e.target.value)}
              />
              <button 
                type="submit" 
                className="ai-prompt-submit"
                disabled={discovering || !aiPrompt.trim()}
              >
                {discovering ? "..." : "→"}
              </button>
            </div>
          </form>
          
          {/* Use Case Buttons */}
          <div className="use-case-buttons">
            <button className="use-case-btn" onClick={() => navigate("/admin/sales/campaign/ai-leads/manage")}>
              <span>🎯</span> List building
            </button>
            <button className="use-case-btn" onClick={() => openModal("companies")}>
              <span>📊</span> Account research and scoring
            </button>
            <button className="use-case-btn" onClick={() => navigate("/admin/sales/campaign/ai-leads/manage")}>
              <span>📧</span> Inbound lead enrichment & routing
            </button>
            <button className="use-case-btn" onClick={() => navigate("/admin/sales/campaign/ai-leads/manage")}>
              <span>💌</span> Personalized outbound
            </button>
          </div>
        </div>

        {/* Import Leads Section with Tabs */}
        <div className="import-leads-section">
          <div className="import-tabs-header">
            <button 
              className={`import-tab ${importMethod === "web-search" ? "active" : ""}`}
              onClick={() => { setImportMethod("web-search"); setShowImportPanel(true); }}
            >
              🌐 Web Search
            </button>
            <button 
              className={`import-tab ${importMethod === "csv" ? "active" : ""}`}
              onClick={() => { setImportMethod("csv"); setShowImportPanel(true); setCsvImportStep(1); }}
            >
              📄 CSV Upload
            </button>
            <button 
              className={`import-tab ${importMethod === "gmail" ? "active" : ""}`}
              onClick={() => { setImportMethod("gmail"); setShowImportPanel(true); fetchGmailAccounts(); }}
            >
              📧 Gmail
            </button>
            <button 
              className={`import-tab ${importMethod === "ai-discovery" ? "active" : ""}`}
              onClick={() => { setImportMethod("ai-discovery"); setShowImportPanel(true); }}
            >
              🔮 AI Discovery
            </button>
          </div>

          {/* Import Panel Content */}
          {showImportPanel && (
            <div className="import-panel">
              {/* Web Search Panel */}
              {importMethod === "web-search" && (
                <div className="import-panel-content">
                  {/* Search Control Status */}
                  {searchControl.global_paused && (
                    <div className="search-status-banner paused">
                      <span className="status-dot">●</span>
                      <span className="status-text">Search Paused</span>
                      <span className="status-reason">Reason: {searchControl.paused_reason || "Manual pause"}</span>
                      <button className="btn-resume" onClick={() => navigate("/admin/sales/campaign/ai-leads/manage")}>
                        ▶ Resume
                      </button>
                      <button className="btn-stop" onClick={() => navigate("/admin/sales/campaign/ai-leads/manage")}>
                        ■ Stop All
                      </button>
                    </div>
                  )}
                  
                  <p className="panel-description">
                    Configure filters to search for LinkedIn profiles. The system will search up to 10,000 leads using multiple query combinations.
                  </p>
                  
                  <div className="form-group">
                    <label>Designation / Title (multiple, comma-separated)</label>
                    <input
                      type="text"
                      placeholder="e.g., CEO, VP Sales, Director of Marketing"
                      value={webSearchDesignation}
                      onChange={(e) => setWebSearchDesignation(e.target.value)}
                      className="form-input"
                    />
                    <small className="form-hint">Enter job titles separated by commas</small>
                  </div>
                  
                  <div className="form-row">
                    <div className="form-group">
                      <label>Countries / Regions (select multiple)</label>
                      <div className="checkbox-grid">
                        {["United States", "United Kingdom", "Canada", "Australia", "Germany", "France", "India", "Singapore"].map(country => (
                          <label key={country} className="checkbox-label">
                            <input
                              type="checkbox"
                              checked={webSearchCountries.includes(country)}
                              onChange={(e) => {
                                if (e.target.checked) {
                                  setWebSearchCountries([...webSearchCountries, country])
                                } else {
                                  setWebSearchCountries(webSearchCountries.filter(c => c !== country))
                                }
                              }}
                            />
                            {country}
                          </label>
                        ))}
                      </div>
                      <small className="selected-count">{webSearchCountries.length} selected</small>
                    </div>
                    
                    <div className="form-group">
                      <label>Seniority Levels (select multiple)</label>
                      <div className="checkbox-grid">
                        {["Owner", "Founder", "CXO", "Partner", "VP", "Director", "Manager", "Senior"].map(level => (
                          <label key={level} className="checkbox-label">
                            <input
                              type="checkbox"
                              checked={webSearchSeniorities.includes(level)}
                              onChange={(e) => {
                                if (e.target.checked) {
                                  setWebSearchSeniorities([...webSearchSeniorities, level])
                                } else {
                                  setWebSearchSeniorities(webSearchSeniorities.filter(s => s !== level))
                                }
                              }}
                            />
                            {level}
                          </label>
                        ))}
                      </div>
                      <small className="selected-count">{webSearchSeniorities.length} selected</small>
                    </div>
                  </div>
                  
                  <div className="panel-actions">
                    <button className="btn-cancel" onClick={() => setShowImportPanel(false)}>Cancel</button>
                    <button 
                      className="btn-import"
                      onClick={() => navigate("/admin/sales/campaign/ai-leads/manage")}
                    >
                      ⭐ Import Leads
                    </button>
                  </div>
                </div>
              )}
              
              {/* CSV Upload Panel */}
              {importMethod === "csv" && (
                <div className="import-panel-content">
                  <p className="panel-description">
                    Upload a CSV file with your leads. Required field: Email. Optional: Name, Company, Title, etc.
                  </p>
                  
                  {csvImportStep === 1 && (
                    <div className="csv-upload-area">
                      <input
                        type="file"
                        accept=".csv"
                        ref={fileInputRef}
                        onChange={handleCsvUpload}
                        style={{ display: "none" }}
                      />
                      <div 
                        className="upload-dropzone"
                        onClick={() => fileInputRef.current?.click()}
                      >
                        <span className="upload-icon">📄</span>
                        <span className="upload-text">Click to upload CSV or drag and drop</span>
                        <span className="upload-hint">Supports .csv files</span>
                      </div>
                    </div>
                  )}
                  
                  {csvImportStep === 2 && csvColumns.length > 0 && (
                    <div className="csv-mapping">
                      <h4>Map CSV Columns to Fields</h4>
                      <div className="mapping-grid">
                        {DB_FIELDS.map(field => (
                          <div key={field.key} className="mapping-row">
                            <label>{field.label} {field.required && <span className="required">*</span>}</label>
                            <select
                              value={columnMapping[field.key] || ""}
                              onChange={(e) => setColumnMapping({ ...columnMapping, [field.key]: e.target.value })}
                            >
                              <option value="">-- Select column --</option>
                              {csvColumns.map(col => (
                                <option key={col} value={col}>{col}</option>
                              ))}
                            </select>
                          </div>
                        ))}
                      </div>
                      <div className="panel-actions">
                        <button className="btn-cancel" onClick={() => { setCsvImportStep(1); setCsvData([]); setCsvColumns([]); }}>Back</button>
                        <button className="btn-import" onClick={() => setCsvImportStep(3)}>Preview Data</button>
                      </div>
                    </div>
                  )}
                  
                  {csvImportStep === 3 && (
                    <div className="csv-preview">
                      <h4>Preview ({csvData.length} rows)</h4>
                      <div className="preview-table-wrapper">
                        <table className="preview-table">
                          <thead>
                            <tr>
                              {Object.keys(columnMapping).filter(k => columnMapping[k]).map(k => (
                                <th key={k}>{DB_FIELDS.find(f => f.key === k)?.label || k}</th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {csvData.slice(0, 5).map((row, idx) => (
                              <tr key={idx}>
                                {Object.keys(columnMapping).filter(k => columnMapping[k]).map(k => (
                                  <td key={k}>{row[columnMapping[k]] || "-"}</td>
                                ))}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                      <div className="panel-actions">
                        <button className="btn-cancel" onClick={() => setCsvImportStep(2)}>Back</button>
                        <button 
                          className="btn-import" 
                          disabled={csvImporting}
                          onClick={handleCsvImport}
                        >
                          {csvImporting ? "Importing..." : `Import ${csvData.length} Leads`}
                        </button>
                      </div>
                    </div>
                  )}
                  
                  {csvImportStep === 1 && (
                    <div className="panel-actions">
                      <button className="btn-cancel" onClick={() => setShowImportPanel(false)}>Cancel</button>
                    </div>
                  )}
                </div>
              )}
              
              {/* Gmail Import Panel */}
              {importMethod === "gmail" && (
                <div className="import-panel-content">
                  <p className="panel-description">
                    Import contacts from your Gmail accounts. Select accounts and configure import options.
                  </p>
                  
                  {gmailAccounts.length === 0 ? (
                    <div className="empty-state">
                      <span>📧</span>
                      <p>No Gmail accounts connected.</p>
                      <button 
                        className="btn-secondary"
                        onClick={() => navigate("/admin/settings")}
                      >
                        Connect Gmail Account
                      </button>
                    </div>
                  ) : (
                    <>
                      <div className="gmail-accounts-list">
                        <label>Select Gmail Accounts</label>
                        {gmailAccounts.map(account => (
                          <label key={account.email} className="checkbox-label">
                            <input
                              type="checkbox"
                              checked={selectedGmailAccounts.includes(account.email)}
                              onChange={(e) => {
                                if (e.target.checked) {
                                  setSelectedGmailAccounts([...selectedGmailAccounts, account.email])
                                } else {
                                  setSelectedGmailAccounts(selectedGmailAccounts.filter(a => a !== account.email))
                                }
                              }}
                            />
                            {account.email}
                          </label>
                        ))}
                      </div>
                      
                      <div className="form-group">
                        <label>Max emails to scan</label>
                        <input
                          type="number"
                          min="10"
                          max="1000"
                          value={gmailMaxEmails}
                          onChange={(e) => setGmailMaxEmails(parseInt(e.target.value) || 100)}
                          className="form-input"
                        />
                      </div>
                      
                      <div className="panel-actions">
                        <button className="btn-cancel" onClick={() => setShowImportPanel(false)}>Cancel</button>
                        <button 
                          className="btn-import"
                          disabled={gmailImporting || selectedGmailAccounts.length === 0}
                          onClick={handleGmailImport}
                        >
                          {gmailImporting ? "Importing..." : "Import from Gmail"}
                        </button>
                      </div>
                    </>
                  )}
                </div>
              )}
              
              {/* AI Discovery Panel */}
              {importMethod === "ai-discovery" && (
                <div className="import-panel-content">
                  <p className="panel-description">
                    Use AI to discover contacts based on your criteria. Powered by Google Search + OpenAI.
                  </p>
                  
                  <div className="form-group">
                    <label>Industry</label>
                    <input
                      type="text"
                      placeholder="e.g., SaaS, Fintech, Healthcare"
                      value={discoveryIndustry}
                      onChange={(e) => setDiscoveryIndustry(e.target.value)}
                      className="form-input"
                    />
                  </div>
                  
                  <div className="form-group">
                    <label>Location</label>
                    <input
                      type="text"
                      placeholder="e.g., USA, Europe, Asia Pacific"
                      value={discoveryLocation}
                      onChange={(e) => setDiscoveryLocation(e.target.value)}
                      className="form-input"
                    />
                  </div>
                  
                  <div className="form-group">
                    <label>Target Designation</label>
                    <input
                      type="text"
                      placeholder="e.g., CEO, VP of Sales, Marketing Director"
                      value={discoveryDesignation}
                      onChange={(e) => setDiscoveryDesignation(e.target.value)}
                      className="form-input"
                    />
                  </div>
                  
                  <div className="form-group">
                    <label>Additional Criteria</label>
                    <textarea
                      placeholder="e.g., Companies with 50-500 employees, Recently funded startups"
                      value={discoveryCriteria}
                      onChange={(e) => setDiscoveryCriteria(e.target.value)}
                      className="form-textarea"
                      rows={3}
                    />
                  </div>
                  
                  {discoveryError && (
                    <div className="error-message">{discoveryError}</div>
                  )}
                  
                  <div className="panel-actions">
                    <button className="btn-cancel" onClick={() => setShowImportPanel(false)}>Cancel</button>
                    <button 
                      className="btn-import"
                      disabled={discoveryLoading}
                      onClick={() => navigate("/admin/sales/campaign/ai-leads/manage")}
                    >
                      {discoveryLoading ? "Discovering..." : "🔮 Discover Contacts"}
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Start from a source */}
        <div className="source-section source-section-centered">
          <h3 className="source-title">Start from a source</h3>
          <div className="source-cards">
            <button className="source-card source-people" onClick={() => navigate("/admin/sales/campaign/ai-leads/manage")}>
              <span className="source-icon">👤</span>
              <span>Find people</span>
            </button>
            <button className="source-card source-companies" onClick={() => openModal("companies")}>
              <span className="source-icon">🏢</span>
              <span>Find companies</span>
            </button>
            <button className="source-card source-local" onClick={() => openModal("local")}>
              <span className="source-icon">💬</span>
              <span>Local businesses</span>
            </button>
            <button className="source-card source-csv" onClick={() => { setImportMethod("csv"); setShowImportPanel(true); setCsvImportStep(1); }}>
              <span className="source-icon">📄</span>
              <span>Import CSV</span>
            </button>
            <button className="source-card source-gmail" onClick={() => { setImportMethod("gmail"); setShowImportPanel(true); fetchGmailAccounts(); }}>
              <span className="source-icon">📧</span>
              <span>Import from Gmail</span>
            </button>
          </div>
        </div>

        {/* Message */}
        {message.text && (
          <div className={`ai-message ${message.type}`}>
            {message.type === "success" ? "✓" : message.type === "error" ? "⚠" : "ℹ"} {message.text}
          </div>
        )}

        {/* Tabs */}
        <div className="workbooks-tabs">
          <button 
            className={`tab-btn ${activeTab === "all" ? "active" : ""}`}
            onClick={() => setActiveTab("all")}
          >
            All files
          </button>
          <button 
            className={`tab-btn ${activeTab === "recents" ? "active" : ""}`}
            onClick={() => setActiveTab("recents")}
          >
            Recents
          </button>
          <button 
            className={`tab-btn ${activeTab === "favorites" ? "active" : ""}`}
            onClick={() => setActiveTab("favorites")}
          >
            Favorites
          </button>
        </div>

        {/* Files Section */}
        <div className="files-section">
          <div className="files-header">
            <h2>All Files</h2>
            <div className="files-actions">
              <div className="search-wrapper">
                <input
                  type="text"
                  placeholder="Search..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="search-input"
                />
              </div>
              <button className="new-btn" onClick={createNewWorkbook}>
                + New
              </button>
            </div>
          </div>

          {/* Filters */}
          <div className="files-filters">
            <div className="filter-group">
              <span>Owner</span>
              <select className="filter-select">
                <option>All</option>
                <option>Me</option>
              </select>
            </div>
            <button className="filter-btn">
              <span>▼</span> Filters
            </button>
          </div>

          {/* Files Table */}
          <div className="files-table-wrapper">
            {workbooksLoading ? (
              <div className="loading-state">
                <div className="spinner"></div>
                <p>Loading workbooks...</p>
              </div>
            ) : filteredWorkbooks.length === 0 ? (
              <div className="empty-state">
                <div className="empty-icon">📁</div>
                <p>No workbooks yet</p>
                <p className="empty-hint">Click "Find people" or "Find companies" to start discovering leads</p>
              </div>
            ) : (
              <table className="files-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Tags</th>
                    <th>Created at</th>
                    <th>Last opened by me</th>
                    <th>Owner</th>
                    <th>Access</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {filteredWorkbooks.map((workbook) => (
                    <tr key={workbook._id}>
                      <td className="name-cell">
                        <span className="file-icon">📄</span>
                        {workbook.leads_count > 0 && (
                          <span className="leads-indicator">⚡</span>
                        )}
                        <span className="file-name">{workbook.name}</span>
                      </td>
                      <td>
                        <button 
                          className={`favorite-btn ${workbook.is_favorite ? "active" : ""}`}
                          onClick={() => toggleFavorite(workbook._id)}
                        >
                          {workbook.is_favorite ? "★" : "☆"}
                        </button>
                      </td>
                      <td className="date-cell">{formatDate(workbook.created_at)}</td>
                      <td className="date-cell">{formatDate(workbook.last_opened)}</td>
                      <td>
                        <div className="owner-cell">
                          <span className="owner-avatar">👤</span>
                          <span>{workbook.owner || "You"}</span>
                        </div>
                      </td>
                      <td>{workbook.access || "Edit"}</td>
                      <td>
                        <button className="more-btn">⋯</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>

      {/* Modal */}
      {showModal && (
        <div className="modal-overlay" onClick={closeModal}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>
                {modalType === "people" && "🔍 Find People"}
                {modalType === "companies" && "🏢 Find Companies"}
                {modalType === "local" && "💬 Local Businesses"}
                {modalType === "csv" && "📄 Import CSV"}
                {modalType === "gmail" && "📧 Import from Gmail"}
              </h2>
              <button className="modal-close" onClick={closeModal}>×</button>
            </div>
            
            <div className="modal-body">
              {modalType === "people" && (
                <>
                  <div className="form-group">
                    <label>Job Title / Designation</label>
                    <input
                      type="text"
                      placeholder="e.g., CEO, VP Sales, Director of Marketing"
                      value={modalData.designation}
                      onChange={(e) => setModalData({ ...modalData, designation: e.target.value })}
                    />
                  </div>
                  <div className="form-group">
                    <label>Industry</label>
                    <input
                      type="text"
                      placeholder="e.g., SaaS, Fintech, Healthcare"
                      value={modalData.industry}
                      onChange={(e) => setModalData({ ...modalData, industry: e.target.value })}
                    />
                  </div>
                  <div className="form-group">
                    <label>Location</label>
                    <input
                      type="text"
                      placeholder="e.g., USA, New York, London"
                      value={modalData.location}
                      onChange={(e) => setModalData({ ...modalData, location: e.target.value })}
                    />
                  </div>
                  <div className="form-group">
                    <label>Number of leads</label>
                    <input
                      type="number"
                      min="5"
                      max="100"
                      value={modalData.count}
                      onChange={(e) => setModalData({ ...modalData, count: parseInt(e.target.value) || 20 })}
                    />
                  </div>
                </>
              )}
              
              {modalType === "companies" && (
                <>
                  <div className="form-group">
                    <label>Industry</label>
                    <input
                      type="text"
                      placeholder="e.g., SaaS, Fintech, E-commerce"
                      value={modalData.industry}
                      onChange={(e) => setModalData({ ...modalData, industry: e.target.value })}
                    />
                  </div>
                  <div className="form-group">
                    <label>Location</label>
                    <input
                      type="text"
                      placeholder="e.g., USA, Europe, Asia"
                      value={modalData.location}
                      onChange={(e) => setModalData({ ...modalData, location: e.target.value })}
                    />
                  </div>
                  <div className="form-group">
                    <label>Number of companies</label>
                    <input
                      type="number"
                      min="5"
                      max="100"
                      value={modalData.count}
                      onChange={(e) => setModalData({ ...modalData, count: parseInt(e.target.value) || 20 })}
                    />
                  </div>
                </>
              )}
              
              {modalType === "local" && (
                <>
                  <div className="form-group">
                    <label>Business Type</label>
                    <input
                      type="text"
                      placeholder="e.g., Restaurant, Gym, Salon"
                      value={modalData.businessType}
                      onChange={(e) => setModalData({ ...modalData, businessType: e.target.value })}
                    />
                  </div>
                  <div className="form-group">
                    <label>Location (City/Area)</label>
                    <input
                      type="text"
                      placeholder="e.g., Manhattan, Downtown LA"
                      value={modalData.location}
                      onChange={(e) => setModalData({ ...modalData, location: e.target.value })}
                    />
                  </div>
                  <div className="form-group">
                    <label>Number of businesses</label>
                    <input
                      type="number"
                      min="5"
                      max="100"
                      value={modalData.count}
                      onChange={(e) => setModalData({ ...modalData, count: parseInt(e.target.value) || 20 })}
                    />
                  </div>
                </>
              )}

              {/* CSV Import Modal */}
              {modalType === "csv" && (
                <>
                  {csvImportStep === 1 && (
                    <div className="form-group">
                      <label>Select CSV File</label>
                      <input
                        type="file"
                        ref={fileInputRef}
                        accept=".csv"
                        onChange={(e) => handleCsvFileSelect(e.target.files[0])}
                        style={{ display: "none" }}
                      />
                      <button 
                        className="upload-btn"
                        onClick={() => fileInputRef.current?.click()}
                      >
                        📄 Choose CSV File
                      </button>
                      <p className="form-hint">Upload a CSV file with lead data (email required)</p>
                    </div>
                  )}
                  
                  {csvImportStep === 2 && (
                    <>
                      <div className="csv-file-info">
                        <span>📄 {csvFile?.name}</span>
                        <span className="csv-rows">{csvData.length} rows</span>
                      </div>
                      <div className="mapping-section">
                        <h4>Map CSV Columns to Fields</h4>
                        <div className="mapping-grid">
                          {DB_FIELDS.map((field) => (
                            <div key={field.key} className="mapping-row">
                              <label>
                                {field.label}
                                {field.required && <span className="required">*</span>}
                              </label>
                              <select
                                value={columnMapping[field.key] || ""}
                                onChange={(e) => handleMappingChange(field.key, e.target.value)}
                              >
                                <option value="">-- Select --</option>
                                {csvColumns.map((col) => (
                                  <option key={col} value={col}>{col}</option>
                                ))}
                              </select>
                            </div>
                          ))}
                        </div>
                      </div>
                    </>
                  )}
                </>
              )}

              {/* Gmail Import Modal */}
              {modalType === "gmail" && (
                <>
                  <div className="form-group">
                    <label>Select Gmail Accounts</label>
                    {gmailAccounts.length === 0 ? (
                      <p className="form-hint">No Gmail accounts connected. Go to Settings to add accounts.</p>
                    ) : (
                      <div className="gmail-accounts-list">
                        {gmailAccounts.map((account) => (
                          <label key={account.email} className="gmail-account-item">
                            <input
                              type="checkbox"
                              checked={selectedGmailAccounts.includes(account.email)}
                              onChange={(e) => {
                                if (e.target.checked) {
                                  setSelectedGmailAccounts([...selectedGmailAccounts, account.email])
                                } else {
                                  setSelectedGmailAccounts(selectedGmailAccounts.filter(a => a !== account.email))
                                }
                              }}
                            />
                            <span>{account.email}</span>
                          </label>
                        ))}
                      </div>
                    )}
                  </div>
                  <div className="form-group">
                    <label>Max Emails to Process</label>
                    <input
                      type="number"
                      min="10"
                      max="1000"
                      value={gmailMaxEmails}
                      onChange={(e) => setGmailMaxEmails(parseInt(e.target.value) || 100)}
                    />
                    <p className="form-hint">Extract leads from your synced Gmail emails</p>
                  </div>
                  {gmailImportProgress && (
                    <div className="import-progress">
                      <div className="progress-bar">
                        <div 
                          className="progress-fill" 
                          style={{ width: `${gmailImportProgress.progress}%` }}
                        />
                      </div>
                      <p>{gmailImportProgress.status === "complete" 
                        ? `✓ Extracted ${gmailImportProgress.extracted} leads` 
                        : "Extracting leads..."}</p>
                    </div>
                  )}
                </>
              )}
            </div>
            
            <div className="modal-footer">
              <button className="btn-secondary" onClick={closeModal}>
                Cancel
              </button>
              {modalType === "csv" ? (
                <button 
                  className="btn-primary" 
                  onClick={handleCsvImport}
                  disabled={csvImporting || csvImportStep === 1 || !columnMapping.email}
                >
                  {csvImporting ? "Importing..." : "📥 Import Leads"}
                </button>
              ) : modalType === "gmail" ? (
                <button 
                  className="btn-primary" 
                  onClick={handleGmailImport}
                  disabled={gmailImporting || gmailAccounts.length === 0}
                >
                  {gmailImporting ? "Extracting..." : "📧 Extract Leads"}
                </button>
              ) : (
                <button 
                  className="btn-primary" 
                  onClick={handleDiscovery}
                  disabled={discovering}
                >
                  {discovering ? "Discovering..." : "🚀 Start Discovery"}
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default AIDatabase
