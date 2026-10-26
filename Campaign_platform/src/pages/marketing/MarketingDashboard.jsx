import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { RefreshCw } from "lucide-react"
import { buildApiUrl } from "../../config"
import { authFetch } from "../../utils/api"
import { notify } from "../../utils/notify"
import { formatDateTime } from "../../utils/format"

// Marketing dashboard (module 13): KPI tiles + sections (website, SEO, paid, social, content, attribution).
const get = async (path) => {
  const res = await authFetch(buildApiUrl(path))
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`)
  return data
}

const fmt = (v, unit) => {
  if (v == null) return "—"
  if (typeof v === "object") return Object.entries(v).map(([k, x]) => `${k} ${x}`).join(" · ")
  if (unit === "INR") return `₹${Math.round(v).toLocaleString("en-IN")}`
  if (unit === "%") return `${v}%`
  return typeof v === "number" ? v.toLocaleString("en-IN") : String(v)
}
const RAG = { red: "border-red-300 bg-red-50", amber: "border-amber-300 bg-amber-50", green: "border-green-300 bg-green-50", none: "border-gray-200" }

function Pairs({ obj }) {
  if (!obj || Object.keys(obj).length === 0) return <span className="text-gray-600">no data yet</span>
  return <span>{Object.entries(obj).map(([k, v]) => `${k.replace(/_/g, " ")}: ${fmt(v)}`).join(" · ")}</span>
}

function Section({ title, children, empty }) {
  return (
    <div className="card">
      <h3 className="card-title">{title}</h3>
      {empty ? <p className="text-sm text-gray-700">No data yet — {empty}</p> : <div className="mt-2 space-y-1 text-sm">{children}</div>}
    </div>
  )
}

export default function MarketingDashboard() {
  const [period, setPeriod] = useState("mtd")
  const [days, setDays] = useState(30)
  const [bu, setBu] = useState("ALL")
  const [model, setModel] = useState("last_non_direct")
  const [kpi, setKpi] = useState(null)
  const [sec, setSec] = useState(null)

  const load = async () => {
    try {
      const [k, s] = await Promise.all([
        get(`/api/kpi/module/marketing?period=${period}&bu=${bu}`),
        get(`/api/marketing/decisions/dashboard?days=${days}&bu=${bu}&model=${model}`),
      ])
      setKpi(k)
      setSec(s)
    } catch (e) {
      notify(e.message, "error")
    }
  }
  useEffect(() => { load() }, [period, days, bu, model])

  if (!kpi || !sec) return <div className="card">Loading…</div>
  const w = sec.website || {}, seo = sec.seo || {}, paid = sec.paid || {}, so = sec.social || {}, ct = sec.content || {}, at = sec.attribution || {}
  return (
    <div className="space-y-4">
      <div className="card">
        <div className="card-header flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="card-title">Marketing dashboard</h2>
            <p className="card-description">Marketing-sourced = last non-direct touch outside outreach email; revenue is the CRM's won / invoiced ₹.</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <select className="form-input" value={bu} onChange={(e) => setBu(e.target.value)}>{["ALL", "SFW", "COGENTIX", "BIM"].map((b) => <option key={b}>{b}</option>)}</select>
            <select className="form-input" value={period} onChange={(e) => setPeriod(e.target.value)}>{["today", "week", "mtd", "qtd", "ytd"].map((p) => <option key={p}>{p}</option>)}</select>
            <button type="button" className="btn btn-secondary flex items-center gap-1" onClick={load}><RefreshCw size={16} /> Refresh</button>
          </div>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {kpi.tiles.map((t) => (
            <div key={t.key} className={`rounded border p-3 ${RAG[t.status] || RAG.none}`} title={t.definition}>
              <p className="text-xs text-gray-700">{t.name}</p>
              <p className="text-lg font-semibold">{t.available ? fmt(t.value, t.unit) : "no source yet"}</p>
              {t.change != null && <p className="text-xs text-gray-700">{t.change > 0 ? "+" : ""}{fmt(t.change, t.unit)} vs previous</p>}
            </div>
          ))}
        </div>
        {kpi.exceptions.length > 0 && (
          <div className="mt-3">
            <h3 className="card-title">Needs attention</h3>
            <ul className="mt-1 text-sm">{kpi.exceptions.map((x, i) => <li key={i} className={x.severity === "red" ? "text-red-700" : ""}>
              <Link to={x.link} className="underline">{x.what}</Link> · waiting {x.waiting_days} d</li>)}</ul>
          </div>
        )}
      </div>

      <div className="card flex flex-wrap items-center gap-2 text-sm">
        Sections over the last
        <select className="form-input" value={days} onChange={(e) => setDays(Number(e.target.value))}>{[7, 30, 90, 180].map((d) => <option key={d} value={d}>{d} days</option>)}</select>
        · attribution model
        <select className="form-input" value={model} onChange={(e) => setModel(e.target.value)}>{(at.models || ["last_non_direct"]).map((m) => <option key={m} value={m}>{m.replace(/_/g, " ")}</option>)}</select>
      </div>

      <Section title="Website" empty={w.no_data && "the tracker is not on the sites yet (site packages)"}>
        <p><strong>Sessions</strong> {fmt(w.sessions)} · visitors {fmt(w.visitors)} (new {fmt(w.new_visitors)}, returning {fmt(w.returning_visitors)})</p>
        <p><strong>By source</strong> <Pairs obj={w.by_source} /></p>
        <p><strong>Devices</strong> <Pairs obj={w.devices} /></p>
        <p><strong>Funnel</strong> <Pairs obj={w.funnel} /> · form abandonment {fmt(w.form_abandonment_pct, "%")}</p>
        <p><strong>Top entry pages</strong> {(w.top_entry_pages || []).map(([p, n]) => `${p} (${n})`).join(" · ")}</p>
        <p><strong>Tracking health</strong> {Object.entries(w.tracking_health || {}).map(([d, h]) => `${d}: ${h.last_event ? `last event ${formatDateTime(h.last_event)}` : "no events"}`).join(" · ")}</p>
      </Section>

      <Section title="SEO">
        <p><strong>Trend</strong> {seo.trend ? seo.trend.map((t) => `${t.week}: ${t.clicks} clicks, pos ${t.position ?? "—"}`).join(" · ") : "no Search Console data yet"}</p>
        <p><strong>Open issues</strong> <Pairs obj={seo.open_issues} /> · <Link to="/admin/marketing/decisions" className="underline">fix plans in D7</Link></p>
        <p><strong>Core Web Vitals pass</strong> {fmt(seo.cwv_pass_pct, "%")} ({seo.cwv_checks || 0} checks)</p>
        <p><strong>Opportunities</strong> {(seo.opportunities || []).slice(0, 8).map((o) => `${o.query} (pos ${o.position}, ${o.impressions} impr.)`).join(" · ") || "—"}</p>
      </Section>

      <Section title="Paid" empty={paid.no_data && "no ad platform connected yet"}>
        <table className="w-full text-sm">
          <thead><tr className="text-left"><th>Campaign</th><th>Platform</th><th>Spend</th><th>Leads</th><th>RFQs</th><th>CPL</th><th>Cost/RFQ</th><th>ROAS</th></tr></thead>
          <tbody>{(paid.campaigns || []).map((c, i) => <tr key={i}><td>{c.campaign}</td><td>{c.platform}</td><td>{fmt(c.spend_inr, "INR")}</td>
            <td>{c.leads}</td><td>{c.rfqs}</td><td>{fmt(c.cpl_inr, "INR")}</td><td>{fmt(c.cost_per_rfq_inr, "INR")}</td><td>{fmt(c.roas)}</td></tr>)}</tbody>
        </table>
        <p><strong>Pacing</strong> {Object.entries(paid.pacing || {}).map(([k, p]) => `${k}: ${fmt(p.month_spend_inr, "INR")}${p.pacing_pct != null ? ` (${p.pacing_pct}% of cap)` : " (no cap set)"}`).join(" · ")}</p>
        <p><strong>Search-term waste</strong> {fmt(paid.search_term_waste_inr, "INR")} · {(paid.top_waste_terms || []).slice(0, 5).map(([t, v]) => `${t} ${fmt(v, "INR")}`).join(" · ")}</p>
        <p><strong>Creative fatigue</strong> {(paid.creative_fatigue || []).map((a) => `${a.ad} (freq ${a.frequency})`).join(" · ") || "none"}</p>
      </Section>

      <Section title="Social">
        <p><strong>Reach / engagement</strong> {so.platforms ? Object.entries(so.platforms).map(([p, v]) => `${p}: reach ${fmt(v.reach)}, engagement ${fmt(v.engagement_rate_pct, "%")}`).join(" · ") : "no page connected yet"}</p>
        <p><strong>WhatsApp</strong> <Pairs obj={so.whatsapp && { conversations: so.whatsapp.conversations, opt_ins: so.whatsapp.opt_ins, opt_outs: so.whatsapp.opt_outs }} /> · templates <Pairs obj={so.whatsapp && so.whatsapp.templates} /></p>
      </Section>

      <Section title="Content">
        <p><strong>By status</strong> <Pairs obj={ct.by_status} /> · calendar adherence {fmt(ct.adherence_pct, "%")}</p>
        <p><strong>Top pieces by leads</strong> {(ct.top_by_leads || []).map((p) => `${p.title || p.channel}: ${p.leads} leads, ${p.rfqs} RFQs`).join(" · ") || "nothing published yet"}</p>
      </Section>

      <Section title={`Attribution — ${(at.model || "").replace(/_/g, " ")}`}>
        <p><strong>RFQs by channel</strong> <Pairs obj={at.rfq_by_channel} /></p>
        <p><strong>Won by channel</strong> <Pairs obj={at.won_by_channel} /> · <strong>won ₹</strong> <Pairs obj={at.won_inr_by_channel} /></p>
        <p><strong>Assisted RFQs</strong> <Pairs obj={at.assisted_rfqs} /> · avg touches to RFQ {fmt(at.avg_touches_to_rfq)} · avg days {fmt(at.avg_days_to_rfq)}</p>
      </Section>
    </div>
  )
}
