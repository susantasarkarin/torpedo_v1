import { useState, useEffect, useRef } from "react"
import { buildApiUrl } from "../../config"
import Papa from "papaparse"

function PanelistManagement() {
  const [activeTab, setActiveTab] = useState("parsing-leads")

  // Parsing leads state
  const [trafficRecords, setTrafficRecords] = useState([])
  const [trafficPage, setTrafficPage] = useState(1)
  const [trafficTotal, setTrafficTotal] = useState(0)
  const [trafficLoading, setTrafficLoading] = useState(false)
  const [trafficSearch, setTrafficSearch] = useState("")

  // Panelist signups state
  const [panelists, setPanelists] = useState([])
  const [panelistPage, setPanelistPage] = useState(1)
  const [panelistTotal, setPanelistTotal] = useState(0)
  const [panelistLoading, setPanelistLoading] = useState(false)
  const [panelistSearch, setPanelistSearch] = useState("")

  // CSV upload state
  const [showUpload, setShowUpload] = useState(false)
  const [csvData, setCsvData] = useState(null)
  const [csvFileName, setCsvFileName] = useState("")
  const [uploading, setUploading] = useState(false)
  const [uploadResult, setUploadResult] = useState(null)
  const fileInputRef = useRef(null)

  const PAGE_SIZE = 20

  useEffect(() => {
    if (activeTab === "parsing-leads") {
      fetchTrafficRecords()
    } else if (activeTab === "panelist-signups") {
      fetchPanelists()
    }
  }, [activeTab, trafficPage, panelistPage])

  const fetchTrafficRecords = async () => {
    setTrafficLoading(true)
    const sessionId = localStorage.getItem("session_id")
    try {
      const params = new URLSearchParams({
        page: trafficPage,
        page_size: PAGE_SIZE,
      })
      if (trafficSearch) params.append("search", trafficSearch)

      const res = await fetch(buildApiUrl(`/api/traffic/list?${params}`), {
        headers: { Authorization: sessionId },
      })
      if (res.ok) {
        const data = await res.json()
        setTrafficRecords(data.records || data.results || [])
        setTrafficTotal(data.total || 0)
      }
    } catch (err) {
      console.error("Failed to fetch traffic records:", err)
    } finally {
      setTrafficLoading(false)
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

      const res = await fetch(buildApiUrl(`/panel-admin/panelists/?${params}`), {
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

  const handleSearchTraffic = (e) => {
    e.preventDefault()
    setTrafficPage(1)
    fetchTrafficRecords()
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
      const res = await fetch(buildApiUrl("/panel-admin/panelists/upload-csv"), {
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
        // Refresh panelists list
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

  const totalTrafficPages = Math.ceil(trafficTotal / PAGE_SIZE)
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
        <div className="card-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div>
            <h2 className="card-title">Panelist Management</h2>
            <p className="card-description">Manage parsing leads, panelist signups, and bulk uploads.</p>
          </div>
          <button
            className="btn btn-primary"
            onClick={() => setShowUpload(!showUpload)}
          >
            {showUpload ? "Close Upload" : "Upload CSV"}
          </button>
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
          </div>
        )}

        {/* Tabs */}
        <div style={{ borderBottom: "1px solid #e5e7eb", marginBottom: "1.5rem" }}>
          <button style={tabStyle("parsing-leads")} onClick={() => setActiveTab("parsing-leads")}>
            Parsing Leads
          </button>
          <button style={tabStyle("panelist-signups")} onClick={() => setActiveTab("panelist-signups")}>
            Panelist Signups
          </button>
        </div>

        {/* Parsing Leads Tab */}
        {activeTab === "parsing-leads" && (
          <div>
            <form onSubmit={handleSearchTraffic} style={{ display: "flex", gap: "0.75rem", marginBottom: "1rem" }}>
              <input
                type="text"
                placeholder="Search by respondent ID, country, vendor..."
                value={trafficSearch}
                onChange={(e) => setTrafficSearch(e.target.value)}
                style={{
                  flex: 1, padding: "0.625rem 1rem", border: "1px solid #d1d5db",
                  borderRadius: "6px", fontSize: "0.875rem",
                }}
              />
              <button type="submit" className="btn btn-primary">Search</button>
            </form>

            {trafficLoading ? (
              <p style={{ color: "#6b7280", padding: "1rem 0" }}>Loading traffic records...</p>
            ) : trafficRecords.length === 0 ? (
              <p style={{ color: "#6b7280", padding: "1rem 0" }}>No traffic records found.</p>
            ) : (
              <>
                <div style={{ overflowX: "auto" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse" }}>
                    <thead>
                      <tr style={{ borderBottom: "2px solid #e5e7eb" }}>
                        <th style={thStyle}>Respondent ID</th>
                        <th style={thStyle}>Country</th>
                        <th style={thStyle}>Vendor ID</th>
                        <th style={thStyle}>IP Address</th>
                        <th style={thStyle}>Status</th>
                        <th style={thStyle}>Survey ID</th>
                        <th style={thStyle}>Created</th>
                      </tr>
                    </thead>
                    <tbody>
                      {trafficRecords.map((record, index) => (
                        <tr key={record._id || record.id || index} style={{ borderBottom: "1px solid #f3f4f6" }}>
                          <td style={tdStyle}>{record.rid || record.respondent_id || "-"}</td>
                          <td style={tdStyle}>{record.cc || record.country_code || "-"}</td>
                          <td style={tdStyle}>{record.vid || record.vendor_id || "-"}</td>
                          <td style={tdStyle}>{record.client_ip || record.ip || "-"}</td>
                          <td style={tdStyle}>
                            <span style={{
                              fontSize: "0.75rem", padding: "0.2rem 0.6rem", borderRadius: "9999px",
                              backgroundColor: record.status === "complete" ? "#d1fae5" :
                                record.status === "terminated" ? "#fee2e2" :
                                record.status === "allocated" ? "#dbeafe" : "#f3f4f6",
                              color: record.status === "complete" ? "#065f46" :
                                record.status === "terminated" ? "#991b1b" :
                                record.status === "allocated" ? "#1e40af" : "#374151",
                            }}>
                              {record.status || "pending"}
                            </span>
                          </td>
                          <td style={tdStyle}>{record.survey_id || "-"}</td>
                          <td style={tdStyle}>
                            {record.created_at ? new Date(record.created_at).toLocaleString() : "-"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {/* Pagination */}
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "1rem" }}>
                  <span style={{ fontSize: "0.875rem", color: "#6b7280" }}>
                    Total: {trafficTotal} records | Page {trafficPage} of {totalTrafficPages}
                  </span>
                  <div style={{ display: "flex", gap: "0.5rem" }}>
                    <button
                      className="btn btn-outline"
                      disabled={trafficPage <= 1}
                      onClick={() => setTrafficPage(trafficPage - 1)}
                    >
                      Previous
                    </button>
                    <button
                      className="btn btn-outline"
                      disabled={trafficPage >= totalTrafficPages}
                      onClick={() => setTrafficPage(trafficPage + 1)}
                    >
                      Next
                    </button>
                  </div>
                </div>
              </>
            )}
          </div>
        )}

        {/* Panelist Signups Tab */}
        {activeTab === "panelist-signups" && (
          <div>
            <form onSubmit={handleSearchPanelists} style={{ display: "flex", gap: "0.75rem", marginBottom: "1rem" }}>
              <input
                type="text"
                placeholder="Search by name, email, country..."
                value={panelistSearch}
                onChange={(e) => setPanelistSearch(e.target.value)}
                style={{
                  flex: 1, padding: "0.625rem 1rem", border: "1px solid #d1d5db",
                  borderRadius: "6px", fontSize: "0.875rem",
                }}
              />
              <button type="submit" className="btn btn-primary">Search</button>
            </form>

            {panelistLoading ? (
              <p style={{ color: "#6b7280", padding: "1rem 0" }}>Loading panelists...</p>
            ) : panelists.length === 0 ? (
              <p style={{ color: "#6b7280", padding: "1rem 0" }}>No panelists found.</p>
            ) : (
              <>
                <div style={{ overflowX: "auto" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse" }}>
                    <thead>
                      <tr style={{ borderBottom: "2px solid #e5e7eb" }}>
                        <th style={thStyle}>Name</th>
                        <th style={thStyle}>Email</th>
                        <th style={thStyle}>Country</th>
                        <th style={thStyle}>Status</th>
                        <th style={thStyle}>Points</th>
                        <th style={thStyle}>Joined</th>
                      </tr>
                    </thead>
                    <tbody>
                      {panelists.map((p, index) => (
                        <tr key={p._id || p.id || index} style={{ borderBottom: "1px solid #f3f4f6" }}>
                          <td style={tdStyle}>{p.first_name} {p.last_name}</td>
                          <td style={tdStyle}>{p.email}</td>
                          <td style={tdStyle}>{p.country || "-"}</td>
                          <td style={tdStyle}>
                            <span style={{
                              fontSize: "0.75rem", padding: "0.2rem 0.6rem", borderRadius: "9999px",
                              backgroundColor: p.status === "active" ? "#d1fae5" : "#fee2e2",
                              color: p.status === "active" ? "#065f46" : "#991b1b",
                            }}>
                              {p.status || "active"}
                            </span>
                          </td>
                          <td style={tdStyle}>{p.rewards_balance ?? 0}</td>
                          <td style={tdStyle}>
                            {p.created_at ? new Date(p.created_at).toLocaleDateString() : "-"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "1rem" }}>
                  <span style={{ fontSize: "0.875rem", color: "#6b7280" }}>
                    Total: {panelistTotal} panelists | Page {panelistPage} of {totalPanelistPages}
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
    </div>
  )
}

const thStyle = { textAlign: "left", padding: "0.75rem", fontSize: "0.875rem", color: "#6b7280" }
const tdStyle = { padding: "0.75rem", fontSize: "0.875rem" }

export default PanelistManagement
