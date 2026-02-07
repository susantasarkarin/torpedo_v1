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

// Fetch client IP - MUST use external IPv4 service for CPX compatibility
// CPX validates IP: API call IP must match survey click IP
// CloudFlare headers often return IPv6, but CPX sees IPv4 when user clicks
// So we MUST use an external IPv4 service to get the correct IP
async function fetchClientIP() {
  // Try IPv4 services FIRST (required for CPX)
  const ipv4Result = await fetchClientIPv4();
  if (ipv4Result.ip) {
    return ipv4Result;
  }
  
  // Fallback to server-side headers (may return IPv6 - not ideal for CPX)
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5000);
    
    const response = await fetch(buildApiUrl('/api/prefetch-ip'), {
      signal: controller.signal,
      mode: "cors",
    });
    clearTimeout(timeoutId);
    
    if (response.ok) {
      const data = await response.json();
      if (data.ip) {
        console.log(`⚠️ Using server IP (may be IPv6): ${data.ip} (source: ${data.source})`);
        return { ip: data.ip, source: data.source, userAgent: data.userAgent };
      }
    }
  } catch (err) {
    console.warn(`⚠️ Server-side IP prefetch failed:`, err.message);
  }
  
  return { ip: null, source: null };
}

// Fetch IPv4 specifically - CRITICAL for CPX
// These services return IPv4 which matches what CPX sees when user clicks survey
async function fetchClientIPv4() {
  const ipServices = [
    { url: "https://api.ipify.org?format=json", parser: (data) => data.ip },
    { url: "https://ipinfo.io/json", parser: (data) => data.ip },
  ];

  for (const service of ipServices) {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 3000); // 3s timeout
      
      const response = await fetch(service.url, {
        signal: controller.signal,
        mode: "cors",
      });
      clearTimeout(timeoutId);

      if (response.ok) {
        const contentType = response.headers.get("content-type") || "";
        let ip;
        if (contentType.includes("application/json")) {
          const data = await response.json();
          ip = service.parser(data);
        } else {
          const text = await response.text();
          ip = service.parser(text);
        }
        if (ip && ip.match(/^[\d.:a-fA-F]+$/)) {
          console.log(`✅ Fetched client IP: ${ip} from ${service.url}`);
          return { ip, source: service.url };
        }
      }
    } catch (err) {
      console.warn(`⚠️ IP fetch failed from ${service.url}:`, err.message);
    }
  }
  console.error("❌ Could not fetch client IP from any service");
  return { ip: null, source: null };
}

// Generate device fingerprint for fraud detection
async function generateDeviceFingerprint() {
  const components = {
    userAgent: navigator.userAgent || "",
    language: navigator.language || "",
    platform: navigator.platform || "",
    timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone || "",
    screen: `${window.screen?.width || 0}x${window.screen?.height || 0}x${window.screen?.colorDepth || 0}`,
    hardwareConcurrency: navigator.hardwareConcurrency || 0,
    deviceMemory: navigator.deviceMemory || 0,
    maxTouchPoints: navigator.maxTouchPoints || 0,
  };

  const raw = JSON.stringify(components);

  const fallbackHash = () => {
    let hash = 5381;
    for (let i = 0; i < raw.length; i += 1) {
      hash = ((hash << 5) + hash) + raw.charCodeAt(i);
      hash &= 0xffffffff;
    }
    return `fp_${(hash >>> 0).toString(16)}`;
  };

  if (window.crypto?.subtle && window.TextEncoder) {
    const data = new TextEncoder().encode(raw);
    const digest = await window.crypto.subtle.digest("SHA-256", data);
    const hashArray = Array.from(new Uint8Array(digest));
    const hashHex = hashArray.map((b) => b.toString(16).padStart(2, "0")).join("");
    return { hash: `fp_${hashHex}`, components };
  }

  return { hash: fallbackHash(), components };
}

export default function TrafficFlowParser() {
  const [urlParams, setUrlParams] = useState({});
  const [fullUrl, setFullUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [email, setEmail] = useState("");
  const [emailError, setEmailError] = useState("");
  const [birthdayDay, setBirthdayDay] = useState("");
  const [birthdayMonth, setBirthdayMonth] = useState("");
  const [birthdayYear, setBirthdayYear] = useState("");
  const [gender, setGender] = useState("");
  const [zipCode, setZipCode] = useState("");
  const [profileError, setProfileError] = useState("");
  // NOTE: retryCount removed - CPX forbids retries (each API call binds identity)
  const currentTransIdRef = useRef(null);
  
  // Pre-fetched IP data (captured on page load for zero-delay allocation)
  const prefetchedIpRef = useRef(null);
  
  // ============================================
  // TASK 8: Frontend Click Safety - Debounce Protection
  // ============================================
  // Prevents double-click/rapid-click from triggering multiple API calls
  // CPX binds identity on each API call - multiple calls = multiple identities = rejection
  const isClickProcessingRef = useRef(false);
  const lastClickTimeRef = useRef(0);
  const CLICK_DEBOUNCE_MS = 2000; // 2 second debounce window

  useEffect(() => {
    const currentUrl = window.location.href;
    setFullUrl(currentUrl);

    const params = new URLSearchParams(window.location.search);
    const parsedParams = {};
    for (let [key, value] of params.entries()) parsedParams[key] = value;
    setUrlParams(parsedParams);
    
    // ZERO-DELAY OPTIMIZATION: Prefetch IP on page load
    // This eliminates the 3-9 second delay when user clicks PROCEED
    // because the IP is already captured from server headers
    const prefetchIp = async () => {
      try {
        console.log('🚀 Prefetching client IP on page load...');
        const ipData = await fetchClientIP();
        if (ipData.ip) {
          prefetchedIpRef.current = ipData;
          console.log(`✅ IP prefetched and cached: ${ipData.ip} (source: ${ipData.source})`);
        }
      } catch (err) {
        console.warn('⚠️ IP prefetch on load failed:', err.message);
      }
    };
    prefetchIp();
  }, []);

  // NOTE: triggerSurveySync removed - CPX forbids sync/retry flows
  // Each CPX API call binds identity. Retry = new identity = violation.

  // NOTE: Polling removed - user is redirected to survey page entirely
  // Survey completion is tracked via CPX callbacks to our backend

  const handleStore = useCallback(async () => {
    // ============================================
    // TASK 8: Frontend Click Safety - Debounce Check
    // ============================================
    // Block rapid clicks to prevent multiple API calls (CPX binds identity per call)
    const now = Date.now();
    const timeSinceLastClick = now - lastClickTimeRef.current;
    
    if (isClickProcessingRef.current) {
      console.log('🚫 Click blocked: Another request is already processing');
      return;
    }
    
    if (timeSinceLastClick < CLICK_DEBOUNCE_MS) {
      console.log(`🚫 Click blocked: Debounce active (${timeSinceLastClick}ms since last click, need ${CLICK_DEBOUNCE_MS}ms)`);
      return;
    }
    
    // Mark as processing and record click time
    isClickProcessingRef.current = true;
    lastClickTimeRef.current = now;
    
    // Check for required traffic parameters
    const vid = urlParams.vid;
    const cc = urlParams.cc;
    const rid = urlParams.rid;

    if (!vid || !cc || !rid) {
      isClickProcessingRef.current = false;  // Reset on validation failure
      alert("Missing required parameters: vid (vendor ID), cc (country code), rid (respondent ID)\nExample: ?vid=123&cc=US&rid=456789");
      return;
    }

    // Validate email is provided and has valid format
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!email || !email.trim()) {
      isClickProcessingRef.current = false;
      setEmailError("Email address is required");
      return;
    }
    if (!emailRegex.test(email.trim())) {
      isClickProcessingRef.current = false;
      setEmailError("Please enter a valid email address");
      return;
    }
    setEmailError("");

    // Validate profiling data (CRITICAL for CPX survey matching)
    if (!birthdayDay || !birthdayMonth || !birthdayYear) {
      isClickProcessingRef.current = false;
      setProfileError("Please enter your complete date of birth");
      return;
    }
    if (!gender) {
      isClickProcessingRef.current = false;
      setProfileError("Please select your gender");
      return;
    }
    if (!zipCode || !zipCode.trim()) {
      isClickProcessingRef.current = false;
      setProfileError("Please enter your postal/zip code");
      return;
    }
    setProfileError("");

    setLoading(true);
    setError(null);

    try {
      // ============================================
      // FRESH IP COLLECTION ON CLICK (CRITICAL FIX)
      // ============================================
      // Mobile carriers (Jio, Airtel) rotate IPs frequently (30-60 seconds)
      // Prefetched IP from page load may be stale by the time user clicks
      // CPX validates: API call IP MUST match survey click IP
      // Solution: Always fetch FRESH IP right before CPX API call
      console.log("🔄 Fetching FRESH IP right before CPX API call...");
      let ipResult = await fetchClientIP();

      // If fresh fetch failed, use prefetched as emergency fallback
      if (!ipResult || !ipResult.ip) {
        console.log("⚠️ Fresh IP fetch failed, using prefetched IP as fallback...");
        ipResult = prefetchedIpRef.current;
        if (!ipResult || !ipResult.ip) {
          throw new Error("Failed to obtain client IP address. Please check your internet connection.");
        }
      } else {
        console.log(`✅ Using FRESH IP: ${ipResult.ip} (source: ${ipResult.source})`);

        // Compare with prefetched IP to detect rotation
        if (prefetchedIpRef.current && prefetchedIpRef.current.ip) {
          const prefetchedIp = prefetchedIpRef.current.ip;
          if (prefetchedIp !== ipResult.ip) {
            console.warn(`⚠️ IP ROTATION DETECTED: Prefetch=${prefetchedIp}, Fresh=${ipResult.ip}`);
            console.warn(`   This is common on mobile networks and would cause CPX screenout if we used prefetch!`);
          } else {
            console.log(`✅ IP consistent: ${ipResult.ip} (no rotation since page load)`);
          }
        }
      }

      // Generate fingerprint in parallel (fast, ~100ms)
      const fingerprint = await generateDeviceFingerprint();
      console.log(`🔐 Device fingerprint: ${fingerprint?.hash?.substring(0, 20)}...`);

      // Generate unique transaction ID for this survey attempt
      const transId = generateTransId();
      currentTransIdRef.current = transId;
      console.log(`🆔 Generated trans_id: ${transId}`);

      // NOTE: Removed preRegisterTransaction call to reduce latency
      // Transaction tracking is now handled by the backend

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
          // IP data from server-side prefetch (fast) or fallback
          clientIp: ipResult.ip || null,
          ipSource: ipResult.source || "none",
          deviceFingerprint: fingerprint?.hash || "",
          fingerprintComponents: fingerprint?.components || {},
          fingerprintSource: "client",
          trans_id: transId, // Include trans_id in traffic record
          email: email.trim(), // User's email address (mandatory)
          // CPX User Profiling Parameters (CRITICAL for demographic survey matching)
          birthday_day: parseInt(birthdayDay, 10),
          birthday_month: parseInt(birthdayMonth, 10),
          birthday_year: parseInt(birthdayYear, 10),
          gender: gender, // "m" or "f"
          zip_code: zipCode.trim(),
        }),
      });

      clearTimeout(timeoutId);

      if (response.ok) {
        const result = await response.json();
        const objectId = result.id;
        const recordType = result.type || "unknown";
        let entryLink = result.entry_link;
        const allocationSuccess = result.allocation_success;
        const allocationError = result.allocation_error;
        const debugInfo = result.debug_info;

        console.log(`✅ Traffic record created: ${objectId} (type: ${recordType})`);

        // Check if survey was allocated successfully
        if (allocationSuccess && entryLink) {
          // CRITICAL: Do NOT modify the CPX href. Use server-side HTTP redirect.
          console.log(`✅ Survey allocated successfully, redirecting via HTTP: ${entryLink}`);

          // Pure HTTP redirect handled by backend (no JS redirect to CPX)
          window.location.href = buildApiUrl(`/cpx/redirect?id=${objectId}`);
        } else {
          // ===============================================================
          // NO SURVEYS AVAILABLE - THIS IS A VALID OUTCOME, NOT AN ERROR
          // ===============================================================
          // CPX RULES: 
          // - Do NOT retry - each API call binds identity
          // - Do NOT sync and retry - violates timing rules
          // - Do NOT pool fallback - hrefs are bound to ext_user_id
          // - Accept "no surveys" as a clean exit
          // ===============================================================
          
          // Log diagnostic info for debugging
          if (allocationError) {
            console.log(`ℹ️ No surveys available: ${allocationError}`);
          }
          if (debugInfo) {
            console.log(`🔍 Debug info:`, debugInfo);
          }
          
          // Show user-friendly message - this is a VALID outcome, not a failure
          const errorMsg = allocationError 
            ? `No surveys available for your profile: ${allocationError}`
            : "No surveys are currently available for your profile. This is normal - please check back later.";
          setError(errorMsg);
          setLoading(false);
          isClickProcessingRef.current = false;  // TASK 8: Reset click guard on no surveys
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
      isClickProcessingRef.current = false;  // TASK 8: Reset click guard on error
    }
  }, [urlParams, fullUrl, email, birthdayDay, birthdayMonth, birthdayYear, gender, zipCode]);

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

        {/* Email input field - mandatory */}
        <div style={{ margin: "20px 0", textAlign: "left" }}>
          <label htmlFor="email" style={{ display: "block", marginBottom: "8px", fontWeight: "500", color: "#333" }}>
            Email Address <span style={{ color: "#c00" }}>*</span>
          </label>
          <input
            type="email"
            id="email"
            value={email}
            onChange={(e) => {
              setEmail(e.target.value);
              if (emailError) setEmailError("");
            }}
            placeholder="Enter your email address"
            style={{
              width: "100%",
              padding: "12px 16px",
              fontSize: "16px",
              border: emailError ? "2px solid #c00" : "1px solid #ccc",
              borderRadius: "8px",
              boxSizing: "border-box",
              outline: "none",
              transition: "border-color 0.2s",
            }}
            onFocus={(e) => e.target.style.borderColor = "#1976d2"}
            onBlur={(e) => e.target.style.borderColor = emailError ? "#c00" : "#ccc"}
          />
          {emailError && (
            <p style={{ color: "#c00", fontSize: "14px", marginTop: "6px", marginBottom: "0" }}>
              {emailError}
            </p>
          )}
        </div>

        {/* Date of Birth - mandatory for CPX demographic targeting */}
        <div style={{ margin: "20px 0", textAlign: "left" }}>
          <label style={{ display: "block", marginBottom: "8px", fontWeight: "500", color: "#333" }}>
            Date of Birth <span style={{ color: "#c00" }}>*</span>
          </label>
          <div style={{ display: "flex", gap: "10px" }}>
            <select
              value={birthdayDay}
              onChange={(e) => {
                setBirthdayDay(e.target.value);
                if (profileError) setProfileError("");
              }}
              style={{
                flex: "1",
                padding: "12px 16px",
                fontSize: "16px",
                border: profileError && !birthdayDay ? "2px solid #c00" : "1px solid #ccc",
                borderRadius: "8px",
                outline: "none",
              }}
            >
              <option value="">Day</option>
              {Array.from({ length: 31 }, (_, i) => i + 1).map(day => (
                <option key={day} value={day}>{day}</option>
              ))}
            </select>
            <select
              value={birthdayMonth}
              onChange={(e) => {
                setBirthdayMonth(e.target.value);
                if (profileError) setProfileError("");
              }}
              style={{
                flex: "1",
                padding: "12px 16px",
                fontSize: "16px",
                border: profileError && !birthdayMonth ? "2px solid #c00" : "1px solid #ccc",
                borderRadius: "8px",
                outline: "none",
              }}
            >
              <option value="">Month</option>
              <option value="1">January</option>
              <option value="2">February</option>
              <option value="3">March</option>
              <option value="4">April</option>
              <option value="5">May</option>
              <option value="6">June</option>
              <option value="7">July</option>
              <option value="8">August</option>
              <option value="9">September</option>
              <option value="10">October</option>
              <option value="11">November</option>
              <option value="12">December</option>
            </select>
            <select
              value={birthdayYear}
              onChange={(e) => {
                setBirthdayYear(e.target.value);
                if (profileError) setProfileError("");
              }}
              style={{
                flex: "1",
                padding: "12px 16px",
                fontSize: "16px",
                border: profileError && !birthdayYear ? "2px solid #c00" : "1px solid #ccc",
                borderRadius: "8px",
                outline: "none",
              }}
            >
              <option value="">Year</option>
              {Array.from({ length: 81 }, (_, i) => new Date().getFullYear() - 18 - i).map(year => (
                <option key={year} value={year}>{year}</option>
              ))}
            </select>
          </div>
        </div>

        {/* Gender - mandatory for CPX demographic targeting */}
        <div style={{ margin: "20px 0", textAlign: "left" }}>
          <label style={{ display: "block", marginBottom: "8px", fontWeight: "500", color: "#333" }}>
            Gender <span style={{ color: "#c00" }}>*</span>
          </label>
          <div style={{ display: "flex", gap: "20px", marginTop: "10px" }}>
            <label style={{ display: "flex", alignItems: "center", cursor: "pointer" }}>
              <input
                type="radio"
                name="gender"
                value="m"
                checked={gender === "m"}
                onChange={(e) => {
                  setGender(e.target.value);
                  if (profileError) setProfileError("");
                }}
                style={{ marginRight: "8px", width: "18px", height: "18px", cursor: "pointer" }}
              />
              <span style={{ fontSize: "16px" }}>Male</span>
            </label>
            <label style={{ display: "flex", alignItems: "center", cursor: "pointer" }}>
              <input
                type="radio"
                name="gender"
                value="f"
                checked={gender === "f"}
                onChange={(e) => {
                  setGender(e.target.value);
                  if (profileError) setProfileError("");
                }}
                style={{ marginRight: "8px", width: "18px", height: "18px", cursor: "pointer" }}
              />
              <span style={{ fontSize: "16px" }}>Female</span>
            </label>
          </div>
        </div>

        {/* Zip/Postal Code - mandatory for CPX location targeting */}
        <div style={{ margin: "20px 0", textAlign: "left" }}>
          <label htmlFor="zipCode" style={{ display: "block", marginBottom: "8px", fontWeight: "500", color: "#333" }}>
            Zip/Postal Code <span style={{ color: "#c00" }}>*</span>
          </label>
          <input
            type="text"
            id="zipCode"
            value={zipCode}
            onChange={(e) => {
              setZipCode(e.target.value);
              if (profileError) setProfileError("");
            }}
            placeholder="Enter your zip or postal code"
            style={{
              width: "100%",
              padding: "12px 16px",
              fontSize: "16px",
              border: profileError && !zipCode ? "2px solid #c00" : "1px solid #ccc",
              borderRadius: "8px",
              boxSizing: "border-box",
              outline: "none",
              transition: "border-color 0.2s",
            }}
            onFocus={(e) => e.target.style.borderColor = "#1976d2"}
            onBlur={(e) => e.target.style.borderColor = profileError && !zipCode ? "#c00" : "#ccc"}
          />
        </div>

        {/* Show profile validation error */}
        {profileError && (
          <div style={{ margin: "10px 0", padding: "15px", backgroundColor: "#fee", color: "#c00", borderRadius: "4px" }}>
            <strong>Error:</strong> {profileError}
          </div>
        )}

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
