"use client"

import { useState, useRef } from "react"
import { useNavigate } from "react-router-dom"
import { API_BASE_URL } from "../../config"
import Papa from "papaparse"
import { ArrowLeft, Upload, Download, CheckCircle, AlertCircle, ArrowRight, FileSpreadsheet } from "lucide-react"
import { buildApiUrl } from "../../config"

// Database fields for estimates
const DB_FIELDS = [
  { key: "estimate_number", label: "Estimate Number", required: false },
  { key: "customer_name", label: "Customer Name", required: true },
  { key: "estimate_date", label: "Estimate Date", required: true },
  { key: "expiry_date", label: "Expiry Date", required: false },
  { key: "reference", label: "Reference", required: false },
  { key: "currency_code", label: "Currency", required: false },
  { key: "subtotal", label: "Subtotal", required: false },
  { key: "tax_amount", label: "Tax Amount", required: false },
  { key: "discount_type", label: "Discount Type", required: false },
  { key: "discount_value", label: "Discount Value", required: false },
  { key: "total", label: "Total Amount", required: false },
  { key: "status", label: "Status", required: false },
  { key: "notes", label: "Notes", required: false },
  { key: "terms", label: "Terms", required: false },
]

// Common column name variations for auto-matching
const COLUMN_ALIASES = {
  estimate_number: ["estimate_number", "estimate_no", "estimate no", "estimate#", "est_number", "est_no", "quote_number", "quote_no", "quotation_number", "quotation"],
  customer_name: ["customer_name", "customer", "client_name", "client", "company_name", "company", "bill_to"],
  estimate_date: ["estimate_date", "date", "est_date", "quote_date", "created_date"],
  expiry_date: ["expiry_date", "expiry", "valid_until", "valid_till", "expires_on", "due_date"],
  reference: ["reference", "ref", "ref_no", "reference_number", "po_reference"],
  currency_code: ["currency_code", "currency", "curr"],
  subtotal: ["subtotal", "sub_total", "sub total", "amount_before_tax"],
  tax_amount: ["tax_amount", "tax", "gst", "tax_total", "total_tax"],
  discount_type: ["discount_type", "discount type"],
  discount_value: ["discount_value", "discount", "disc"],
  total: ["total", "total_amount", "grand_total", "amount", "estimate_amount", "quote_amount"],
  status: ["status", "estimate_status", "quote_status"],
  notes: ["notes", "remarks", "comments", "description", "memo"],
  terms: ["terms", "terms_and_conditions", "conditions"],
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
  unmappedWarning: {
    marginTop: "1.5rem",
    padding: "1rem",
    backgroundColor: "#fffbeb",
    border: "1px solid #fde68a",
    borderRadius: "8px",
  },
  actions: {
    display: "flex",
    justifyContent: "space-between",
    marginTop: "2rem",
    paddingTop: "1.5rem",
    borderTop: "1px solid #e5e7eb",
  },
}

function EstimatesImport() {
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
    const sampleRow = "EST-202512-0001,Acme Corporation,2025-12-21,2026-01-20,REF-001,INR,10000,1800,flat,0,11800,draft,Sample estimate notes,Valid for 30 days"
    const csvContent = `${templateHeaders}\n${sampleRow}`
    
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" })
    const url = URL.createObjectURL(blob)
    const link = document.createElement("a")
    link.href = url
    link.download = "estimates_import_template.csv"
    link.click()
    URL.revokeObjectURL(url)
  }

  const handleImport = async () => {
    if (!columnMapping.customer_name) {
      setError("Customer Name field mapping is required")
      return
    }
    
    if (!columnMapping.estimate_date) {
      setError("Estimate Date field mapping is required")
      return
    }
    
    setImporting(true)
    setError("")
    
    try {
      const sessionId = localStorage.getItem("session_id")
      if (!sessionId) {
        navigate("/admin/login")
        return
      }
      
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
      
      const response = await fetch(buildApiUrl(`/finance/estimates/import/csv`), {
        method: "POST",
        headers: {
          Authorization: sessionId,
        },
        body: formDataUpload,
      })
      
      if (response.status === 401) {
        alert("Session expired. Please login again.")
        localStorage.removeItem("session_id")
        navigate("/admin/login")
        return
      }
      
      if (!response.ok) {
        const errData = await response.json()
        throw new Error(errData.detail || "Import failed")
      }
      
      const result = await response.json()
      setImportResult(result)
      setStep(3)
    } catch (err) {
      setError(err.message)
    } finally {
      setImporting(false)
    }
  }

  const getMappedValue = (dbField) => {
    return columnMapping[dbField] || ""
  }

  const getUnmappedColumns = () => {
    const mappedCols = Object.values(columnMapping).filter(Boolean)
    return csvColumns.filter((col) => !mappedCols.includes(col))
  }

  const getMappingStats = () => {
    const mapped = Object.values(columnMapping).filter(Boolean).length
    const required = DB_FIELDS.filter((f) => f.required && columnMapping[f.key]).length
    const requiredTotal = DB_FIELDS.filter((f) => f.required).length
    return { mapped, total: csvColumns.length, required, requiredTotal }
  }

  const resetImport = () => {
    setStep(1)
    setFile(null)
    setCsvData([])
    setCsvColumns([])
    setColumnMapping({})
    setImportResult(null)
    setError("")
  }

  return (
    <div style={styles.container}>
      {/* Back Button */}
      <button style={styles.backButton} onClick={() => navigate("/admin/finance/estimates")}>
        <ArrowLeft style={{ width: "16px", height: "16px" }} />
        Back to Estimates
      </button>

      {/* Header */}
      <div style={styles.header}>
        <h1 style={styles.title}>Import Estimates</h1>
        <p style={styles.subtitle}>Upload a CSV file to import estimates into your database</p>
      </div>

      {/* Progress Steps */}
      <div style={styles.progressBar}>
        {[
          { num: 1, label: "Upload File" },
          { num: 2, label: "Map Columns" },
          { num: 3, label: "Complete" },
        ].map((s, idx) => (
          <div key={s.num} style={styles.step}>
            <div
              style={{
                ...styles.stepCircle,
                backgroundColor: step >= s.num ? "#0d6efd" : "#e5e7eb",
                color: step >= s.num ? "#fff" : "#6b7280",
              }}
            >
              {step > s.num ? <CheckCircle style={{ width: "16px", height: "16px" }} /> : s.num}
            </div>
            <span
              style={{
                ...styles.stepLabel,
                color: step >= s.num ? "#111827" : "#9ca3af",
                fontWeight: step >= s.num ? "500" : "400",
              }}
            >
              {s.label}
            </span>
            {idx < 2 && (
              <div
                style={{
                  ...styles.stepConnector,
                  backgroundColor: step > s.num ? "#0d6efd" : "#e5e7eb",
                }}
              />
            )}
          </div>
        ))}
      </div>

      {/* Error Message */}
      {error && (
        <div style={styles.errorBox}>
          <AlertCircle style={{ width: "20px", height: "20px", flexShrink: 0 }} />
          <span>{error}</span>
        </div>
      )}

      {/* Step 1: Upload File */}
      {step === 1 && (
        <div style={styles.card}>
          <div style={{ textAlign: "center", marginBottom: "2rem" }}>
            <div
              style={{
                width: "64px",
                height: "64px",
                backgroundColor: "#eff6ff",
                borderRadius: "50%",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                margin: "0 auto 1rem",
              }}
            >
              <Upload style={{ width: "32px", height: "32px", color: "#3b82f6" }} />
            </div>
            <h2 style={{ fontSize: "1.125rem", fontWeight: "600", marginBottom: "0.5rem" }}>
              Upload your CSV file
            </h2>
            <p style={{ color: "#6b7280" }}>Select a CSV file containing your estimate data</p>
          </div>

          {/* Drop Zone */}
          <div
            onClick={() => fileInputRef.current?.click()}
            onDrop={handleDrop}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            style={{
              ...styles.dropZone,
              ...(dragOver ? styles.dropZoneHover : {}),
            }}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv"
              onChange={(e) => handleFileSelect(e.target.files[0])}
              style={{ display: "none" }}
            />
            <FileSpreadsheet style={{ width: "48px", height: "48px", color: "#9ca3af", margin: "0 auto 1rem" }} />
            <p style={{ color: "#6b7280", marginBottom: "0.5rem" }}>
              <span style={{ color: "#3b82f6", fontWeight: "500" }}>Click to upload</span> or drag and drop
            </p>
            <p style={{ fontSize: "0.875rem", color: "#9ca3af" }}>CSV files only</p>
          </div>

          {/* Template Download */}
          <div style={styles.templateSection}>
            <div>
              <h3 style={{ fontWeight: "500", color: "#111827", marginBottom: "0.25rem" }}>Need a template?</h3>
              <p style={{ fontSize: "0.875rem", color: "#6b7280" }}>
                Download our CSV template to format your data correctly
              </p>
            </div>
            <button
              onClick={handleDownloadTemplate}
              style={{
                ...styles.btnSecondary,
                color: "#3b82f6",
                borderColor: "#3b82f6",
              }}
            >
              <Download style={{ width: "16px", height: "16px" }} />
              Download Template
            </button>
          </div>
        </div>
      )}

      {/* Step 2: Map Columns */}
      {step === 2 && (
        <div>
          {/* File Info */}
          <div style={styles.fileInfo}>
            <div
              style={{
                width: "48px",
                height: "48px",
                backgroundColor: "#dcfce7",
                borderRadius: "8px",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <CheckCircle style={{ width: "24px", height: "24px", color: "#22c55e" }} />
            </div>
            <div style={{ flex: 1 }}>
              <h3 style={{ fontWeight: "500", color: "#111827" }}>{file?.name}</h3>
              <p style={{ fontSize: "0.875rem", color: "#6b7280" }}>
                {csvData.length} rows found • {csvColumns.length} columns detected
              </p>
            </div>
            <button style={styles.btnSecondary} onClick={resetImport}>
              Change file
            </button>
          </div>

          {/* Column Mapping */}
          <div style={styles.card}>
            <div style={{ marginBottom: "1.5rem" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                  <h3 style={{ fontWeight: "600", color: "#111827" }}>Map Columns</h3>
                  <p style={{ fontSize: "0.875rem", color: "#6b7280", marginTop: "0.25rem" }}>
                    Match your CSV columns to estimate fields. We've auto-matched what we could.
                  </p>
                </div>
                <span style={{ fontSize: "0.875rem", color: "#6b7280" }}>
                  {getMappingStats().mapped} of {csvColumns.length} columns mapped
                </span>
              </div>
            </div>

            <div>
              {DB_FIELDS.map((field) => (
                <div key={field.key} style={styles.mappingRow}>
                  <div style={styles.mappingLabel}>
                    {field.label}
                    {field.required && <span style={{ color: "#dc2626", marginLeft: "4px" }}>*</span>}
                  </div>
                  <ArrowRight style={{ width: "20px", height: "20px", color: "#9ca3af" }} />
                  <select
                    value={getMappedValue(field.key)}
                    onChange={(e) => handleMappingChange(field.key, e.target.value)}
                    style={{
                      ...styles.mappingSelect,
                      ...(getMappedValue(field.key) ? styles.mappingSelectMapped : {}),
                    }}
                  >
                    <option value="">-- Do not import --</option>
                    {csvColumns.map((col) => (
                      <option key={col} value={col}>
                        {col}
                      </option>
                    ))}
                  </select>
                  {getMappedValue(field.key) && (
                    <CheckCircle style={{ width: "20px", height: "20px", color: "#22c55e" }} />
                  )}
                </div>
              ))}
            </div>

            {/* Unmapped Columns Warning */}
            {getUnmappedColumns().length > 0 && (
              <div style={styles.unmappedWarning}>
                <h4 style={{ fontSize: "0.875rem", fontWeight: "500", color: "#92400e", marginBottom: "0.5rem" }}>
                  Unmapped columns (will be ignored):
                </h4>
                <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem" }}>
                  {getUnmappedColumns().map((col) => (
                    <span
                      key={col}
                      style={{
                        padding: "0.25rem 0.5rem",
                        backgroundColor: "#fef3c7",
                        color: "#92400e",
                        fontSize: "0.875rem",
                        borderRadius: "4px",
                      }}
                    >
                      {col}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Preview */}
          <div style={{ ...styles.card, marginTop: "1.5rem" }}>
            <h3 style={{ fontWeight: "600", color: "#111827", marginBottom: "1rem" }}>Preview (First 5 rows)</h3>
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
                          {row[columnMapping[field.key]] || "-"}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Actions */}
          <div style={styles.actions}>
            <button style={styles.btnSecondary} onClick={resetImport}>
              Cancel
            </button>
            <button
              onClick={handleImport}
              disabled={importing || !columnMapping.customer_name || !columnMapping.estimate_date}
              style={{
                ...styles.btnPrimary,
                ...(importing || !columnMapping.customer_name || !columnMapping.estimate_date ? styles.btnDisabled : {}),
              }}
            >
              {importing ? (
                <>
                  <span
                    style={{
                      width: "16px",
                      height: "16px",
                      border: "2px solid #fff",
                      borderTopColor: "transparent",
                      borderRadius: "50%",
                      animation: "spin 1s linear infinite",
                    }}
                  />
                  Importing...
                </>
              ) : (
                <>
                  Import {csvData.length} Estimates
                  <ArrowRight style={{ width: "16px", height: "16px" }} />
                </>
              )}
            </button>
          </div>
        </div>
      )}

      {/* Step 3: Complete */}
      {step === 3 && importResult && (
        <div style={styles.card}>
          <div style={styles.successBox}>
            <div
              style={{
                width: "64px",
                height: "64px",
                backgroundColor: "#dcfce7",
                borderRadius: "50%",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                margin: "0 auto 1.5rem",
              }}
            >
              <CheckCircle style={{ width: "32px", height: "32px", color: "#22c55e" }} />
            </div>
            <h2 style={{ fontSize: "1.25rem", fontWeight: "600", color: "#111827", marginBottom: "0.5rem" }}>
              Import Complete!
            </h2>
            <p style={{ color: "#6b7280", marginBottom: "1.5rem" }}>{importResult.message}</p>

            {importResult.errors && importResult.errors.length > 0 && (
              <div
                style={{
                  textAlign: "left",
                  padding: "1rem",
                  backgroundColor: "#fffbeb",
                  border: "1px solid #fde68a",
                  borderRadius: "8px",
                  marginBottom: "1.5rem",
                  maxHeight: "150px",
                  overflowY: "auto",
                }}
              >
                <h4 style={{ fontSize: "0.875rem", fontWeight: "500", color: "#92400e", marginBottom: "0.5rem" }}>
                  Some rows had issues:
                </h4>
                <ul style={{ fontSize: "0.875rem", color: "#92400e", paddingLeft: "1.25rem", margin: 0 }}>
                  {importResult.errors.slice(0, 10).map((err, idx) => (
                    <li key={idx}>{err}</li>
                  ))}
                  {importResult.errors.length > 10 && (
                    <li>...and {importResult.errors.length - 10} more</li>
                  )}
                </ul>
              </div>
            )}

            <div style={{ display: "flex", justifyContent: "center", gap: "1rem" }}>
              <button style={styles.btnSecondary} onClick={resetImport}>
                Import More
              </button>
              <button style={styles.btnPrimary} onClick={() => navigate("/admin/finance/estimates")}>
                View Estimates
              </button>
            </div>
          </div>
        </div>
      )}

      <style>{`
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  )
}

export default EstimatesImport
