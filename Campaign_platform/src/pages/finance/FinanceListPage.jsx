/**
 * Every Finance tab (owner 2026-10-26): the Sales list look (LeadTable), server
 * paging / search / sort, no row actions — a row opens the record in a new tab,
 * where it is edited.
 */
import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { buildApiUrl } from "../../config"
import { authFetch } from "../../utils/api"
import LeadTable from "../../components/leads/LeadTable"
import Pagination from "../../components/ui/Pagination"
import { FINANCE_KINDS, apiKind } from "../../components/finance/financeKinds"
import "../../styles/SalesPages.css"

export default function FinanceListPage({ kind, importPath }) {
  const cfg = FINANCE_KINDS[kind]
  const navigate = useNavigate()
  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [pages, setPages] = useState(1)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(25)
  const [search, setSearch] = useState("")
  const [statusFilter, setStatusFilter] = useState("")
  const [sort, setSort] = useState({ by: null, order: null })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")

  useEffect(() => {
    let live = true
    const t = setTimeout(async () => {
      setLoading(true)
      setError("")
      const qs = new URLSearchParams({ page, page_size: pageSize })
      if (search.trim()) qs.set("search", search.trim())
      if (statusFilter) qs.set("status", statusFilter)
      if (sort.by) { qs.set("sort", sort.by); qs.set("order", sort.order) }
      try {
        const r = await authFetch(buildApiUrl(`/finance/records/${apiKind(kind)}?${qs}`))
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        const d = await r.json()
        if (!live) return
        setRows(d.records || [])
        setTotal(d.total || 0)
        setPages(d.pages || 1)
      } catch (e) {
        if (live) setError(`Could not load ${cfg.title.toLowerCase()} (${e.message}).`)
      } finally {
        if (live) setLoading(false)
      }
    }, search ? 300 : 0)
    return () => { live = false; clearTimeout(t) }
  }, [kind, page, pageSize, search, statusFilter, sort])

  const open = (id) => window.open(`/admin/finance/record/${kind}/${id}`, "_blank", "noopener")

  return (
    <div className="sales-page">
      <div className="page-header">
        <div className="header-left">
          <h1 className="cx-page-title">{cfg.title}</h1>
          <p className="subtitle">{total.toLocaleString("en-IN")} {cfg.title.toLowerCase()} · {cfg.subtitle}</p>
        </div>
        <div className="header-actions">
          {importPath && <button className="btn btn-secondary" onClick={() => navigate(importPath)}>Import</button>}
          <button className="btn btn-primary" onClick={() => open("new")}>+ New {cfg.singular.toLowerCase()}</button>
        </div>
      </div>

      {error && <div className="error-alert">{error}</div>}

      <LeadTable
        leads={rows}
        columns={cfg.columns}
        catalog={{}}
        storageKey={`finance_${kind}_cols`}
        onRowClick={(r) => open(r._id)}
        sort={sort}
        onSort={(by, order) => { setSort({ by, order }); setPage(1) }}
        toolbar={
          <>
            <input type="text" placeholder={`Search ${cfg.title.toLowerCase()}…`} value={search} style={{ minWidth: 260 }}
                   onChange={(e) => { setSearch(e.target.value); setPage(1) }} aria-label={`Search ${cfg.title}`} />
            {cfg.statuses && (
              <select value={statusFilter} onChange={(e) => { setStatusFilter(e.target.value); setPage(1) }} aria-label="Status">
                <option value="">All statuses</option>
                {cfg.statuses.map((s) => <option key={s} value={s}>{s.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase())}</option>)}
              </select>
            )}
            {loading && <span style={{ color: "#6f6f6f", fontSize: "0.85rem" }}>Loading…</span>}
          </>
        }
        empty={
          <div style={{ textAlign: "center", padding: 64, color: "#5c5c5c" }}>
            <h3>{loading ? `Loading ${cfg.title.toLowerCase()}…` : `No ${cfg.title.toLowerCase()} found`}</h3>
          </div>
        }
      />

      <Pagination currentPage={page} totalPages={pages} totalRecords={total} pageSize={pageSize}
                  onPageChange={setPage} onPageSizeChange={(v) => { setPageSize(parseInt(v, 10)); setPage(1) }} loading={loading} />
    </div>
  )
}
