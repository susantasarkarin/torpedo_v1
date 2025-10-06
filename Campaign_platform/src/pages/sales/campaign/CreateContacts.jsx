"use client"

import { useState, useEffect } from "react"
import "./CreateContacts.css"

function CreateContacts({ onBack, listName }) {
  // Added listName prop
  const [currentView, setCurrentView] = useState("methods") // 'methods', 'csv-upload', or 'manual-form'
  const [selectedFile, setSelectedFile] = useState(null)
  const [csvHeaders, setCsvHeaders] = useState([])
  const [businessUnit, setBusinessUnit] = useState("Cogentix research") // Default to first option
  const [fieldMapping, setFieldMapping] = useState({
    email: "",
    firstName: "",
    lastName: "",
    name: "",
    emailStatus: "",
    title: "",
    linkedin: "",
    location: "",
    addedOn: "",
    companyName: "",
    companyDomain: "",
    companyWebsite: "",
    companyEmployeeCount: "",
    companyEmployeeCountRange: "",
    companyFounded: "",
    companyIndustry: "",
    companyType: "",
    companyHeadquarters: "",
    companyRevenueRange: "",
    companyLinkedinUrl: "",
    companyCrunchbaseUrl: "",
    companyFundingRounds: "",
    companyLastFundingRoundAmount: "",
    companyLogoUrlPrimary: "",
    companyLogoUrlSecondary: "",
  })
  const [importedContacts, setImportedContacts] = useState([])
  const [showEmailOptions, setShowEmailOptions] = useState(false)
  const [dbCount, setDbCount] = useState(null)
  const [lastUploadSummary, setLastUploadSummary] = useState(null) // { parsed, inserted, skipped }
  const [csvPreview, setCsvPreview] = useState([]) // first few uploaded contacts for UI preview

  const [manualFormData, setManualFormData] = useState({
    name: "",
    firstName: "",
    lastName: "",
    email: "",
    emailStatus: "subscribed",
    title: "",
    linkedin: "",
    location: "",
    addedOn: new Date().toISOString().split("T")[0],
    companyName: "",
    companyDomain: "",
    companyWebsite: "",
    companyEmployeeCount: "",
    companyEmployeeCountRange: "",
    companyFounded: "",
    companyIndustry: "",
    companyType: "",
    companyHeadquarters: "",
    companyRevenueRange: "",
    companyLinkedinUrl: "",
    companyCrunchbaseUrl: "",
    companyFundingRounds: "",
    companyLastFundingRoundAmount: "",
    companyLogoUrlPrimary: "",
    companyLogoUrlSecondary: "",
    businessUnit: "Cogentix research", // Default to first option
  })

  // Handler for manual form input changes
  const handleManualFormChange = (field, value) => {
    setManualFormData((prev) => ({
      ...prev,
      [field]: value,
    }))
  }

  async function refreshDbCount() {
    if (!listName) return
    try {
      console.log("[v0] fetching Mongo count for list:", listName)
      const r = await fetch(`http://localhost:8000/contact-count?listName=${encodeURIComponent(listName)}`)
      if (!r.ok) throw new Error(`count request failed: ${r.status}`)
      const j = await r.json()
      setDbCount(typeof j?.count === "number" ? j.count : 0)
    } catch (e) {
      console.log("[v0] count fetch failed:", e?.message || e)
      setDbCount(null) // hide the banner if backend not ready
    }
  }

  useEffect(() => {
    refreshDbCount()
  }, [listName])

  useEffect(() => {
    // Add any necessary effect here
  }, [])

  const handleFileSelect = async (event) => {
    const file = event.target.files[0]
    if (file && (file.type === "text/csv" || file.name.endsWith(".csv"))) {
      setSelectedFile(file)

      // Parse CSV headers
      try {
        const text = await file.text()
        const firstLine = text.split("\n")[0]
        const headers = firstLine.split(",").map((header) => header.trim().replace(/"/g, ""))
        setCsvHeaders(headers)
      } catch (error) {
        console.error("Error parsing CSV headers:", error)
        setCsvHeaders([])
      }
    } else {
      alert("Please select a valid CSV file")
    }
  }

  const handleUploadCSV = () => {
    setCurrentView("csv-upload")
  }

  const handleManualForm = () => {
    setCurrentView("manual-form")
  }

  const handleBackToMethods = () => {
    setCurrentView("methods")
    setSelectedFile(null)
    setCsvHeaders([])
    // Reset imported contacts and email options when going back to methods
    setImportedContacts([])
    setShowEmailOptions(false)
    setLastUploadSummary(null)
    setCsvPreview([])
  }

  const handleImportContacts = async () => {
    if (!selectedFile) {
      alert("Please select a CSV file first")
      return
    }

    if (!fieldMapping.email) {
      alert("Please map the Email field before importing contacts")
      return
    }

    if (!listName) {
      alert("No list selected. Please go back and select a list.")
      return
    }

    try {
      // Step 1: Read CSV as text
      const text = await selectedFile.text()

      // Step 2: Parse CSV into rows
      const rows = text
        .split("\n")
        .map((row) => row.trim())
        .filter((r) => r)
      const headers = rows[0].split(",").map((h) => h.trim())
      const dataRows = rows.slice(1)

      console.log("[v0] CSV Headers:", headers)
      console.log("[v0] Field Mapping:", fieldMapping)
      console.log("[v0] List Name:", listName) // Added logging for listName

      // Step 3: Apply field mapping
      const mappedContacts = dataRows.map((row) => {
        const values = row.split(",").map((v) => v.trim())
        const contact = {}

        contact.businessUnit = businessUnit
        contact.listName = listName
        contact.listId = listName // Using listName as listId for now

        Object.entries(fieldMapping).forEach(([field, mappedColumn]) => {
          if (mappedColumn) {
            const colIndex = headers.indexOf(mappedColumn)
            if (colIndex !== -1) {
              contact[field] = values[colIndex] || ""
            }
          }
        })

        return contact
      })

      console.log("[v0] Mapped Contacts:", mappedContacts)
      console.log("[v0] Sample contact:", mappedContacts[0])

      setLastUploadSummary({ parsed: mappedContacts.length, inserted: 0, skipped: 0 })
      setCsvPreview(mappedContacts.slice(0, 5))

      // Step 4: Send mapped data to backend for database storage only
      try {
        const res = await fetch("http://localhost:8000/upload-csv/", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ contacts: mappedContacts }),
        })

        const data = await res.json()
        if (res.ok) {
          const inserted = Array.isArray(data?.contacts) ? data.contacts.length : 0
          const skipped = Math.max(mappedContacts.length - inserted, 0)
          setLastUploadSummary({ parsed: mappedContacts.length, inserted, skipped })
          setImportedContacts(
            Array.isArray(data?.contacts) && data.contacts.length > 0 ? data.contacts : mappedContacts,
          )
          setCsvPreview(
            Array.isArray(data?.contacts) && data.contacts.length > 0
              ? data.contacts.slice(0, 5)
              : mappedContacts.slice(0, 5),
          )
          setShowEmailOptions(true)

          const contactNames = data.contacts
            ?.slice(0, 3)
            .map((c) => c.name || `${c.firstName || ""} ${c.lastName || ""}`.trim() || c.email)
            .join(", ")

          console.log(`[v0] Successfully uploaded ${inserted} contacts: ${contactNames}${inserted > 3 ? "..." : ""}`)

          refreshDbCount()
        } else {
          throw new Error(data.detail || "Upload failed")
        }
      } catch (backendError) {
        console.log("[v0] Backend unavailable, storing contacts locally:", backendError.message)

        // Store in localStorage for persistence
        try {
          const existingContacts = JSON.parse(localStorage.getItem("contactListContacts") || "{}")
          const updatedContacts = {
            ...existingContacts,
            [listName]: [...(existingContacts[listName] || []), ...mappedContacts],
          }
          localStorage.setItem("contactListContacts", JSON.stringify(updatedContacts))

          // Trigger a storage event to update the List component
          window.dispatchEvent(
            new StorageEvent("storage", {
              key: "contactListContacts",
              newValue: JSON.stringify(updatedContacts),
            }),
          )

          setLastUploadSummary({ parsed: mappedContacts.length, inserted: mappedContacts.length, skipped: 0 })
          setImportedContacts(mappedContacts)
          setCsvPreview(mappedContacts.slice(0, 5))
          setShowEmailOptions(true)

          const contactNames = mappedContacts
            .slice(0, 3)
            .map((c) => c.name || `${c.firstName || ""} ${c.lastName || ""}`.trim() || c.email)
            .join(", ")

          console.log(
            `[v0] Successfully stored ${mappedContacts.length} contacts locally: ${contactNames}${mappedContacts.length > 3 ? "..." : ""}`,
          )
          alert(
            `Successfully uploaded ${mappedContacts.length} contacts to "${listName}"! (Stored locally since backend is unavailable)`,
          )
        } catch (storageError) {
          console.error("[v0] Failed to store contacts locally:", storageError)
          alert("Error storing contacts: " + storageError.message)
        }
      }
    } catch (err) {
      console.error("[v0] Import error:", err)
      alert("Error importing contacts: " + err.message)
    }
  }

  const handleSendEmails = async () => {
    if (importedContacts.length === 0) {
      alert("No contacts to send emails to. Please import contacts first.")
      return
    }

    try {
      const res = await fetch("http://localhost:8000/send-emails/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          contacts: importedContacts,
          sendWelcome: document.getElementById("send-welcome")?.checked || false,
          validateEmails: document.getElementById("validate-emails")?.checked || false,
        }),
      })

      const data = await res.json()
      if (res.ok) {
        alert(data.message || "Emails sent successfully!")
        console.log("[v0] Email response:", data)
        // Optionally reset after sending emails
        // setShowEmailOptions(false);
        // setImportedContacts([]);
      } else {
        console.log("[v0] Email error:", data)
        alert("Error: " + (data.detail || "Email sending failed"))
      }
    } catch (err) {
      console.error("[v0] Email error:", err)
      alert("Error sending emails: " + err.message)
    }
  }

  const handleManualFormSubmit = async (e) => {
    e.preventDefault()
    if (!manualFormData.email) {
      alert("Email is required")
      return
    }

    if (!listName) {
      alert("No list selected. Please go back and select a list.")
      return
    }

    try {
      const contactData = {
        ...manualFormData,
        listName: listName,
        listId: listName, // Using listName as listId for consistency
      }

      try {
        const res = await fetch("http://localhost:8000/upload-csv/", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ contacts: [contactData] }),
        })

        const data = await res.json()
        if (res.ok) {
          const contactName =
            contactData.name ||
            `${contactData.firstName || ""} ${contactData.lastName || ""}`.trim() ||
            contactData.email
          console.log(`[v0] Successfully added contact: ${contactName}`)
          alert(`Contact "${contactName}" added successfully!`)

          refreshDbCount()
        } else {
          throw new Error(data.detail || "Failed to add contact")
        }
      } catch (backendError) {
        console.log("[v0] Backend unavailable, storing contact locally:", backendError.message)

        try {
          const existingContacts = JSON.parse(localStorage.getItem("contactListContacts") || "{}")
          const updatedContacts = {
            ...existingContacts,
            [listName]: [...(existingContacts[listName] || []), contactData],
          }
          localStorage.setItem("contactListContacts", JSON.stringify(updatedContacts))

          // Trigger a storage event to update the List component
          window.dispatchEvent(
            new StorageEvent("storage", {
              key: "contactListContacts",
              newValue: JSON.JSON.stringify(updatedContacts),
            }),
          )

          const contactName =
            contactData.name ||
            `${contactData.firstName || ""} ${contactData.lastName || ""}`.trim() ||
            contactData.email
          console.log(`[v0] Successfully stored contact locally: ${contactName}`)
          alert(`Contact "${contactName}" added successfully! (Stored locally since backend is unavailable)`)
        } catch (storageError) {
          console.error("[v0] Failed to store contact locally:", storageError)
          alert("Error storing contact: " + storageError.message)
        }
      }

      // Reset form
      setManualFormData({
        name: "",
        firstName: "",
        lastName: "",
        email: "",
        emailStatus: "subscribed",
        title: "",
        linkedin: "",
        location: "",
        addedOn: new Date().toISOString().split("T")[0],
        companyName: "",
        companyDomain: "",
        companyWebsite: "",
        companyEmployeeCount: "",
        companyEmployeeCountRange: "",
        companyFounded: "",
        companyIndustry: "",
        companyType: "",
        companyHeadquarters: "",
        companyRevenueRange: "",
        companyLinkedinUrl: "",
        companyCrunchbaseUrl: "",
        companyFundingRounds: "",
        companyLastFundingRoundAmount: "",
        companyLogoUrlPrimary: "",
        companyLogoUrlSecondary: "",
        businessUnit: "Cogentix research", // Default to first option
      })
    } catch (err) {
      console.error("[v0] Manual form error:", err)
      alert("Error adding contact: " + err.message)
    }
  }

  if (currentView === "manual-form") {
    return (
      <div className="create-contacts-container">
        <div className="page-header">
          <div className="breadcrumb">
            <button className="breadcrumb-link" onClick={onBack}>
              Lists
            </button>
            <span className="breadcrumb-separator">/</span>
            <button className="breadcrumb-link" onClick={handleBackToMethods}>
              Add Contacts
            </button>
            <span className="breadcrumb-separator">/</span>
            <span className="breadcrumb-current">Manual Form</span>
          </div>
          <h1 className="page-title">Add Contact Manually</h1>
          <p className="page-description">Fill out the form to add a new contact to your list</p>
        </div>

        <div className="csv-upload-container">
          <div className="upload-card">
            <form onSubmit={handleManualFormSubmit}>
              <div className="upload-section">
                <h3 className="section-title">Personal Information</h3>
                <div className="mapping-grid">
                  <div className="mapping-row">
                    <label className="mapping-label">Name</label>
                    <input
                      type="text"
                      value={manualFormData.name}
                      onChange={(e) => handleManualFormChange("name", e.target.value)}
                      className="mapping-select"
                      placeholder="Full name"
                    />
                  </div>
                  <div className="mapping-row">
                    <label className="mapping-label">First Name</label>
                    <input
                      type="text"
                      value={manualFormData.firstName}
                      onChange={(e) => handleManualFormChange("firstName", e.target.value)}
                      className="mapping-select"
                      placeholder="First name"
                    />
                  </div>
                  <div className="mapping-row">
                    <label className="mapping-label">Last Name</label>
                    <input
                      type="text"
                      value={manualFormData.lastName}
                      onChange={(e) => handleManualFormChange("lastName", e.target.value)}
                      className="mapping-select"
                      placeholder="last name"
                    />
                  </div>
                  <div className="mapping-row">
                    <label className="mapping-label">Email *</label>
                    <input
                      type="email"
                      value={manualFormData.email}
                      onChange={(e) => handleManualFormChange("email", e.target.value)}
                      className="mapping-select"
                      placeholder="email@example.com"
                      required
                    />
                  </div>
                  <div className="mapping-row">
                    <label className="mapping-label">Email Status</label>
                    <select
                      value={manualFormData.emailStatus}
                      onChange={(e) => handleManualFormChange("emailStatus", e.target.value)}
                      className="mapping-select"
                    >
                      <option value="subscribed">Subscribed</option>
                      <option value="unsubscribed">Unsubscribed</option>
                      <option value="pending">Pending</option>
                    </select>
                  </div>
                  <div className="mapping-row">
                    <label className="mapping-label">Title</label>
                    <input
                      type="text"
                      value={manualFormData.title}
                      onChange={(e) => handleManualFormChange("title", e.target.value)}
                      className="mapping-select"
                      placeholder="Job title"
                    />
                  </div>
                  <div className="mapping-row">
                    <label className="mapping-label">LinkedIn</label>
                    <input
                      type="url"
                      value={manualFormData.linkedin}
                      onChange={(e) => handleManualFormChange("linkedin", e.target.value)}
                      className="mapping-select"
                      placeholder="LinkedIn profile URL"
                    />
                  </div>
                  <div className="mapping-row">
                    <label className="mapping-label">Location</label>
                    <input
                      type="text"
                      value={manualFormData.location}
                      onChange={(e) => handleManualFormChange("location", e.target.value)}
                      className="mapping-select"
                      placeholder="City, Country"
                    />
                  </div>
                  <div className="mapping-row">
                    <label className="mapping-label">Added On</label>
                    <input
                      type="date"
                      value={manualFormData.addedOn}
                      onChange={(e) => handleManualFormChange("addedOn", e.target.value)}
                      className="mapping-select"
                    />
                  </div>
                </div>
              </div>

              <div className="upload-section">
                <h3 className="section-title">Company Information</h3>
                <div className="mapping-grid">
                  <div className="mapping-row">
                    <label className="mapping-label">Company Name</label>
                    <input
                      type="text"
                      value={manualFormData.companyName}
                      onChange={(e) => handleManualFormChange("companyName", e.target.value)}
                      className="mapping-select"
                      placeholder="Company name"
                    />
                  </div>
                  <div className="mapping-row">
                    <label className="mapping-label">Company Domain</label>
                    <input
                      type="text"
                      value={manualFormData.companyDomain}
                      onChange={(e) => handleManualFormChange("companyDomain", e.target.value)}
                      className="mapping-select"
                      placeholder="example.com"
                    />
                  </div>
                  <div className="mapping-row">
                    <label className="mapping-label">Company Website</label>
                    <input
                      type="url"
                      value={manualFormData.companyWebsite}
                      onChange={(e) => handleManualFormChange("companyWebsite", e.target.value)}
                      className="mapping-select"
                      placeholder="https://example.com"
                    />
                  </div>
                  <div className="mapping-row">
                    <label className="mapping-label">Company Employee Count</label>
                    <input
                      type="number"
                      value={manualFormData.companyEmployeeCount}
                      onChange={(e) => handleManualFormChange("companyEmployeeCount", e.target.value)}
                      className="mapping-select"
                      placeholder="Number of employees"
                    />
                  </div>
                  <div className="mapping-row">
                    <label className="mapping-label">Company Employee Count Range</label>
                    <select
                      value={manualFormData.companyEmployeeCountRange}
                      onChange={(e) => handleManualFormChange("companyEmployeeCountRange", e.target.value)}
                      className="mapping-select"
                    >
                      <option value="">Select range</option>
                      <option value="1-10">1-10</option>
                      <option value="11-50">11-50</option>
                      <option value="51-200">51-200</option>
                      <option value="201-500">201-500</option>
                      <option value="501-1000">501-1000</option>
                      <option value="1001-5000">1001-5000</option>
                      <option value="5000+">5000+</option>
                    </select>
                  </div>
                  <div className="mapping-row">
                    <label className="mapping-label">Company Founded</label>
                    <input
                      type="number"
                      value={manualFormData.companyFounded}
                      onChange={(e) => handleManualFormChange("companyFounded", e.target.value)}
                      className="mapping-select"
                      placeholder="Year founded"
                      min="1800"
                      max={new Date().getFullYear()}
                    />
                  </div>
                  <div className="mapping-row">
                    <label className="mapping-label">Company Industry</label>
                    <input
                      type="text"
                      value={manualFormData.companyIndustry}
                      onChange={(e) => handleManualFormChange("companyIndustry", e.target.value)}
                      className="mapping-select"
                      placeholder="Industry sector"
                    />
                  </div>
                  <div className="mapping-row">
                    <label className="mapping-label">Company Type</label>
                    <select
                      value={manualFormData.companyType}
                      onChange={(e) => handleManualFormChange("companyType", e.target.value)}
                      className="mapping-select"
                    >
                      <option value="">Select type</option>
                      <option value="Public">Public</option>
                      <option value="Private">Private</option>
                      <option value="Startup">Startup</option>
                      <option value="Non-profit">Non-profit</option>
                      <option value="Government">Government</option>
                    </select>
                  </div>
                  <div className="mapping-row">
                    <label className="mapping-label">Company Headquarters</label>
                    <input
                      type="text"
                      value={manualFormData.companyHeadquarters}
                      onChange={(e) => handleManualFormChange("companyHeadquarters", e.target.value)}
                      className="mapping-select"
                      placeholder="City, Country"
                    />
                  </div>
                  <div className="mapping-row">
                    <label className="mapping-label">Company Revenue Range</label>
                    <select
                      value={manualFormData.companyRevenueRange}
                      onChange={(e) => handleManualFormChange("companyRevenueRange", e.target.value)}
                      className="mapping-select"
                    >
                      <option value="">Select range</option>
                      <option value="$0-$1M">$0-$1M</option>
                      <option value="$1M-$10M">$1M-$10M</option>
                      <option value="$10M-$50M">$10M-$50M</option>
                      <option value="$50M-$100M">$50M-$100M</option>
                      <option value="$100M-$500M">$100M-$500M</option>
                      <option value="$500M+">$500M+</option>
                    </select>
                  </div>
                  <div className="mapping-row">
                    <label className="mapping-label">Company LinkedIn URL</label>
                    <input
                      type="url"
                      value={manualFormData.companyLinkedinUrl}
                      onChange={(e) => handleManualFormChange("companyLinkedinUrl", e.target.value)}
                      className="mapping-select"
                      placeholder="LinkedIn company page URL"
                    />
                  </div>
                  <div className="mapping-row">
                    <label className="mapping-label">Company Crunchbase URL</label>
                    <input
                      type="url"
                      value={manualFormData.companyCrunchbaseUrl}
                      onChange={(e) => handleManualFormChange("companyCrunchbaseUrl", e.target.value)}
                      className="mapping-select"
                      placeholder="Crunchbase company URL"
                    />
                  </div>
                  <div className="mapping-row">
                    <label className="mapping-label">Company Funding Rounds</label>
                    <input
                      type="number"
                      value={manualFormData.companyFundingRounds}
                      onChange={(e) => handleManualFormChange("companyFundingRounds", e.target.value)}
                      className="mapping-select"
                      placeholder="Number of funding rounds"
                      min="0"
                    />
                  </div>
                  <div className="mapping-row">
                    <label className="mapping-label">Company Last Funding Round Amount</label>
                    <input
                      type="text"
                      value={manualFormData.companyLastFundingRoundAmount}
                      onChange={(e) => handleManualFormChange("companyLastFundingRoundAmount", e.target.value)}
                      className="mapping-select"
                      placeholder="$1M, $10M, etc."
                    />
                  </div>
                  <div className="mapping-row">
                    <label className="mapping-label">Company Logo URL Primary</label>
                    <input
                      type="url"
                      value={manualFormData.companyLogoUrlPrimary}
                      onChange={(e) => handleManualFormChange("companyLogoUrlPrimary", e.target.value)}
                      className="mapping-select"
                      placeholder="Primary logo URL"
                    />
                  </div>
                  <div className="mapping-row">
                    <label className="mapping-label">Company Logo URL Secondary</label>
                    <input
                      type="url"
                      value={manualFormData.companyLogoUrlSecondary}
                      onChange={(e) => handleManualFormChange("companyLogoUrlSecondary", e.target.value)}
                      className="mapping-select"
                      placeholder="Secondary logo URL"
                    />
                  </div>
                  <div className="mapping-row">
                    <label className="mapping-label">Business Unit</label>
                    <div className="radio-group">
                      <label className="radio-option">
                        <input
                          type="radio"
                          name="businessUnit"
                          value="Cogentix research"
                          checked={manualFormData.businessUnit === "Cogentix research"}
                          onChange={(e) => handleManualFormChange("businessUnit", e.target.value)}
                        />
                        <span>Cogentix research</span>
                      </label>
                      <label className="radio-option">
                        <input
                          type="radio"
                          name="businessUnit"
                          value="Survey Field Work"
                          checked={manualFormData.businessUnit === "Survey Field Work"}
                          onChange={(e) => handleManualFormChange("businessUnit", e.target.value)}
                        />
                        <span>Survey Field Work</span>
                      </label>
                    </div>
                  </div>
                </div>
              </div>

              <div className="action-buttons">
                <button type="button" className="btn-secondary" onClick={handleBackToMethods}>
                  Back to Methods
                </button>
                <button type="submit" className="btn-primary">
                  Add Contact
                </button>
              </div>
            </form>
          </div>
        </div>
      </div>
    )
  }

  if (currentView === "csv-upload") {
    return (
      <div className="create-contacts-container">
        <div className="page-header">
          {/* ... your header & breadcrumbs ... */}

          {dbCount !== null && (
            <div className="mt-3 rounded-md border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-sm text-[var(--muted-foreground)]">
              Ready to add contacts — <span className="font-medium text-[var(--foreground)]">{dbCount}</span> in MongoDB
              for "{listName}"
              <button
                className="ml-3 inline-flex items-center rounded-md border border-[var(--border)] px-2 py-1 text-xs hover:bg-[var(--accent)]"
                onClick={refreshDbCount}
                type="button"
              >
                Refresh
              </button>
            </div>
          )}

          {lastUploadSummary && (
            <div className="mt-3 rounded-md border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-sm text-[var(--muted-foreground)]">
              CSV uploaded — Parsed:
              <span className="mx-1 font-medium text-[var(--foreground)]">{lastUploadSummary.parsed}</span>, Inserted:
              <span className="mx-1 font-medium text-[var(--foreground)]">{lastUploadSummary.inserted}</span>,
              Skipped/duplicates:
              <span className="mx-1 font-medium text-[var(--foreground)]">{lastUploadSummary.skipped}</span>
              {csvPreview.length > 0 && (
                <div className="mt-2 overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead className="text-[var(--foreground)]">
                      <tr>
                        <th className="py-1 pr-3">Email</th>
                        <th className="py-1 pr-3">Name</th>
                        <th className="py-1 pr-3">Company</th>
                      </tr>
                    </thead>
                    <tbody>
                      {csvPreview.map((c, idx) => (
                        <tr key={idx} className="border-t border-[var(--border)]">
                          <td className="py-1 pr-3">{c.email || "-"}</td>
                          <td className="py-1 pr-3">
                            {c.name || `${(c.firstName || "").trim()} ${(c.lastName || "").trim()}`.trim() || "-"}
                          </td>
                          <td className="py-1 pr-3">{c.companyName || "-"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>

        <div className="csv-upload-container">
          <div className="upload-card">
            <div className="upload-section">
              {/* File Upload */}
              <h3 className="section-title">File Upload</h3>
              <div className="file-upload-area">
                <input type="file" accept=".csv" onChange={handleFileSelect} className="file-input" id="csv-file" />
                <label htmlFor="csv-file" className="file-upload-label">
                  <div className="upload-icon">📁</div>
                  <div className="upload-text">
                    {selectedFile ? selectedFile.name : "Choose file to import your contacts"}
                  </div>
                  <div className="upload-subtext">CSV files only</div>
                </label>
              </div>
            </div>

            {selectedFile && csvHeaders.length > 0 && (
              <div className="field-mapping-section">
                <h3 className="section-title">Field Mapping</h3>
                <p className="mapping-description">
                  Map your CSV columns to our contact fields to ensure proper data import
                </p>

                <div className="business-unit-section">
                  <label className="mapping-label">Business Unit</label>
                  <div className="radio-group">
                    <label className="radio-option">
                      <input
                        type="radio"
                        name="businessUnit"
                        value="Cogentix research"
                        checked={businessUnit === "Cogentix research"}
                        onChange={(e) => setBusinessUnit(e.target.value)}
                      />
                      <span>Cogentix research</span>
                    </label>
                    <label className="radio-option">
                      <input
                        type="radio"
                        name="businessUnit"
                        value="Survey Field Work"
                        checked={businessUnit === "Survey Field Work"}
                        onChange={(e) => setBusinessUnit(e.target.value)}
                      />
                      <span>Survey Field Work</span>
                    </label>
                  </div>
                </div>

                <div className="mapping-grid">
                  <div className="mapping-row">
                    <label className="mapping-label">Name</label>
                    <select
                      value={fieldMapping.name}
                      onChange={(e) => setFieldMapping({ ...fieldMapping, name: e.target.value })}
                      className="mapping-select"
                    >
                      <option value="">Select column</option>
                      {csvHeaders.map((header, index) => (
                        <option key={index} value={header}>
                          {header}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="mapping-row">
                    <label className="mapping-label">First Name</label>
                    <select
                      value={fieldMapping.firstName}
                      onChange={(e) => setFieldMapping({ ...fieldMapping, firstName: e.target.value })}
                      className="mapping-select"
                    >
                      <option value="">Select column</option>
                      {csvHeaders.map((header, index) => (
                        <option key={index} value={header}>
                          {header}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="mapping-row">
                    <label className="mapping-label">Last Name</label>
                    <select
                      value={fieldMapping.lastName}
                      onChange={(e) => setFieldMapping({ ...fieldMapping, lastName: e.target.value })}
                      className="mapping-select"
                    >
                      <option value="">Select column</option>
                      {csvHeaders.map((header, index) => (
                        <option key={index} value={header}>
                          {header}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="mapping-row">
                    <label className="mapping-label">Email Address *</label>
                    <select
                      value={fieldMapping.email}
                      onChange={(e) => setFieldMapping({ ...fieldMapping, email: e.target.value })}
                      className="mapping-select"
                    >
                      <option value="">Select column</option>
                      {csvHeaders.map((header, index) => (
                        <option key={index} value={header}>
                          {header}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="mapping-row">
                    <label className="mapping-label">Email Status</label>
                    <select
                      value={fieldMapping.emailStatus}
                      onChange={(e) => setFieldMapping({ ...fieldMapping, emailStatus: e.target.value })}
                      className="mapping-select"
                    >
                      <option value="">Select column</option>
                      {csvHeaders.map((header, index) => (
                        <option key={index} value={header}>
                          {header}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="mapping-row">
                    <label className="mapping-label">Title</label>
                    <select
                      value={fieldMapping.title}
                      onChange={(e) => setFieldMapping({ ...fieldMapping, title: e.target.value })}
                      className="mapping-select"
                    >
                      <option value="">Select column</option>
                      {csvHeaders.map((header, index) => (
                        <option key={index} value={header}>
                          {header}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="mapping-row">
                    <label className="mapping-label">LinkedIn</label>
                    <select
                      value={fieldMapping.linkedin}
                      onChange={(e) => setFieldMapping({ ...fieldMapping, linkedin: e.target.value })}
                      className="mapping-select"
                    >
                      <option value="">Select column</option>
                      {csvHeaders.map((header, index) => (
                        <option key={index} value={header}>
                          {header}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="mapping-row">
                    <label className="mapping-label">Location</label>
                    <select
                      value={fieldMapping.location}
                      onChange={(e) => setFieldMapping({ ...fieldMapping, location: e.target.value })}
                      className="mapping-select"
                    >
                      <option value="">Select column</option>
                      {csvHeaders.map((header, index) => (
                        <option key={index} value={header}>
                          {header}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="mapping-row">
                    <label className="mapping-label">Added On</label>
                    <select
                      value={fieldMapping.addedOn}
                      onChange={(e) => setFieldMapping({ ...fieldMapping, addedOn: e.target.value })}
                      className="mapping-select"
                    >
                      <option value="">Select column</option>
                      {csvHeaders.map((header, index) => (
                        <option key={index} value={header}>
                          {header}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="mapping-row">
                    <label className="mapping-label">Company Name</label>
                    <select
                      value={fieldMapping.companyName}
                      onChange={(e) => setFieldMapping({ ...fieldMapping, companyName: e.target.value })}
                      className="mapping-select"
                    >
                      <option value="">Select column</option>
                      {csvHeaders.map((header, index) => (
                        <option key={index} value={header}>
                          {header}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="mapping-row">
                    <label className="mapping-label">Company Domain</label>
                    <select
                      value={fieldMapping.companyDomain}
                      onChange={(e) => setFieldMapping({ ...fieldMapping, companyDomain: e.target.value })}
                      className="mapping-select"
                    >
                      <option value="">Select column</option>
                      {csvHeaders.map((header, index) => (
                        <option key={index} value={header}>
                          {header}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="mapping-row">
                    <label className="mapping-label">Company Website</label>
                    <select
                      value={fieldMapping.companyWebsite}
                      onChange={(e) => setFieldMapping({ ...fieldMapping, companyWebsite: e.target.value })}
                      className="mapping-select"
                    >
                      <option value="">Select column</option>
                      {csvHeaders.map((header, index) => (
                        <option key={index} value={header}>
                          {header}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="mapping-row">
                    <label className="mapping-label">Company Employee Count</label>
                    <select
                      value={fieldMapping.companyEmployeeCount}
                      onChange={(e) => setFieldMapping({ ...fieldMapping, companyEmployeeCount: e.target.value })}
                      className="mapping-select"
                    >
                      <option value="">Select column</option>
                      {csvHeaders.map((header, index) => (
                        <option key={index} value={header}>
                          {header}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="mapping-row">
                    <label className="mapping-label">Company Employee Count Range</label>
                    <select
                      value={fieldMapping.companyEmployeeCountRange}
                      onChange={(e) => setFieldMapping({ ...fieldMapping, companyEmployeeCountRange: e.target.value })}
                      className="mapping-select"
                    >
                      <option value="">Select column</option>
                      {csvHeaders.map((header, index) => (
                        <option key={index} value={header}>
                          {header}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="mapping-row">
                    <label className="mapping-label">Company Founded</label>
                    <select
                      value={fieldMapping.companyFounded}
                      onChange={(e) => setFieldMapping({ ...fieldMapping, companyFounded: e.target.value })}
                      className="mapping-select"
                    >
                      <option value="">Select column</option>
                      {csvHeaders.map((header, index) => (
                        <option key={index} value={header}>
                          {header}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="mapping-row">
                    <label className="mapping-label">Company Industry</label>
                    <select
                      value={fieldMapping.companyIndustry}
                      onChange={(e) => setFieldMapping({ ...fieldMapping, companyIndustry: e.target.value })}
                      className="mapping-select"
                    >
                      <option value="">Select column</option>
                      {csvHeaders.map((header, index) => (
                        <option key={index} value={header}>
                          {header}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="mapping-row">
                    <label className="mapping-label">Company Type</label>
                    <select
                      value={fieldMapping.companyType}
                      onChange={(e) => setFieldMapping({ ...fieldMapping, companyType: e.target.value })}
                      className="mapping-select"
                    >
                      <option value="">Select column</option>
                      <option value="Public">Public</option>
                      <option value="Private">Private</option>
                      <option value="Startup">Startup</option>
                      <option value="Non-profit">Non-profit</option>
                      <option value="Government">Government</option>
                    </select>
                  </div>

                  <div className="mapping-row">
                    <label className="mapping-label">Company Headquarters</label>
                    <select
                      value={fieldMapping.companyHeadquarters}
                      onChange={(e) => setFieldMapping({ ...fieldMapping, companyHeadquarters: e.target.value })}
                      className="mapping-select"
                    >
                      <option value="">Select column</option>
                      {csvHeaders.map((header, index) => (
                        <option key={index} value={header}>
                          {header}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="mapping-row">
                    <label className="mapping-label">Company Revenue Range</label>
                    <select
                      value={fieldMapping.companyRevenueRange}
                      onChange={(e) => setFieldMapping({ ...fieldMapping, companyRevenueRange: e.target.value })}
                      className="mapping-select"
                    >
                      <option value="">Select column</option>
                      <option value="$0-$1M">$0-$1M</option>
                      <option value="$1M-$10M">$1M-$10M</option>
                      <option value="$10M-$50M">$10M-$50M</option>
                      <option value="$50M-$100M">$50M-$100M</option>
                      <option value="$100M-$500M">$100M-$500M</option>
                      <option value="$500M+">$500M+</option>
                    </select>
                  </div>

                  <div className="mapping-row">
                    <label className="mapping-label">Company LinkedIn URL</label>
                    <select
                      value={fieldMapping.companyLinkedinUrl}
                      onChange={(e) => setFieldMapping({ ...fieldMapping, companyLinkedinUrl: e.target.value })}
                      className="mapping-select"
                    >
                      <option value="">Select column</option>
                      {csvHeaders.map((header, index) => (
                        <option key={index} value={header}>
                          {header}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="mapping-row">
                    <label className="mapping-label">Company Crunchbase URL</label>
                    <select
                      value={fieldMapping.companyCrunchbaseUrl}
                      onChange={(e) => setFieldMapping({ ...fieldMapping, companyCrunchbaseUrl: e.target.value })}
                      className="mapping-select"
                    >
                      <option value="">Select column</option>
                      {csvHeaders.map((header, index) => (
                        <option key={index} value={header}>
                          {header}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="mapping-row">
                    <label className="mapping-label">Company Funding Rounds</label>
                    <select
                      value={fieldMapping.companyFundingRounds}
                      onChange={(e) => setFieldMapping({ ...fieldMapping, companyFundingRounds: e.target.value })}
                      className="mapping-select"
                    >
                      <option value="">Select column</option>
                      {csvHeaders.map((header, index) => (
                        <option key={index} value={header}>
                          {header}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="mapping-row">
                    <label className="mapping-label">Company Last Funding Round Amount</label>
                    <select
                      value={fieldMapping.companyLastFundingRoundAmount}
                      onChange={(e) =>
                        setFieldMapping({ ...fieldMapping, companyLastFundingRoundAmount: e.target.value })
                      }
                      className="mapping-select"
                    >
                      <option value="">Select column</option>
                      {csvHeaders.map((header, index) => (
                        <option key={index} value={header}>
                          {header}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="mapping-row">
                    <label className="mapping-label">Company Logo URL Primary</label>
                    <select
                      value={fieldMapping.companyLogoUrlPrimary}
                      onChange={(e) => setFieldMapping({ ...fieldMapping, companyLogoUrlPrimary: e.target.value })}
                      className="mapping-select"
                    >
                      <option value="">Select column</option>
                      {csvHeaders.map((header, index) => (
                        <option key={index} value={header}>
                          {header}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="mapping-row">
                    <label className="mapping-label">Company Logo URL Secondary</label>
                    <select
                      value={fieldMapping.companyLogoUrlSecondary}
                      onChange={(e) => setFieldMapping({ ...fieldMapping, companyLogoUrlSecondary: e.target.value })}
                      className="mapping-select"
                    >
                      <option value="">Select column</option>
                      {csvHeaders.map((header, index) => (
                        <option key={index} value={header}>
                          {header}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
              </div>
            )}

            {selectedFile && csvHeaders.length > 0 && (
              <div className="import-section">
                <button className="btn-primary" onClick={handleImportContacts}>
                  Import Contacts to Database
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    )
  }
  return (
    <div className="create-contacts-container">
      <div className="page-header">
        <div className="breadcrumb">
          <button className="breadcrumb-link" onClick={onBack}>
            Lists
          </button>
          <span className="breadcrumb-separator">/</span>
          <span className="breadcrumb-current">Add Contacts</span>
        </div>
        <h1 className="page-title">Choose Your Contact Method</h1>
        <p className="page-description">Select the best way to build your contact list</p>

        <div className="mt-2">
          <button className="btn-secondary" onClick={onBack} type="button">
            {"← Back to Lists"}
          </button>
        </div>
      </div>

      <div className="method-cards">
        <div className="method-card csv">
          <div className="card-content">
            <div className="card-icon-wrapper">
              <div className="card-icon">
                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                  <polyline points="14,2 14,8 20,8" />
                  <line x1="16" y1="13" x2="8" y2="13" />
                  <line x1="16" y1="17" x2="8" y2="17" />
                  <polyline points="10,9 9,9 8,9" />
                </svg>
              </div>
            </div>
            <h3 className="card-title">CSV Import</h3>
            <p className="card-description">Upload contacts from CSV or Excel files with automatic field mapping</p>
            <ul className="card-features">
              <li>CSV/Excel file support</li>
              <li>Automatic field detection</li>
              <li>Bulk data validation</li>
              <li>Error reporting</li>
            </ul>
          </div>
          <button className="card-button" onClick={handleUploadCSV}>
            Upload CSV
            <span className="button-arrow">→</span>
          </button>
        </div>

        <div className="method-card form">
          <div className="card-content">
            <div className="card-icon-wrapper">
              <div className="card-icon">
                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M9 12l2 2 4-4" />
                  <path d="M21 12c-1 0-3-1-9-3s-9-1.34-9-3 2-3 9-3 9 1.34 9 3" />
                  <path d="M3 12c1 0 3-1 3-3s-2-3-3-3-3 1-3 3" />
                  <path d="M12 3v6m0 6v6" />
                </svg>
              </div>
            </div>
            <h3 className="card-title">Manual Form</h3>
            <p className="card-description">Add contacts individually using a structured form interface</p>
            <ul className="card-features">
              <li>Step-by-step entry</li>
              <li>Real-time validation</li>
              <li>Custom field support</li>
              <li>Duplicate detection</li>
            </ul>
          </div>
          <button className="card-button" onClick={handleManualForm}>
            Create Form
            <span className="button-arrow">→</span>
          </button>
        </div>

        <div className="method-card database">
          <div className="card-content">
            <div className="card-icon-wrapper">
              <div className="card-icon">
                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <ellipse cx="12" cy="5" rx="9" ry="3" />
                  <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
                  <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
                </svg>
              </div>
            </div>
            <h3 className="card-title">Database Connection</h3>
            <p className="card-description">Connect to external databases and CRM systems for seamless data sync</p>
            <ul className="card-features">
              <li>CRM integrations</li>
              <li>API connections</li>
              <li>Real-time sync</li>
              <li>Secure authentication</li>
            </ul>
          </div>
          <button className="card-button">
            Connect Database
            <span className="button-arrow">→</span>
          </button>
        </div>
      </div>
    </div>
  )
}

export default CreateContacts
