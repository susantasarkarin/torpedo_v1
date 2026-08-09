"use client"

import { useState, useEffect, useCallback } from "react"
import { Link } from "react-router-dom"
import { buildApiUrl } from "../../config"
import "./Accounts.css"
import "../../styles/SalesPages.css"

const getAuthToken = () => localStorage.getItem("session_id") || sessionStorage.getItem("token")

const STATE_LABELS = {
  open: "Open",
  won: "Won",
  lost: "Lost",
  closed: "Closed",
}

const formatMoney = (value, currency = "INR") => {
  const amount = Number(value || 0)
  try {
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency,
      maximumFractionDigits: 0,
    }).format(amount)
  } catch {
    return `${currency} ${amount.toLocaleString()}`
  }
}

const formatDate = (value) => {
  if (!value) return "—"
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleDateString()
}

function Accounts() {
  const [accounts, setAccounts] = useState([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState("")
  const [statusFilter, setStatusFilter] = useState("")
  const [error, setError] = useState("")

  const [selectedId, setSelectedId] = useState(null)
  const [overview, setOverview] = useState(null)
  const [overviewLoading, setOverviewLoading] = useState(false)
  const [tab, setTab] = useState("contacts")

  const loadAccounts = useCallback(async () => {
    setLoading(true)
    setError("")
    try {
      const token = getAuthToken()
      const params = new URLSearchParams({ limit: "200" })
      if (search) params.append("search", search)
      if (statusFilter) params.append("status", statusFilter)

      const response = await fetch(buildApiUrl(`/sales/accounts?${params.toString()}`), {
        headers: { Authorization: token },
      })
      if (!response.ok) throw new Error(`Failed to load accounts (${response.status})`)

      const data = await response.json()
      setAccounts(Array.isArray(data) ? data : [])
    } catch (e) {
      console.error("Error loading accounts:", e)
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [search, statusFilter])

  useEffect(() => {
    const debounce = setTimeout(loadAccounts, 300)
    return () => clearTimeout(debounce)
  }, [loadAccounts])

  const loadOverview = async (accountId) => {
    setOverviewLoading(true)
    setOverview(null)
    try {
      const token = getAuthToken()
      const response = await fetch(
        buildApiUrl(`/sales/accounts/${accountId}/overview`),
        { headers: { Authorization: token } }
      )
      if (!response.ok) throw new Error(`Failed to load account (${response.status})`)
      setOverview(await response.json())
    } catch (e) {
      console.error("Error loading account overview:", e)
      setOverview({ error: e.message })
    } finally {
      setOverviewLoading(false)
    }
  }

  const selectAccount = (account) => {
    setSelectedId(account._id)
    setTab("contacts")
    loadOverview(account._id)
  }

  // ---- list ------------------------------------------------------------
  if (!selectedId) {
    return (
      <div className="sales-page accounts-page">
        <div className="sales-page-header">
          <div>
            <h1>Accounts</h1>
            <p className="sales-page-subtitle">
              Companies across sales, finance and operations
            </p>
          </div>
          <div className="accounts-filters">
            <input
              type="text"
              className="accounts-search"
              placeholder="Search name, company or email…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
              <option value="">All statuses</option>
              <option value="active">Active</option>
              <option value="prospect">Prospect</option>
              <option value="inactive">Inactive</option>
            </select>
          </div>
        </div>

        {error && <div className="accounts-error">{error}</div>}

        {loading ? (
          <div className="accounts-empty">Loading accounts…</div>
        ) : accounts.length === 0 ? (
          <div className="accounts-empty">
            <p>No accounts yet.</p>
            <p className="accounts-empty-hint">
              Accounts are created automatically from mailbox traffic by the mail-pool
              AI pipeline, then adopted into Sales by the nightly CRM reconcile.
            </p>
          </div>
        ) : (
          <div className="accounts-table-wrap">
            <table className="accounts-table">
              <thead>
                <tr>
                  <th>Account</th>
                  <th>Industry</th>
                  <th>Country</th>
                  <th>Status</th>
                  <th>Links</th>
                  <th>Source</th>
                </tr>
              </thead>
              <tbody>
                {accounts.map((account) => (
                  <tr
                    key={account._id}
                    className="accounts-row"
                    onClick={() => selectAccount(account)}
                  >
                    <td>
                      <span className="accounts-name">
                        {account.account_name || account.company_name || "Unnamed"}
                      </span>
                      {account.website && (
                        <span className="accounts-website">{account.website}</span>
                      )}
                    </td>
                    <td>{account.industry || "—"}</td>
                    <td>{account.country || "—"}</td>
                    <td>
                      <span className={`accounts-badge status-${account.status || "active"}`}>
                        {account.status || "active"}
                      </span>
                    </td>
                    <td>
                      <div className="accounts-links">
                        {account.linked_finance_customer_id && (
                          <span className="accounts-chip chip-finance">Finance</span>
                        )}
                        {account.linked_operations_client_id && (
                          <span className="accounts-chip chip-ops">Ops</span>
                        )}
                        {account.crm_account_id && (
                          <span className="accounts-chip chip-spine">CRM</span>
                        )}
                      </div>
                    </td>
                    <td className="accounts-source">{account.source || "manual"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    )
  }

  // ---- detail ----------------------------------------------------------
  const account = overview?.account || {}
  const rfqs = overview?.rfqs || {}
  const finance = overview?.finance || {}
  const operations = overview?.operations || {}
  const contacts = overview?.contacts || []

  return (
    <div className="sales-page accounts-page">
      <button className="accounts-back" onClick={() => { setSelectedId(null); setOverview(null) }}>
        ← All accounts
      </button>

      {overviewLoading ? (
        <div className="accounts-empty">Loading account…</div>
      ) : overview?.error ? (
        <div className="accounts-error">{overview.error}</div>
      ) : (
        <>
          <div className="sales-page-header">
            <div>
              <h1>{account.account_name || account.company_name || "Account"}</h1>
              <p className="sales-page-subtitle">
                {[account.industry, account.country, account.website]
                  .filter(Boolean)
                  .join(" · ") || "No company details recorded"}
              </p>
            </div>
          </div>

          <div className="accounts-summary">
            <div className="accounts-stat">
              <span className="accounts-stat-label">Contacts</span>
              <span className="accounts-stat-value">{contacts.length}</span>
            </div>
            <div className="accounts-stat">
              <span className="accounts-stat-label">RFQs</span>
              <span className="accounts-stat-value">{rfqs.total || 0}</span>
            </div>
            <div className="accounts-stat">
              <span className="accounts-stat-label">Open pipeline</span>
              <span className="accounts-stat-value">
                {formatMoney(rfqs.stats?.open_value)}
              </span>
            </div>
            <div className="accounts-stat">
              <span className="accounts-stat-label">Lifetime billed</span>
              <span className="accounts-stat-value">
                {formatMoney(finance.totals?.lifetime_billed)}
              </span>
            </div>
            <div className="accounts-stat">
              <span className="accounts-stat-label">Outstanding</span>
              <span className="accounts-stat-value accounts-stat-warn">
                {formatMoney(finance.totals?.outstanding)}
              </span>
            </div>
            <div className="accounts-stat">
              <span className="accounts-stat-label">Projects</span>
              <span className="accounts-stat-value">
                {operations.totals?.project_count || 0}
              </span>
            </div>
          </div>

          <div className="accounts-tabs">
            {["contacts", "rfqs", "finance", "operations"].map((key) => (
              <button
                key={key}
                className={`accounts-tab ${tab === key ? "active" : ""}`}
                onClick={() => setTab(key)}
              >
                {key === "rfqs" ? "RFQs" : key.charAt(0).toUpperCase() + key.slice(1)}
              </button>
            ))}
          </div>

          <div className="accounts-panel">
            {tab === "contacts" && (
              contacts.length === 0 ? (
                <p className="accounts-empty-hint">No contacts found for this account.</p>
              ) : (
                <table className="accounts-table">
                  <thead>
                    <tr>
                      <th>Name</th><th>Email</th><th>Designation</th>
                      <th>Country</th><th>Last seen</th><th>Source</th>
                    </tr>
                  </thead>
                  <tbody>
                    {contacts.map((c) => (
                      <tr key={c._id}>
                        <td>{c.name || "—"}</td>
                        <td>{c.email || "—"}</td>
                        <td>{c.designation || "—"}</td>
                        <td>{c.country || "—"}</td>
                        <td>{formatDate(c.last_seen_date)}</td>
                        <td className="accounts-source">{c.source}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )
            )}

            {tab === "rfqs" && (
              rfqs.reason || rfqs.error ? (
                <p className="accounts-empty-hint">{rfqs.reason || rfqs.error}</p>
              ) : (rfqs.items || []).length === 0 ? (
                <p className="accounts-empty-hint">No RFQs recorded for this account.</p>
              ) : (
                <table className="accounts-table">
                  <thead>
                    <tr>
                      <th>RFQ</th><th>Title</th><th>State</th>
                      <th>Stage</th><th>Value</th><th>Received</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(rfqs.items || []).map((r) => (
                      <tr key={r._id}>
                        <td>
                          <Link to={`/admin/sales/rfq?rfq=${r.rfq_id}`}>{r.rfq_id}</Link>
                        </td>
                        <td>{r.title || "—"}</td>
                        <td>
                          <span className={`accounts-badge state-${r.state}`}>
                            {STATE_LABELS[r.state] || r.state}
                          </span>
                        </td>
                        <td>{r.stage || "—"}</td>
                        <td>{formatMoney(r.final_value, r.final_currency)}</td>
                        <td>{formatDate(r.received_date)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )
            )}

            {tab === "finance" && (
              !finance.linked ? (
                <p className="accounts-empty-hint">{finance.reason || finance.error}</p>
              ) : (
                <>
                  <h3 className="accounts-subhead">
                    Invoices ({finance.totals?.invoice_count || 0})
                  </h3>
                  <table className="accounts-table">
                    <thead>
                      <tr>
                        <th>Invoice</th><th>Status</th><th>Total</th>
                        <th>Balance due</th><th>Date</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(finance.invoices || []).map((inv) => (
                        <tr key={inv._id}>
                          <td>{inv.invoice_number || inv._id}</td>
                          <td>
                            <span className={`accounts-badge status-${inv.status}`}>
                              {inv.status || "—"}
                            </span>
                          </td>
                          <td>{formatMoney(inv.total_amount ?? inv.total, inv.currency_code)}</td>
                          <td>{formatMoney(inv.balance_due, inv.currency_code)}</td>
                          <td>{formatDate(inv.created_at || inv.invoice_date)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>

                  <h3 className="accounts-subhead">
                    Estimates ({finance.totals?.estimate_count || 0})
                  </h3>
                  <table className="accounts-table">
                    <thead>
                      <tr><th>Estimate</th><th>Status</th><th>Total</th><th>Date</th></tr>
                    </thead>
                    <tbody>
                      {(finance.estimates || []).map((est) => (
                        <tr key={est._id}>
                          <td>{est.estimate_number || est._id}</td>
                          <td>
                            <span className={`accounts-badge status-${est.status}`}>
                              {est.status || "—"}
                            </span>
                          </td>
                          <td>{formatMoney(est.total_amount ?? est.total, est.currency_code)}</td>
                          <td>{formatDate(est.created_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </>
              )
            )}

            {tab === "operations" && (
              !operations.linked ? (
                <p className="accounts-empty-hint">{operations.reason || operations.error}</p>
              ) : (
                <table className="accounts-table">
                  <thead>
                    <tr><th>Project</th><th>Status</th><th>Client</th><th>Created</th></tr>
                  </thead>
                  <tbody>
                    {(operations.projects || []).map((p) => (
                      <tr key={p._id}>
                        <td>{p.name || p.project_name || p._id}</td>
                        <td>
                          <span className={`accounts-badge status-${p.status}`}>
                            {p.status || "—"}
                          </span>
                        </td>
                        <td>{p.client || "—"}</td>
                        <td>{formatDate(p.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )
            )}
          </div>
        </>
      )}
    </div>
  )
}

export default Accounts
