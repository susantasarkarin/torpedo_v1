// Shared presentation pieces for the Operations > Projects (Research Desk) pages.
// Kept in one file so the list, surveys, sources and modal screens render
// metrics, statuses, menus and dialogs the same way.

import { useEffect, useId, useRef, useState } from "react";
import "./opsProjects.css";

export const NOT_CONFIRMED_TIP = "definition not yet confirmed";

// Only these roles see buy price / expense. Read from the role the login stored.
export const canSeePricing = () => {
  try {
    const role = (localStorage.getItem("role") || "").toLowerCase();
    return role === "admin" || role === "finance";
  } catch {
    return false;
  }
};

// ---------- Formatters (null means "not yet confirmed", never 0) ----------

export const fmtInt = (v) => (v === null || v === undefined ? null : Number(v).toLocaleString());
export const fmtPct = (v) => (v === null || v === undefined ? null : `${Number(v).toFixed(1)}%`);
export const fmtLoi = (v) => (v === null || v === undefined ? null : `${Number(v).toFixed(1)} min`);
export const fmtMoney = (v, currency) => {
  if (v === null || v === undefined) return null;
  try {
    return new Intl.NumberFormat("en-US", { style: "currency", currency: currency || "USD" }).format(Number(v));
  } catch {
    return `${Number(v).toFixed(2)} ${currency || ""}`.trim();
  }
};
export const fmtDateTime = (v) => {
  if (!v) return "—";
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? String(v) : d.toLocaleString();
};

// Renders a metric. A null value shows an em dash with the agreed tooltip.
export function Metric({ value, format = (v) => v, className = "" }) {
  const text = format(value);
  if (text === null || text === undefined) {
    return (
      <span className={`ops-null ${className}`} title={NOT_CONFIRMED_TIP} aria-label={NOT_CONFIRMED_TIP}>
        —
      </span>
    );
  }
  return <span className={className}>{text}</span>;
}

export const STATUS_LABELS = {
  live: "Live",
  paused: "Paused",
  completed: "Completed",
  draft: "Draft",
  cancelled: "Cancelled",
  auto_paused: "Auto-paused",
  scheduled: "Scheduled",
  all: "All",
};

export function StatusBadge({ status }) {
  const label = STATUS_LABELS[status] || status || "—";
  return <span className={`ops-badge ops-badge--${status || "unknown"}`}>{label}</span>;
}

// Pagination footer. `total` is the server total; page is 1-based.
export function Pagination({ page, pageSize, total, onPage, onPageSize, pageSizes = [10, 20, 50] }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const first = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const last = Math.min(total, page * pageSize);
  return (
    <nav className="ops-pagination" aria-label="Pagination">
      <span className="ops-pagination__info">
        {first}–{last} of {total.toLocaleString()}
      </span>
      <label className="ops-pagination__size">
        Rows
        <select value={pageSize} onChange={(e) => onPageSize(Number(e.target.value))}>
          {pageSizes.map((n) => (
            <option key={n} value={n}>{n}</option>
          ))}
        </select>
      </label>
      <button type="button" className="ops-btn ops-btn--ghost" disabled={page <= 1} onClick={() => onPage(page - 1)}>
        Previous
      </button>
      <span className="ops-pagination__page">Page {page} of {pages}</span>
      <button type="button" className="ops-btn ops-btn--ghost" disabled={page >= pages} onClick={() => onPage(page + 1)}>
        Next
      </button>
    </nav>
  );
}

// Sortable column header. Sets aria-sort so screen readers announce the order.
export function SortHeader({ label, sortKey, sort, order, onSort, align = "left", title }) {
  const active = sort === sortKey;
  return (
    <th
      scope="col"
      className={`ops-th ops-th--${align}`}
      aria-sort={active ? (order === "asc" ? "ascending" : "descending") : "none"}
      title={title}
    >
      <button type="button" className="ops-sort" onClick={() => onSort(sortKey)}>
        {label}
        <span aria-hidden="true" className="ops-sort__arrow">
          {active ? (order === "asc" ? "▲" : "▼") : "↕"}
        </span>
      </button>
    </th>
  );
}

// Modal dialog shell with Escape to close and a labelled dialog role.
export function ModalShell({ title, onClose, children, footer, wide = false }) {
  const titleId = useId();
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="ops-overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`ops-modal ${wide ? "ops-modal--wide" : ""}`} role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <header className="ops-modal__header">
          <h2 id={titleId}>{title}</h2>
          <button type="button" className="ops-icon-btn" onClick={onClose} aria-label="Close dialog">
            ×
          </button>
        </header>
        <div className="ops-modal__body">{children}</div>
        {footer && <footer className="ops-modal__footer">{footer}</footer>}
      </div>
    </div>
  );
}

// The ⋯ row menu. Closes on outside click and Escape.
export function RowMenu({ label, items }) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef(null);
  const menuId = useId();

  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false);
    };
    const onKey = (e) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="ops-menu" ref={wrapRef}>
      <button
        type="button"
        className="ops-icon-btn"
        aria-label={`Actions for ${label}`}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={menuId}
        onClick={() => setOpen((o) => !o)}
      >
        ⋯
      </button>
      {open && (
        <ul id={menuId} className="ops-menu__list" role="menu">
          {items.map((item) => (
            <li key={item.label} role="none">
              <button
                type="button"
                role="menuitem"
                className="ops-menu__item"
                disabled={item.disabled}
                onClick={() => {
                  setOpen(false);
                  item.onSelect();
                }}
              >
                {item.label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// Change-status dialog: radio list of statuses, submit guarded against double clicks.
export function StatusChangeModal({ entityLabel, current, options, onClose, onSubmit }) {
  const [value, setValue] = useState(current || options[0]?.value);
  const [saving, setSaving] = useState(false);
  const busy = useRef(false);
  const groupId = useId();

  const submit = async () => {
    if (busy.current || value === current) return;
    busy.current = true;
    setSaving(true);
    try {
      await onSubmit(value);
    } finally {
      busy.current = false;
      setSaving(false);
    }
  };

  return (
    <ModalShell
      title={`Change status: ${entityLabel}`}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="ops-btn ops-btn--ghost" onClick={onClose} disabled={saving}>
            Cancel
          </button>
          <button type="button" className="ops-btn ops-btn--primary" onClick={submit} disabled={saving || value === current}>
            {saving ? "Saving…" : "Update status"}
          </button>
        </>
      }
    >
      <fieldset className="ops-fieldset" aria-labelledby={groupId}>
        <legend id={groupId}>Status</legend>
        {options.map((opt) => (
          <label key={opt.value} className="ops-radio">
            <input
              type="radio"
              name="ops-status"
              value={opt.value}
              checked={value === opt.value}
              onChange={() => setValue(opt.value)}
            />
            {opt.label}
          </label>
        ))}
      </fieldset>
    </ModalShell>
  );
}

// Searchable timezone picker. Options come from Intl.supportedValuesOf.
const TIMEZONES = (() => {
  try {
    const list = Intl.supportedValuesOf ? Intl.supportedValuesOf("timeZone") : [];
    return list.length ? list : ["UTC"];
  } catch {
    return ["UTC"];
  }
})();

export function TimezoneSelect({ id, value, onChange, error }) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const listId = useId();
  const wrapRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const q = query.trim().toLowerCase();
  const matches = (q ? TIMEZONES.filter((tz) => tz.toLowerCase().includes(q)) : TIMEZONES).slice(0, 100);

  return (
    <div className="ops-tz" ref={wrapRef}>
      <input
        id={id}
        type="text"
        role="combobox"
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        className={`ops-input ${error ? "ops-input--error" : ""}`}
        placeholder="Search timezone…"
        value={open ? query : value || ""}
        onFocus={() => {
          setQuery("");
          setOpen(true);
        }}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        aria-invalid={Boolean(error)}
        autoComplete="off"
      />
      {open && (
        <ul id={listId} role="listbox" className="ops-tz__list" aria-label="Timezones">
          {matches.length === 0 && <li className="ops-tz__empty">No timezone matches</li>}
          {matches.map((tz) => (
            <li key={tz}>
              <button
                type="button"
                role="option"
                aria-selected={tz === value}
                className={`ops-tz__option ${tz === value ? "is-selected" : ""}`}
                onClick={() => {
                  onChange(tz);
                  setOpen(false);
                  setQuery("");
                }}
              >
                {tz}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// Breadcrumb trail. Items with `to` are links rendered through `Link`.
export function Breadcrumbs({ items, LinkComponent }) {
  return (
    <nav aria-label="Breadcrumb" className="ops-crumbs">
      <ol>
        {items.map((item, i) => {
          const last = i === items.length - 1;
          return (
            <li key={`${item.label}-${i}`} aria-current={last ? "page" : undefined}>
              {item.to && !last ? <LinkComponent to={item.to}>{item.label}</LinkComponent> : item.label}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

// Window toggle (P24H / P14D) used by the surveys and sources screens.
export function WindowToggle({ value, onChange }) {
  const options = [
    { value: "p24h", label: "P24H" },
    { value: "p14d", label: "P14D" },
  ];
  return (
    <div className="ops-segmented" role="radiogroup" aria-label="Metrics window">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          className={`ops-segmented__btn ${value === o.value ? "is-active" : ""}`}
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

// Page-level message: loading, empty or error states share one look.
export function StateMessage({ kind, title, message, onRetry }) {
  return (
    <div className={`ops-state ops-state--${kind}`} role={kind === "error" ? "alert" : "status"}>
      <p className="ops-state__title">{title}</p>
      {message && <p className="ops-state__msg">{message}</p>}
      {onRetry && (
        <button type="button" className="ops-btn ops-btn--ghost" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}
