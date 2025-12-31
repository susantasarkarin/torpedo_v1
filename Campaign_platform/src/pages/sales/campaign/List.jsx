"use client"

import { useState, useEffect } from "react"
import { useLocation, useNavigate } from "react-router-dom"
import CreateContacts from "./CreateContacts"
import "./List.css"
import { API_BASE_URL } from "../../../config"


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
  const [currentPage, setCurrentPage] = useState(1)
  const [recordsPerPage, setRecordsPerPage] = useState(10)

  const [localContacts, setLocalContacts] = useState(() => {
    try {
      const stored = localStorage.getItem("contactListContacts")
      return stored ? JSON.parse(stored) : {}
    } catch {
      return {}
    }
  })

  // ✅ Workflow integration
  const location = useLocation()
  const navigate = useNavigate()
  const { selectedTemplate } = location.state || {}

  const addContactsToLocal = (listName, newContacts) => {
    const updated = {
      ...localContacts,
      [listName]: [...(localContacts[listName] || []), ...newContacts],
    }
    setLocalContacts(updated)
    localStorage.setItem("contactListContacts", JSON.stringify(updated))
    console.log(`[v0] Added ${newContacts.length} contacts to local storage for "${listName}"`)
  }

  useEffect(() => {
  async function fetchLists() {
    const sessionId = localStorage.getItem("session_id");
    if (!sessionId) {
      navigate("/login");
      return;
    }

    try {
      console.log(`[v0] Connecting to backend at ${API_BASE_URL}/lists/`);
      const res = await fetch(`${API_BASE_URL}/lists/`, {
        headers: {
          "Content-Type": "application/json",
          "Authorization": sessionId,
        },
      });

      if (res.status === 401) {
        alert("Session expired. Please login again.");
        localStorage.removeItem("session_id");
        navigate("/login");
        return;
      }

      if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);

      const data = await res.json();
      console.log("[v0] ✅ Got", data.lists?.length || 0, "lists from backend");
      setLists(data.lists || []);
      setBackendConnected(true);
    } catch (err) {
      console.log("[v0] ❌ Backend connection failed:", err.message);
      setBackendConnected(false);
      setLists([]);
    }
  }

  fetchLists();
}, [navigate]);


useEffect(() => {
  async function fetchContacts() {
    if (!selectedList) return;

    const sessionId = localStorage.getItem("session_id");
    if (!sessionId) {
      navigate("/login");
      return;
    }

    console.log("[v0] Fetching contacts for list:", selectedList.name, "ID:", selectedList._id);

    try {
      const res = await fetch(`${API_BASE_URL}/contacts/${selectedList._id}`, {
        headers: {
          "Content-Type": "application/json",
          "Authorization": sessionId,
        },
      });

      if (res.status === 401) {
        alert("Session expired. Please login again.");
        localStorage.removeItem("session_id");
        navigate("/login");
        return;
      }

      if (res.ok) {
        const data = await res.json();
        setContacts(data.contacts || []);
        setBackendConnected(true);
        return;
      } else {
        console.log("[v0] ❌ Contacts fetch failed with status:", res.status);
      }
    } catch (err) {
      console.log("[v0] ❌ Database fetch error:", err.message);
    }

    // fallback: localStorage only
    const localContactsForList = localContacts[selectedList.name] || [];
    setContacts(localContactsForList);
  }

  fetchContacts();
}, [selectedList, localContacts, navigate]);


 const saveListToDatabase = async (listData) => {
  const sessionId = localStorage.getItem("session_id");
  if (!sessionId) {
    navigate("/login");
    return;
  }

  try {
    const response = await fetch(`${API_BASE_URL}/create-list/`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": sessionId,
      },
      body: JSON.stringify(listData),
    });

    if (response.status === 401) {
      alert("Session expired. Please login again.");
      localStorage.removeItem("session_id");
      navigate("/login");
      return;
    }

    if (!response.ok) throw new Error("Failed to save list");
    const data = await response.json();
    setLists((prev) => [...prev, data.list]);
  } catch (error) {
    console.error("Error saving list to database:", error);
  }
};


  const handleDelete = async (id) => {
  const confirmDelete = window.confirm("Are you sure you want to delete this list?");
  if (!confirmDelete) return;

  const sessionId = localStorage.getItem("session_id");
  if (!sessionId) {
    navigate("/login");
    return;
  }

  try {
    const res = await fetch(`${API_BASE_URL}/delete-list/${id}`, {
      method: "DELETE",
      headers: {
        "Content-Type": "application/json",
        "Authorization": sessionId,
      },
    });

    if (res.status === 401) {
      alert("Session expired. Please login again.");
      localStorage.removeItem("session_id");
      navigate("/login");
      return;
    }

    if (!res.ok) throw new Error("Failed to delete list");
    setLists((prev) => prev.filter((l) => l._id !== id));
  } catch (err) {
    console.error("Delete failed:", err);
    alert("Could not delete list. Please try again.");
  }
};


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

    if (filters.search) {
      filteredLists = filteredLists.filter((list) => list.name.toLowerCase().includes(filters.search.toLowerCase()))
    }

    if (filters.status !== "all") {
      filteredLists = filteredLists.filter((list) => list.status === filters.status)
    }

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
    setCurrentPage(1)
  }

  const clearAllFilters = () => {
    setFilters({
      search: "",
      status: "all",
      contactCount: "all",
      dateRange: "all",
    })
    setCurrentPage(1)
  }

  const getActiveFilterCount = () => {
    let count = 0
    if (filters.search) count++
    if (filters.status !== "all") count++
    if (filters.contactCount !== "all") count++
    if (filters.dateRange !== "all") count++
    return count
  }

  const handleRecordsPerPageChange = (value) => {
    setRecordsPerPage(parseInt(value))
    setCurrentPage(1)
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
              <h2>{contacts.length} contact(s) loaded</h2>
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
                  {contacts.map((c, idx) => (
                    <tr key={idx}>
                      <td>{c.email || "-"}</td>
                      <td>{c.name || "-"}</td>
                      <td>{c.companyName || "-"}</td>
                      <td>{c.businessUnit || "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>

              {/* Grouped action buttons */}
              <div className="actions-row" role="group" aria-label="List actions">
                <button
                  className="create-contacts-btn"
                  onClick={() => setShowCreateContacts(true)}
                  aria-label="Add more contacts"
                >
                  Add More Contacts
                </button>

                {/* � Database Connection - AI Lead Import */}
                <button
                  className="create-contacts-btn"
                  onClick={() =>
                    navigate("/admin/sales/campaign/ai-leads", {
                      state: { selectedList },
                    })
                  }
                  aria-label="Import from LinkedIn Database"
                  title="Import AI-Classified LinkedIn Leads"
                  style={{ background: "linear-gradient(135deg, #8b5cf6, #7c3aed)" }}
                >
                  🤖 AI Lead Database
                </button>

                {/* �🚀 Workflow integration button */}
                <button
                  className="create-contacts-btn"
                  onClick={() =>
                    navigate("/admin/sales/campaign/workflow", {
                      state: { selectedTemplate, list: selectedList, contacts },
                    })
                  }
                  aria-label="Use this list in workflow"
                  title="Use This List in Workflow"
                >
                  🚀 Use This List in Workflow
                </button>
              </div>
            </div>
          ) : (
            <div className="empty-state">
              <div className="empty-icon">📋</div>
              <h2 className="empty-title">Ready to add contacts?</h2>
              <p className="empty-description" style={{margin:"auto"}}>
                {backendConnected
                  ? "No contacts found in your database for this list. Start by adding some contacts."
                  : "Start building your contact database by adding contacts to this list."}
              </p>
              {/* Grouped action buttons */}
              <div className="actions-row" role="group" aria-label="List actions">
                <button
                  className="create-contacts-btn"
                  onClick={() => setShowCreateContacts(true)}
                  aria-label="Add more contacts" style={{margin:"auto"}}
                >
                  Add Contacts
                </button>
                <button
                  className="create-contacts-btn"
                  onClick={() =>
                    navigate("/admin/sales/campaign/ai-leads", {
                      state: { selectedList },
                    })
                  }
                  aria-label="Import from LinkedIn Database"
                  style={{ background: "linear-gradient(135deg, #8b5cf6, #7c3aed)", margin: "auto" }}
                >
                  🤖 AI Lead Database
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    )
  }

  const filteredLists = getFilteredAndSortedLists()
  const activeFilterCount = getActiveFilterCount()
  
  const totalPages = Math.ceil(filteredLists.length / recordsPerPage)
  const startIdx = (currentPage - 1) * recordsPerPage
  const endIdx = startIdx + recordsPerPage
  const paginatedLists = filteredLists.slice(startIdx, endIdx)

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
            <div className="header-controls">
              <select className="sort-select" value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
                <option value="recent">Recently Created</option>
                <option value="name">Name A-Z</option>
                <option value="contacts">Most Contacts</option>
              </select>
              <select className="records-per-page-select" value={recordsPerPage} onChange={(e) => handleRecordsPerPageChange(e.target.value)}>
                <option value={10}>10 per page</option>
                <option value={20}>20 per page</option>
                <option value={50}>50 per page</option>
                <option value={100}>100 per page</option>
              </select>
            </div>
          </div>

          {activeFilterCount > 0 && (
            <div className="filter-results">
              Showing {filteredLists.length} of {lists.length} lists
            </div>
          )}

          <div className="lists-grid">
            {paginatedLists.length > 0 ? (
              paginatedLists.map((list) => (
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

          {totalPages > 1 && (
            <div className="pagination-container">
              <button
                className="pagination-btn"
                onClick={() => setCurrentPage(Math.max(1, currentPage - 1))}
                disabled={currentPage === 1}
              >
                ← Previous
              </button>
              <div className="page-info">
                Page <strong>{currentPage}</strong> of <strong>{totalPages}</strong>
              </div>
              <button
                className="pagination-btn"
                onClick={() => setCurrentPage(Math.min(totalPages, currentPage + 1))}
                disabled={currentPage === totalPages}
              >
                Next →
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default List
