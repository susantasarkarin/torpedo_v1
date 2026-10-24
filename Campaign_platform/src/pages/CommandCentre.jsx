import { useEffect, useState } from "react"
import { Link, useParams } from "react-router-dom"
import { buildApiUrl } from "../config"
import { authFetch } from "../utils/api"

// CRM plan 3.14: the Command Centre (business pulse, ranked "needs attention",
// module health, BU comparison) and, at /admin/dashboards/:module, each
// module's KPI tiles with its exceptions. Values come from /api/kpi; a KPI
// with no data source yet says so instead of showing a number.

const PERIODS = [["today", "Today"], ["week", "This week"], ["mtd", "MTD"], ["qtd", "QTD"], ["ytd", "YTD"]]
const BUS = ["ALL", "SFW", "COGENTIX", "BIM"]
const MODULE_LABEL = {
  outreach: "Lead gen & outreach", deliverability: "Deliverability", web: "Website & retargeting",
  replies: "Replies", rfq: "RFQ & pricing", ops: "Operations", service_delivery: "Service Delivery",
  vendors: "Vendors", panel: "Panel", finance: "Finance", accounts: "Accounts", system: "System health",
}
const RAG = {
  red: "border-red-300 bg-red-50", amber: "border-amber-300 bg-amber-50",
  green: "border-emerald-300 bg-emerald-50", none: "border-gray-200 bg-white",
}
const DOT = { red: "bg-red-500", amber: "bg-amber-500", green: "bg-emerald-500", none: "bg-gray-300" }

function fmt(v, unit) {
  if (v === null || v === undefined) return "—"
  if (typeof v === "object") {
    if (v.error) return "error"
    return Object.entries(v).map(([k, x]) => `${k}: ${fmt(x, unit === "INR" ? "INR" : "")}`).join(" · ")
  }
  if (unit === "INR") return "₹" + Math.round(v).toLocaleString("en-IN")
  if (unit === "%") return `${v}%`
  return `${typeof v === "number" ? v.toLocaleString("en-IN") : v}${unit && !["count", "INR", "%"].includes(unit) ? " " + unit : ""}`
}

function Tile({ t }) {
  return (
    <div className={`rounded-xl border p-4 ${RAG[t.status] || RAG.none}`} title={t.definition}>
      <div className="text-xs font-medium uppercase tracking-wide text-gray-500">{t.name}</div>
      {t.available ? (
        <>
          <div className="mt-1 text-xl font-bold text-gray-900 break-words">{fmt(t.value, t.unit)}</div>
          <div className="mt-1 text-xs text-gray-500">
            {t.target !== null && t.target !== undefined ? `Target ${fmt(t.target, t.unit)} · ` : "No target set · "}
            {typeof t.change === "number" ? `${t.change >= 0 ? "+" : ""}${fmt(t.change, t.unit)} vs previous` : "no comparison"}
          </div>
        </>
      ) : (
        <div className="mt-2 text-sm text-gray-500">No data source yet</div>
      )}
    </div>
  )
}

function Filters({ period, setPeriod, bu, setBu }) {
  return (
    <div className="flex flex-wrap gap-2">
      <select aria-label="Business unit" value={bu} onChange={(e) => setBu(e.target.value)}
        className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm">
        {BUS.map((b) => <option key={b} value={b}>{b === "ALL" ? "All BUs" : b}</option>)}
      </select>
      <div className="flex flex-wrap gap-1" role="group" aria-label="Period">
        {PERIODS.map(([k, l]) => (
          <button key={k} onClick={() => setPeriod(k)}
            className={`rounded-lg px-3 py-1.5 text-sm ${period === k ? "bg-gray-900 font-medium text-white" : "border border-gray-300 bg-white text-gray-700 hover:bg-gray-50"}`}>
            {l}
          </button>
        ))}
      </div>
    </div>
  )
}

function Attention({ items, total }) {
  if (!items.length) return <div className="rounded-xl border border-gray-200 bg-white p-6 text-center text-gray-500">Nothing needs attention.</div>
  return (
    <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
      <ul className="divide-y divide-gray-100">
        {items.map((i, n) => (
          <li key={n} className="flex flex-wrap items-center gap-3 p-3">
            <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${DOT[i.severity]}`} aria-label={i.severity} />
            <div className="min-w-0 flex-1">
              <div className="text-sm font-medium text-gray-900 break-words">{i.what}</div>
              <div className="text-xs text-gray-500">
                {MODULE_LABEL[i.module] || i.module} · waiting {i.waiting_days} d
                {i.at_stake_inr ? ` · ${fmt(i.at_stake_inr, "INR")} at stake` : ""}{i.owner ? ` · ${i.owner}` : ""}
              </div>
            </div>
            {i.link && <Link to={i.link} className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50">Open</Link>}
          </li>
        ))}
      </ul>
      {total > items.length && <div className="border-t border-gray-100 p-3 text-sm text-gray-500">{total - items.length} more not shown</div>}
    </div>
  )
}

export default function CommandCentre() {
  const { module } = useParams()
  const [period, setPeriod] = useState("mtd")
  const [bu, setBu] = useState("ALL")
  const [data, setData] = useState(null)
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let live = true
    setLoading(true)
    setError("")
    const path = module ? `/api/kpi/module/${module}` : "/api/kpi/command-centre"
    authFetch(buildApiUrl(`${path}?period=${period}&bu=${bu}`))
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then((d) => live && setData(d))
      .catch((e) => live && setError(`Could not load the dashboard (${e.message}).`))
      .finally(() => live && setLoading(false))
    return () => { live = false }
  }, [module, period, bu])

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-4 sm:p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold text-gray-900">{module ? MODULE_LABEL[module] || module : "Command Centre"}</h1>
          {module && <Link to="/admin/command-centre" className="text-sm text-gray-500 hover:text-gray-800">← Command Centre</Link>}
        </div>
        <Filters period={period} setPeriod={setPeriod} bu={bu} setBu={setBu} />
      </div>
      {error && <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div>}
      {loading && !data && <div className="text-sm text-gray-500">Loading…</div>}
      {data && !module && (
        <>
          <section aria-labelledby="pulse">
            <h2 id="pulse" className="mb-2 text-sm font-semibold text-gray-700">Business pulse</h2>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">{data.pulse.map((t) => <Tile key={t.key} t={t} />)}</div>
          </section>
          <section aria-labelledby="attention">
            <h2 id="attention" className="mb-2 text-sm font-semibold text-gray-700">Needs attention today</h2>
            <Attention items={data.needs_attention.items} total={data.needs_attention.total} />
          </section>
          <section aria-labelledby="health">
            <h2 id="health" className="mb-2 text-sm font-semibold text-gray-700">Module health</h2>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-6">
              {data.module_health.map((m) => (
                <Link key={m.module} to={`/admin/dashboards/${m.module}`}
                  className={`flex items-center gap-2 rounded-xl border p-3 text-sm text-gray-800 hover:shadow-sm ${RAG[m.status]}`}>
                  <span className={`h-2.5 w-2.5 rounded-full ${DOT[m.status]}`} />{MODULE_LABEL[m.module] || m.module}
                </Link>
              ))}
            </div>
          </section>
          <section aria-labelledby="bus">
            <h2 id="bus" className="mb-2 text-sm font-semibold text-gray-700">BU comparison ({PERIODS.find((p) => p[0] === period)[1]})</h2>
            <div className="overflow-x-auto rounded-xl border border-gray-200 bg-white">
              <table className="min-w-full text-sm">
                <thead className="bg-gray-50 text-left text-xs uppercase text-gray-500">
                  <tr><th className="p-3">BU</th><th className="p-3">Revenue</th><th className="p-3">Pipeline</th><th className="p-3">Win rate</th><th className="p-3">Overdue</th><th className="p-3">Live projects</th></tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {data.bu_comparison.map((r) => (
                    <tr key={r.bu}>
                      <td className="p-3 font-medium">{r.bu}</td><td className="p-3">{fmt(r.revenue_invoiced, "INR")}</td>
                      <td className="p-3">{fmt(r.open_pipeline, "INR")}</td><td className="p-3">{fmt(r.win_rate_90d, "%")}</td>
                      <td className="p-3">{fmt(r.overdue_receivables, "INR")}</td><td className="p-3">{fmt(r.projects_live)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-2 text-xs text-gray-500">Pipeline and win rate are all-BU until RFQs carry a BU.</p>
          </section>
        </>
      )}
      {data && module && (
        <>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">{data.tiles.map((t) => <Tile key={t.key} t={t} />)}</div>
          <section aria-labelledby="exceptions">
            <h2 id="exceptions" className="mb-2 text-sm font-semibold text-gray-700">Exceptions</h2>
            <Attention items={data.exceptions} total={data.exceptions.length} />
          </section>
        </>
      )}
    </div>
  )
}
