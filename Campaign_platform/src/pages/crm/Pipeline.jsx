/**
 * Opportunity Pipeline — editable kanban over canonical opportunities.
 * Stage moves via POST /api/crm/opportunities/{id}/stage (lost requires a
 * reason), Mark Won via /win, create + edit via the generic CRUD endpoints.
 */
import { useEffect, useState, useCallback } from "react";
import { Trophy, RefreshCw, Building2, Plus, Pencil, XCircle } from "lucide-react";
import api from "../../utils/api";
import CrmNav, { Modal, Field, inputStyle } from "./CrmNav";
import "../../styles/crm-ui.css";

const STAGE_ORDER = ["new", "rfq", "qualified", "proposal", "negotiation", "won", "lost"];
const OPEN_STAGES = STAGE_ORDER.filter((s) => s !== "won" && s !== "lost");

const fmtAmount = (n) =>
  typeof n === "number" && !Number.isNaN(n)
    ? n.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 })
    : "—";

export default function Pipeline() {
  const [opps, setOpps] = useState([]);
  const [accounts, setAccounts] = useState({});
  const [accountList, setAccountList] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState(null);   // opportunity being edited
  const [losing, setLosing] = useState(null);     // opportunity being marked lost
  const [lossReason, setLossReason] = useState("");
  const [form, setForm] = useState({});

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [opportunities, accs] = await Promise.all([
        api.get("/api/crm/opportunities", { limit: 1000 }, { cacheTTL: 0 }),
        api.get("/api/crm/accounts", { limit: 1000 }, { cacheTTL: 0 }),
      ]);
      setOpps(Array.isArray(opportunities) ? opportunities : []);
      const list = Array.isArray(accs) ? accs : [];
      setAccountList(list);
      const map = {};
      list.forEach((a) => { map[a._id] = a.name; });
      setAccounts(map);
    } catch (e) {
      setError(e.message || "Failed to load pipeline");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const act = async (id, fn) => {
    setBusyId(id);
    setError(null);
    try { await fn(); await load(); }
    catch (e) { setError(e.message || "Action failed"); }
    finally { setBusyId(null); }
  };

  const moveStage = (opp, stage) => {
    if (stage === opp.stage) return;
    if (stage === "lost") { setLosing(opp); setLossReason(""); return; }
    act(opp._id, () => api.post(`/api/crm/opportunities/${opp._id}/stage`, { stage }));
  };

  const confirmLost = () =>
    act(losing._id, async () => {
      await api.post(`/api/crm/opportunities/${losing._id}/stage`,
        { stage: "lost", loss_reason: lossReason });
      setLosing(null);
    });

  const saveNew = () =>
    act("new", async () => {
      await api.post("/api/crm/opportunities", {
        title: form.title,
        account_id: form.account_id || null,
        amount: parseFloat(form.amount) || 0,
        stage: form.stage || "new",
        owner: form.owner || null,
        expected_close_date: form.expected_close_date || null,
      });
      setCreating(false);
      setForm({});
    });

  const saveEdit = () =>
    act(editing._id, async () => {
      await api.put(`/api/crm/opportunities/${editing._id}`, {
        title: form.title,
        amount: parseFloat(form.amount) || 0,
        owner: form.owner || null,
        expected_close_date: form.expected_close_date || null,
      });
      setEditing(null);
      setForm({});
    });

  const stages = STAGE_ORDER.filter(
    (s) => OPEN_STAGES.includes(s) || opps.some((o) => (o.stage || "new") === s));
  const totalValue = opps.filter((o) => o.status === "open")
    .reduce((s, o) => s + (Number(o.amount) || 0), 0);

  return (
    <div className="crm-page">
      <CrmNav />
      <div className="crm-head">
        <div>
          <h1 className="crm-title">Opportunity Pipeline</h1>
          <p className="crm-subtitle">
            {loading ? "Loading…" : `${opps.length} opportunities · open value ${fmtAmount(totalValue)}`}
          </p>
        </div>
        <div style={{ display: "flex", gap: "0.5rem" }}>
          <button onClick={load} className="crm-btn"><RefreshCw size={16} /> Refresh</button>
          <button className="crm-btn crm-btn--primary"
            onClick={() => { setForm({ stage: "new" }); setCreating(true); }}>
            <Plus size={15} /> New Opportunity
          </button>
        </div>
      </div>

      {error && <div className="crm-error">{error}</div>}

      {loading ? <p className="crm-muted">Loading…</p> : (
        <div className="crm-kanban">
          {stages.map((stage) => {
            const items = opps.filter((o) => (o.stage || "new") === stage);
            const value = items.reduce((s, o) => s + (Number(o.amount) || 0), 0);
            return (
              <div key={stage} className="crm-col">
                <div className="crm-col__head">
                  <span className="crm-col__title">{stage}</span>
                  <span className="crm-count">{items.length} · {fmtAmount(value)}</span>
                </div>
                {items.map((o) => (
                  <div key={o._id} className={`crm-opp ${stage}`}>
                    <div className="crm-opp__title">{o.title || "Untitled"}</div>
                    <div className="crm-opp__meta"><Building2 size={12} /> {accounts[o.account_id] || "—"}</div>
                    <div className="crm-opp__amount">{fmtAmount(o.amount)}</div>
                    {o.owner && <div className="crm-muted" style={{ fontSize: "0.7rem" }}>owner: {o.owner}</div>}
                    {o.expected_close_date && (
                      <div className="crm-muted" style={{ fontSize: "0.7rem" }}>
                        close: {new Date(o.expected_close_date).toLocaleDateString()}
                      </div>
                    )}
                    {o.loss_reason && (
                      <div style={{ fontSize: "0.7rem", color: "#b91c1c" }}>lost: {o.loss_reason}</div>
                    )}
                    {o.status === "open" ? (
                      <div style={{ display: "flex", gap: "0.3rem", marginTop: "0.45rem", flexWrap: "wrap", alignItems: "center" }}>
                        <select
                          value={o.stage || "new"}
                          disabled={busyId === o._id}
                          onChange={(e) => moveStage(o, e.target.value)}
                          title="Move stage"
                          style={{ ...inputStyle, width: "auto", padding: "0.2rem 0.3rem", fontSize: "0.72rem" }}>
                          {STAGE_ORDER.map((s) => <option key={s} value={s}>{s}</option>)}
                        </select>
                        <button className="crm-btn" style={{ padding: "0.25rem 0.45rem" }} title="Edit"
                          onClick={() => {
                            setForm({
                              title: o.title, amount: o.amount, owner: o.owner || "",
                              expected_close_date: o.expected_close_date
                                ? String(o.expected_close_date).slice(0, 10) : "",
                            });
                            setEditing(o);
                          }}>
                          <Pencil size={13} />
                        </button>
                        <button className="crm-btn crm-btn--success" style={{ padding: "0.25rem 0.45rem" }}
                          disabled={busyId === o._id} title="Mark Won"
                          onClick={() => act(o._id, () => api.post(`/api/crm/opportunities/${o._id}/win`))}>
                          <Trophy size={13} />
                        </button>
                        <button className="crm-btn crm-btn--danger" style={{ padding: "0.25rem 0.45rem" }}
                          title="Mark Lost"
                          onClick={() => { setLosing(o); setLossReason(""); }}>
                          <XCircle size={13} />
                        </button>
                      </div>
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

      {(creating || editing) && (
        <Modal title={creating ? "New Opportunity" : `Edit: ${editing.title}`}
          onClose={() => { setCreating(false); setEditing(null); setForm({}); }}>
          <Field label="Title">
            <input style={inputStyle} value={form.title || ""}
              onChange={(e) => setForm({ ...form, title: e.target.value })} />
          </Field>
          {creating && (
            <>
              <Field label="Account">
                <select style={inputStyle} value={form.account_id || ""}
                  onChange={(e) => setForm({ ...form, account_id: e.target.value })}>
                  <option value="">— none —</option>
                  {accountList.map((a) => <option key={a._id} value={a._id}>{a.name}</option>)}
                </select>
              </Field>
              <Field label="Stage">
                <select style={inputStyle} value={form.stage || "new"}
                  onChange={(e) => setForm({ ...form, stage: e.target.value })}>
                  {OPEN_STAGES.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </Field>
            </>
          )}
          <Field label="Amount (USD)">
            <input type="number" style={inputStyle} value={form.amount ?? ""}
              onChange={(e) => setForm({ ...form, amount: e.target.value })} />
          </Field>
          <Field label="Owner">
            <input style={inputStyle} value={form.owner || ""} placeholder="username or email"
              onChange={(e) => setForm({ ...form, owner: e.target.value })} />
          </Field>
          <Field label="Expected close date">
            <input type="date" style={inputStyle} value={form.expected_close_date || ""}
              onChange={(e) => setForm({ ...form, expected_close_date: e.target.value })} />
          </Field>
          <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem", marginTop: "0.5rem" }}>
            <button className="crm-btn" onClick={() => { setCreating(false); setEditing(null); setForm({}); }}>Cancel</button>
            <button className="crm-btn crm-btn--primary" disabled={!form.title}
              onClick={creating ? saveNew : saveEdit}>Save</button>
          </div>
        </Modal>
      )}

      {losing && (
        <Modal title={`Mark lost: ${losing.title}`} onClose={() => setLosing(null)}>
          <Field label="Loss reason (required)">
            <input style={inputStyle} value={lossReason} autoFocus
              placeholder="e.g. budget cut, went to competitor, no response"
              onChange={(e) => setLossReason(e.target.value)} />
          </Field>
          <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem" }}>
            <button className="crm-btn" onClick={() => setLosing(null)}>Cancel</button>
            <button className="crm-btn crm-btn--danger" disabled={!lossReason.trim()}
              onClick={confirmLost}>Mark Lost</button>
          </div>
        </Modal>
      )}
    </div>
  );
}
