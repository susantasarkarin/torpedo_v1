"use client"

import { useState } from "react"
import CreateContacts from "./CreateContacts"
import "./List.css"

function List() {
  const [showCreateContacts, setShowCreateContacts] = useState(false)

  if (showCreateContacts) {
    return <CreateContacts onBack={() => setShowCreateContacts(false)} />
  }

  return (
    <div className="list-container">
      <div className="list-header">
        <div className="header-content">
          <div className="title-section">
            <h1 className="page-title">Contact Lists</h1>
            <p className="page-subtitle">Manage and organize your contact databases</p>
          </div>
          <button className="create-btn" onClick={() => setShowCreateContacts(true)}>
            <span className="btn-icon">+</span>
            New List
          </button>
        </div>
      </div>

      <div className="dashboard-stats">
        <div className="stat-card">
          <div className="stat-number">2</div>
          <div className="stat-label">Total Lists</div>
        </div>
        <div className="stat-card">
          <div className="stat-number">1,948</div>
          <div className="stat-label">Total Contacts</div>
        </div>
        <div className="stat-card">
          <div className="stat-number">85%</div>
          <div className="stat-label">Active Rate</div>
        </div>
      </div>

      <div className="content-wrapper">
        <div className="filters-panel">
          <h3 className="panel-title">Filters</h3>

          <div className="filter-group">
            <label className="filter-label">Owner</label>
            <div className="toggle-group">
              <label className="toggle-item">
                <input type="radio" name="owner" defaultChecked />
                <span className="toggle-text">My Lists</span>
              </label>
              <label className="toggle-item">
                <input type="radio" name="owner" />
                <span className="toggle-text">Shared</span>
              </label>
            </div>
          </div>

          <div className="filter-group">
            <label className="filter-label">Status</label>
            <div className="checkbox-group">
              <label className="checkbox-item">
                <input type="checkbox" defaultChecked />
                <span className="checkmark"></span>
                Active
              </label>
              <label className="checkbox-item">
                <input type="checkbox" />
                <span className="checkmark"></span>
                Archived
              </label>
            </div>
          </div>
        </div>

        <div className="lists-section">
          <div className="section-header">
            <h2 className="section-title">Your Lists</h2>
            <select className="sort-select">
              <option>Recently Created</option>
              <option>Name A-Z</option>
              <option>Most Contacts</option>
            </select>
          </div>

          <div className="lists-grid">
           

            <div className="list-card">
              <div className="card-header">
                <div className="list-info">
                  <h3 className="list-name">Independence Day Campaign</h3>
                  <span className="contact-count">1,948 contacts</span>
                </div>
                <div className="card-actions">
                  <button className="action-btn">⋯</button>
                </div>
              </div>
              <div className="card-meta">
                <span className="created-date">Created Jul 4, 2023</span>
                <span className="status-badge active">Active</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default List
