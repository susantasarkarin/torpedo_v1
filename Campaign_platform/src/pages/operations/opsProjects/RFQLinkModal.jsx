import { useEffect, useId, useRef, useState } from "react";
import { lookupRfq, setProjectRfq, OpsApiError } from "../../../services/opsProjectsService";
import { ModalShell } from "./opsShared";
import { rfqOf, rfqCandidatesOf, rfqStageLabel, rfqStageTone } from "./opsUtils";

// Links a project to one sales RFQ. Shows the current match (with Unlink), the server's
// candidates as one-click choices, and a debounced search. Confirm sends the PUT.
export default function RFQLinkModal({ project, onClose, onSaved }) {
  const current = rfqOf(project);
  const candidates = rfqCandidatesOf(project);
  const [selected, setSelected] = useState(null);
  const [query, setQuery] = useState("");
  const [term, setTerm] = useState("");
  const [results, setResults] = useState({ items: [], loading: false, error: null });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const busy = useRef(false);
  const searchId = useId();
  const groupId = useId();

  // Debounce the search box by 300ms.
  useEffect(() => {
    const t = setTimeout(() => setTerm(query.trim()), 300);
    return () => clearTimeout(t);
  }, [query]);

  // Search the sales RFQs. The ignore flag drops answers to older terms.
  useEffect(() => {
    if (term.length < 2) {
      setResults({ items: [], loading: false, error: null });
      return undefined;
    }
    let ignore = false;
    setResults((r) => ({ ...r, loading: true, error: null }));
    lookupRfq(term)
      .then((items) => {
        if (!ignore) setResults({ items, loading: false, error: null });
      })
      .catch((e) => {
        if (!ignore) setResults({ items: [], loading: false, error: e.message || "Search failed." });
      });
    return () => {
      ignore = true;
    };
  }, [term]);

  // One save at a time. rfqId null clears the link.
  const save = async (rfqId) => {
    if (busy.current) return;
    busy.current = true;
    setSaving(true);
    setError(null);
    try {
      const updated = await setProjectRfq(project.id, rfqId);
      onSaved(updated);
    } catch (e) {
      setError(e instanceof OpsApiError ? e.message : "Could not update the RFQ link.");
    } finally {
      busy.current = false;
      setSaving(false);
    }
  };

  const canConfirm = Boolean(selected) && selected.id !== current?.id && !saving;

  const onSubmit = (e) => {
    e.preventDefault();
    if (canConfirm) save(selected.id);
  };

  const choice = (rfq) => {
    const isSelected = selected?.id === rfq.id;
    return (
      <li key={rfq.id}>
        <button
          type="button"
          className={`ops-rfq-option ${isSelected ? "is-selected" : ""}`}
          aria-pressed={isSelected}
          onClick={() => setSelected(rfq)}
          disabled={saving}
        >
          <span className="ops-rfq-option__title">{rfq.title || rfq.id}</span>
          <span className={`ops-rfq-chip ops-rfq-chip--${rfqStageTone(rfq.stage)}`}>{rfqStageLabel(rfq.stage)}</span>
        </button>
      </li>
    );
  };

  // Search hits that are already in the candidate list are not repeated.
  const candidateIds = new Set(candidates.map((c) => c.id));
  const extraHits = results.items.filter((r) => !candidateIds.has(r.id));

  return (
    <ModalShell
      title={`Link RFQ: ${project.projectName || "project"}`}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="ops-btn ops-btn--ghost" onClick={onClose} disabled={saving}>
            Cancel
          </button>
          <button type="submit" form="ops-rfq-link-form" className="ops-btn ops-btn--primary" disabled={!canConfirm}>
            {saving ? "Saving…" : "Link RFQ"}
          </button>
        </>
      }
    >
      <form id="ops-rfq-link-form" className="ops-form" onSubmit={onSubmit} noValidate>
        {error && <p className="ops-form__error" role="alert">{error}</p>}

        <section className="ops-rfq-section" aria-labelledby={`${groupId}-current`}>
          <h3 id={`${groupId}-current`} className="ops-rfq-section__title">Current match</h3>
          {current ? (
            <div className="ops-rfq-current">
              <span className="ops-rfq-option__title">{current.title || current.id}</span>
              <span className={`ops-rfq-chip ops-rfq-chip--${rfqStageTone(current.stage)}`}>{rfqStageLabel(current.stage)}</span>
              <button
                type="button"
                className="ops-btn ops-btn--ghost ops-btn--sm"
                onClick={() => save(null)}
                disabled={saving}
              >
                Unlink
              </button>
            </div>
          ) : (
            <p className="ops-subtle">No RFQ linked.</p>
          )}
        </section>

        {candidates.length > 0 && (
          <section className="ops-rfq-section" aria-labelledby={`${groupId}-cand`}>
            <h3 id={`${groupId}-cand`} className="ops-rfq-section__title">Possible matches</h3>
            <ul className="ops-rfq-options" aria-label="Possible RFQ matches">
              {candidates.map(choice)}
            </ul>
          </section>
        )}

        <section className="ops-rfq-section" aria-labelledby={`${groupId}-search`}>
          <h3 id={`${groupId}-search`} className="ops-rfq-section__title">Search RFQs</h3>
          <div className="ops-field">
            <label htmlFor={searchId}>RFQ title or number</label>
            <input
              id={searchId}
              type="search"
              className="ops-input"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              autoComplete="off"
              placeholder="Type at least 2 characters"
            />
          </div>
          {term.length >= 2 && results.loading && <p className="ops-subtle" role="status">Searching…</p>}
          {term.length >= 2 && results.error && <p className="ops-form__error" role="alert">{results.error}</p>}
          {term.length >= 2 && !results.loading && !results.error && extraHits.length === 0 && (
            <p className="ops-subtle">No RFQs found for “{term}”.</p>
          )}
          {extraHits.length > 0 && <ul className="ops-rfq-options" aria-label="Search results">{extraHits.map(choice)}</ul>}
        </section>

        {selected && (
          <p className="ops-field__hint" role="status">
            Selected: {selected.title || selected.id}
          </p>
        )}
      </form>
    </ModalShell>
  );
}
