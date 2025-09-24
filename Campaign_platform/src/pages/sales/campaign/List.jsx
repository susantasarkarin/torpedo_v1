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
  const [backendConnected, setBackendConnected] = useState(false)

  const [localContacts, setLocalContacts] = useState(() => {
    try {
      const stored = localStorage.getItem("contactListContacts")
      return stored ? JSON.parse(stored) : {}
    } catch {
      return {}
    }
  })

  const addContactsToLocal = (listName, newContacts) => {
    const updated = {
      ...localContacts,
      [listName]: [...(localContacts[listName] || []), ...newContacts],
    }
    setLocalContacts(updated)
    localStorage.setItem("contactListContacts", JSON.stringify(updated))
    console.log(`[v0] Added ${newContacts.length} contacts to local storage for "${listName}"`)
  }

  const mockLists = [
    {
      _id: "list1",
      name: "list 11",
      contacts: 1,
      created: "Dec 15, 2024",
      status: "active",
    },
    {
      _id: "list2",
      name: "Marketing Leads",
      contacts: 3,
      created: "Dec 14, 2024",
      status: "active",
    },
    {
      _id: "list3",
      name: "Sales Prospects",
      contacts: 2,
      created: "Dec 13, 2024",
      status: "active",
    },
    {
      _id: "list5",
      name: "List 5",
      contacts: 1,
      created: "Dec 16, 2024",
      status: "active",
    },
  ]

  const mockContacts = {
    "list 11": [
      {
        email: "info@surveyfieldwork.com",
        name: "info",
        companyName: "Cogentix research",
        businessUnit: "-",
      },
    ],
    "List 5": [
      {
        email: "contact@example.com",
        name: "John Doe",
        companyName: "Example Corp",
        businessUnit: "Sales",
      },
    ],
    "Marketing Leads": [
      {
        email: "john@example.com",
        name: "John Smith",
        companyName: "Tech Corp",
        businessUnit: "Marketing",
      },
      {
        email: "sarah@company.com",
        name: "Sarah Johnson",
        companyName: "Business Inc",
        businessUnit: "Sales",
      },
      {
        email: "mike@startup.io",
        name: "Mike Wilson",
        companyName: "Startup LLC",
        businessUnit: "Product",
      },
    ],
    "Sales Prospects": [
      {
        email: "alice@corp.com",
        name: "Alice Brown",
        companyName: "Enterprise Corp",
        businessUnit: "Operations",
      },
      {
        email: "bob@business.net",
        name: "Bob Davis",
        companyName: "Global Business",
        businessUnit: "Finance",
      },
    ],
  }

  useEffect(() => {
    async function fetchLists() {
      try {
        console.log("[v0] Attempting to connect to backend at http://localhost:8000/lists/")
        const res = await fetch("http://localhost:8000/lists/")
        if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`)
        const data = await res.json()
        console.log("[v0] Successfully connected to backend! Fetched", data.lists?.length || 0, "lists")
        setLists(data.lists || [])
        setBackendConnected(true)
      } catch (err) {
        console.log("[v0] Backend connection failed:", err.message)
        console.log(
          "[v0] Using mock data. To see real database data, start backend with: cd backend && uvicorn main:app --reload --port 8000",
        )
        setLists(mockLists)
        setBackendConnected(false)
      }
    }
    fetchLists()
  }, [])

  useEffect(() => {
    async function fetchContacts() {
      if (!selectedList) return

      console.log("[v0] Fetching contacts for list:", selectedList.name, "ID:", selectedList._id)

      try {
        console.log("[v0] Testing backend connection...")
        const healthCheck = await fetch("http://localhost:8000/lists/")
        if (!healthCheck.ok) {
          throw new Error("Backend not available")
        }
        console.log("[v0] Backend is available, fetching contacts...")
        setBackendConnected(true)
      } catch (err) {
        console.log("[v0] Backend not available:", err.message)
        setBackendConnected(false)

        // Use fallback data when backend is not available
        console.log("[v0] Using fallback data (local + mock)")
        const localContactsForList = localContacts[selectedList.name] || []
        const mockContactsForList = mockContacts[selectedList.name] || []
        const allContacts = [...localContactsForList, ...mockContactsForList]

        console.log("[v0] Local contacts:", localContactsForList.length, "Mock contacts:", mockContactsForList.length)
        setContacts(allContacts)
        return
      }

      try {
        console.log("[v0] Attempting database fetch for contacts...")
        let res = await fetch(`http://localhost:8000/contacts/${selectedList._id}`)
        console.log("[v0] Fetch by ID response status:", res.status)

        if (!res.ok) {
          console.log("[v0] Trying fetch by name:", selectedList.name)
          res = await fetch(`http://localhost:8000/contacts/${encodeURIComponent(selectedList.name)}`)
          console.log("[v0] Fetch by name response status:", res.status)
        }

        if (res.ok) {
          const data = await res.json()
          console.log("[v0] ✅ SUCCESS! Fetched", data.contacts?.length || 0, "contacts from DATABASE")
          console.log("[v0] Contact data:", data.contacts)
          setContacts(data.contacts || [])
          return // Exit early when real data is found
        } else {
          console.log("[v0] API returned error status:", res.status)
          const errorText = await res.text()
          console.log("[v0] Error response:", errorText)
        }
      } catch (err) {
        console.log("[v0] ❌ Database fetch failed:", err.message)
      }

      console.log("[v0] Using fallback data (local + mock)")
      const localContactsForList = localContacts[selectedList.name] || []
      const mockContactsForList = mockContacts[selectedList.name] || []
      const allContacts = [...localContactsForList, ...mockContactsForList]

      console.log("[v0] Local contacts:", localContactsForList.length, "Mock contacts:", mockContactsForList.length)
      setContacts(allContacts)
    }
    fetchContacts()
  }, [selectedList, localContacts])

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

  if (showCreateContacts) {
    return (
      <CreateContacts
        onBack={() => setShowCreateContacts(false)}
        listName={selectedList?.name}
        listId={selectedList?._id}
        onAddContacts={addContactsToLocal}
      />
    )
  }

  if (currentView === "createForm") {
    return (
      <div className="list-container">
        <div className="create-form-container">
          <div className="form-header">
            <button className="back-btn" onClick={() => setCurrentView("main")} style={{ color: "black" }}>
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
              <button className="create-list-btn" onClick={createListHandler} disabled={!newListName.trim()}>
                Create List
              </button>
            </div>
          </div>
        </div>
      </div>
    )
  }

  if (currentView === "listDetail" && selectedList) {
    console.log("[v0] Rendering list detail for:", selectedList.name, "with", contacts.length, "contacts")

    return (
      <div className="list-container">
        <div className="list-detail-container">
          <div className="detail-header">
            <button className="back-btn back-btn--contrast" onClick={() => setCurrentView("main")}>
              ← Back to Lists
            </button>
            <h1 className="detail-title">{selectedList.name}</h1>
            <div className="connection-status">
              {backendConnected ? (
                <span className="status-indicator status-connected">🟢 Connected to Database</span>
              ) : (
                <>
                  <span className="status-indicator status-disconnected">🔴 Database Offline</span>
                  <p className="status-help">
                    To see your real database contacts, start the backend server:
                    <br />
                    <code>cd backend && uvicorn main:app --reload --port 8000</code>
                  </p>
                </>
              )}
            </div>
          </div>

          {contacts.length > 0 ? (
            <div className="uploaded-contacts">
              <h2>
                {backendConnected
                  ? `${contacts.length} contact${contacts.length !== 1 ? "s" : ""} from your MongoDB database:`
                  : `${contacts.length} contact${contacts.length !== 1 ? "s" : ""} (using fallback data):`}
              </h2>
              <table className="contacts-table">
                <thead>
                  <tr>
                    <th>Email</th>
                    <th>Name</th>
                    <th>Company</th>
                    <th>Business Unit</th>
                  </tr>
                </thead>
                <tbody>
                  {contacts.map((c, idx) => {
                    console.log("[v0] Rendering contact:", c)
                    return (
                      <tr key={idx}>
                        <td>{c.email || "-"}</td>
                        <td>
                          {c.name ||
                            (c.firstName || c.lastName ? `${c.firstName || ""} ${c.lastName || ""}`.trim() : "-")}
                        </td>
                        <td>{c.companyName || "-"}</td>
                        <td>{c.businessUnit || "-"}</td>
                      </tr>
                    )
                  })}
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
                {backendConnected
                  ? "No contacts found in your database for this list. Start by adding some contacts."
                  : "Start building your contact database by adding contacts to this list."}
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
