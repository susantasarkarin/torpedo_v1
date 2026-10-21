import { useEffect, useState } from "react";
import { buildApiUrl } from "../../config";
import { authFetch } from "../../utils/api";
import "./QualificationEditor.css";

const GENDERS = [
  { value: "m", label: "Male" },
  { value: "f", label: "Female" },
];

const NCCS_GRADES = ["A1", "A2", "A3", "B1", "B2", "C1", "C2", "D1", "D2", "E1", "E2", "E3"];

// Targeting profile (backend/services/respondent_profile.py). Panel members' answers
// come from their panel profile; other traffic is asked on the landing page.
const PLACE_FIELDS = [
  { key: "states", label: "States", hint: "comma-separated, e.g. Maharashtra, Karnataka" },
  { key: "cities", label: "Cities", hint: "comma-separated, e.g. Mumbai, Delhi, Bengaluru" },
  { key: "zipPrefixes", label: "PIN / postcode starts with", hint: "comma-separated, e.g. 400, 110" },
];

const EMPTY_QUAL = {
  enabled: false, ageMin: "", ageMax: "", ageRanges: [], panelQuestions: [], genders: [], employment: [], occupation: [], bank: [], custom: [],
  states: "", cities: "", zipPrefixes: "", childrenMin: "", childrenMax: "", childAgeMin: "", childAgeMax: "", nccs: [],
};

const asText = (v) => (Array.isArray(v) ? v.join(", ") : v || "");

export const COUNTRIES = [
  { value: "IN", label: "India" },
  { value: "UK", label: "United Kingdom" },
  { value: "US", label: "United States" },
];

// Age ranges; older projects have a single ageMin / ageMax, shown as one range.
const rangesOf = (q) => (Array.isArray(q.ageRanges) && q.ageRanges.length
  ? q.ageRanges
  : (q.ageMin !== "" && q.ageMin != null) || (q.ageMax !== "" && q.ageMax != null)
    ? [{ min: q.ageMin ?? "", max: q.ageMax ?? "" }]
    : []);

const authHeaders = (extra = {}) => ({ Authorization: localStorage.getItem("session_id") || "", ...extra });

// Project-level qualification criteria + routing settings (survey routing engine).
// Value lives on the project: formData.qualification, formData.routingEnabled, formData.routingPriority.
export default function QualificationEditor({ formData, setFormData }) {
  const [library, setLibrary] = useState(null);
  const [pick, setPick] = useState("");
  const [draft, setDraft] = useState(null); // {text, options} while creating a bank question
  const [bankError, setBankError] = useState("");
  const [rfq, setRfq] = useState(null); // suggestion read from the RFQ email
  const [rfqBusy, setRfqBusy] = useState(false);
  const [panelQs, setPanelQs] = useState(null); // SurveyFieldwork Panel profiling questions
  const [panelPick, setPanelPick] = useState("");
  const qual = { ...EMPTY_QUAL, ...(formData.qualification || {}) };
  const country = String(formData.countryCode || "IN").toUpperCase();
  const india = country === "IN";
  const ageRanges = rangesOf(qual);
  const setRanges = (list) => setQual({ ageRanges: list, ageMin: "", ageMax: "" });

  useEffect(() => {
    authFetch(buildApiUrl("/api/routing/panel-questions"), { headers: authHeaders() })
      .then((r) => (r.ok ? r.json() : { questions: [], available: false }))
      .then(setPanelQs)
      .catch(() => setPanelQs({ questions: [], available: false }));
  }, []);
  const panelById = Object.fromEntries((panelQs?.questions || []).map((q) => [q.id, q]));
  const panelText = (q) => (q.countries[country] || q.countries.IN || Object.values(q.countries)[0]);
  const pickedPanel = qual.panelQuestions || [];
  const panelSections = [...new Set((panelQs?.questions || []).map((q) => q.section))];

  const readRfq = async () => {
    setRfqBusy(true);
    setRfq(null);
    try {
      const qs = new URLSearchParams({ projectName: formData.projectName || "", rfqId: formData.rfqId || "", surveyNo: formData.surveyNo || "" });
      const res = await authFetch(buildApiUrl(`/api/routing/qualification-from-rfq?${qs}`), { headers: authHeaders() });
      setRfq(res.ok ? await res.json() : { found: false, message: "Could not read the RFQ email." });
    } catch {
      setRfq({ found: false, message: "Could not read the RFQ email." });
    }
    setRfqBusy(false);
  };

  const applyRfq = () => {
    const found = { ...(rfq?.qualification || {}) };
    if (!india) delete found.nccs;
    if (found.ageMin != null || found.ageMax != null) {
      found.ageRanges = [{ min: found.ageMin ?? "", max: found.ageMax ?? "" }];
      found.ageMin = "";
      found.ageMax = "";
    }
    setFormData((prev) => ({
      ...prev,
      loi: prev.loi || (rfq?.loi ? String(rfq.loi) : prev.loi),
      clientIR: prev.clientIR || (rfq?.ir ? String(rfq.ir) : prev.clientIR),
      qualification: { ...EMPTY_QUAL, ...(prev.qualification || {}), ...found, enabled: true },
    }));
    setRfq(null);
  };

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

      <div className="qe-bank-row">
        <button type="button" className="qe-add" onClick={readRfq} disabled={rfqBusy || !(formData.projectName || formData.rfqId)}>
          {rfqBusy ? "Reading the RFQ email…" : "Fill from RFQ email"}
        </button>
      </div>
      {rfq && !rfq.found && <small className="qe-warn">{rfq.message}</small>}
      {rfq && rfq.found && (
        <div className="qe-custom">
          <strong className="qe-custom-title">From: {rfq.subject}</strong>
          {(rfq.evidence || []).length === 0 && <small className="qe-warn">No age, gender, NCCS, children or cities found in it.</small>}
          <ul>
            {(rfq.evidence || []).filter((e) => india || e.field !== "nccs").map((e) => (
              <li key={e.field}>
                <strong>{e.field}:</strong> {typeof e.value === "object" ? JSON.stringify(e.value) : String(e.value)}
                {e.from && <small> (“{e.from}”)</small>}
              </li>
            ))}
            {rfq.loi && <li><strong>LOI:</strong> {rfq.loi} min</li>}
            {rfq.ir && <li><strong>IR:</strong> {rfq.ir}%</li>}
          </ul>
          {(rfq.notes || []).length > 0 && (
            <>
              <small className="pp-hint">Also in the RFQ, not checked automatically (add as bank questions if needed):</small>
              <ul>{rfq.notes.map((n) => <li key={n}><small>{n}</small></li>)}</ul>
            </>
          )}
          <div className="qe-bank-row">
            <button type="button" className="qe-add" onClick={applyRfq} disabled={!(rfq.evidence || []).length}>Apply to this project</button>
            <button type="button" className="qe-link" onClick={() => setRfq(null)}>Dismiss</button>
          </div>
          <small className="pp-hint">Applying fills the fields below; check them, then save the project.</small>
        </div>
      )}

      {qual.enabled && (
        <div className="qe-body">
          <div className="qe-group">
            <span className="qe-group-label">Age ranges <small>(any of them qualifies; none = any age)</small></span>
            {ageRanges.map((r, i) => (
              <div key={i} className="qe-range">
                <input type="number" min="13" max="99" placeholder="from" value={r.min ?? ""}
                  onChange={(e) => setRanges(ageRanges.map((x, j) => (j === i ? { ...x, min: e.target.value } : x)))} />
                <span>to</span>
                <input type="number" min="13" max="120" placeholder="to" value={r.max ?? ""}
                  onChange={(e) => setRanges(ageRanges.map((x, j) => (j === i ? { ...x, max: e.target.value } : x)))} />
                <button type="button" className="qe-link" onClick={() => setRanges(ageRanges.filter((_, j) => j !== i))}>Remove</button>
              </div>
            ))}
            <button type="button" className="qe-add" onClick={() => setRanges([...ageRanges, { min: "", max: "" }])}>+ Add age range</button>
          </div>

          <div className="qe-group">
            <span className="qe-group-label">
              Panel profiling questions <small>(what panel members answered at signup; others are asked on the survey page)</small>
            </span>
            {panelQs && !panelQs.available && <small className="qe-warn">The panel question list could not be loaded just now.</small>}
            {pickedPanel.map((ref, i) => {
              const q = panelById[ref.id];
              const per = q && panelText(q);
              const chosen = (ref.qualifying || []).map(String);
              return (
                <div key={ref.id} className="qe-custom">
                  <strong className="qe-custom-title">
                    {per ? per.text : ref.id} <small>({ref.id}{q ? (q.type === "multi" ? ", any ticked answer" : ", one answer") : ""})</small>
                  </strong>
                  <div className="qe-custom-qualifying">
                    <span>Qualifying answers:</span>
                    {(per?.options || []).map((o) => {
                      const on = chosen.includes(String(o.code));
                      return (
                        <label key={o.code} className="qe-chip">
                          <input type="checkbox" checked={on} onChange={() => {
                            const list = [...pickedPanel];
                            list[i] = { ...ref, qualifying: on ? chosen.filter((c) => c !== String(o.code)) : [...chosen, String(o.code)] };
                            setQual({ panelQuestions: list });
                          }} />
                          {o.label}
                        </label>
                      );
                    })}
                  </div>
                  {!chosen.length && <small className="qe-warn">Tick at least one qualifying answer, or this question is ignored.</small>}
                  <button type="button" className="qe-link" onClick={() => setQual({ panelQuestions: pickedPanel.filter((_, j) => j !== i) })}>
                    Remove from this project
                  </button>
                </div>
              );
            })}
            <div className="qe-bank-row">
              <select className="qe-bank-select" value={panelPick} onChange={(e) => {
                const id = e.target.value;
                if (id && !pickedPanel.some((p) => p.id === id)) setQual({ panelQuestions: [...pickedPanel, { id, qualifying: [] }] });
                setPanelPick("");
              }}>
                <option value="">+ Add a panel question…</option>
                {panelSections.map((section) => (
                  <optgroup key={section} label={section}>
                    {(panelQs?.questions || [])
                      .filter((q) => q.section === section && q.countries[country] && !pickedPanel.some((p) => p.id === q.id))
                      .map((q) => <option key={q.id} value={q.id}>{panelText(q).text}</option>)}
                  </optgroup>
                ))}
              </select>
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

          {PLACE_FIELDS.map((f) => (
            <div key={f.key} className="pp-field">
              <label>{f.label} <small>(empty = any)</small></label>
              <input type="text" placeholder={f.hint} value={asText(qual[f.key])} onChange={(e) => setQual({ [f.key]: e.target.value })} />
            </div>
          ))}

          <div className="pp-form-row">
            <div className="pp-field">
              <label>Children under 18: at least</label>
              <input type="number" min="0" max="10" value={qual.childrenMin ?? ""} onChange={(e) => setQual({ childrenMin: e.target.value })} />
            </div>
            <div className="pp-field">
              <label>at most</label>
              <input type="number" min="0" max="10" value={qual.childrenMax ?? ""} onChange={(e) => setQual({ childrenMax: e.target.value })} />
            </div>
          </div>
          <div className="pp-form-row">
            <div className="pp-field">
              <label>Has a child aged from</label>
              <input type="number" min="0" max="17" value={qual.childAgeMin ?? ""} onChange={(e) => setQual({ childAgeMin: e.target.value })} />
            </div>
            <div className="pp-field">
              <label>to</label>
              <input type="number" min="0" max="17" value={qual.childAgeMax ?? ""} onChange={(e) => setQual({ childAgeMax: e.target.value })} />
            </div>
          </div>

          {india && (
            <div className="qe-group">
              <span className="qe-group-label">NCCS <small>(India only; none ticked = any)</small></span>
              {NCCS_GRADES.map((g) => (
                <label key={g} className="qe-chip">
                  <input type="checkbox" checked={(qual.nccs || []).includes(g)} onChange={() => toggle("nccs", g)} />
                  {g}
                </label>
              ))}
            </div>
          )}

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
          Accept routed respondents and panel members (router links, other surveys' screen-outs, and SurveyFieldwork Panel members before CPX / Cint)
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
