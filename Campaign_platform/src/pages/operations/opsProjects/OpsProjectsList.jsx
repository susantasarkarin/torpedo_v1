import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  listProjects,
  setProjectFavorite,
  setProjectStatus,
  getProjectChangeLog,
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
  fmtPct,
  fmtLoi,
} from "./opsShared";
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

  // Debounce the search box; any new term goes back to page 1.
  useEffect(() => {
    const t = setTimeout(() => {
      setQ(search.trim());
      setPage(1);
    }, 300);
    return () => clearTimeout(t);
  }, [search]);

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
      await setProjectFavorite(project.id, next);
    } catch (e) {
      apply(!next);
      notifyToast(e.message || "Could not update favourite.", "error");
    } finally {
      favoriteBusy.current.delete(project.id);
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
        <div className="ops-search">
          <label htmlFor="ops-proj-search" className="ops-visually-hidden">Search projects</label>
          <input
            id="ops-proj-search"
            type="search"
            className="ops-input"
            placeholder="Search by name or number"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
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
                            { label: "Edit", onSelect: () => setModal({ mode: "edit", project: p }) },
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
