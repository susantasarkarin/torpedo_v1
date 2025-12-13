import { useState, useEffect } from "react";
import { API_BASE_URL } from "../../config";
import "./TrafficFlowParser.css";

export default function TrafficFlowParser() {
  const [urlParams, setUrlParams] = useState({});
  const [fullUrl, setFullUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    const currentUrl = window.location.href;
    setFullUrl(currentUrl);

    const params = new URLSearchParams(window.location.search);
    const parsedParams = {};
    for (let [key, value] of params.entries()) parsedParams[key] = value;
    setUrlParams(parsedParams);
  }, []);

  const handleStore = async () => {
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
      const response = await fetch(`${API_BASE_URL}/api/store`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        mode: "cors",
        body: JSON.stringify({
          url: fullUrl,
          params: urlParams,
          userAgent: navigator.userAgent,
        }),
      });

      if (response.ok) {
        const result = await response.json();
        const objectId = result.id;
        const recordType = result.type || "unknown";

        console.log(`✅ Traffic record created: ${objectId} (type: ${recordType})`);

        // ✅ Redirect to survey with traffic ObjectId
        // This will be replaced with actual survey assignment later
        window.location.href = `https://survey.zohopublic.in/zs/lTCyZz?rid=${objectId}`;
      } else {
        const errorData = await response.json().catch(() => ({ detail: "Unknown error" }));
        throw new Error(errorData.detail || "Failed to store data");
      }
    } catch (error) {
      console.error("Store error:", error);
      setError(error.message);
      setLoading(false);
    }
  };

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
        
        {/* Show error message */}
        {error && (
          <div style={{ margin: "10px 0", padding: "10px", backgroundColor: "#fee", color: "#c00", borderRadius: "4px" }}>
            <strong>Error:</strong> {error}
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
