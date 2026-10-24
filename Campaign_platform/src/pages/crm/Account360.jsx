import { useEffect, useState } from "react"
import { Link, useParams } from "react-router-dom"
import api from "../../utils/api"
import { formatDate, formatDateTime } from "../../utils/format"

// CRM plan 3.8: everything about one account on one page — communication
// (threaded, filterable by type), RFQs, projects, quotations, invoices and
// payments with the outstanding balance per currency, DND status and BU.

const money = (v, cur) =>
  v == null ? "—" : `${cur || ""} ${Number(v).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`.trim()

function Section({ title, count, children }) {
  return (
    <section className="rounded-xl border border-gray-200 bg-white p-4">
      <h2 className="mb-3 text-sm font-semibold text-gray-900">
        {title} {count != null && <span className="font-normal text-gray-400">({count})</span>}
      </h2>
      {children}
    </section>
  )
}

function Empty({ text = "None" }) {
  return <p className="text-sm text-gray-400">{text}</p>
}

export default function Account360() {
  const { accountId } = useParams()
  const [data, setData] = useState(null)
  const [category, setCategory] = useState("")
  const [error, setError] = useState("")
  const [open, setOpen] = useState({})

  useEffect(() => {
    let alive = true
    setError("")
    api.get(`/api/crm/360/account/${accountId}`, category ? { category } : {}, { cacheTTL: 0 })
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(e?.message || "Could not load the account"))
    return () => { alive = false }
  }, [accountId, category])

  if (error) return <div className="p-6 text-sm text-red-600">{error}</div>
  if (!data) return <div className="p-6 text-sm text-gray-500">Loading…</div>

  const a = data.account || {}
  const comm = data.communication || { threads: [], categories: {} }
  const out = Object.entries(data.outstanding_by_currency || {})

  return (
    <div className="space-y-4 p-4 sm:p-6">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <Link to="/admin/crm/accounts" className="text-xs text-gray-500 hover:text-gray-800">← Accounts</Link>
          <h1 className="text-xl font-bold text-gray-900 sm:text-2xl">{a.name || "Account"}</h1>
          <p className="text-sm text-gray-500">{(data.matched_on?.domains || []).join(", ") || a.domain || "no domain on record"}</p>
        </div>
        <div className="flex flex-wrap gap-2 text-xs">
          <span className="rounded-full bg-blue-50 px-3 py-1 font-medium text-blue-700">
            BU: {data.bu?.bu || "not decided"}
          </span>
          {data.dnd?.account && <span className="rounded-full bg-red-50 px-3 py-1 font-medium text-red-700">Account DND</span>}
          {data.dnd?.contacts_dnd > 0 && (
            <span className="rounded-full bg-amber-50 px-3 py-1 font-medium text-amber-700">{data.dnd.contacts_dnd} contact(s) DND</span>
          )}
          {a.credit_hold && <span className="rounded-full bg-red-50 px-3 py-1 font-medium text-red-700">Credit hold</span>}
          <span className="rounded-full bg-gray-100 px-3 py-1 text-gray-700">
            Outstanding: {out.length ? out.map(([c, v]) => money(v, c)).join(" · ") : "nil"}
          </span>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Section title="Communication" count={comm.messages}>
            <div className="mb-3 flex flex-wrap gap-2">
              <button onClick={() => setCategory("")}
                className={`rounded-full border px-3 py-1 text-xs ${!category ? "border-gray-900 bg-gray-900 text-white" : "border-gray-200 bg-white text-gray-700"}`}>All</button>
              {Object.entries(comm.categories || {}).map(([c, n]) => (
                <button key={c} onClick={() => setCategory(c === "uncategorised" ? "" : c)}
                  className={`rounded-full border px-3 py-1 text-xs ${category === c ? "border-gray-900 bg-gray-900 text-white" : "border-gray-200 bg-white text-gray-700"}`}>
                  {c} ({n})
                </button>
              ))}
            </div>
            {comm.threads.length === 0 ? <Empty text="No mail found for this account's contacts or domain." /> : (
              <ul className="divide-y divide-gray-100">
                {comm.threads.map((t) => (
                  <li key={t.thread_id} className="py-2">
                    <button onClick={() => setOpen((o) => ({ ...o, [t.thread_id]: !o[t.thread_id] }))} className="w-full text-left">
                      <div className="flex items-center justify-between gap-3">
                        <span className="truncate text-sm font-medium text-gray-900">{t.subject || "(no subject)"}</span>
                        <span className="shrink-0 text-xs text-gray-400">{t.messages.length} · {formatDate(t.last_at)}</span>
                      </div>
                      <div className="text-xs text-gray-400">{t.categories.join(", ")}</div>
                    </button>
                    {open[t.thread_id] && (
                      <ul className="mt-2 space-y-1 border-l-2 border-gray-100 pl-3">
                        {t.messages.map((m) => (
                          <li key={m._id} className="text-xs">
                            <span className={m.direction === "outbound" ? "text-blue-700" : "text-gray-700"}>
                              {m.direction === "outbound" ? "→ sent" : "← received"}
                            </span>{" "}
                            <span className="text-gray-400">{formatDateTime(m.timestamp)}</span>{" "}
                            <span className="text-gray-600">{m.snippet}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </li>
                ))}
              </ul>
            )}
            {comm.truncated && <p className="mt-2 text-xs text-gray-400">Showing the latest 300 messages.</p>}
          </Section>

          <Section title="RFQs" count={(data.rfqs || []).length}>
            {(data.rfqs || []).length === 0 ? <Empty /> : (
              <table className="w-full text-sm">
                <tbody>
                  {data.rfqs.map((r) => (
                    <tr key={r._id} className="border-t border-gray-100">
                      <td className="py-1.5 pr-2 text-gray-900">{r.title}</td>
                      <td className="py-1.5 pr-2 text-gray-500">{r.stage}</td>
                      <td className="py-1.5 pr-2 text-gray-500">{r.cpi != null ? money(r.cpi, r.currency) : ""}</td>
                      <td className="py-1.5 text-right text-gray-400">{formatDate(r.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Section>

          <Section title="Invoices & payments" count={(data.invoices || []).length}>
            {(data.invoices || []).length === 0 ? <Empty /> : (
              <table className="w-full text-sm">
                <tbody>
                  {data.invoices.map((i) => (
                    <tr key={i._id} className="border-t border-gray-100">
                      <td className="py-1.5 pr-2 text-gray-900">{i.invoice_number}</td>
                      <td className="py-1.5 pr-2 text-gray-500">{i.status}</td>
                      <td className="py-1.5 pr-2 text-gray-500">{money(i.total, i.currency_code)}</td>
                      <td className="py-1.5 pr-2 text-gray-500">due {money(i.balance_due, i.currency_code)}</td>
                      <td className="py-1.5 text-right text-gray-400">{formatDate(i.invoice_date)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <p className="mt-2 text-xs text-gray-400">{(data.payments || []).length} payment(s) recorded</p>
          </Section>
        </div>

        <div className="space-y-4">
          <Section title="Contacts" count={(data.contacts || []).length}>
            {(data.contacts || []).length === 0 ? <Empty /> : (
              <ul className="space-y-2">
                {data.contacts.map((c) => (
                  <li key={c._id} className="text-sm">
                    <div className="text-gray-900">{c.name || c.email}</div>
                    <div className="text-xs text-gray-500">{c.title || ""} {c.dnd && <span className="text-red-600">· DND ({c.dnd_reason})</span>}</div>
                  </li>
                ))}
              </ul>
            )}
          </Section>
          <Section title="Projects" count={(data.projects || []).length}>
            {(data.projects || []).length === 0 ? <Empty /> : (
              <ul className="space-y-1 text-sm">
                {data.projects.map((p) => (
                  <li key={p._id} className="flex justify-between gap-2">
                    <Link to={`/admin/operations/projects/${p._id}`} className="truncate text-gray-900 hover:underline">{p.projectName || p.name}</Link>
                    <span className="text-xs text-gray-500">{p.status}</span>
                  </li>
                ))}
              </ul>
            )}
          </Section>
          <Section title="Quotations & contracts" count={(data.quotations || []).length + (data.contracts || []).length}>
            {(data.quotations || []).length + (data.contracts || []).length === 0 ? <Empty /> : (
              <ul className="space-y-1 text-sm">
                {(data.contracts || []).map((c) => (
                  <li key={c._id} className="flex justify-between"><span>{c.contract_number}</span><span className="text-xs text-gray-500">{c.status}</span></li>
                ))}
                {(data.quotations || []).map((e) => (
                  <li key={e._id} className="flex justify-between"><span>{e.estimate_number}</span><span className="text-xs text-gray-500">{e.status}</span></li>
                ))}
              </ul>
            )}
          </Section>
        </div>
      </div>
    </div>
  )
}
