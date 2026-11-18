import { useCallback, useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import { getOpsDashboard } from "../../services/opsProjectsService"
import "./OpsDashboard.css"

// Operations dashboard (owner 2026-11-18 revamp). Answers, in order:
//   1. how is traffic doing vs the previous period and vs normal (KPIs)
//   2. what needs attention now (alerts built server-side)
//   3. daily trend, then who/where it comes from, then live project progress.
// One series per chart, no dual axes; every chart has a table beside or below it.

const RANGES = [
  { days: 1, label: "Today" },
  { days: 7, label: "7 days" },
  { days: 30, label: "30 days" },
  { days: 90, label: "90 days" },
]
const SOURCES = [
  { value: "all", label: "All sources" },
  { value: "project", label: "Project links" },
  { value: "cpx", label: "CPX" },
  { value: "cint", label: "Cint" },
]
const STATUS_LABELS = {
  complete: "Complete",
  terminate: "Terminate",
  quality: "Quality / security term",
  quota: "Quota full",
  notRouted: "Screened out by us",
  incomplete: "Incomplete / drop-off",
}
const LEVEL = {
  critical: { icon: "⛔", label: "Critical" },
  serious: { icon: "⚠️", label: "Needs action" },
  warning: { icon: "ℹ️", label: "Check" },
}
const SERIES = { entrants: "#2a78d6", completes: "#1baf7a", conversion: "#6250d6" }

const fmtInt = (n) => (n === null || n === undefined ? "—" : Number(n).toLocaleString("en-IN"))
const fmtPct = (n) => (n === null || n === undefined ? "—" : `${n}%`)
const dayLabel = (iso) => new Date(`${iso}T00:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short" })
const istTime = (iso) =>
  new Date(`${iso}Z`).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit" })

// Change vs the previous period: % for counts, percentage points for rates.
function Delta({ cur, prev, rate = false, goodWhenUp = true, periodLabel }) {
  if (cur === null || cur === undefined || prev === null || prev === undefined) return null
  let text
  let diff
  if (rate) {
    diff = Math.round((cur - prev) * 10) / 10
    text = `${diff > 0 ? "+" : ""}${diff} pts`
  } else {
    if (!prev) return <span className="dash-delta">no traffic {periodLabel}</span>
    diff = Math.round(((cur - prev) / prev) * 100)
    text = `${diff > 0 ? "+" : ""}${diff}%`
  }
  if (diff === 0) return <span className="dash-delta">no change {periodLabel}</span>
  const good = diff > 0 === goodWhenUp
  return (
    <span className={`dash-delta ${good ? "is-good" : "is-bad"}`}>
      {diff > 0 ? "▲" : "▼"} {text} <span className="dash-delta__vs">{periodLabel}</span>
    </span>
  )
}

function Kpi({ label, value, hint, children }) {
  return (
    <div className="dash-kpi" title={hint}>
      <div className="dash-kpi__label">{label}</div>
      <div className="dash-kpi__value">{value}</div>
      <div className="dash-kpi__foot">{children}</div>
    </div>
  )
}

function ChartTip({ active, payload, label, fmt }) {
  if (!active || !payload?.length) return null
  return (
    <div className="dash-tip">
      <div className="dash-tip__label">{dayLabel(label)}</div>
      <div className="dash-tip__value">{fmt(payload[0].value)}</div>
    </div>
  )
}

// One series per chart; the title names it, so no legend.
function TrendChart({ title, data, dataKey, color, kind, fmt }) {
  const common = { data, margin: { top: 8, right: 8, bottom: 0, left: -12 } }
  const axes = (
    <>
      <CartesianGrid vertical={false} stroke="#ece9e3" />
      <XAxis dataKey="date" tickFormatter={dayLabel} tick={{ fontSize: 11, fill: "#6b7280" }} tickLine={false}
        axisLine={{ stroke: "#d9d4cb" }} minTickGap={16} />
      <YAxis tick={{ fontSize: 11, fill: "#6b7280" }} tickLine={false} axisLine={false} allowDecimals={false}
        width={48} />
      <Tooltip content={<ChartTip fmt={fmt} />} cursor={{ fill: "rgba(0,0,0,0.04)" }} />
    </>
  )
  return (
    <div className="dash-card dash-chart">
      <h3 className="dash-card__title">{title}</h3>
      <div className="dash-chart__plot">
        <ResponsiveContainer width="100%" height="100%">
          {kind === "line" ? (
            <LineChart {...common}>
              {axes}
              <Line type="monotone" dataKey={dataKey} stroke={color} strokeWidth={2} dot={{ r: 3, fill: color }}
                activeDot={{ r: 5 }} connectNulls={false} isAnimationActive={false} />
            </LineChart>
          ) : (
            <BarChart {...common} barCategoryGap="20%">
              {axes}
              <Bar dataKey={dataKey} fill={color} radius={[4, 4, 0, 0]} isAnimationActive={false} />
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
    </div>
  )
}

// Inline share bar for table rows (decorative; the number beside it is the value).
function Share({ value, max }) {
  const w = max ? Math.max(2, Math.round((100 * value) / max)) : 0
  return (
    <span className="dash-share" aria-hidden="true">
      <span style={{ width: `${w}%` }} />
    </span>
  )
}

export default function OpsDashboard() {
  const [days, setDays] = useState(7)
  const [source, setSource] = useState("all")
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    let active = true
    setLoading(true)
    setError(null)
    getOpsDashboard(days, source)
      .then((d) => active && setData(d))
      .catch((e) => active && setError(e.message || "Could not load the dashboard."))
      .finally(() => active && setLoading(false))
    return () => {
      active = false
    }
  }, [days, source, reloadKey])

  const refresh = useCallback(() => setReloadKey((k) => k + 1), [])
  const k = data?.kpis
  const cur = k?.current
  const prev = k?.previous
  const periodLabel = `vs previous ${days === 1 ? "day" : `${days} days`}`
  const statusTotal = (data?.statuses || []).reduce((s, x) => s + x.count, 0)
  const maxVendor = Math.max(0, ...(data?.vendors || []).map((v) => v.entrants))
  const maxCountry = Math.max(0, ...(data?.countries || []).map((c) => c.entrants))

  return (
    <div className="dash">
      <header className="dash-head">
        <div>
          <h1 className="dash-head__title">Operations</h1>
          <p className="dash-head__sub">
            {data ? `Updated ${istTime(data.generatedAt)} IST · days in India time` : "Loading…"}
          </p>
        </div>
        <div className="dash-controls">
          <div className="dash-seg" role="group" aria-label="Date range">
            {RANGES.map((r) => (
              <button key={r.days} type="button" aria-pressed={days === r.days}
                className={days === r.days ? "is-active" : ""} onClick={() => setDays(r.days)}>
                {r.label}
              </button>
            ))}
          </div>
          <select aria-label="Traffic source" value={source} onChange={(e) => setSource(e.target.value)}>
            {SOURCES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
          </select>
          <button type="button" className="dash-btn" onClick={refresh} disabled={loading}>
            {loading ? "Loading…" : "Refresh"}
          </button>
        </div>
      </header>

      {error && <p className="dash-error" role="alert">{error}</p>}

      {cur && (
        <section className="dash-kpis" aria-label="Key numbers">
          <Kpi label="Entrants" value={fmtInt(cur.entrants)} hint="Respondents who entered a survey link">
            <Delta cur={cur.entrants} prev={prev.entrants} periodLabel={periodLabel} />
          </Kpi>
          <Kpi label="Completes" value={fmtInt(cur.completes)} hint="Respondents the client marked complete">
            <Delta cur={cur.completes} prev={prev.completes} periodLabel={periodLabel} />
          </Kpi>
          <Kpi label="Conversion" value={fmtPct(cur.conversion)} hint="Completes ÷ entrants">
            <Delta cur={cur.conversion} prev={prev.conversion} rate periodLabel={periodLabel} />
          </Kpi>
          <Kpi label="Terminated" value={fmtPct(cur.terminationRate)}
            hint="Terminated by the client survey ÷ entrants (quality and security terms are counted separately)">
            <Delta cur={cur.terminationRate} prev={prev.terminationRate} rate goodWhenUp={false} periodLabel={periodLabel} />
          </Kpi>
          <Kpi label="Live projects" value={fmtInt(k.liveProjects)} hint="Projects with status Live">
            <Link to="/admin/operations/projects" className="dash-link">Open projects →</Link>
          </Kpi>
        </section>
      )}

      {data && (
        <section className="dash-card dash-attention" aria-label="Needs attention">
          <h2 className="dash-card__title">Needs attention</h2>
          {data.attention.length === 0 ? (
            <p className="dash-muted">Nothing flagged for this period.</p>
          ) : (
            <ul>
              {data.attention.map((a, i) => (
                <li key={i} className={`dash-alert dash-alert--${a.level}`}>
                  <span className="dash-alert__badge">
                    <span aria-hidden="true">{LEVEL[a.level]?.icon}</span> {LEVEL[a.level]?.label}
                  </span>
                  <div>
                    <div className="dash-alert__title">
                      {a.surveyId && a.projectId ? (
                        <Link to={`/admin/operations/projects/research/${a.projectId}/surveys/${a.surveyId}`}>{a.title}</Link>
                      ) : a.projectId ? (
                        <Link to={`/admin/operations/projects/research/${a.projectId}`}>{a.title}</Link>
                      ) : a.title}
                    </div>
                    <div className="dash-alert__detail">{a.detail}</div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {data && (
        <section className="dash-trends" aria-label="Daily trend">
          <TrendChart title="Entrants per day" data={data.daily} dataKey="entrants" color={SERIES.entrants} fmt={fmtInt} />
          <TrendChart title="Completes per day" data={data.daily} dataKey="completes" color={SERIES.completes} fmt={fmtInt} />
          <TrendChart title="Conversion % per day" data={data.daily} dataKey="conversion" color={SERIES.conversion}
            kind="line" fmt={fmtPct} />
        </section>
      )}

      {data && (
        <div className="dash-grid">
          <section className="dash-card" aria-label="Where respondents ended">
            <h2 className="dash-card__title">Where respondents ended</h2>
            <table className="dash-table">
              <tbody>
                {data.statuses.map((s) => (
                  <tr key={s.status}>
                    <td>{STATUS_LABELS[s.status] || s.status}</td>
                    <td className="dash-num">{fmtInt(s.count)}</td>
                    <td className="dash-num dash-muted">
                      {statusTotal ? `${Math.round((100 * s.count) / statusTotal)}%` : "—"}
                    </td>
                    <td className="dash-bar-cell"><Share value={s.count} max={statusTotal} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <section className="dash-card" aria-label="Countries">
            <h2 className="dash-card__title">Countries</h2>
            <table className="dash-table">
              <thead>
                <tr><th>Country</th><th className="dash-num">Entrants</th><th className="dash-num">Completes</th>
                  <th className="dash-num">Conv.</th><th /></tr>
              </thead>
              <tbody>
                {data.countries.length === 0 && <tr><td colSpan={5} className="dash-muted">No traffic.</td></tr>}
                {data.countries.map((c) => (
                  <tr key={c.country}>
                    <td>{c.country}</td>
                    <td className="dash-num">{fmtInt(c.entrants)}</td>
                    <td className="dash-num">{fmtInt(c.completes)}</td>
                    <td className="dash-num">{fmtPct(c.conversion)}</td>
                    <td className="dash-bar-cell"><Share value={c.entrants} max={maxCountry} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </div>
      )}

      {data && (
        <section className="dash-card" aria-label="Vendors">
          <h2 className="dash-card__title">Vendors</h2>
          <div className="dash-scroll">
            <table className="dash-table">
              <thead>
                <tr><th>Vendor</th><th className="dash-num">Entrants</th><th /><th className="dash-num">Completes</th>
                  <th className="dash-num">Conversion</th><th className="dash-num">Terminated</th>
                  <th className="dash-num">Quality term</th><th className="dash-num">Quota full</th></tr>
              </thead>
              <tbody>
                {data.vendors.length === 0 && <tr><td colSpan={8} className="dash-muted">No traffic.</td></tr>}
                {data.vendors.map((v) => (
                  <tr key={v.vendorId || v.vendorName}>
                    <td>{v.vendorName}<span className="dash-muted"> · {v.vendorId || "?"}</span></td>
                    <td className="dash-num">{fmtInt(v.entrants)}</td>
                    <td className="dash-bar-cell"><Share value={v.entrants} max={maxVendor} /></td>
                    <td className="dash-num">{fmtInt(v.completes)}</td>
                    <td className="dash-num">{fmtPct(v.conversion)}</td>
                    <td className="dash-num">{fmtPct(v.terminationRate)}</td>
                    <td className="dash-num">{fmtPct(v.qualityRate)}</td>
                    <td className="dash-num">{fmtPct(v.quotaRate)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {data && (
        <section className="dash-card" aria-label="Busiest supplier links">
          <h2 className="dash-card__title">Busiest supplier links</h2>
          <div className="dash-scroll">
            <table className="dash-table">
              <thead>
                <tr><th>Link</th><th>Survey</th><th>Vendor</th><th className="dash-num">Entrants</th>
                  <th className="dash-num">Completes</th><th className="dash-num">Conversion</th></tr>
              </thead>
              <tbody>
                {data.links.length === 0 && <tr><td colSpan={6} className="dash-muted">No project-link traffic.</td></tr>}
                {data.links.map((l) => (
                  <tr key={l.pid}>
                    <td>{l.pid}</td>
                    <td>
                      {l.surveyId && l.projectId ? (
                        <Link to={`/admin/operations/projects/research/${l.projectId}/surveys/${l.surveyId}`}>
                          {l.surveyName}
                        </Link>
                      ) : <span className="dash-muted">Not in a survey</span>}
                      {l.projectNumber && <span className="dash-muted"> · {l.projectNumber}</span>}
                    </td>
                    <td>{l.vendorName || l.vendorId || "—"}</td>
                    <td className="dash-num">{fmtInt(l.entrants)}</td>
                    <td className="dash-num">{fmtInt(l.completes)}</td>
                    <td className="dash-num">{fmtPct(l.conversion)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {data && (
        <section className="dash-card" aria-label="Live projects">
          <h2 className="dash-card__title">Live projects <span className="dash-muted">· all-time completes</span></h2>
          <div className="dash-scroll">
            <table className="dash-table">
              <thead>
                <tr><th>Project</th><th>Client</th><th className="dash-num">Surveys</th>
                  <th className="dash-num">Completes</th><th className="dash-num">Target</th><th>Progress</th>
                  <th className="dash-num">IR</th><th className="dash-num">LOI</th></tr>
              </thead>
              <tbody>
                {data.projects.length === 0 && <tr><td colSpan={8} className="dash-muted">No live projects.</td></tr>}
                {data.projects.map((p) => (
                  <tr key={p.id}>
                    <td>
                      <Link to={`/admin/operations/projects/research/${p.id}`}>{p.projectName}</Link>
                      <span className="dash-muted"> · {p.projectNumber}</span>
                    </td>
                    <td>{p.clientName || "—"}</td>
                    <td className="dash-num">{fmtInt(p.surveyCount)}</td>
                    <td className="dash-num">{fmtInt(p.completes)}</td>
                    <td className="dash-num">{p.target ? fmtInt(p.target) : <span className="dash-muted">not set</span>}</td>
                    <td className="dash-bar-cell">
                      {p.progress === null ? <span className="dash-muted">—</span> : (
                        <span className="dash-progress" title={`${p.progress}% of target`}>
                          <span style={{ width: `${Math.min(100, p.progress)}%` }} />
                          <em>{p.progress}%</em>
                        </span>
                      )}
                    </td>
                    <td className="dash-num">{fmtPct(p.ir)}</td>
                    <td className="dash-num">{p.loi === null || p.loi === undefined ? "—" : `${p.loi} min`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {loading && !data && <p className="dash-muted dash-loading">Loading dashboard…</p>}
    </div>
  )
}
