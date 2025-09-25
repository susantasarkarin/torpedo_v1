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

  const [filters, setFilters] = useState({
    search: "",
    status: "all",
    contactCount: "all",
    dateRange: "all",
  })
  const [sortBy, setSortBy] = useState("recent")

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
      status: "inactive",
    },
    {
      _id: "list5",
      name: "List 5",
      contacts: 1,
      created: "Dec 16, 2024",
      status: "active",
    },
    {
      _id: "list6",
      name: "VIP Customers",
      contacts: 8,
      created: "Dec 10, 2024",
      status: "active",
    },
    {
      _id: "list7",
      name: "Newsletter Subscribers",
      contacts: 15,
      created: "Nov 28, 2024",
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
    "VIP Customers": [
      {
        email: "vip1@example.com",
        name: "VIP One",
        companyName: "VIP Co",
        businessUnit: "Executive",
      },
      {
        email: "vip2@example.com",
        name: "VIP Two",
        companyName: "VIP Co",
        businessUnit: "Executive",
      },
      {
        email: "vip3@example.com",
        name: "VIP Three",
        companyName: "VIP Co",
        businessUnit: "Executive",
      },
      {
        email: "vip4@example.com",
        name: "VIP Four",
        companyName: "VIP Co",
        businessUnit: "Executive",
      },
      {
        email: "vip5@example.com",
        name: "VIP Five",
        companyName: "VIP Co",
        businessUnit: "Executive",
      },
      {
        email: "vip6@example.com",
        name: "VIP Six",
        companyName: "VIP Co",
        businessUnit: "Executive",
      },
      {
        email: "vip7@example.com",
        name: "VIP Seven",
        companyName: "VIP Co",
        businessUnit: "Executive",
      },
      {
        email: "vip8@example.com",
        name: "VIP Eight",
        companyName: "VIP Co",
        businessUnit: "Executive",
      },
    ],
    "Newsletter Subscribers": [
      {
        email: "subscriber1@example.com",
        name: "Subscriber One",
        companyName: "Subscriber Co",
        businessUnit: "Marketing",
      },
      {
        email: "subscriber2@example.com",
        name: "Subscriber Two",
        companyName: "Subscriber Co",
        businessUnit: "Marketing",
      },
      {
        email: "subscriber3@example.com",
        name: "Subscriber Three",
        companyName: "Subscriber Co",
        businessUnit: "Marketing",
      },
      {
        email: "subscriber4@example.com",
        name: "Subscriber Four",
        companyName: "Subscriber Co",
        businessUnit: "Marketing",
      },
      {
        email: "subscriber5@example.com",
        name: "Subscriber Five",
        companyName: "Subscriber Co",
        businessUnit: "Marketing",
      },
      {
        email: "subscriber6@example.com",
        name: "Subscriber Six",
        companyName: "Subscriber Co",
        businessUnit: "Marketing",
      },
      {
        email: "subscriber7@example.com",
        name: "Subscriber Seven",
        companyName: "Subscriber Co",
        businessUnit: "Marketing",
      },
      {
        email: "subscriber8@example.com",
        name: "Subscriber Eight",
        companyName: "Subscriber Co",
        businessUnit: "Marketing",
      },
      {
        email: "subscriber9@example.com",
        name: "Subscriber Nine",
        companyName: "Subscriber Co",
        businessUnit: "Marketing",
      },
      {
        email: "subscriber10@example.com",
        name: "Subscriber Ten",
        companyName: "Subscriber Co",
        businessUnit: "Marketing",
      },
      {
        email: "subscriber11@example.com",
        name: "Subscriber Eleven",
        companyName: "Subscriber Co",
        businessUnit: "Marketing",
      },
      {
        email: "subscriber12@example.com",
        name: "Subscriber Twelve",
        companyName: "Subscriber Co",
        businessUnit: "Marketing",
      },
      {
        email: "subscriber13@example.com",
        name: "Subscriber Thirteen",
        companyName: "Subscriber Co",
        businessUnit: "Marketing",
      },
      {
        email: "subscriber14@example.com",
        name: "Subscriber Fourteen",
        companyName: "Subscriber Co",
        businessUnit: "Marketing",
      },
      {
        email: "subscriber15@example.com",
        name: "Subscriber Fifteen",
        companyName: "Subscriber Co",
        businessUnit: "Marketing",
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

  const getFilteredAndSortedLists = () => {
    let filteredLists = [...lists]

    // Apply search filter
    if (filters.search) {
      filteredLists = filteredLists.filter((list) => list.name.toLowerCase().includes(filters.search.toLowerCase()))
    }

    // Apply status filter
    if (filters.status !== "all") {
      filteredLists = filteredLists.filter((list) => list.status === filters.status)
    }

    // Apply contact count filter
    if (filters.contactCount !== "all") {
      filteredLists = filteredLists.filter((list) => {
        const count = list.contacts || 0
        switch (filters.contactCount) {
          case "empty":
            return count === 0
          case "small":
            return count >= 1 && count <= 5
          case "medium":
            return count >= 6 && count <= 15
          case "large":
            return count > 15
          default:
            return true
        }
      })
    }

    // Apply date range filter
    if (filters.dateRange !== "all") {
      const now = new Date()
      filteredLists = filteredLists.filter((list) => {
        const listDate = new Date(list.created)
        const daysDiff = Math.floor((now - listDate) / (1000 * 60 * 60 * 24))

        switch (filters.dateRange) {
          case "today":
            return daysDiff === 0
          case "week":
            return daysDiff <= 7
          case "month":
            return daysDiff <= 30
          case "older":
            return daysDiff > 30
          default:
            return true
        }
      })
    }

    // Apply sorting
    filteredLists.sort((a, b) => {
      switch (sortBy) {
        case "recent":
          return new Date(b.created) - new Date(a.created)
        case "name":
          return a.name.localeCompare(b.name)
        case "contacts":
          return (b.contacts || 0) - (a.contacts || 0)
        default:
          return 0
      }
    })

    return filteredLists
  }

  const handleFilterChange = (filterType, value) => {
    setFilters((prev) => ({
      ...prev,
      [filterType]: value,
    }))
  }

  const clearAllFilters = () => {
    setFilters({
      search: "",
      status: "all",
      contactCount: "all",
      dateRange: "all",
    })
  }

  const getActiveFilterCount = () => {
    let count = 0
    if (filters.search) count++
    if (filters.status !== "all") count++
    if (filters.contactCount !== "all") count++
    if (filters.dateRange !== "all") count++
    return count
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

  const filteredLists = getFilteredAndSortedLists()
  const activeFilterCount = getActiveFilterCount()

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
          <div className="stat-number">{filteredLists.length}</div>
          <div className="stat-label">Filtered Results</div>
        </div>
      </div>

      <div className="content-wrapper">
        <div className="filters-panel">
          <div className="filter-header">
            <h3 className="panel-title">Filters</h3>
            {activeFilterCount > 0 && (
              <button className="clear-filters-btn" onClick={clearAllFilters}>
                Clear All ({activeFilterCount})
              </button>
            )}
          </div>

          <div className="filter-group">
            <label className="filter-label">Search Lists</label>
            <input
              type="text"
              className="filter-input"
              placeholder="Search by name..."
              value={filters.search}
              onChange={(e) => handleFilterChange("search", e.target.value)}
            />
          </div>

          <div className="filter-group">
            <label className="filter-label">Status</label>
            <div className="radio-group">
              {[
                { value: "all", label: "All Status" },
                { value: "active", label: "Active" },
                { value: "inactive", label: "Inactive" },
              ].map((option) => (
                <label key={option.value} className="radio-item">
                  <input
                    type="radio"
                    name="status"
                    value={option.value}
                    checked={filters.status === option.value}
                    onChange={(e) => handleFilterChange("status", e.target.value)}
                  />
                  <span className="radio-text">{option.label}</span>
                </label>
              ))}
            </div>
          </div>

          <div className="filter-group">
            <label className="filter-label">Contact Count</label>
            <div className="radio-group">
              {[
                { value: "all", label: "Any Size" },
                { value: "empty", label: "Empty (0)" },
                { value: "small", label: "Small (1-5)" },
                { value: "medium", label: "Medium (6-15)" },
                { value: "large", label: "Large (15+)" },
              ].map((option) => (
                <label key={option.value} className="radio-item">
                  <input
                    type="radio"
                    name="contactCount"
                    value={option.value}
                    checked={filters.contactCount === option.value}
                    onChange={(e) => handleFilterChange("contactCount", e.target.value)}
                  />
                  <span className="radio-text">{option.label}</span>
                </label>
              ))}
            </div>
          </div>

          <div className="filter-group">
            <label className="filter-label">Created</label>
            <div className="radio-group">
              {[
                { value: "all", label: "Any Time" },
                { value: "today", label: "Today" },
                { value: "week", label: "This Week" },
                { value: "month", label: "This Month" },
                { value: "older", label: "Older" },
              ].map((option) => (
                <label key={option.value} className="radio-item">
                  <input
                    type="radio"
                    name="dateRange"
                    value={option.value}
                    checked={filters.dateRange === option.value}
                    onChange={(e) => handleFilterChange("dateRange", e.target.value)}
                  />
                  <span className="radio-text">{option.label}</span>
                </label>
              ))}
            </div>
          </div>
        </div>

        <div className="lists-section">
          <div className="section-header">
            <h2 className="section-title">Your Lists</h2>
            <select className="sort-select" value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
              <option value="recent">Recently Created</option>
              <option value="name">Name A-Z</option>
              <option value="contacts">Most Contacts</option>
            </select>
          </div>

          {activeFilterCount > 0 && (
            <div className="filter-results">
              Showing {filteredLists.length} of {lists.length} lists
            </div>
          )}

          <div className="lists-grid">
            {filteredLists.length > 0 ? (
              filteredLists.map((list) => (
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
                      {/* <p className="contact-count">{list.contacts || 0} contacts</p> */}
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
              ))
            ) : (
              <div className="no-results">
                <div className="no-results-icon">🔍</div>
                <h3>No lists match your filters</h3>
                <p>Try adjusting your search criteria or clearing some filters.</p>
                <button className="clear-filters-btn" onClick={clearAllFilters}>
                  Clear All Filters
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export default List
