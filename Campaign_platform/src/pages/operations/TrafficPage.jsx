import TrafficManagement from "./TrafficManagement"
import "./TrafficPage.css"

// Traffic module (owner 2026-11-18): respondent entries. The CPX callback log was
// removed from the UI (it covered CPX traffic only); its API, /api/cpx-callback-logs,
// is kept in the backend.
export default function TrafficPage() {
  return (
    <div className="traffic-page">
      <div className="traffic-page__head">
        <h1 className="cx-page-title">🚦 Traffic</h1>
      </div>
      <TrafficManagement embedded />
    </div>
  )
}
