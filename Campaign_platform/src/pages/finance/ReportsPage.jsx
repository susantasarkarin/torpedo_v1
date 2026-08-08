"use client"

import { useState, useEffect } from "react"
import { API_BASE_URL } from "../../config"
import { BarChart3, Download, TrendingUp, TrendingDown, DollarSign, Clock, Calculator, Scale } from "lucide-react"
import { PageHeader } from "../../components/ui/PageHeader"
import { Card, CardContent, CardHeader } from "../../components/ui/Card"
import { Button } from "../../components/ui/Button"
import { Badge } from "../../components/ui/Badge"
import { buildApiUrl } from "../../config"
import { authFetch } from "../../utils/api"

function ReportsPage() {
  const [activeReport, setActiveReport] = useState("profit-loss")
  const [reportData, setReportData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [dateRange, setDateRange] = useState({
    start_date: new Date(new Date().getFullYear(), 0, 1).toISOString().split("T")[0],
    end_date: new Date().toISOString().split("T")[0],
  })

  const styles = {
    container: {
      minHeight: "100vh",
      backgroundColor: "#f3f4f6",
      padding: "1.5rem",
    },
    header: {
      display: "flex",
      justifyContent: "space-between",
      alignItems: "center",
      marginBottom: "2rem",
    },
    title: {
      fontSize: "2rem",
      fontWeight: "700",
      color: "#1a1a1a",
      margin: "0 0 0.5rem 0",
    },
    subtitle: {
      fontSize: "0.95rem",
      color: "#6b7280",
      margin: "0",
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
      display: "flex",
      alignItems: "center",
      gap: "0.5rem",
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
    card: {
      backgroundColor: "white",
      borderRadius: "0.75rem",
      overflow: "hidden",
      boxShadow: "0 1px 3px rgba(0,0,0,0.1)",
      marginBottom: "1.5rem",
    },
    cardHeader: {
      padding: "1.5rem",
      borderBottom: "1px solid #e5e7eb",
    },
    cardContent: {
      padding: "1.5rem",
    },
    button: {
      padding: "0.75rem 1.5rem",
      backgroundColor: "#6b7280",
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
    tabButtons: {
      display: "flex",
      gap: "0.5rem",
      padding: "1rem",
      flexWrap: "wrap",
    },
    tabButton: {
      padding: "0.65rem 1rem",
      border: "none",
      borderRadius: "0.375rem",
      fontSize: "0.9rem",
      fontWeight: "500",
      cursor: "pointer",
      display: "flex",
      alignItems: "center",
      gap: "0.5rem",
    },
  }

  useEffect(() => {
    fetchReport()
  }, [activeReport, dateRange])

  const fetchReport = async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams(dateRange)
      const response = await authFetch(buildApiUrl(`/finance/reports/${activeReport}?${params}`))
      if (response.ok) {
        const data = await response.json()
        setReportData(data)
      }
    } catch (error) {
      console.error("Error fetching report:", error)
    } finally {
      setLoading(false)
    }
  }

  const formatCurrency = (amount) => {
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency: "INR",
      maximumFractionDigits: 0,
    }).format(amount || 0)
  }

  const reportTypes = [
    { id: "profit-loss", name: "Profit & Loss", icon: BarChart3 },
    { id: "balance-sheet", name: "Balance Sheet", icon: Scale },
    { id: "cash-flow", name: "Cash Flow", icon: TrendingUp },
    { id: "gst-report", name: "GST Report", icon: Calculator },
    { id: "aging/receivables", name: "AR Aging", icon: Clock },
    { id: "aging/payables", name: "AP Aging", icon: Clock },
  ]

  const renderProfitLoss = () => {
    if (!reportData) return null

    return (
      <div className="space-y-6">
        <Card style={styles.card}>
          <CardHeader style={styles.cardHeader}>
            <h3 className="text-lg font-semibold text-slate-900 flex items-center gap-2">
              <TrendingUp className="w-5 h-5 text-green-600" />
              Revenue
            </h3>
          </CardHeader>
          <CardContent style={styles.cardContent}>
            <div className="flex justify-between py-2">
              <span className="text-slate-600">Total Sales</span>
              <span className="font-medium text-green-600">{formatCurrency(reportData.revenue?.total_sales)}</span>
            </div>
            <div className="flex justify-between py-2">
              <span className="text-slate-600">Other Income</span>
              <span className="font-medium text-green-600">{formatCurrency(reportData.revenue?.other_income)}</span>
            </div>
            <div className="flex justify-between py-3 border-t border-slate-200 font-semibold">
              <span>Total Revenue</span>
              <span className="text-green-600">{formatCurrency(reportData.revenue?.total)}</span>
            </div>
          </CardContent>
        </Card>

        <Card style={styles.card}>
          <CardHeader style={styles.cardHeader}>
            <h3 className="text-lg font-semibold text-slate-900 flex items-center gap-2">
              <TrendingDown className="w-5 h-5 text-red-600" />
              Expenses
            </h3>
          </CardHeader>
          <CardContent style={styles.cardContent}>
            <div className="flex justify-between py-2">
              <span className="text-slate-600">Cost of Goods Sold</span>
              <span className="font-medium text-red-600">{formatCurrency(reportData.expenses?.cogs)}</span>
            </div>
            <div className="flex justify-between py-2">
              <span className="text-slate-600">Operating Expenses</span>
              <span className="font-medium text-red-600">{formatCurrency(reportData.expenses?.operating)}</span>
            </div>
            <div className="flex justify-between py-3 border-t border-slate-200 font-semibold">
              <span>Total Expenses</span>
              <span className="text-red-600">{formatCurrency(reportData.expenses?.total)}</span>
            </div>
          </CardContent>
        </Card>

        <Card style={{ ...styles.card, backgroundImage: "linear-gradient(to right, #0a58ca, #f3f4f6)" }}>
          <CardContent style={styles.cardContent}>
            <div className="flex justify-between items-center">
              <div className="flex items-center gap-3">
                <div className="w-12 h-12 bg-cogentix-navy-100 rounded-lg flex items-center justify-center">
                  <DollarSign className="w-6 h-6 text-cogentix-navy-600" />
                </div>
                <span className="text-xl font-semibold text-slate-900">Net Profit/Loss</span>
              </div>
              <span
                className={`text-3xl font-bold ${(reportData.net_profit || 0) >= 0 ? "text-green-600" : "text-red-600"}`}
              >
                {formatCurrency(reportData.net_profit)}
              </span>
            </div>
          </CardContent>
        </Card>
      </div>
    )
  }

  const renderBalanceSheet = () => {
    if (!reportData) return null

    return (
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Card style={styles.card}>
          <CardHeader style={styles.cardHeader}>
            <h3 className="text-lg font-semibold text-slate-900">Assets</h3>
          </CardHeader>
          <CardContent style={styles.cardContent}>
            <div className="flex justify-between py-2">
              <span className="text-slate-600">Cash & Bank</span>
              <span className="font-medium">{formatCurrency(reportData.assets?.cash)}</span>
            </div>
            <div className="flex justify-between py-2">
              <span className="text-slate-600">Accounts Receivable</span>
              <span className="font-medium">{formatCurrency(reportData.assets?.receivables)}</span>
            </div>
            <div className="flex justify-between py-2">
              <span className="text-slate-600">Inventory</span>
              <span className="font-medium">{formatCurrency(reportData.assets?.inventory)}</span>
            </div>
            <div className="flex justify-between py-3 border-t border-slate-200 font-semibold">
              <span>Total Assets</span>
              <span>{formatCurrency(reportData.assets?.total)}</span>
            </div>
          </CardContent>
        </Card>

        <div className="space-y-6">
          <Card style={styles.card}>
            <CardHeader style={styles.cardHeader}>
              <h3 className="text-lg font-semibold text-slate-900">Liabilities</h3>
            </CardHeader>
            <CardContent style={styles.cardContent}>
              <div className="flex justify-between py-2">
                <span className="text-slate-600">Accounts Payable</span>
                <span className="font-medium">{formatCurrency(reportData.liabilities?.payables)}</span>
              </div>
              <div className="flex justify-between py-2">
                <span className="text-slate-600">Other Liabilities</span>
                <span className="font-medium">{formatCurrency(reportData.liabilities?.other)}</span>
              </div>
              <div className="flex justify-between py-3 border-t border-slate-200 font-semibold">
                <span>Total Liabilities</span>
                <span>{formatCurrency(reportData.liabilities?.total)}</span>
              </div>
            </CardContent>
          </Card>

          <Card style={styles.card}>
            <CardHeader style={styles.cardHeader}>
              <h3 className="text-lg font-semibold text-slate-900">Equity</h3>
            </CardHeader>
            <CardContent style={styles.cardContent}>
              <div className="flex justify-between py-2">
                <span className="text-slate-600">Retained Earnings</span>
                <span className="font-medium">{formatCurrency(reportData.equity?.retained_earnings)}</span>
              </div>
              <div className="flex justify-between py-3 border-t border-slate-200 font-semibold">
                <span>Total Equity</span>
                <span>{formatCurrency(reportData.equity?.total)}</span>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    )
  }

  const renderAgingReport = () => {
    if (!reportData) return null

    return (
      <div className="space-y-6">
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <Card style={styles.card}>
            <CardContent style={styles.cardContent}>
              <p className="text-sm text-slate-500 mb-1">Current</p>
              <p className="text-xl font-bold text-green-600">{formatCurrency(reportData.current)}</p>
            </CardContent>
          </Card>
          <Card style={styles.card}>
            <CardContent style={styles.cardContent}>
              <p className="text-sm text-slate-500 mb-1">1-30 Days</p>
              <p className="text-xl font-bold text-amber-600">{formatCurrency(reportData["1_30"])}</p>
            </CardContent>
          </Card>
          <Card style={styles.card}>
            <CardContent style={styles.cardContent}>
              <p className="text-sm text-slate-500 mb-1">31-60 Days</p>
              <p className="text-xl font-bold text-amber-600">{formatCurrency(reportData["31_60"])}</p>
            </CardContent>
          </Card>
          <Card style={styles.card}>
            <CardContent style={styles.cardContent}>
              <p className="text-sm text-slate-500 mb-1">61-90 Days</p>
              <p className="text-xl font-bold text-red-600">{formatCurrency(reportData["61_90"])}</p>
            </CardContent>
          </Card>
          <Card style={styles.card}>
            <CardContent style={styles.cardContent}>
              <p className="text-sm text-slate-500 mb-1">90+ Days</p>
              <p className="text-xl font-bold text-red-600">{formatCurrency(reportData["90_plus"])}</p>
            </CardContent>
          </Card>
        </div>

        <Card style={{ ...styles.card, backgroundColor: "#f3f4f6" }}>
          <CardContent style={styles.cardContent}>
            <div className="flex justify-between items-center">
              <span className="text-xl font-semibold text-slate-900">Total Outstanding</span>
              <span className="text-3xl font-bold text-cogentix-navy-900">{formatCurrency(reportData.total)}</span>
            </div>
          </CardContent>
        </Card>
      </div>
    )
  }

  const renderGSTReport = () => {
    if (!reportData) return null

    return (
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <Card style={styles.card}>
          <CardContent style={styles.cardContent}>
            <div className="w-12 h-12 bg-blue-100 rounded-lg flex items-center justify-center mx-auto mb-4">
              <TrendingUp className="w-6 h-6 text-blue-600" />
            </div>
            <h4 className="text-sm text-slate-500 mb-2">GST Collected (Output Tax)</h4>
            <p className="text-2xl font-bold text-blue-600">{formatCurrency(reportData.output_gst)}</p>
          </CardContent>
        </Card>
        <Card style={styles.card}>
          <CardContent style={styles.cardContent}>
            <div className="w-12 h-12 bg-orange-100 rounded-lg flex items-center justify-center mx-auto mb-4">
              <TrendingDown className="w-6 h-6 text-orange-600" />
            </div>
            <h4 className="text-sm text-slate-500 mb-2">GST Paid (Input Tax)</h4>
            <p className="text-2xl font-bold text-orange-600">{formatCurrency(reportData.input_gst)}</p>
          </CardContent>
        </Card>
        <Card style={{ ...styles.card, backgroundImage: "linear-gradient(to right, #0a58ca, #f3f4f6)" }}>
          <CardContent style={styles.cardContent}>
            <div className="w-12 h-12 bg-cogentix-navy-100 rounded-lg flex items-center justify-center mx-auto mb-4">
              <Calculator className="w-6 h-6 text-cogentix-navy-600" />
            </div>
            <h4 className="text-sm text-slate-500 mb-2">Net GST Liability</h4>
            <p className={`text-2xl font-bold ${(reportData.net_gst || 0) >= 0 ? "text-green-600" : "text-red-600"}`}>
              {formatCurrency(reportData.net_gst)}
            </p>
          </CardContent>
        </Card>
      </div>
    )
  }

  const renderReport = () => {
    if (loading) {
      return (
        <Card style={styles.card}>
          <CardContent
            style={{
              ...styles.cardContent,
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              height: "100%",
            }}
          >
            <div className="w-8 h-8 border-4 border-cogentix-navy-600 border-t-transparent rounded-full animate-spin mx-auto mb-4"></div>
            <p className="text-slate-600">Loading report...</p>
          </CardContent>
        </Card>
      )
    }

    if (!reportData) {
      return (
        <Card style={styles.card}>
          <CardContent
            style={{
              ...styles.cardContent,
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              height: "100%",
            }}
          >
            <BarChart3 className="w-12 h-12 mx-auto mb-4 opacity-50" />
            <p>No data available</p>
          </CardContent>
        </Card>
      )
    }

    switch (activeReport) {
      case "profit-loss":
        return renderProfitLoss()
      case "balance-sheet":
        return renderBalanceSheet()
      case "aging/receivables":
      case "aging/payables":
        return renderAgingReport()
      case "gst-report":
        return renderGSTReport()
      default:
        return (
          <Card style={styles.card}>
            <CardContent
              style={{
                ...styles.cardContent,
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                height: "100%",
              }}
            >
              <BarChart3 className="w-12 h-12 mx-auto mb-4 opacity-50" />
              <p>Report coming soon</p>
            </CardContent>
          </Card>
        )
    }
  }

  return (
    <div style={styles.container}>
      <PageHeader
        title="Financial Reports"
        description="View and analyze financial data"
        actions={
          <Button style={styles.btnPrimary}>
            <Download className="w-4 h-4 mr-2" />
            Export PDF
          </Button>
        }
      />

      {/* Report Tabs */}
      <Card style={styles.card}>
        <CardContent style={styles.cardContent}>
          <div style={styles.tabButtons}>
            {reportTypes.map((report) => {
              const Icon = report.icon
              return (
                <button
                  key={report.id}
                  style={{
                    ...styles.tabButton,
                    backgroundColor: activeReport === report.id ? "#0a58ca" : "#6b7280",
                    color: activeReport === report.id ? "white" : "#f3f4f6",
                  }}
                  onClick={() => setActiveReport(report.id)}
                >
                  <Icon className="w-4 h-4" />
                  {report.name}
                </button>
              )
            })}
          </div>
        </CardContent>
      </Card>

      {/* Date Range */}
      <Card style={styles.card}>
        <CardContent style={styles.cardContent}>
          <div className="flex flex-wrap items-center gap-4">
            <div className="flex items-center gap-2">
              <label className="text-sm text-slate-600">From:</label>
              <input
                type="date"
                value={dateRange.start_date}
                onChange={(e) => setDateRange({ ...dateRange, start_date: e.target.value })}
                className="px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-cogentix-navy-500/20"
              />
            </div>
            <div className="flex items-center gap-2">
              <label className="text-sm text-slate-600">To:</label>
              <input
                type="date"
                value={dateRange.end_date}
                onChange={(e) => setDateRange({ ...dateRange, end_date: e.target.value })}
                className="px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-cogentix-navy-500/20"
              />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Report Header */}
      <Card style={styles.card}>
        <CardContent style={styles.cardContent}>
          <div className="flex justify-between items-center">
            <h2 className="text-xl font-semibold text-slate-900">
              {reportTypes.find((r) => r.id === activeReport)?.name}
            </h2>
            <Badge variant="blue">
              {new Date(dateRange.start_date).toLocaleDateString("en-IN")} -{" "}
              {new Date(dateRange.end_date).toLocaleDateString("en-IN")}
            </Badge>
          </div>
        </CardContent>
      </Card>

      {/* Report Content */}
      {renderReport()}
    </div>
  )
}

export default ReportsPage
