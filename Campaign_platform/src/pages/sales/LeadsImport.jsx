"use client"

import { useState, useRef } from "react"
import { useNavigate } from "react-router-dom"
import { API_BASE_URL } from "../../config"
import Papa from "papaparse"
import { buildApiUrl } from "../../config"

// Database fields for leads
const DB_FIELDS = [
  { key: "name", label: "Full Name", required: false },
  { key: "firstName", label: "First Name", required: false },
  { key: "lastName", label: "Last Name", required: false },
  { key: "email", label: "Email", required: true },
  { key: "emailStatus", label: "Email Status", required: false },
  { key: "title", label: "Job Title", required: false },
  { key: "linkedin", label: "LinkedIn URL", required: false },
  { key: "location", label: "Location", required: false },
  { key: "companyName", label: "Company Name", required: false },
  { key: "companyDomain", label: "Company Domain", required: false },
  { key: "companyWebsite", label: "Company Website", required: false },
  { key: "companyEmployeeCount", label: "Employee Count", required: false },
  { key: "companyEmployeeCountRange", label: "Employee Count Range", required: false },
  { key: "companyFounded", label: "Year Founded", required: false },
  { key: "companyIndustry", label: "Industry", required: false },
  { key: "companyType", label: "Company Type", required: false },
  { key: "companyHeadquarters", label: "Headquarters", required: false },
  { key: "companyRevenueRange", label: "Revenue Range", required: false },
  { key: "companyLinkedinUrl", label: "Company LinkedIn", required: false },
  { key: "companyCrunchbaseUrl", label: "Crunchbase URL", required: false },
  { key: "companyFundingRounds", label: "Funding Rounds", required: false },
  { key: "companyLastFundingRoundAmount", label: "Last Funding Amount", required: false },
]

// Common column name variations for auto-matching
const COLUMN_ALIASES = {
  name: ["name", "full_name", "fullname", "contact_name", "contactname"],
  firstName: ["firstname", "first_name", "first", "given_name", "givenname"],
  lastName: ["lastname", "last_name", "last", "surname", "family_name", "familyname"],
  email: ["email", "email_address", "emailaddress", "e-mail", "mail", "work_email", "workemail"],
  emailStatus: ["emailstatus", "email_status", "status", "email_valid", "valid"],
  title: ["title", "job_title", "jobtitle", "position", "role", "designation"],
  linkedin: ["linkedin", "linkedin_url", "linkedinurl", "linkedin_profile", "profile_url"],
  location: ["location", "city", "address", "region", "country", "geo"],
  companyName: ["companyname", "company_name", "company", "organization", "org", "employer", "business_name"],
  companyDomain: ["companydomain", "company_domain", "domain", "website_domain"],
  companyWebsite: ["companywebsite", "company_website", "website", "url", "company_url"],
  companyEmployeeCount: ["companyemployeecount", "company_employee_count", "employees", "employee_count", "headcount", "size"],
  companyEmployeeCountRange: ["companyemployeecountrange", "employee_range", "size_range", "company_size"],
  companyFounded: ["companyfounded", "company_founded", "founded", "year_founded", "founded_year", "established"],
  companyIndustry: ["companyindustry", "company_industry", "industry", "sector", "vertical"],
  companyType: ["companytype", "company_type", "type", "business_type"],
  companyHeadquarters: ["companyheadquarters", "headquarters", "hq", "hq_location", "main_office"],
  companyRevenueRange: ["companyrevenuerange", "revenue_range", "revenue", "annual_revenue"],
  companyLinkedinUrl: ["companylinkedinurl", "company_linkedin", "company_linkedin_url"],
  companyCrunchbaseUrl: ["companycrunchbaseurl", "crunchbase", "crunchbase_url"],
  companyFundingRounds: ["companyfundingrounds", "funding_rounds", "rounds"],
  companyLastFundingRoundAmount: ["companylastfundingroundamount", "last_funding", "funding_amount"],
}

function normalizeColumnName(col) {
  return col.toLowerCase().replace(/[\s\-\.]/g, "_").replace(/[^a-z0-9_]/g, "")
}

function autoMatchColumns(csvColumns) {
  const mapping = {}
  
  csvColumns.forEach((csvCol) => {
    const normalizedCsv = normalizeColumnName(csvCol)
    
    for (const [dbField, aliases] of Object.entries(COLUMN_ALIASES)) {
      if (aliases.some((alias) => normalizedCsv === alias || normalizedCsv.includes(alias))) {
        if (!mapping[dbField]) {
          mapping[dbField] = csvCol
        }
        break
      }
    }
  })
  
  return mapping
}

const styles = {
  container: {
    padding: "1.5rem",
    maxWidth: "1200px",
    margin: "0 auto",
  },
  backButton: {
    display: "flex",
    alignItems: "center",
    gap: "0.5rem",
    color: "#6b7280",
    background: "none",
    border: "none",
    cursor: "pointer",
    padding: "0.5rem 0",
    marginBottom: "1rem",
    fontSize: "0.875rem",
  },
  header: {
    marginBottom: "1.5rem",
  },
  title: {
    fontSize: "1.5rem",
    fontWeight: "700",
    color: "#111827",
    margin: 0,
  },
  subtitle: {
    color: "#6b7280",
    marginTop: "0.25rem",
  },
  progressBar: {
    display: "flex",
    alignItems: "center",
    marginBottom: "2rem",
  },
  step: {
    display: "flex",
    alignItems: "center",
  },
  stepCircle: {
    width: "32px",
    height: "32px",
    borderRadius: "50%",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontSize: "0.875rem",
    fontWeight: "500",
  },
  stepLabel: {
    marginLeft: "0.5rem",
    fontSize: "0.875rem",
  },
  stepConnector: {
    width: "64px",
    height: "2px",
    margin: "0 1rem",
  },
  card: {
    background: "#fff",
    borderRadius: "12px",
    boxShadow: "0 1px 3px rgba(0,0,0,0.1)",
    border: "1px solid #e5e7eb",
    padding: "2rem",
  },
  dropZone: {
    border: "2px dashed #d1d5db",
    borderRadius: "8px",
    padding: "3rem",
    textAlign: "center",
    cursor: "pointer",
    transition: "all 0.2s",
  },
  dropZoneHover: {
    borderColor: "#3b82f6",
    backgroundColor: "#eff6ff",
  },
  templateSection: {
    marginTop: "2rem",
    padding: "1rem",
    backgroundColor: "#f9fafb",
    borderRadius: "8px",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
  },
  fileInfo: {
    display: "flex",
    alignItems: "center",
    gap: "1rem",
    padding: "1rem",
    backgroundColor: "#f0fdf4",
    borderRadius: "8px",
    marginBottom: "1.5rem",
  },
  mappingRow: {
    display: "flex",
    alignItems: "center",
    gap: "1rem",
    padding: "0.75rem 0",
    borderBottom: "1px solid #f3f4f6",
  },
  mappingLabel: {
    width: "200px",
    fontSize: "0.875rem",
    fontWeight: "500",
    color: "#374151",
  },
  mappingSelect: {
    flex: 1,
    padding: "0.5rem 0.75rem",
    borderRadius: "6px",
    border: "1px solid #d1d5db",
    fontSize: "0.875rem",
    backgroundColor: "#fff",
  },
  mappingSelectMapped: {
    borderColor: "#22c55e",
    backgroundColor: "#f0fdf4",
  },
  previewTable: {
    width: "100%",
    borderCollapse: "collapse",
    fontSize: "0.875rem",
  },
  previewTh: {
    textAlign: "left",
    padding: "0.75rem",
    backgroundColor: "#f9fafb",
    borderBottom: "1px solid #e5e7eb",
    fontWeight: "600",
    color: "#374151",
  },
  previewTd: {
    padding: "0.75rem",
    borderBottom: "1px solid #f3f4f6",
    color: "#6b7280",
  },
  btnPrimary: {
    padding: "0.625rem 1.25rem",
    backgroundColor: "#0d6efd",
    color: "#fff",
    border: "none",
    borderRadius: "6px",
    cursor: "pointer",
    fontWeight: "500",
    display: "flex",
    alignItems: "center",
    gap: "0.5rem",
  },
  btnSecondary: {
    padding: "0.625rem 1.25rem",
    backgroundColor: "#fff",
    color: "#374151",
    border: "1px solid #d1d5db",
    borderRadius: "6px",
    cursor: "pointer",
    fontWeight: "500",
    display: "flex",
    alignItems: "center",
    gap: "0.5rem",
  },
  btnDisabled: {
    opacity: 0.5,
    cursor: "not-allowed",
  },
  errorBox: {
    padding: "1rem",
    backgroundColor: "#fef2f2",
    border: "1px solid #fecaca",
    borderRadius: "8px",
    color: "#dc2626",
    marginBottom: "1.5rem",
    display: "flex",
    alignItems: "flex-start",
    gap: "0.75rem",
  },
  successBox: {
    textAlign: "center",
    padding: "2rem",
  },
  actions: {
    display: "flex",
    justifyContent: "space-between",
    marginTop: "2rem",
    paddingTop: "1.5rem",
    borderTop: "1px solid #e5e7eb",
  },
}

function LeadsImport() {
  const navigate = useNavigate()
  const fileInputRef = useRef(null)
  
  const [step, setStep] = useState(1)
  const [file, setFile] = useState(null)
  const [csvData, setCsvData] = useState([])
  const [csvColumns, setCsvColumns] = useState([])
  const [columnMapping, setColumnMapping] = useState({})
  const [importing, setImporting] = useState(false)
  const [importResult, setImportResult] = useState(null)
  const [error, setError] = useState("")
  const [dragOver, setDragOver] = useState(false)

  const handleFileSelect = (selectedFile) => {
    if (!selectedFile) return
    
    if (!selectedFile.name.endsWith(".csv")) {
      setError("Please select a CSV file")
      return
    }
    
    setError("")
    setFile(selectedFile)
    
    Papa.parse(selectedFile, {
      header: true,
      skipEmptyLines: true,
      complete: (results) => {
        if (results.errors.length > 0) {
          setError("Error parsing CSV: " + results.errors[0].message)
          return
        }
        
        const columns = results.meta.fields || []
        const data = results.data
        
        setCsvColumns(columns)
        setCsvData(data)
        
        const autoMapping = autoMatchColumns(columns)
        setColumnMapping(autoMapping)
        
        setStep(2)
      },
      error: (err) => {
        setError("Error reading file: " + err.message)
      },
    })
  }

  const handleDrop = (e) => {
    e.preventDefault()
    setDragOver(false)
    const droppedFile = e.dataTransfer.files[0]
    handleFileSelect(droppedFile)
  }

  const handleDragOver = (e) => {
    e.preventDefault()
    setDragOver(true)
  }

  const handleDragLeave = () => {
    setDragOver(false)
  }

  const handleMappingChange = (dbField, csvColumn) => {
    setColumnMapping((prev) => ({
      ...prev,
      [dbField]: csvColumn || undefined,
    }))
  }

  const handleDownloadTemplate = () => {
    const templateHeaders = DB_FIELDS.map((f) => f.key).join(",")
    const sampleRow = "John Doe,John,Doe,john@example.com,Valid,CEO,https://linkedin.com/in/johndoe,New York,Acme Corp,acme.com,https://acme.com,500,201-500,2010,Technology,Private,San Francisco,10M-50M,https://linkedin.com/company/acme,,2,5000000"
    const csvContent = `${templateHeaders}\n${sampleRow}`
    
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" })
    const url = URL.createObjectURL(blob)
    const link = document.createElement("a")
    link.href = url
    link.download = "leads_import_template.csv"
    link.click()
    URL.revokeObjectURL(url)
  }

  const handleImport = async () => {
    if (!columnMapping.email) {
      setError("Email field mapping is required")
      return
    }
    
    setImporting(true)
    setError("")
    
    try {
      // Create a new CSV with mapped columns
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
      const formDataUpload = new FormData()
      formDataUpload.append("file", blob, "import.csv")
      
      const sessionId = localStorage.getItem("session_id")
      const response = await fetch(buildApiUrl(`/leads/import/csv`), {
        method: "POST",
        headers: {
          Authorization: sessionId,
        },
        body: formDataUpload,
      })
      
      if (!response.ok) {
        const errData = await response.json()
        throw new Error(errData.detail || "Import failed")
      }
      
      const result = await response.json()
      setImportResult(result)
      setStep(4)
      
    } catch (err) {
      setError(err.message || "Import failed")
    } finally {
      setImporting(false)
    }
  }

  const getMappedFieldsCount = () => {
    return Object.values(columnMapping).filter(Boolean).length
  }

  const renderStep = () => {
    switch (step) {
      case 1:
        return (
          <div style={styles.card}>
            <h3 style={{ marginTop: 0 }}>📁 Upload CSV File</h3>
            <p style={{ color: "#6b7280" }}>
              Upload a CSV file containing your leads data. The file should have headers in the first row.
            </p>
            
            {error && (
              <div style={styles.errorBox}>
                <span>⚠️</span>
                <span>{error}</span>
              </div>
            )}
            
            <div
              style={{ ...styles.dropZone, ...(dragOver ? styles.dropZoneHover : {}) }}
              onClick={() => fileInputRef.current?.click()}
              onDrop={handleDrop}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
            >
              <div style={{ fontSize: "3rem", marginBottom: "1rem" }}>📤</div>
              <p style={{ margin: 0, fontWeight: "500" }}>
                Drop your CSV file here, or click to browse
              </p>
              <p style={{ margin: "0.5rem 0 0", color: "#6b7280", fontSize: "0.875rem" }}>
                Supports .csv files up to 500MB
              </p>
              <input
                ref={fileInputRef}
                type="file"
                accept=".csv"
                style={{ display: "none" }}
                onChange={(e) => handleFileSelect(e.target.files[0])}
              />
            </div>
            
            <div style={styles.templateSection}>
              <div>
                <strong>📋 Need a template?</strong>
                <p style={{ margin: "0.25rem 0 0", color: "#6b7280", fontSize: "0.875rem" }}>
                  Download our CSV template with all supported fields
                </p>
              </div>
              <button style={styles.btnSecondary} onClick={handleDownloadTemplate}>
                ⬇️ Download Template
              </button>
            </div>
          </div>
        )
      
      case 2:
        return (
          <div style={styles.card}>
            <div style={styles.fileInfo}>
              <span>📄</span>
              <div>
                <strong>{file?.name}</strong>
                <span style={{ color: "#6b7280", marginLeft: "0.5rem" }}>
                  ({csvData.length} rows, {csvColumns.length} columns)
                </span>
              </div>
            </div>
            
            <h3 style={{ marginTop: 0 }}>🔗 Map Columns</h3>
            <p style={{ color: "#6b7280" }}>
              Match your CSV columns to the lead fields. We've auto-matched {getMappedFieldsCount()} fields.
            </p>
            
            {error && (
              <div style={styles.errorBox}>
                <span>⚠️</span>
                <span>{error}</span>
              </div>
            )}
            
            <div style={{ maxHeight: "400px", overflowY: "auto" }}>
              {DB_FIELDS.map((field) => (
                <div key={field.key} style={styles.mappingRow}>
                  <div style={styles.mappingLabel}>
                    {field.label}
                    {field.required && <span style={{ color: "#dc2626" }}> *</span>}
                  </div>
                  <select
                    style={{
                      ...styles.mappingSelect,
                      ...(columnMapping[field.key] ? styles.mappingSelectMapped : {}),
                    }}
                    value={columnMapping[field.key] || ""}
                    onChange={(e) => handleMappingChange(field.key, e.target.value)}
                  >
                    <option value="">-- Select column --</option>
                    {csvColumns.map((col) => (
                      <option key={col} value={col}>
                        {col}
                      </option>
                    ))}
                  </select>
                </div>
              ))}
            </div>
            
            <div style={styles.actions}>
              <button style={styles.btnSecondary} onClick={() => setStep(1)}>
                ◀ Back
              </button>
              <button
                style={{
                  ...styles.btnPrimary,
                  ...(columnMapping.email ? {} : styles.btnDisabled),
                }}
                onClick={() => setStep(3)}
                disabled={!columnMapping.email}
              >
                Preview ▶
              </button>
            </div>
          </div>
        )
      
      case 3:
        return (
          <div style={styles.card}>
            <h3 style={{ marginTop: 0 }}>👁️ Preview Import</h3>
            <p style={{ color: "#6b7280" }}>
              Review the first 5 rows before importing. {csvData.length} leads will be imported.
            </p>
            
            {error && (
              <div style={styles.errorBox}>
                <span>⚠️</span>
                <span>{error}</span>
              </div>
            )}
            
            <div style={{ overflowX: "auto" }}>
              <table style={styles.previewTable}>
                <thead>
                  <tr>
                    {DB_FIELDS.filter((f) => columnMapping[f.key]).map((field) => (
                      <th key={field.key} style={styles.previewTh}>
                        {field.label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {csvData.slice(0, 5).map((row, idx) => (
                    <tr key={idx}>
                      {DB_FIELDS.filter((f) => columnMapping[f.key]).map((field) => (
                        <td key={field.key} style={styles.previewTd}>
                          {row[columnMapping[field.key]] || "—"}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            
            <div style={styles.actions}>
              <button style={styles.btnSecondary} onClick={() => setStep(2)}>
                ◀ Back
              </button>
              <button
                style={{
                  ...styles.btnPrimary,
                  ...(importing ? styles.btnDisabled : {}),
                }}
                onClick={handleImport}
                disabled={importing}
              >
                {importing ? "⏳ Importing..." : "✅ Import Leads"}
              </button>
            </div>
          </div>
        )
      
      case 4:
        return (
          <div style={styles.card}>
            <div style={styles.successBox}>
              <div style={{ fontSize: "4rem", marginBottom: "1rem" }}>✅</div>
              <h2 style={{ margin: 0, color: "#16a34a" }}>Import Complete!</h2>
              <p style={{ color: "#6b7280", marginTop: "0.5rem" }}>
                {importResult?.imported || 0} leads imported successfully
                {importResult?.skipped > 0 && `, ${importResult.skipped} skipped`}
              </p>
              
              {importResult?.errors?.length > 0 && (
                <div style={{ marginTop: "1rem", textAlign: "left" }}>
                  <p style={{ fontWeight: "500", color: "#dc2626" }}>
                    Some rows had errors:
                  </p>
                  <ul style={{ color: "#6b7280", fontSize: "0.875rem" }}>
                    {importResult.errors.slice(0, 5).map((err, idx) => (
                      <li key={idx}>{err}</li>
                    ))}
                  </ul>
                </div>
              )}
              
              <div style={{ marginTop: "2rem", display: "flex", gap: "1rem", justifyContent: "center" }}>
                <button
                  style={styles.btnSecondary}
                  onClick={() => {
                    setStep(1)
                    setFile(null)
                    setCsvData([])
                    setCsvColumns([])
                    setColumnMapping({})
                    setImportResult(null)
                  }}
                >
                  📁 Import More
                </button>
                <button
                  style={styles.btnPrimary}
                  onClick={() => navigate("/admin/sales/leads")}
                >
                  👥 View Leads
                </button>
              </div>
            </div>
          </div>
        )
      
      default:
        return null
    }
  }

  const renderProgressBar = () => {
    const steps = [
      { num: 1, label: "Upload" },
      { num: 2, label: "Map" },
      { num: 3, label: "Preview" },
      { num: 4, label: "Complete" },
    ]
    
    return (
      <div style={styles.progressBar}>
        {steps.map((s, idx) => (
          <div key={s.num} style={{ display: "flex", alignItems: "center" }}>
            <div style={styles.step}>
              <div
                style={{
                  ...styles.stepCircle,
                  backgroundColor: step >= s.num ? "#3b82f6" : "#e5e7eb",
                  color: step >= s.num ? "#fff" : "#6b7280",
                }}
              >
                {step > s.num ? "✓" : s.num}
              </div>
              <span
                style={{
                  ...styles.stepLabel,
                  color: step >= s.num ? "#111827" : "#6b7280",
                  fontWeight: step === s.num ? "600" : "400",
                }}
              >
                {s.label}
              </span>
            </div>
            {idx < steps.length - 1 && (
              <div
                style={{
                  ...styles.stepConnector,
                  backgroundColor: step > s.num ? "#3b82f6" : "#e5e7eb",
                }}
              />
            )}
          </div>
        ))}
      </div>
    )
  }

  return (
    <div style={styles.container}>
      <button style={styles.backButton} onClick={() => navigate("/admin/sales/leads")}>
        ◀ Back to Leads
      </button>
      
      <div style={styles.header}>
        <h1 style={styles.title}>📥 Import Leads</h1>
        <p style={styles.subtitle}>
          Bulk import leads from a CSV file with smart column mapping
        </p>
      </div>
      
      {renderProgressBar()}
      {renderStep()}
    </div>
  )
}

export default LeadsImport
