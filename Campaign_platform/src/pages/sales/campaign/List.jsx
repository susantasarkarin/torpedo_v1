"use client"

import { useState, useEffect } from "react"
import CreateContacts from "./CreateContacts"
import "./List.css"

function List() {
  const [showCreateContacts, setShowCreateContacts] = useState(false)
  const [currentView, setCurrentView] = useState("main") // 'main', 'createForm', 'listDetail'
  const [selectedList, setSelectedList] = useState(null)
  const [lists, setLists] = useState([])
  const [newListName, setNewListName] = useState("")
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchLists()
  }, [])

  const fetchLists = async () => {
    try {
      setLoading(true)
      const response = await fetch("http://localhost:8000/get-all-lists/")
      const data = await response.json()
      setLists(data.lists || [])
    } catch (error) {
      console.error("Error fetching lists:", error)
      setLists([])
    } finally {
      setLoading(false)
    }
  }

  const createList = async (listName) => {
    try {
      const response = await fetch("http://localhost:8000/create-list/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          name: listName,
          created: new Date().toLocaleDateString("en-US", {
            year: "numeric",
            month: "short",
            day: "numeric",
          }),
        }),
      })

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.detail || "Failed to create list")
      }

      const data = await response.json()
      // Refresh the lists after creating a new one
      await fetchLists()
      return data
    } catch (error) {
      console.error("Error creating list:", error)
      throw error
    }
  }

  if (showCreateContacts) {
    return (
      <CreateContacts
        onBack={() => setShowCreateContacts(false)}
        listName={selectedList?.name}
        listId={selectedList?.id}
      />
    )
  }

  if (currentView === "createForm") {
    return (
      <div className="list-container">
        <div className="create-form-container">
          <div className="form-header">
            <button className="back-btn" onClick={() => setCurrentView("main")}>
              ← Back to Lists
            </button>
            <h1 className="form-title">Create New List</h1>
          </div>

          <div className="form-content">
            <div className="form-group">
              <label className="form-label">List Name</label>
              <input
                type="text"
                className="form-input"
                placeholder="Enter list name..."
                value={newListName}
                onChange={(e) => setNewListName(e.target.value)}
              />
            </div>

            <div className="form-actions">
              <button
                className="cancel-btn"
                onClick={() => {
                  setCurrentView("main")
                  setNewListName("")
                }}
              >
                Cancel
              </button>
              <button
                className="create-list-btn"
                onClick={async () => {
                  if (newListName.trim()) {
                    try {
                      await createList(newListName.trim())
                      setNewListName("")
                      setCurrentView("main")
                    } catch (error) {
                      alert(`Error creating list: ${error.message}`)
                    }
                  }
                }}
                disabled={!newListName.trim()}
              >
                Create List
              </button>
            </div>
          </div>
        </div>
      </div>
    )
  }

  if (currentView === "listDetail" && selectedList) {
    return (
      <div className="list-container">
        <div className="list-detail-container">
          <div className="detail-header">
            <button className="back-btn" onClick={() => setCurrentView("main")}>
              ← Back to Lists
            </button>
            <h1 className="detail-title">{selectedList.name}</h1>
          </div>

          <div className="empty-state">
            <div className="empty-icon">📋</div>
            <h2 className="empty-title">No contacts, create one?</h2>
            <p className="empty-description">
              This list is empty. Start building your contact database by adding contacts.
            </p>
            <button className="create-contacts-btn" onClick={() => setShowCreateContacts(true)}>
              Create Contacts
            </button>
          </div>
        </div>
      </div>
    )
  }

  if (loading) {
    return (
      <div className="list-container">
        <div className="loading-state">
          <p>Loading lists...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="list-container">
      <div className="list-header">
        <div className="header-content">
          <div className="title-section">
            <h1 className="page-title">Contact Lists</h1>
            <p className="page-subtitle">Manage and organize your contact databases</p>
          </div>
          <button className="create-btn" onClick={() => setCurrentView("createForm")}>
            <span className="btn-icon">+</span>
            New List
          </button>
        </div>
      </div>

      <div className="dashboard-stats">
        <div className="stat-card">
          <div className="stat-number">{lists.length}</div>
          <div className="stat-label">Total Lists</div>
        </div>
        <div className="stat-card">
          <div className="stat-number">{lists.reduce((sum, list) => sum + list.contacts, 0).toLocaleString()}</div>
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
            {lists.map((list) => (
              <div
                key={list.id}
                className="list-card clickable"
                onClick={() => {
                  setSelectedList(list)
                  setCurrentView("listDetail")
                }}
              >
                <div className="card-header">
                  <div className="list-info">
                    <h3 className="list-name">{list.name}</h3>
                    <span className="contact-count">{list.contacts.toLocaleString()} contacts</span>
                  </div>
                  <div className="card-actions">
                    <button
                      className="action-btn"
                      onClick={(e) => {
                        e.stopPropagation()
                        // Handle menu actions
                      }}
                    >
                      ⋯
                    </button>
                  </div>
                </div>
                <div className="card-meta">
                  <span className="created-date">Created {list.created}</span>
                  <span className={`status-badge ${list.status}`}>{list.status}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

export default List
