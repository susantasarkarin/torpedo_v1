import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  listSurveySuppliers,
  updateSurveySupplier,
  deleteSurveySupplier,
  downloadTrafficReport,
  saveBlob,
  OpsApiError,
} from "../../../services/opsProjectsService";
import { notify as notifyToast, confirmAction } from "../../../utils/notify";
import AddSupplierModal from "./AddSupplierModal";
import AttachLinkModal from "./AttachLinkModal";
import { Metric, StatusBadge, Breadcrumbs, StateMessage } from "./opsShared";
import { canSeePricing, fmtInt, fmtPct, fmtLoi, openSurveyTestLink, TEST_LINK_TIP } from "./opsUtils";
import "./opsProjects.css";

// Supplier (survey source) statuses the backend accepts: live, paused, completed.
const SOURCE_STATUS_OPTIONS = [
  { value: "live", label: "Live" },
  { value: "paused", label: "Paused" },
  { value: "completed", label: "Completed" },
];

// One supplier row. It owns its own edit state, so rows save independently.
function SupplierRow({ row, onChange, onRemove, onAttach }) {
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
      <td className="ops-td">
        <div>{row.vendorName || "—"}</div>
        {row.needsLink ? (
          <span className="ops-badge ops-badge--draft">No link yet</span>
        ) : (
          <div className="ops-subtle">link {row.surveyNo}</div>
        )}
      </td>
      <td className="ops-td">{row.sourceName || "—"}</td>
      {metric("entrants", fmtInt)}
      {metric("terms", fmtInt)}
      {metric("abandons", fmtInt)}
      {metric("completes", fmtInt)}
      {metric("ir", fmtPct)}
      {metric("conversion", fmtPct)}
      {metric("loi", fmtLoi)}


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
        {row.needsLink && (
          <button type="button" className="ops-btn ops-btn--ghost ops-btn--sm" onClick={() => onAttach(row)} disabled={busy}
            aria-label={`Attach link to ${row.vendorName}`}>
            Attach link
          </button>
        )}
        {row.legacyProjectId && (
          <Link className="ops-btn ops-btn--ghost ops-btn--sm" to={`/admin/operations/projects/${row.legacyProjectId}`}
            aria-label={`Open link settings for ${row.vendorName}`}>
            Open link settings
          </Link>
        )}
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

  const [data, setData] = useState({ project: null, survey: null, items: [] });
  const [unverified, setUnverified] = useState([]);
  const [inflightMinutes, setInflightMinutes] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [adding, setAdding] = useState(false);
  const [linkRow, setLinkRow] = useState(null);
  const [reporting, setReporting] = useState(false);

  useEffect(() => {
    let ignore = false;
    setLoading(true);
    setError(null);
    listSurveySuppliers(surveyId)
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
  }, [surveyId, reloadKey]);

  const { project, survey, items } = data;

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
          { label: "Projects", to: "/admin/operations/projects" },
          { label: "Surveys", to: `/admin/operations/projects/research/${projectId}` },
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
                  <th scope="col" className="ops-th">Source name</th>
                  <th scope="col" className="ops-th">Source</th>
                  {metricHeader("Entrants", "entrants")}
                  {metricHeader("Terms", "terms")}
                  {metricHeader("Abandons", "abandons")}
                  {metricHeader("Completes", "completes")}
                  {metricHeader("IR", "ir")}
                  {metricHeader("Conversion", "conversion")}
                  {metricHeader("LOI", "loi")}
                  <th scope="col" className="ops-th">Status</th>
                  <th scope="col" className="ops-th ops-th--center"><span className="ops-visually-hidden">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {items.map((row) => (
                  <SupplierRow
                    key={row.id}
                    row={row}
                    onChange={updateRow}
                    onRemove={removeRow}
                    onAttach={setLinkRow}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
        {!error && items.length > 0 && inflightMinutes != null && (
          <p className="ops-subtle">
            Abandons = started more than {inflightMinutes} min ago without a final status.
          </p>
        )}
      </div>


      {adding && (
        <AddSupplierModal
          surveyId={surveyId}
          project={data.project}
          canPrice={canPrice}
          onClose={() => setAdding(false)}
          onAdded={() => {
            setAdding(false);
            notifyToast("Suppliers added to the survey.", "success");
            setReloadKey((k) => k + 1);
          }}
        />
      )}

      {linkRow && (
        <AttachLinkModal
          row={linkRow}
          onClose={() => setLinkRow(null)}
          onAttached={() => {
            setLinkRow(null);
            notifyToast("Link attached.", "success");
            setReloadKey((k) => k + 1); // metrics come from the link, so the list is re-read
          }}
        />
      )}
    </div>
  );
}
