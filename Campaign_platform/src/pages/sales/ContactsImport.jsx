import { useState, useRef, useEffect } from "react"
import { useNavigate } from "react-router-dom"
import Papa from "papaparse"
import { API_BASE_URL as API_BASE } from "../../config"

// Database fields for contacts
const DB_FIELDS = [
  { key: "email", label: "Email", required: true },
  { key: "firstName", label: "First Name", required: false },
  { key: "lastName", label: "Last Name", required: false },
  { key: "name", label: "Full Name", required: false },
  { key: "phone", label: "Phone", required: false },
  { key: "company", label: "Company", required: false },
  { key: "title", label: "Job Title", required: false },
  { key: "address", label: "Address", required: false },
  { key: "city", label: "City", required: false },
  { key: "state", label: "State", required: false },
  { key: "country", label: "Country", required: false },
  { key: "postalCode", label: "Postal Code", required: false },
  { key: "notes", label: "Notes", required: false },
  { key: "tags", label: "Tags", required: false },
  { key: "source", label: "Source", required: false },
]

// Common column name variations for auto-matching
const COLUMN_ALIASES = {
  email: ["email", "email_address", "emailaddress", "e-mail", "mail", "contact_email"],
  firstName: ["firstname", "first_name", "first", "fname", "given_name", "givenname"],
  lastName: ["lastname", "last_name", "last", "lname", "surname", "family_name", "familyname"],
  name: ["name", "full_name", "fullname", "contact_name", "contactname", "display_name"],
  phone: ["phone", "phone_number", "phonenumber", "mobile", "mobile_number", "cell", "telephone", "tel", "contact_number"],
  company: ["company", "company_name", "companyname", "organization", "org", "business", "employer"],
  title: ["title", "job_title", "jobtitle", "position", "role", "designation"],
  address: ["address", "street", "street_address", "address_line_1", "address1", "line1"],
  city: ["city", "town", "locality"],
  state: ["state", "province", "region", "state_province"],
  country: ["country", "nation", "country_name"],
  postalCode: ["postalcode", "postal_code", "zip", "zipcode", "zip_code", "pincode", "pin_code"],
  notes: ["notes", "note", "comments", "comment", "remarks", "description"],
  tags: ["tags", "tag", "labels", "label", "categories", "category"],
  source: ["source", "lead_source", "leadsource", "origin", "channel"],
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

function ContactsImport() {
  const navigate = useNavigate()
  const fileInputRef = useRef(null)
  
  const [step, setStep] = useState(1) // 1: Upload, 2: Map columns, 3: Preview & Import
  const [file, setFile] = useState(null)
  const [csvData, setCsvData] = useState([])
  const [csvColumns, setCsvColumns] = useState([])
  const [columnMapping, setColumnMapping] = useState({})
  const [selectedList, setSelectedList] = useState("")
  const [lists, setLists] = useState([])
  const [importing, setImporting] = useState(false)
  const [importResult, setImportResult] = useState(null)
  const [error, setError] = useState("")

  // Fetch available lists on mount
  useEffect(() => {
    fetchLists()
  }, [])

  const fetchLists = async () => {
    try {
      const res = await fetch(`${API_BASE}/lists/`)
      if (res.ok) {
        const data = await res.json()
        setLists(data)
      }
    } catch (err) {
      console.error("Failed to fetch lists:", err)
    }
  }

  const handleFileSelect = (e) => {
    const selectedFile = e.target.files[0]
    if (!selectedFile) return
    
    if (!selectedFile.name.endsWith(".csv")) {
      setError("Please select a CSV file")
      return
    }
    
    setError("")
    setFile(selectedFile)
    
    // Parse CSV to get columns and preview data
    Papa.parse(selectedFile, {
      header: true,
      skipEmptyLines: true,
      complete: (results) => {
        if (results.errors.length > 0) {
          setError("Error parsing CSV: " + results.errors[0].message)
          return
        }
        
        const columns = results.meta.fields || []
        const data = results.data.slice(0, 100) // Preview first 100 rows
        
        setCsvColumns(columns)
        setCsvData(data)
        
        // Auto-match columns
        const autoMapping = autoMatchColumns(columns)
        setColumnMapping(autoMapping)
        
        // Move to mapping step
        setStep(2)
      },
      error: (err) => {
        setError("Error reading file: " + err.message)
      },
    })
  }

  const handleMappingChange = (dbField, csvColumn) => {
    setColumnMapping((prev) => ({
      ...prev,
      [dbField]: csvColumn || undefined,
    }))
  }

  const handleDownloadTemplate = () => {
    const templateHeaders = DB_FIELDS.map((f) => f.key).join(",")
    const sampleRow = "john@example.com,John,Doe,John Doe,+1234567890,Acme Inc,Manager,123 Main St,New York,NY,USA,10001,Imported from campaign,lead,website"
    const csvContent = `${templateHeaders}\n${sampleRow}`
    
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" })
    const url = URL.createObjectURL(blob)
    const link = document.createElement("a")
    link.href = url
    link.download = "contacts_import_template.csv"
    link.click()
    URL.revokeObjectURL(url)
  }

  const handleImport = async () => {
    // Validate required fields
    if (!columnMapping.email) {
      setError("Email field mapping is required")
      return
    }
    
    if (!selectedList) {
      setError("Please select a list to import contacts into")
      return
    }
    
    setImporting(true)
    setError("")
    
    try {
      // Transform data using mapping
      const transformedContacts = csvData.map((row) => {
        const contact = {
          listId: selectedList,
        }
        
        DB_FIELDS.forEach((field) => {
          const csvCol = columnMapping[field.key]
          if (csvCol && row[csvCol] !== undefined) {
            contact[field.key] = row[csvCol]
          }
        })
        
        return contact
      })
      
      // Send to backend
      const res = await fetch(`${API_BASE}/upload-csv/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ contacts: transformedContacts }),
      })
      
      if (!res.ok) {
        const errData = await res.json()
        throw new Error(errData.detail || "Import failed")
      }
      
      const result = await res.json()
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

  return (
    <div className="p-6 max-w-5xl mx-auto">
      {/* Header */}
      <div className="mb-6">
        <button
          onClick={() => navigate("/admin/sales/contacts")}
          className="text-gray-600 hover:text-gray-900 flex items-center gap-2 mb-4"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
          </svg>
          Back to Contacts
        </button>
        <h1 className="text-2xl font-bold text-gray-900">Import Contacts</h1>
        <p className="text-gray-600 mt-1">Upload a CSV file to import contacts into your lists</p>
      </div>

      {/* Progress Steps */}
      <div className="flex items-center mb-8">
        {[
          { num: 1, label: "Upload File" },
          { num: 2, label: "Map Columns" },
          { num: 3, label: "Complete" },
        ].map((s, idx) => (
          <div key={s.num} className="flex items-center">
            <div
              className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium ${
                step >= s.num ? "bg-blue-600 text-white" : "bg-gray-200 text-gray-600"
              }`}
            >
              {step > s.num ? (
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
              ) : (
                s.num
              )}
            </div>
            <span className={`ml-2 text-sm ${step >= s.num ? "text-gray-900 font-medium" : "text-gray-500"}`}>
              {s.label}
            </span>
            {idx < 2 && <div className={`w-16 h-0.5 mx-4 ${step > s.num ? "bg-blue-600" : "bg-gray-200"}`} />}
          </div>
        ))}
      </div>

      {/* Error Message */}
      {error && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700 flex items-start gap-3">
          <svg className="w-5 h-5 mt-0.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
            />
          </svg>
          <span>{error}</span>
        </div>
      )}

      {/* Step 1: Upload File */}
      {step === 1 && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-8">
          <div className="text-center mb-8">
            <div className="w-16 h-16 bg-blue-50 rounded-full flex items-center justify-center mx-auto mb-4">
              <svg className="w-8 h-8 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
                />
              </svg>
            </div>
            <h2 className="text-lg font-semibold text-gray-900 mb-2">Upload your CSV file</h2>
            <p className="text-gray-600">Select a CSV file containing your contact data</p>
          </div>

          {/* Drop Zone */}
          <div
            onClick={() => fileInputRef.current?.click()}
            className="border-2 border-dashed border-gray-300 rounded-lg p-12 text-center cursor-pointer hover:border-blue-400 hover:bg-blue-50 transition-colors"
          >
            <input ref={fileInputRef} type="file" accept=".csv" onChange={handleFileSelect} className="hidden" />
            <svg className="w-12 h-12 text-gray-400 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M9 13h6m-3-3v6m5 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
              />
            </svg>
            <p className="text-gray-600 mb-2">
              <span className="text-blue-600 font-medium">Click to upload</span> or drag and drop
            </p>
            <p className="text-sm text-gray-500">CSV files only</p>
          </div>

          {/* Template Download */}
          <div className="mt-8 p-4 bg-gray-50 rounded-lg flex items-center justify-between">
            <div>
              <h3 className="font-medium text-gray-900">Need a template?</h3>
              <p className="text-sm text-gray-600">Download our CSV template to format your data correctly</p>
            </div>
            <button
              onClick={handleDownloadTemplate}
              className="px-4 py-2 text-blue-600 hover:text-blue-700 font-medium flex items-center gap-2"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"
                />
              </svg>
              Download Template
            </button>
          </div>
        </div>
      )}

      {/* Step 2: Map Columns */}
      {step === 2 && (
        <div className="space-y-6">
          {/* File Info */}
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-4">
                <div className="w-12 h-12 bg-green-50 rounded-lg flex items-center justify-center">
                  <svg className="w-6 h-6 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                  </svg>
                </div>
                <div>
                  <h3 className="font-medium text-gray-900">{file?.name}</h3>
                  <p className="text-sm text-gray-600">
                    {csvData.length} contacts found • {csvColumns.length} columns detected
                  </p>
                </div>
              </div>
              <button
                onClick={() => {
                  setStep(1)
                  setFile(null)
                  setCsvData([])
                  setCsvColumns([])
                  setColumnMapping({})
                }}
                className="text-gray-500 hover:text-gray-700"
              >
                Change file
              </button>
            </div>
          </div>

          {/* Select List */}
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
            <h3 className="font-medium text-gray-900 mb-4">Select Target List</h3>
            <select
              value={selectedList}
              onChange={(e) => setSelectedList(e.target.value)}
              className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            >
              <option value="">-- Select a list --</option>
              {lists.map((list) => (
                <option key={list._id} value={list._id}>
                  {list.name}
                </option>
              ))}
            </select>
          </div>

          {/* Column Mapping */}
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
            <div className="flex items-center justify-between mb-6">
              <div>
                <h3 className="font-medium text-gray-900">Map Columns</h3>
                <p className="text-sm text-gray-600 mt-1">
                  Match your CSV columns to contact fields. We've auto-matched what we could.
                </p>
              </div>
              <div className="text-sm text-gray-600">
                {getMappingStats().mapped} of {getMappingStats().total} columns mapped
              </div>
            </div>

            <div className="space-y-4">
              {DB_FIELDS.map((field) => (
                <div key={field.key} className="flex items-center gap-4">
                  <div className="w-48">
                    <label className="text-sm font-medium text-gray-700">
                      {field.label}
                      {field.required && <span className="text-red-500 ml-1">*</span>}
                    </label>
                  </div>
                  <div className="flex-1 flex items-center gap-2">
                    <svg className="w-5 h-5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 5l7 7m0 0l-7 7m7-7H3" />
                    </svg>
                    <select
                      value={getMappedValue(field.key)}
                      onChange={(e) => handleMappingChange(field.key, e.target.value)}
                      className={`flex-1 px-4 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 ${
                        getMappedValue(field.key) ? "border-green-300 bg-green-50" : "border-gray-300"
                      }`}
                    >
                      <option value="">-- Do not import --</option>
                      {csvColumns.map((col) => (
                        <option key={col} value={col}>
                          {col}
                        </option>
                      ))}
                    </select>
                    {getMappedValue(field.key) && (
                      <svg className="w-5 h-5 text-green-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                      </svg>
                    )}
                  </div>
                </div>
              ))}
            </div>

            {/* Unmapped Columns Warning */}
            {getUnmappedColumns().length > 0 && (
              <div className="mt-6 p-4 bg-yellow-50 border border-yellow-200 rounded-lg">
                <h4 className="text-sm font-medium text-yellow-800 mb-2">Unmapped columns (will be ignored):</h4>
                <div className="flex flex-wrap gap-2">
                  {getUnmappedColumns().map((col) => (
                    <span key={col} className="px-2 py-1 bg-yellow-100 text-yellow-800 text-sm rounded">
                      {col}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Preview */}
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
            <h3 className="font-medium text-gray-900 mb-4">Preview (First 5 rows)</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-50">
                    {DB_FIELDS.filter((f) => columnMapping[f.key]).map((field) => (
                      <th key={field.key} className="px-4 py-2 text-left font-medium text-gray-700">
                        {field.label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {csvData.slice(0, 5).map((row, idx) => (
                    <tr key={idx} className="border-t border-gray-100">
                      {DB_FIELDS.filter((f) => columnMapping[f.key]).map((field) => (
                        <td key={field.key} className="px-4 py-2 text-gray-600">
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
          <div className="flex items-center justify-between">
            <button
              onClick={() => {
                setStep(1)
                setFile(null)
                setCsvData([])
                setCsvColumns([])
                setColumnMapping({})
              }}
              className="px-6 py-2 text-gray-600 hover:text-gray-900"
            >
              Cancel
            </button>
            <button
              onClick={handleImport}
              disabled={importing || !columnMapping.email || !selectedList}
              className="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed flex items-center gap-2"
            >
              {importing ? (
                <>
                  <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                    <circle
                      className="opacity-25"
                      cx="12"
                      cy="12"
                      r="10"
                      stroke="currentColor"
                      strokeWidth="4"
                      fill="none"
                    />
                    <path
                      className="opacity-75"
                      fill="currentColor"
                      d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                    />
                  </svg>
                  Importing...
                </>
              ) : (
                <>
                  Import {csvData.length} Contacts
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 5l7 7m0 0l-7 7m7-7H3" />
                  </svg>
                </>
              )}
            </button>
          </div>
        </div>
      )}

      {/* Step 3: Complete */}
      {step === 3 && importResult && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-8 text-center">
          <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-6">
            <svg className="w-8 h-8 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <h2 className="text-xl font-semibold text-gray-900 mb-2">Import Complete!</h2>
          <p className="text-gray-600 mb-6">{importResult.message}</p>

          <div className="flex items-center justify-center gap-4">
            <button
              onClick={() => {
                setStep(1)
                setFile(null)
                setCsvData([])
                setCsvColumns([])
                setColumnMapping({})
                setImportResult(null)
                setSelectedList("")
              }}
              className="px-6 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50"
            >
              Import More
            </button>
            <button
              onClick={() => navigate("/admin/sales/contacts")}
              className="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
            >
              View Contacts
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

export default ContactsImport
