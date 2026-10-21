import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { buildApiUrl } from "../../config";
import { authFetch } from "../../utils/api";
import { notify } from "../../utils/notify";
import QualificationEditor, { COUNTRIES } from "./QualificationEditor";
import "./ProjectsPage.css";

const authHeaders = (extra = {}) => ({ Authorization: localStorage.getItem("session_id") || "", ...extra });

// Operations -> Projects -> <project> -> Qualifications: who may enter this survey.
// Country, age ranges, gender, NCCS (India), the panel's profiling questions,
// places / children, bank questions, and whether it takes routed respondents
// and panel members. Panel members are matched on their panel profile; others
// are asked on the survey landing page. Saves only these fields.
export default function ProjectQualifications() {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const [formData, setFormData] = useState(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    authFetch(buildApiUrl(`/projects/${encodeURIComponent(projectId)}`), { headers: authHeaders() })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`Project not found (${r.status})`))))
      .then((d) => setFormData(d.project))
      .catch((e) => setError(e.message));
  }, [projectId]);

  const save = async () => {
    setSaving(true);
    setError("");
    try {
      const body = {
        countryCode: formData.countryCode || "",
        qualification: formData.qualification || {},
        routingEnabled: Boolean(formData.routingEnabled),
        routingPriority: formData.routingPriority ?? "",
        loi: formData.loi ?? "",
        clientIR: formData.clientIR ?? "",
      };
      const res = await authFetch(buildApiUrl(`/projects/${encodeURIComponent(projectId)}`), {
        method: "PUT",
        headers: authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `Save failed (${res.status})`);
      notify("Qualifications saved", "success");
      navigate("/admin/operations/projects");
    } catch (e) {
      setError(e.message);
    }
    setSaving(false);
  };

  if (error && !formData) return <div className="pp-container"><p className="qe-warn">{error}</p></div>;
  if (!formData) return <div className="pp-container"><p>Loading…</p></div>;

  const country = String(formData.countryCode || "").toUpperCase();
  return (
    <div className="pp-container">
      <button type="button" className="pp-act-btn" onClick={() => navigate("/admin/operations/projects")} title="Back to projects">
        <ArrowLeft size={14} /> Projects
      </button>
      <h2>Qualifications: {formData.projectName}</h2>
      <p className="pp-hint">
        Survey {formData.surveyNo} · {formData.client || "no client"}. Panel members are matched on their panel profile;
        everyone else is asked these questions on the survey page, then sent to the best-matching survey.
      </p>

      <fieldset className="pp-fieldset">
        <legend>Country</legend>
        <select value={COUNTRIES.some((c) => c.value === country) ? country : country || ""}
          onChange={(e) => setFormData((prev) => ({ ...prev, countryCode: e.target.value }))}>
          {!COUNTRIES.some((c) => c.value === country) && <option value={country}>{country || "Not set"}</option>}
          {COUNTRIES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
        </select>
        <small className="pp-hint"> Respondents are matched by the country of their IP address. NCCS applies to India only.</small>
      </fieldset>

      <QualificationEditor formData={formData} setFormData={setFormData} />

      {error && <p className="qe-warn">{error}</p>}
      <div className="qe-bank-row" style={{ marginTop: 12 }}>
        <button type="button" className="pp-btn-primary" onClick={save} disabled={saving}>
          {saving ? "Saving…" : "Save qualifications"}
        </button>
        <button type="button" className="qe-link" onClick={() => navigate("/admin/operations/projects")}>Cancel</button>
      </div>
    </div>
  );
}
