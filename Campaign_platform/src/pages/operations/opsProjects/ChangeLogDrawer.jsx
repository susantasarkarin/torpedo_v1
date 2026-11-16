import { useEffect, useId, useState } from "react";
import { unwrapList } from "../../../services/opsProjectsService";
import { StateMessage } from "./opsShared";
import { fmtDateTime, fmtChangeValue } from "./opsUtils";

// Side drawer listing the change log for a project or survey.
// `loader` returns the raw API response. Entries are { ts, userId, action, field, old, new, ... }.
export default function ChangeLogDrawer({ title, loader, onClose }) {
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const titleId = useId();

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    loader()
      .then((data) => {
        if (!cancelled) setEntries(unwrapList(data, "items", "entries", "changes"));
      })
      .catch((e) => {
        if (!cancelled) setError(e.message || "Could not load the change log.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // loader is recreated by the parent on every render; attempt is the real trigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attempt]);

  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="ops-overlay ops-overlay--drawer" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <aside className="ops-drawer" role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <header className="ops-modal__header">
          <h2 id={titleId}>Change log: {title}</h2>
          <button type="button" className="ops-icon-btn" onClick={onClose} aria-label="Close change log">
            ×
          </button>
        </header>
        <div className="ops-modal__body">
          {loading && <StateMessage kind="loading" title="Loading change log…" />}
          {!loading && error && (
            <StateMessage kind="error" title="Could not load the change log" message={error} onRetry={() => setAttempt((n) => n + 1)} />
          )}
          {!loading && !error && entries.length === 0 && <StateMessage kind="empty" title="No changes recorded yet" />}
          {!loading && !error && entries.length > 0 && (
            <ol className="ops-changelog">
              {entries.map((entry, i) => {
                const when = entry.ts;
                const who = entry.userId || "System";
                const summary = entry.field
                  ? `${entry.action || "Change"}: ${entry.field} ${fmtChangeValue(entry.old)} → ${fmtChangeValue(entry.new)}`
                  : entry.action || "Change recorded";
                return (
                  <li key={entry.id || i} className="ops-changelog__item">
                    <time dateTime={when || undefined}>{fmtDateTime(when)}</time>
                    <span className="ops-changelog__who">{who}</span>
                    <p>{summary}</p>
                  </li>
                );
              })}
            </ol>
          )}
        </div>
      </aside>
    </div>
  );
}
