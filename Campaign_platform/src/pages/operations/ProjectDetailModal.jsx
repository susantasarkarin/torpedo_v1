import React, { useState, useEffect } from "react";
import "./ProjectDetailModal.css";
import { buildApiUrl } from "../../config"

function ProjectDetailModal({ project, onClose }) {
  const [activeTab, setActiveTab] = useState("study");
  const [financials, setFinancials] = useState(null);
  const [loadingFinancials, setLoadingFinancials] = useState(false);
  const [creatingInvoice, setCreatingInvoice] = useState(false);
  const [invoiceError, setInvoiceError] = useState(null);
  const [invoiceSuccess, setInvoiceSuccess] = useState(null);

  const token = sessionStorage.getItem("session_token");

  useEffect(() => {
    if (activeTab === "financials" && project?._id) {
      fetchFinancials();
    }
  }, [activeTab, project?._id]);

  const fetchFinancials = async () => {
    setLoadingFinancials(true);
    try {
      const res = await fetch(buildApiUrl(`/operations/projects/${project._id}/financials`), {
        headers: { Authorization: token },
      });
      if (res.ok) {
        const data = await res.json();
        setFinancials(data);
      }
    } catch (err) {
      console.error("Error fetching financials:", err);
    } finally {
      setLoadingFinancials(false);
    }
  };

  const handleCreateInvoice = async () => {
    setCreatingInvoice(true);
    setInvoiceError(null);
    setInvoiceSuccess(null);
    
    try {
      const res = await fetch(buildApiUrl(`/operations/projects/${project._id}/invoice`), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: token,
        },
        body: JSON.stringify({
          tax_rate: 18,
          notes: `Invoice for project: ${project.projectName}`,
        }),
      });
      
      const data = await res.json();
      
      if (res.ok) {
        setInvoiceSuccess(`Invoice ${data.invoice?.invoice_number} created successfully!`);
        fetchFinancials(); // Refresh financials
      } else {
        setInvoiceError(data.detail || "Failed to create invoice");
      }
    } catch (err) {
      setInvoiceError("Error creating invoice: " + err.message);
    } finally {
      setCreatingInvoice(false);
    }
  };

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

  const renderFinancials = () => (
    <div className="modal-section">
      <div className="financials-header">
        <h3>Project Financials</h3>
        <button 
          className="create-invoice-btn"
          onClick={handleCreateInvoice}
          disabled={creatingInvoice}
        >
          {creatingInvoice ? "Creating..." : "+ Create Invoice"}
        </button>
      </div>
      
      {invoiceSuccess && (
        <div className="alert alert-success">{invoiceSuccess}</div>
      )}
      {invoiceError && (
        <div className="alert alert-error">{invoiceError}</div>
      )}
      
      {loadingFinancials ? (
        <p>Loading financials...</p>
      ) : financials ? (
        <>
          <div className="financials-grid">
            {/* Revenue Section */}
            <div className="financial-card revenue">
              <h4>Revenue</h4>
              <div className="financial-item">
                <span>Project Value:</span>
                <span className="value">₹{(financials.project_value || 0).toLocaleString()}</span>
              </div>
              <div className="financial-item">
                <span>Invoiced:</span>
                <span className="value">₹{(financials.invoiced_amount || 0).toLocaleString()}</span>
              </div>
              <div className="financial-item">
                <span>Received:</span>
                <span className="value positive">₹{(financials.received_amount || 0).toLocaleString()}</span>
              </div>
              <div className="financial-item">
                <span>Outstanding:</span>
                <span className="value warning">₹{(financials.outstanding_amount || 0).toLocaleString()}</span>
              </div>
            </div>
            
            {/* Costs Section */}
            <div className="financial-card costs">
              <h4>Costs</h4>
              <div className="financial-item">
                <span>Vendor Costs:</span>
                <span className="value">₹{(financials.vendor_costs || 0).toLocaleString()}</span>
              </div>
              <div className="financial-item">
                <span>Other Expenses:</span>
                <span className="value">₹{(financials.other_expenses || 0).toLocaleString()}</span>
              </div>
              <div className="financial-item total">
                <span>Total Costs:</span>
                <span className="value negative">₹{(financials.total_costs || 0).toLocaleString()}</span>
              </div>
            </div>
            
            {/* Profitability Section */}
            <div className="financial-card profit">
              <h4>Profitability</h4>
              <div className="financial-item">
                <span>Gross Profit:</span>
                <span className={`value ${financials.gross_profit >= 0 ? 'positive' : 'negative'}`}>
                  ₹{(financials.gross_profit || 0).toLocaleString()}
                </span>
              </div>
              <div className="financial-item">
                <span>Profit Margin:</span>
                <span className={`value ${financials.profit_margin >= 0 ? 'positive' : 'negative'}`}>
                  {(financials.profit_margin || 0).toFixed(1)}%
                </span>
              </div>
            </div>
          </div>
          
          {/* Document Counts */}
          <div className="documents-summary">
            <span className="doc-count">📄 {financials.invoice_count || 0} Invoices</span>
            <span className="doc-count">📋 {financials.bill_count || 0} Bills</span>
            <span className="doc-count">💰 {financials.expense_count || 0} Expenses</span>
          </div>
        </>
      ) : (
        <p>No financial data available</p>
      )}
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
          <button
            className={`tab-button ${activeTab === "financials" ? "active" : ""}`}
            onClick={() => setActiveTab("financials")}
          >
            💰 Financials
          </button>
        </div>

        <div className="modal-body">
          {activeTab === "study" && renderStudySpecification()}
          {activeTab === "traffic" && renderTrafficDetails()}
          {activeTab === "stats" && renderProjectStatistics()}
          {activeTab === "financials" && renderFinancials()}
        </div>
      </div>
    </div>
  );
}

export default ProjectDetailModal;
