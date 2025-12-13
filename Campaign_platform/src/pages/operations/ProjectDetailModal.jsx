import React, { useState } from "react";
import "./ProjectDetailModal.css";

function ProjectDetailModal({ project, onClose }) {
  const [activeTab, setActiveTab] = useState("study");

  if (!project) return null;

  const renderStudySpecification = () => (
    <div className="modal-section">
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
          <label>Industry:</label>
          <p>{project.industry || "—"}</p>
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
    <div className="modal-section">
      <h3>Traffic Details</h3>
      <div className="spec-grid">
        <div className="spec-item">
          <label>Test Link:</label>
          <p>
            {project.testLink ? (
              <a href={project.testLink} target="_blank" rel="noopener noreferrer">
                {project.testLink}
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
    <div className="modal-section">
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
          <label>Difference (Days):</label>
          <p>{project.differenceDays || "—"}</p>
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

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>{project.projectName}</h2>
          <button className="modal-close" onClick={onClose}>
            ✕
          </button>
        </div>

        <div className="modal-tabs">
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

        <div className="modal-body">
          {activeTab === "study" && renderStudySpecification()}
          {activeTab === "traffic" && renderTrafficDetails()}
          {activeTab === "stats" && renderProjectStatistics()}
        </div>
      </div>
    </div>
  );
}

export default ProjectDetailModal;
