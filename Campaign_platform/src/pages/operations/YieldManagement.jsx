import React, { useEffect, useState, useCallback } from "react";
import { buildApiUrl } from "../../config";
import "./YieldManagement.css";

const STATUS_COLORS = {
  active: "status-active",
  inactive: "status-inactive",
  testing: "status-testing",
  excluded: "status-excluded",
};

// Derive the effective status shown in the UI (considers both pool layer and yield layer)
const effectiveStatus = (s) => {
  if (s.in_pool === false) return "excluded";
  return s.survey_status || "testing";
};

const effectiveStatusLabel = (s) => {
  const es = effectiveStatus(s);
  if (es === "excluded") return "Excluded";
  if (es === "inactive") return "Inactive";
  if (es === "active") return "Active";
  return "Testing";
};

const pct = (v) => (v == null ? "—" : `${(v * 100).toFixed(1)}%`);
const money = (v) => (v == null ? "—" : `$${Number(v).toFixed(3)}`);
const num = (v) => (v == null ? "—" : Number(v).toFixed(2));

function YieldManagement() {
  const [surveys, setSurveys] = useState([]);
  const [buyers, setBuyers] = useState([]);
  const [thresholds, setThresholds] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [lastRefresh, setLastRefresh] = useState(null);

  // Filters
  const [countryFilter, setCountryFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [searchTerm, setSearchTerm] = useState("");

  // Threshold panel
  const [showThresholds, setShowThresholds] = useState(false);
  const [editThresholds, setEditThresholds] = useState(null);
  const [thresholdSaving, setThresholdSaving] = useState(false);

  // Action state
  const [actionPending, setActionPending] = useState(null); // survey_id

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (countryFilter) params.set("country_code", countryFilter);
      if (statusFilter) params.set("status", statusFilter);

      const [survRes, buyRes, thrRes] = await Promise.all([
        fetch(buildApiUrl(`/api/cint/yield-dashboard?${params}`)),
        fetch(buildApiUrl("/api/cint/buyer-stats")),
        fetch(buildApiUrl("/api/cint/yield-thresholds")),
      ]);

      if (!survRes.ok) throw new Error(`Yield dashboard: ${survRes.status}`);
      const survData = await survRes.json();
      setSurveys(survData.surveys || []);

      if (buyRes.ok) {
        const buyData = await buyRes.json();
        setBuyers(buyData.buyers || []);
      }

      if (thrRes.ok) {
        const thrData = await thrRes.json();
        setThresholds(thrData);
        setEditThresholds(JSON.parse(JSON.stringify(thrData)));
      }

      setLastRefresh(new Date());
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [countryFilter, statusFilter]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleToggleStatus = async (survey) => {
    const action = survey.survey_status === "inactive" ? "activate" : "deactivate";
    const confirmMsg =
      action === "deactivate"
        ? `Deactivate survey ${survey.survey_id} (${survey.account_name})? Traffic will stop immediately.`
        : `Activate survey ${survey.survey_id} (${survey.account_name})?`;
    if (!window.confirm(confirmMsg)) return;

    setActionPending(survey.survey_id);
    try {
      const res = await fetch(
        buildApiUrl(`/api/cint/surveys/${survey.survey_id}/yield-status`),
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action }),
        }
      );
      if (!res.ok) throw new Error(`API ${res.status}`);
      await fetchData();
    } catch (err) {
      alert(`Action failed: ${err.message}`);
    } finally {
      setActionPending(null);
    }
  };

  const handleSaveThresholds = async () => {
    setThresholdSaving(true);
    try {
      const res = await fetch(buildApiUrl("/api/cint/yield-thresholds"), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(editThresholds),
      });
      if (!res.ok) throw new Error(`API ${res.status}`);
      setThresholds(editThresholds);
      setShowThresholds(false);
    } catch (err) {
      alert(`Save failed: ${err.message}`);
    } finally {
      setThresholdSaving(false);
    }
  };

  const filteredSurveys = surveys.filter((s) => {
    if (searchTerm) {
      const term = searchTerm.toLowerCase();
      if (
        !s.survey_id.toString().includes(term) &&
        !(s.account_name || "").toLowerCase().includes(term)
      )
        return false;
    }
    return true;
  });

  const countries = [...new Set(surveys.map((s) => s.country_code).filter(Boolean))].sort();

  // Summary stats
  const activeCount = surveys.filter((s) => s.survey_status === "active").length;
  const inactiveCount = surveys.filter((s) => s.survey_status === "inactive").length;
  const testingCount = surveys.filter((s) => s.survey_status === "testing").length;
  const reviewCount = surveys.filter((s) => s.eligible_for_review).length;

  return (
    <div className="yield-page">
      {/* Header */}
      <div className="yield-header">
        <div>
          <h1>Yield Management</h1>
          <p>
            Cint survey performance &amp; traffic routing control &mdash; ranked by functional
            conversion
          </p>
        </div>
        <div className="yield-header-actions">
          {lastRefresh && (
            <span className="last-refresh">
              Updated {lastRefresh.toLocaleTimeString()}
            </span>
          )}
          <button className="btn-secondary" onClick={() => setShowThresholds(true)}>
            ⚙ Thresholds
          </button>
          <button className="btn-primary" onClick={fetchData} disabled={loading}>
            {loading ? "Loading…" : "↻ Refresh"}
          </button>
        </div>
      </div>

      {/* Summary pills */}
      <div className="yield-summary">
        <div className="pill pill-active">
          <span className="pill-value">{activeCount}</span>
          <span className="pill-label">Active</span>
        </div>
        <div className="pill pill-testing">
          <span className="pill-value">{testingCount}</span>
          <span className="pill-label">Testing</span>
        </div>
        <div className="pill pill-inactive">
          <span className="pill-value">{inactiveCount}</span>
          <span className="pill-label">Inactive</span>
        </div>
        {reviewCount > 0 && (
          <div className="pill pill-review">
            <span className="pill-value">{reviewCount}</span>
            <span className="pill-label">Eligible for Review</span>
          </div>
        )}
      </div>

      {/* Filters */}
      <div className="yield-filters">
        <input
          type="text"
          placeholder="Search survey ID or buyer…"
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          className="filter-input"
        />
        <select
          value={countryFilter}
          onChange={(e) => setCountryFilter(e.target.value)}
          className="filter-select"
        >
          <option value="">All countries</option>
          {countries.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="filter-select"
        >
          <option value="">All statuses</option>
          <option value="active">Active</option>
          <option value="testing">Testing</option>
          <option value="inactive">Inactive</option>
        </select>
      </div>

      {error && <div className="yield-error">{error}</div>}

      {/* Main table */}
      <div className="yield-table-wrap">
        <table className="yield-table">
          <thead>
            <tr>
              <th>#</th>
              <th>Survey ID</th>
              <th>Buyer</th>
              <th>CC</th>
              <th>LOI</th>
              <th>TLOI</th>
              <th>CPI</th>
              <th>RPC</th>
              <th>RPCM</th>
              <th>Global Conv</th>
              <th>Internal Conv</th>
              <th>Func Conv</th>
              <th>Quota Left</th>
              <th>Sessions</th>
              <th>Status</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {filteredSurveys.length === 0 && !loading && (
              <tr>
                <td colSpan={16} className="no-data">
                  No surveys found
                </td>
              </tr>
            )}
            {filteredSurveys.map((s) => (
              <tr
                key={s.survey_id}
                className={`row-${effectiveStatus(s)}${s.eligible_for_review ? " row-review" : ""}`}
              >
                <td className="col-rank">{s.rank}</td>
                <td className="col-id">{s.survey_id}</td>
                <td className="col-buyer" title={s.account_name}>
                  {s.account_name || "—"}
                </td>
                <td>{s.country_code || "—"}</td>
                <td>{s.loi ? `${s.loi}m` : "—"}</td>
                <td>{s.tloi ? `${s.tloi}m` : "—"}</td>
                <td>{money(s.cpi)}</td>
                <td>{money(s.rpc)}</td>
                <td>{money(s.rpcm)}</td>
                <td>{pct(s.global_conv)}</td>
                <td>
                  {s.internal_conv != null ? pct(s.internal_conv) : <span className="muted">—</span>}
                </td>
                <td className="col-fconv">{pct(s.functional_conv)}</td>
                <td>{s.total_remaining}</td>
                <td>{s.entrants_n}</td>
                <td>
                  <span className={`status-badge ${STATUS_COLORS[effectiveStatus(s)] || ""}`}>
                    {effectiveStatusLabel(s)}
                  </span>
                  {s.in_pool === false && (
                    <span className="pool-badge" title="Excluded by Survey Pool (CPI/country filter)">
                      Pool
                    </span>
                  )}
                  {s.eligible_for_review && (
                    <span className="review-badge" title="Global conv rose >10% above deactivation snapshot">
                      ✦ Review
                    </span>
                  )}
                </td>
                <td>
                  <button
                    className={`action-btn ${effectiveStatus(s) === "inactive" || effectiveStatus(s) === "excluded" ? "btn-activate" : "btn-deactivate"}`}
                    onClick={() => handleToggleStatus(s)}
                    disabled={actionPending === s.survey_id}
                  >
                    {actionPending === s.survey_id
                      ? "…"
                      : effectiveStatus(s) === "inactive" || effectiveStatus(s) === "excluded"
                      ? "Activate"
                      : "Deactivate"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Buyer stats */}
      {buyers.length > 0 && (
        <div className="yield-section">
          <h2 className="section-title">Buyer Conversion Performance</h2>
          <div className="buyer-grid">
            {buyers.map((b) => (
              <div key={b.buyer_name} className="buyer-card">
                <div className="buyer-name">{b.buyer_name}</div>
                <div className="buyer-conv">{pct(b.conversion_rate)}</div>
                <div className="buyer-meta">
                  {b.total_completes || 0} / {b.total_sessions || 0} sessions
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Thresholds modal */}
      {showThresholds && editThresholds && (
        <div className="modal-overlay" onClick={() => setShowThresholds(false)}>
          <div className="modal-box" onClick={(e) => e.stopPropagation()}>
            <h2>Yield Thresholds</h2>
            <p className="modal-subtitle">
              Global thresholds apply until per-country data is available (4–6 weeks).
            </p>

            <div className="threshold-group">
              <h3>Global</h3>
              <label>
                Inactive conv threshold (auto-deactivate below this)
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  max="1"
                  value={(editThresholds.global || {}).inactive_conv_threshold ?? 0.05}
                  onChange={(e) =>
                    setEditThresholds((t) => ({
                      ...t,
                      global: { ...(t.global || {}), inactive_conv_threshold: parseFloat(e.target.value) },
                    }))
                  }
                />
                <span className="hint">
                  Current: {pct((editThresholds.global || {}).inactive_conv_threshold ?? 0.05)}
                </span>
              </label>
              <label>
                Min IR floor (%)
                <input
                  type="number"
                  step="1"
                  min="0"
                  value={(editThresholds.global || {}).min_ir ?? 15}
                  onChange={(e) =>
                    setEditThresholds((t) => ({
                      ...t,
                      global: { ...(t.global || {}), min_ir: parseInt(e.target.value, 10) },
                    }))
                  }
                />
              </label>
              <label>
                Min CPI floor ($)
                <input
                  type="number"
                  step="0.05"
                  min="0"
                  value={(editThresholds.global || {}).min_cpi ?? 0.75}
                  onChange={(e) =>
                    setEditThresholds((t) => ({
                      ...t,
                      global: { ...(t.global || {}), min_cpi: parseFloat(e.target.value) },
                    }))
                  }
                />
              </label>
            </div>

            <div className="modal-actions">
              <button className="btn-secondary" onClick={() => setShowThresholds(false)}>
                Cancel
              </button>
              <button
                className="btn-primary"
                onClick={handleSaveThresholds}
                disabled={thresholdSaving}
              >
                {thresholdSaving ? "Saving…" : "Save"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default YieldManagement;
