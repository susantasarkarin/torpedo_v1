import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import {
  listSurveySuppliers,
  updateSurveySupplier,
  deleteSurveySupplier,
  downloadTrafficReport,
  getSurveyTrend,
  saveBlob,
  OpsApiError,
} from "../../../services/opsProjectsService";
import { notify as notifyToast, confirmAction } from "../../../utils/notify";
import AddSupplierModal from "./AddSupplierModal";
import { Metric, StatusBadge, Breadcrumbs, WindowToggle, StateMessage } from "./opsShared";
import { canSeePricing, fmtInt, fmtPct, fmtLoi, fmtMoney, openSurveyTestLink, TEST_LINK_TIP } from "./opsUtils";
import "./opsProjects.css";

const CURRENCIES = ["USD", "INR", "EUR", "GBP", "AUD", "CAD", "SGD", "AED"];
const TREND_DAYS = [7, 14, 30];

// Supplier (survey source) statuses the backend accepts: live, paused, completed.
const SOURCE_STATUS_OPTIONS = [
  { value: "live", label: "Live" },
  { value: "paused", label: "Paused" },
  { value: "completed", label: "Completed" },
];

// One supplier row. It owns its own edit state, so rows save independently.
function SupplierRow({ row, canPrice, onChange, onRemove, onPriceSaved }) {
  const [editingPrice, setEditingPrice] = useState(false);
  const [priceDraft, setPriceDraft] = useState({ buyPrice: "", currency: "USD" });
  const [busy, setBusy] = useState(false);

  const save = async (body, successMsg) => {
    if (busy) return false;
    setBusy(true);
    try {
      const updated = await updateSurveySupplier(row.id, body);
      // Apply what was sent, then anything the server echoes back with an id.
      onChange({ ...row, ...body, ...(updated?.id ? updated : {}) });
      if (successMsg) notifyToast(successMsg, "success");
      return true;
    } catch (e) {
      notifyToast(e instanceof OpsApiError ? e.message : "Could not save the change.", "error");
      return false;
    } finally {
      setBusy(false);
    }
  };

  const startPriceEdit = () => {
    setPriceDraft({ buyPrice: row.buyPrice ?? "", currency: row.currency || "USD" });
    setEditingPrice(true);
  };

  const savePrice = async (e) => {
    e.preventDefault();
    const n = priceDraft.buyPrice === "" ? null : Number(priceDraft.buyPrice);
    if (n !== null && (Number.isNaN(n) || n < 0)) {
      notifyToast("Buy price must be 0 or more.", "warning");
      return;
    }
    const ok = await save({ buyPrice: n, currency: priceDraft.currency }, "Buy price saved.");
    if (ok) {
      setEditingPrice(false);
      onPriceSaved(); // expense depends on price, so the list is re-read
    }
  };

  const remove = async () => {
    const confirmed = await confirmAction(
      `Remove ${row.vendorName} from this survey? The vendor record itself is not changed.`
    );
    if (!confirmed || busy) return;
    setBusy(true);
    try {
      await deleteSurveySupplier(row.id);
      notifyToast("Supplier removed from the survey.", "success");
      onRemove(row.id);
    } catch (e) {
      notifyToast(e instanceof OpsApiError ? e.message : "Could not remove the supplier.", "error");
      setBusy(false);
    }
  };

  const metric = (key, fmt) => (
    <td className="ops-td ops-td--num">
      <Metric value={row[key]} format={fmt} />
    </td>
  );

  return (
    <tr className={busy ? "is-busy" : ""}>
      <td className="ops-td">{row.vendorName || "—"}</td>
      <td className="ops-td">{row.sourceName || "—"}</td>
      {metric("entrants", fmtInt)}
      {metric("terms", fmtInt)}
      {metric("oqs", fmtInt)}
      {metric("abandons", fmtInt)}
      {metric("inFlights", fmtInt)}
      {metric("completes", fmtInt)}
      {metric("completesWindow", fmtInt)}
      {metric("ir", fmtPct)}
      {metric("conversion", fmtPct)}
      {metric("loi", fmtLoi)}

      {canPrice && (
        <td className="ops-td ops-td--num">
          {editingPrice ? (
            <form className="ops-inline-edit" onSubmit={savePrice}>
              <label className="ops-visually-hidden" htmlFor={`bp-${row.id}`}>Buy price for {row.vendorName}</label>
              <input
                id={`bp-${row.id}`}
                type="number"
                min="0"
                step="0.01"
                className="ops-input ops-input--sm"
                value={priceDraft.buyPrice}
                onChange={(e) => setPriceDraft((d) => ({ ...d, buyPrice: e.target.value }))}
              />
              <label className="ops-visually-hidden" htmlFor={`cur-${row.id}`}>Currency for {row.vendorName}</label>
              <select
                id={`cur-${row.id}`}
                className="ops-input ops-input--sm"
                value={priceDraft.currency}
                onChange={(e) => setPriceDraft((d) => ({ ...d, currency: e.target.value }))}
              >
                {CURRENCIES.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
              <button type="submit" className="ops-btn ops-btn--primary ops-btn--sm" disabled={busy}>Save</button>
              <button type="button" className="ops-btn ops-btn--ghost ops-btn--sm" onClick={() => setEditingPrice(false)} disabled={busy}>Cancel</button>
            </form>
          ) : (
            <span className="ops-inline-value">
              <Metric value={row.buyPrice} format={(v) => fmtMoney(v, row.currency)} />
              <button type="button" className="ops-icon-btn ops-icon-btn--sm" onClick={startPriceEdit} aria-label={`Edit buy price for ${row.vendorName}`} disabled={busy}>
                ✎
              </button>
            </span>
          )}
        </td>
      )}
      {canPrice && (
        <td className="ops-td ops-td--num">
          <Metric value={row.expense} format={(v) => fmtMoney(v, row.currency)} />
        </td>
      )}
      {canPrice && <td className="ops-td">{row.expenseBasis || "—"}</td>}

      <td className="ops-td">
        <label className="ops-visually-hidden" htmlFor={`st-${row.id}`}>Status for {row.vendorName}</label>
        <select
          id={`st-${row.id}`}
          className="ops-input ops-input--sm"
          value={row.status || ""}
          disabled={busy}
          onChange={(e) => save({ status: e.target.value }, "Status saved.")}
        >
          {!SOURCE_STATUS_OPTIONS.some((o) => o.value === row.status) && row.status && (
            <option value={row.status}>{row.status}</option>
          )}
          {SOURCE_STATUS_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      </td>
      <td className="ops-td ops-td--center">
        <button type="button" className="ops-btn ops-btn--danger ops-btn--sm" onClick={remove} disabled={busy}
          aria-label={`Remove ${row.vendorName} from this survey`}>
          Remove
        </button>
      </td>
    </tr>
  );
}

export default function OpsSurveySources() {
  const { projectId, surveyId } = useParams();
  const canPrice = canSeePricing();

  const [windowKey, setWindowKey] = useState("p24h");
  const [data, setData] = useState({ project: null, survey: null, items: [] });
  const [unverified, setUnverified] = useState([]);
  const [inflightMinutes, setInflightMinutes] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [adding, setAdding] = useState(false);
  const [reporting, setReporting] = useState(false);
  const [trendDays, setTrendDays] = useState(14);
  const [trend, setTrend] = useState(null);
  const [trendLoading, setTrendLoading] = useState(true);
  const [trendError, setTrendError] = useState(null);
  const [trendReloadKey, setTrendReloadKey] = useState(0);

  useEffect(() => {
    let ignore = false;
    setLoading(true);
    setError(null);
    listSurveySuppliers(surveyId, { window: windowKey })
      .then((res) => {
        if (ignore) return;
        setData({ project: res.project || null, survey: res.survey || null, items: res.items || [] });
        setUnverified(res.meta?.unverifiedMetrics || []);
        setInflightMinutes(res.meta?.inflightMinutes ?? null);
      })
      .catch((e) => {
        if (!ignore) setError(e.message || "Could not load sources.");
      })
      .finally(() => {
        if (!ignore) setLoading(false);
      });
    return () => {
      ignore = true;
    };
  }, [surveyId, windowKey, reloadKey]);

  useEffect(() => {
    let ignore = false;
    setTrendLoading(true);
    setTrendError(null);
    getSurveyTrend(surveyId, trendDays)
      .then((res) => {
        if (!ignore) setTrend(res || {});
      })
      .catch((e) => {
        if (!ignore) setTrendError(e instanceof OpsApiError ? e.message : "Could not load the trend.");
      })
      .finally(() => {
        if (!ignore) setTrendLoading(false);
      });
    return () => {
      ignore = true;
    };
  }, [surveyId, trendDays, trendReloadKey]);

  const windowLabel = windowKey === "p14d" ? "P14D" : "P24H";
  const { project, survey, items } = data;
  const trendDates = Array.isArray(trend?.days) ? trend.days : [];
  const trendSeries = Array.isArray(trend?.series) ? trend.series : [];
  const trendTotal = Array.isArray(trend?.total?.completes) ? trend.total.completes : [];

  const updateRow = (next) =>
    setData((d) => ({ ...d, items: d.items.map((r) => (r.id === next.id ? next : r)) }));
  const removeRow = (id) =>
    setData((d) => ({ ...d, items: d.items.filter((r) => r.id !== id) }));

  const onReport = async () => {
    setReporting(true);
    try {
      const { blob, filename } = await downloadTrafficReport(surveyId, { format: "csv", includeAnswers: true });
      saveBlob(blob, filename);
    } catch (e) {
      notifyToast(e instanceof OpsApiError ? e.message : "Could not download the traffic report.", "error");
    } finally {
      setReporting(false);
    }
  };

  const metricHeader = (label, key) => (
    <th scope="col" className="ops-th ops-th--right" title={unverified.includes(key) ? "definition not yet confirmed" : undefined}>
      {label}
    </th>
  );

  return (
    <div className="ops-page">
      <Breadcrumbs
        items={[
          { label: "Projects", to: "/admin/operations/ops-projects" },
          { label: "Surveys", to: `/admin/operations/ops-projects/${projectId}` },
          { label: "Sources" },
        ]}
      />

      <header className="ops-page__header">
        <div className="ops-page__heading">
          <h1 className="ops-page__title">{survey?.surveyName || "Survey sources"}</h1>
          <dl className="ops-meta">
            <div><dt>Project</dt><dd>{project?.projectName || "—"} {project?.projectNumber ? `(${project.projectNumber})` : ""}</dd></div>
            <div><dt>Manager</dt><dd>{project?.managerName || "Unassigned"}</dd></div>
            <div><dt>Survey no.</dt><dd>{survey?.surveyNo ?? "—"}</dd></div>
            <div><dt>Survey status</dt><dd>{survey?.status ? <StatusBadge status={survey.status} /> : "—"}</dd></div>
          </dl>
        </div>
        <div className="ops-header-actions">
          <button type="button" className="ops-btn ops-btn--ghost" onClick={() => openSurveyTestLink(surveyId)} title={TEST_LINK_TIP}>
            Test Survey
          </button>
          <button type="button" className="ops-btn ops-btn--ghost" onClick={onReport} disabled={reporting}>
            {reporting ? "Preparing…" : "Download traffic report"}
          </button>
          <button type="button" className="ops-btn ops-btn--primary" onClick={() => setAdding(true)}>
            + Add supplier
          </button>
        </div>
      </header>

      <div className="ops-toolbar ops-toolbar--end">
        <WindowToggle value={windowKey} onChange={setWindowKey} />
      </div>

      {unverified.length > 0 && (
        <p className="ops-notice" role="note">
          Some metrics are not yet verified and show “—”: {unverified.join(", ")}.
        </p>
      )}

      <div className="ops-card">
        {loading && items.length === 0 && <StateMessage kind="loading" title="Loading sources…" />}
        {error && <StateMessage kind="error" title="Could not load sources" message={error} onRetry={() => setReloadKey((k) => k + 1)} />}
        {!error && !loading && items.length === 0 && (
          <StateMessage kind="empty" title="No suppliers on this survey yet" message="Add vendors to start receiving traffic from them." />
        )}

        {!error && items.length > 0 && (
          <div className="ops-table-wrap" aria-busy={loading}>
            <table className="ops-table ops-table--wide">
              <caption className="ops-visually-hidden">Suppliers for {survey?.surveyName || "this survey"}</caption>
              <thead>
                <tr>
                  <th scope="col" className="ops-th">Vendor</th>
                  <th scope="col" className="ops-th">Source</th>
                  {metricHeader("Entrants", "entrants")}
                  {metricHeader("Terms", "terms")}
                  {metricHeader("OQs", "oqs")}
                  {metricHeader("Abandons", "abandons")}
                  {metricHeader("In-flights", "inFlights")}
                  {metricHeader("Completes", "completes")}
                  {metricHeader(`Completes (${windowLabel})`, "completesWindow")}
                  {metricHeader("IR", "ir")}
                  {metricHeader("Conversion", "conversion")}
                  {metricHeader("LOI", "loi")}
                  {canPrice && <th scope="col" className="ops-th ops-th--right">Buy price</th>}
                  {canPrice && <th scope="col" className="ops-th ops-th--right">Expense</th>}
                  {canPrice && <th scope="col" className="ops-th">Expense basis</th>}
                  <th scope="col" className="ops-th">Status</th>
                  <th scope="col" className="ops-th ops-th--center"><span className="ops-visually-hidden">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {items.map((row) => (
                  <SupplierRow
                    key={row.id}
                    row={row}
                    canPrice={canPrice}
                    onChange={updateRow}
                    onRemove={removeRow}
                    onPriceSaved={() => setReloadKey((k) => k + 1)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
        {!error && items.length > 0 && inflightMinutes != null && (
          <p className="ops-subtle">
            In-Flights = started in the last {inflightMinutes} min without a final status; Abandons = older than that.
          </p>
        )}
      </div>

      <section className="ops-section" aria-labelledby="ops-trend-title">
        <div className="ops-section__head">
          <h2 id="ops-trend-title" className="ops-section__title">Completes trend</h2>
          <label className="ops-pagination__size">
            Days
            <select value={trendDays} onChange={(e) => setTrendDays(Number(e.target.value))}>
              {TREND_DAYS.map((d) => (
                <option key={d} value={d}>{d}</option>
              ))}
            </select>
          </label>
        </div>

        {trendLoading && !trend && <StateMessage kind="loading" title="Loading trend…" />}
        {trendError && (
          <StateMessage kind="error" title="Could not load the trend" message={trendError} onRetry={() => setTrendReloadKey((k) => k + 1)} />
        )}
        {!trendError && trend && trendDates.length === 0 && (
          <StateMessage kind="empty" title="No trend data for this period" message="Completes appear here once traffic arrives." />
        )}
        {!trendError && trendDates.length > 0 && (
          <div className="ops-card" aria-busy={trendLoading}>
            <div className="ops-table-wrap">
              <table className="ops-table ops-trend-table">
                <caption className="ops-visually-hidden">Completes per day for the last {trendDays} days, by supplier, with total</caption>
                <thead>
                  <tr>
                    <th scope="col" className="ops-th">Date</th>
                    {trendSeries.map((s, j) => (
                      <th key={s.vendorId || j} scope="col" className="ops-th ops-th--right">{s.vendorName || s.vendorId || "—"}</th>
                    ))}
                    <th scope="col" className="ops-th ops-th--right">Total</th>
                  </tr>
                </thead>
                <tbody>
                  {trendDates.map((day, i) => (
                    <tr key={`${day}-${i}`}>
                      <th scope="row" className="ops-td">{String(day)}</th>
                      {trendSeries.map((s, j) => (
                        <td key={s.vendorId || j} className="ops-td ops-td--num">
                          <Metric value={Array.isArray(s.completes) ? s.completes[i] : null} format={fmtInt} />
                        </td>
                      ))}
                      <td className="ops-td ops-td--num">
                        <Metric value={trendTotal[i]} format={fmtInt} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </section>

      {adding && (
        <AddSupplierModal
          surveyId={surveyId}
          attachedVendorIds={items.map((r) => r.vendorId)}
          canPrice={canPrice}
          onClose={() => setAdding(false)}
          onAdded={() => {
            setAdding(false);
            notifyToast("Suppliers added to the survey.", "success");
            setReloadKey((k) => k + 1);
          }}
        />
      )}
    </div>
  );
}
