import { useSearchParams } from "react-router-dom"
import TrafficManagement from "./TrafficManagement"
import CPXCallbackLogs from "./CPXCallbackLogs"
import "./TrafficPage.css"

// One Traffic module (owner 2026-11-18): the old Inbound Traffic (entries) and
// Outbound Traffic (callbacks) pages as two tabs. The tab lives in ?tab= so links
// and the old /admin/operations/reports address can open the Callbacks tab.
const TABS = [
  { key: "entries", label: "Entries", hint: "Respondents coming in from vendors" },
  { key: "callbacks", label: "Callbacks", hint: "Results sent back to vendors" },
]

export default function TrafficPage() {
  const [params, setParams] = useSearchParams()
  const tab = params.get("tab") === "callbacks" ? "callbacks" : "entries"

  return (
    <div className="traffic-page">
      <div className="traffic-page__head">
        <h1 className="cx-page-title">🚦 Traffic</h1>
        <div className="traffic-page__tabs" role="tablist" aria-label="Traffic views">
          {TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={tab === t.key}
              className={`traffic-page__tab ${tab === t.key ? "is-active" : ""}`}
              title={t.hint}
              onClick={() => setParams(t.key === "entries" ? {} : { tab: t.key }, { replace: true })}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>
      <div role="tabpanel">
        {tab === "entries" ? <TrafficManagement embedded /> : <CPXCallbackLogs embedded />}
      </div>
    </div>
  )
}
