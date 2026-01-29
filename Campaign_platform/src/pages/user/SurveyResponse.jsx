import { useState, useEffect, useCallback } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import { API_BASE_URL, buildApiUrl } from "../../config";
import "./TrafficFlowParser.css";

/**
 * SurveyResponse Component
 * 
 * This is the user landing page for the CPX API integration flow.
 * URL format: /survey-response?trans_id={trans_id}&status={status}
 * 
 * Flow:
 * 1. User completes survey on CPX
 * 2. CPX sends server-to-server postback to /cpx-postback
 * 3. Frontend polls /survey-status while user waits
 * 4. User is redirected to /survey-response?trans_id=XXX
 * 5. This page fetches final status from DB and displays result
 */
export default function SurveyResponse() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  
  const transId = searchParams.get("trans_id");
  const statusHint = searchParams.get("status"); // Hint from redirect, not authoritative
  
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState(null);
  const [transaction, setTransaction] = useState(null);
  const [error, setError] = useState(null);

  const fetchTransactionStatus = useCallback(async () => {
    if (!transId) {
      setError("Missing transaction ID");
      setLoading(false);
      return;
    }

    try {
      const response = await fetch(buildApiUrl(`/transaction/${transId}`), {
        method: "GET",
        headers: { "Content-Type": "application/json" },
        mode: "cors",
      });

      if (response.ok) {
        const data = await response.json();
        setTransaction(data);
        setStatus(data.status);
        setLoading(false);
      } else if (response.status === 404) {
        // Transaction not found - might still be processing
        setStatus("pending");
        setLoading(false);
      } else {
        throw new Error("Failed to fetch transaction status");
      }
    } catch (err) {
      console.error("Error fetching transaction:", err);
      setError(err.message);
      setLoading(false);
    }
  }, [transId]);

  useEffect(() => {
    fetchTransactionStatus();
  }, [fetchTransactionStatus]);

  // Auto-refresh for pending status
  useEffect(() => {
    if (status === "pending") {
      const timer = setTimeout(() => {
        fetchTransactionStatus();
      }, 5000);
      return () => clearTimeout(timer);
    }
  }, [status, fetchTransactionStatus]);

  if (loading) {
    return (
      <div className="survey-container">
        <div className="survey-card">
          <img src="/SF.png" alt="SurveyFieldwork Logo" className="survey-logo" />
          <h1 className="survey-title">Processing...</h1>
          <div className="survey-spinner"></div>
          <p className="survey-text">Please wait while we verify your survey completion.</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="survey-container">
        <div className="survey-card">
          <img src="/SF.png" alt="SurveyFieldwork Logo" className="survey-logo" />
          <h1 className="survey-title" style={{ color: "#dc3545" }}>Something Went Wrong</h1>
          <hr className="survey-divider" />
          <p className="survey-text">{error}</p>
          <p className="survey-text">Please contact support if this issue persists.</p>
          {transId && (
            <p className="survey-text" style={{ fontSize: "12px", color: "#999" }}>
              Reference: {transId}
            </p>
          )}
        </div>
      </div>
    );
  }

  if (status === "completed") {
    return (
      <div className="survey-container">
        <div className="survey-card">
          <img src="/SF.png" alt="SurveyFieldwork Logo" className="survey-logo" />
          <h1 className="survey-title" style={{ color: "#28a745" }}>✓ Survey Completed!</h1>
          <hr className="survey-divider" />
          <p className="survey-text">
            Thank you for completing the survey. Your response has been recorded.
          </p>
          {transaction?.amount_usd && (
            <p className="survey-text" style={{ fontSize: "24px", color: "#28a745", fontWeight: "bold" }}>
              Earned: ${transaction.amount_usd.toFixed(2)}
            </p>
          )}
          <p className="survey-text">
            You will be credited accordingly.
          </p>
          {transId && (
            <p className="survey-text" style={{ fontSize: "12px", color: "#999" }}>
              Transaction: {transId}
            </p>
          )}
        </div>
      </div>
    );
  }

  if (status === "pending") {
    return (
      <div className="survey-container">
        <div className="survey-card">
          <img src="/SF.png" alt="SurveyFieldwork Logo" className="survey-logo" />
          <h1 className="survey-title" style={{ color: "#ffc107" }}>⏳ Processing...</h1>
          <div className="survey-spinner"></div>
          <hr className="survey-divider" />
          <p className="survey-text">
            Waiting for survey completion confirmation.
          </p>
          <p className="survey-text" style={{ fontSize: "14px", color: "#666" }}>
            This page will automatically refresh.
          </p>
          {transId && (
            <p className="survey-text" style={{ fontSize: "12px", color: "#999" }}>
              Transaction: {transId}
            </p>
          )}
        </div>
      </div>
    );
  }

  // Canceled, fraud, or other status
  return (
    <div className="survey-container">
      <div className="survey-card">
        <img src="/SF.png" alt="SurveyFieldwork Logo" className="survey-logo" />
        <h1 className="survey-title">Survey Not Completed</h1>
        <hr className="survey-divider" />
        <p className="survey-text">
          Unfortunately, the survey was not completed successfully.
        </p>
        <p className="survey-text">
          If you believe this is an error, please contact support.
        </p>
        {transId && (
          <p className="survey-text" style={{ fontSize: "12px", color: "#999" }}>
            Transaction: {transId}
          </p>
        )}
      </div>
    </div>
  );
}
