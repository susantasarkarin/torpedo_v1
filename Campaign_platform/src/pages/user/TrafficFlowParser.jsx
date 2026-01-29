import { useState, useEffect, useRef, useCallback } from "react";
import { API_BASE_URL } from "../../config";
import "./TrafficFlowParser.css";
import { buildApiUrl } from "../../config"

// Generate a unique transaction ID (UUID v4)
function generateTransId() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
    const r = Math.random() * 16 | 0;
    const v = c === 'x' ? r : (r & 0x3 | 0x8);
    return v.toString(16);
  });
}

export default function TrafficFlowParser() {
  const [urlParams, setUrlParams] = useState({});
  const [fullUrl, setFullUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [retryCount, setRetryCount] = useState(0);
  const [pollingStatus, setPollingStatus] = useState(null); // For showing survey completion status
  const hasAutoTriggered = useRef(false);
  const pollIntervalRef = useRef(null);
  const currentTransIdRef = useRef(null);

  useEffect(() => {
    const currentUrl = window.location.href;
    setFullUrl(currentUrl);

    const params = new URLSearchParams(window.location.search);
    const parsedParams = {};
    for (let [key, value] of params.entries()) parsedParams[key] = value;
    setUrlParams(parsedParams);
    
    // Cleanup polling on unmount
    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
      }
    };
  }, []);

  // Function to trigger survey pool sync
  const triggerSurveySync = async () => {
    try {
      console.log("🔄 Triggering survey pool sync...");
      const syncResponse = await fetch(buildApiUrl(`/survey-pool/sync`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        mode: "cors",
      });
      if (syncResponse.ok) {
        const syncResult = await syncResponse.json();
        console.log("✅ Survey sync completed:", syncResult);
        return true;
      }
    } catch (err) {
      console.error("⚠️ Survey sync failed:", err);
    }
    return false;
  };

  // Pre-register transaction before user starts survey
  const preRegisterTransaction = async (transId, subid) => {
    try {
      console.log(`📝 Pre-registering transaction: ${transId}`);
      const response = await fetch(buildApiUrl(`/cpx-api/transaction/create`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        mode: "cors",
        body: JSON.stringify({
          trans_id: transId,
          subid: subid,
          status: "pending"
        }),
      });
      if (response.ok) {
        const result = await response.json();
        console.log("✅ Transaction pre-registered:", result);
        return true;
      } else {
        console.error("❌ Failed to pre-register transaction");
        return false;
      }
    } catch (err) {
      console.error("❌ Transaction pre-registration error:", err);
      return false;
    }
  };

  // Poll for survey completion status
  const startPolling = useCallback((transId) => {
    console.log(`🔄 Starting polling for transaction: ${transId}`);
    setPollingStatus("waiting");
    
    const pollForStatus = async () => {
      try {
        const response = await fetch(buildApiUrl(`/cpx-api/survey-status?trans_id=${transId}`), {
          method: "GET",
          headers: { "Content-Type": "application/json" },
          mode: "cors",
        });
        
        if (response.ok) {
          const result = await response.json();
          console.log(`📊 Poll result:`, result);
          
          if (result.status === "completed" || result.status === "canceled" || result.status === "fraud") {
            // Stop polling and redirect to response page
            if (pollIntervalRef.current) {
              clearInterval(pollIntervalRef.current);
              pollIntervalRef.current = null;
            }
            console.log(`✅ Survey ${result.status}, redirecting to response page...`);
            window.location.href = `/response?trans_id=${transId}&status=${result.status}&subid=${urlParams.rid || ""}`;
          }
        }
      } catch (err) {
        console.error("⚠️ Polling error:", err);
      }
    };
    
    // Poll immediately, then every 5 seconds
    pollForStatus();
    pollIntervalRef.current = setInterval(pollForStatus, 5000);
    
    // Stop polling after 30 minutes (surveys have time limits)
    setTimeout(() => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
        setPollingStatus("timeout");
        console.log("⏰ Polling timeout reached");
      }
    }, 30 * 60 * 1000);
  }, [urlParams.rid]);

  const handleStore = useCallback(async (isRetry = false) => {
    // Check for required traffic parameters
    const vid = urlParams.vid;
    const cc = urlParams.cc;
    const rid = urlParams.rid;

    if (!vid || !cc || !rid) {
      alert("Missing required parameters: vid (vendor ID), cc (country code), rid (respondent ID)\nExample: ?vid=123&cc=US&rid=456789");
      return;
    }

    setLoading(true);
    setError(null);

    try {
      // Generate unique transaction ID for this survey attempt
      const transId = generateTransId();
      currentTransIdRef.current = transId;
      console.log(`🆔 Generated trans_id: ${transId}`);

      // Pre-register transaction before starting survey
      const preRegistered = await preRegisterTransaction(transId, rid);
      if (!preRegistered) {
        console.warn("⚠️ Failed to pre-register transaction, continuing anyway...");
      }

      // Add timeout controller for better error handling
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 30000); // 30 second timeout

      const response = await fetch(buildApiUrl(`/api/store`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        mode: "cors",
        signal: controller.signal,
        body: JSON.stringify({
          url: fullUrl,
          params: urlParams,
          userAgent: navigator.userAgent,
          trans_id: transId, // Include trans_id in traffic record
        }),
      });

      clearTimeout(timeoutId);

      if (response.ok) {
        const result = await response.json();
        const objectId = result.id;
        const recordType = result.type || "unknown";
        let entryLink = result.entry_link;
        const allocationSuccess = result.allocation_success;

        console.log(`✅ Traffic record created: ${objectId} (type: ${recordType})`);

        // Check if survey was allocated successfully
        if (allocationSuccess && entryLink) {
          // Append trans_id to entry link for CPX postback tracking
          const separator = entryLink.includes('?') ? '&' : '?';
          entryLink = `${entryLink}${separator}ext_subid2=${transId}`;
          
          console.log(`✅ Survey allocated successfully, redirecting to: ${entryLink}`);
          
          // Start polling for survey completion
          startPolling(transId);
          
          // Redirect to survey
          window.location.href = entryLink;
        } else {
          // No survey allocated - try to sync and retry once
          if (!isRetry && retryCount < 1) {
            console.log("⚠️ No survey allocated, triggering sync and retrying...");
            setRetryCount(prev => prev + 1);
            const synced = await triggerSurveySync();
            if (synced) {
              // Wait a moment for sync to complete, then retry
              setTimeout(() => handleStore(true), 2000);
              return;
            }
          }
          
          // If retry also failed, show error
          console.error("❌ No survey allocated from pool after retry. Backend may have no active surveys.");
          setError("No surveys are currently available. Please try again in a few minutes or contact support.");
          setLoading(false);
        }
      } else {
        const errorData = await response.json().catch(() => ({ detail: "Unknown error" }));
        throw new Error(errorData.detail || "Failed to store data");
      }
    } catch (err) {
      console.error("Store error:", err);

      // Provide user-friendly error messages
      let errorMessage = err.message;
      if (err.name === "AbortError") {
        errorMessage = "Request timed out. Please check your internet connection and try again.";
      } else if (err.message === "Failed to fetch") {
        errorMessage = "Network error. Please disable any VPN or ad-blockers and try again, or check your internet connection.";
      }

      setError(errorMessage);
      setLoading(false);
    }
  }, [urlParams, fullUrl, retryCount, startPolling]);

  // Auto-trigger removed - user must click the "Next" button manually
  // This was causing the system to automatically click the button
  // useEffect(() => {
  //   if (hasAutoTriggered.current) return;
  //   if (urlParams.vid && urlParams.cc && urlParams.rid && fullUrl) {
  //     hasAutoTriggered.current = true;
  //     handleStore();
  //   }
  // }, [urlParams, fullUrl, handleStore]);

  return (
    <div className="survey-container">
      <div className="survey-card">
        <img src="/SF.png" alt="SurveyFieldwork Logo" className="survey-logo" />
        <h1 className="survey-title">
          Thank You for Agreeing To Participate In Our Survey
        </h1>
        <p className="survey-text">
          Your opinions are important to us. Kindly provide honest and thoughtful responses for each question in order to make your participation count.
        </p>
        <p className="survey-text highlight">
          Your responses will be kept confidential and will be used in aggregate only.
        </p>

        {/* Show error message with retry button */}
        {error && (
          <div style={{ margin: "10px 0", padding: "15px", backgroundColor: "#fee", color: "#c00", borderRadius: "4px" }}>
            <strong>Error:</strong> {error}
            <br />
            <button
              onClick={handleStore}
              style={{
                marginTop: "10px",
                padding: "8px 20px",
                cursor: "pointer",
                backgroundColor: "#fff",
                border: "1px solid #c00",
                borderRadius: "4px",
                color: "#c00"
              }}
            >
              Try Again
            </button>
          </div>
        )}

        {/* Show polling status when waiting for survey completion */}
        {pollingStatus === "waiting" && (
          <div style={{ margin: "10px 0", padding: "15px", backgroundColor: "#e7f3ff", color: "#0066cc", borderRadius: "4px", textAlign: "center" }}>
            <div className="spinner" style={{ margin: "0 auto 10px" }}></div>
            <strong>Waiting for survey completion...</strong>
            <p style={{ margin: "5px 0 0", fontSize: "14px" }}>
              You will be automatically redirected when the survey is complete.
            </p>
          </div>
        )}

        {pollingStatus === "timeout" && (
          <div style={{ margin: "10px 0", padding: "15px", backgroundColor: "#fff3cd", color: "#856404", borderRadius: "4px" }}>
            <strong>Session Timeout</strong>
            <p style={{ margin: "5px 0 0" }}>
              Your survey session has timed out. Please start again if you haven't completed the survey.
            </p>
            <button
              onClick={() => {
                setPollingStatus(null);
                setLoading(false);
              }}
              style={{
                marginTop: "10px",
                padding: "8px 20px",
                cursor: "pointer",
                backgroundColor: "#fff",
                border: "1px solid #856404",
                borderRadius: "4px",
                color: "#856404"
              }}
            >
              Start New Survey
            </button>
          </div>
        )}

        <hr className="survey-divider" />
        <p className="survey-highlight">Please click below to continue!</p>
        <button
          onClick={handleStore}
          className="survey-button"
          disabled={loading}
        >
          {loading ? "Processing..." : "Next"}
        </button>
      </div>
    </div>
  );
}
