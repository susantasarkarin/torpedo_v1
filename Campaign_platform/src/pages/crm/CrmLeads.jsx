/**
 * CRM Leads — canonical spine leads with the standard Convert flow
 * (lead -> account + contact, optionally an opportunity).
 */
import { useEffect, useState, useCallback } from "react";
import { RefreshCw, UserPlus, ArrowRightCircle, Download } from "lucide-react";
import api from "../../utils/api";
import { API_BASE_URL } from "../../config";
import CrmNav, { Modal, Field, inputStyle } from "./CrmNav";
import "../../styles/crm-ui.css";

const STATUS_COLORS = {
  new: "#2563eb", working: "#d97706", converted: "#059669", disqualified: "#6b7280",
};

export default function CrmLeads() {
  const [leads, setLeads] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [converting, setConverting] = useState(null);
  const [withOpp, setWithOpp] = useState(true);
  const [oppForm, setOppForm] = useState({});
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = { limit: 1000 };
      if (statusFilter) params.status = statusFilter;
      if (filter) params.q = filter;
      const data = await api.get("/api/crm/leads", params, { cacheTTL: 0 });
      setLeads(Array.isArray(data) ? data : []);
    } catch (e) {
      setError(e.message || "Failed to load leads");
    } finally {
      setLoading(false);
    }
  }, [statusFilter, filter]);

  useEffect(() => { load(); }, [load]);

  const openConvert = (lead) => {
    setConverting(lead);
    setWithOpp(true);
    setOppForm({
      title: lead.company ? `Opportunity: ${lead.company}` : `Opportunity: ${lead.name || lead.email}`,
      amount: "",
    });
  };

  const confirmConvert = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/api/crm/leads/${converting._id}/convert`,
        withOpp ? { opportunity: { title: oppForm.title, amount: parseFloat(oppForm.amount) || 0 } } : {});
      setConverting(null);
      await load();
    } catch (e) {
      setError(e.message || "Conversion failed");
    } finally {
      setBusy(false);
    }
  };

  const setStatus = async (lead, status) => {
    try {
      await api.put(`/api/crm/leads/${lead._id}`, { status });
      await load();
    } catch (e) { setError(e.message || "Update failed"); }
  };

  return (
    <div className="crm-page">
      <CrmNav />
      <div className="crm-head">
        <div>
          <h1 className="crm-title">Leads</h1>
          <p className="crm-subtitle">Canonical spine leads. Convert promotes to account + contact (+ opportunity).</p>
        </div>
        <div style={{ display: "flex", gap: "0.5rem" }}>
          <a className="crm-btn" href={`${API_BASE_URL}/api/crm/leads/export.csv`}>
            <Download size={15} /> CSV
          </a>
          <button className="crm-btn" onClick={load}><RefreshCw size={15} /> Refresh</button>
        </div>
      </div>

      {error && <div className="crm-error">{error}</div>}

      <div style={{ display: "flex", gap: "0.5rem", marginBottom: "0.75rem" }}>
        <input style={{ ...inputStyle, maxWidth: 260 }} placeholder="Search name / email / company…"
          value={filter} onChange={(e) => setFilter(e.target.value)} />
        <select style={{ ...inputStyle, width: "auto" }} value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="">all statuses</option>
          {Object.keys(STATUS_COLORS).map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>

      <div className="crm-panel">
        {loading ? <p className="crm-muted" style={{ padding: "1rem" }}>Loading…</p> :
          leads.length === 0 ? (
            <p className="crm-muted" style={{ padding: "1rem" }}>
              <UserPlus size={15} style={{ verticalAlign: "-2px" }} /> No leads match.
            </p>
          ) : leads.map((l) => (
            <div key={l._id} className="crm-row" style={{ gap: "0.75rem" }}>
              <div style={{ flex: 2, minWidth: 0 }}>
                <div style={{ fontWeight: 600, color: "#111827", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {l.name || `${l.firstName || ""} ${l.lastName || ""}`.trim() || l.email || "(unnamed)"}
                </div>
                <div className="crm-muted" style={{ fontSize: "0.75rem" }}>
                  {l.email || "no email"}{l.company ? ` · ${l.company}` : ""}{l.title ? ` · ${l.title}` : ""}
                </div>
              </div>
              <span className="crm-muted" style={{ fontSize: "0.72rem", width: 90 }}>{l.source || "—"}</span>
              <span className="crm-badge" style={{ color: STATUS_COLORS[l.status] || "#374151" }}>
                {l.status || "new"}
              </span>
              {l.status !== "converted" && (
                <div style={{ display: "flex", gap: "0.3rem" }}>
                  <button className="crm-btn crm-btn--primary" style={{ padding: "0.25rem 0.55rem", fontSize: "0.75rem" }}
                    onClick={() => openConvert(l)}>
                    <ArrowRightCircle size={13} /> Convert
                  </button>
                  {l.status !== "disqualified" && (
                    <button className="crm-btn" style={{ padding: "0.25rem 0.55rem", fontSize: "0.75rem" }}
                      onClick={() => setStatus(l, "disqualified")}>
                      Disqualify
                    </button>
                  )}
                </div>
              )}
            </div>
          ))}
      </div>

      {converting && (
        <Modal title={`Convert: ${converting.name || converting.email}`}
          onClose={() => setConverting(null)}>
          <p className="crm-muted" style={{ marginTop: 0 }}>
            Creates/links {converting.company ? <b>account “{converting.company}”</b> : "no account (no company)"}{" "}
            and {converting.email ? <b>contact {converting.email}</b> : "no contact (no email)"}.
          </p>
          <label style={{ display: "flex", alignItems: "center", gap: "0.4rem", marginBottom: "0.7rem", fontSize: "0.85rem" }}>
            <input type="checkbox" checked={withOpp} onChange={(e) => setWithOpp(e.target.checked)} />
            Also open an opportunity
          </label>
          {withOpp && (
            <>
              <Field label="Opportunity title">
                <input style={inputStyle} value={oppForm.title || ""}
                  onChange={(e) => setOppForm({ ...oppForm, title: e.target.value })} />
              </Field>
              <Field label="Amount (USD)">
                <input type="number" style={inputStyle} value={oppForm.amount || ""}
                  onChange={(e) => setOppForm({ ...oppForm, amount: e.target.value })} />
              </Field>
            </>
          )}
          <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem" }}>
            <button className="crm-btn" onClick={() => setConverting(null)}>Cancel</button>
            <button className="crm-btn crm-btn--primary" disabled={busy || (withOpp && !oppForm.title)}
              onClick={confirmConvert}>{busy ? "Converting…" : "Convert"}</button>
          </div>
        </Modal>
      )}
    </div>
  );
}
