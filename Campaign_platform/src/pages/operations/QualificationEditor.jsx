import { useEffect, useState } from "react";
import { buildApiUrl } from "../../config";
import { authFetch } from "../../utils/api";
import "./QualificationEditor.css";

const GENDERS = [
  { value: "m", label: "Male" },
  { value: "f", label: "Female" },
];

const EMPTY_QUAL = { enabled: false, ageMin: "", ageMax: "", genders: [], employment: [], occupation: [], custom: [] };

const newQuestionId = () => `q_${Math.random().toString(36).slice(2, 10)}`;

// Project-level qualification criteria + routing settings (survey routing engine).
// Value lives on the project: formData.qualification, formData.routingEnabled, formData.routingPriority.
export default function QualificationEditor({ formData, setFormData }) {
  const [library, setLibrary] = useState(null);
  const qual = { ...EMPTY_QUAL, ...(formData.qualification || {}) };

  useEffect(() => {
    authFetch(buildApiUrl("/api/routing/question-library"), {
      headers: { Authorization: localStorage.getItem("session_id") || "" },
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => d && setLibrary(d))
      .catch(() => {});
  }, []);

  const setQual = (patch) => setFormData((prev) => ({
    ...prev,
    qualification: { ...EMPTY_QUAL, ...(prev.qualification || {}), ...patch },
  }));

  const toggle = (field, value) => {
    const list = qual[field] || [];
    setQual({ [field]: list.includes(value) ? list.filter((v) => v !== value) : [...list, value] });
  };

  const updateCustom = (index, patch) => {
    const custom = [...qual.custom];
    custom[index] = { ...custom[index], ...patch };
    setQual({ custom });
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
            <span className="qe-group-label">Study-specific questions</span>
            {qual.custom.map((q, i) => (
              <div key={q.id} className="qe-custom">
                <input
                  className="qe-custom-text"
                  placeholder="Question, e.g. Do you wear a uniform at work?"
                  value={q.text}
                  onChange={(e) => updateCustom(i, { text: e.target.value })}
                />
                <input
                  className="qe-custom-options"
                  placeholder="Answer options, comma-separated, e.g. Yes, No"
                  value={(q.options || []).join(", ")}
                  onChange={(e) => {
                    const options = e.target.value.split(",").map((s) => s.trim()).filter(Boolean);
                    updateCustom(i, { options, qualifying: (q.qualifying || []).filter((o) => options.includes(o)) });
                  }}
                />
                <div className="qe-custom-qualifying">
                  <span>Qualifying answers:</span>
                  {(q.options || []).map((o) => (
                    <label key={o} className="qe-chip">
                      <input
                        type="checkbox"
                        checked={(q.qualifying || []).includes(o)}
                        onChange={() => updateCustom(i, {
                          qualifying: (q.qualifying || []).includes(o)
                            ? q.qualifying.filter((x) => x !== o)
                            : [...(q.qualifying || []), o],
                        })}
                      />
                      {o}
                    </label>
                  ))}
                </div>
                <button type="button" className="qe-link" onClick={() => setQual({ custom: qual.custom.filter((_, j) => j !== i) })}>
                  Remove question
                </button>
              </div>
            ))}
            <button
              type="button"
              className="qe-add"
              onClick={() => setQual({ custom: [...qual.custom, { id: newQuestionId(), text: "", options: ["Yes", "No"], qualifying: ["Yes"] }] })}
            >
              + Add question
            </button>
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
