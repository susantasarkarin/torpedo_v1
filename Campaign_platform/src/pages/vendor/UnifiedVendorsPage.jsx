"use client"

import { useState, useEffect } from "react"
import { API_BASE_URL as API_URL } from "../../config"
import "./UnifiedVendorsPage.css"
import { buildApiUrl } from "../../config"

function UnifiedVendorsPage() {
  const [vendors, setVendors] = useState([])
  const [loading, setLoading] = useState(true)
  const [searchTerm, setSearchTerm] = useState("")
  const [filterType, setFilterType] = useState("all")
  const [showAddModal, setShowAddModal] = useState(false)

  useEffect(() => {
    fetchAllVendors()
  }, [])

  const fetchAllVendors = async () => {
    try {
      setLoading(true)
      
      // Fetch unified vendors from the unified vendors endpoint
      const unifiedRes = await fetch(buildApiUrl(`/vendors/unified`))
      const unifiedData = unifiedRes.ok ? await unifiedRes.json() : []
      
      // Separate by source type
      const panelData = (unifiedData || []).filter(v => v.source === 'panel')
      const billingData = (unifiedData || []).filter(v => v.source === 'billing')

      // Merge and normalize vendors
      const panelVendors = (panelData || []).map(v => ({
        ...v,
        id: v._id || v.id,
        type: "panel",
        displayName: v.vendor_name || v.name || "Unknown",
        email: v.email || v.contact_email || "",
        linked_billing_id: v.linked_billing_vendor_id || null
      }))

      const billingVendors = (billingData || []).map(v => ({
        ...v,
        id: v._id || v.id,
        type: "billing",
        displayName: v.vendor_name || v.name || "Unknown",
        email: v.email || v.contact_email || "",
        linked_panel_id: v.linked_panel_vendor_id || null
      }))

      setVendors([...panelVendors, ...billingVendors])
    } catch (error) {
      console.error("Error fetching vendors:", error)
    } finally {
      setLoading(false)
    }
  }

  const filteredVendors = vendors.filter(vendor => {
    const matchesSearch = 
      vendor.displayName?.toLowerCase().includes(searchTerm.toLowerCase()) ||
      vendor.email?.toLowerCase().includes(searchTerm.toLowerCase())
    
    const matchesFilter = 
      filterType === "all" || 
      vendor.type === filterType

    return matchesSearch && matchesFilter
  })

  const getTypeLabel = (type) => {
    return type === "panel" ? "🎯 Panel" : "💰 Billing"
  }

  const getLinkedStatus = (vendor) => {
    if (vendor.type === "panel" && vendor.linked_billing_id) {
      return <span className="linked-badge">🔗 Linked to Billing</span>
    }
    if (vendor.type === "billing" && vendor.linked_panel_id) {
      return <span className="linked-badge">🔗 Linked to Panel</span>
    }
    return <span className="unlinked-badge">Not Linked</span>
  }

  if (loading) {
    return (
      <div className="unified-vendors-page">
        <div className="loading-spinner">Loading vendors...</div>
      </div>
    )
  }

  return (
    <div className="unified-vendors-page">
      <div className="page-header">
        <div className="header-left">
          <h1>📋 All Vendors</h1>
          <p className="page-subtitle">Unified view of all panel and billing vendors</p>
        </div>
        <div className="header-right">
          <button className="add-vendor-btn" onClick={() => setShowAddModal(true)}>
            ➕ Add Vendor
          </button>
        </div>
      </div>

      <div className="filters-bar">
        <div className="search-box">
          <input
            type="text"
            placeholder="Search vendors..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        </div>
        <div className="filter-buttons">
          <button 
            className={`filter-btn ${filterType === "all" ? "active" : ""}`}
            onClick={() => setFilterType("all")}
          >
            All ({vendors.length})
          </button>
          <button 
            className={`filter-btn ${filterType === "panel" ? "active" : ""}`}
            onClick={() => setFilterType("panel")}
          >
            🎯 Panel ({vendors.filter(v => v.type === "panel").length})
          </button>
          <button 
            className={`filter-btn ${filterType === "billing" ? "active" : ""}`}
            onClick={() => setFilterType("billing")}
          >
            💰 Billing ({vendors.filter(v => v.type === "billing").length})
          </button>
        </div>
      </div>

      <div className="vendors-table-container">
        <table className="vendors-table">
          <thead>
            <tr>
              <th>Vendor Name</th>
              <th>Type</th>
              <th>Email</th>
              <th>Link Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {filteredVendors.length === 0 ? (
              <tr>
                <td colSpan="5" className="no-data">
                  No vendors found
                </td>
              </tr>
            ) : (
              filteredVendors.map((vendor) => (
                <tr key={`${vendor.type}-${vendor.id}`}>
                  <td className="vendor-name">{vendor.displayName}</td>
                  <td>
                    <span className={`type-badge ${vendor.type}`}>
                      {getTypeLabel(vendor.type)}
                    </span>
                  </td>
                  <td className="vendor-email">{vendor.email || "-"}</td>
                  <td>{getLinkedStatus(vendor)}</td>
                  <td className="actions-cell">
                    <button className="action-btn view" title="View Details">👁️</button>
                    <button className="action-btn edit" title="Edit">✏️</button>
                    <button className="action-btn link" title="Link Vendor">🔗</button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {showAddModal && (
        <div className="modal-overlay" onClick={() => setShowAddModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <h2>Add New Vendor</h2>
            <p>Vendor creation form coming soon...</p>
            <button className="close-modal-btn" onClick={() => setShowAddModal(false)}>
              Close
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

export default UnifiedVendorsPage
