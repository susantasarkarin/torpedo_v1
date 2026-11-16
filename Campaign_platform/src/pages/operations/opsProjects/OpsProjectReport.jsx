import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getProjectReport, OpsApiError } from "../../../services/opsProjectsService";
import { Metric, StatusBadge, SortHeader, Breadcrumbs, StateMessage } from "./opsShared";
import { canSeePricing, fmtInt, fmtPct, fmtLoi, fmtMoney, fmtDateTime } from "./opsUtils";
import "./opsProjects.css";

const TOTAL_CARDS = [
  { key: "entrants", label: "Entrants", fmt: fmtInt },
  { key: "terms", label: "Terms", fmt: fmtInt },
  { key: "oqs", label: "OQs", fmt: fmtInt },
  { key: "completes", label: "Completes", fmt: fmtInt },
  { key: "ir", label: "IR", fmt: fmtPct },
  { key: "conversion", label: "Conversion", fmt: fmtPct },
  { key: "loi", label: "LOI", fmt: fmtLoi },
  { key: "target", label: "Target", fmt: fmtInt },
];

const SUPPLIER_NUMERIC = ["surveys", "entrants", "terms", "oqs", "completes", "ir", "conversion", "loi"];

// Accepts an array of {currency, amount} or an object keyed by currency.
function normalizeExpense(raw) {
  let rows = [];
  if (Array.isArray(raw)) {
    rows = raw.map((r) => ({ currency: r?.currency || "USD", amount: r?.amount ?? r?.total ?? r?.value ?? null }));
  } else if (raw && typeof raw === "object") {
    rows = Object.entries(raw).map(([currency, amount]) => ({ currency, amount }));
  }
  return rows.filter((r) => r.amount !== null && r.amount !== undefined);
}

// The report's latestReconciliation is keyed by surveyId: { [surveyId]: { id, createdAt, counts } }.
// Each entry gets its survey number and name from the report's survey rows.
function normalizeReconciliations(raw, surveys) {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return [];
  const byId = new Map(surveys.map((s) => [String(s.id), s]));
  return Object.entries(raw).map(([surveyId, rec]) => {
    const survey = byId.get(String(surveyId)) || {};
    return { ...rec, surveyId, surveyNo: survey.surveyNo, surveyName: survey.surveyName };
  });
}

const sortValue = (row, key) => {
  if (key === "vendorName") return String(row.vendorName || "");
  const v = row[key];
  return v === null || v === undefined ? null : Number(v);
};

export default function OpsProjectReport() {
  const { projectId } = useParams();
  const showPricing = canSeePricing();

  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [sort, setSort] = useState("completes");
  const [order, setOrder] = useState("desc");

  useEffect(() => {
    let ignore = false;
    setLoading(true);
    setError(null);
    getProjectReport(projectId)
      .then((res) => {
        if (!ignore) setReport(res || {});
      })
      .catch((e) => {
        if (!ignore) setError(e instanceof OpsApiError ? e.message : "Could not load the report.");
      })
      .finally(() => {
        if (!ignore) setLoading(false);
      });
    return () => {
      ignore = true;
    };
  }, [projectId, reloadKey]);

  const project = report?.project || {};
  const totals = report?.totals || {};
  const surveys = Array.isArray(report?.surveys) ? report.surveys : [];
  const suppliers = useMemo(() => (Array.isArray(report?.suppliers) ? report.suppliers : []), [report]);
  const expense = showPricing ? normalizeExpense(report?.expenseByCurrency) : [];
  const reconciliations = normalizeReconciliations(report?.latestReconciliation, surveys);

  const sortedSuppliers = useMemo(() => {
    const dir = order === "asc" ? 1 : -1;
    return [...suppliers].sort((a, b) => {
      const va = sortValue(a, sort);
      const vb = sortValue(b, sort);
      // Missing values sort last in both directions.
      if (va === null && vb === null) return 0;
      if (va === null) return 1;
      if (vb === null) return -1;
      if (typeof va === "string") return va.localeCompare(vb) * dir;
      return (va - vb) * dir;
    });
  }, [suppliers, sort, order]);

  const onSort = (key) => {
    if (key === sort) setOrder((o) => (o === "asc" ? "desc" : "asc"));
    else {
      setSort(key);
      setOrder(key === "vendorName" ? "asc" : "desc");
    }
  };

  const metricCell = (value, fmt) => (
    <td className="ops-td ops-td--num"><Metric value={value} format={fmt} /></td>
  );

  return (
    <div className="ops-page">
      <Breadcrumbs
        items={[
          { label: "Projects", to: "/admin/operations/ops-projects" },
          { label: project.projectName || "Project", to: `/admin/operations/ops-projects/${projectId}` },
          { label: "Report" },
        ]}
      />

      <header className="ops-page__header">
        <div className="ops-page__heading">
          <h1 className="ops-page__title">Project report</h1>
          <p className="ops-page__subtitle">
            {project.projectName || "—"} {project.projectNumber ? `(${project.projectNumber})` : ""}
            {project.status ? <> · <StatusBadge status={project.status} /></> : null}
          </p>
        </div>
      </header>

      {loading && !report && <StateMessage kind="loading" title="Loading report…" />}
      {error && <StateMessage kind="error" title="Could not load the report" message={error} onRetry={() => setReloadKey((k) => k + 1)} />}

      {!error && report && (
        <div aria-busy={loading}>
          <section className="ops-section" aria-labelledby="ops-rep-totals">
            <h2 id="ops-rep-totals" className="ops-section__title">Totals</h2>
            <dl className="ops-kpis">
              {TOTAL_CARDS.map((card) => (
                <div key={card.key} className="ops-kpi">
                  <dt>{card.label}</dt>
                  <dd><Metric value={totals[card.key]} format={card.fmt} /></dd>
                </div>
              ))}
            </dl>
          </section>

          <section className="ops-section" aria-labelledby="ops-rep-surveys">
            <h2 id="ops-rep-surveys" className="ops-section__title">Surveys</h2>
            {surveys.length === 0 ? (
              <StateMessage kind="empty" title="No surveys in this report" />
            ) : (
              <div className="ops-table-wrap">
                <table className="ops-table ops-table--wide">
                  <caption className="ops-visually-hidden">Survey figures for {project.projectName || "this project"}</caption>
                  <thead>
                    <tr>
                      <th scope="col" className="ops-th">Survey</th>
                      <th scope="col" className="ops-th">No.</th>
                      <th scope="col" className="ops-th">Status</th>
                      <th scope="col" className="ops-th ops-th--right">Entrants</th>
                      <th scope="col" className="ops-th ops-th--right">Terms</th>
                      <th scope="col" className="ops-th ops-th--right">OQs</th>
                      <th scope="col" className="ops-th ops-th--right">Completes</th>
                      <th scope="col" className="ops-th ops-th--right">IR</th>
                      <th scope="col" className="ops-th ops-th--right">Conversion</th>
                      <th scope="col" className="ops-th ops-th--right">LOI</th>
                    </tr>
                  </thead>
                  <tbody>
                    {surveys.map((s, i) => (
                      <tr key={s.id || i}>
                        <td className="ops-td">
                          {s.id ? (
                            <Link className="ops-link" to={`/admin/operations/ops-projects/${projectId}/surveys/${s.id}`}>
                              {s.surveyName || s.name || "Survey"}
                            </Link>
                          ) : (
                            s.surveyName || s.name || "Survey"
                          )}
                        </td>
                        <td className="ops-td">{s.surveyNo ?? "—"}</td>
                        <td className="ops-td">{s.status ? <StatusBadge status={s.status} /> : "—"}</td>
                        {metricCell(s.entrants, fmtInt)}
                        {metricCell(s.terms, fmtInt)}
                        {metricCell(s.oqs, fmtInt)}
                        {metricCell(s.completes, fmtInt)}
                        {metricCell(s.ir, fmtPct)}
                        {metricCell(s.conversion, fmtPct)}
                        {metricCell(s.loi, fmtLoi)}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="ops-section" aria-labelledby="ops-rep-suppliers">
            <h2 id="ops-rep-suppliers" className="ops-section__title">Supplier comparison</h2>
            {suppliers.length === 0 ? (
              <StateMessage kind="empty" title="No suppliers in this report" />
            ) : (
              <div className="ops-table-wrap">
                <table className="ops-table ops-table--wide">
                  <caption className="ops-visually-hidden">Suppliers compared across the project. Use the column headers to sort.</caption>
                  <thead>
                    <tr>
                      <SortHeader label="Supplier" sortKey="vendorName" sort={sort} order={order} onSort={onSort} />
                      <SortHeader label="Surveys" sortKey="surveys" sort={sort} order={order} onSort={onSort} align="right" />
                      <SortHeader label="Entrants" sortKey="entrants" sort={sort} order={order} onSort={onSort} align="right" />
                      <SortHeader label="Terms" sortKey="terms" sort={sort} order={order} onSort={onSort} align="right" />
                      <SortHeader label="OQs" sortKey="oqs" sort={sort} order={order} onSort={onSort} align="right" />
                      <SortHeader label="Completes" sortKey="completes" sort={sort} order={order} onSort={onSort} align="right" />
                      <SortHeader label="IR" sortKey="ir" sort={sort} order={order} onSort={onSort} align="right" />
                      <SortHeader label="Conversion" sortKey="conversion" sort={sort} order={order} onSort={onSort} align="right" />
                      <SortHeader label="LOI" sortKey="loi" sort={sort} order={order} onSort={onSort} align="right" />
                    </tr>
                  </thead>
                  <tbody>
                    {sortedSuppliers.map((s, i) => (
                      <tr key={s.vendorId || i}>
                        <td className="ops-td">{s.vendorName || s.vendorId || "—"}</td>
                        {SUPPLIER_NUMERIC.map((key) => (
                          <td key={key} className="ops-td ops-td--num">
                            <Metric value={s[key]} format={key === "ir" || key === "conversion" ? fmtPct : key === "loi" ? fmtLoi : fmtInt} />
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {expense.length > 0 && (
            <section className="ops-section" aria-labelledby="ops-rep-expense">
              <h2 id="ops-rep-expense" className="ops-section__title">Expense by currency</h2>
              <div className="ops-table-wrap">
                <table className="ops-table">
                  <caption className="ops-visually-hidden">Total expense grouped by currency</caption>
                  <thead>
                    <tr>
                      <th scope="col" className="ops-th">Currency</th>
                      <th scope="col" className="ops-th ops-th--right">Amount</th>
                    </tr>
                  </thead>
                  <tbody>
                    {expense.map((row) => (
                      <tr key={row.currency}>
                        <td className="ops-td">{row.currency}</td>
                        <td className="ops-td ops-td--num">
                          <Metric value={row.amount} format={(v) => fmtMoney(v, row.currency)} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          <section className="ops-section" aria-labelledby="ops-rep-recon">
            <h2 id="ops-rep-recon" className="ops-section__title">Latest reconciliation per survey</h2>
            {reconciliations.length === 0 ? (
              <StateMessage kind="empty" title="No reconciliations recorded" message="Run a reconciliation from the project's surveys page." />
            ) : (
              <div className="ops-table-wrap">
                <table className="ops-table ops-table--wide">
                  <caption className="ops-visually-hidden">Most recent reconciliation for each survey</caption>
                  <thead>
                    <tr>
                      <th scope="col" className="ops-th">Survey</th>
                      <th scope="col" className="ops-th">Run</th>
                      <th scope="col" className="ops-th ops-th--right">Our completes</th>
                      <th scope="col" className="ops-th ops-th--right">Accepted</th>
                      <th scope="col" className="ops-th ops-th--right">Rejected</th>
                      <th scope="col" className="ops-th ops-th--right">Matched</th>
                      <th scope="col" className="ops-th ops-th--right">Not found</th>
                      <th scope="col" className="ops-th ops-th--right">Not complete</th>
                      <th scope="col" className="ops-th ops-th--right">Not in client file</th>
                    </tr>
                  </thead>
                  <tbody>
                    {reconciliations.map((rec, i) => {
                      const c = rec.counts || {};
                      const name = [rec.surveyNo, rec.surveyName].filter(Boolean).join(" ") || rec.surveyId || "Survey";
                      return (
                        <tr key={rec.id || i}>
                          <td className="ops-td">{name}</td>
                          <td className="ops-td">{fmtDateTime(rec.createdAt)}</td>
                          {metricCell(c.ourCompletes, fmtInt)}
                          {metricCell(c.accepted, fmtInt)}
                          {metricCell(c.rejected, fmtInt)}
                          {metricCell(c.acceptedMatched, fmtInt)}
                          {metricCell(c.acceptedNotFound, fmtInt)}
                          {metricCell(c.acceptedNotComplete, fmtInt)}
                          {metricCell(c.completesNotInClientFile, fmtInt)}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
