/**
 * Survey Revenue — surveys ranked by expected revenue per entrant.
 * Plain CSS (crm-ui.css). Consumes /api/ai/decisions?agent_name=survey_revenue_agent.
 */
import { useEffect, useState } from "react";
import { TrendingUp, RefreshCw, Clock } from "lucide-react";
import api from "../../utils/api";
import "../../styles/crm-ui.css";

const fmtMoney = (n) => (typeof n === "number" && !Number.isNaN(n) ? `$${n.toFixed(2)}` : "—");

const BASIS_LABEL = {
  conversion_rate: "actual conversion",
  expected_ir: "provider IR",
  default: "default est.",
};

export default function SurveyRevenue() {
  const [ranked, setRanked] = useState([]);
  const [recommendedAt, setRecommendedAt] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = async () => {
    setLoading(true); setError(null);
    try {
      const decisions = await api.get("/api/ai/decisions", { agent_name: "survey_revenue_agent", limit: 50 });
      const latest = Array.isArray(decisions) && decisions.length ? decisions[0] : null;
      setRanked(latest?.input_summary?.top || []);
      setRecommendedAt(latest?.created_at || null);
    } catch (e) {
      setError(e.message || "Failed to load survey revenue data");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  return (
    <div className="crm-page">
      <div className="crm-head">
        <div className="crm-head__titles">
          <TrendingUp size={26} style={{ color: "#059669" }} />
          <div>
            <h1 className="crm-title">Survey Revenue</h1>
            <p className="crm-subtitle">Active surveys ranked by expected revenue per entrant (CPI × P(complete)).</p>
          </div>
        </div>
        <button onClick={load} className="crm-btn"><RefreshCw size={16} /> Refresh</button>
      </div>

      {recommendedAt && (
        <p className="crm-muted" style={{ fontSize: "0.72rem", display: "inline-flex", alignItems: "center", gap: "0.25rem", marginBottom: "0.75rem" }}>
          <Clock size={12} /> Last recommended {new Date(recommendedAt).toLocaleString()}
        </p>
      )}

      {error && <div className="crm-error">{error}</div>}

      {loading ? (
        <p className="crm-muted">Loading…</p>
      ) : ranked.length === 0 ? (
        <div className="crm-empty">No survey-revenue recommendations yet. Run the survey_revenue_agent to populate this view.</div>
      ) : (
        <div className="crm-table-wrap">
          <table className="crm-table">
            <thead>
              <tr>
                <th>#</th><th>Survey</th><th className="num">CPI</th>
                <th className="num">P(complete)</th><th>Basis</th><th className="num">EPC</th>
              </tr>
            </thead>
            <tbody>
              {ranked.map((s, i) => (
                <tr key={s.survey_id || i} className={i === 0 ? "top-row" : ""}>
                  <td className="crm-muted">{i + 1}</td>
                  <td style={{ fontWeight: 600, color: "#111827" }}>{s.name || s.survey_id}</td>
                  <td className="num">{fmtMoney(s.cpi)}</td>
                  <td className="num">{s.p_complete != null ? `${Math.round(s.p_complete * 100)}%` : "—"}</td>
                  <td className="crm-muted">{BASIS_LABEL[s.basis] || s.basis || "—"}</td>
                  <td className="num" style={{ fontWeight: 700, color: "#047857" }}>{fmtMoney(s.epc)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
