import { useState, useEffect, useRef } from "react"
import { buildApiUrl } from "../../config"
import Papa from "papaparse"

const PANEL_ADMIN_API_PREFIX = "/api/panel-admin"

function PanelistManagement() {
  const [activeTab, setActiveTab] = useState("panelist-leads")

  // SFW Panel state
  const [sfwPanelists, setSfwPanelists] = useState([])
  const [sfwPage, setSfwPage] = useState(1)
  const [sfwTotal, setSfwTotal] = useState(0)
  const [sfwPages, setSfwPages] = useState(1)
  const [sfwLoading, setSfwLoading] = useState(false)
  const [sfwSearch, setSfwSearch] = useState("")
  const [sfwCountry, setSfwCountry] = useState("")
  const [sfwSortBy, setSfwSortBy] = useState("createdAt")
  const [sfwOrder, setSfwOrder] = useState("desc")
  const [sfwDetail, setSfwDetail] = useState(null)
  const [sfwDetailLoading, setSfwDetailLoading] = useState(false)

  // Panelist leads state
  const [panelLeads, setPanelLeads] = useState([])
  const [leadPage, setLeadPage] = useState(1)
  const [leadTotal, setLeadTotal] = useState(0)
  const [leadLoading, setLeadLoading] = useState(false)
  const [leadSearch, setLeadSearch] = useState("")

  // Approved panelists state
  const [panelists, setPanelists] = useState([])
  const [panelistPage, setPanelistPage] = useState(1)
  const [panelistTotal, setPanelistTotal] = useState(0)
  const [panelistLoading, setPanelistLoading] = useState(false)
  const [panelistSearch, setPanelistSearch] = useState("")
  const [countryFilter, setCountryFilter] = useState("")
  const [availableCountries, setAvailableCountries] = useState([])
  const [leadCountries, setLeadCountries] = useState([])

  // CSV upload state
  const [showUpload, setShowUpload] = useState(false)
  const [csvData, setCsvData] = useState(null)
  const [csvFileName, setCsvFileName] = useState("")
  const [uploading, setUploading] = useState(false)
  const [uploadResult, setUploadResult] = useState(null)
  const [importUrl, setImportUrl] = useState("")
  const [importFormat, setImportFormat] = useState("auto")
  const [importRootKey, setImportRootKey] = useState("")
  const [importingLink, setImportingLink] = useState(false)
  const [importLinkResult, setImportLinkResult] = useState(null)
  const fileInputRef = useRef(null)

  // Invitation state
  const [showInviteModal, setShowInviteModal] = useState(false)
  const [inviteLoading, setInviteLoading] = useState(false)
  const [inviteResult, setInviteResult] = useState(null)
  const [inviteCount, setInviteCount] = useState(0)

  // Test email state
  const [showTestEmailModal, setShowTestEmailModal] = useState(false)
  const [testEmailAddress, setTestEmailAddress] = useState("")
  const [testEmailName, setTestEmailName] = useState("")
  const [testEmailLoading, setTestEmailLoading] = useState(false)
  const [testEmailResult, setTestEmailResult] = useState(null)

  // Lead promotion state — parsing-page leads only receive invitations once
  // they have been merged into the `panelists` collection.
  const [promotionStatus, setPromotionStatus] = useState(null)
  const [promoting, setPromoting] = useState(false)
  const [promoteResult, setPromoteResult] = useState(null)

  // Records loaded per request. Fetching 100 rows of a 190K-row collection on
  // every page click was the bulk of the wait, so this is user-controlled and
  // defaults low; the table always loads one batch at a time from the server.
  const PAGE_SIZE_OPTIONS = [25, 50, 100, 250, 500]
  const [pageSize, setPageSize] = useState(25)

  const handlePageSizeChange = (e) => {
    setPageSize(parseInt(e.target.value))
    setLeadPage(1)
    setPanelistPage(1)
    setSfwPage(1)
  }

  useEffect(() => {
    if (activeTab === "sfw-panelists") {
      fetchSfwPanelists()
    } else if (activeTab === "panelist-leads") {
      fetchPanelLeads()
    } else if (activeTab === "panelist-approved") {
      fetchPanelists()
    }
  }, [activeTab, leadPage, panelistPage, countryFilter, pageSize])

  // Fetch distinct countries on mount
  useEffect(() => {
    fetchCountries()
    fetchLeadCountries()
    fetchPromotionStatus()
  }, [])

  const fetchPromotionStatus = async () => {
    const sessionId = localStorage.getItem("session_id")
    try {
      const res = await fetch(buildApiUrl(`${PANEL_ADMIN_API_PREFIX}/panelist-leads/promotion-status`), {
        headers: { Authorization: sessionId },
      })
      if (res.ok) setPromotionStatus(await res.json())
    } catch (err) {
      console.error("Failed to fetch lead promotion status:", err)
    }
  }

  const handlePromoteLeads = async () => {
    setPromoting(true)
    setPromoteResult(null)
    const sessionId = localStorage.getItem("session_id")
    try {
      const res = await fetch(buildApiUrl(`${PANEL_ADMIN_API_PREFIX}/panelist-leads/promote`), {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: sessionId },
        body: JSON.stringify({}),
      })
      const data = await parseApiResponse(res)
      if (res.ok) {
        setPromoteResult({
          success: true,
          message: `Merged ${data.inserted || 0} new leads into the panelist list (${data.already_present || 0} were already there). They enter the invite rotation on the next run.`,
        })
        fetchPromotionStatus()
        fetchPanelists()
      } else {
        setPromoteResult({ success: false, message: data.detail || "Merge failed" })
      }
    } catch (err) {
      setPromoteResult({ success: false, message: "Network error: " + err.message })
    } finally {
      setPromoting(false)
    }
  }

  const fetchCountries = async () => {
    const sessionId = localStorage.getItem("session_id")
    try {
      const res = await fetch(buildApiUrl(`${PANEL_ADMIN_API_PREFIX}/panelists/countries`), {
        headers: { Authorization: sessionId },
      })
      if (res.ok) {
        const data = await res.json()
        setAvailableCountries(data.countries || [])
      }
    } catch (err) {
      console.error("Failed to fetch countries:", err)
    }
  }

  const fetchLeadCountries = async () => {
    const sessionId = localStorage.getItem("session_id")
    try {
      const res = await fetch(buildApiUrl(`${PANEL_ADMIN_API_PREFIX}/panelist-leads/countries`), {
        headers: { Authorization: sessionId },
      })
      if (res.ok) {
        const data = await res.json()
        setLeadCountries(data.countries || [])
      }
    } catch (err) {
      console.error("Failed to fetch lead countries:", err)
    }
  }

  const fetchPanelLeads = async () => {
    setLeadLoading(true)
    const sessionId = localStorage.getItem("session_id")
    try {
      const params = new URLSearchParams({
        page: leadPage,
        page_size: pageSize,
      })
      if (leadSearch) params.append("search", leadSearch)
      if (countryFilter) params.append("country", countryFilter)

      const res = await fetch(buildApiUrl(`${PANEL_ADMIN_API_PREFIX}/panelist-leads/?${params}`), {
        headers: { Authorization: sessionId },
      })
      if (res.ok) {
        const data = await res.json()
        setPanelLeads(data.results || [])
        setLeadTotal(data.total || 0)
      }
    } catch (err) {
      console.error("Failed to fetch panelist leads:", err)
    } finally {
      setLeadLoading(false)
    }
  }

  const fetchPanelists = async () => {
    setPanelistLoading(true)
    const sessionId = localStorage.getItem("session_id")
    try {
      const params = new URLSearchParams({
        page: panelistPage,
        page_size: pageSize,
      })
      if (panelistSearch) params.append("search", panelistSearch)
      if (countryFilter) params.append("country", countryFilter)
      params.append("status", "active")

      const res = await fetch(buildApiUrl(`${PANEL_ADMIN_API_PREFIX}/panelists/with-email-status?${params}`), {
        headers: { Authorization: sessionId },
      })
      if (res.ok) {
        const data = await res.json()
        setPanelists(data.results || data.panelists || [])
        setPanelistTotal(data.total || 0)
      }
    } catch (err) {
      console.error("Failed to fetch panelists:", err)
    } finally {
      setPanelistLoading(false)
    }
  }

  const handleSearchLeads = (e) => {
    e.preventDefault()
    setLeadPage(1)
    fetchPanelLeads()
  }

  const handleSearchPanelists = (e) => {
    e.preventDefault()
    setPanelistPage(1)
    fetchPanelists()
  }

  const parseApiResponse = async (res) => {
    const contentType = (res.headers.get("content-type") || "").toLowerCase()
    if (contentType.includes("application/json")) {
      return await res.json()
    }

    const text = await res.text()
    return {
      detail:
        res.status === 524 || res.status === 522
          ? `Server timeout (HTTP ${res.status}) — the backend took too long to respond.`
          : `Unexpected server response (${res.status}): ${text}`,
    }
  }

  // Helper to get email status badge styling
  const getEmailStatusBadge = (status) => {
    if (!status) return { bg: "#f3f4f6", text: "#6b7280", label: "Not sent" }
    const statusMap = {
      sent: { bg: "#dbeafe", text: "#1e40af", label: "Sent" },
      bounced: { bg: "#fee2e2", text: "#991b1b", label: "Bounced" },
      complained: { bg: "#fecaca", text: "#7c2d12", label: "Complained" },
      confirmed: { bg: "#d1fae5", text: "#065f46", label: "Confirmed" },
      clicked: { bg: "#c7d2fe", text: "#312e81", label: "Clicked" },
      soft_bounced: { bg: "#fef3c7", text: "#92400e", label: "Soft Bounce" },
      failed: { bg: "#f3f4f6", text: "#6b7280", label: "Failed" },
    }
    return statusMap[status] || { bg: "#f3f4f6", text: "#6b7280", label: status }
  }

  // CSV Upload handlers
  const handleFileSelect = (e) => {
    const file = e.target.files[0]
    if (!file) return

    setCsvFileName(file.name)
    setUploadResult(null)

    Papa.parse(file, {
      header: true,
      skipEmptyLines: true,
      complete: (results) => {
        setCsvData(results.data)
      },
      error: (err) => {
        console.error("CSV parse error:", err)
        alert("Failed to parse CSV file. Please check the format.")
      },
    })
  }

  const handleUploadCSV = async () => {
    if (!csvData || csvData.length === 0) return

    setUploading(true)
    setUploadResult(null)
    const sessionId = localStorage.getItem("session_id")

    try {
      const res = await fetch(buildApiUrl(`${PANEL_ADMIN_API_PREFIX}/panelists/upload-csv`), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: sessionId,
        },
        body: JSON.stringify({ panelists: csvData }),
      })

      const data = await parseApiResponse(res)
      if (res.ok) {
        setUploadResult({ success: true, message: data.message || `Uploaded ${data.inserted || 0} panelists`, data })
        setCsvData(null)
        setCsvFileName("")
        if (fileInputRef.current) fileInputRef.current.value = ""
        fetchPanelists()
      } else {
        setUploadResult({ success: false, message: data.detail || "Upload failed" })
      }
    } catch (err) {
      setUploadResult({ success: false, message: "Network error: " + err.message })
    } finally {
      setUploading(false)
    }
  }

  const handleImportFromLink = async () => {
    if (!importUrl.trim()) return

    setImportingLink(true)
    setImportLinkResult(null)
    const sessionId = localStorage.getItem("session_id")

    try {
      const payload = {
        url: importUrl.trim(),
        format: importFormat,
      }
      if (importRootKey.trim()) payload.root_key = importRootKey.trim()

      const res = await fetch(buildApiUrl(`${PANEL_ADMIN_API_PREFIX}/panelists/import-link`), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: sessionId,
        },
        body: JSON.stringify(payload),
      })

      const data = await parseApiResponse(res)
      if (res.ok) {
        setImportLinkResult({
          success: true,
          message: data.message || `Imported ${data.inserted || 0} panelists from link`,
          data,
        })
        fetchPanelists()
      } else {
        setImportLinkResult({ success: false, message: data.detail || "Import from link failed" })
      }
    } catch (err) {
      setImportLinkResult({ success: false, message: "Network error: " + err.message })
    } finally {
      setImportingLink(false)
    }
  }

  // Test email handler
  const handleSendTestEmail = async () => {
    if (!testEmailAddress || !testEmailAddress.includes("@")) return
    setTestEmailLoading(true)
    setTestEmailResult(null)
    const sessionId = localStorage.getItem("session_id")
    try {
      const res = await fetch(buildApiUrl(`${PANEL_ADMIN_API_PREFIX}/invitations/test-send`), {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: sessionId },
        body: JSON.stringify({ to_email: testEmailAddress, first_name: testEmailName }),
      })
      const data = await res.json()
      if (res.ok) {
        setTestEmailResult({ success: true, message: `Test email sent to ${testEmailAddress}` })
      } else {
        setTestEmailResult({ success: false, message: data.detail || "Failed to send test email" })
      }
    } catch (err) {
      setTestEmailResult({ success: false, message: "Network error: " + err.message })
    } finally {
      setTestEmailLoading(false)
    }
  }

  // Invitation handlers
  const handleSendInvitationsClick = async () => {
    const sessionId = localStorage.getItem("session_id")
    try {
      const params = new URLSearchParams()
      if (countryFilter) params.append("country", countryFilter)
      const res = await fetch(buildApiUrl(`${PANEL_ADMIN_API_PREFIX}/invitations/preview?${params}`), {
        headers: { Authorization: sessionId },
      })
      if (res.ok) {
        const data = await res.json()
        setInviteCount(data.eligible_count || 0)
        setInviteResult(null)
        setShowInviteModal(true)
      }
    } catch (err) {
      console.error("Failed to get invitation preview:", err)
    }
  }

  const handleConfirmSendInvitations = async () => {
    setInviteLoading(true)
    setInviteResult(null)
    const sessionId = localStorage.getItem("session_id")

    try {
      const body = {}
      if (countryFilter) body.country = countryFilter

      const res = await fetch(buildApiUrl(`${PANEL_ADMIN_API_PREFIX}/invitations/send`), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: sessionId,
        },
        body: JSON.stringify(body),
      })

      const data = await res.json()
      if (res.ok) {
        setInviteResult({
          success: true,
          message: `Sent: ${data.sent || 0} | Skipped: ${data.skipped || 0} (suppressed/already invited) | Failed: ${data.failed || 0}`,
        })
      } else {
        setInviteResult({ success: false, message: data.detail || "Failed to send invitations" })
      }
    } catch (err) {
      setInviteResult({ success: false, message: "Network error: " + err.message })
    } finally {
      setInviteLoading(false)
    }
  }

  const totalLeadPages = Math.ceil(leadTotal / pageSize)
  const totalPanelistPages = Math.ceil(panelistTotal / pageSize)

  const tabStyle = (tab) => ({
    padding: "0.75rem 1.5rem",
    border: "none",
    borderBottom: activeTab === tab ? "3px solid #3b82f6" : "3px solid transparent",
    background: "none",
    cursor: "pointer",
    fontWeight: activeTab === tab ? "600" : "400",
    color: activeTab === tab ? "#3b82f6" : "#6b7280",
    fontSize: "0.95rem",
  })


  const fetchSfwPanelists = async (overrides = {}) => {
    setSfwLoading(true)
    const sessionId = localStorage.getItem("session_id")
    const pg = overrides.page ?? sfwPage
    const sb = overrides.sortBy ?? sfwSortBy
    const od = overrides.order ?? sfwOrder
    const ct = overrides.country ?? sfwCountry
    const sr = overrides.search ?? sfwSearch
    try {
      const params = new URLSearchParams({ page: pg, limit: Math.min(pageSize, 100), sort_by: sb, order: od, ...(ct ? { country: ct } : {}), ...(sr ? { search: sr } : {}) })
      const res = await fetch(buildApiUrl(`${PANEL_ADMIN_API_PREFIX}/sfwpanel-panelists?${params}`), { headers: { Authorization: sessionId } })
      if (res.ok) {
        const data = await res.json()
        setSfwPanelists(data.panelists || [])
        setSfwTotal(data.total || 0)
        setSfwPages(data.pages || 1)
      }
    } catch (err) { console.error("SFW panelists error:", err) }
    finally { setSfwLoading(false) }
  }

  const fetchSfwDetail = async (userId) => {
    setSfwDetailLoading(true)
    const sessionId = localStorage.getItem("session_id")
    try {
      const res = await fetch(buildApiUrl(`${PANEL_ADMIN_API_PREFIX}/sfwpanel-panelists/${userId}`), { headers: { Authorization: sessionId } })
      if (res.ok) setSfwDetail(await res.json())
    } catch (err) { console.error("SFW detail error:", err) }
    finally { setSfwDetailLoading(false) }
  }

  const sfwSort = (field) => {
    const newOrder = sfwSortBy === field && sfwOrder === "desc" ? "asc" : "desc"
    setSfwSortBy(field); setSfwOrder(newOrder); setSfwPage(1)
    fetchSfwPanelists({ sortBy: field, order: newOrder, page: 1 })
  }

  const rupees = (p) => p ? "₹" + (p / 100).toLocaleString("en-IN", { maximumFractionDigits: 0 }) : "₹0"
  const fmtDate = (d) => d ? new Date(d).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "—"
  const fmtTime = (d) => d ? new Date(d).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "—"
  const CNAMES = { US: "United States", IN: "India", GB: "United Kingdom", AU: "Australia", CA: "Canada", DE: "Germany", SG: "Singapore", AE: "UAE", XX: "Unknown" }
  const cname = (cc) => CNAMES[cc] || cc || "—"

  return (
    <div>
      <div className="card">
        <div className="card-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "0.75rem" }}>
          <div>
            <h2 className="card-title">Panelist Management</h2>
            <p className="card-description">Manage parsing-page leads, approved panelists, and bulk uploads.</p>
          </div>
          <div style={{ display: "flex", gap: "0.75rem" }}>
            <button
              className="btn btn-primary"
              onClick={handleSendInvitationsClick}
              style={{ background: "#059669", borderColor: "#059669" }}
            >
              Send Invitations
            </button>
            <button
              className="btn btn-outline"
              onClick={() => { setTestEmailResult(null); setShowTestEmailModal(true) }}
            >
              Send Test Email
            </button>
            <button
              className="btn btn-primary"
              onClick={() => setShowUpload(!showUpload)}
            >
              {showUpload ? "Close Upload" : "Upload CSV"}
            </button>
          </div>
        </div>

        {/* CSV Upload Section */}
        {showUpload && (
          <div className="card" style={{ marginBottom: "1.5rem", backgroundColor: "#f9fafb" }}>
            <h3 className="card-title">Upload Panelists CSV</h3>
            <p style={{ fontSize: "0.875rem", color: "#6b7280", marginBottom: "1rem" }}>
              CSV should have columns: first_name, last_name, email, country, language (optional)
            </p>
            <div style={{ display: "flex", gap: "1rem", alignItems: "center", flexWrap: "wrap" }}>
              <input
                ref={fileInputRef}
                type="file"
                accept=".csv"
                onChange={handleFileSelect}
                style={{ fontSize: "0.875rem" }}
              />
              {csvData && (
                <span style={{ fontSize: "0.875rem", color: "#059669" }}>
                  {csvData.length} rows parsed from {csvFileName}
                </span>
              )}
              <button
                className="btn btn-primary"
                onClick={handleUploadCSV}
                disabled={!csvData || uploading}
                style={{ opacity: !csvData || uploading ? 0.5 : 1 }}
              >
                {uploading ? "Uploading..." : "Upload"}
              </button>
            </div>

            {/* CSV Preview */}
            {csvData && csvData.length > 0 && (
              <div style={{ marginTop: "1rem", overflowX: "auto", maxHeight: "200px", overflowY: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.8rem" }}>
                  <thead>
                    <tr style={{ borderBottom: "2px solid #e5e7eb" }}>
                      {Object.keys(csvData[0]).map((col) => (
                        <th key={col} style={{ textAlign: "left", padding: "0.5rem", color: "#6b7280", whiteSpace: "nowrap" }}>
                          {col}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {csvData.slice(0, 5).map((row, i) => (
                      <tr key={i} style={{ borderBottom: "1px solid #f3f4f6" }}>
                        {Object.values(row).map((val, j) => (
                          <td key={j} style={{ padding: "0.5rem", whiteSpace: "nowrap" }}>{val}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
                {csvData.length > 5 && (
                  <p style={{ fontSize: "0.75rem", color: "#6b7280", marginTop: "0.5rem" }}>
                    Showing first 5 of {csvData.length} rows
                  </p>
                )}
              </div>
            )}

            {uploadResult && (
              <div style={{
                marginTop: "1rem",
                padding: "0.75rem",
                borderRadius: "6px",
                backgroundColor: uploadResult.success ? "#d1fae5" : "#fee2e2",
                color: uploadResult.success ? "#065f46" : "#991b1b",
                fontSize: "0.875rem",
              }}>
                {uploadResult.message}
              </div>
            )}

            <div style={{ marginTop: "1.5rem", paddingTop: "1rem", borderTop: "1px solid #e5e7eb" }}>
              <h3 className="card-title" style={{ marginBottom: "0.5rem" }}>Import from Link (CSV/JSON)</h3>
              <p style={{ fontSize: "0.875rem", color: "#6b7280", marginBottom: "0.75rem" }}>
                Paste an API/export URL from sfw_panel or any system. Supported: CSV or JSON array payloads.
              </p>
              <div style={{ display: "grid", gridTemplateColumns: "2fr 120px 1fr auto", gap: "0.75rem", alignItems: "center" }}>
                <input
                  type="text"
                  value={importUrl}
                  onChange={(e) => setImportUrl(e.target.value)}
                  placeholder="https://example.com/panelists.csv"
                  style={{ padding: "0.625rem 1rem", border: "1px solid #d1d5db", borderRadius: "6px", fontSize: "0.875rem" }}
                />
                <select
                  value={importFormat}
                  onChange={(e) => setImportFormat(e.target.value)}
                  style={{ padding: "0.625rem 0.75rem", border: "1px solid #d1d5db", borderRadius: "6px", fontSize: "0.875rem", backgroundColor: "#fff" }}
                >
                  <option value="auto">Auto</option>
                  <option value="csv">CSV</option>
                  <option value="json">JSON</option>
                </select>
                <input
                  type="text"
                  value={importRootKey}
                  onChange={(e) => setImportRootKey(e.target.value)}
                  placeholder="JSON root key (optional)"
                  style={{ padding: "0.625rem 1rem", border: "1px solid #d1d5db", borderRadius: "6px", fontSize: "0.875rem" }}
                />
                <button
                  className="btn btn-primary"
                  onClick={handleImportFromLink}
                  disabled={!importUrl.trim() || importingLink}
                  style={{ opacity: !importUrl.trim() || importingLink ? 0.5 : 1 }}
                >
                  {importingLink ? "Importing..." : "Import Link"}
                </button>
              </div>

              {importLinkResult && (
                <div style={{
                  marginTop: "0.75rem",
                  padding: "0.75rem",
                  borderRadius: "6px",
                  backgroundColor: importLinkResult.success ? "#d1fae5" : "#fee2e2",
                  color: importLinkResult.success ? "#065f46" : "#991b1b",
                  fontSize: "0.875rem",
                }}>
                  {importLinkResult.message}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Tabs */}
        <div style={{ borderBottom: "1px solid #e5e7eb", marginBottom: "1.5rem", display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "0.5rem" }}>
          <div>
            <button style={tabStyle("panelist-leads")} onClick={() => setActiveTab("panelist-leads")}>
              Panelist Lead
            </button>
            <button style={tabStyle("panelist-approved")} onClick={() => setActiveTab("panelist-approved")}>
              Panelist Approved
            </button>
            <button style={tabStyle("sfw-panelists")} onClick={() => setActiveTab("sfw-panelists")}>
              SFW Panelists
            </button>
          </div>
          <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontSize: "0.8rem", color: "#6b7280", paddingBottom: "0.5rem" }}>
            Rows per batch
            <select
              value={pageSize}
              onChange={handlePageSizeChange}
              style={{ padding: "0.35rem 0.5rem", border: "1px solid #d1d5db", borderRadius: "6px", fontSize: "0.8rem", backgroundColor: "#fff" }}
            >
              {PAGE_SIZE_OPTIONS.map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </select>
          </label>
        </div>

        {/* Panelist Lead Tab */}
        {activeTab === "panelist-leads" && (
          <div>
            {/* Leads live in the traffic collection; the invite senders only
                read `panelists`. Until a lead is merged across, it is visible
                here but receives no mail at all. */}
            <div style={{
              marginBottom: "1rem", padding: "0.9rem 1.1rem", borderRadius: "10px",
              border: "1px solid #fcd34d", backgroundColor: "#fffbeb",
              display: "flex", justifyContent: "space-between", alignItems: "center",
              gap: "1rem", flexWrap: "wrap",
            }}>
              <div style={{ fontSize: "0.85rem", color: "#92400e", lineHeight: "1.5" }}>
                <strong>These leads are only mailed once merged into the panelist list.</strong>
                <br />
                {promotionStatus
                  ? promotionStatus.not_yet_promoted > 0
                    ? `${promotionStatus.not_yet_promoted.toLocaleString()} of the ${promotionStatus.sampled.toLocaleString()} most recent leads are not in the panelist list yet, so they are receiving no invitations.`
                    : `All ${promotionStatus.sampled.toLocaleString()} recent leads are already merged and in the invite rotation.`
                  : "Checking how many leads are still unmerged…"}
                <br />
                <span style={{ color: "#b45309" }}>
                  Runs automatically each day at 08:20 IST; use the button for an immediate full backfill.
                </span>
              </div>
              <button
                className="btn btn-primary"
                onClick={handlePromoteLeads}
                disabled={promoting}
                style={{ background: "#d97706", borderColor: "#d97706", opacity: promoting ? 0.5 : 1, whiteSpace: "nowrap" }}
              >
                {promoting ? "Merging…" : "Merge Leads into Panelists"}
              </button>
            </div>

            {promoteResult && (
              <div style={{
                marginBottom: "1rem", padding: "0.75rem", borderRadius: "6px",
                backgroundColor: promoteResult.success ? "#d1fae5" : "#fee2e2",
                color: promoteResult.success ? "#065f46" : "#991b1b",
                fontSize: "0.875rem",
              }}>
                {promoteResult.message}
              </div>
            )}

            <div style={{ display: "flex", gap: "0.75rem", marginBottom: "1rem", flexWrap: "wrap" }}>
              <form onSubmit={handleSearchLeads} style={{ display: "flex", gap: "0.75rem", flex: 1, minWidth: "250px" }}>
                <input
                  type="text"
                  placeholder="Search by mail ID, respondent ID, vendor, country..."
                  value={leadSearch}
                  onChange={(e) => setLeadSearch(e.target.value)}
                  style={{
                    flex: 1, padding: "0.625rem 1rem", border: "1px solid #d1d5db",
                    borderRadius: "6px", fontSize: "0.875rem",
                  }}
                />
                <button type="submit" className="btn btn-primary">Search</button>
              </form>
              <select
                value={countryFilter}
                onChange={(e) => { setCountryFilter(e.target.value); setLeadPage(1) }}
                style={{
                  padding: "0.625rem 1rem", border: "1px solid #d1d5db",
                  borderRadius: "6px", fontSize: "0.875rem", minWidth: "180px",
                  backgroundColor: "#fff",
                }}
              >
                <option value="">All Countries</option>
                {leadCountries.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </div>

            {leadLoading ? (
              <p style={{ color: "#6b7280", padding: "1rem 0" }}>Loading panelist leads...</p>
            ) : panelLeads.length === 0 ? (
              <p style={{ color: "#6b7280", padding: "1rem 0" }}>No parsing-page mail IDs found.</p>
            ) : (
              <>
                <div style={{ overflowX: "auto" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse" }}>
                    <thead>
                      <tr style={{ borderBottom: "2px solid #e5e7eb" }}>
                        <th style={{ ...thStyle, fontWeight: "700", color: "#111827", minWidth: "220px" }}>Email</th>
                        <th style={{ ...thStyle, fontWeight: "700", color: "#111827", minWidth: "120px" }}>Country</th>
                        <th style={thStyle}>Respondent ID</th>
                        <th style={thStyle}>Vendor ID</th>
                        <th style={thStyle}>Status</th>
                        <th style={thStyle}>Collected</th>
                      </tr>
                    </thead>
                    <tbody>
                      {panelLeads.map((lead, index) => (
                        <tr key={lead._id || lead.id || index} style={{ borderBottom: "1px solid #f3f4f6" }}>
                          <td style={{ ...tdStyle, fontWeight: "600", color: "#1f2937" }}>{lead.email || "-"}</td>
                          <td style={{ ...tdStyle, fontWeight: "600", color: "#1f2937" }}>
                            {lead.countryCode ? (
                              <span style={{
                                display: "inline-flex", alignItems: "center", gap: "0.25rem",
                                background: "#eff6ff", color: "#1e40af", padding: "0.2rem 0.6rem",
                                borderRadius: "9999px", fontSize: "0.8rem", fontWeight: "600",
                              }}>
                                {lead.countryCode}
                              </span>
                            ) : "-"}
                          </td>
                          <td style={tdStyle}>{lead.respondentId || "-"}</td>
                          <td style={tdStyle}>{lead.vendorId || "-"}</td>
                          <td style={tdStyle}>
                            <span style={{
                              fontSize: "0.75rem", padding: "0.2rem 0.6rem", borderRadius: "9999px",
                              backgroundColor: lead.status === "COMPLETE" ? "#d1fae5" : lead.status === "INCOMPLETE" ? "#fef3c7" : "#e5e7eb",
                              color: lead.status === "COMPLETE" ? "#065f46" : lead.status === "INCOMPLETE" ? "#92400e" : "#374151",
                            }}>
                              {lead.status || "-"}
                            </span>
                          </td>
                          <td style={tdStyle}>
                            {lead.createdAt ? new Date(lead.createdAt).toLocaleDateString() : "-"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "1rem" }}>
                  <span style={{ fontSize: "0.875rem", color: "#6b7280" }}>
                    Total: {leadTotal} unique mail IDs | Page {leadPage} of {totalLeadPages}
                  </span>
                  <div style={{ display: "flex", gap: "0.5rem" }}>
                    <button
                      className="btn btn-outline"
                      disabled={leadPage <= 1}
                      onClick={() => setLeadPage(leadPage - 1)}
                    >
                      Previous
                    </button>
                    <button
                      className="btn btn-outline"
                      disabled={leadPage >= totalLeadPages}
                      onClick={() => setLeadPage(leadPage + 1)}
                    >
                      Next
                    </button>
                  </div>
                </div>
              </>
            )}
          </div>
        )}

        {/* Panelist Approved Tab */}
        {activeTab === "panelist-approved" && (
          <div>
            <div style={{ display: "flex", gap: "0.75rem", marginBottom: "1rem", flexWrap: "wrap" }}>
              <form onSubmit={handleSearchPanelists} style={{ display: "flex", gap: "0.75rem", flex: 1, minWidth: "250px" }}>
                <input
                  type="text"
                  placeholder="Search approved panelists by email, name, country..."
                  value={panelistSearch}
                  onChange={(e) => setPanelistSearch(e.target.value)}
                  style={{
                    flex: 1, padding: "0.625rem 1rem", border: "1px solid #d1d5db",
                    borderRadius: "6px", fontSize: "0.875rem",
                  }}
                />
                <button type="submit" className="btn btn-primary">Search</button>
              </form>
              <select
                value={countryFilter}
                onChange={(e) => { setCountryFilter(e.target.value); setPanelistPage(1) }}
                style={{
                  padding: "0.625rem 1rem", border: "1px solid #d1d5db",
                  borderRadius: "6px", fontSize: "0.875rem", minWidth: "180px",
                  backgroundColor: "#fff",
                }}
              >
                <option value="">All Countries</option>
                {availableCountries.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </div>

            {panelistLoading ? (
              <p style={{ color: "#6b7280", padding: "1rem 0" }}>Loading approved panelists...</p>
            ) : panelists.length === 0 ? (
              <p style={{ color: "#6b7280", padding: "1rem 0" }}>No approved panelists found.</p>
            ) : (
              <>
                <div style={{ overflowX: "auto" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse" }}>
                    <thead>
                      <tr style={{ borderBottom: "2px solid #e5e7eb" }}>
                        <th style={{ ...thStyle, fontWeight: "700", color: "#111827", minWidth: "220px" }}>Email</th>
                        <th style={{ ...thStyle, fontWeight: "700", color: "#111827", minWidth: "120px" }}>Country</th>
                        <th style={thStyle}>Name</th>
                        <th style={thStyle}>Status</th>
                        <th style={thStyle}>Verified</th>
                        <th style={thStyle}>Bounce Status</th>
                        <th style={thStyle}>Joined</th>
                        <th style={thStyle}>Email Sent Date</th>
                        <th style={thStyle}>Email Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {panelists.map((panelist, index) => {
                        const emailStatusBadge = getEmailStatusBadge(panelist.email_status)
                        return (
                          <tr key={panelist._id || panelist.id || index} style={{ borderBottom: "1px solid #f3f4f6" }}>
                            <td style={{ ...tdStyle, fontWeight: "600", color: "#1f2937" }}>{panelist.email || "-"}</td>
                            <td style={{ ...tdStyle, fontWeight: "600", color: "#1f2937" }}>
                              {panelist.country ? (
                                <span style={{
                                  display: "inline-flex", alignItems: "center", gap: "0.25rem",
                                  background: "#eff6ff", color: "#1e40af", padding: "0.2rem 0.6rem",
                                  borderRadius: "9999px", fontSize: "0.8rem", fontWeight: "600",
                                }}>
                                  {panelist.country}
                                </span>
                              ) : "-"}
                            </td>
                            <td style={tdStyle}>{[panelist.first_name, panelist.last_name].filter(Boolean).join(" ") || "-"}</td>
                            <td style={tdStyle}>
                              <span style={{
                                fontSize: "0.75rem", padding: "0.2rem 0.6rem", borderRadius: "9999px",
                                backgroundColor: panelist.status === "active" ? "#d1fae5" : panelist.status === "pending" ? "#fef3c7" : "#fee2e2",
                                color: panelist.status === "active" ? "#065f46" : panelist.status === "pending" ? "#92400e" : "#991b1b",
                              }}>
                                {panelist.status || "active"}
                              </span>
                            </td>
                            <td style={tdStyle}>
                              <span style={{
                                fontSize: "0.75rem", padding: "0.2rem 0.6rem", borderRadius: "9999px",
                                backgroundColor: panelist.email_verified ? "#d1fae5" : "#f3f4f6",
                                color: panelist.email_verified ? "#065f46" : "#6b7280",
                              }}>
                                {panelist.email_verified ? "Verified" : "Unverified"}
                              </span>
                            </td>
                            <td style={tdStyle}>
                              <span style={{
                                fontSize: "0.75rem", padding: "0.25rem 0.65rem", borderRadius: "6px", fontWeight: "600",
                                backgroundColor:
                                  panelist.email_status === "bounced" ? "#fee2e2" :
                                  panelist.email_status === "soft_bounced" ? "#fef3c7" :
                                  panelist.email_status === "complained" ? "#fecaca" :
                                  "#d1fae5",
                                color:
                                  panelist.email_status === "bounced" ? "#991b1b" :
                                  panelist.email_status === "soft_bounced" ? "#92400e" :
                                  panelist.email_status === "complained" ? "#7c2d12" :
                                  "#065f46",
                              }}>
                                {panelist.email_status === "bounced" ? "⚠ BOUNCED" :
                                 panelist.email_status === "soft_bounced" ? "⚠ SOFT BOUNCE" :
                                 panelist.email_status === "complained" ? "⚠ COMPLAINED" :
                                 "✓ OK"}
                              </span>
                            </td>
                            <td style={tdStyle}>
                              {panelist.created_at ? new Date(panelist.created_at).toLocaleDateString() : "-"}
                            </td>
                            <td style={tdStyle}>
                              {panelist.email_sent_date ? new Date(panelist.email_sent_date).toLocaleDateString() : "-"}
                            </td>
                            <td style={tdStyle}>
                              <span style={{
                                fontSize: "0.75rem", padding: "0.2rem 0.6rem", borderRadius: "9999px",
                                backgroundColor: emailStatusBadge.bg,
                                color: emailStatusBadge.text,
                                fontWeight: "600",
                              }}>
                                {emailStatusBadge.label}
                              </span>
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>

                {/* Pagination */}
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "1rem" }}>
                  <span style={{ fontSize: "0.875rem", color: "#6b7280" }}>
                    Total: {panelistTotal} approved panelists | Page {panelistPage} of {totalPanelistPages}
                  </span>
                  <div style={{ display: "flex", gap: "0.5rem" }}>
                    <button
                      className="btn btn-outline"
                      disabled={panelistPage <= 1}
                      onClick={() => setPanelistPage(panelistPage - 1)}
                    >
                      Previous
                    </button>
                    <button
                      className="btn btn-outline"
                      disabled={panelistPage >= totalPanelistPages}
                      onClick={() => setPanelistPage(panelistPage + 1)}
                    >
                      Next
                    </button>
                  </div>
                </div>
              </>
            )}
          </div>
        )}
        {/* SFW Panelists Tab */}
        {activeTab === "sfw-panelists" && (
          <div>
            {/* Filters */}
            <div style={{ display: "flex", gap: "0.75rem", marginBottom: "1rem", flexWrap: "wrap", alignItems: "center" }}>
              <input type="text" placeholder="Search name, email, panelist ID…" value={sfwSearch}
                onChange={(e) => setSfwSearch(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") { setSfwPage(1); fetchSfwPanelists({ page: 1, search: e.target.value }) } }}
                style={{ flex: 1, minWidth: "220px", padding: "0.5rem 0.75rem", border: "1px solid #d1d5db", borderRadius: "6px", fontSize: "0.875rem" }} />
              <select value={sfwCountry} onChange={(e) => { setSfwCountry(e.target.value); setSfwPage(1); fetchSfwPanelists({ page: 1, country: e.target.value }) }}
                style={{ padding: "0.5rem 0.75rem", border: "1px solid #d1d5db", borderRadius: "6px", fontSize: "0.875rem" }}>
                <option value="">All Countries</option>
                {["US","IN","GB","AU","CA","DE","SG","AE"].map(c => <option key={c} value={c}>{c}</option>)}
              </select>
              <button onClick={() => { setSfwPage(1); fetchSfwPanelists({ page: 1 }) }}
                style={{ padding: "0.5rem 1rem", background: "#f97316", color: "#fff", border: "none", borderRadius: "6px", cursor: "pointer", fontSize: "0.875rem", fontWeight: "600" }}>
                ↻ Refresh
              </button>
            </div>

            <p style={{ fontSize: "0.8rem", color: "#9ca3af", marginBottom: "0.75rem" }}>{sfwTotal} panelists {sfwSearch || sfwCountry ? "(filtered)" : ""}</p>

            {/* Table */}
            {sfwLoading ? (
              <p style={{ color: "#6b7280", padding: "2rem 0", textAlign: "center" }}>Loading…</p>
            ) : sfwPanelists.length === 0 ? (
              <p style={{ color: "#6b7280", padding: "2rem 0", textAlign: "center" }}>No panelists found</p>
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.8rem" }}>
                  <thead>
                    <tr style={{ background: "#f9fafb", borderBottom: "2px solid #e5e7eb" }}>
                      {[
                        { label: "Panelist", field: null },
                        { label: "Country", field: null },
                        { label: "Joined ↕", field: "createdAt" },
                        { label: "Total", field: null },
                        { label: "Complete", field: null },
                        { label: "Terminate", field: null },
                        { label: "Quota", field: null },
                        { label: "Rate", field: null },
                        { label: "Earned ↕", field: "totalEarnedPaise" },
                        { label: "Balance ↕", field: "balancePaise" },
                        { label: "Redeemed", field: null },
                        { label: "Last Active ↕", field: "lastActiveAt" },
                      ].map(({ label, field }) => (
                        <th key={label} onClick={field ? () => sfwSort(field) : undefined}
                          style={{ ...thStyle, cursor: field ? "pointer" : "default", whiteSpace: "nowrap", userSelect: "none",
                            color: sfwSortBy === field ? "#f97316" : "#6b7280" }}>
                          {label}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {sfwPanelists.map((p) => {
                      const sv = p.surveys || {}
                      const denom = (sv.complete || 0) + (sv.terminate || 0)
                      const rate = denom ? Math.round((sv.complete / denom) * 100) + "%" : "—"
                      const redeemed = (p.totalEarnedPaise || 0) - (p.balancePaise || 0)
                      return (
                        <tr key={p._id} onClick={() => fetchSfwDetail(p._id)}
                          style={{ borderBottom: "1px solid #f3f4f6", cursor: "pointer" }}
                          onMouseEnter={(e) => e.currentTarget.style.background = "#fff7ed"}
                          onMouseLeave={(e) => e.currentTarget.style.background = ""}>
                          <td style={tdStyle}>
                            <p style={{ fontWeight: "600", color: "#111827" }}>{[p.firstName, p.lastName].filter(Boolean).join(" ") || <span style={{ color: "#9ca3af" }}>unnamed</span>}</p>
                            <p style={{ color: "#9ca3af", fontSize: "0.75rem" }}>{p.email}</p>
                            <p style={{ color: "#d1d5db", fontFamily: "monospace", fontSize: "0.7rem" }}>{p.panelistId || "—"}</p>
                          </td>
                          <td style={tdStyle}>{cname(p.country)}</td>
                          <td style={{ ...tdStyle, whiteSpace: "nowrap", color: "#6b7280" }}>{fmtDate(p.createdAt)}</td>
                          <td style={{ ...tdStyle, textAlign: "center", fontWeight: "600" }}>{sv.total || 0}</td>
                          <td style={{ ...tdStyle, textAlign: "center", color: "#059669", fontWeight: "600" }}>{sv.complete || 0}</td>
                          <td style={{ ...tdStyle, textAlign: "center", color: "#dc2626" }}>{sv.terminate || 0}</td>
                          <td style={{ ...tdStyle, textAlign: "center", color: "#d97706" }}>{sv.quotafull || 0}</td>
                          <td style={{ ...tdStyle, textAlign: "center", color: "#6b7280" }}>{rate}</td>
                          <td style={{ ...tdStyle, textAlign: "right", color: "#111827" }}>{rupees(p.totalEarnedPaise)}</td>
                          <td style={{ ...tdStyle, textAlign: "right", color: "#7c3aed", fontWeight: "600" }}>{rupees(p.balancePaise)}</td>
                          <td style={{ ...tdStyle, textAlign: "right", color: "#6b7280" }}>{rupees(redeemed > 0 ? redeemed : 0)}</td>
                          <td style={{ ...tdStyle, whiteSpace: "nowrap", color: "#9ca3af" }}>{fmtDate(p.lastActiveAt)}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}

            {/* Pagination */}
            {sfwPages > 1 && (
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "1rem", fontSize: "0.875rem", color: "#6b7280" }}>
                <span>Page {sfwPage} of {sfwPages} · {sfwTotal} panelists</span>
                <div style={{ display: "flex", gap: "0.5rem" }}>
                  <button disabled={sfwPage <= 1} onClick={() => { const p = sfwPage - 1; setSfwPage(p); fetchSfwPanelists({ page: p }) }}
                    style={{ padding: "0.4rem 0.8rem", border: "1px solid #d1d5db", borderRadius: "6px", cursor: sfwPage <= 1 ? "default" : "pointer", opacity: sfwPage <= 1 ? 0.4 : 1 }}>
                    ← Prev
                  </button>
                  <button disabled={sfwPage >= sfwPages} onClick={() => { const p = sfwPage + 1; setSfwPage(p); fetchSfwPanelists({ page: p }) }}
                    style={{ padding: "0.4rem 0.8rem", border: "1px solid #d1d5db", borderRadius: "6px", cursor: sfwPage >= sfwPages ? "default" : "pointer", opacity: sfwPage >= sfwPages ? 0.4 : 1 }}>
                    Next →
                  </button>
                </div>
              </div>
            )}

            {/* Detail modal */}
            {(sfwDetail || sfwDetailLoading) && (
              <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)", zIndex: 1000, display: "flex", alignItems: "center", justifyContent: "center", padding: "1rem" }}>
                <div style={{ background: "#fff", borderRadius: "16px", width: "100%", maxWidth: "600px", maxHeight: "85vh", overflow: "hidden", display: "flex", flexDirection: "column", boxShadow: "0 20px 60px rgba(0,0,0,0.3)" }}>
                  <div style={{ padding: "1.25rem 1.5rem", borderBottom: "1px solid #f3f4f6", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <h3 style={{ fontWeight: "700", color: "#111827", margin: 0 }}>Panelist Detail</h3>
                    <button onClick={() => setSfwDetail(null)} style={{ background: "none", border: "none", cursor: "pointer", fontSize: "1.25rem", color: "#9ca3af" }}>✕</button>
                  </div>
                  <div style={{ overflowY: "auto", padding: "1.5rem", flex: 1 }}>
                    {sfwDetailLoading ? (
                      <p style={{ textAlign: "center", color: "#6b7280" }}>Loading…</p>
                    ) : sfwDetail && (
                      <>
                        <div style={{ display: "flex", gap: "1rem", alignItems: "flex-start", marginBottom: "1.5rem" }}>
                          <div style={{ width: "48px", height: "48px", borderRadius: "50%", background: "#f3e8ff", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: "700", fontSize: "1.25rem", color: "#7c3aed", flexShrink: 0 }}>
                            {(sfwDetail.user?.firstName?.[0] || sfwDetail.user?.email?.[0] || "?").toUpperCase()}
                          </div>
                          <div>
                            <p style={{ fontWeight: "700", color: "#111827", fontSize: "1rem" }}>{[sfwDetail.user?.firstName, sfwDetail.user?.lastName].filter(Boolean).join(" ") || "—"}</p>
                            <p style={{ color: "#6b7280", fontSize: "0.875rem" }}>{sfwDetail.user?.email}</p>
                            <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.5rem", flexWrap: "wrap" }}>
                              <span style={{ fontSize: "0.75rem", padding: "0.2rem 0.6rem", background: "#f3f4f6", borderRadius: "99px", fontFamily: "monospace" }}>{sfwDetail.user?.panelistId || "no-id"}</span>
                              {sfwDetail.user?.country && <span style={{ fontSize: "0.75rem", padding: "0.2rem 0.6rem", background: "#e0f2fe", color: "#0369a1", borderRadius: "99px" }}>{cname(sfwDetail.user.country)}</span>}
                              <span style={{ fontSize: "0.75rem", padding: "0.2rem 0.6rem", background: "#fef3c7", color: "#92400e", borderRadius: "99px", textTransform: "capitalize" }}>{sfwDetail.user?.level || "bronze"}</span>
                            </div>
                          </div>
                        </div>

                        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "0.75rem", marginBottom: "1.5rem" }}>
                          {[
                            { label: "Balance", value: rupees(sfwDetail.user?.balancePaise) },
                            { label: "Total Earned", value: rupees(sfwDetail.user?.totalEarnedPaise) },
                            { label: "Redeemed", value: rupees(Math.max(0, (sfwDetail.user?.totalEarnedPaise || 0) - (sfwDetail.user?.balancePaise || 0))) },
                            { label: "Referrals", value: sfwDetail.user?.confirmedReferralCount || 0 },
                            { label: "Profile %", value: `${sfwDetail.user?.profileQuestionCompletion || 0}%` },
                            { label: "Joined", value: fmtDate(sfwDetail.user?.createdAt) },
                          ].map(({ label, value }) => (
                            <div key={label} style={{ background: "#f9fafb", borderRadius: "8px", padding: "0.75rem" }}>
                              <p style={{ fontSize: "0.7rem", color: "#9ca3af", marginBottom: "0.25rem" }}>{label}</p>
                              <p style={{ fontWeight: "600", color: "#111827", fontSize: "0.875rem" }}>{value}</p>
                            </div>
                          ))}
                        </div>

                        <p style={{ fontWeight: "700", color: "#374151", marginBottom: "0.75rem", fontSize: "0.875rem" }}>Survey Stats</p>
                        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "0.5rem", marginBottom: "0.75rem" }}>
                          {[
                            { label: "Total", value: sfwDetail.survey_stats?.total || 0, color: "#111827" },
                            { label: "Complete", value: sfwDetail.survey_stats?.complete || 0, color: "#059669" },
                            { label: "Terminate", value: sfwDetail.survey_stats?.terminate || 0, color: "#dc2626" },
                            { label: "Quota", value: sfwDetail.survey_stats?.quotafull || 0, color: "#d97706" },
                          ].map(({ label, value, color }) => (
                            <div key={label} style={{ background: "#f9fafb", borderRadius: "8px", padding: "0.75rem", textAlign: "center" }}>
                              <p style={{ fontSize: "1.25rem", fontWeight: "700", color }}>{value}</p>
                              <p style={{ fontSize: "0.7rem", color: "#9ca3af" }}>{label}</p>
                            </div>
                          ))}
                        </div>
                        <p style={{ fontSize: "0.75rem", color: "#9ca3af", marginBottom: "1.5rem" }}>
                          Points from surveys: {rupees(sfwDetail.survey_stats?.points_earned)}
                        </p>

                        {sfwDetail.recent_surveys?.length > 0 && (
                          <>
                            <p style={{ fontWeight: "700", color: "#374151", marginBottom: "0.75rem", fontSize: "0.875rem" }}>Recent Survey Activity</p>
                            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.75rem" }}>
                              <thead>
                                <tr style={{ background: "#f9fafb" }}>
                                  {["Survey ID", "Status", "Points", "Date"].map(h => (
                                    <th key={h} style={{ ...thStyle, fontSize: "0.7rem", padding: "0.5rem 0.75rem" }}>{h}</th>
                                  ))}
                                </tr>
                              </thead>
                              <tbody>
                                {sfwDetail.recent_surveys.map((s, i) => (
                                  <tr key={i} style={{ borderBottom: "1px solid #f3f4f6" }}>
                                    <td style={{ ...tdStyle, fontFamily: "monospace", fontSize: "0.7rem", color: "#6b7280", padding: "0.5rem 0.75rem" }}>{s.surveyId || s.rid}</td>
                                    <td style={{ ...tdStyle, padding: "0.5rem 0.75rem" }}>
                                      <span style={{ padding: "0.15rem 0.5rem", borderRadius: "99px", fontSize: "0.7rem", fontWeight: "600",
                                        background: s.status === "complete" ? "#d1fae5" : s.status === "terminate" ? "#fee2e2" : "#fef3c7",
                                        color: s.status === "complete" ? "#065f46" : s.status === "terminate" ? "#991b1b" : "#92400e" }}>
                                        {s.status}
                                      </span>
                                    </td>
                                    <td style={{ ...tdStyle, textAlign: "right", padding: "0.5rem 0.75rem", color: "#111827" }}>{s.pointsEarned > 0 ? rupees(s.pointsEarned) : "—"}</td>
                                    <td style={{ ...tdStyle, textAlign: "right", padding: "0.5rem 0.75rem", color: "#9ca3af", whiteSpace: "nowrap" }}>{fmtTime(s.completedAt)}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </>
                        )}
                      </>
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

      </div>

      {/* Test Email Modal */}
      {showTestEmailModal && (
        <div
          style={{
            position: "fixed", top: 0, left: 0, right: 0, bottom: 0,
            backgroundColor: "rgba(0,0,0,0.5)", display: "flex",
            alignItems: "center", justifyContent: "center", zIndex: 1000,
          }}
          onClick={() => !testEmailLoading && setShowTestEmailModal(false)}
        >
          <div
            style={{
              backgroundColor: "#fff", borderRadius: "12px", padding: "2rem",
              maxWidth: "440px", width: "90%", boxShadow: "0 20px 60px rgba(0,0,0,0.2)",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <h3 style={{ fontSize: "1.25rem", fontWeight: "700", marginBottom: "0.75rem", color: "#111827" }}>
              Send Test Invitation Email
            </h3>
            <p style={{ color: "#6b7280", fontSize: "0.875rem", marginBottom: "1.25rem", lineHeight: "1.5" }}>
              Preview the invite email by sending it to any address. Sent from <strong>panel@surveyfieldwork.com</strong> via SES.
            </p>

            <div style={{ marginBottom: "1rem" }}>
              <label style={{ display: "block", fontSize: "0.875rem", fontWeight: "600", color: "#374151", marginBottom: "0.4rem" }}>
                Recipient Email <span style={{ color: "#ef4444" }}>*</span>
              </label>
              <input
                type="email"
                value={testEmailAddress}
                onChange={(e) => setTestEmailAddress(e.target.value)}
                placeholder="you@example.com"
                style={{
                  width: "100%", padding: "0.5rem 0.75rem", border: "1px solid #d1d5db",
                  borderRadius: "6px", fontSize: "0.9rem", boxSizing: "border-box",
                }}
              />
            </div>

            <div style={{ marginBottom: "1.5rem" }}>
              <label style={{ display: "block", fontSize: "0.875rem", fontWeight: "600", color: "#374151", marginBottom: "0.4rem" }}>
                First Name (optional)
              </label>
              <input
                type="text"
                value={testEmailName}
                onChange={(e) => setTestEmailName(e.target.value)}
                placeholder="e.g. Alex"
                style={{
                  width: "100%", padding: "0.5rem 0.75rem", border: "1px solid #d1d5db",
                  borderRadius: "6px", fontSize: "0.9rem", boxSizing: "border-box",
                }}
              />
            </div>

            {testEmailResult && (
              <div style={{
                padding: "0.75rem 1rem", borderRadius: "8px", marginBottom: "1.25rem",
                backgroundColor: testEmailResult.success ? "#d1fae5" : "#fee2e2",
                color: testEmailResult.success ? "#065f46" : "#991b1b",
                fontSize: "0.875rem",
              }}>
                {testEmailResult.message}
              </div>
            )}

            <div style={{ display: "flex", gap: "0.75rem", justifyContent: "flex-end" }}>
              <button
                className="btn btn-outline"
                onClick={() => setShowTestEmailModal(false)}
                disabled={testEmailLoading}
              >
                Close
              </button>
              <button
                className="btn btn-primary"
                onClick={handleSendTestEmail}
                disabled={testEmailLoading || !testEmailAddress.includes("@")}
                style={{ opacity: testEmailLoading || !testEmailAddress.includes("@") ? 0.5 : 1 }}
              >
                {testEmailLoading ? "Sending..." : "Send Test Email"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Send Invitations Modal */}
      {showInviteModal && (
        <div
          style={{
            position: "fixed", top: 0, left: 0, right: 0, bottom: 0,
            backgroundColor: "rgba(0,0,0,0.5)", display: "flex",
            alignItems: "center", justifyContent: "center", zIndex: 1000,
          }}
          onClick={() => !inviteLoading && setShowInviteModal(false)}
        >
          <div
            style={{
              backgroundColor: "#fff", borderRadius: "12px", padding: "2rem",
              maxWidth: "480px", width: "90%", boxShadow: "0 20px 60px rgba(0,0,0,0.2)",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <h3 style={{ fontSize: "1.25rem", fontWeight: "700", marginBottom: "0.75rem", color: "#111827" }}>
              Send Invitation Emails
            </h3>

            {!inviteResult ? (
              <>
                <p style={{ color: "#6b7280", fontSize: "0.9rem", marginBottom: "1rem", lineHeight: "1.5" }}>
                  {countryFilter
                    ? `Send invitation emails to ${inviteCount} eligible panelists in ${countryFilter}.`
                    : `Send invitation emails to ${inviteCount} eligible panelists across all countries.`}
                </p>
                <p style={{ color: "#9ca3af", fontSize: "0.8rem", marginBottom: "1.5rem" }}>
                  Suppressed (bounced/complained) and already-invited panelists will be skipped automatically.
                </p>
                <div style={{ display: "flex", gap: "0.75rem", justifyContent: "flex-end" }}>
                  <button
                    className="btn btn-outline"
                    onClick={() => setShowInviteModal(false)}
                    disabled={inviteLoading}
                  >
                    Cancel
                  </button>
                  <button
                    className="btn btn-primary"
                    onClick={handleConfirmSendInvitations}
                    disabled={inviteLoading || inviteCount === 0}
                    style={{ background: "#059669", borderColor: "#059669", opacity: inviteLoading || inviteCount === 0 ? 0.5 : 1 }}
                  >
                    {inviteLoading ? "Sending..." : `Send to ${inviteCount} Panelists`}
                  </button>
                </div>
              </>
            ) : (
              <>
                <div style={{
                  padding: "1rem",
                  borderRadius: "8px",
                  backgroundColor: inviteResult.success ? "#d1fae5" : "#fee2e2",
                  color: inviteResult.success ? "#065f46" : "#991b1b",
                  fontSize: "0.9rem",
                  marginBottom: "1.5rem",
                  lineHeight: "1.5",
                }}>
                  {inviteResult.message}
                </div>
                <div style={{ display: "flex", justifyContent: "flex-end" }}>
                  <button className="btn btn-primary" onClick={() => setShowInviteModal(false)}>
                    Close
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

const thStyle = { textAlign: "left", padding: "0.75rem", fontSize: "0.875rem", color: "#6b7280" }
const tdStyle = { padding: "0.75rem", fontSize: "0.875rem" }

export default PanelistManagement
