import { useState, useEffect, useRef } from "react"
import { buildApiUrl } from "../../config"
import Papa from "papaparse"

const PANEL_ADMIN_API_PREFIX = "/api/panel-admin"

function PanelistManagement() {
  const [activeTab, setActiveTab] = useState("panelist-leads")

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

  const PAGE_SIZE = 20

  useEffect(() => {
    if (activeTab === "panelist-leads") {
      fetchPanelLeads()
    } else if (activeTab === "panelist-approved") {
      fetchPanelists()
    }
  }, [activeTab, leadPage, panelistPage, countryFilter])

  // Fetch distinct countries on mount
  useEffect(() => {
    fetchCountries()
    fetchLeadCountries()
  }, [])

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
        page_size: PAGE_SIZE,
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
        page_size: PAGE_SIZE,
      })
      if (panelistSearch) params.append("search", panelistSearch)
      if (countryFilter) params.append("country", countryFilter)
      params.append("status", "active")

      const res = await fetch(buildApiUrl(`${PANEL_ADMIN_API_PREFIX}/panelists/?${params}`), {
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

      const data = await res.json()
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

      const data = await res.json()
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

  const totalLeadPages = Math.ceil(leadTotal / PAGE_SIZE)
  const totalPanelistPages = Math.ceil(panelistTotal / PAGE_SIZE)

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
        <div style={{ borderBottom: "1px solid #e5e7eb", marginBottom: "1.5rem" }}>
          <button style={tabStyle("panelist-leads")} onClick={() => setActiveTab("panelist-leads")}>
            Panelist Lead
          </button>
          <button style={tabStyle("panelist-approved")} onClick={() => setActiveTab("panelist-approved")}>
            Panelist Approved
          </button>
        </div>

        {/* Panelist Lead Tab */}
        {activeTab === "panelist-leads" && (
          <div>
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
                        <th style={thStyle}>Joined</th>
                      </tr>
                    </thead>
                    <tbody>
                      {panelists.map((panelist, index) => (
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
                            {panelist.created_at ? new Date(panelist.created_at).toLocaleDateString() : "-"}
                          </td>
                        </tr>
                      ))}
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
      </div>

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
