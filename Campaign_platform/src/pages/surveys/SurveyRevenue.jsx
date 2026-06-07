/**
 * Survey Revenue — ranked surveys by expected revenue per entrant.
 *
 * Consumes the survey_revenue_agent's logged recommendations:
 *   GET /api/ai/decisions?agent_name=survey_revenue_agent
 * The most recent decision carries input_summary.top — the ranked list with
 * per-survey economics (cpi, P(complete), basis, EPC).
 */
import { useEffect, useState } from "react";
import { TrendingUp, RefreshCw, Clock } from "lucide-react";
import api from "../../utils/api";

const fmtMoney = (n) =>
  typeof n === "number" && !Number.isNaN(n)
    ? `$${n.toFixed(2)}`
    : "—";

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
    setLoading(true);
    setError(null);
    try {
      const decisions = await api.get("/api/ai/decisions", {
        agent_name: "survey_revenue_agent",
        limit: 50,
      });
      const latest = Array.isArray(decisions) && decisions.length ? decisions[0] : null;
      const top = latest?.input_summary?.top || [];
      setRanked(top);
      setRecommendedAt(latest?.created_at || null);
    } catch (e) {
      setError(e.message || "Failed to load survey revenue data");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  return (
    <div className="p-6">
      <div className="mb-5 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <TrendingUp className="h-7 w-7 text-emerald-600" />
          <div>
            <h1 className="text-xl font-semibold text-gray-900">Survey Revenue</h1>
            <p className="text-sm text-gray-500">
              Active surveys ranked by expected revenue per entrant (CPI × P(complete)).
            </p>
          </div>
        </div>
        <button
          onClick={load}
          className="inline-flex items-center gap-1.5 rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          <RefreshCw className="h-4 w-4" /> Refresh
        </button>
      </div>

      {recommendedAt && (
        <p className="mb-3 inline-flex items-center gap-1 text-xs text-gray-400">
          <Clock className="h-3 w-3" /> Last recommended {new Date(recommendedAt).toLocaleString()}
        </p>
      )}

      {error && (
        <div className="mb-4 rounded-md bg-red-50 px-4 py-2 text-sm text-red-700">{error}</div>
      )}

      {loading ? (
        <p className="text-sm text-gray-500">Loading…</p>
      ) : ranked.length === 0 ? (
        <div className="rounded-lg border border-dashed border-gray-300 py-12 text-center text-gray-500">
          No survey-revenue recommendations yet. Run the survey_revenue_agent to populate this view.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
              <tr>
                <th className="px-4 py-2">#</th>
                <th className="px-4 py-2">Survey</th>
                <th className="px-4 py-2 text-right">CPI</th>
                <th className="px-4 py-2 text-right">P(complete)</th>
                <th className="px-4 py-2">Basis</th>
                <th className="px-4 py-2 text-right">EPC</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {ranked.map((s, i) => (
                <tr key={s.survey_id || i} className={i === 0 ? "bg-emerald-50/50" : "hover:bg-gray-50"}>
                  <td className="px-4 py-2 text-gray-400">{i + 1}</td>
                  <td className="px-4 py-2 font-medium text-gray-900">{s.name || s.survey_id}</td>
                  <td className="px-4 py-2 text-right text-gray-700">{fmtMoney(s.cpi)}</td>
                  <td className="px-4 py-2 text-right text-gray-700">
                    {s.p_complete != null ? `${Math.round(s.p_complete * 100)}%` : "—"}
                  </td>
                  <td className="px-4 py-2 text-gray-500">{BASIS_LABEL[s.basis] || s.basis || "—"}</td>
                  <td className="px-4 py-2 text-right font-semibold text-emerald-700">{fmtMoney(s.epc)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
