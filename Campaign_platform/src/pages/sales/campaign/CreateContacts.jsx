"use client"

import "./CreateContacts.css"

function CreateContacts({ onBack }) {
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
          <button className="card-button">
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
