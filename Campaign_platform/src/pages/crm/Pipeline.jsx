/**
 * Opportunity Pipeline — kanban of canonical opportunities grouped by stage.
 * "Mark Won" calls POST /api/crm/opportunities/{id}/win. Plain CSS (crm-ui.css).
 */
import { useEffect, useState, useCallback } from "react";
import { Trophy, RefreshCw, Building2 } from "lucide-react";
import api from "../../utils/api";
import "../../styles/crm-ui.css";

const STAGE_ORDER = ["new", "rfq", "qualified", "proposal", "negotiation", "won", "lost"];

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
      (accs || []).forEach((a) => { map[a._id] = a.name; });
      setAccounts(map);
    } catch (e) {
      setError(e.message || "Failed to load pipeline");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

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
  const totalValue = opps.filter((o) => o.status === "open").reduce((s, o) => s + (Number(o.amount) || 0), 0);

  return (
    <div className="crm-page">
      <div className="crm-head">
        <div>
          <h1 className="crm-title">Opportunity Pipeline</h1>
          <p className="crm-subtitle">
            {loading ? "Loading…" : `${opps.length} opportunities · open value ${fmtAmount(totalValue)}`}
          </p>
        </div>
        <button onClick={load} className="crm-btn"><RefreshCw size={16} /> Refresh</button>
      </div>

      {error && <div className="crm-error">{error}</div>}

      {!loading && opps.length === 0 ? (
        <div className="crm-empty">No opportunities yet. They appear here once RFQs are created or the migration runs.</div>
      ) : (
        <div className="crm-kanban">
          {stages.map((stage) => {
            const items = opps.filter((o) => (o.stage || "new") === stage);
            return (
              <div key={stage} className="crm-col">
                <div className="crm-col__head">
                  <span className="crm-col__title">{stage}</span>
                  <span className="crm-count">{items.length}</span>
                </div>
                {items.map((o) => (
                  <div key={o._id} className={`crm-opp ${stage}`}>
                    <div className="crm-opp__title">{o.title || "Untitled"}</div>
                    <div className="crm-opp__meta"><Building2 size={12} /> {accounts[o.account_id] || "—"}</div>
                    <div className="crm-opp__amount">{fmtAmount(o.amount)}</div>
                    {o.status === "open" ? (
                      <button disabled={winningId === o._id} onClick={() => markWon(o._id)}
                        className="crm-btn crm-btn--success" style={{ marginTop: "0.5rem", padding: "0.25rem 0.5rem", fontSize: "0.75rem" }}>
                        <Trophy size={12} /> Mark Won
                      </button>
                    ) : (
                      <span className="crm-badge" style={{ marginTop: "0.5rem", display: "inline-block" }}>{o.status}</span>
                    )}
                  </div>
                ))}
                {items.length === 0 && <div className="crm-col__empty">empty</div>}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
