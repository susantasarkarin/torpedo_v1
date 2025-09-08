"use client"

import { useState } from "react"
import "./CreateContacts.css"

function CreateContacts({ onBack }) {
  const [currentView, setCurrentView] = useState("methods") // 'methods' or 'csv-upload'
  const [selectedFile, setSelectedFile] = useState(null)
  const [subscriptionType, setSubscriptionType] = useState("subscribed")
  const [fieldMapping, setFieldMapping] = useState({
    email: "",
    firstName: "",
    lastName: "",
    phone: "",
  })
  const [showAdvancedOptions, setShowAdvancedOptions] = useState(false)

  const handleFileSelect = (event) => {
    const file = event.target.files[0]
    if (file && (file.type === "text/csv" || file.name.endsWith(".csv"))) {
      setSelectedFile(file)
    } else {
      alert("Please select a valid CSV file")
    }
  }

  const handleUploadCSV = () => {
    setCurrentView("csv-upload")
  }

  const handleBackToMethods = () => {
    setCurrentView("methods")
    setSelectedFile(null)
  }

  const handleImportContacts = () => {
    if (!selectedFile) {
      alert("Please select a CSV file first")
      return
    }
    // Here you would implement the actual import logic
    console.log("Importing contacts...", {
      file: selectedFile,
      subscriptionType,
      fieldMapping,
    })
    alert("Contacts imported successfully!")
  }

  if (currentView === "csv-upload") {
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
            <span className="breadcrumb-current">Import Contacts</span>
          </div>
          <h1 className="page-title">Import Contacts</h1>
          <p className="page-description">Upload your contact list and configure import settings</p>
        </div>

        <div className="csv-upload-container">
          <div className="upload-card">
            <div className="upload-section">
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

            <div className="subscription-section">
              <h3 className="section-title">Subscription Type</h3>
              <div className="subscription-options">
                <label className="radio-option">
                  <input
                    type="radio"
                    name="subscription"
                    value="subscribed"
                    checked={subscriptionType === "subscribed"}
                    onChange={(e) => setSubscriptionType(e.target.value)}
                  />
                  <span className="radio-label">Subscribed</span>
                </label>
                <label className="radio-option">
                  <input
                    type="radio"
                    name="subscription"
                    value="unsubscribed"
                    checked={subscriptionType === "unsubscribed"}
                    onChange={(e) => setSubscriptionType(e.target.value)}
                  />
                  <span className="radio-label">Unsubscribed</span>
                </label>
              </div>
              <p className="subscription-note">
                Choose the most accurate subscription status to avoid contacts from unsubscribing
              </p>
            </div>

            <div className="field-mapping-section">
              <h3 className="section-title">Field Mapping</h3>
              <p className="mapping-description">
                Map your CSV columns to our contact fields to ensure proper data import
              </p>

              <div className="mapping-grid">
                <div className="mapping-row">
                  <label className="mapping-label">Email Address *</label>
                  <select
                    value={fieldMapping.email}
                    onChange={(e) => setFieldMapping({ ...fieldMapping, email: e.target.value })}
                    className="mapping-select"
                  >
                    <option value="">Select column</option>
                    <option value="email">Email</option>
                    <option value="email_address">Email Address</option>
                    <option value="contact_email">Contact Email</option>
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
                    <option value="first_name">First Name</option>
                    <option value="fname">FName</option>
                    <option value="given_name">Given Name</option>
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
                    <option value="last_name">Last Name</option>
                    <option value="lname">LName</option>
                    <option value="surname">Surname</option>
                  </select>
                </div>

                <div className="mapping-row">
                  <label className="mapping-label">Phone Number</label>
                  <select
                    value={fieldMapping.phone}
                    onChange={(e) => setFieldMapping({ ...fieldMapping, phone: e.target.value })}
                    className="mapping-select"
                  >
                    <option value="">Select column</option>
                    <option value="phone">Phone</option>
                    <option value="phone_number">Phone Number</option>
                    <option value="mobile">Mobile</option>
                  </select>
                </div>
              </div>
            </div>

            <div className="advanced-options-section">
              <button className="advanced-toggle" onClick={() => setShowAdvancedOptions(!showAdvancedOptions)}>
                Show advanced options {showAdvancedOptions ? "▼" : "▶"}
              </button>

              {showAdvancedOptions && (
                <div className="advanced-content">
                  <div className="checkbox-option">
                    <input type="checkbox" id="skip-duplicates" />
                    <label htmlFor="skip-duplicates">Skip duplicate contacts</label>
                  </div>
                  <div className="checkbox-option">
                    <input type="checkbox" id="validate-emails" />
                    <label htmlFor="validate-emails">Validate email addresses</label>
                  </div>
                  <div className="checkbox-option">
                    <input type="checkbox" id="send-welcome" />
                    <label htmlFor="send-welcome">Send welcome email to new contacts</label>
                  </div>
                </div>
              )}
            </div>

            <div className="action-buttons">
              <button className="btn-secondary" onClick={handleBackToMethods}>
                Back to Methods
              </button>
              <button className="btn-primary" onClick={handleImportContacts}>
                Import Contacts
              </button>
            </div>
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
                  <path d="M21 12c-1 0-3-1-3-3s2-3 3-3 3 1 3 3-2 3-3 3" />
                  <path d="M3 12c1 0 3-1 3-3s-2-3-3-3-3 1-3 3 2 3 3 3" />
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
          <button className="card-button">
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
