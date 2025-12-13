"use client"

import { useState, useEffect, useRef } from "react"
import { API_BASE_URL } from "../../config"
import { Users, Search, Pencil, Trash2, FileText, Loader2, Upload, Download } from "lucide-react"

// GST Treatment options
const GST_TREATMENT_OPTIONS = [
  { value: "registered_regular", label: "Registered Business - Regular" },
  { value: "registered_composition", label: "Registered Business - Composition" },
  { value: "unregistered", label: "Unregistered Business" },
  { value: "consumer", label: "Consumer" },
  { value: "overseas", label: "Overseas" },
]

// Customer type options
const CUSTOMER_TYPE_OPTIONS = [
  { value: "business", label: "Business" },
  { value: "individual", label: "Individual" },
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

function CustomersPage() {
  const [customers, setCustomers] = useState([])
  const [loading, setLoading] = useState(true)
  const [searchTerm, setSearchTerm] = useState("")
  const [showModal, setShowModal] = useState(false)
  const [editingCustomer, setEditingCustomer] = useState(null)
  const [formErrors, setFormErrors] = useState({})
  const [exporting, setExporting] = useState(false)
  const [importing, setImporting] = useState(false)
  const fileInputRef = useRef(null)
  
  const initialFormData = {
    name: "",
    customer_type: "business",
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
    shipping_address: {
      line1: "",
      line2: "",
      city: "",
      state: "",
      pincode: "",
      country: "India",
    },
    same_as_billing: true,
    payment_terms: 30,
    credit_limit: 0,
    currency: "INR",
    opening_balance: 0,
    notes: "",
    status: "active",
  }
  
  const [formData, setFormData] = useState(initialFormData)

  useEffect(() => {
    fetchCustomers()
  }, [])

  const fetchCustomers = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/finance/finance/customers/`)
      if (response.ok) {
        const data = await response.json()
        setCustomers(data)
      }
    } catch (error) {
      console.error("Error fetching customers:", error)
    } finally {
      setLoading(false)
    }
  }

  // Validation helpers
  const validateEmail = (email) => {
    if (!email) return true // Email is optional
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
    return emailRegex.test(email)
  }

  const validatePhone = (phone) => {
    if (!phone) return true // Phone is optional
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

  const isGSTINRequired = () => {
    return formData.gst_treatment === "registered_regular" || formData.gst_treatment === "registered_composition"
  }

  const validateForm = () => {
    const errors = {}
    
    if (!formData.name.trim()) {
      errors.name = "Customer name is required"
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
    
    setFormErrors(errors)
    return Object.keys(errors).length === 0
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    
    if (!validateForm()) {
      return
    }
    
    try {
      // Prepare data with shipping address logic
      const submitData = {
        ...formData,
        shipping_address: formData.same_as_billing ? formData.billing_address : formData.shipping_address,
      }
      
      const url = editingCustomer
        ? `${API_BASE_URL}/finance/finance/customers/${editingCustomer._id}`
        : `${API_BASE_URL}/finance/finance/customers/`

      const method = editingCustomer ? "PUT" : "POST"

      const response = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(submitData),
      })

      if (response.ok) {
        fetchCustomers()
        handleCloseModal()
      }
    } catch (error) {
      console.error("Error saving customer:", error)
    }
  }

  const handleDelete = async (id) => {
    if (!window.confirm("Are you sure you want to delete this customer?")) return

    try {
      const response = await fetch(`${API_BASE_URL}/finance/finance/customers/${id}`, {
        method: "DELETE",
      })
      if (response.ok) {
        fetchCustomers()
      }
    } catch (error) {
      console.error("Error deleting customer:", error)
    }
  }

  const handleEdit = (customer) => {
    setEditingCustomer(customer)
    setFormData({
      name: customer.name || "",
      customer_type: customer.customer_type || "business",
      company_name: customer.company_name || "",
      email: customer.email || "",
      phone: customer.phone || "",
      gst_treatment: customer.gst_treatment || "unregistered",
      gstin: customer.gstin || "",
      pan: customer.pan || "",
      billing_address: customer.billing_address || {
        line1: "",
        line2: "",
        city: "",
        state: "",
        pincode: "",
        country: "India",
      },
      shipping_address: customer.shipping_address || {
        line1: "",
        line2: "",
        city: "",
        state: "",
        pincode: "",
        country: "India",
      },
      same_as_billing: customer.same_as_billing !== false,
      payment_terms: customer.payment_terms || 30,
      credit_limit: customer.credit_limit || 0,
      currency: customer.currency || "INR",
      opening_balance: customer.opening_balance || 0,
      notes: customer.notes || "",
      status: customer.status || "active",
    })
    setFormErrors({})
    setShowModal(true)
  }

  const handleCloseModal = () => {
    setShowModal(false)
    setEditingCustomer(null)
    setFormData(initialFormData)
    setFormErrors({})
  }

  const filteredCustomers = customers.filter(
    (c) =>
      c.name?.toLowerCase().includes(searchTerm.toLowerCase()) ||
      c.email?.toLowerCase().includes(searchTerm.toLowerCase()) ||
      c.gstin?.toLowerCase().includes(searchTerm.toLowerCase()),
  )

  const formatCurrency = (amount) => {
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency: "INR",
      maximumFractionDigits: 0,
    }).format(amount || 0)
  }

  // Export customers to CSV
  const handleExportCSV = async () => {
    setExporting(true)
    try {
      const response = await fetch(`${API_BASE_URL}/finance/finance/customers/export/csv`)
      if (response.ok) {
        const blob = await response.blob()
        const url = window.URL.createObjectURL(blob)
        const a = document.createElement("a")
        a.href = url
        a.download = `customers_export_${new Date().toISOString().split("T")[0]}.csv`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        window.URL.revokeObjectURL(url)
      }
    } catch (error) {
      console.error("Error exporting customers:", error)
      alert("Failed to export customers")
    } finally {
      setExporting(false)
    }
  }

  // Import customers from CSV
  const handleImportCSV = async (event) => {
    const file = event.target.files?.[0]
    if (!file) return

    setImporting(true)
    const formDataUpload = new FormData()
    formDataUpload.append("file", file)

    try {
      const response = await fetch(`${API_BASE_URL}/finance/finance/customers/import/csv`, {
        method: "POST",
        body: formDataUpload,
      })

      if (response.ok) {
        const result = await response.json()
        alert(`Successfully imported ${result.imported} customers`)
        fetchCustomers()
      } else {
        const error = await response.json()
        alert(`Import failed: ${error.detail}`)
      }
    } catch (error) {
      console.error("Error importing customers:", error)
      alert("Failed to import customers")
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
          <h2 style={styles.title}>Customers</h2>
          <p style={styles.subtitle}>Manage your customer accounts</p>
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
            + Add Customer
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
            placeholder="Search customers..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            style={styles.searchInput}
          />
        </div>
        <div style={styles.stats}>
          <span>
            Total: <strong>{filteredCustomers.length}</strong>
          </span>
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
            <p style={{ color: "#6b7280" }}>Loading customers...</p>
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
                <th style={styles.th}>Outstanding</th>
                <th style={styles.th}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredCustomers.map((customer) => (
                <tr key={customer._id} style={styles.tr}>
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
                        {customer.name?.charAt(0).toUpperCase()}
                      </div>
                      <span style={{ fontWeight: "500" }}>{customer.name}</span>
                    </div>
                  </td>
                  <td style={styles.td}>{customer.email || "-"}</td>
                  <td style={styles.td}>{customer.phone || "-"}</td>
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
                      {customer.gstin || "-"}
                    </code>
                  </td>
                  <td style={{ ...styles.td, fontWeight: "600" }}>{formatCurrency(customer.outstanding_amount)}</td>
                  <td style={styles.td}>
                    <div style={styles.actionButtons}>
                      <button style={styles.btnEdit} onClick={() => handleEdit(customer)}>
                        <Pencil style={{ width: "16px", height: "16px" }} />
                      </button>
                      <button style={styles.btnEdit}>
                        <FileText style={{ width: "16px", height: "16px" }} />
                      </button>
                      <button style={styles.btnDelete} onClick={() => handleDelete(customer._id)}>
                        <Trash2 style={{ width: "16px", height: "16px" }} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {filteredCustomers.length === 0 && (
                <tr>
                  <td colSpan={6} style={styles.emptyState}>
                    <Users style={{ width: "48px", height: "48px", margin: "0 auto 1rem", opacity: 0.5 }} />
                    <p>No customers found. Click "Add Customer" to create one.</p>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {showModal && (
        <div style={styles.modal} onClick={handleCloseModal}>
          <div style={styles.modalContent} onClick={(e) => e.stopPropagation()}>
            <div style={styles.modalHeader}>
              <h3 style={styles.modalTitle}>{editingCustomer ? "Edit Customer" : "Add Customer"}</h3>
              <button style={styles.closeBtn} onClick={handleCloseModal}>
                ×
              </button>
            </div>

            <div style={{ ...styles.modalBody, overflow: "auto", flex: 1, maxHeight: "70vh" }}>
              {/* Basic Information */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "1rem", marginBottom: "1.5rem" }}>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Customer Name *</label>
                  <input
                    style={{ ...styles.input, borderColor: formErrors.name ? "#ef4444" : undefined }}
                    type="text"
                    value={formData.name}
                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                    required
                    placeholder="Enter customer name"
                  />
                  {formErrors.name && <span style={styles.errorText}>{formErrors.name}</span>}
                </div>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Customer Type</label>
                  <select
                    style={styles.select}
                    value={formData.customer_type}
                    onChange={(e) => setFormData({ ...formData, customer_type: e.target.value })}
                  >
                    {CUSTOMER_TYPE_OPTIONS.map((opt) => (
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
                    placeholder="customer@example.com"
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

              {/* Shipping Address */}
              <div style={styles.section}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
                  <h4 style={{ ...styles.sectionTitle, marginBottom: 0 }}>Shipping Address</h4>
                  <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", cursor: "pointer" }}>
                    <input
                      type="checkbox"
                      checked={formData.same_as_billing}
                      onChange={(e) => setFormData({ ...formData, same_as_billing: e.target.checked })}
                    />
                    Same as billing address
                  </label>
                </div>
                {!formData.same_as_billing && (
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
                    <div style={{ gridColumn: "1 / -1" }}>
                      <div style={styles.formGroup}>
                        <label style={styles.label}>Address Line 1</label>
                        <input
                          style={styles.input}
                          type="text"
                          value={formData.shipping_address.line1}
                          onChange={(e) =>
                            setFormData({
                              ...formData,
                              shipping_address: { ...formData.shipping_address, line1: e.target.value },
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
                          value={formData.shipping_address.line2}
                          onChange={(e) =>
                            setFormData({
                              ...formData,
                              shipping_address: { ...formData.shipping_address, line2: e.target.value },
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
                        value={formData.shipping_address.city}
                        onChange={(e) =>
                          setFormData({
                            ...formData,
                            shipping_address: { ...formData.shipping_address, city: e.target.value },
                          })
                        }
                      />
                    </div>
                    <div style={styles.formGroup}>
                      <label style={styles.label}>State</label>
                      <select
                        style={styles.select}
                        value={formData.shipping_address.state}
                        onChange={(e) =>
                          setFormData({
                            ...formData,
                            shipping_address: { ...formData.shipping_address, state: e.target.value },
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
                        value={formData.shipping_address.pincode}
                        onChange={(e) =>
                          setFormData({
                            ...formData,
                            shipping_address: { ...formData.shipping_address, pincode: e.target.value },
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
                        value={formData.shipping_address.country}
                        onChange={(e) =>
                          setFormData({
                            ...formData,
                            shipping_address: { ...formData.shipping_address, country: e.target.value },
                          })
                        }
                      />
                    </div>
                  </div>
                )}
              </div>

              {/* Payment & Financial Information */}
              <div style={styles.section}>
                <h4 style={styles.sectionTitle}>Payment & Financial Information</h4>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: "1rem" }}>
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
                    <label style={styles.label}>Credit Limit</label>
                    <input
                      style={styles.input}
                      type="number"
                      value={formData.credit_limit}
                      onChange={(e) => setFormData({ ...formData, credit_limit: Number.parseFloat(e.target.value) || 0 })}
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
                        placeholder="Additional notes about this customer..."
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
                {editingCustomer ? "Update Customer" : "Create Customer"}
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

export default CustomersPage