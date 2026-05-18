"use client"

import { useState, useEffect, useRef, useMemo } from "react"
import { API_BASE_URL } from "../../config"
import { Building2, Search, Pencil, Trash2, Loader2, Upload, Download, Link2, Unlink } from "lucide-react"
import { buildApiUrl } from "../../config"
import Pagination from "../../components/ui/Pagination"

// GST Treatment options
const GST_TREATMENT_OPTIONS = [
  { value: "registered_regular", label: "Registered Business - Regular" },
  { value: "registered_composition", label: "Registered Business - Composition" },
  { value: "unregistered", label: "Unregistered Business" },
  { value: "consumer", label: "Consumer" },
  { value: "overseas", label: "Overseas" },
]

// Vendor type options
const VENDOR_TYPE_OPTIONS = [
  { value: "supplier", label: "Supplier" },
  { value: "contractor", label: "Contractor" },
  { value: "service_provider", label: "Service Provider" },
  { value: "consultant", label: "Consultant" },
]

// Indian states list
const INDIAN_STATES = [
  "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh",
  "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka",
  "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram",
  "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu",
  "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal",
  "Andaman and Nicobar Islands", "Chandigarh", "Dadra and Nagar Haveli and Daman and Diu",
  "Delhi", "Jammu and Kashmir", "Ladakh", "Lakshadweep", "Puducherry"
]

function VendorsPage() {
  const [vendors, setVendors] = useState([])
  const [loading, setLoading] = useState(true)
  const [searchTerm, setSearchTerm] = useState("")
  const [showModal, setShowModal] = useState(false)
  const [editingVendor, setEditingVendor] = useState(null)
  const [formErrors, setFormErrors] = useState({})
  const [exporting, setExporting] = useState(false)
  const [importing, setImporting] = useState(false)
  const [currentPage, setCurrentPage] = useState(1)
  const [recordsPerPage, setRecordsPerPage] = useState(100)
  const [totalRecords, setTotalRecords] = useState(0)
  const [totalPages, setTotalPages] = useState(1)
  const fileInputRef = useRef(null)
  
  const initialFormData = {
    name: "",
    vendor_type: "supplier",
    company_name: "",
    email: "",
    phone: "",
    gst_treatment: "unregistered",
    gstin: "",
    pan: "",
    billing_address: {
      line1: "",
      line2: "",
      city: "",
      state: "",
      pincode: "",
      country: "India",
    },
    payment_terms: 30,
    currency: "INR",
    bank_name: "",
    account_number: "",
    ifsc_code: "",
    opening_balance: 0,
    notes: "",
    status: "active",
  }
  
  const [formData, setFormData] = useState(initialFormData)
  
  // Panel Vendor Linking State
  const [showLinkModal, setShowLinkModal] = useState(false)
  const [panelVendors, setPanelVendors] = useState([])
  const [selectedVendorForLink, setSelectedVendorForLink] = useState(null)
  const [selectedPanelVendor, setSelectedPanelVendor] = useState("")
  const [linking, setLinking] = useState(false)

  useEffect(() => {
    fetchVendors()
  }, [currentPage])

  const fetchVendors = async (pg = currentPage, ps = recordsPerPage, srch = searchTerm) => {
    try {
      setLoading(true)
      const params = new URLSearchParams({ page: String(pg), page_size: String(ps) })
      if (srch) params.set("search", srch)
      const response = await fetch(buildApiUrl(`/finance/vendors/?${params}`))
      if (response.ok) {
        const data = await response.json()
        setVendors(data.vendors || [])
        setTotalRecords(data.total || 0)
        setTotalPages(data.pages || 1)
      }
    } catch (error) {
      console.error("Error fetching vendors:", error)
    } finally {
      setLoading(false)
    }
  }

  // Fetch available panel vendors for linking
  const fetchPanelVendors = async () => {
    try {
      const response = await fetch(buildApiUrl(`/finance/vendors/panel-vendors`))
      if (response.ok) {
        const data = await response.json()
        setPanelVendors(data)
      }
    } catch (error) {
      console.error("Error fetching panel vendors:", error)
    }
  }

  // Open link modal for a vendor
  const openLinkModal = (vendor) => {
    setSelectedVendorForLink(vendor)
    setSelectedPanelVendor("")
    fetchPanelVendors()
    setShowLinkModal(true)
  }

  // Link vendor to panel vendor
  const handleLinkVendor = async () => {
    if (!selectedVendorForLink || !selectedPanelVendor) return
    
    setLinking(true)
    try {
      const response = await fetch(
        buildApiUrl(`/finance/vendors/${selectedVendorForLink._id}/link-panel-vendor`),
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ panel_vendor_id: selectedPanelVendor }),
        }
      )
      
      if (response.ok) {
        fetchVendors()
        setShowLinkModal(false)
        alert("Vendor linked successfully!")
      } else {
        const error = await response.json()
        alert(error.detail || "Failed to link vendor")
      }
    } catch (error) {
      console.error("Error linking vendor:", error)
      alert("Failed to link vendor")
    } finally {
      setLinking(false)
    }
  }

  // Unlink vendor from panel vendor
  const handleUnlinkVendor = async (vendorId) => {
    if (!window.confirm("Are you sure you want to unlink this vendor from the panel vendor?")) return
    
    try {
      const response = await fetch(
        buildApiUrl(`/finance/vendors/${vendorId}/unlink-panel-vendor`),
        { method: "DELETE" }
      )
      
      if (response.ok) {
        fetchVendors()
        alert("Vendor unlinked successfully!")
      } else {
        const error = await response.json()
        alert(error.detail || "Failed to unlink vendor")
      }
    } catch (error) {
      console.error("Error unlinking vendor:", error)
    }
  }

  // Validation helpers
  const validateEmail = (email) => {
    if (!email) return true
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
    return emailRegex.test(email)
  }

  const validatePhone = (phone) => {
    if (!phone) return true
    const phoneRegex = /^(\+91[\-\s]?)?[0]?(91)?[6789]\d{9}$/
    return phoneRegex.test(phone.replace(/\s/g, ""))
  }

  const validateGSTIN = (gstin) => {
    if (!gstin) return true
    const gstinRegex = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$/
    return gstinRegex.test(gstin)
  }

  const validatePAN = (pan) => {
    if (!pan) return true
    const panRegex = /^[A-Z]{5}[0-9]{4}[A-Z]{1}$/
    return panRegex.test(pan)
  }

  const validateIFSC = (ifsc) => {
    if (!ifsc) return true
    const ifscRegex = /^[A-Z]{4}0[A-Z0-9]{6}$/
    return ifscRegex.test(ifsc)
  }

  const isGSTINRequired = () => {
    return formData.gst_treatment === "registered_regular" || formData.gst_treatment === "registered_composition"
  }

  const validateForm = () => {
    const errors = {}
    
    if (!formData.name.trim()) {
      errors.name = "Vendor name is required"
    }
    
    if (!validateEmail(formData.email)) {
      errors.email = "Invalid email format"
    }
    
    if (!validatePhone(formData.phone)) {
      errors.phone = "Invalid phone number format"
    }
    
    if (isGSTINRequired() && !formData.gstin) {
      errors.gstin = "GSTIN is required for registered businesses"
    } else if (formData.gstin && !validateGSTIN(formData.gstin)) {
      errors.gstin = "Invalid GSTIN format (e.g., 29ABCDE1234F1Z5)"
    }
    
    if (formData.pan && !validatePAN(formData.pan)) {
      errors.pan = "Invalid PAN format (e.g., ABCDE1234F)"
    }
    
    if (formData.ifsc_code && !validateIFSC(formData.ifsc_code)) {
      errors.ifsc_code = "Invalid IFSC format (e.g., SBIN0001234)"
    }
    
    setFormErrors(errors)
    return Object.keys(errors).length === 0
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    
    if (!validateForm()) {
      return
    }
    
    try {
      const url = editingVendor
        ? buildApiUrl(`/finance/vendors/${editingVendor._id}`)
        : buildApiUrl(`/finance/vendors/`)

      const method = editingVendor ? "PUT" : "POST"

      const response = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(formData),
      })

      if (response.ok) {
        fetchVendors()
        handleCloseModal()
      }
    } catch (error) {
      console.error("Error saving vendor:", error)
    }
  }

  const handleDelete = async (id) => {
    if (!window.confirm("Are you sure you want to delete this vendor?")) return

    try {
      const response = await fetch(buildApiUrl(`/finance/vendors/${id}`), {
        method: "DELETE",
      })
      if (response.ok) {
        fetchVendors()
      }
    } catch (error) {
      console.error("Error deleting vendor:", error)
    }
  }

  const handleEdit = (vendor) => {
    setEditingVendor(vendor)
    setFormData({
      name: vendor.name || "",
      vendor_type: vendor.vendor_type || "supplier",
      company_name: vendor.company_name || "",
      email: vendor.email || "",
      phone: vendor.phone || "",
      gst_treatment: vendor.gst_treatment || "unregistered",
      gstin: vendor.gstin || "",
      pan: vendor.pan || "",
      billing_address: vendor.billing_address || {
        line1: "",
        line2: "",
        city: "",
        state: "",
        pincode: "",
        country: "India",
      },
      payment_terms: vendor.payment_terms || 30,
      currency: vendor.currency || "INR",
      bank_name: vendor.bank_name || "",
      account_number: vendor.account_number || "",
      ifsc_code: vendor.ifsc_code || "",
      opening_balance: vendor.opening_balance || 0,
      notes: vendor.notes || "",
      status: vendor.status || "active",
    })
    setFormErrors({})
    setShowModal(true)
  }

  const handleCloseModal = () => {
    setShowModal(false)
    setEditingVendor(null)
    setFormData(initialFormData)
    setFormErrors({})
  }

  const paginatedVendors = vendors

  const handleSearch = (value) => {
    setSearchTerm(value)
    setCurrentPage(1)
    fetchVendors(1, recordsPerPage, value)
  }

  const handleRecordsPerPageChange = (value) => {
    const ps = typeof value === 'number' ? value : parseInt(value)
    setRecordsPerPage(ps)
    setCurrentPage(1)
    fetchVendors(1, ps, searchTerm)
  }

  const formatCurrency = (amount) => {
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency: "INR",
      maximumFractionDigits: 0,
    }).format(amount || 0)
  }

  // Export vendors to CSV
  const handleExportCSV = async () => {
    setExporting(true)
    try {
      const response = await fetch(buildApiUrl(`/finance/vendors/export/csv`))
      if (response.ok) {
        const blob = await response.blob()
        const url = window.URL.createObjectURL(blob)
        const a = document.createElement("a")
        a.href = url
        a.download = `vendors_export_${new Date().toISOString().split("T")[0]}.csv`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        window.URL.revokeObjectURL(url)
      }
    } catch (error) {
      console.error("Error exporting vendors:", error)
      alert("Failed to export vendors")
    } finally {
      setExporting(false)
    }
  }

  // Import vendors from CSV
  const handleImportCSV = async (event) => {
    const file = event.target.files?.[0]
    if (!file) return

    setImporting(true)
    const formDataUpload = new FormData()
    formDataUpload.append("file", file)

    try {
      const response = await fetch(buildApiUrl(`/finance/vendors/import/csv`), {
        method: "POST",
        body: formDataUpload,
      })

      if (response.ok) {
        const result = await response.json()
        alert(`Successfully imported ${result.imported} vendors`)
        fetchVendors()
      } else {
        const error = await response.json()
        alert(`Import failed: ${error.detail}`)
      }
    } catch (error) {
      console.error("Error importing vendors:", error)
      alert("Failed to import vendors")
    } finally {
      setImporting(false)
      if (fileInputRef.current) {
        fileInputRef.current.value = ""
      }
    }
  }

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <div>
          <h2 style={styles.title}>Vendors</h2>
          <p style={styles.subtitle}>Manage your vendor accounts</p>
        </div>
        <div style={{ display: "flex", gap: "0.75rem" }}>
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleImportCSV}
            accept=".csv"
            style={{ display: "none" }}
          />
          <button 
            style={styles.btnSecondary} 
            onClick={() => fileInputRef.current?.click()}
            disabled={importing}
          >
            <Upload style={{ width: "16px", height: "16px" }} />
            {importing ? "Importing..." : "Import CSV"}
          </button>
          <button 
            style={styles.btnSecondary} 
            onClick={handleExportCSV}
            disabled={exporting}
          >
            <Download style={{ width: "16px", height: "16px" }} />
            {exporting ? "Exporting..." : "Export CSV"}
          </button>
          <button style={styles.btnPrimary} onClick={() => setShowModal(true)}>
            + Add Vendor
          </button>
        </div>
      </div>

      <div style={styles.searchSection}>
        <div style={{ flex: 1, maxWidth: "400px", position: "relative" }}>
          <Search
            style={{
              position: "absolute",
              left: "12px",
              top: "50%",
              transform: "translateY(-50%)",
              width: "16px",
              height: "16px",
              color: "#9ca3af",
            }}
          />
          <input
            type="text"
            placeholder="Search by name, email, GSTIN..."
            value={searchTerm}
            onChange={(e) => handleSearch(e.target.value)}
            style={styles.searchInput}
          />
        </div>
        <select
          style={styles.recordsPerPageSelect}
          value={recordsPerPage}
          onChange={(e) => handleRecordsPerPageChange(e.target.value)}
        >
          <option value={10}>10 per page</option>
          <option value={20}>20 per page</option>
          <option value={50}>50 per page</option>
          <option value={100}>100 per page</option>
          <option value={200}>200 per page</option>
        </select>
        <div style={styles.stats}>
          <span>Total: <strong>{vendors.length}</strong></span>
          <span>Active: <strong>{vendors.filter(v => v.status === "active").length}</strong></span>
          <span>Inactive: <strong>{vendors.filter(v => v.status === "inactive").length}</strong></span>
        </div>
      </div>

      {loading ? (
        <div style={styles.tableContainer}>
          <div style={{ textAlign: "center", padding: "3rem" }}>
            <Loader2
              style={{
                width: "32px",
                height: "32px",
                animation: "spin 1s linear infinite",
                margin: "0 auto 1rem",
                color: "#0d6efd",
              }}
            />
            <p style={{ color: "#6b7280" }}>Loading vendors...</p>
          </div>
        </div>
      ) : (
        <div style={styles.tableContainer}>
          <table style={styles.table}>
            <thead style={styles.thead}>
              <tr>
                <th style={styles.th}>Name</th>
                <th style={styles.th}>Email</th>
                <th style={styles.th}>Phone</th>
                <th style={styles.th}>GSTIN</th>
                <th style={styles.th}>Status</th>
                <th style={styles.th}>Outstanding</th>
                <th style={styles.th}>Panel Link</th>
                <th style={styles.th}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {paginatedVendors.map((vendor) => (
                <tr key={vendor._id} style={styles.tr}>
                  <td style={styles.td}>
                    <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
                      <div
                        style={{
                          width: "32px",
                          height: "32px",
                          backgroundColor: "#f3f4f6",
                          borderRadius: "0.5rem",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                        }}
                      >
                        {vendor.name?.charAt(0).toUpperCase()}
                      </div>
                      <span style={{ fontWeight: "500" }}>{vendor.name}</span>
                    </div>
                  </td>
                  <td style={styles.td}>{vendor.email || "-"}</td>
                  <td style={styles.td}>{vendor.phone || "-"}</td>
                  <td style={styles.td}>
                    <code
                      style={{
                        fontSize: "0.85rem",
                        backgroundColor: "#f3f4f6",
                        padding: "0.375rem 0.75rem",
                        borderRadius: "0.375rem",
                        fontFamily: "monospace",
                      }}
                    >
                      {vendor.gstin || "-"}
                    </code>
                  </td>
                  <td style={styles.td}>
                    <span style={{
                      ...styles.statusBadge,
                      ...(vendor.status === 'active' ? styles.statusActive : styles.statusInactive)
                    }}>
                      {vendor.status === 'active' ? 'Active' : 'Inactive'}
                    </span>
                  </td>
                  <td style={{ ...styles.td, fontWeight: "600" }}>{formatCurrency(vendor.outstanding_amount)}</td>
                  <td style={styles.td}>
                    {/* Panel Vendor Link Status */}
                    {vendor.is_panel_vendor ? (
                      <span 
                        style={{
                          backgroundColor: "#dbeafe",
                          color: "#1e40af",
                          padding: "2px 8px",
                          borderRadius: "4px",
                          fontSize: "0.75rem",
                          fontWeight: "500"
                        }}
                        title={`Linked to: ${vendor.panel_vendor_name || vendor.panel_vendor_vid}`}
                      >
                        🔗 {vendor.panel_vendor_name || vendor.panel_vendor_vid || "Linked"}
                      </span>
                    ) : (
                      <span style={{ color: "#9ca3af", fontSize: "0.75rem" }}>Not linked</span>
                    )}
                  </td>
                  <td style={styles.td}>
                    <div style={styles.actionButtons}>
                      <button style={styles.btnEdit} onClick={() => handleEdit(vendor)}>
                        <Pencil style={{ width: "16px", height: "16px" }} />
                      </button>
                      {vendor.is_panel_vendor ? (
                        <button 
                          style={{ ...styles.btnDelete, backgroundColor: "#fef3c7" }}
                          onClick={() => handleUnlinkVendor(vendor._id)}
                          title="Unlink from Panel Vendor"
                        >
                          <Unlink style={{ width: "16px", height: "16px", color: "#92400e" }} />
                        </button>
                      ) : (
                        <button 
                          style={{ ...styles.btnEdit, backgroundColor: "#dbeafe" }}
                          onClick={() => openLinkModal(vendor)}
                          title="Link to Panel Vendor"
                        >
                          <Link2 style={{ width: "16px", height: "16px", color: "#1e40af" }} />
                        </button>
                      )}
                      <button style={styles.btnDelete} onClick={() => handleDelete(vendor._id)}>
                        <Trash2 style={{ width: "16px", height: "16px" }} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {paginatedVendors.length === 0 && filteredVendors.length === 0 && (
                <tr>
                  <td colSpan={8} style={styles.emptyState}>
                    <Building2 style={{ width: "48px", height: "48px", margin: "0 auto 1rem", opacity: 0.5 }} />
                    <p>No vendors found. Click "Add Vendor" to create one.</p>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      <Pagination
        currentPage={currentPage}
        totalPages={totalPages}
        totalRecords={totalRecords}
        pageSize={recordsPerPage}
        onPageChange={(p) => setCurrentPage(p)}
        onPageSizeChange={handleRecordsPerPageChange}
        loading={loading}
      />

      {showModal && (
        <div style={styles.modal} onClick={handleCloseModal}>
          <div style={styles.modalContent} onClick={(e) => e.stopPropagation()}>
            <div style={styles.modalHeader}>
              <h3 style={styles.modalTitle}>{editingVendor ? "Edit Vendor" : "Add Vendor"}</h3>
              <button style={styles.closeBtn} onClick={handleCloseModal}>
                ×
              </button>
            </div>

            <div style={{ ...styles.modalBody, overflow: "auto", flex: 1, maxHeight: "70vh" }}>
              {/* Basic Information */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "1rem", marginBottom: "1.5rem" }}>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Vendor Name *</label>
                  <input
                    style={{ ...styles.input, borderColor: formErrors.name ? "#ef4444" : undefined }}
                    type="text"
                    value={formData.name}
                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                    required
                    placeholder="Enter vendor name"
                  />
                  {formErrors.name && <span style={styles.errorText}>{formErrors.name}</span>}
                </div>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Vendor Type</label>
                  <select
                    style={styles.select}
                    value={formData.vendor_type}
                    onChange={(e) => setFormData({ ...formData, vendor_type: e.target.value })}
                  >
                    {VENDOR_TYPE_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>{opt.label}</option>
                    ))}
                  </select>
                </div>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Company Name</label>
                  <input
                    style={styles.input}
                    type="text"
                    value={formData.company_name}
                    onChange={(e) => setFormData({ ...formData, company_name: e.target.value })}
                    placeholder="Company name (if applicable)"
                  />
                </div>
              </div>

              {/* Contact Information */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem", marginBottom: "1.5rem" }}>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Email</label>
                  <input
                    style={{ ...styles.input, borderColor: formErrors.email ? "#ef4444" : undefined }}
                    type="email"
                    value={formData.email}
                    onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                    placeholder="vendor@example.com"
                  />
                  {formErrors.email && <span style={styles.errorText}>{formErrors.email}</span>}
                </div>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Phone</label>
                  <input
                    style={{ ...styles.input, borderColor: formErrors.phone ? "#ef4444" : undefined }}
                    type="tel"
                    value={formData.phone}
                    onChange={(e) => setFormData({ ...formData, phone: e.target.value })}
                    placeholder="+91 XXXXX XXXXX"
                  />
                  {formErrors.phone && <span style={styles.errorText}>{formErrors.phone}</span>}
                </div>
              </div>

              {/* GST Information */}
              <div style={styles.section}>
                <h4 style={styles.sectionTitle}>GST Information</h4>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "1rem" }}>
                  <div style={styles.formGroup}>
                    <label style={styles.label}>GST Treatment *</label>
                    <select
                      style={styles.select}
                      value={formData.gst_treatment}
                      onChange={(e) => setFormData({ ...formData, gst_treatment: e.target.value })}
                    >
                      {GST_TREATMENT_OPTIONS.map((opt) => (
                        <option key={opt.value} value={opt.value}>{opt.label}</option>
                      ))}
                    </select>
                  </div>
                  <div style={styles.formGroup}>
                    <label style={styles.label}>
                      GSTIN {isGSTINRequired() && <span style={{ color: "#ef4444" }}>*</span>}
                    </label>
                    <input
                      style={{ ...styles.input, borderColor: formErrors.gstin ? "#ef4444" : undefined }}
                      type="text"
                      value={formData.gstin}
                      onChange={(e) => setFormData({ ...formData, gstin: e.target.value.toUpperCase() })}
                      placeholder="29ABCDE1234F1Z5"
                      maxLength={15}
                    />
                    {formErrors.gstin && <span style={styles.errorText}>{formErrors.gstin}</span>}
                  </div>
                  <div style={styles.formGroup}>
                    <label style={styles.label}>PAN</label>
                    <input
                      style={{ ...styles.input, borderColor: formErrors.pan ? "#ef4444" : undefined }}
                      type="text"
                      value={formData.pan}
                      onChange={(e) => setFormData({ ...formData, pan: e.target.value.toUpperCase() })}
                      placeholder="ABCDE1234F"
                      maxLength={10}
                    />
                    {formErrors.pan && <span style={styles.errorText}>{formErrors.pan}</span>}
                  </div>
                </div>
              </div>

              {/* Billing Address */}
              <div style={styles.section}>
                <h4 style={styles.sectionTitle}>Billing Address</h4>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
                  <div style={{ gridColumn: "1 / -1" }}>
                    <div style={styles.formGroup}>
                      <label style={styles.label}>Address Line 1</label>
                      <input
                        style={styles.input}
                        type="text"
                        value={formData.billing_address.line1}
                        onChange={(e) =>
                          setFormData({
                            ...formData,
                            billing_address: { ...formData.billing_address, line1: e.target.value },
                          })
                        }
                        placeholder="Street address"
                      />
                    </div>
                  </div>
                  <div style={{ gridColumn: "1 / -1" }}>
                    <div style={styles.formGroup}>
                      <label style={styles.label}>Address Line 2</label>
                      <input
                        style={styles.input}
                        type="text"
                        value={formData.billing_address.line2}
                        onChange={(e) =>
                          setFormData({
                            ...formData,
                            billing_address: { ...formData.billing_address, line2: e.target.value },
                          })
                        }
                        placeholder="Apartment, suite, etc."
                      />
                    </div>
                  </div>
                  <div style={styles.formGroup}>
                    <label style={styles.label}>City</label>
                    <input
                      style={styles.input}
                      type="text"
                      value={formData.billing_address.city}
                      onChange={(e) =>
                        setFormData({
                          ...formData,
                          billing_address: { ...formData.billing_address, city: e.target.value },
                        })
                      }
                    />
                  </div>
                  <div style={styles.formGroup}>
                    <label style={styles.label}>State</label>
                    <select
                      style={styles.select}
                      value={formData.billing_address.state}
                      onChange={(e) =>
                        setFormData({
                          ...formData,
                          billing_address: { ...formData.billing_address, state: e.target.value },
                        })
                      }
                    >
                      <option value="">Select State</option>
                      {INDIAN_STATES.map((state) => (
                        <option key={state} value={state}>{state}</option>
                      ))}
                    </select>
                  </div>
                  <div style={styles.formGroup}>
                    <label style={styles.label}>Pincode</label>
                    <input
                      style={styles.input}
                      type="text"
                      value={formData.billing_address.pincode}
                      onChange={(e) =>
                        setFormData({
                          ...formData,
                          billing_address: { ...formData.billing_address, pincode: e.target.value },
                        })
                      }
                      maxLength={6}
                    />
                  </div>
                  <div style={styles.formGroup}>
                    <label style={styles.label}>Country</label>
                    <input
                      style={styles.input}
                      type="text"
                      value={formData.billing_address.country}
                      onChange={(e) =>
                        setFormData({
                          ...formData,
                          billing_address: { ...formData.billing_address, country: e.target.value },
                        })
                      }
                    />
                  </div>
                </div>
              </div>

              {/* Bank Details */}
              <div style={styles.section}>
                <h4 style={styles.sectionTitle}>Bank Details</h4>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "1rem" }}>
                  <div style={styles.formGroup}>
                    <label style={styles.label}>Bank Name</label>
                    <input
                      style={styles.input}
                      type="text"
                      value={formData.bank_name}
                      onChange={(e) => setFormData({ ...formData, bank_name: e.target.value })}
                      placeholder="Bank name"
                    />
                  </div>
                  <div style={styles.formGroup}>
                    <label style={styles.label}>Account Number</label>
                    <input
                      style={styles.input}
                      type="text"
                      value={formData.account_number}
                      onChange={(e) => setFormData({ ...formData, account_number: e.target.value })}
                      placeholder="Account number"
                    />
                  </div>
                  <div style={styles.formGroup}>
                    <label style={styles.label}>IFSC Code</label>
                    <input
                      style={{ ...styles.input, borderColor: formErrors.ifsc_code ? "#ef4444" : undefined }}
                      type="text"
                      value={formData.ifsc_code}
                      onChange={(e) => setFormData({ ...formData, ifsc_code: e.target.value.toUpperCase() })}
                      placeholder="SBIN0001234"
                      maxLength={11}
                    />
                    {formErrors.ifsc_code && <span style={styles.errorText}>{formErrors.ifsc_code}</span>}
                  </div>
                </div>
              </div>

              {/* Payment & Financial Information */}
              <div style={styles.section}>
                <h4 style={styles.sectionTitle}>Payment & Financial Information</h4>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "1rem" }}>
                  <div style={styles.formGroup}>
                    <label style={styles.label}>Payment Terms (Days)</label>
                    <input
                      style={styles.input}
                      type="number"
                      value={formData.payment_terms}
                      onChange={(e) => setFormData({ ...formData, payment_terms: Number.parseInt(e.target.value) || 0 })}
                      min={0}
                    />
                  </div>
                  <div style={styles.formGroup}>
                    <label style={styles.label}>Opening Balance</label>
                    <input
                      style={styles.input}
                      type="number"
                      value={formData.opening_balance}
                      onChange={(e) => setFormData({ ...formData, opening_balance: Number.parseFloat(e.target.value) || 0 })}
                    />
                  </div>
                  <div style={styles.formGroup}>
                    <label style={styles.label}>Currency</label>
                    <select
                      style={styles.select}
                      value={formData.currency}
                      onChange={(e) => setFormData({ ...formData, currency: e.target.value })}
                    >
                      <option value="INR">INR - Indian Rupee</option>
                      <option value="USD">USD - US Dollar</option>
                      <option value="EUR">EUR - Euro</option>
                      <option value="GBP">GBP - British Pound</option>
                    </select>
                  </div>
                </div>
              </div>

              {/* Additional Information */}
              <div style={styles.section}>
                <h4 style={styles.sectionTitle}>Additional Information</h4>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
                  <div style={styles.formGroup}>
                    <label style={styles.label}>Status</label>
                    <select
                      style={styles.select}
                      value={formData.status}
                      onChange={(e) => setFormData({ ...formData, status: e.target.value })}
                    >
                      <option value="active">Active</option>
                      <option value="inactive">Inactive</option>
                    </select>
                  </div>
                  <div style={{ gridColumn: "1 / -1" }}>
                    <div style={styles.formGroup}>
                      <label style={styles.label}>Notes</label>
                      <textarea
                        style={{ ...styles.input, minHeight: "80px", resize: "vertical" }}
                        value={formData.notes}
                        onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
                        placeholder="Additional notes about this vendor..."
                      />
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div style={styles.modalFooter}>
              <button style={styles.btnCancel} type="button" onClick={handleCloseModal}>
                Cancel
              </button>
              <button style={styles.btnSave} onClick={handleSubmit}>
                {editingVendor ? "Update Vendor" : "Create Vendor"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Panel Vendor Link Modal */}
      {showLinkModal && selectedVendorForLink && (
        <div style={styles.modal} onClick={() => setShowLinkModal(false)}>
          <div 
            style={{ ...styles.modalContent, maxWidth: "500px", maxHeight: "400px" }} 
            onClick={(e) => e.stopPropagation()}
          >
            <div style={styles.modalHeader}>
              <h3 style={styles.modalTitle}>Link to Panel Vendor</h3>
              <button style={styles.closeBtn} onClick={() => setShowLinkModal(false)}>
                ×
              </button>
            </div>

            <div style={{ padding: "1.5rem" }}>
              <p style={{ marginBottom: "1rem", color: "#374151" }}>
                Link <strong>{selectedVendorForLink.name}</strong> to an Operations panel vendor.
                This allows tracking both billing and survey routing information.
              </p>

              <div style={styles.formGroup}>
                <label style={styles.label}>Select Panel Vendor</label>
                <select
                  style={styles.select}
                  value={selectedPanelVendor}
                  onChange={(e) => setSelectedPanelVendor(e.target.value)}
                >
                  <option value="">Select a panel vendor...</option>
                  {panelVendors.map((pv) => (
                    <option key={pv._id} value={pv._id}>
                      {pv.name || pv.vid} {pv.email ? `(${pv.email})` : ""}
                    </option>
                  ))}
                </select>
              </div>

              {panelVendors.length === 0 && (
                <p style={{ color: "#6b7280", fontSize: "0.875rem", marginTop: "0.5rem" }}>
                  No unlinked panel vendors available. All panel vendors may already be linked.
                </p>
              )}
            </div>

            <div style={styles.modalFooter}>
              <button 
                style={styles.btnCancel} 
                type="button" 
                onClick={() => setShowLinkModal(false)}
              >
                Cancel
              </button>
              <button 
                style={{ ...styles.btnSave, opacity: !selectedPanelVendor || linking ? 0.5 : 1 }}
                onClick={handleLinkVendor}
                disabled={!selectedPanelVendor || linking}
              >
                {linking ? "Linking..." : "Link Vendor"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

const styles = {
  container: {
    padding: "1.5rem",
    backgroundColor: "#f9fafb",
    minHeight: "100vh",
  },
  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "flex-start",
    marginBottom: "2rem",
  },
  title: {
    fontSize: "2rem",
    fontWeight: "700",
    margin: "0 0 0.5rem 0",
    color: "#1a1a1a",
  },
  subtitle: {
    color: "#6b7280",
    margin: "0",
    fontSize: "0.95rem",
  },
  btnPrimary: {
    padding: "0.75rem 1.5rem",
    backgroundColor: "#0d6efd",
    color: "white",
    border: "none",
    borderRadius: "0.5rem",
    fontSize: "0.95rem",
    fontWeight: "500",
    cursor: "pointer",
  },
  btnSecondary: {
    padding: "0.75rem 1.5rem",
    backgroundColor: "#6c757d",
    color: "white",
    border: "none",
    borderRadius: "0.5rem",
    fontSize: "0.95rem",
    fontWeight: "500",
    cursor: "pointer",
    display: "flex",
    alignItems: "center",
    gap: "0.5rem",
  },
  searchSection: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: "1.5rem",
    padding: "1.25rem",
    backgroundColor: "white",
    borderRadius: "0.75rem",
    boxShadow: "0 1px 3px rgba(0,0,0,0.1)",
    gap: "1rem",
    flexWrap: "wrap",
  },
  searchInput: {
    width: "100%",
    paddingLeft: "2.5rem",
    paddingRight: "1rem",
    paddingTop: "0.75rem",
    paddingBottom: "0.75rem",
    border: "1px solid #d1d5db",
    borderRadius: "0.5rem",
    fontSize: "0.95rem",
  },
  stats: {
    display: "flex",
    gap: "2rem",
    fontSize: "0.9rem",
    color: "#6b7280",
  },
  tableContainer: {
    backgroundColor: "white",
    borderRadius: "0.75rem",
    overflow: "hidden",
    boxShadow: "0 1px 3px rgba(0,0,0,0.1)",
  },
  table: {
    width: "100%",
    borderCollapse: "collapse",
  },
  thead: {
    backgroundColor: "#f9fafb",
    borderBottom: "2px solid #e5e7eb",
  },
  th: {
    padding: "1rem",
    textAlign: "left",
    fontSize: "0.75rem",
    fontWeight: "600",
    textTransform: "uppercase",
    color: "#6b7280",
    letterSpacing: "0.05em",
  },
  tr: {
    borderBottom: "1px solid #e5e7eb",
  },
  td: {
    padding: "1rem",
    fontSize: "0.9rem",
    color: "#374151",
  },
  statusBadge: {
    display: "inline-block",
    padding: "0.375rem 0.75rem",
    borderRadius: "0.375rem",
    fontSize: "0.8rem",
    fontWeight: "600",
    textTransform: "capitalize",
  },
  statusActive: {
    backgroundColor: "#d1fae5",
    color: "#065f46",
  },
  statusInactive: {
    backgroundColor: "#e5e7eb",
    color: "#6b7280",
  },
  actionButtons: {
    display: "flex",
    gap: "0.5rem",
  },
  btnEdit: {
    padding: "0.5rem 0.75rem",
    backgroundColor: "#6b7280",
    color: "white",
    border: "none",
    borderRadius: "0.375rem",
    cursor: "pointer",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
  },
  btnDelete: {
    padding: "0.5rem 0.75rem",
    backgroundColor: "#ef4444",
    color: "white",
    border: "none",
    borderRadius: "0.375rem",
    cursor: "pointer",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
  },
  emptyState: {
    textAlign: "center",
    padding: "3rem",
    color: "#9ca3af",
  },
  recordsPerPageSelect: {
    padding: "0.75rem 1rem",
    border: "1px solid #d1d5db",
    borderRadius: "0.5rem",
    fontSize: "0.95rem",
    backgroundColor: "white",
    cursor: "pointer",
  },
  paginationContainer: {
    display: "flex",
    justifyContent: "center",
    alignItems: "center",
    gap: "1rem",
    marginTop: "2rem",
    padding: "1rem",
    backgroundColor: "white",
    borderRadius: "0.75rem",
    boxShadow: "0 1px 3px rgba(0,0,0,0.1)",
  },
  paginationBtn: {
    padding: "0.5rem 1rem",
    backgroundColor: "#0d6efd",
    color: "white",
    border: "none",
    borderRadius: "0.375rem",
    fontSize: "0.9rem",
    fontWeight: "500",
    cursor: "pointer",
    transition: "all 0.2s",
  },
  paginationBtnDisabled: {
    backgroundColor: "#d1d5db",
    cursor: "not-allowed",
    opacity: "0.6",
  },
  pageInfo: {
    fontSize: "0.9rem",
    color: "#6b7280",
    minWidth: "150px",
    textAlign: "center",
  },
  modal: {
    position: "fixed",
    top: "0",
    left: "0",
    right: "0",
    bottom: "0",
    backgroundColor: "rgba(0, 0, 0, 0.5)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    zIndex: "1000",
    padding: "1rem",
  },
  modalContent: {
    backgroundColor: "white",
    borderRadius: "0.75rem",
    width: "100%",
    maxWidth: "900px",
    maxHeight: "90vh",
    overflow: "hidden",
    display: "flex",
    flexDirection: "column",
    boxShadow: "0 25px 50px -12px rgba(0, 0, 0, 0.25)",
  },
  modalHeader: {
    padding: "1.5rem",
    borderBottom: "1px solid #e5e7eb",
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
  },
  modalTitle: {
    fontSize: "1.5rem",
    fontWeight: "600",
    color: "#1a1a1a",
    margin: "0",
  },
  closeBtn: {
    background: "none",
    border: "none",
    fontSize: "2rem",
    color: "#9ca3af",
    cursor: "pointer",
    padding: "0",
    width: "2rem",
    height: "2rem",
  },
  modalBody: {
    padding: "1.5rem",
  },
  section: {
    marginBottom: "2rem",
    paddingBottom: "1.5rem",
    borderBottom: "1px solid #e5e7eb",
  },
  sectionTitle: {
    fontSize: "1.1rem",
    fontWeight: "600",
    color: "#1a1a1a",
    marginBottom: "1rem",
  },
  formGroup: {
    display: "flex",
    flexDirection: "column",
  },
  label: {
    marginBottom: "0.5rem",
    fontSize: "0.875rem",
    fontWeight: "500",
    color: "#374151",
  },
  input: {
    padding: "0.75rem",
    border: "1px solid #d1d5db",
    borderRadius: "0.5rem",
    fontSize: "0.95rem",
    backgroundColor: "white",
  },
  select: {
    padding: "0.75rem",
    border: "1px solid #d1d5db",
    borderRadius: "0.5rem",
    fontSize: "0.95rem",
    backgroundColor: "white",
    cursor: "pointer",
  },
  errorText: {
    color: "#ef4444",
    fontSize: "0.75rem",
    marginTop: "0.25rem",
  },
  modalFooter: {
    padding: "1rem 1.5rem",
    borderTop: "1px solid #e5e7eb",
    display: "flex",
    justifyContent: "flex-end",
    gap: "0.75rem",
  },
  btnCancel: {
    padding: "0.75rem 1.5rem",
    backgroundColor: "#6b7280",
    color: "white",
    border: "none",
    borderRadius: "0.5rem",
    fontSize: "0.95rem",
    fontWeight: "500",
    cursor: "pointer",
  },
  btnSave: {
    padding: "0.75rem 1.5rem",
    backgroundColor: "#0d6efd",
    color: "white",
    border: "none",
    borderRadius: "0.5rem",
    fontSize: "0.95rem",
    fontWeight: "500",
    cursor: "pointer",
  },
}

export default VendorsPage