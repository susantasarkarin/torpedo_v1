import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  listSurveys,
  getSurvey,
  getProject,
  setSurveyStatus,
  duplicateSurvey,
  downloadTrafficReport,
  getSurveyChangeLog,
  saveBlob,
} from "../../../services/opsProjectsService";
import { notify as notifyToast } from "../../../utils/notify";
import SurveyModal from "./SurveyModal";
import ProjectModal from "./ProjectModal";
import ChangeLogDrawer from "./ChangeLogDrawer";
import DataCleaningModal from "./DataCleaningModal";
import ReconciliationModal from "./ReconciliationModal";
import RFQLinkModal from "./RFQLinkModal";
import RfqChip from "./RfqChip";
import {
  Metric,
  StatusBadge,
  StatusChangeModal,
  Pagination,
  SortHeader,
  RowMenu,
  StateMessage,
  Breadcrumbs,
} from "./opsShared";
import { fmtInt, fmtPct, fmtLoi, NOT_CONFIRMED_TIP, openSurveyTestLink, TEST_LINK_TIP } from "./opsUtils";
import "./opsProjects.css";

const TABS = [
  { key: "all", label: "All" },
  { key: "live", label: "Live" },
  { key: "paused", label: "Paused" },
  { key: "completed", label: "Completed" },
  { key: "draft", label: "Draft" },
  { key: "cancelled", label: "Cancelled" },
  { key: "auto_paused", label: "Auto-paused" },
  { key: "scheduled", label: "Scheduled" },
];

// auto_paused is set by the system, so it is not offered in the manual status dialog.
const SURVEY_STATUS_OPTIONS = [
  { value: "live", label: "Live" },
  { value: "paused", label: "Paused" },
  { value: "completed", label: "Completed" },
  { value: "draft", label: "Draft" },
  { value: "cancelled", label: "Cancelled" },
  { value: "scheduled", label: "Scheduled" },
];

const EMPTY_COUNTS = { all: 0, live: 0, paused: 0, completed: 0, draft: 0, cancelled: 0, auto_paused: 0, scheduled: 0 };

// Mirrors meta.sqTermsNote from the API (routers/ops_surveys.py SQ_TERMS_NOTE).
const SQ_TERMS_TIP = "Screened out by our qualification before reaching the client survey; counted separately from Terms.";

// Metric columns. `key` matches the API field and the unverifiedMetrics list.
// `tip` is the header tooltip.
// `gated` columns are sortable only while the response does not list them as unverified.
const METRIC_COLUMNS = [
  { key: "entrants", label: "Entrants", fmt: fmtInt },
  { key: "defenderTerms", label: "Defender terms", fmt: fmtInt, gated: true },
  { key: "terms", label: "Terms", fmt: fmtInt },
  { key: "sqTerms", label: "SQ terms", fmt: fmtInt, tip: SQ_TERMS_TIP },
  { key: "abandons", label: "Abandons", fmt: fmtInt, gated: true },
  { key: "completes", label: "Completes", fmt: fmtInt },
  { key: "ir", label: "IR", fmt: fmtPct },
  { key: "conversion", label: "Conversion", fmt: fmtPct },
  { key: "loi", label: "LOI", fmt: fmtLoi },
];

export default function OpsProjectSurveys() {
  const { projectId } = useParams();

  const [tab, setTab] = useState("all");
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState("surveyName");
  const [order, setOrder] = useState("asc");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const windowKey = "p24h";

  const [project, setProject] = useState(null);
  const [data, setData] = useState({ items: [], total: 0, counts: EMPTY_COUNTS });
  const [unverified, setUnverified] = useState([]);
  const [inflightMinutes, setInflightMinutes] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);

  const [modal, setModal] = useState(null); // { mode: "create" } | { mode: "edit", survey }
  const [statusTarget, setStatusTarget] = useState(null);
  const [logTarget, setLogTarget] = useState(null);
  const [cleaningOpen, setCleaningOpen] = useState(false);
  const [reconOpen, setReconOpen] = useState(false);
  // Full project (carries the RFQ match). A failed read just hides the chip.
  const [projectFull, setProjectFull] = useState(null);
  const [rfqOpen, setRfqOpen] = useState(false);
  const [projectEdit, setProjectEdit] = useState(false);

  useEffect(() => {
    let ignore = false;
    getProject(projectId)
      .then((p) => {
        if (!ignore) setProjectFull(p);
      })
      .catch(() => {
        if (!ignore) setProjectFull(null);
      });
    return () => {
      ignore = true;
    };
  }, [projectId]);

  useEffect(() => {
    const t = setTimeout(() => {
      setQ(search.trim());
      setPage(1);
    }, 300);
    return () => clearTimeout(t);
  }, [search]);

  useEffect(() => {
    let ignore = false;
    setLoading(true);
    setError(null);
    listSurveys(projectId, {
      status: tab === "all" ? undefined : tab,
      q: q || undefined,
      sort,
      order,
      page,
      pageSize,
      window: windowKey,
    })
      .then((res) => {
        if (ignore) return;
        setProject(res.project || null);
        setData({
          items: res.items || [],
          total: res.total ?? (res.items || []).length,
          counts: { ...EMPTY_COUNTS, ...(res.counts || {}) },
        });
        setUnverified(res.meta?.unverifiedMetrics || []);
        setInflightMinutes(res.meta?.inflightMinutes ?? null);
      })
      .catch((e) => {
        if (!ignore) setError(e.message || "Could not load surveys.");
      })
      .finally(() => {
        if (!ignore) setLoading(false);
      });
    return () => {
      ignore = true;
    };
  }, [projectId, tab, q, sort, order, page, pageSize, windowKey, reloadKey]);

  const reload = useCallback(() => setReloadKey((k) => k + 1), []);

  const onSort = (key) => {
    if (key === sort) setOrder((o) => (o === "asc" ? "desc" : "asc"));
    else {
      setSort(key);
      setOrder("asc");
    }
    setPage(1);
  };

  const changeTab = (key) => {
    setTab(key);
    setPage(1);
  };

  const onDuplicate = async (survey) => {
    try {
      const copy = await duplicateSurvey(survey.id);
      notifyToast("Survey duplicated. Review the copy and save.", "success");
      reload();
      setModal({ mode: "edit", survey: copy });
    } catch (e) {
      notifyToast(e.message || "Could not duplicate the survey.", "error");
    }
  };

  // List rows are a summary; the edit form needs the full survey.
  const onEdit = async (survey) => {
    try {
      const full = await getSurvey(survey.id);
      setModal({ mode: "edit", survey: full });
    } catch (e) {
      notifyToast(e.message || "Could not open the survey.", "error");
    }
  };

  const onDownload = async (survey) => {
    try {
      const { blob, filename } = await downloadTrafficReport(survey.id, { format: "csv", includeAnswers: true });
      saveBlob(blob, filename);
    } catch (e) {
      notifyToast(e.message || "Could not download the traffic report.", "error");
    }
  };

  const changeStatus = async (status) => {
    try {
      await setSurveyStatus(statusTarget.id, status);
      notifyToast("Survey status updated.", "success");
      setStatusTarget(null);
      reload();
    } catch (e) {
      notifyToast(e.message || "Could not change status.", "error");
    }
  };

  const onSaved = () => {
    notifyToast(modal?.mode === "edit" ? "Survey saved." : "Survey created.", "success");
    setModal(null);
    reload();
  };

  const hasFilter = Boolean(q) || tab !== "all";
  // A gated column is sortable only when the response does not mark it unverified.
  const isSortable = (col) => !(col.gated && unverified.includes(col.key));

  return (
    <div className="ops-page">
      <Breadcrumbs
        items={[{ label: "Projects", to: "/admin/operations/projects" }, { label: "Surveys" }]}
      />

      <header className="ops-page__header">
        <div className="ops-page__heading">
          <h1 className="ops-page__title">{project?.projectName || "Project"}</h1>
          <dl className="ops-meta">
            <div>
              <dt>Number</dt>
              <dd className="ops-meta__number">
                {project?.projectNumber || "—"}
                {projectFull && (
                  <RfqChip project={projectFull} onReview={() => setRfqOpen(true)} />
                )}
              </dd>
            </div>
            <div><dt>Manager</dt><dd>{project?.managerName || "Unassigned"}</dd></div>
            <div><dt>Status</dt><dd>{project?.status ? <StatusBadge status={project.status} /> : "—"}</dd></div>
          </dl>
        </div>
        <div className="ops-header-actions">
          <button type="button" className="ops-btn ops-btn--ghost" disabled={!projectFull}
            onClick={() => setProjectEdit(true)}>
            Edit project
          </button>
          <Link className="ops-btn ops-btn--ghost" to={`/admin/operations/projects/research/${projectId}/report`}>
            Report
          </Link>
          <button type="button" className="ops-btn ops-btn--ghost" onClick={() => setReconOpen(true)}>
            Reconciliation
          </button>
          <button type="button" className="ops-btn ops-btn--ghost" onClick={() => setCleaningOpen(true)}>
            Request Data Cleaning
          </button>
          <button type="button" className="ops-btn ops-btn--primary" onClick={() => setModal({ mode: "create" })}>
            + New Survey
          </button>
        </div>
      </header>

      <div className="ops-toolbar">
        <div className="ops-search">
          <label htmlFor="ops-sv-search" className="ops-visually-hidden">Search surveys</label>
          <input
            id="ops-sv-search"
            type="search"
            className="ops-input"
            placeholder="Search by survey name or number"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>

      <div className="ops-tabs ops-tabs--wrap" role="tablist" aria-label="Filter surveys by status">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={tab === t.key}
            className={`ops-tab ${tab === t.key ? "is-active" : ""}`}
            onClick={() => changeTab(t.key)}
          >
            {t.label}
            <span className="ops-tab__count">{(data.counts[t.key] ?? 0).toLocaleString()}</span>
          </button>
        ))}
      </div>

      {unverified.length > 0 && (
        <p className="ops-notice" role="note">
          Some metrics are not yet verified and show “—”: {unverified.join(", ")}.
        </p>
      )}

      <div className="ops-card">
        {loading && data.items.length === 0 && <StateMessage kind="loading" title="Loading surveys…" />}

        {error && <StateMessage kind="error" title="Could not load surveys" message={error} onRetry={reload} />}

        {!error && !loading && data.items.length === 0 && (
          <StateMessage
            kind="empty"
            title={hasFilter ? "No surveys match these filters" : "No surveys in this project yet"}
            message={hasFilter ? "Try another status or clear the search." : "Create the first survey to start collecting sources."}
          />
        )}

        {!error && data.items.length > 0 && (
          <>
            <div className="ops-table-wrap" aria-busy={loading}>
              <table className="ops-table ops-table--wide">
                <caption className="ops-visually-hidden">Surveys in {project?.projectName || "this project"}, {data.total} total</caption>
                <thead>
                  <tr>
                    <SortHeader label="Survey" sortKey="surveyName" sort={sort} order={order} onSort={onSort} />
                    <SortHeader label="No." sortKey="surveyNo" sort={sort} order={order} onSort={onSort} />
                    <SortHeader label="Status" sortKey="status" sort={sort} order={order} onSort={onSort} />
                    {METRIC_COLUMNS.map((col) => {
                      const label = col.label;
                      const tip = unverified.includes(col.key) ? NOT_CONFIRMED_TIP : col.tip;
                      if (!isSortable(col)) {
                        return (
                          <th
                            key={col.key}
                            scope="col"
                            className="ops-th ops-th--right"
                            title={tip}
                          >
                            {label}
                          </th>
                        );
                      }
                      return (
                        <SortHeader
                          key={col.key}
                          label={label}
                          sortKey={col.key}
                          sort={sort}
                          order={order}
                          onSort={onSort}
                          align="right"
                          title={tip}
                        />
                      );
                    })}
                    <th scope="col" className="ops-th ops-th--center"><span className="ops-visually-hidden">Actions</span></th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((s) => (
                    <tr key={s.id}>
                      <td className="ops-td">
                        <Link className="ops-link" to={`/admin/operations/projects/research/${projectId}/surveys/${s.id}`}>
                          {s.surveyName}
                        </Link>
                      </td>
                      <td className="ops-td">{s.surveyNo ?? "—"}</td>
                      <td className="ops-td"><StatusBadge status={s.status} /></td>
                      {METRIC_COLUMNS.map((col) => (
                        <td key={col.key} className="ops-td ops-td--num">
                          <Metric
                            value={s[col.key]}
                            format={col.fmt}
                          />
                        </td>
                      ))}
                      <td className="ops-td ops-td--center ops-td--actions">
                        <button type="button" className="ops-btn ops-btn--ghost ops-btn--xs" onClick={() => onEdit(s)}
                          aria-label={`Edit ${s.surveyName}`}>
                          Edit
                        </button>
                        <RowMenu
                          label={s.surveyName}
                          items={[
                            { label: "Edit", onSelect: () => onEdit(s) },
                            { label: "Test Survey", title: TEST_LINK_TIP, onSelect: () => openSurveyTestLink(s.id) },
                            { label: "Duplicate", onSelect: () => onDuplicate(s) },
                            { label: "Download traffic report", onSelect: () => onDownload(s) },
                            { label: "Change status", onSelect: () => setStatusTarget(s) },
                            { label: "Change log", onSelect: () => setLogTarget(s) },
                          ]}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {inflightMinutes != null && (
              <p className="ops-subtle">
                Abandons = started more than {inflightMinutes} min ago without a final status.
              </p>
            )}
            <Pagination
              page={page}
              pageSize={pageSize}
              total={data.total}
              onPage={setPage}
              onPageSize={(n) => {
                setPageSize(n);
                setPage(1);
              }}
            />
          </>
        )}
      </div>

      {modal && (
        <SurveyModal
          projectId={projectId}
          survey={modal.mode === "edit" ? modal.survey : null}
          onClose={() => {
            setModal(null);
            reload();
          }}
          onSaved={onSaved}
        />
      )}

      {statusTarget && (
        <StatusChangeModal
          entityLabel={statusTarget.surveyName}
          current={statusTarget.status}
          options={SURVEY_STATUS_OPTIONS}
          onClose={() => setStatusTarget(null)}
          onSubmit={changeStatus}
        />
      )}

      {logTarget && (
        <ChangeLogDrawer
          title={logTarget.surveyName}
          loader={() => getSurveyChangeLog(logTarget.id)}
          onClose={() => setLogTarget(null)}
        />
      )}

      {cleaningOpen && (
        <DataCleaningModal
          projectId={projectId}
          onClose={() => setCleaningOpen(false)}
        />
      )}

      {reconOpen && (
        <ReconciliationModal
          projectId={projectId}
          onClose={() => setReconOpen(false)}
        />
      )}

      {projectEdit && projectFull && (
        <ProjectModal
          project={projectFull}
          onClose={() => setProjectEdit(false)}
          onSaved={(saved) => {
            notifyToast("Project updated.", "success");
            setProjectEdit(false);
            if (saved?.id) setProjectFull(saved);
            setReloadKey((k) => k + 1); // header name/manager/status come from the list response
          }}
        />
      )}

      {rfqOpen && projectFull && (
        <RFQLinkModal
          project={projectFull}
          onClose={() => setRfqOpen(false)}
          onSaved={(updated) => {
            notifyToast("RFQ link updated.", "success");
            setRfqOpen(false);
            if (updated?.id) setProjectFull(updated);
            else
              getProject(projectId)
                .then(setProjectFull)
                .catch(() => {});
          }}
        />
      )}
    </div>
  );
}
