import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, CheckCircle2, XCircle } from "lucide-react";
import { buildApiUrl } from "../../config";
import { authFetch } from "../../utils/api";
import { notify } from "../../utils/notify";
import QualificationEditor, { COUNTRIES } from "./QualificationEditor";
import "./ProjectsPage.css";

const authHeaders = (extra = {}) => ({ Authorization: localStorage.getItem("session_id") || "", ...extra });

const SAVED_FIELDS = ["countryCode", "qualification", "routingEnabled", "routingPriority", "loi", "clientIR"];
const snapshot = (d) => JSON.stringify(SAVED_FIELDS.map((k) => d?.[k] ?? null));

// What the server checks before it offers this project to a Panel member
// (services/survey_routing.py routable_projects / eligible_projects).
function panelChecks(p, savedRouting) {
  const status = String(p.projectStatus || "").toLowerCase();
  return [
    { ok: status === "live", label: "Project status is Live", fix: `Status is "${p.projectStatus || "not set"}"; set it to Live on the project.` },
    { ok: Boolean(p.liveLink || p.clientLink), label: "Live link is set", fix: "Add the client's live link on the project." },
    { ok: Boolean(p.countryCode), label: `Country is set${p.countryCode ? ` (${String(p.countryCode).toUpperCase()})` : ""}`, fix: "Pick a country below; members are matched by IP country." },
    {
      ok: p.routingEnabled !== false && savedRouting,
      label: "Accepts routed respondents and panel members",
      fix: p.routingEnabled !== false ? "Ticked but not saved yet: click Save qualifications." : "Tick it in Qualification & routing below.",
    },
  ];
}

// Operations -> Projects -> <project> -> Qualifications: who may enter this survey.
// Country, age ranges, gender, NCCS (India), the panel's profiling questions,
// places / children, bank questions, and whether it takes routed respondents
// and panel members. Panel members are matched on their panel profile; others
// are asked on the survey landing page. Saves only these fields.
export default function ProjectQualifications() {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const [formData, setFormData] = useState(null);
  const [saved, setSaved] = useState(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    authFetch(buildApiUrl(`/projects/${encodeURIComponent(projectId)}`), { headers: authHeaders() })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`Project not found (${r.status})`))))
      .then((d) => { setFormData(d.project); setSaved(d.project); })
      .catch((e) => setError(e.message));
  }, [projectId]);

  const back = () => navigate("/admin/operations/projects");

  const save = async () => {
    setSaving(true);
    setError("");
    try {
      const body = {
        countryCode: formData.countryCode || "",
        qualification: formData.qualification || {},
        routingEnabled: formData.routingEnabled !== false,
        routingPriority: formData.routingPriority ?? "",
        loi: formData.loi ?? "",
        clientIR: formData.clientIR ?? "",
        // saved here = the team's own: automatic filling from the RFQ email stops for this project
        qualificationManual: true,
      };
      const res = await authFetch(buildApiUrl(`/projects/${encodeURIComponent(projectId)}`), {
        method: "PUT",
        headers: authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `Save failed (${res.status})`);
      notify("Qualifications saved", "success");
      back();
    } catch (e) {
      setError(e.message);
    }
    setSaving(false);
  };

  if (error && !formData) return <div className="pp-container"><p className="qe-warn">{error}</p></div>;
  if (!formData) return <div className="pp-container"><div className="loading-spinner" /></div>;

  const country = String(formData.countryCode || "").toUpperCase();
  const dirty = snapshot(formData) !== snapshot(saved);
  const checks = panelChecks(formData, saved?.routingEnabled !== false);
  const ready = checks.every((c) => c.ok);

  return (
    <div className="pp-container qp-page">
      <button type="button" className="qp-back" onClick={back}>
        <ArrowLeft size={16} /> Back to projects
      </button>

      <header className="qp-head">
        <h1 className="cx-page-title">Qualifications</h1>
        <p className="qp-project">{formData.projectName}</p>
        <p className="qp-meta">
          Survey <strong>{formData.surveyNo}</strong> · {formData.client || "no client"}
        </p>
        <p className="pp-hint">
          Panel members are matched on their panel profile; everyone else is asked these questions on the survey page,
          then sent to the best-matching survey.
        </p>
      </header>

      <section className={`qp-ready ${ready ? "is-ready" : ""}`}>
        <h2>{ready ? "Panel members can be sent to this survey" : "Panel members will not get this survey yet"}</h2>
        <ul>
          {checks.map((c) => (
            <li key={c.label} className={c.ok ? "ok" : "bad"}>
              {c.ok ? <CheckCircle2 size={16} /> : <XCircle size={16} />}
              <span>{c.label}{!c.ok && <small> {c.fix}</small>}</span>
            </li>
          ))}
        </ul>
        <small className="pp-hint">
          Also needed per member: same IP country, quota not yet full, and their profile matches any qualifications below.
          Each member gets one try at our projects, then CPX / Cint.
        </small>
      </section>

      <p className="qp-source">
        {formData.qualificationManual
          ? "Set by hand: automatic filling from the RFQ email is off for this project."
          : formData.qualificationSource?.from === "rfq_email"
            ? `Filled automatically from the RFQ email "${formData.qualificationSource.subject || ""}". Check it; saving here makes it yours and stops automatic filling.`
            : "No RFQ email with a target group found yet; it is checked every 30 minutes. Fill in by hand below if the email does not have it."}
      </p>

      <fieldset className="pp-fieldset">
        <legend>Country</legend>
        <div className="qp-row">
          <select className="qp-select" value={country} aria-label="Country"
            onChange={(e) => setFormData((prev) => ({ ...prev, countryCode: e.target.value }))}>
            {!COUNTRIES.some((c) => c.value === country) && <option value={country}>{country || "Not set"}</option>}
            {COUNTRIES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
          </select>
          <small className="pp-hint">Respondents are matched by the country of their IP address. NCCS applies to India only.</small>
        </div>
      </fieldset>

      <QualificationEditor formData={formData} setFormData={setFormData} />

      <div className="qp-savebar">
        {error && <p className="qe-warn">{error}</p>}
        {dirty && !error && <span className="qp-dirty">Unsaved changes</span>}
        <button type="button" className="qp-cancel" onClick={back}>Cancel</button>
        <button type="button" className="pp-btn-primary" onClick={save} disabled={saving || !dirty}>
          {saving ? "Saving…" : "Save qualifications"}
        </button>
      </div>
    </div>
  );
}
