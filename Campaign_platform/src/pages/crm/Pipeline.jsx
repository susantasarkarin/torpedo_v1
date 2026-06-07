/**
 * Opportunity Pipeline — kanban of canonical opportunities grouped by stage.
 *
 * Consumes /api/crm/opportunities and resolves account names from
 * /api/crm/accounts. The "Mark Won" action calls
 * POST /api/crm/opportunities/{id}/win, which (per the Phase 2 spine) activates
 * the linked Project and creates a draft Invoice.
 */
import { useEffect, useState, useCallback } from "react";
import { Trophy, RefreshCw, Building2 } from "lucide-react";
import api from "../../utils/api";

// Stable left-to-right stage order; any unknown stages are appended.
const STAGE_ORDER = ["new", "rfq", "qualified", "proposal", "negotiation", "won", "lost"];

const STAGE_STYLES = {
  won: "border-green-300 bg-green-50",
  lost: "border-red-200 bg-red-50",
  rfq: "border-amber-200 bg-amber-50",
};

const fmtAmount = (n) =>
  typeof n === "number" && !Number.isNaN(n)
    ? n.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 })
    : "—";

function orderedStages(opps) {
  const present = [...new Set(opps.map((o) => o.stage || "new"))];
  const known = STAGE_ORDER.filter((s) => present.includes(s));
  const extra = present.filter((s) => !STAGE_ORDER.includes(s)).sort();
  return [...known, ...extra];
}

export default function Pipeline() {
  const [opps, setOpps] = useState([]);
  const [accounts, setAccounts] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [winningId, setWinningId] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [opportunities, accs] = await Promise.all([
        api.get("/api/crm/opportunities", { limit: 1000 }),
        api.get("/api/crm/accounts", { limit: 1000 }),
      ]);
      setOpps(Array.isArray(opportunities) ? opportunities : []);
      const map = {};
      (accs || []).forEach((a) => {
        map[a._id] = a.name;
      });
      setAccounts(map);
    } catch (e) {
      setError(e.message || "Failed to load pipeline");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const markWon = async (id) => {
    setWinningId(id);
    try {
      await api.post(`/api/crm/opportunities/${id}/win`);
      await load();
    } catch (e) {
      setError(e.message || "Failed to mark won");
    } finally {
      setWinningId(null);
    }
  };

  const stages = orderedStages(opps);
  const totalValue = opps
    .filter((o) => o.status === "open")
    .reduce((sum, o) => sum + (Number(o.amount) || 0), 0);

  return (
    <div className="p-6">
      <div className="mb-5 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Opportunity Pipeline</h1>
          <p className="text-sm text-gray-500">
            {loading ? "Loading…" : `${opps.length} opportunities · open value ${fmtAmount(totalValue)}`}
          </p>
        </div>
        <button
          onClick={load}
          className="inline-flex items-center gap-1.5 rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          <RefreshCw className="h-4 w-4" /> Refresh
        </button>
      </div>

      {error && (
        <div className="mb-4 rounded-md bg-red-50 px-4 py-2 text-sm text-red-700">{error}</div>
      )}

      {!loading && opps.length === 0 ? (
        <div className="rounded-lg border border-dashed border-gray-300 py-12 text-center text-gray-500">
          No opportunities yet. They appear here once RFQs are created or the migration runs.
        </div>
      ) : (
        <div className="flex gap-4 overflow-x-auto pb-4">
          {stages.map((stage) => {
            const items = opps.filter((o) => (o.stage || "new") === stage);
            return (
              <div key={stage} className="w-72 flex-shrink-0">
                <div className="mb-2 flex items-center justify-between px-1">
                  <span className="text-sm font-semibold capitalize text-gray-700">{stage}</span>
                  <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-500">
                    {items.length}
                  </span>
                </div>
                <div className="space-y-2">
                  {items.map((o) => (
                    <div
                      key={o._id}
                      className={`rounded-lg border p-3 shadow-sm ${STAGE_STYLES[stage] || "border-gray-200 bg-white"}`}
                    >
                      <div className="font-medium text-gray-900">{o.title || "Untitled"}</div>
                      <div className="mt-1 flex items-center gap-1 text-xs text-gray-500">
                        <Building2 className="h-3 w-3" />
                        {accounts[o.account_id] || "—"}
                      </div>
                      <div className="mt-1 text-sm font-semibold text-gray-700">{fmtAmount(o.amount)}</div>
                      {o.status === "open" && (
                        <button
                          disabled={winningId === o._id}
                          onClick={() => markWon(o._id)}
                          className="mt-2 inline-flex items-center gap-1 rounded-md border border-green-300 px-2 py-1 text-xs font-medium text-green-700 hover:bg-green-100 disabled:opacity-50"
                        >
                          <Trophy className="h-3 w-3" /> Mark Won
                        </button>
                      )}
                      {o.status && o.status !== "open" && (
                        <span className="mt-2 inline-block rounded-full bg-gray-100 px-2 py-0.5 text-xs capitalize text-gray-600">
                          {o.status}
                        </span>
                      )}
                    </div>
                  ))}
                  {items.length === 0 && (
                    <div className="rounded-lg border border-dashed border-gray-200 py-6 text-center text-xs text-gray-400">
                      empty
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
