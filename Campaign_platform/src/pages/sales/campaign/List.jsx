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
  const [contacts, setContacts] = useState([]) // ✅ store contacts for selected list

  // ✅ Fetch all lists
  useEffect(() => {
    async function fetchLists() {
      try {
        const res = await fetch("http://localhost:8000/lists/")
        if (!res.ok) throw new Error("Failed to fetch lists")
        const data = await res.json()
        setLists(data.lists || [])
      } catch (err) {
        console.error("Error loading lists:", err)
      }
    }
    fetchLists()
  }, [])

  // ✅ Fetch contacts whenever selectedList changes
  useEffect(() => {
    async function fetchContacts() {
      if (!selectedList?._id) return
      try {
        const res = await fetch(`http://localhost:8000/contacts/${selectedList._id}`)
        if (!res.ok) throw new Error("Failed to fetch contacts")
        const data = await res.json()
        setContacts(data.contacts || [])
      } catch (err) {
        console.error("Error loading contacts:", err)
      }
    }
    fetchContacts()
  }, [selectedList])

  // ✅ Save new list
  const saveListToDatabase = async (listData) => {
    try {
      const response = await fetch("http://localhost:8000/create-list/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(listData),
      })
      if (!response.ok) throw new Error("Failed to save list")
      const data = await response.json()
      setLists((prev) => [...prev, data.list])
    } catch (error) {
      console.error("Error saving list to database:", error)
    }
  }

  // ✅ Delete list
  const handleDelete = async (id) => {
    const confirmDelete = window.confirm("Are you sure you want to delete this list?")
    if (!confirmDelete) return

    try {
      const res = await fetch(`http://localhost:8000/delete-list/${id}`, { method: "DELETE" })
      if (!res.ok) throw new Error("Failed to delete list")
      setLists((prev) => prev.filter((l) => l._id !== id))
    } catch (err) {
      console.error("Delete failed:", err)
      alert("Could not delete list. Please try again.")
    }
  }

  // ✅ Create new list
  const createListHandler = () => {
    if (!newListName.trim()) return
    const newList = {
      name: newListName.trim(),
      contacts: 0,
      created: new Date().toLocaleDateString("en-US", {
        year: "numeric",
        month: "short",
        day: "numeric",
      }),
      status: "active",
    }
    saveListToDatabase(newList)
    setNewListName("")
    setCurrentView("main")
  }

  // ✅ Show CreateContacts view
  if (showCreateContacts) {
    return (
      <CreateContacts
        onBack={() => setShowCreateContacts(false)}
        listName={selectedList?.name}
        listId={selectedList?._id}
      />
    )
  }

  // ✅ Create Form view
  if (currentView === "createForm") {
    return (
      <div className="list-container">
        <div className="create-form-container">
          <div className="form-header">
            <button
              className="back-btn"
              onClick={() => setCurrentView("main")}
              style={{ color: "black" }}
            >
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
                onClick={createListHandler}
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

  // ✅ List Detail view
  if (currentView === "listDetail" && selectedList) {
    return (
      <div className="list-container">
        <div className="list-detail-container">
          <div className="detail-header">
            <button className="back-btn back-btn--contrast" onClick={() => setCurrentView("main")}>
              ← Back to Lists
            </button>
            <h1 className="detail-title">{selectedList.name}</h1>
          </div>

          {contacts.length > 0 ? (
            <div className="uploaded-contacts">
              <h2>{contacts.length} contact(s) uploaded:</h2>
              <table className="contacts-table">
                <thead>
                  <tr>
                    <th>Email</th>
                    <th>Name</th>
                    <th>Company</th>
                  </tr>
                </thead>
                <tbody>
                  {contacts.map((c, idx) => (
                    <tr key={idx}>
                      <td>{c.email || "-"}</td>
                      <td>{c.name || `${c.firstName || ""} ${c.lastName || ""}`.trim() || "-"}</td>
                      <td>{c.companyName || "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <button className="create-contacts-btn" onClick={() => setShowCreateContacts(true)}>
                Add More Contacts
              </button>
            </div>
          ) : (
            <div className="empty-state">
              <div className="empty-icon">📋</div>
              <h2 className="empty-title">Ready to add contacts?</h2>
              <p className="empty-description">
                Start building your contact database by adding contacts to this list.
              </p>
              <button className="create-contacts-btn" onClick={() => setShowCreateContacts(true)}>
                Add Contacts
              </button>
            </div>
          )}
        </div>
      </div>
    )
  }

  // ✅ Main Lists view
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
          <div className="stat-number">85%</div>
          <div className="stat-label">Active Rate</div>
        </div>
      </div>

      <div className="content-wrapper">
        <div className="filters-panel">
          <h3 className="panel-title">Filters</h3>
          {/* your filter controls remain unchanged */}
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
                key={list._id}
                className="list-card clickable"
                onClick={() => {
                  setSelectedList(list)
                  setCurrentView("listDetail")
                }}
              >
                <div className="card-header">
                  <div className="list-info">
                    <h3 className="list-name">{list.name}</h3>
                  </div>
                  <div className="card-actions">
                    <button
                      className="delete-btn"
                      onClick={(e) => {
                        e.stopPropagation()
                        handleDelete(list._id)
                      }}
                      title="Delete List"
                    >
                      🗑️
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
