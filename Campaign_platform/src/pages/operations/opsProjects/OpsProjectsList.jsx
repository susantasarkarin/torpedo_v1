import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  listProjects,
  getProject,
  setProjectFavorite,
  setProjectStatus,
  getProjectChangeLog,
  globalSearch,
  unwrapList,
} from "../../../services/opsProjectsService";
import { notify as notifyToast } from "../../../utils/notify";
import ProjectModal from "./ProjectModal";
import ChangeLogDrawer from "./ChangeLogDrawer";
import {
  Metric,
  StatusBadge,
  StatusChangeModal,
  Pagination,
  SortHeader,
  RowMenu,
  StateMessage,
} from "./opsShared";
import { fmtPct, fmtLoi } from "./opsUtils";
import "./opsProjects.css";

const TABS = [
  { key: "all", label: "All" },
  { key: "live", label: "Live" },
  { key: "paused", label: "Paused" },
  { key: "completed", label: "Completed" },
];

const PROJECT_STATUS_OPTIONS = [
  { value: "live", label: "Live" },
  { value: "paused", label: "Paused" },
  { value: "completed", label: "Completed" },
];

const EMPTY_COUNTS = { all: 0, live: 0, paused: 0, completed: 0 };

const projectHref = (p) => `/admin/operations/ops-projects/${p.id}`;
// A survey opens its sources page only when its parent project is known.
const sourcesHref = (projectId, surveyId) =>
  projectId && surveyId ? `/admin/operations/ops-projects/${projectId}/surveys/${surveyId}` : null;
const NO_PAGE_TIP = "Open the parent survey to see its sources";

// One dropdown row. A link when href is set; otherwise a disabled row with the tooltip.
function SearchRow({ href, title, sub, tip, onPick }) {
  return (
    <li className="ops-search-results__item">
      {href ? (
        <Link to={href} onClick={onPick}>
          {title}
          {sub && <span className="ops-search-results__sub">{sub}</span>}
        </Link>
      ) : (
        <button type="button" disabled title={tip}>
          {title}
          {sub && <span className="ops-search-results__sub">{sub}</span>}
        </button>
      )}
    </li>
  );
}

export default function OpsProjectsList() {
  const [tab, setTab] = useState("all");
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState("projectName");
  const [order, setOrder] = useState("asc");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const [data, setData] = useState({ items: [], total: 0, counts: EMPTY_COUNTS });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);

  const [modal, setModal] = useState(null); // { mode: "create" } | { mode: "edit", project }
  const [statusTarget, setStatusTarget] = useState(null);
  const [logTarget, setLogTarget] = useState(null);
  const favoriteBusy = useRef(new Set());

  const [hits, setHits] = useState(null); // { projects, surveys, suppliers } for the current term
  const [hitsLoading, setHitsLoading] = useState(false);
  const [hitsError, setHitsError] = useState(null);
  const [resultsOpen, setResultsOpen] = useState(false);
  const searchWrapRef = useRef(null);

  // Debounce the search box; any new term goes back to page 1.
  useEffect(() => {
    const t = setTimeout(() => {
      setQ(search.trim());
      setPage(1);
    }, 300);
    return () => clearTimeout(t);
  }, [search]);

  // Global search for the dropdown. Runs on the same 300ms-debounced term as the list.
  useEffect(() => {
    if (q.length < 2) {
      setHits(null);
      setHitsError(null);
      setHitsLoading(false);
      return undefined;
    }
    let ignore = false;
    setHitsLoading(true);
    setHitsError(null);
    globalSearch(q)
      .then((res) => {
        if (ignore) return;
        setHits({
          projects: unwrapList(res, "projects"),
          surveys: unwrapList(res, "surveys"),
          suppliers: unwrapList(res, "suppliers"),
        });
      })
      .catch((e) => {
        if (!ignore) setHitsError(e.message || "Search failed.");
      })
      .finally(() => {
        if (!ignore) setHitsLoading(false);
      });
    return () => {
      ignore = true;
    };
  }, [q]);

  // Close the results dropdown on outside click.
  useEffect(() => {
    if (!resultsOpen) return undefined;
    const onDown = (e) => {
      if (searchWrapRef.current && !searchWrapRef.current.contains(e.target)) setResultsOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [resultsOpen]);

  // Fetch. The ignore flag drops responses that arrive after a newer request.
  useEffect(() => {
    let ignore = false;
    setLoading(true);
    setError(null);
    listProjects({
      status: tab === "all" ? undefined : tab,
      q: q || undefined,
      sort,
      order,
      page,
      pageSize,
    })
      .then((res) => {
        if (ignore) return;
        setData({
          items: res.items || [],
          total: res.total ?? (res.items || []).length,
          counts: { ...EMPTY_COUNTS, ...(res.counts || {}) },
        });
      })
      .catch((e) => {
        if (!ignore) setError(e.message || "Could not load projects.");
      })
      .finally(() => {
        if (!ignore) setLoading(false);
      });
    return () => {
      ignore = true;
    };
  }, [tab, q, sort, order, page, pageSize, reloadKey]);

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

  // Optimistic star toggle; rolled back if the server refuses.
  const toggleFavorite = async (project) => {
    if (favoriteBusy.current.has(project.id)) return;
    favoriteBusy.current.add(project.id);
    const next = !project.isFavorite;
    const apply = (value) =>
      setData((d) => ({
        ...d,
        items: d.items.map((p) => (p.id === project.id ? { ...p, isFavorite: value } : p)),
      }));
    apply(next);
    try {
      // The server flips the flag; apply what it reports, not what was asked for.
      const res = await setProjectFavorite(project.id, next);
      if (typeof res?.isFavorite === "boolean") apply(res.isFavorite);
    } catch (e) {
      apply(!next);
      notifyToast(e.message || "Could not update favourite.", "error");
    } finally {
      favoriteBusy.current.delete(project.id);
    }
  };

  // List rows lack fieldwork date and timezone, so the edit form loads the full project.
  const onEdit = async (project) => {
    try {
      setModal({ mode: "edit", project: await getProject(project.id) });
    } catch (e) {
      notifyToast(e.message || "Could not open the project.", "error");
    }
  };

  const changeStatus = async (status) => {
    try {
      await setProjectStatus(statusTarget.id, status);
      notifyToast("Project status updated.", "success");
      setStatusTarget(null);
      reload();
    } catch (e) {
      notifyToast(e.message || "Could not change status.", "error");
    }
  };

  const onSaved = (saved) => {
    notifyToast(modal?.mode === "edit" ? "Project saved." : "Project created.", "success");
    setModal(null);
    reload();
    return saved;
  };

  const totalCount = data.counts.all ?? 0;
  const hasFilter = Boolean(q) || tab !== "all";

  return (
    <div className="ops-page">
      <header className="ops-page__header">
        <div>
          <h1 className="ops-page__title">Projects</h1>
          <p className="ops-page__subtitle">Research Desk projects and their surveys</p>
        </div>
        <button type="button" className="ops-btn ops-btn--primary" onClick={() => setModal({ mode: "create" })}>
          + New Project
        </button>
      </header>

      <div className="ops-toolbar">
        <div className="ops-search ops-search--wrap" ref={searchWrapRef}>
          <label htmlFor="ops-proj-search" className="ops-visually-hidden">Search projects, surveys and sources</label>
          <input
            id="ops-proj-search"
            type="search"
            className="ops-input"
            placeholder="Search by name or number"
            value={search}
            autoComplete="off"
            aria-expanded={resultsOpen && search.trim().length >= 2}
            aria-controls="ops-proj-search-results"
            onFocus={() => setResultsOpen(true)}
            onChange={(e) => {
              setSearch(e.target.value);
              setResultsOpen(true);
            }}
            onKeyDown={(e) => {
              if (e.key === "Escape") setResultsOpen(false);
            }}
          />
          {resultsOpen && q.length >= 2 && (
            <ul id="ops-proj-search-results" className="ops-search-results" aria-label="Search results">
              {hitsLoading && !hits && <li className="ops-search-results__empty" role="status">Searching…</li>}
              {hitsError && <li className="ops-search-results__empty" role="alert">{hitsError}</li>}
              {hits && hits.projects.length + hits.surveys.length + hits.suppliers.length === 0 && (
                <li className="ops-search-results__empty">No matches for “{q}”.</li>
              )}
              {hits && hits.projects.length > 0 && (
                <>
                  <li className="ops-search-results__group" role="presentation">Projects</li>
                  {hits.projects.map((p) => (
                    <SearchRow
                      key={`p-${p.id}`}
                      href={projectHref(p)}
                      title={p.projectName || p.id}
                      sub={p.projectNumber}
                      onPick={() => setResultsOpen(false)}
                    />
                  ))}
                </>
              )}
              {hits && hits.surveys.length > 0 && (
                <>
                  <li className="ops-search-results__group" role="presentation">Surveys</li>
                  {hits.surveys.map((s) => {
                    const href = sourcesHref(s.parentProjectId, s.id);
                    return (
                      <SearchRow
                        key={`s-${s.id}`}
                        href={href}
                        tip={NO_PAGE_TIP}
                        title={s.surveyName || s.id}
                        sub={s.surveyNo}
                        onPick={() => setResultsOpen(false)}
                      />
                    );
                  })}
                </>
              )}
              {hits && hits.suppliers.length > 0 && (
                <>
                  <li className="ops-search-results__group" role="presentation">Sources</li>
                  {hits.suppliers.map((src, i) => {
                    const href = sourcesHref(src.parentProjectId, src.surveyId);
                    return (
                      <SearchRow
                        key={`src-${src.id ?? i}`}
                        href={href}
                        tip={NO_PAGE_TIP}
                        title={src.vendorName || src.id || "Source"}
                        sub={src.status}
                        onPick={() => setResultsOpen(false)}
                      />
                    );
                  })}
                </>
              )}
            </ul>
          )}
        </div>
      </div>

      <div className="ops-tabs" role="tablist" aria-label="Filter projects by status">
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

      <div className="ops-card">
        {loading && data.items.length === 0 && <StateMessage kind="loading" title="Loading projects…" />}

        {error && (
          <StateMessage kind="error" title="Could not load projects" message={error} onRetry={reload} />
        )}

        {!error && !loading && data.items.length === 0 && (
          <StateMessage
            kind="empty"
            title={hasFilter ? "No projects match these filters" : "No projects yet"}
            message={hasFilter ? "Try another status or clear the search." : "Create the first project to get started."}
          />
        )}

        {!error && data.items.length > 0 && (
          <>
            <div className="ops-table-wrap" aria-busy={loading}>
              <table className="ops-table">
                <caption className="ops-visually-hidden">Projects, {data.total} total</caption>
                <thead>
                  <tr>
                    <th scope="col" className="ops-th ops-th--center"><span className="ops-visually-hidden">Favourite</span></th>
                    <SortHeader label="Project" sortKey="projectName" sort={sort} order={order} onSort={onSort} />
                    <SortHeader label="Number" sortKey="projectNumber" sort={sort} order={order} onSort={onSort} />
                    <SortHeader label="Manager" sortKey="managerName" sort={sort} order={order} onSort={onSort} />
                    <SortHeader label="IR" sortKey="ir" sort={sort} order={order} onSort={onSort} align="right" />
                    <SortHeader label="Conversion" sortKey="conversion" sort={sort} order={order} onSort={onSort} align="right" />
                    <SortHeader label="LOI" sortKey="loi" sort={sort} order={order} onSort={onSort} align="right" />
                    <SortHeader label="Status" sortKey="status" sort={sort} order={order} onSort={onSort} />
                    <th scope="col" className="ops-th ops-th--center"><span className="ops-visually-hidden">Actions</span></th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((p) => (
                    <tr key={p.id}>
                      <td className="ops-td ops-td--center">
                        <button
                          type="button"
                          className={`ops-star ${p.isFavorite ? "is-on" : ""}`}
                          aria-pressed={Boolean(p.isFavorite)}
                          aria-label={`${p.isFavorite ? "Remove" : "Add"} ${p.projectName} ${p.isFavorite ? "from" : "to"} favourites`}
                          onClick={() => toggleFavorite(p)}
                        >
                          {p.isFavorite ? "★" : "☆"}
                        </button>
                      </td>
                      <td className="ops-td">
                        <Link className="ops-link" to={`/admin/operations/ops-projects/${p.id}`}>
                          {p.projectName}
                        </Link>
                        <div className="ops-subtle">{p.surveyCount ?? 0} surveys</div>
                      </td>
                      <td className="ops-td">{p.projectNumber}</td>
                      <td className="ops-td">{p.managerName || "—"}</td>
                      <td className="ops-td ops-td--num"><Metric value={p.ir} format={fmtPct} /></td>
                      <td className="ops-td ops-td--num"><Metric value={p.conversion} format={fmtPct} /></td>
                      <td className="ops-td ops-td--num"><Metric value={p.loi} format={fmtLoi} /></td>
                      <td className="ops-td"><StatusBadge status={p.status} /></td>
                      <td className="ops-td ops-td--center">
                        <RowMenu
                          label={p.projectName}
                          items={[
                            { label: "Edit", onSelect: () => onEdit(p) },
                            { label: "Change status", onSelect: () => setStatusTarget(p) },
                            { label: "Change log", onSelect: () => setLogTarget(p) },
                          ]}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
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
        {!error && loading && data.items.length > 0 && <p className="ops-subtle ops-loading-note">Updating…</p>}
      </div>

      {totalCount > 0 && <p className="ops-subtle">{totalCount.toLocaleString()} projects in total</p>}

      {modal && (
        <ProjectModal
          project={modal.mode === "edit" ? modal.project : null}
          onClose={() => setModal(null)}
          onSaved={onSaved}
        />
      )}

      {statusTarget && (
        <StatusChangeModal
          entityLabel={statusTarget.projectName}
          current={statusTarget.status}
          options={PROJECT_STATUS_OPTIONS}
          onClose={() => setStatusTarget(null)}
          onSubmit={changeStatus}
        />
      )}

      {logTarget && (
        <ChangeLogDrawer
          title={logTarget.projectName}
          loader={() => getProjectChangeLog(logTarget.id)}
          onClose={() => setLogTarget(null)}
        />
      )}
    </div>
  );
}
