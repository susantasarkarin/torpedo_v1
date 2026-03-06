"use client"

import { useEffect, useMemo, useState } from "react"
import { Link } from "react-router-dom"
import api from "../../utils/api"
import {
  ArrowLeft,
  Play,
  RefreshCcw,
  UserPlus,
  Trash2,
  Power,
  PowerOff,
  Linkedin
} from "lucide-react"
import "./Marketing.css"

function LinkedInAutomationPage() {
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [actionBusy, setActionBusy] = useState("")
  const [error, setError] = useState("")
  const [dashboard, setDashboard] = useState(null)
  const [accounts, setAccounts] = useState([])
  const [formData, setFormData] = useState({
    account_name: "",
    email: "",
    password: "",
    frequency: "daily",
    run_time: "02:00"
  })

  const activeCount = useMemo(
    () => accounts.filter((item) => item.active).length,
    [accounts]
  )

  const loadData = async (initial = false) => {
    if (initial) {
      setLoading(true)
    }
    setError("")
    try {
      const [dashboardData, accountsData] = await Promise.all([
        api.get("/api/marketing/linkedin/dashboard"),
        api.get("/api/marketing/linkedin/accounts", { active_only: false })
      ])
      setDashboard(dashboardData || null)
      setAccounts(Array.isArray(accountsData) ? accountsData : [])
    } catch (err) {
      console.error("Failed to load LinkedIn automation data:", err)
      setError(err?.message || "Failed to load LinkedIn automation data")
    } finally {
      if (initial) {
        setLoading(false)
      }
    }
  }

  useEffect(() => {
    loadData(true)
  }, [])

  const handleCreateAccount = async (e) => {
    e.preventDefault()
    if (!formData.account_name || !formData.email || !formData.password) {
      setError("Account name, email, and password are required")
      return
    }

    setSubmitting(true)
    setError("")
    try {
      await api.post("/api/marketing/linkedin/accounts", {
        account_name: formData.account_name,
        email: formData.email,
        password: formData.password,
        active: true,
        schedule: {
          frequency: formData.frequency,
          run_time: formData.run_time,
          days_of_week: null,
          enabled: true
        }
      })
      setFormData({
        account_name: "",
        email: "",
        password: "",
        frequency: "daily",
        run_time: "02:00"
      })
      await loadData()
    } catch (err) {
      console.error("Failed to create LinkedIn account:", err)
      setError(err?.message || "Failed to create LinkedIn account")
    } finally {
      setSubmitting(false)
    }
  }

  const runNow = async (accountId) => {
    setActionBusy(`run-${accountId}`)
    setError("")
    try {
      await api.post(`/api/marketing/linkedin/accounts/${accountId}/run`, {})
      await loadData()
    } catch (err) {
      console.error("Failed to trigger automation:", err)
      setError(err?.message || "Failed to trigger automation")
    } finally {
      setActionBusy("")
    }
  }

  const toggleActive = async (account) => {
    setActionBusy(`toggle-${account._id || account.id}`)
    setError("")
    try {
      await api.put(`/api/marketing/linkedin/accounts/${account._id || account.id}`, {
        active: !account.active
      })
      await loadData()
    } catch (err) {
      console.error("Failed to update account status:", err)
      setError(err?.message || "Failed to update account status")
    } finally {
      setActionBusy("")
    }
  }

  const deleteAccount = async (account) => {
    const accountId = account._id || account.id
    const confirmed = window.confirm(
      `Delete LinkedIn account "${account.account_name}"?`
    )
    if (!confirmed) {
      return
    }

    setActionBusy(`delete-${accountId}`)
    setError("")
    try {
      await api.delete(`/api/marketing/linkedin/accounts/${accountId}`)
      await loadData()
    } catch (err) {
      console.error("Failed to delete account:", err)
      setError(err?.message || "Failed to delete account")
    } finally {
      setActionBusy("")
    }
  }

  if (loading) {
    return (
      <div className="marketing-dashboard">
        <div className="card">
          <p className="card-description">Loading LinkedIn Automation...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="marketing-dashboard">
      <div className="marketing-header" style={{ marginBottom: "1rem" }}>
        <div className="flex items-center gap-3">
          <Link to="/admin/marketing" className="p-2 hover:bg-gray-100 rounded-lg">
            <ArrowLeft size={18} />
          </Link>
          <h1 className="flex items-center gap-2">
            <Linkedin size={22} />
            LinkedIn Automation
          </h1>
        </div>
        <button
          className="btn btn-secondary flex items-center gap-2"
          onClick={() => loadData()}
          disabled={actionBusy !== "" || submitting}
        >
          <RefreshCcw size={16} />
          Refresh
        </button>
      </div>

      {error && (
        <div className="card" style={{ border: "1px solid #ef4444", marginBottom: "1rem" }}>
          <p style={{ color: "#b91c1c" }}>{error}</p>
        </div>
      )}

      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-card-label">Total Accounts</div>
          <div className="stat-card-value">{dashboard?.accounts?.total ?? accounts.length}</div>
        </div>
        <div className="stat-card">
          <div className="stat-card-label">Active Accounts</div>
          <div className="stat-card-value">{dashboard?.accounts?.active ?? activeCount}</div>
        </div>
        <div className="stat-card">
          <div className="stat-card-label">Inactive Accounts</div>
          <div className="stat-card-value">
            {dashboard?.accounts?.inactive ?? Math.max(accounts.length - activeCount, 0)}
          </div>
        </div>
      </div>

      <div className="card" style={{ marginBottom: "1rem" }}>
        <div className="card-header">
          <h3 className="card-title">Add LinkedIn Account</h3>
          <p className="card-description">Credentials are encrypted by backend service</p>
        </div>
        <form onSubmit={handleCreateAccount}>
          <div className="grid grid-cols-2 gap-4 mb-4">
            <input
              className="input"
              placeholder="Account Name"
              value={formData.account_name}
              onChange={(e) => setFormData({ ...formData, account_name: e.target.value })}
            />
            <input
              className="input"
              type="email"
              placeholder="LinkedIn Email"
              value={formData.email}
              onChange={(e) => setFormData({ ...formData, email: e.target.value })}
            />
            <input
              className="input"
              type="password"
              placeholder="LinkedIn Password"
              value={formData.password}
              onChange={(e) => setFormData({ ...formData, password: e.target.value })}
            />
            <select
              className="input"
              value={formData.frequency}
              onChange={(e) => setFormData({ ...formData, frequency: e.target.value })}
            >
              <option value="daily">Daily</option>
              <option value="hourly">Hourly</option>
              <option value="weekly">Weekly</option>
              <option value="custom">Custom</option>
            </select>
            <input
              className="input"
              type="time"
              value={formData.run_time}
              onChange={(e) => setFormData({ ...formData, run_time: e.target.value })}
            />
          </div>
          <button
            type="submit"
            className="btn btn-primary flex items-center gap-2"
            disabled={submitting}
          >
            <UserPlus size={16} />
            {submitting ? "Adding..." : "Add Account"}
          </button>
        </form>
      </div>

      <div className="card">
        <div className="card-header">
          <h3 className="card-title">Configured Accounts</h3>
          <p className="card-description">Run now, disable/enable, or remove accounts</p>
        </div>

        {accounts.length === 0 ? (
          <p className="card-description">No LinkedIn accounts configured yet.</p>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table className="table" style={{ width: "100%" }}>
              <thead>
                <tr>
                  <th>Account</th>
                  <th>Email</th>
                  <th>Status</th>
                  <th>Schedule</th>
                  <th style={{ textAlign: "right" }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {accounts.map((account) => {
                  const accountId = account._id || account.id
                  return (
                    <tr key={accountId}>
                      <td>{account.account_name}</td>
                      <td>{account.email}</td>
                      <td>{account.active ? "Active" : "Inactive"}</td>
                      <td>
                        {account?.schedule?.frequency || "daily"} @{" "}
                        {account?.schedule?.run_time || "00:00"}
                      </td>
                      <td style={{ textAlign: "right" }}>
                        <div className="flex items-center justify-end gap-2">
                          <button
                            className="btn btn-secondary"
                            onClick={() => runNow(accountId)}
                            disabled={actionBusy !== ""}
                          >
                            <Play size={14} />
                          </button>
                          <button
                            className="btn btn-secondary"
                            onClick={() => toggleActive(account)}
                            disabled={actionBusy !== ""}
                          >
                            {account.active ? <PowerOff size={14} /> : <Power size={14} />}
                          </button>
                          <button
                            className="btn btn-secondary"
                            onClick={() => deleteAccount(account)}
                            disabled={actionBusy !== ""}
                          >
                            <Trash2 size={14} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

export default LinkedInAutomationPage
