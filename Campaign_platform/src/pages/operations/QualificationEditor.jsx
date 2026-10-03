import { useEffect, useState } from "react";
import { buildApiUrl } from "../../config";
import { authFetch } from "../../utils/api";
import "./QualificationEditor.css";

const GENDERS = [
  { value: "m", label: "Male" },
  { value: "f", label: "Female" },
];

const EMPTY_QUAL = { enabled: false, ageMin: "", ageMax: "", genders: [], employment: [], occupation: [], bank: [], custom: [] };

const authHeaders = (extra = {}) => ({ Authorization: localStorage.getItem("session_id") || "", ...extra });

// Project-level qualification criteria + routing settings (survey routing engine).
// Value lives on the project: formData.qualification, formData.routingEnabled, formData.routingPriority.
export default function QualificationEditor({ formData, setFormData }) {
  const [library, setLibrary] = useState(null);
  const [pick, setPick] = useState("");
  const [draft, setDraft] = useState(null); // {text, options} while creating a bank question
  const [bankError, setBankError] = useState("");
  const qual = { ...EMPTY_QUAL, ...(formData.qualification || {}) };

  const loadLibrary = () =>
    authFetch(buildApiUrl("/api/routing/question-library"), { headers: authHeaders() })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => d && setLibrary(d))
      .catch(() => {});

  useEffect(() => { loadLibrary(); }, []);

  const bankById = Object.fromEntries((library?.bank || []).map((q) => [q.id, q]));
  const usedIds = new Set(qual.bank.map((b) => b.id));

  const addFromBank = (id) => {
    const q = bankById[id];
    if (!q || usedIds.has(id)) return;
    setQual({ bank: [...qual.bank, { id, qualifying: [] }] });
    setPick("");
  };

  const saveDraft = async () => {
    setBankError("");
    const options = (draft?.optionsText || "").split(",").map((o) => o.trim()).filter(Boolean);
    try {
      const res = await authFetch(buildApiUrl("/api/routing/questions"), {
        method: "POST",
        headers: authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ text: draft?.text || "", options }),
      });
      const out = await res.json();
      if (!res.ok) throw new Error(out.detail || "Could not save the question");
      await loadLibrary();
      setQual({ bank: [...qual.bank, { id: out.id, qualifying: [] }] });
      setDraft(null);
    } catch (err) {
      setBankError(err.message);
    }
  };

  const setQual = (patch) => setFormData((prev) => ({
    ...prev,
    qualification: { ...EMPTY_QUAL, ...(prev.qualification || {}), ...patch },
  }));

  const toggle = (field, value) => {
    const list = qual[field] || [];
    setQual({ [field]: list.includes(value) ? list.filter((v) => v !== value) : [...list, value] });
  };


  const libQuestion = (id) => library?.questions?.find((q) => q.id === id);

  return (
    <fieldset className="pp-fieldset qe">
      <legend>Qualification &amp; Routing</legend>

      <label className="qe-toggle">
        <input type="checkbox" checked={qual.enabled} onChange={(e) => setQual({ enabled: e.target.checked })} />
        Pre-screen respondents in Torpedo before sending them to this survey
      </label>
      <small className="pp-hint">
        Only criteria you set here are checked. Leave this off to send everyone to the survey as before.
      </small>

      {qual.enabled && (
        <div className="qe-body">
          <div className="pp-form-row">
            <div className="pp-field">
              <label>Minimum age</label>
              <input type="number" min="13" max="99" value={qual.ageMin ?? ""} onChange={(e) => setQual({ ageMin: e.target.value })} />
            </div>
            <div className="pp-field">
              <label>Maximum age</label>
              <input type="number" min="13" max="120" value={qual.ageMax ?? ""} onChange={(e) => setQual({ ageMax: e.target.value })} />
            </div>
          </div>

          <div className="qe-group">
            <span className="qe-group-label">Gender <small>(none ticked = any)</small></span>
            {GENDERS.map((g) => (
              <label key={g.value} className="qe-chip">
                <input type="checkbox" checked={qual.genders.includes(g.value)} onChange={() => toggle("genders", g.value)} />
                {g.label}
              </label>
            ))}
          </div>

          {["employment", "occupation"].map((field) => {
            const q = libQuestion(field);
            if (!q) return null;
            return (
              <div key={field} className="qe-group">
                <span className="qe-group-label">
                  {field === "employment" ? "Employment status" : "Occupation / industry"} <small>(none ticked = not asked)</small>
                </span>
                {q.options.map((o) => (
                  <label key={o.value} className="qe-chip">
                    <input type="checkbox" checked={qual[field].includes(o.value)} onChange={() => toggle(field, o.value)} />
                    {o.label}
                  </label>
                ))}
              </div>
            );
          })}

          <div className="qe-group">
            <span className="qe-group-label">
              Questions from the question bank <small>(create once, reuse in any project)</small>
            </span>
            {qual.bank.map((ref, i) => {
              const q = bankById[ref.id];
              if (!q) return null;
              return (
                <div key={ref.id} className="qe-custom">
                  <strong className="qe-custom-title">
                    {q.text}{q.active === false ? " (archived)" : ""}
                  </strong>
                  <div className="qe-custom-qualifying">
                    <span>Qualifying answers:</span>
                    {q.options.map((o) => (
                      <label key={o} className="qe-chip">
                        <input
                          type="checkbox"
                          checked={(ref.qualifying || []).includes(o)}
                          onChange={() => {
                            const bank = [...qual.bank];
                            const chosen = ref.qualifying || [];
                            bank[i] = { ...ref, qualifying: chosen.includes(o) ? chosen.filter((x) => x !== o) : [...chosen, o] };
                            setQual({ bank });
                          }}
                        />
                        {o}
                      </label>
                    ))}
                  </div>
                  {!(ref.qualifying || []).length && (
                    <small className="qe-warn">Tick at least one qualifying answer, or this question is ignored.</small>
                  )}
                  <button type="button" className="qe-link" onClick={() => setQual({ bank: qual.bank.filter((_, j) => j !== i) })}>
                    Remove from this project
                  </button>
                </div>
              );
            })}

            <div className="qe-bank-row">
              <select value={pick} onChange={(e) => addFromBank(e.target.value)} className="qe-bank-select">
                <option value="">+ Add a question from the bank…</option>
                {(library?.bank || [])
                  .filter((q) => q.active !== false && !usedIds.has(q.id))
                  .map((q) => (
                    <option key={q.id} value={q.id}>{q.text}</option>
                  ))}
              </select>
              {!draft && (
                <button type="button" className="qe-add" onClick={() => setDraft({ text: "", optionsText: "Yes, No" })}>
                  + Create new question
                </button>
              )}
            </div>

            {draft && (
              <div className="qe-custom">
                <input
                  className="qe-custom-text"
                  placeholder="Question, e.g. Do you wear a uniform at work?"
                  value={draft.text}
                  onChange={(e) => setDraft({ ...draft, text: e.target.value })}
                />
                <input
                  className="qe-custom-options"
                  placeholder="Answer options, comma-separated, e.g. Yes, No"
                  value={draft.optionsText}
                  onChange={(e) => setDraft({ ...draft, optionsText: e.target.value })}
                />
                {bankError && <small className="qe-warn">{bankError}</small>}
                <div className="qe-bank-row">
                  <button type="button" className="qe-add" onClick={saveDraft}>Save to question bank</button>
                  <button type="button" className="qe-link" onClick={() => { setDraft(null); setBankError(""); }}>Cancel</button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      <div className="qe-routing">
        <label className="qe-toggle">
          <input
            type="checkbox"
            checked={Boolean(formData.routingEnabled)}
            onChange={(e) => setFormData((prev) => ({ ...prev, routingEnabled: e.target.checked }))}
          />
          Accept routed respondents (from router links and other surveys' screen-outs)
        </label>
        {formData.routingEnabled && (
          <div className="pp-field qe-priority">
            <label>Routing priority</label>
            <input
              type="number"
              min="1"
              max="999"
              value={formData.routingPriority ?? ""}
              placeholder="1 = offered first"
              onChange={(e) => setFormData((prev) => ({ ...prev, routingPriority: e.target.value }))}
            />
          </div>
        )}
        {library && !library.routingEnabled && (
          <small className="pp-hint">Routing is switched off on the server (SURVEY_ROUTING_ENABLED); this setting takes effect when it is on.</small>
        )}
        {library && (
          <small className="pp-hint">
            Country check {library.countryRoutingEnabled ? "on" : "off"}: respondents are matched by the country of their IP address.
            Up to {library.maxAttempts} surveys per respondent.
          </small>
        )}
      </div>
    </fieldset>
  );
}
