"use client"

import { useState, useEffect, useRef } from "react"
import { useNavigate } from "react-router-dom"
import { CreditCard, Plus, Search, X, Loader2, ArrowDownCircle, ArrowUpCircle, TrendingUp, Upload, Download } from "lucide-react"
import { API_BASE_URL } from "../../config"
import { DEFAULT_CURRENCY, formatCurrency as formatCurrencyUtil } from "../../utils/currency"
import { buildApiUrl } from "../../config"
import { authFetch } from "../../utils/api"
import Pagination from "../../components/ui/Pagination"

function PaymentsPage() {
  const navigate = useNavigate()
  const [activeTab, setActiveTab] = useState("received")
  const [paymentsReceived, setPaymentsReceived] = useState([])
  const [paymentsMade, setPaymentsMade] = useState([])
  const [customers, setCustomers] = useState([])
  const [vendors, setVendors] = useState([])
  const [invoices, setInvoices] = useState([])
  const [bills, setBills] = useState([])
  const [loading, setLoading] = useState(false)
  const [searchTerm, setSearchTerm] = useState("")
  const [showModal, setShowModal] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [importing, setImporting] = useState(false)
  const [currentPage, setCurrentPage] = useState(1)
  const [recordsPerPage, setRecordsPerPage] = useState(100)
  const [totalPayments, setTotalPayments] = useState(0)
  const fileInputRef = useRef(null)
  const [formData, setFormData] = useState({
    payment_type: "received",
    customer_id: "",
    vendor_id: "",
    invoice_id: "",
    bill_id: "",
    amount: "",
    currency_code: DEFAULT_CURRENCY,
    payment_date: new Date().toISOString().split("T")[0],
    payment_method: "bank_transfer",
    reference_number: "",
    notes: "",
  })

  useEffect(() => {
    fetchPaginatedPayments(currentPage, recordsPerPage, searchTerm)
    fetchCustomers()
    fetchVendors()
    fetchInvoices()
    fetchBills()
  }, [activeTab, currentPage, recordsPerPage, searchTerm])

  const fetchPaginatedPayments = async (page = 1, page_size = 100, search = "") => {
    setLoading(true)
    try {
      const params = new URLSearchParams({
        page: page.toString(),
        page_size: page_size.toString(),
        ...(search ? { search } : {}),
      })
      const endpoint = activeTab === "received" ? "/finance/payments/received/" : "/finance/payments/made/"
      const response = await authFetch(buildApiUrl(`${endpoint}?${params}`))
      if (response.ok) {
        const data = await response.json()
        if (activeTab === "received") {
          setPaymentsReceived(data.items || [])
          setTotalPayments(data.total || 0)
        } else {
          setPaymentsMade(data.items || [])
          setTotalPayments(data.total || 0)
        }
      }
    } catch (error) {
      console.error("Error fetching payments:", error)
    } finally {
      setLoading(false)
    }
  }

  const fetchPaymentsReceived = async () => {
    try {
      const response = await authFetch(buildApiUrl(`/finance/payments/received/`))
      if (response.ok) {
        const data = await response.json()
        setPaymentsReceived(data)
      }
    } catch (error) {
      console.error("Error fetching payments received:", error)
    }
  }

  const fetchPaymentsMade = async () => {
    try {
      const response = await authFetch(buildApiUrl(`/finance/payments/made/`))
      if (response.ok) {
        const data = await response.json()
        setPaymentsMade(data)
      }
    } catch (error) {
      console.error("Error fetching payments made:", error)
    }
  }

  const fetchCustomers = async () => {
    try {
      const response = await authFetch(buildApiUrl(`/finance/customers/`))
      if (response.ok) {
        const data = await response.json()
        setCustomers(data)
      }
    } catch (error) {
      console.error("Error fetching customers:", error)
    }
  }

  const fetchVendors = async () => {
    try {
      const response = await authFetch(buildApiUrl(`/finance/vendors/`))
      if (response.ok) {
        const data = await response.json()
        setVendors(data)
      }
    } catch (error) {
      console.error("Error fetching vendors:", error)
    }
  }

  const fetchInvoices = async () => {
    try {
      const response = await authFetch(buildApiUrl(`/finance/invoices/`))
      if (response.ok) {
        const data = await response.json()
        // Only show unpaid invoices
        setInvoices(data.filter((inv) => inv.status !== "paid" && inv.balance_due > 0))
      }
    } catch (error) {
      console.error("Error fetching invoices:", error)
    }
  }

  const fetchBills = async () => {
    try {
      const response = await authFetch(buildApiUrl(`/finance/bills/`))
      if (response.ok) {
        const data = await response.json()
        // Only show unpaid bills
        setBills(data.filter((bill) => bill.status !== "paid" && bill.balance_due > 0))
      }
    } catch (error) {
      console.error("Error fetching bills:", error)
    }
  }

  const handleSubmit = async () => {
    try {
      const endpoint = formData.payment_type === "received"
        ? buildApiUrl(`/finance/payments/received/`)
        : buildApiUrl(`/finance/payments/made/`)

      const paymentData = {
        ...formData,
        amount: parseFloat(formData.amount) || 0,
      }

      const response = await authFetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(paymentData),
      })

      if (response.ok) {
        fetchAllData()
        handleCloseModal()
      } else {
        const error = await response.json()
        alert(error.detail || "Error recording payment")
      }
    } catch (error) {
      console.error("Error recording payment:", error)
      alert("Error recording payment")
    }
  }

  const handleCloseModal = () => {
    setShowModal(false)
    setFormData({
      payment_type: activeTab,
      customer_id: "",
      vendor_id: "",
      invoice_id: "",
      bill_id: "",
      amount: "",
      currency_code: DEFAULT_CURRENCY,
      payment_date: new Date().toISOString().split("T")[0],
      payment_method: "bank_transfer",
      reference_number: "",
      notes: "",
    })
  }

  const openModal = () => {
    setFormData({ ...formData, payment_type: activeTab })
    setShowModal(true)
  }

  const formatCurrency = (amount) => {
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency: "INR",
      maximumFractionDigits: 0,
    }).format(amount || 0)
  }

  const paymentMethods = [
    { value: "bank_transfer", label: "Bank Transfer" },
    { value: "cash", label: "Cash" },
    { value: "cheque", label: "Cheque" },
    { value: "upi", label: "UPI" },
    { value: "credit_card", label: "Credit Card" },
    { value: "debit_card", label: "Debit Card" },
    { value: "other", label: "Other" },
  ]

  const invoiceOptions = [
    { value: "", label: "Select Invoice (Optional)" },
    ...invoices.map((inv) => ({
      value: inv._id,
      label: `${inv.invoice_number} - ${formatCurrency(inv.balance_due)}`,
    })),
  ]

  const billOptions = [
    { value: "", label: "Select Bill (Optional)" },
    ...bills.map((bill) => ({
      value: bill._id,
      label: `${bill.bill_number} - ${formatCurrency(bill.balance_due)}`,
    })),
  ]

  const customerOptions = [
    { value: "", label: "Select Customer" },
    ...customers.map((c) => ({ value: c._id, label: c.name })),
  ]

  const vendorOptions = [
    { value: "", label: "Select Vendor" },
    ...vendors.map((v) => ({ value: v._id, label: v.name })),
  ]

  const currentPayments = activeTab === "received" ? paymentsReceived : paymentsMade
  const totalPages = Math.ceil(totalPayments / recordsPerPage)
  const handlePageChange = (page) => {
    setCurrentPage(page)
  }

  const handleRecordsPerPageChange = (value) => {
    setRecordsPerPage(parseInt(value))
    setCurrentPage(1)
  }

  // Calculate totals
  const totalReceived = paymentsReceived.reduce((sum, p) => sum + (p.amount || 0), 0)
  const totalMade = paymentsMade.reduce((sum, p) => sum + (p.amount || 0), 0)

  // Export payments to CSV
  const handleExportCSV = async () => {
    setExporting(true)
    try {
      const endpoint = activeTab === "received" ? "received" : "made"
      const response = await authFetch(buildApiUrl(`/finance/payments/${endpoint}/export/csv`))
      if (response.ok) {
        const blob = await response.blob()
        const url = window.URL.createObjectURL(blob)
        const a = document.createElement("a")
        a.href = url
        a.download = `payments_${endpoint}_export_${new Date().toISOString().split("T")[0]}.csv`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        window.URL.revokeObjectURL(url)
      }
    } catch (error) {
      console.error("Error exporting payments:", error)
      alert("Failed to export payments")
    } finally {
      setExporting(false)
    }
  }

  // Import payments from CSV
  const handleImportCSV = async (event) => {
    const file = event.target.files?.[0]
    if (!file) return

    setImporting(true)
    const formDataUpload = new FormData()
    formDataUpload.append("file", file)

    try {
      const endpoint = activeTab === "received" ? "received" : "made"
      const response = await authFetch(buildApiUrl(`/finance/payments/${endpoint}/import/csv`), {
        method: "POST",
        body: formDataUpload,
      })

      if (response.ok) {
        const result = await response.json()
        alert(`Successfully imported ${result.imported} payments`)
        fetchAllData()
      } else {
        const error = await response.json()
        alert(`Import failed: ${error.detail}`)
      }
    } catch (error) {
      console.error("Error importing payments:", error)
      alert("Failed to import payments")
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
          <h2 style={styles.title}>Payments</h2>
          <p style={styles.subtitle}>Track payments received and made</p>
        </div>
        <div style={{ display: "flex", gap: "0.75rem" }}>
          <button 
            style={styles.btnSecondary} 
            onClick={() => navigate("/admin/finance/payments/import")}
          >
            <Upload style={{ width: "16px", height: "16px" }} />
            Import CSV
          </button>
          <button 
            style={styles.btnSecondary} 
            onClick={handleExportCSV}
            disabled={exporting}
          >
            <Download style={{ width: "16px", height: "16px" }} />
            {exporting ? "Exporting..." : "Export CSV"}
          </button>
          <button style={styles.btnPrimary} onClick={openModal}>
            + Record Payment
          </button>
        </div>
      </div>

      {/* Summary Cards */}
      <div style={styles.summaryGrid}>
        <div style={styles.summaryCard}>
          <div style={styles.summaryCardContent}>
            <div>
              <p style={styles.summaryLabel}>Total Received</p>
              <p style={{ ...styles.summaryValue, color: "#16a34a" }}>{formatCurrency(totalReceived)}</p>
            </div>
            <div style={{ ...styles.summaryIcon, backgroundColor: "#d1fae5" }}>
              <ArrowDownCircle style={{ width: "24px", height: "24px", color: "#16a34a" }} />
            </div>
          </div>
        </div>
        <div style={styles.summaryCard}>
          <div style={styles.summaryCardContent}>
            <div>
              <p style={styles.summaryLabel}>Total Paid</p>
              <p style={{ ...styles.summaryValue, color: "#dc2626" }}>{formatCurrency(totalMade)}</p>
            </div>
            <div style={{ ...styles.summaryIcon, backgroundColor: "#fee2e2" }}>
              <ArrowUpCircle style={{ width: "24px", height: "24px", color: "#dc2626" }} />
            </div>
          </div>
        </div>
        <div style={styles.summaryCard}>
          <div style={styles.summaryCardContent}>
            <div>
              <p style={styles.summaryLabel}>Net Cash Flow</p>
              <p
                style={{
                  ...styles.summaryValue,
                  color: totalReceived - totalMade >= 0 ? "#16a34a" : "#dc2626",
                }}
              >
                {formatCurrency(totalReceived - totalMade)}
              </p>
            </div>
            <div style={{ ...styles.summaryIcon, backgroundColor: "#dbeafe" }}>
              <TrendingUp style={{ width: "24px", height: "24px", color: "#0d6efd" }} />
            </div>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div style={styles.tabsCard}>
        <div style={styles.tabsContainer}>
          <button
            style={{
              ...styles.tab,
              ...(activeTab === "received" ? styles.tabActive : {}),
            }}
            onClick={() => setActiveTab("received")}
          >
            <ArrowDownCircle style={{ width: "16px", height: "16px", marginRight: "0.5rem" }} />
            Payments Received ({paymentsReceived.length})
          </button>
          <button
            style={{
              ...styles.tab,
              ...(activeTab === "made" ? styles.tabActive : {}),
            }}
            onClick={() => setActiveTab("made")}
          >
            <ArrowUpCircle style={{ width: "16px", height: "16px", marginRight: "0.5rem" }} />
            Payments Made ({paymentsMade.length})
          </button>
        </div>
      </div>

      {/* Search Section */}
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
            placeholder={`Search ${activeTab === "received" ? "customers" : "vendors"}...`}
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            style={styles.searchInput}
          />
        </div>
        <div style={styles.stats}>
          <span>
            Total: <strong>{totalPayments}</strong>
          </span>
        </div>
      </div>

      {/* Payments Table */}
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
            <p style={{ color: "#6b7280" }}>Loading payments...</p>
          </div>
        </div>
      ) : (
        <div style={styles.tableContainer}>
          <table style={styles.table}>
            <thead style={styles.thead}>
              <tr>
                <th style={styles.th}>Date</th>
                <th style={styles.th}>{activeTab === "received" ? "Customer" : "Vendor"}</th>
                <th style={styles.th}>{activeTab === "received" ? "Invoice" : "Bill"}</th>
                <th style={styles.th}>Method</th>
                <th style={styles.th}>Reference</th>
                <th style={styles.th}>Amount</th>
              </tr>
            </thead>
            <tbody>
              {currentPayments.map((payment) => (
                <tr key={payment._id} style={styles.tr}>
                  <td style={styles.td}>{new Date(payment.payment_date).toLocaleDateString("en-IN")}</td>
                  <td style={{ ...styles.td, fontWeight: "500" }}>
                    {activeTab === "received" ? payment.customer_name : payment.vendor_name}
                  </td>
                  <td style={styles.td}>
                    <code style={styles.code}>
                      {activeTab === "received" ? payment.invoice_number : payment.bill_number}
                    </code>
                  </td>
                  <td style={styles.td}>
                    {paymentMethods.find((m) => m.value === payment.payment_method)?.label || payment.payment_method}
                  </td>
                  <td style={styles.td}>{payment.reference_number || "-"}</td>
                  <td style={styles.td}>
                    <span
                      style={{
                        fontWeight: "600",
                        color: activeTab === "received" ? "#16a34a" : "#dc2626",
                      }}
                    >
                      {formatCurrency(payment.amount)}
                    </span>
                  </td>
                </tr>
              ))}
              {currentPayments.length === 0 && (
                <tr>
                  <td colSpan={6} style={styles.emptyState}>
                    <CreditCard style={{ width: "48px", height: "48px", margin: "0 auto 1rem", opacity: 0.5 }} />
                    <p>No payments found. Click "Record Payment" to add one.</p>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      <Pagination
        currentPage={currentPage}
        totalPages={totalPages}
        totalRecords={totalPayments}
        pageSize={recordsPerPage}
        onPageChange={handlePageChange}
        onPageSizeChange={handleRecordsPerPageChange}
        loading={loading}
      />

      {/* Payment Modal */}
      {showModal && (
        <div style={styles.modal} onClick={handleCloseModal}>
          <div style={styles.modalContent} onClick={(e) => e.stopPropagation()}>
            <div style={styles.modalHeader}>
              <h3 style={styles.modalTitle}>
                Record {formData.payment_type === "received" ? "Payment Received" : "Payment Made"}
              </h3>
              <button style={styles.closeBtn} onClick={handleCloseModal}>
                ×
              </button>
            </div>

            <div style={{ ...styles.modalBody, overflow: "auto", flex: 1 }}>
              {/* Payment Type */}
              <div style={{ marginBottom: "1.5rem" }}>
                <label style={styles.label}>Payment Type</label>
                <div style={{ display: "flex", gap: "1rem", marginTop: "0.5rem" }}>
                  <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", cursor: "pointer" }}>
                    <input
                      type="radio"
                      name="payment_type"
                      value="received"
                      checked={formData.payment_type === "received"}
                      onChange={(e) => setFormData({ ...formData, payment_type: e.target.value })}
                      style={{ width: "16px", height: "16px", accentColor: "#0d6efd" }}
                    />
                    <span style={{ fontSize: "0.875rem", color: "#374151" }}>Payment Received</span>
                  </label>
                  <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", cursor: "pointer" }}>
                    <input
                      type="radio"
                      name="payment_type"
                      value="made"
                      checked={formData.payment_type === "made"}
                      onChange={(e) => setFormData({ ...formData, payment_type: e.target.value })}
                      style={{ width: "16px", height: "16px", accentColor: "#0d6efd" }}
                    />
                    <span style={{ fontSize: "0.875rem", color: "#374151" }}>Payment Made</span>
                  </label>
                </div>
              </div>

              {formData.payment_type === "received" ? (
                <>
                  <div style={styles.formGroup}>
                    <label style={styles.label}>Customer *</label>
                    <select
                      style={styles.select}
                      value={formData.customer_id}
                      onChange={(e) => setFormData({ ...formData, customer_id: e.target.value })}
                      required
                    >
                      {customerOptions.map((opt) => (
                        <option key={opt.value} value={opt.value}>
                          {opt.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div style={styles.formGroup}>
                    <label style={styles.label}>Invoice</label>
                    <select
                      style={styles.select}
                      value={formData.invoice_id}
                      onChange={(e) => setFormData({ ...formData, invoice_id: e.target.value })}
                    >
                      {invoiceOptions.map((opt) => (
                        <option key={opt.value} value={opt.value}>
                          {opt.label}
                        </option>
                      ))}
                    </select>
                  </div>
                </>
              ) : (
                <>
                  <div style={styles.formGroup}>
                    <label style={styles.label}>Vendor *</label>
                    <select
                      style={styles.select}
                      value={formData.vendor_id}
                      onChange={(e) => setFormData({ ...formData, vendor_id: e.target.value })}
                      required
                    >
                      {vendorOptions.map((opt) => (
                        <option key={opt.value} value={opt.value}>
                          {opt.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div style={styles.formGroup}>
                    <label style={styles.label}>Bill</label>
                    <select
                      style={styles.select}
                      value={formData.bill_id}
                      onChange={(e) => setFormData({ ...formData, bill_id: e.target.value })}
                    >
                      {billOptions.map((opt) => (
                        <option key={opt.value} value={opt.value}>
                          {opt.label}
                        </option>
                      ))}
                    </select>
                  </div>
                </>
              )}

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem", marginBottom: "1rem" }}>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Amount *</label>
                  <input
                    style={styles.input}
                    type="number"
                    value={formData.amount}
                    onChange={(e) => setFormData({ ...formData, amount: parseFloat(e.target.value) })}
                    required
                    min={0}
                    step={0.01}
                    placeholder="0.00"
                  />
                </div>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Payment Date</label>
                  <input
                    style={styles.input}
                    type="date"
                    value={formData.payment_date}
                    onChange={(e) => setFormData({ ...formData, payment_date: e.target.value })}
                  />
                </div>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem", marginBottom: "1rem" }}>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Payment Method</label>
                  <select
                    style={styles.select}
                    value={formData.payment_method}
                    onChange={(e) => setFormData({ ...formData, payment_method: e.target.value })}
                  >
                    {paymentMethods.map((method) => (
                      <option key={method.value} value={method.value}>
                        {method.label}
                      </option>
                    ))}
                  </select>
                </div>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Reference Number</label>
                  <input
                    style={styles.input}
                    type="text"
                    value={formData.reference_number}
                    onChange={(e) => setFormData({ ...formData, reference_number: e.target.value })}
                    placeholder="Transaction ID, Cheque No."
                  />
                </div>
              </div>

              <div style={styles.formGroup}>
                <label style={styles.label}>Notes</label>
                <textarea
                  value={formData.notes}
                  onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
                  placeholder="Additional notes..."
                  rows={3}
                  style={{ ...styles.input, minHeight: "80px", resize: "vertical" }}
                />
              </div>
            </div>

            <div style={styles.modalFooter}>
              <button style={styles.btnCancel} type="button" onClick={handleCloseModal}>
                Cancel
              </button>
              <button style={styles.btnSave} onClick={handleSubmit}>
                Record Payment
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
  summaryGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(250px, 1fr))",
    gap: "1rem",
    marginBottom: "1.5rem",
  },
  summaryCard: {
    backgroundColor: "white",
    borderRadius: "0.75rem",
    padding: "1.25rem",
    boxShadow: "0 1px 3px rgba(0,0,0,0.1)",
  },
  summaryCardContent: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
  },
  summaryLabel: {
    fontSize: "0.875rem",
    color: "#6b7280",
    margin: "0 0 0.5rem 0",
  },
  summaryValue: {
    fontSize: "1.5rem",
    fontWeight: "700",
    margin: "0",
  },
  summaryIcon: {
    width: "48px",
    height: "48px",
    borderRadius: "0.5rem",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
  },
  tabsCard: {
    backgroundColor: "white",
    borderRadius: "0.75rem",
    overflow: "hidden",
    boxShadow: "0 1px 3px rgba(0,0,0,0.1)",
    marginBottom: "1.5rem",
  },
  tabsContainer: {
    display: "flex",
    borderBottom: "2px solid #e5e7eb",
  },
  tab: {
    flex: 1,
    padding: "1rem",
    textAlign: "center",
    fontSize: "0.95rem",
    fontWeight: "500",
    color: "#6b7280",
    backgroundColor: "white",
    border: "none",
    cursor: "pointer",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    borderBottom: "2px solid transparent",
    marginBottom: "-2px",
  },
  tabActive: {
    color: "#1a1a1a",
    backgroundColor: "#f9fafb",
    borderBottom: "2px solid #0d6efd",
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
  code: {
    fontSize: "0.85rem",
    backgroundColor: "#f3f4f6",
    padding: "0.375rem 0.75rem",
    borderRadius: "0.375rem",
    fontFamily: "monospace",
  },
  emptyState: {
    textAlign: "center",
    padding: "3rem",
    color: "#9ca3af",
  },
  modal: {
    position: "fixed",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: "rgba(0, 0, 0, 0.5)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    zIndex: 1000,
    padding: "1rem",
  },
  modalContent: {
    backgroundColor: "white",
    borderRadius: "0.75rem",
    width: "100%",
    maxWidth: "700px",
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
    margin: 0,
  },
  closeBtn: {
    background: "none",
    border: "none",
    fontSize: "2rem",
    color: "#9ca3af",
    cursor: "pointer",
    padding: 0,
    width: "2rem",
    height: "2rem",
  },
  modalBody: {
    padding: "1.5rem",
  },
  formGroup: {
    display: "flex",
    flexDirection: "column",
    marginBottom: "1rem",
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
    cursor: "pointer",
    backgroundColor: "white",
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

export default PaymentsPage