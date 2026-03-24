import React, { useState, useEffect, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  ArrowLeft,
  Globe,
  ExternalLink,
  Copy,
  Check,
  Target,
  Clock,
  Percent,
  DollarSign,
  CheckCircle,
  Users,
  TrendingUp,
  Award,
  CalendarDays,
  Link2,
  Building2,
  User,
  Briefcase,
  ClipboardList,
} from "lucide-react";
import "./ProjectDetail.css";
import { buildApiUrl } from "../../config";

function ProjectDetail() {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const [project, setProject] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [copiedField, setCopiedField] = useState(null);

  const getProjectCallbackBase = () => {
    if (typeof window !== "undefined" && window.location?.origin) {
      return window.location.origin.replace(/\/$/, "");
    }
    return "https://surveyfieldwork.com";
  };

  const getEntryLinkTemplate = () => {
    const base = getProjectCallbackBase();
    const vid = project?.vendorId || "{VID}";
    const cc = project?.countryCode || "{CC}";
    return `${base}/takesurvey?api=false&vid=${vid}&cc=${cc}&pid=${projectId}&rid={RID}`;
  };

  const copyToClipboard = useCallback((text, fieldName) => {
    navigator.clipboard.writeText(text).then(() => {
      setCopiedField(fieldName);
      setTimeout(() => setCopiedField(null), 2000);
    });
  }, []);

  useEffect(() => {
    const fetchProject = async () => {
      const sessionId = localStorage.getItem("session_id");
      if (!sessionId) {
        navigate("/admin/login");
        return;
      }

      try {
        const res = await fetch(buildApiUrl(`/projects/`), {
          headers: {
            "Content-Type": "application/json",
            Authorization: sessionId,
          },
        });

        if (res.status === 401) {
          alert("Session expired. Please login again.");
          localStorage.removeItem("session_id");
          navigate("/admin/login");
          return;
        }

        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to load project");

        const projects = data.projects || [];
        const selectedProject = projects.find((p) => p._id === projectId);

        if (selectedProject) {
          setProject(selectedProject);
        } else {
          setError("Project not found");
        }
      } catch (err) {
        console.error("Project fetch failed:", err.message);
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    fetchProject();
  }, [projectId, navigate]);

  const StatusBadge = ({ status }) => {
    const s = (status || "").toLowerCase();
    const cls = s === "live" ? "status-live" : s === "pause" ? "status-pause" : "status-close";
    return <span className={`pd-status-badge ${cls}`}>{status || "—"}</span>;
  };

  const UrlRow = ({ label, url, fieldKey, icon: Icon }) => {
    const isCopied = copiedField === fieldKey;
    return (
      <div className="pd-url-row">
        <div className="pd-url-label">
          {Icon && <Icon size={13} />}
          <span>{label}</span>
        </div>
        <div className="pd-url-value-wrap">
          {url ? (
            <>
              <a className="pd-url-value" href={url} target="_blank" rel="noopener noreferrer" title={url}>
                {url.length > 80 ? url.substring(0, 80) + "…" : url}
              </a>
              <div className="pd-url-actions">
                <button className="pd-icon-btn" onClick={() => copyToClipboard(url, fieldKey)} title={isCopied ? "Copied!" : "Copy"}>
                  {isCopied ? <Check size={13} className="pd-copied" /> : <Copy size={13} />}
                </button>
                <a className="pd-icon-btn" href={url} target="_blank" rel="noopener noreferrer" title="Open">
                  <ExternalLink size={13} />
                </a>
              </div>
            </>
          ) : (
            <span className="pd-url-empty">Not configured</span>
          )}
        </div>
      </div>
    );
  };

  const StatCard = ({ label, value, icon: Icon, color, sub }) => (
    <div className="pd-stat-card">
      <div className="pd-stat-icon" style={{ backgroundColor: color + "14", color }}>
        <Icon size={16} />
      </div>
      <div className="pd-stat-body">
        <span className="pd-stat-value">{value ?? "—"}</span>
        <span className="pd-stat-label">{label}</span>
        {sub && <span className="pd-stat-sub">{sub}</span>}
      </div>
    </div>
  );

  if (loading) {
    return <div className="pd-container"><div className="pd-loading">Loading…</div></div>;
  }
  if (error || !project) {
    return (
      <div className="pd-container">
        <div className="pd-error">{error || "Project not found"}</div>
        <button onClick={() => navigate(-1)} className="pd-back-btn"><ArrowLeft size={14} /> Back</button>
      </div>
    );
  }

  const totalRequired = Number(project.totalCompletesRequired) || 0;
  const actualCompletes = Number(project.actualCompletes) || 0;
  const progressPct = totalRequired > 0 ? Math.min(100, Math.round((actualCompletes / totalRequired) * 100)) : 0;
  const actualIR = Number(project.actualIR) || 0;
  const clientIR = Number(project.clientIR) || 0;
  const irColor = actualIR >= clientIR && clientIR > 0 ? "#16a34a" : actualIR >= clientIR * 0.7 ? "#d97706" : "#dc2626";

  return (
    <div className="pd-container">
      {/* ── Top bar: back + title + chips ── */}
      <div className="pd-topbar">
        <button onClick={() => navigate(-1)} className="pd-back-btn"><ArrowLeft size={14} /> Back</button>
        <div className="pd-topbar-main">
          <h1 className="pd-title">{project.projectName}</h1>
          <div className="pd-meta-chips">
            <StatusBadge status={project.projectStatus} />
            <span className="pd-chip"><ClipboardList size={12} /> #{project.surveyNo || "—"}</span>
            <span className="pd-chip"><Building2 size={12} /> {project.client || "—"}</span>
            {project.vendorName && <span className="pd-chip"><Briefcase size={12} /> {project.vendorName}</span>}
            {project.salesPerson && <span className="pd-chip"><User size={12} /> {project.salesPerson}</span>}
            {project.projectValue && <span className="pd-chip"><DollarSign size={12} /> ${Number(project.projectValue).toLocaleString()}</span>}
          </div>
        </div>
      </div>

      {/* ── Stats strip (8 cards in one row) ── */}
      <div className="pd-stats-strip">
        <StatCard label="Required" value={project.totalCompletesRequired || "—"} icon={Target} color="#6366f1" />
        <StatCard label="LOI (min)" value={project.loi || "—"} icon={Clock} color="#8b5cf6" />
        <StatCard label="Client IR" value={project.clientIR ? `${project.clientIR}%` : "—"} icon={Percent} color="#0ea5e9" />
        <StatCard label="CPI" value={project.cpi ? `$${project.cpi}` : "—"} icon={DollarSign} color="#10b981" />
        <StatCard label="Completes" value={project.totalCompletes || "—"} icon={CheckCircle} color="#6366f1" />
        <StatCard label="Respondents" value={project.totalRespondents || "—"} icon={Users} color="#8b5cf6" />
        <StatCard label="Actual" value={project.actualCompletes || "—"} icon={Award} color="#10b981" />
        <StatCard label="Actual IR" value={actualIR ? `${actualIR}%` : "—"} icon={TrendingUp} color={irColor} sub={clientIR > 0 ? `Target: ${clientIR}%` : undefined} />
      </div>

      {/* ── Progress bar ── */}
      {totalRequired > 0 && (
        <div className="pd-progress-wrap">
          <div className="pd-progress-header">
            <span>{actualCompletes.toLocaleString()} / {totalRequired.toLocaleString()} completes</span>
            <span className="pd-progress-pct">{progressPct}%</span>
          </div>
          <div className="pd-progress-bar">
            <div className="pd-progress-fill" style={{ width: `${progressPct}%`, backgroundColor: progressPct >= 100 ? "#16a34a" : progressPct >= 50 ? "#6366f1" : "#d97706" }} />
          </div>
        </div>
      )}

      {/* ── Two-column body: left = details, right = URLs ── */}
      <div className="pd-two-col">
        {/* Left column */}
        <div className="pd-col">
          <div className="pd-section">
            <h4 className="pd-section-title">Project Details</h4>
            <div className="pd-kv-grid">
              <div className="pd-kv"><span className="pd-k">Project Name</span><span className="pd-v">{project.projectName || "—"}</span></div>
              <div className="pd-kv"><span className="pd-k">Survey No</span><span className="pd-v mono">{project.surveyNo || "—"}</span></div>
              <div className="pd-kv"><span className="pd-k">Client</span><span className="pd-v">{project.client || "—"}</span></div>
              <div className="pd-kv"><span className="pd-k">Vendor</span><span className="pd-v">{project.vendorName || "—"}</span></div>
              <div className="pd-kv"><span className="pd-k">Sales Person</span><span className="pd-v">{project.salesPerson || "—"}</span></div>
              <div className="pd-kv"><span className="pd-k">Value</span><span className="pd-v">{project.projectValue ? `$${Number(project.projectValue).toLocaleString()}` : "—"}</span></div>
            </div>
          </div>

          <div className="pd-section">
            <h4 className="pd-section-title"><CalendarDays size={14} /> Timeline</h4>
            <div className="pd-kv-grid">
              <div className="pd-kv"><span className="pd-k">Launch Date</span><span className="pd-v">{project.projectLaunchDate || "—"}</span></div>
              <div className="pd-kv"><span className="pd-k">Close Date</span><span className="pd-v">{project.projectCloseDate || "—"}</span></div>
            </div>
          </div>

          {project.rfqDetails && (
            <div className="pd-section">
              <h4 className="pd-section-title">RFQ Details</h4>
              <p className="pd-rfq">{project.rfqDetails}</p>
            </div>
          )}
        </div>

        {/* Right column */}
        <div className="pd-col">
          <div className="pd-section">
            <h4 className="pd-section-title"><Link2 size={14} /> Survey Link</h4>
            <div className="pd-live-link-card">
              <div className="pd-live-link-label">Live Link</div>
              {project.liveLink ? (
                <div className="pd-live-link-row">
                  <a href={project.liveLink} target="_blank" rel="noopener noreferrer" className="pd-live-link-url">{project.liveLink}</a>
                  <button className="pd-copy-btn" onClick={() => copyToClipboard(project.liveLink, "liveLink")}>
                    {copiedField === "liveLink" ? <><Check size={13} /> Copied</> : <><Copy size={13} /> Copy</>}
                  </button>
                </div>
              ) : (
                <span className="pd-url-empty">Not configured</span>
              )}
            </div>
          </div>

          <div className="pd-section">
            <h4 className="pd-section-title"><Globe size={14} /> Entry &amp; Callback URLs</h4>
            <div className="pd-urls-table">
              <UrlRow label="Entry Link" url={getEntryLinkTemplate()} fieldKey="entryLink" icon={Globe} />
              <UrlRow label="Complete" url={project.completePage} fieldKey="completePage" icon={CheckCircle} />
              <UrlRow label="Terminate" url={project.terminatePage} fieldKey="terminatePage" icon={Target} />
              <UrlRow label="Quota Full" url={project.quotaFullPage} fieldKey="quotaFullPage" icon={Users} />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default ProjectDetail;
