import { useState, useEffect, useRef, useCallback } from "react";
import { API_BASE_URL } from "../../config";
import "./TrafficFlowParser.css";
import { buildApiUrl } from "../../config"

export default function TrafficFlowParser() {
  const [urlParams, setUrlParams] = useState({});
  const [fullUrl, setFullUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [retryCount, setRetryCount] = useState(0);
  const hasAutoTriggered = useRef(false);

  useEffect(() => {
    const currentUrl = window.location.href;
    setFullUrl(currentUrl);

    const params = new URLSearchParams(window.location.search);
    const parsedParams = {};
    for (let [key, value] of params.entries()) parsedParams[key] = value;
    setUrlParams(parsedParams);
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
        }),
      });

      clearTimeout(timeoutId);

      if (response.ok) {
        const result = await response.json();
        const objectId = result.id;
        const recordType = result.type || "unknown";
        const entryLink = result.entry_link;
        const allocationSuccess = result.allocation_success;

        console.log(`✅ Traffic record created: ${objectId} (type: ${recordType})`);

        // Check if survey was allocated successfully
        if (allocationSuccess && entryLink) {
          console.log(`✅ Survey allocated successfully, redirecting to: ${entryLink}`);
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
  }, [urlParams, fullUrl, retryCount]);

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
