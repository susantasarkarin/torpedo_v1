import { useEffect, useState } from "react"
import { RefreshCw } from "lucide-react"
import { notify } from "../../utils/notify"
import { formatDateTime } from "../../utils/format"
import { marketingApi } from "./api"

const api = marketingApi("/api/marketing/inbox")

// Marketing > Weekly report (MARKETING_PLAN 6.4). The HTML is built and escaped on the server.
export default function MarketingReport() {
  const [r, setR] = useState(null)
  const load = async (rebuild = false) => {
    try {
      setR(await api(`/weekly-report${rebuild ? "?rebuild=true" : ""}`))
    } catch (e) {
      notify(e.message, "error")
    }
  }
  useEffect(() => { load() }, [])
  if (!r) return <div className="card">Loading…</div>
  return (
    <div className="card">
      <div className="card-header flex items-center justify-between">
        <p className="card-description">Week {r.week} · built {formatDateTime(r.built_at)} · every Monday 09:00 IST</p>
        <button type="button" className="btn btn-secondary flex items-center gap-1" onClick={() => load(true)}><RefreshCw size={16} /> Rebuild</button>
      </div>
      <div className="marketing-report text-sm" dangerouslySetInnerHTML={{ __html: r.html }} />
    </div>
  )
}
