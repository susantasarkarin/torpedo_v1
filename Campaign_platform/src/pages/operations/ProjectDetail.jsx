import React, { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import "./ProjectDetail.css";
import { buildApiUrl } from "../../config"

function ProjectDetail() {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const [project, setProject] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState("study");

  const getEntryLinkTemplate = () => {
    const base = (typeof window !== "undefined" && window.location?.origin)
      ? window.location.origin.replace(/\/$/, "")
      : "https://torpedo.cogentixresearch.com";
    return `${base}/takesurvey?api=dalse&vid=vendor_id&cc=country_code&rid=respondent_id`;
  };

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
        console.error("❌ Project fetch failed:", err.message);
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    fetchProject();
  }, [projectId, navigate]);

  const renderStudySpecification = () => (
    <div className="detail-section">
      <h3>Study Specification</h3>
      <div className="spec-grid">
        <div className="spec-item">
          <label>Project Name:</label>
          <p>{project.projectName || "—"}</p>
        </div>
        <div className="spec-item">
          <label>Survey No:</label>
          <p>{project.surveyNo || "—"}</p>
        </div>
        <div className="spec-item">
          <label>Client:</label>
          <p>{project.client || "—"}</p>
        </div>
        <div className="spec-item">
          <label>Project Status:</label>
          <p>{project.projectStatus || "—"}</p>
        </div>
        <div className="spec-item">
          <label>Sales Person:</label>
          <p>{project.salesPerson || "—"}</p>
        </div>
        <div className="spec-item">
          <label>Project Value:</label>
          <p>{project.projectValue || "—"}</p>
        </div>
        <div className="spec-item">
          <label>RFQ Details:</label>
          <p>{project.rfqDetails || "—"}</p>
        </div>
      </div>
    </div>
  );

  const renderTrafficDetails = () => (
    <div className="detail-section">
      <h3>Traffic Details</h3>
      <div className="spec-grid">
        <div className="spec-item">
          <label>Entry Link:</label>
          <p>
            {getEntryLinkTemplate() ? (
              <a href={getEntryLinkTemplate()} target="_blank" rel="noopener noreferrer">
                {getEntryLinkTemplate()}
              </a>
            ) : (
              "—"
            )}
          </p>
        </div>
        <div className="spec-item">
          <label>Live Link:</label>
          <p>
            {project.liveLink ? (
              <a href={project.liveLink} target="_blank" rel="noopener noreferrer">
                {project.liveLink}
              </a>
            ) : (
              "—"
            )}
          </p>
        </div>
        <div className="spec-item">
          <label>Complete Page:</label>
          <p>
            {project.completePage ? (
              <a href={project.completePage} target="_blank" rel="noopener noreferrer">
                {project.completePage}
              </a>
            ) : (
              "—"
            )}
          </p>
        </div>
        <div className="spec-item">
          <label>Terminate Page:</label>
          <p>
            {project.terminatePage ? (
              <a href={project.terminatePage} target="_blank" rel="noopener noreferrer">
                {project.terminatePage}
              </a>
            ) : (
              "—"
            )}
          </p>
        </div>
        <div className="spec-item">
          <label>Quota Full Page:</label>
          <p>
            {project.quotaFullPage ? (
              <a href={project.quotaFullPage} target="_blank" rel="noopener noreferrer">
                {project.quotaFullPage}
              </a>
            ) : (
              "—"
            )}
          </p>
        </div>
        <div className="spec-item">
          <label>Vendor Name:</label>
          <p>{project.vendorName || "—"}</p>
        </div>
      </div>
    </div>
  );

  const renderProjectStatistics = () => (
    <div className="detail-section">
      <h3>Project Statistics</h3>
      <div className="spec-grid">
        <div className="spec-item">
          <label>Total Completes Required:</label>
          <p>{project.totalCompletesRequired || "—"}</p>
        </div>
        <div className="spec-item">
          <label>LOI (Minutes):</label>
          <p>{project.loi || "—"}</p>
        </div>
        <div className="spec-item">
          <label>Client IR (%):</label>
          <p>{project.clientIR || "—"}</p>
        </div>
        <div className="spec-item">
          <label>CPI:</label>
          <p>{project.cpi || "—"}</p>
        </div>
        <div className="spec-item">
          <label>Total Completes:</label>
          <p>{project.totalCompletes || "—"}</p>
        </div>
        <div className="spec-item">
          <label>Total Respondents:</label>
          <p>{project.totalRespondents || "—"}</p>
        </div>
        <div className="spec-item">
          <label>Actual Completes:</label>
          <p>{project.actualCompletes || "—"}</p>
        </div>
        <div className="spec-item">
          <label>Actual IR (%):</label>
          <p>{project.actualIR || "—"}</p>
        </div>
        <div className="spec-item">
          <label>Launch Date:</label>
          <p>{project.projectLaunchDate || "—"}</p>
        </div>
        <div className="spec-item">
          <label>Close Date:</label>
          <p>{project.projectCloseDate || "—"}</p>
        </div>
      </div>
    </div>
  );

  if (loading) {
    return (
      <div className="detail-container">
        <div className="loading">Loading project details...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="detail-container">
        <div className="error">Error: {error}</div>
        <button onClick={() => navigate(-1)} className="back-button">
          ← Back to Projects
        </button>
      </div>
    );
  }

  if (!project) {
    return (
      <div className="detail-container">
        <div className="error">Project not found</div>
        <button onClick={() => navigate(-1)} className="back-button">
          ← Back to Projects
        </button>
      </div>
    );
  }

  return (
    <div className="detail-container">
      <div className="detail-header">
        <div>
          <button onClick={() => navigate(-1)} className="back-button">
            ← Back to Projects
          </button>
          <h1>{project.projectName}</h1>
          <p className="subtitle">Survey No: {project.surveyNo || "—"}</p>
        </div>
      </div>

      <div className="detail-tabs">
        <button
          className={`tab-button ${activeTab === "study" ? "active" : ""}`}
          onClick={() => setActiveTab("study")}
        >
          Study Specification
        </button>
        <button
          className={`tab-button ${activeTab === "traffic" ? "active" : ""}`}
          onClick={() => setActiveTab("traffic")}
        >
          Traffic Details
        </button>
        <button
          className={`tab-button ${activeTab === "stats" ? "active" : ""}`}
          onClick={() => setActiveTab("stats")}
        >
          Project Statistics
        </button>
      </div>

      <div className="detail-body">
        {activeTab === "study" && renderStudySpecification()}
        {activeTab === "traffic" && renderTrafficDetails()}
        {activeTab === "stats" && renderProjectStatistics()}
      </div>
    </div>
  );
}

export default ProjectDetail;
