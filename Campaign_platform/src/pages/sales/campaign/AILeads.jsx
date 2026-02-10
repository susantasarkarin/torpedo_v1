/**
 * AI Lead Database
 * Path: /admin/sales/campaign/ai-leads
 * Light theme matching app styling
 */

import React, { useState, useEffect, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { API_BASE_URL } from "../../../config";
import Papa from "papaparse";
import "./AILeads.css";
import { buildApiUrl } from "../../../config"

// ============== FILTER OPTIONS ==============

// LinkedIn Seniority Levels (matches LinkedIn Sales Navigator)
const SENIORITY_OPTIONS = [
  "Owner",
  "Founder",
  "CXO",
  "Partner",
  "VP",
  "Director",
  "Manager",
  "Senior",
  "Entry",
  "Training",
  "Unpaid"
];
const DEPARTMENT_OPTIONS = ["Sales", "Marketing", "Engineering", "Operations", "Finance", "HR", "Product", "Other"];
const PERSONA_OPTIONS = ["Decision Maker", "Influencer", "Gatekeeper", "Practitioner"];
const COMPANY_SIZE_OPTIONS = ["Startup", "SMB", "Mid-Market", "Enterprise"];

// Countries for web search filter
const COUNTRY_OPTIONS = [
  "United States", "United Kingdom", "Canada", "Australia", "Germany", 
  "France", "India", "Singapore", "UAE", "Netherlands", "Sweden", 
  "Switzerland", "Japan", "South Korea", "Brazil", "Mexico", "Spain",
  "Italy", "China", "Hong Kong", "Indonesia", "Philippines", "Thailand",
  "Vietnam", "Malaysia", "New Zealand", "Ireland", "Belgium", "Austria",
  "Denmark", "Norway", "Finland", "Poland", "Portugal", "South Africa",
  "Israel", "Saudi Arabia", "Turkey", "Russia", "Argentina", "Chile",
  "Colombia", "Peru", "Egypt", "Nigeria", "Kenya", "Other"
];

// Designation presets for web search (can also type custom)
const DESIGNATION_PRESETS = [
  "CEO", "CTO", "CFO", "COO", "CMO", "CRO", "CHRO", "CIO", "CPO",
  "VP Sales", "VP Marketing", "VP Engineering", "VP Product", "VP Operations",
  "Director of Sales", "Director of Marketing", "Director of Engineering",
  "Sales Manager", "Marketing Manager", "Product Manager", "Engineering Manager",
  "Head of Sales", "Head of Marketing", "Head of Growth", "Head of Product",
  "Founder", "Co-Founder", "Owner", "Partner", "Managing Director"
];

// CSV Import fields - Full schema matching all lead fields (Issue 6 - all fields)
const DB_FIELDS = [
  { key: "name", label: "Full Name", required: false },
  { key: "first_name", label: "First Name", required: false },
  { key: "last_name", label: "Last Name", required: false },
  { key: "email", label: "Email", required: true },  // Made mandatory per Issue 6
  { key: "email_status", label: "Email Status", required: false },
  { key: "title", label: "Job Title", required: false },
  { key: "linkedin_url", label: "LinkedIn URL", required: false },
  { key: "location", label: "Location", required: false },
  { key: "added_on", label: "Added On", required: false },
  { key: "profile_picture", label: "Profile Picture", required: false },
  { key: "seniority_level", label: "Seniority Level", required: false },
  { key: "buying_role", label: "Buying Role", required: false },
  { key: "gender", label: "Gender", required: false },
  { key: "company_name", label: "Company Name", required: false },
  { key: "company_domain", label: "Company Domain", required: false },
  { key: "company_website", label: "Company Website", required: false },
  { key: "company_employee_count", label: "Company Employee Count", required: false },
  { key: "company_employee_count_range", label: "Company Employee Count Range", required: false },
  { key: "company_founded", label: "Company Founded", required: false },
  { key: "company_industry", label: "Company Industry", required: false },
  { key: "company_type", label: "Company Type", required: false },
  { key: "company_headquarters", label: "Company Headquarters", required: false },
  { key: "company_revenue_range", label: "Company Revenue Range", required: false },
  { key: "company_linkedin_url", label: "Company LinkedIn URL", required: false },
  { key: "company_crunchbase_url", label: "Company Crunchbase URL", required: false },
  { key: "company_funding_rounds", label: "Company Funding Rounds", required: false },
  { key: "company_last_funding_round_amount", label: "Company Last Funding Round Amount", required: false },
  { key: "company_logo_url_primary", label: "Company Logo URL Primary", required: false },
  { key: "company_logo_url_secondary", label: "Company Logo URL Secondary", required: false },
  { key: "snippet", label: "Bio/Description", required: false },
];

const COLUMN_ALIASES = {
  name: ["name", "full_name", "fullname", "full name", "contact_name"],
  first_name: ["firstname", "first_name", "first", "given_name"],
  last_name: ["lastname", "last_name", "last", "surname"],
  email: ["email", "email_address", "e-mail", "mail", "work_email"],
  email_status: ["email_status", "emailstatus", "email status", "status", "valid", "email_valid"],
  title: ["title", "job_title", "jobtitle", "position", "role", "designation"],
  linkedin_url: ["linkedin", "linkedin_url", "linkedinurl", "linkedin_profile", "profile_url", "linkedin url"],
  location: ["location", "city", "country", "region", "geo", "address"],
  added_on: ["added_on", "addedon", "added", "created", "created_at", "date_added", "import_date"],
  profile_picture: ["profile_picture", "profilepicture", "photo", "avatar", "image", "picture", "photo_url"],
  seniority_level: ["seniority_level", "senioritylevel", "seniority", "level", "job_level"],
  buying_role: ["buying_role", "buyingrole", "buyer_role", "role_type"],
  gender: ["gender", "sex"],
  company_name: ["company", "company_name", "companyname", "organization", "employer", "company name"],
  company_domain: ["company_domain", "companydomain", "domain", "website_domain"],
  company_website: ["company_website", "companywebsite", "website", "company_url", "company website"],
  company_employee_count: ["company_employee_count", "employees", "employee_count", "headcount", "size"],
  company_employee_count_range: ["company_employee_count_range", "employee_range", "size_range", "company_size"],
  company_founded: ["company_founded", "founded", "year_founded", "founded_year", "established"],
  company_industry: ["company_industry", "industry", "sector", "vertical"],
  company_type: ["company_type", "type", "business_type"],
  company_headquarters: ["company_headquarters", "headquarters", "hq", "hq_location", "main_office"],
  company_revenue_range: ["company_revenue_range", "revenue_range", "revenue", "annual_revenue"],
  company_linkedin_url: ["company_linkedin_url", "company_linkedin", "company linkedin"],
  company_crunchbase_url: ["company_crunchbase_url", "crunchbase", "crunchbase_url", "cb_url"],
  company_funding_rounds: ["company_funding_rounds", "funding_rounds", "rounds", "funding"],
  company_last_funding_round_amount: ["company_last_funding_round_amount", "last_funding", "funding_amount", "last_round"],
  company_logo_url_primary: ["company_logo_url_primary", "logo", "logo_url", "company_logo", "primary_logo"],
  company_logo_url_secondary: ["company_logo_url_secondary", "secondary_logo", "alt_logo"],
  snippet: ["snippet", "bio", "description", "about", "summary", "headline"],
};

function AILeads() {
  const navigate = useNavigate();
  const sessionId = localStorage.getItem("session_id");

  // Data State
  const [leads, setLeads] = useState([]);
  const [rawLeads, setRawLeads] = useState([]);
  const [statistics, setStatistics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selectedIds, setSelectedIds] = useState(new Set());

  // View State
  const [activeTab, setActiveTab] = useState("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [currentPage, setCurrentPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);

  // Filters
  const [filters, setFilters] = useState({
    seniority_level: "",
    department: "",
    persona: "",
    company_size: "",
    min_confidence: "",
  });

  // Import Modal State
  const [showImportModal, setShowImportModal] = useState(false);
  const [importMethod, setImportMethod] = useState("web-search");
  const [importData, setImportData] = useState("");
  const [csvFile, setCsvFile] = useState(null);
  const [googleSearchQuery, setGoogleSearchQuery] = useState("");
  const [googleSearchResults, setGoogleSearchResults] = useState(10);
  const [importing, setImporting] = useState(false);
  const [classifying, setClassifying] = useState(false);
  const [importError, setImportError] = useState("");

  // View Mode State - compact vs full table
  const [viewMode, setViewMode] = useState("compact"); // "compact" or "full"
  const [expandedLeadId, setExpandedLeadId] = useState(null); // For viewing lead details

  // Web Search Filters (enhanced with multi-select)
  const [webSearchDesignation, setWebSearchDesignation] = useState("");
  const [webSearchCountries, setWebSearchCountries] = useState([]); // Multi-select
  const [webSearchSeniorities, setWebSearchSeniorities] = useState([]); // Multi-select
  // Note: No target count - job runs continuously until stopped
  const [webSearchProgress, setWebSearchProgress] = useState(null);
  const [webSearchJobId, setWebSearchJobId] = useState(null); // Background job ID
  const [deletingAllLeads, setDeletingAllLeads] = useState(false);
  
  // Legacy single-select for backward compatibility
  const [webSearchCountry, setWebSearchCountry] = useState("");
  const [webSearchSeniority, setWebSearchSeniority] = useState("");

  // CSV Import State (from LeadsImport.jsx)
  const [csvData, setCsvData] = useState([]);
  const [csvColumns, setCsvColumns] = useState([]);
  const [columnMapping, setColumnMapping] = useState({});
  const [csvImportStep, setCsvImportStep] = useState(1); // 1=upload, 2=map, 3=preview
  const fileInputRef = useRef(null);

  // Gmail Import State (Issue 7)
  const [gmailAccounts, setGmailAccounts] = useState([]);
  const [selectedGmailAccounts, setSelectedGmailAccounts] = useState([]);
  const [gmailMaxEmails, setGmailMaxEmails] = useState(100);
  const [gmailSegments, setGmailSegments] = useState([]);
  const [selectedGmailSegments, setSelectedGmailSegments] = useState([]);
  const [gmailImporting, setGmailImporting] = useState(false);
  const [enrichmentPhases, setEnrichmentPhases] = useState({
    basic: true,    // Email, Full Name
    names: true,    // First Name, Last Name
    company: true,  // Company Name
    domain: true    // Domain from email
  });
  const [gmailImportProgress, setGmailImportProgress] = useState(null);

  // AI Discovery State (Perplexity Direct - no Google CSE needed)
  const [discoveryStep, setDiscoveryStep] = useState(1); // 1=search, 2=preview contacts
  const [discoveryIndustry, setDiscoveryIndustry] = useState("");

  // Search Control State (Global pause, circuit breaker, emergency stop)
  const [searchControl, setSearchControl] = useState({
    global_paused: false,
    paused_reason: "",
    circuit_breaker_open: false,
    consecutive_errors: 0,
    last_error: null,
    auto_resume_disabled: false,
    active_jobs_count: 0
  });
  const [searchControlLoading, setSearchControlLoading] = useState(false);
  const [allJobs, setAllJobs] = useState([]);
  const [discoveryLocation, setDiscoveryLocation] = useState("");
  const [discoveryCriteria, setDiscoveryCriteria] = useState("");
  const [discoveryDesignation, setDiscoveryDesignation] = useState("");
  const [discoveredCompanies, setDiscoveredCompanies] = useState([]);
  const [selectedCompanies, setSelectedCompanies] = useState([]);
  const [discoveryContacts, setDiscoveryContacts] = useState([]);
  const [selectedContacts, setSelectedContacts] = useState([]);
  const [discoveryLoading, setDiscoveryLoading] = useState(false);
  const [discoveryStatus, setDiscoveryStatus] = useState(null);
  const [discoveryError, setDiscoveryError] = useState("");

  // Gmail segment options
  const GMAIL_SEGMENT_OPTIONS = [
    { id: "promotional", name: "Promotional" },
    { id: "outreach", name: "Outreach" },
    { id: "discovery", name: "Discovery" },
    { id: "presentation", name: "Presentation" },
    { id: "rfq_pricing", name: "RFQ & Pricing" },
    { id: "negotiation", name: "Negotiation" },
    { id: "invoice", name: "Invoice" },
    { id: "banking", name: "Banking" },
    { id: "others", name: "Others" },
  ];

  // ============== FETCH DATA ==============

  // Helper to get source filter for current tab
  const getSourceFilterForTab = useCallback(() => {
    switch (activeTab) {
      case "classified-websearch":
        return "web_search,google_search,linkedin";
      case "classified-csv":
        return "csv,csv_import,google_sheets,json_import";
      case "classified-gmail":
        return "gmail,gmail_workspace,email_sync,email_import,email_classification,gmail_api,gmail_archive";
      default:
        return null; // No source filter for "all" or "classified"
    }
  }, [activeTab]);

  const fetchLeads = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (searchQuery) params.append("search", searchQuery);
      if (filters.seniority_level) params.append("seniority_level", filters.seniority_level);
      if (filters.department) params.append("department", filters.department);
      if (filters.persona) params.append("persona", filters.persona);
      if (filters.company_size) params.append("company_size", filters.company_size);
      if (filters.min_confidence) params.append("min_confidence", filters.min_confidence);
      
      // Add source filter based on active tab
      const sourceFilter = getSourceFilterForTab();
      if (sourceFilter) params.append("source", sourceFilter);
      
      params.append("page", currentPage);
      params.append("limit", 50);

      const res = await fetch(buildApiUrl(`/leads?${params.toString()}`), {
        headers: { Authorization: sessionId },
      });

      if (!res.ok) throw new Error("Failed to fetch leads");
      const data = await res.json();
      setLeads(data.leads || []);
      setTotalPages(data.pages || 1);
    } catch (err) {
      console.error("Error fetching leads:", err);
    }
  }, [filters, currentPage, searchQuery, sessionId, getSourceFilterForTab]);

  const fetchRawLeads = useCallback(async () => {
    try {
      const res = await fetch(buildApiUrl(`/leads/raw`), {
        headers: { Authorization: sessionId },
      });
      if (!res.ok) throw new Error("Failed to fetch raw leads");
      const data = await res.json();
      setRawLeads(data.leads || []);
    } catch (err) {
      console.error("Error fetching raw leads:", err);
    }
  }, [sessionId]);

  const fetchStatistics = useCallback(async () => {
    try {
      const res = await fetch(buildApiUrl(`/leads/statistics`), {
        headers: { Authorization: sessionId },
      });
      if (!res.ok) throw new Error("Failed to fetch statistics");
      const data = await res.json();
      setStatistics(data);
    } catch (err) {
      console.error("Error fetching statistics:", err);
    }
  }, [sessionId]);

  // Fetch Gmail accounts
  const fetchGmailAccounts = useCallback(async () => {
    try {
      const res = await fetch(buildApiUrl(`/leads/gmail/accounts`), {
        headers: { Authorization: sessionId },
      });
      if (!res.ok) return;
      const data = await res.json();
      setGmailAccounts(data.accounts || []);
    } catch (err) {
      console.error("Error fetching Gmail accounts:", err);
    }
  }, [sessionId]);

  // Fetch Gmail segments with counts
  const fetchGmailSegments = useCallback(async () => {
    try {
      const res = await fetch(buildApiUrl(`/leads/gmail/segments`), {
        headers: { Authorization: sessionId },
      });
      if (!res.ok) return;
      const data = await res.json();
      setGmailSegments(data.segments || []);
    } catch (err) {
      console.error("Error fetching Gmail segments:", err);
    }
  }, [sessionId]);

  // Fetch Search Control status (global pause, circuit breaker, etc.)
  const fetchSearchControl = useCallback(async () => {
    try {
      const res = await fetch(buildApiUrl(`/leads/import/web-search/control`), {
        headers: { Authorization: sessionId },
      });
      if (!res.ok) return;
      const data = await res.json();
      setSearchControl(data);
    } catch (err) {
      console.error("Error fetching search control:", err);
    }
  }, [sessionId]);

  // Fetch all web search jobs
  const fetchAllJobs = useCallback(async () => {
    try {
      const res = await fetch(buildApiUrl(`/leads/import/web-search/jobs?limit=20`), {
        headers: { Authorization: sessionId },
      });
      if (!res.ok) return;
      const data = await res.json();
      setAllJobs(data.jobs || []);
    } catch (err) {
      console.error("Error fetching jobs:", err);
    }
  }, [sessionId]);

  // Emergency stop all jobs
  const handleStopAllJobs = async () => {
    if (!confirm("🚨 EMERGENCY STOP: This will stop ALL running web search jobs. Continue?")) {
      return;
    }
    setSearchControlLoading(true);
    try {
      const res = await fetch(buildApiUrl(`/leads/import/web-search/stop-all`), {
        method: "POST",
        headers: { Authorization: sessionId },
      });
      const data = await res.json();
      alert(data.message || "All jobs stopped");
      fetchSearchControl();
      fetchAllJobs();
      if (window.webSearchPollInterval) {
        clearInterval(window.webSearchPollInterval);
      }
      setWebSearchProgress(null);
    } catch (err) {
      alert("Failed to stop jobs: " + err.message);
    } finally {
      setSearchControlLoading(false);
    }
  };

  // Pause global search
  const handlePauseSearch = async () => {
    setSearchControlLoading(true);
    try {
      const res = await fetch(buildApiUrl(`/leads/import/web-search/control/pause`), {
        method: "POST",
        headers: { Authorization: sessionId },
      });
      await res.json();
      fetchSearchControl();
    } catch (err) {
      console.error("Failed to pause:", err);
    } finally {
      setSearchControlLoading(false);
    }
  };

  // Resume global search
  const handleResumeSearch = async () => {
    setSearchControlLoading(true);
    try {
      const res = await fetch(buildApiUrl(`/leads/import/web-search/control/resume`), {
        method: "POST",
        headers: { Authorization: sessionId },
      });
      await res.json();
      fetchSearchControl();
    } catch (err) {
      console.error("Failed to resume:", err);
    } finally {
      setSearchControlLoading(false);
    }
  };

  useEffect(() => {
    // PHASED LOADING: Load data progressively for faster perceived performance
    // Phase 1: Load leads table immediately (most important for user)
    const loadPhase1 = async () => {
      setLoading(true);
      await fetchLeads();
      setLoading(false);
    };
    
    // Phase 2: Load secondary data after a small delay (non-blocking)
    const loadPhase2 = () => {
      // Use setTimeout to yield to the main thread and let UI render first
      setTimeout(() => {
        fetchRawLeads();
      }, 100);
      
      setTimeout(() => {
        fetchStatistics();
      }, 200);
      
      setTimeout(() => {
        fetchGmailAccounts();
      }, 300);
      
      // Also fetch search control status
      setTimeout(() => {
        fetchSearchControl();
        fetchAllJobs();
      }, 400);
    };
    
    loadPhase1();
    loadPhase2();
  }, []);

  // Refetch leads when filters or active tab change
  useEffect(() => {
    if (!loading) {
      setCurrentPage(1); // Reset to page 1 when tab changes
      fetchLeads();
    }
  }, [filters, currentPage, searchQuery, activeTab, fetchLeads]);

  // ============== IMPORT HANDLER ==============

  // Helper: Auto-match CSV columns
  const autoMatchColumns = (columns) => {
    const mapping = {};
    
    // Helper to normalize strings for comparison
    const normalize = (str) => str.toLowerCase().replace(/[\s\-\.]/g, "_").replace(/[^a-z0-9_]/g, "");
    
    columns.forEach((csvCol) => {
      const normalizedCsv = normalize(csvCol);
      for (const [dbField, aliases] of Object.entries(COLUMN_ALIASES)) {
        // Normalize aliases too for comparison
        const normalizedAliases = aliases.map(a => normalize(a));
        if (normalizedAliases.some((alias) => normalizedCsv === alias || normalizedCsv.includes(alias) || alias.includes(normalizedCsv))) {
          if (!mapping[dbField]) {
            mapping[dbField] = csvCol;
          }
          break;
        }
      }
    });
    return mapping;
  };

  // Handle CSV file selection
  const handleCsvFileSelect = async (file) => {
    if (!file) return;
    if (!file.name.endsWith(".csv")) {
      setImportError("Please select a CSV file");
      return;
    }
    setImportError("");
    setCsvFile(file);

    Papa.parse(file, {
      header: true,
      skipEmptyLines: true,
      complete: async (results) => {
        if (results.errors.length > 0) {
          setImportError("Error parsing CSV: " + results.errors[0].message);
          return;
        }
        const columns = results.meta.fields || [];
        setCsvColumns(columns);
        setCsvData(results.data);
        
        // Try to load saved mapping first
        let savedMapping = null;
        try {
          const res = await fetch(buildApiUrl(`/leads/import/csv/mapping?columns=${encodeURIComponent(columns.join(","))}`), {
            headers: { Authorization: sessionId },
          });
          if (res.ok) {
            const data = await res.json();
            if (data.mapping) {
              savedMapping = data.mapping;
            }
          }
        } catch (e) {
          console.log("Could not load saved mapping:", e);
        }
        
        // Use saved mapping if available, otherwise auto-match
        const autoMapping = savedMapping || autoMatchColumns(columns);
        setColumnMapping(autoMapping);
        setCsvImportStep(2);
      },
      error: (err) => {
        setImportError("Error reading file: " + err.message);
      },
    });
  };

  // Handle CSV column mapping change
  const handleMappingChange = (dbField, csvColumn) => {
    setColumnMapping((prev) => ({
      ...prev,
      [dbField]: csvColumn || undefined,
    }));
  };

  // Get mapped fields count
  const getMappedFieldsCount = () => {
    return Object.values(columnMapping).filter(Boolean).length;
  };

  const handleImport = async () => {
    setImporting(true);
    setImportError("");

    const parseResponse = async (res) => {
      const ct = res.headers.get("content-type") || "";
      if (ct.includes("application/json")) {
        return res.json();
      }
      const text = await res.text();
      return { detail: text || res.statusText };
    };
    
    try {
      let res;
      
      if (importMethod === "csv") {
        // Enhanced CSV import with mapping
        if (csvImportStep === 1) {
          setImportError("Please select a CSV file first");
          setImporting(false);
          return;
        }
        if (!columnMapping.email) {
          setImportError("Email field mapping is required");
          setImporting(false);
          return;
        }

        // Save column mapping for future use
        try {
          await fetch(buildApiUrl(`/leads/import/csv/mapping`), {
            method: "POST",
            headers: { "Content-Type": "application/json", Authorization: sessionId },
            body: JSON.stringify({ 
              filename: csvFile?.name || "default",
              mapping: columnMapping,
              columns: csvColumns
            }),
          });
        } catch (e) {
          console.log("Could not save mapping:", e);
        }

        // Map CSV data to expected format
        const mappedData = csvData.map((row) => {
          const newRow = {};
          DB_FIELDS.forEach((field) => {
            const csvCol = columnMapping[field.key];
            if (csvCol && row[csvCol] !== undefined) {
              newRow[field.key] = row[csvCol];
            }
          });
          return newRow;
        });

        // Convert back to CSV
        const csv = Papa.unparse(mappedData, { columns: DB_FIELDS.map(f => f.key) });
        const blob = new Blob([csv], { type: "text/csv" });
        const formData = new FormData();
        formData.append("file", blob, "import.csv");
        
        res = await fetch(buildApiUrl(`/leads/import/csv`), {
          method: "POST",
          headers: { Authorization: sessionId },
          body: formData,
        });
      } else if (importMethod === "web-search") {
        // New enhanced web search with multi-select - runs as background job
        const hasDesignation = webSearchDesignation.trim();
        const hasCountries = webSearchCountries.length > 0;
        const hasSeniorities = webSearchSeniorities.length > 0;
        
        if (!hasDesignation && !hasCountries && !hasSeniorities) {
          setImportError("Please select at least one filter (Designation, Country, or Seniority)");
          setImporting(false);
          return;
        }
        
        setWebSearchProgress({ status: "Starting background search...", found: 0, imported: 0 });
        
        res = await fetch(buildApiUrl(`/leads/import/web-search`), {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: sessionId },
          body: JSON.stringify({
            designation: webSearchDesignation,
            countries: webSearchCountries,
            seniorities: webSearchSeniorities
          }),
        });
        
        const jobData = await parseResponse(res);
        if (!res.ok) {
          throw new Error(jobData.detail || "Failed to start search job");
        }
        
        const jobResult = jobData;
        
        if (jobResult.success && jobResult.job_id) {
          // Store job ID and start polling for status
          setWebSearchJobId(jobResult.job_id);
          setWebSearchProgress({ 
            status: "running", 
            job_id: jobResult.job_id,
            found: 0, 
            imported: 0,
            classified: 0,
            emails_found: 0,
            progress_percent: 0
          });
          
          // Start polling interval for status updates
          const pollInterval = setInterval(async () => {
            try {
              const statusRes = await fetch(
                buildApiUrl(`/leads/import/web-search/status/${jobResult.job_id}`),
                { headers: { Authorization: sessionId } }
              );
              
              if (statusRes.ok) {
                const status = await statusRes.json();
                setWebSearchProgress({
                  status: status.status,
                  job_id: status.job_id,
                  found: status.total_found,
                  imported: status.total_imported,
                  duplicates: status.total_duplicates,
                  classified: status.total_classified,
                  emails_found: status.emails_found,
                  progress_percent: status.progress_percent,
                  current_query: status.current_query,
                  leads_today: status.leads_today,
                  daily_limit: status.daily_limit,
                  errors: status.errors
                });
                
                // Refresh leads list periodically
                if (status.total_imported > 0 && status.total_imported % 50 === 0) {
                  fetchRawLeads();
                  fetchStatistics();
                }
                
                // Stop polling if job is done
                if (["completed", "stopped", "failed", "api_error", "paused"].includes(status.status)) {
                  clearInterval(pollInterval);
                  setImporting(false);
                  fetchRawLeads();
                  fetchStatistics();
                  fetchSearchControl(); // Refresh control panel status
                  
                  if (status.status === "completed") {
                    alert(`✅ Search completed! Imported ${status.total_imported} leads, found ${status.emails_found} emails.`);
                  } else if (status.status === "stopped") {
                    alert(`⏹️ Search stopped. Imported ${status.total_imported} leads so far.`);
                  } else if (status.status === "api_error") {
                    alert(`🔴 API Error: Check your Perplexity/OpenAI API keys in Settings. Imported ${status.total_imported} leads before error.`);
                  } else if (status.status === "paused") {
                    // Don't alert for paused - user can see in control panel
                  }
                }
              }
            } catch (pollError) {
              console.error("Error polling status:", pollError);
            }
          }, 2000); // Poll every 2 seconds
          
          // Store interval ID for cleanup
          window.webSearchPollInterval = pollInterval;
          
          // Don't close modal - keep it open to show progress
          return;
        } else {
          throw new Error(jobResult.message || "Failed to start search job");
        }
      }

      const resultData = await parseResponse(res);
      if (!res.ok) {
        throw new Error(resultData.detail || `Import failed (HTTP ${res.status})`);
      }

      const result = resultData;
      alert(result.message || `Imported ${result.imported} leads`);
      resetImportModal();
      fetchRawLeads();
      fetchStatistics();
    } catch (err) {
      setImportError(err.message);
      setWebSearchProgress(null);
    } finally {
      setImporting(false);
    }
  };

  // Reset import modal state
  const resetImportModal = () => {
    // Clean up polling interval if exists
    if (window.webSearchPollInterval) {
      clearInterval(window.webSearchPollInterval);
      window.webSearchPollInterval = null;
    }
    setShowImportModal(false);
    setImportData("");
    setCsvFile(null);
    setCsvData([]);
    setCsvColumns([]);
    setColumnMapping({});
    setCsvImportStep(1);
    setWebSearchDesignation("");
    setWebSearchCountries([]);
    setWebSearchSeniorities([]);
    setWebSearchProgress(null);
    setWebSearchJobId(null);
    setImportError("");
    // Reset Gmail/Email state
    setSelectedGmailAccounts([]);
    setSelectedGmailSegments([]);
    setGmailMaxEmails(100);
    setGmailImporting(false);
    setGmailImportProgress(null);
    setEnrichmentPhases({ basic: true, names: true, company: true, domain: true });
  };

  // Transfer lead to Vendor Leads
  const handleTransferToVendorLeads = async (leadId) => {
    if (!window.confirm("Transfer this lead to Vendor Leads for qualification?")) {
      return;
    }
    
    try {
      const res = await fetch(buildApiUrl(`/vendor-leads/transfer-from-ai-database`), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: sessionId,
        },
        body: JSON.stringify({ lead_id: leadId }),
      });
      
      if (!res.ok) {
        const error = await res.json();
        throw new Error(error.detail || "Transfer failed");
      }
      
      const result = await res.json();
      alert(`✅ Lead transferred to Vendor Leads successfully!`);
      fetchLeads();
    } catch (err) {
      alert("Error: " + err.message);
    }
  };

  // Bulk transfer selected leads to Vendor Leads
  const handleBulkTransferToVendorLeads = async () => {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) {
      alert("Please select leads to transfer");
      return;
    }
    
    if (!window.confirm(`Transfer ${ids.length} lead(s) to Vendor Leads for qualification?`)) {
      return;
    }
    
    try {
      const res = await fetch(buildApiUrl(`/vendor-leads/bulk-transfer-from-ai-database`), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: sessionId,
        },
        body: JSON.stringify({ lead_ids: ids }),
      });
      
      if (!res.ok) {
        const error = await res.json();
        throw new Error(error.detail || "Transfer failed");
      }
      
      const result = await res.json();
      alert(`✅ ${result.transferred_count} lead(s) transferred to Vendor Leads!`);
      setSelectedIds(new Set());
      fetchLeads();
    } catch (err) {
      alert("Error: " + err.message);
    }
  };

  // Delete all leads
  const handleDeleteAllLeads = async () => {
    if (!window.confirm("⚠️ WARNING: This will delete ALL leads from the database!\n\nAre you absolutely sure you want to delete ALL leads? This action cannot be undone.")) {
      return;
    }
    
    // Double confirmation for safety
    if (!window.confirm("🚨 FINAL CONFIRMATION 🚨\n\nYou are about to delete ALL leads including:\n• Web Search leads\n• CSV imports\n• Email imports\n• All classified leads\n\nClick OK to proceed with deletion.")) {
      return;
    }
    
    setDeletingAllLeads(true);
    try {
      const res = await fetch(buildApiUrl(`/leads/all`), {
        method: "DELETE",
        headers: { Authorization: sessionId },
      });
      
      if (!res.ok) {
        const error = await res.json();
        throw new Error(error.detail || "Delete failed");
      }
      
      const result = await res.json();
      alert(`✅ ${result.message}`);
      fetchRawLeads();
      fetchLeads();
      fetchStatistics();
    } catch (err) {
      alert("Error: " + err.message);
    } finally {
      setDeletingAllLeads(false);
    }
  };

  // Email extraction and enrichment handler (from MongoDB stored emails)
  const handleGmailImport = async () => {
    setGmailImporting(true);
    setImportError("");
    setGmailImportProgress({ status: "running", progress: 0, extracted: 0, enriched: 0, duplicates: 0 });
    
    try {
      const res = await fetch(buildApiUrl(`/leads/emails/extract`), {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: sessionId },
        body: JSON.stringify({
          account_emails: selectedGmailAccounts.length > 0 ? selectedGmailAccounts : null,
          max_emails: gmailMaxEmails,
          segments: selectedGmailSegments.length > 0 ? selectedGmailSegments : null,
          enrichment_phases: enrichmentPhases
        }),
      });
      
      if (!res.ok) {
        const error = await res.json();
        throw new Error(error.detail || "Lead extraction failed");
      }
      
      const result = await res.json();
      setGmailImportProgress({
        status: "complete",
        progress: 100,
        extracted: result.leads_extracted || 0,
        enriched: result.leads_enriched || 0,
        duplicates: result.duplicates || 0
      });
      
      // Show success message after a brief delay
      setTimeout(() => {
        resetImportModal();
        fetchRawLeads();
        fetchLeads();
        fetchStatistics();
      }, 1500);
    } catch (err) {
      setImportError(err.message);
      setGmailImportProgress(null);
    } finally {
      setGmailImporting(false);
    }
  };

  // ============== AI DISCOVERY HANDLERS ==============

  const checkDiscoveryStatus = async () => {
    try {
      const res = await fetch(buildApiUrl(`/leads/discover/status`), {
        headers: { Authorization: sessionId }
      });
      if (res.ok) {
        const data = await res.json();
        setDiscoveryStatus(data);
      }
    } catch (err) {
      console.error("Error checking discovery status:", err);
    }
  };

  const handleDiscoverCompanies = async () => {
    if (!discoveryIndustry || !discoveryDesignation) {
      setDiscoveryError("Please enter both industry and designation");
      return;
    }
    
    setDiscoveryLoading(true);
    setDiscoveryError("");
    
    try {
      // Use new direct discovery endpoint - finds contacts directly without Google CSE
      const res = await fetch(buildApiUrl(`/leads/ai-database/discover-leads`), {
        method: "POST",
        headers: { 
          "Content-Type": "application/json", 
          Authorization: sessionId 
        },
        body: JSON.stringify({
          designation: discoveryDesignation,
          industry: discoveryIndustry,
          location: discoveryLocation || "USA",
          count: 20,
          criteria: discoveryCriteria
        })
      });
      
      if (!res.ok) {
        const error = await res.json();
        throw new Error(error.detail || "Discovery failed");
      }
      
      const data = await res.json();
      // Set discovered contacts directly and move to preview
      setDiscoveryContacts(data.contacts || []);
      setSelectedContacts(data.contacts || []); // Pre-select all
      setDiscoveryStep(2);
      
      // Show success message
      alert(`✅ Discovered ${data.contacts_found} contacts. ${data.leads_imported} leads auto-imported. Cost: ${data.cost_estimate}`);
    } catch (err) {
      setDiscoveryError(err.message);
    } finally {
      setDiscoveryLoading(false);
    }
  };

  const toggleCompanySelection = (company) => {
    setSelectedCompanies(prev => {
      const exists = prev.find(c => c.name === company.name);
      if (exists) {
        return prev.filter(c => c.name !== company.name);
      }
      return [...prev, company];
    });
  };

  const handleFindContacts = async () => {
    if (selectedCompanies.length === 0) {
      setDiscoveryError("Please select at least one company");
      return;
    }
    if (!discoveryDesignation) {
      setDiscoveryError("Please enter a target designation");
      return;
    }
    
    setDiscoveryLoading(true);
    setDiscoveryError("");
    
    try {
      const res = await fetch(buildApiUrl(`/leads/discover/contacts`), {
        method: "POST",
        headers: { 
          "Content-Type": "application/json", 
          Authorization: sessionId 
        },
        body: JSON.stringify({
          companies: selectedCompanies.map(c => ({ name: c.name, description: c.description })),
          designation: discoveryDesignation,
          limit_per_company: 5
        })
      });
      
      if (!res.ok) {
        const error = await res.json();
        throw new Error(error.detail || "Contact search failed");
      }
      
      const data = await res.json();
      setDiscoveryContacts(data.contacts || []);
      setDiscoveryStep(3);
    } catch (err) {
      setDiscoveryError(err.message);
    } finally {
      setDiscoveryLoading(false);
    }
  };

  const toggleContactSelection = (contact) => {
    setSelectedContacts(prev => {
      const idx = prev.findIndex(c => c.linkedin_url === contact.linkedin_url);
      if (idx > -1) {
        return prev.filter((_, i) => i !== idx);
      }
      return [...prev, contact];
    });
  };

  const toggleAllContacts = () => {
    if (selectedContacts.length === discoveryContacts.length) {
      setSelectedContacts([]);
    } else {
      setSelectedContacts([...discoveryContacts]);
    }
  };

  const handleImportDiscoveredContacts = async () => {
    if (selectedContacts.length === 0) {
      setDiscoveryError("Please select at least one contact to import");
      return;
    }
    
    setDiscoveryLoading(true);
    setDiscoveryError("");
    
    try {
      const res = await fetch(buildApiUrl(`/leads/discover/import`), {
        method: "POST",
        headers: { 
          "Content-Type": "application/json", 
          Authorization: sessionId 
        },
        body: JSON.stringify({
          contacts: selectedContacts
        })
      });
      
      if (!res.ok) {
        const error = await res.json();
        throw new Error(error.detail || "Import failed");
      }
      
      const data = await res.json();
      alert(`Successfully imported ${data.imported} contacts!`);
      resetImportModal();
      fetchLeads();
      fetchRawLeads();
      fetchStatistics();
    } catch (err) {
      setDiscoveryError(err.message);
    } finally {
      setDiscoveryLoading(false);
    }
  };

  const resetDiscovery = () => {
    setDiscoveryStep(1);
    setDiscoveredCompanies([]);
    setSelectedCompanies([]);
    setDiscoveryContacts([]);
    setSelectedContacts([]);
    setDiscoveryError("");
  };

  // ============== CLASSIFY HANDLER ==============

  const handleClassify = async (leadIds = null) => {
    setClassifying(true);
    try {
      // When leadIds is null, classify ALL pending leads (no batch_size limit)
      const res = await fetch(buildApiUrl(`/leads/classify`), {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: sessionId },
        body: JSON.stringify({ lead_ids: leadIds }),
      });

      if (!res.ok) throw new Error("Classification failed");
      const result = await res.json();
      alert(result.message);

      setTimeout(() => {
        fetchLeads();
        fetchRawLeads();
        fetchStatistics();
      }, 2000);
    } catch (err) {
      alert("Classification error: " + err.message);
    } finally {
      setClassifying(false);
    }
  };

  // ============== SELECTION ==============

  const toggleSelectAll = () => {
    const currentList = getDisplayLeads();
    if (selectedIds.size === currentList.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(currentList.map(l => l._id)));
    }
  };

  const toggleSelect = (id) => {
    const newSet = new Set(selectedIds);
    if (newSet.has(id)) newSet.delete(id);
    else newSet.add(id);
    setSelectedIds(newSet);
  };

  // ============== FILTER HANDLERS ==============

  const handleFilterChange = (key, value) => {
    setFilters(prev => ({ ...prev, [key]: value }));
    setCurrentPage(1);
  };

  const clearFilters = () => {
    setFilters({
      seniority_level: "",
      department: "",
      persona: "",
      company_size: "",
      min_confidence: "",
    });
    setSearchQuery("");
    setCurrentPage(1);
  };

  // ============== TAB COUNT HELPERS ==============
  
  // Helper to check if a lead belongs to AI Database stage
  const isInAIDatabase = (lead) => {
    // A lead is in AI Database if stage is 'ai_database', undefined, null, or empty
    // Backend uses 'stage' field, not 'lead_stage'
    const stage = lead.stage || lead.lead_stage;
    return !stage || stage === 'ai_database' || stage === '';
  };

  const getPendingCount = () => {
    return rawLeads.filter(l => {
      if (!isInAIDatabase(l)) return false; // Exclude leads moved to other stages
      const isCsv = l.source === "csv" || l.source === "csv_import" || l.source === "google_sheets" || l.source === "json_import";
      const hasEmail = l.email && l.email.trim() !== "";
      if (isCsv && hasEmail) return false;
      return l.classification_status === "Pending";
    }).length;
  };

  const getCsvCount = () => {
    const enrichedCsv = leads.filter(l => isInAIDatabase(l) && (l.source === "csv" || l.source === "csv_import" || l.source === "google_sheets" || l.source === "json_import"));
    const rawCsvWithEmail = rawLeads.filter(l => {
      if (!isInAIDatabase(l)) return false; // Exclude leads moved to other stages
      const isCsv = l.source === "csv" || l.source === "csv_import" || l.source === "google_sheets" || l.source === "json_import";
      const hasEmail = l.email && l.email.trim() !== "";
      const notEnriched = !leads.some(e => e._id === l._id || e.email === l.email);
      return isCsv && hasEmail && notEnriched;
    });
    return enrichedCsv.length + rawCsvWithEmail.length;
  };

  // ============== GET DISPLAY DATA ==============

  const getDisplayLeads = () => {
    if (activeTab === "pending") {
      // Exclude CSV records that have an email (they go to classified-csv)
      return rawLeads.filter(l => {
        if (!isInAIDatabase(l)) return false; // Exclude leads moved to other stages
        const isCsv = l.source === "csv" || l.source === "csv_import" || l.source === "google_sheets" || l.source === "json_import";
        const hasEmail = l.email && l.email.trim() !== "";
        // If it's CSV with email, it goes to classified-csv, not pending
        if (isCsv && hasEmail) return false;
        return l.classification_status === "Pending";
      });
    } else if (activeTab === "classified-websearch" || activeTab === "classified-csv" || activeTab === "classified-gmail") {
      // Backend already filters by source for these tabs, just filter by stage
      return leads.filter(l => isInAIDatabase(l));
    } else if (activeTab === "classified") {
      return leads.filter(l => isInAIDatabase(l));
    }
    // "all" tab - show raw leads
    return rawLeads.filter(l => isInAIDatabase(l));
  };

  const displayLeads = getDisplayLeads();

  // ============== HELPER FUNCTIONS ==============

  const getConfidenceClass = (score) => {
    if (!score) return "low";
    if (score >= 0.8) return "high";
    if (score >= 0.5) return "medium";
    return "low";
  };

  // ============== RENDER ==============

  if (loading) {
    return (
      <div className="ai-leads-page">
        <div className="loading-container">
          <div className="loading-spinner"></div>
          <span>Loading leads...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="ai-leads-page">
      {/* Page Header */}
      <div className="page-header">
        <div className="header-left">
          <h1>🤖 AI Database</h1>
          <p className="subtitle">Import, classify, and manage LinkedIn leads with AI</p>
        </div>
        <div className="header-actions">
          <button className="btn btn-outline" onClick={() => navigate(-1)}>
            ← Back
          </button>
          <button className="btn btn-primary" onClick={() => setShowImportModal(true)}>
            📥 Import Leads
          </button>
          <button 
            className="btn btn-success"
            onClick={() => handleClassify()}
            disabled={classifying}
          >
            {classifying ? "⏳ Classifying..." : "🤖 Classify All"}
          </button>
        </div>
      </div>

      {/* Stats Cards */}
      <div className="stats-row">
        <div className="stat-card">
          <div className="stat-value">{statistics?.raw?.total || 0}</div>
          <div className="stat-label">Total Raw Leads</div>
        </div>
        <div className="stat-card warning">
          <div className="stat-value">{statistics?.raw?.pending || 0}</div>
          <div className="stat-label">Pending Classification</div>
        </div>
        <div className="stat-card info">
          <div className="stat-value">{statistics?.raw?.processing || 0}</div>
          <div className="stat-label">Processing</div>
        </div>
        <div className="stat-card success">
          <div className="stat-value">{statistics?.raw?.classified || 0}</div>
          <div className="stat-label">Classified</div>
        </div>
        <div className="stat-card danger">
          <div className="stat-value">{statistics?.raw?.failed || 0}</div>
          <div className="stat-label">Failed</div>
        </div>
        <div className="stat-card primary">
          <div className="stat-value">{statistics?.enriched?.total || 0}</div>
          <div className="stat-label">Enriched Leads</div>
        </div>
      </div>

      {/* Tabs */}
      <div className="tabs-row">
        <button 
          className={`tab-btn ${activeTab === "all" ? "active" : ""}`}
          onClick={() => setActiveTab("all")}
        >
          All Leads ({leads.length})
        </button>
        <button 
          className={`tab-btn ${activeTab === "pending" ? "active" : ""}`}
          onClick={() => setActiveTab("pending")}
        >
          Pending ({getPendingCount()})
        </button>
        <button 
          className={`tab-btn ${activeTab === "classified-websearch" ? "active" : ""}`}
          onClick={() => setActiveTab("classified-websearch")}
        >
          Classified (Web Search) ({statistics?.by_source?.websearch?.classified_count || leads.filter(l => l.source === "web_search" || l.source === "google_search" || l.source === "linkedin").length})
        </button>
        <button 
          className={`tab-btn ${activeTab === "classified-csv" ? "active" : ""}`}
          onClick={() => setActiveTab("classified-csv")}
        >
          Classified (CSV Upload) ({statistics?.by_source?.csv?.classified_count || getCsvCount()})
        </button>
        <button 
          className={`tab-btn ${activeTab === "classified-gmail" ? "active" : ""}`}
          onClick={() => setActiveTab("classified-gmail")}
        >
          Classified (Gmail) ({statistics?.by_source?.gmail?.classified_count || leads.filter(l => ["gmail", "gmail_workspace", "email_sync", "email_import", "email_classification", "gmail_api", "gmail_archive"].includes(l.source)).length})
        </button>
      </div>

      {/* Filters Bar */}
      <div className="filters-bar">
        <input
          type="text"
          className="search-input"
          placeholder="🔍 Search leads..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
        />
        <select
          className="filter-select"
          value={filters.seniority_level}
          onChange={(e) => handleFilterChange("seniority_level", e.target.value)}
        >
          <option value="">All Seniority</option>
          {SENIORITY_OPTIONS.map(opt => (
            <option key={opt} value={opt}>{opt}</option>
          ))}
        </select>
        <select
          className="filter-select"
          value={filters.department}
          onChange={(e) => handleFilterChange("department", e.target.value)}
        >
          <option value="">All Departments</option>
          {DEPARTMENT_OPTIONS.map(opt => (
            <option key={opt} value={opt}>{opt}</option>
          ))}
        </select>
        <select
          className="filter-select"
          value={filters.persona}
          onChange={(e) => handleFilterChange("persona", e.target.value)}
        >
          <option value="">All Personas</option>
          {PERSONA_OPTIONS.map(opt => (
            <option key={opt} value={opt}>{opt}</option>
          ))}
        </select>
        <button className="btn btn-outline btn-sm" onClick={clearFilters}>
          Clear
        </button>
        
        {/* View Mode Toggle */}
        {activeTab.startsWith("classified") && (
          <div className="view-toggle">
            <button 
              className={`view-btn ${viewMode === "compact" ? "active" : ""}`}
              onClick={() => setViewMode("compact")}
              title="Compact View"
            >
              ▤
            </button>
            <button 
              className={`view-btn ${viewMode === "full" ? "active" : ""}`}
              onClick={() => setViewMode("full")}
              title="Full Table View"
            >
              ▦
            </button>
          </div>
        )}
        
        {/* Delete All Leads Button */}
        <button 
          className="btn btn-danger btn-sm"
          onClick={handleDeleteAllLeads}
          disabled={deletingAllLeads}
          style={{ marginLeft: "auto", backgroundColor: "#dc2626", color: "white" }}
        >
          {deletingAllLeads ? "⏳ Deleting..." : "🗑️ Delete All Leads"}
        </button>
      </div>

      {/* Selection Bar */}
      {selectedIds.size > 0 && (
        <div className="selection-bar">
          <span>{selectedIds.size} lead(s) selected</span>
          <button 
            className="btn btn-sm" 
            onClick={() => {
              const selectedLeads = leads.filter(l => selectedIds.has(l._id))
              console.log("🚀 Sending to workflow:", { 
                selectedLeadsCount: selectedLeads.length, 
                selectedLeads,
                selectedIds: Array.from(selectedIds)
              })
              navigate("/admin/sales/campaign/workflow", {
                state: { 
                  contacts: selectedLeads,
                  list: { name: "AI Database Leads" }
                }
              })
            }}
            style={{ backgroundColor: "#9333ea", color: "#fff", borderColor: "#9333ea" }}
          >
            🔄 Create Workflow
          </button>
          <button className="btn btn-sm btn-primary" onClick={() => handleClassify(Array.from(selectedIds))}>
            🤖 Classify Selected
          </button>
          <button className="btn btn-sm btn-success" onClick={handleBulkTransferToVendorLeads} style={{ backgroundColor: "#22c55e", borderColor: "#22c55e" }}>
            🎯 Transfer to Vendor Leads
          </button>
          <button className="btn btn-sm btn-outline" onClick={() => setSelectedIds(new Set())}>
            ✕ Clear
          </button>
        </div>
      )}

      {/* Data Table */}
      <div className="table-wrapper">
        {displayLeads.length === 0 ? (
          <div className="empty-state">
            <div className="empty-icon">📋</div>
            <h2>No leads found</h2>
            <p>Import some leads to get started.</p>
            <button className="btn btn-primary" onClick={() => setShowImportModal(true)}>
              📥 Import Leads
            </button>
          </div>
        ) : activeTab.startsWith("classified") ? (
          /* Classified Leads Table - Compact or Full view */
          <div className="classified-table-container">
            <table className={`data-table classified-table ${viewMode === "compact" ? "compact-view" : "full-view"}`}>
              <thead>
                <tr>
                  <th className="checkbox-col sticky-col">
                    <input
                      type="checkbox"
                      checked={selectedIds.size === displayLeads.length && displayLeads.length > 0}
                      onChange={toggleSelectAll}
                    />
                  </th>
                  <th className="sticky-col-2">Name</th>
                  <th>Email</th>
                  <th>Title</th>
                  <th>Company</th>
                  <th>Seniority</th>
                  <th>Industry</th>
                  <th>Source</th>
                  <th>Email Status</th>
                  {viewMode === "full" && (
                    <>
                      <th>First Name</th>
                      <th>Last Name</th>
                      <th>LinkedIn</th>
                      <th>Location</th>
                      <th>Added On</th>
                      <th>Buying Role</th>
                      <th>Company Domain</th>
                      <th>Company Website</th>
                      <th>Employee Count</th>
                      <th>Employee Range</th>
                      <th>Founded</th>
                      <th>Company Type</th>
                      <th>Headquarters</th>
                      <th>Revenue Range</th>
                      <th>Company LinkedIn</th>
                    </>
                  )}
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {displayLeads.map((lead) => (
                  <React.Fragment key={lead._id}>
                    <tr className={`${selectedIds.has(lead._id) ? "selected" : ""} ${expandedLeadId === lead._id ? "expanded" : ""}`}>
                      <td className="checkbox-col sticky-col">
                        <input
                          type="checkbox"
                          checked={selectedIds.has(lead._id)}
                          onChange={() => toggleSelect(lead._id)}
                        />
                      </td>
                      <td className="name-cell sticky-col-2">
                        <span 
                          className="name-link" 
                          onClick={() => navigate(`/admin/sales/campaign/ai-leads/${lead._id}`)}
                        >
                          {lead.name}
                        </span>
                      </td>
                      <td className="email-cell">{lead.email || "-"}</td>
                      <td>{lead.title || "-"}</td>
                      <td>{lead.company_name || "-"}</td>
                      <td><span className="badge badge-blue">{lead.seniority_level || "Unknown"}</span></td>
                      <td>{lead.company_industry || "-"}</td>
                      <td>
                        <span className={`source-badge ${lead.source?.replace("_", "-") || "unknown"}`}>
                          {lead.source === "web_search" ? "🌐 Web" : 
                           lead.source === "google_search" ? "🔍 Google" :
                           lead.source === "csv" || lead.source === "csv_import" ? "📄 CSV" :
                           lead.source === "linkedin" ? "💼 LinkedIn" :
                           lead.source || "Unknown"}
                        </span>
                      </td>
                      <td>
                        <span className={`status-badge ${(lead.email_status || "unknown").toLowerCase().replace(" ", "-")}`}>
                          {lead.email_status || "Unknown"}
                        </span>
                      </td>
                      {viewMode === "full" && (
                        <>
                          <td>{lead.first_name || "-"}</td>
                          <td>{lead.last_name || "-"}</td>
                          <td>
                            <a href={lead.linkedin_url} target="_blank" rel="noopener noreferrer" className="linkedin-link">
                              View ↗
                            </a>
                          </td>
                          <td>{lead.location || "-"}</td>
                          <td>{lead.added_on ? new Date(lead.added_on).toLocaleDateString() : "-"}</td>
                          <td><span className="badge badge-orange">{lead.buying_role || "Unknown"}</span></td>
                          <td>{lead.company_domain || "-"}</td>
                          <td>
                            {lead.company_website ? (
                              <a href={lead.company_website.startsWith("http") ? lead.company_website : `https://${lead.company_website}`} target="_blank" rel="noopener noreferrer">
                                {lead.company_website}
                              </a>
                            ) : "-"}
                          </td>
                          <td>{lead.company_employee_count || "-"}</td>
                          <td>{lead.company_employee_count_range || "-"}</td>
                          <td>{lead.company_founded || "-"}</td>
                          <td>{lead.company_type || "-"}</td>
                          <td>{lead.company_headquarters || "-"}</td>
                          <td>{lead.company_revenue_range || "-"}</td>
                          <td>
                            {lead.company_linkedin_url ? (
                              <a href={lead.company_linkedin_url} target="_blank" rel="noopener noreferrer">
                                View ↗
                              </a>
                            ) : "-"}
                          </td>
                        </>
                      )}
                      <td className="actions-cell">
                        <a href={lead.linkedin_url} target="_blank" rel="noopener noreferrer" className="action-link action-btn-linkedin">
                          LinkedIn ↗
                        </a>
                        <button className="action-btn" onClick={() => handleClassify([lead._id])}>
                          Re
                        </button>
                        <button 
                          className="action-btn" 
                          onClick={() => handleTransferToVendorLeads(lead._id)}
                          title="Transfer to Vendor Leads"
                          style={{ backgroundColor: "#dcfce7", color: "#166534" }}
                        >
                          🎯
                        </button>
                      </td>
                    </tr>
                    {/* Expandable Details Row in Compact Mode */}
                    {viewMode === "compact" && expandedLeadId === lead._id && (
                      <tr className="expanded-details-row">
                        <td colSpan={10}>
                          <div className="lead-details-panel">
                            <div className="details-grid">
                              <div className="detail-group">
                                <h4>Contact Info</h4>
                                <p><strong>First Name:</strong> {lead.first_name || "-"}</p>
                                <p><strong>Last Name:</strong> {lead.last_name || "-"}</p>
                                <p><strong>Email Status:</strong> <span className={`status-badge ${(lead.email_status || "unknown").toLowerCase().replace(" ", "-")}`}>{lead.email_status || "Unknown"}</span></p>
                                <p><strong>Location:</strong> {lead.location || "-"}</p>
                                <p><strong>LinkedIn:</strong> {lead.linkedin_url ? <a href={lead.linkedin_url} target="_blank" rel="noopener noreferrer">View Profile ↗</a> : "-"}</p>
                              </div>
                              <div className="detail-group">
                                <h4>Role Details</h4>
                                <p><strong>Buying Role:</strong> <span className="badge badge-orange">{lead.buying_role || "Unknown"}</span></p>
                                <p><strong>Added On:</strong> {lead.added_on ? new Date(lead.added_on).toLocaleDateString() : "-"}</p>
                              </div>
                              <div className="detail-group">
                                <h4>Company Info</h4>
                                <p><strong>Domain:</strong> {lead.company_domain || "-"}</p>
                                <p><strong>Website:</strong> {lead.company_website ? <a href={lead.company_website.startsWith("http") ? lead.company_website : `https://${lead.company_website}`} target="_blank" rel="noopener noreferrer">{lead.company_website}</a> : "-"}</p>
                                <p><strong>Employees:</strong> {lead.company_employee_count || lead.company_employee_count_range || "-"}</p>
                                <p><strong>Founded:</strong> {lead.company_founded || "-"}</p>
                                <p><strong>Type:</strong> {lead.company_type || "-"}</p>
                                <p><strong>Headquarters:</strong> {lead.company_headquarters || "-"}</p>
                                <p><strong>Revenue:</strong> {lead.company_revenue_range || "-"}</p>
                                <p><strong>LinkedIn:</strong> {lead.company_linkedin_url ? <a href={lead.company_linkedin_url} target="_blank" rel="noopener noreferrer">View ↗</a> : "-"}</p>
                              </div>
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          /* Raw/Pending Leads Table - Simple view */
          <table className="data-table">
            <thead>
              <tr>
                <th className="checkbox-col">
                  <input
                    type="checkbox"
                    checked={selectedIds.size === displayLeads.length && displayLeads.length > 0}
                    onChange={toggleSelectAll}
                  />
                </th>
                <th>Name</th>
                <th>Job Title</th>
                <th>Company</th>
                <th>Source</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {displayLeads.map((lead) => (
                <tr key={lead._id} className={selectedIds.has(lead._id) ? "selected" : ""}>
                  <td className="checkbox-col">
                    <input
                      type="checkbox"
                      checked={selectedIds.has(lead._id)}
                      onChange={() => toggleSelect(lead._id)}
                    />
                  </td>
                  <td className="name-cell">
                    <span 
                      className="name-link" 
                      onClick={() => navigate(`/admin/sales/campaign/ai-leads/${lead._id}`)}
                    >
                      {lead.name}
                    </span>
                  </td>
                  <td>{lead.title || lead.job_title || "-"}</td>
                  <td>{lead.company_name || "-"}</td>
                  <td>
                    <span className={`source-badge ${lead.source?.replace("_", "-") || "unknown"}`}>
                      {lead.source === "web_search" ? "🌐 Web" : 
                       lead.source === "google_search" ? "🔍 Google" :
                       lead.source === "csv" || lead.source === "csv_import" ? "📄 CSV" :
                       lead.source === "linkedin" ? "💼 LinkedIn" :
                       lead.source || "Unknown"}
                    </span>
                  </td>
                  <td>
                    <span className={`status-pill ${lead.classification_status?.toLowerCase()}`}>
                      {lead.classification_status}
                    </span>
                  </td>
                  <td className="actions-cell">
                    <a href={lead.linkedin_url} target="_blank" rel="noopener noreferrer" className="action-link action-btn-linkedin">
                      LinkedIn ↗
                    </a>
                    {lead.classification_status === "Pending" && (
                      <button className="action-btn" onClick={() => handleClassify([lead._id])}>
                        Classify
                      </button>
                    )}
                    <button 
                      className="action-btn" 
                      onClick={() => handleTransferToVendorLeads(lead._id)}
                      title="Transfer to Vendor Leads"
                      style={{ backgroundColor: "#dcfce7", color: "#166534" }}
                    >
                      🎯
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && activeTab.startsWith("classified") && (
        <div className="pagination-bar">
          <button 
            className="btn btn-outline btn-sm"
            disabled={currentPage === 1} 
            onClick={() => setCurrentPage(p => p - 1)}
          >
            ← Previous
          </button>
          <span className="page-info">Page {currentPage} of {totalPages}</span>
          <button 
            className="btn btn-outline btn-sm"
            disabled={currentPage === totalPages} 
            onClick={() => setCurrentPage(p => p + 1)}
          >
            Next →
          </button>
        </div>
      )}

      {/* Import Modal */}
      {showImportModal && (
        <div className="modal-overlay" onClick={() => resetImportModal()}>
          <div className="modal-box modal-large" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>📥 Import Leads</h2>
              <button className="modal-close-btn" onClick={() => resetImportModal()}>×</button>
            </div>

            <div className="modal-body">
              {/* Import Method Tabs */}
              <div className="import-method-tabs">
                <button 
                  className={`method-tab ${importMethod === "web-search" ? "active" : ""}`}
                  onClick={() => { setImportMethod("web-search"); setCsvImportStep(1); }}
                >
                  🌐 Web Search
                </button>
                <button 
                  className={`method-tab ${importMethod === "csv" ? "active" : ""}`}
                  onClick={() => { setImportMethod("csv"); setCsvImportStep(1); }}
                >
                  📄 CSV Upload
                </button>
                <button 
                  className={`method-tab ${importMethod === "gmail" ? "active" : ""}`}
                  onClick={() => { setImportMethod("gmail"); setCsvImportStep(1); fetchGmailAccounts(); fetchGmailSegments(); }}
                >
                  📧 Gmail
                </button>
                <button 
                  className={`method-tab ${importMethod === "ai-discovery" ? "active" : ""}`}
                  onClick={() => { setImportMethod("ai-discovery"); setCsvImportStep(1); resetDiscovery(); checkDiscoveryStatus(); }}
                >
                  🔮 AI Discovery
                </button>
              </div>

              {/* Error Display */}
              {importError && (
                <div className="error-alert">{importError}</div>
              )}

              {/* AI Discovery (Perplexity Direct) */}
              {importMethod === "ai-discovery" && (
                <div className="import-form">
                  <h3>🔮 AI-Powered Lead Discovery</h3>
                  <p className="form-hint">
                    Use Perplexity AI to discover contacts directly. Streamlined 2-step pipeline: Perplexity finds contacts → OpenAI enriches. Cost: ~$0.001/lead
                  </p>
                  
                  {discoveryError && (
                    <div className="error-alert">{discoveryError}</div>
                  )}
                  
                  {discoveryStatus && !discoveryStatus.enabled && (
                    <div className="warning-alert" style={{ background: '#fef3c7', border: '1px solid #f59e0b', padding: '1rem', borderRadius: '8px', marginBottom: '1rem' }}>
                      ⚠️ Perplexity discovery is not configured. Please add your API key in <a href="/admin/settings">Settings</a>.
                    </div>
                  )}
                  
                  {/* Step 1: Search for Leads Directly */}
                  {discoveryStep === 1 && (
                    <div className="discovery-step">
                      <h4>Step 1: Discover Leads</h4>
                      <div className="form-grid" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                        <div className="form-group">
                          <label>Target Designation *</label>
                          <input
                            type="text"
                            className="form-input"
                            placeholder="e.g., CEO, VP Sales, Director of Marketing"
                            value={discoveryDesignation}
                            onChange={(e) => setDiscoveryDesignation(e.target.value)}
                          />
                        </div>
                        <div className="form-group">
                          <label>Industry *</label>
                          <input
                            type="text"
                            className="form-input"
                            placeholder="e.g., fintech, healthtech, SaaS"
                            value={discoveryIndustry}
                            onChange={(e) => setDiscoveryIndustry(e.target.value)}
                          />
                        </div>
                        <div className="form-group">
                          <label>Location (optional)</label>
                          <input
                            type="text"
                            className="form-input"
                            placeholder="e.g., California, India, Europe"
                            value={discoveryLocation}
                            onChange={(e) => setDiscoveryLocation(e.target.value)}
                          />
                        </div>
                        <div className="form-group">
                          <label>Additional Criteria (optional)</label>
                          <input
                            type="text"
                            className="form-input"
                            placeholder="e.g., funded startups, enterprise, B2B"
                            value={discoveryCriteria}
                            onChange={(e) => setDiscoveryCriteria(e.target.value)}
                          />
                        </div>
                      </div>
                      <button 
                        className="btn btn-primary" 
                        onClick={handleDiscoverCompanies}
                        disabled={discoveryLoading || !discoveryIndustry || !discoveryDesignation || (discoveryStatus && !discoveryStatus.enabled)}
                        style={{ marginTop: '1rem' }}
                      >
                        {discoveryLoading ? "Discovering..." : "🔍 Discover Leads"}
                      </button>
                    </div>
                  )}
                  
                  {/* Step 2: Preview Discovered Contacts */}
                  {discoveryStep === 2 && (
                    <div className="discovery-step">
                      <h4>Step 2: Preview Contacts ({selectedContacts.length}/{discoveryContacts.length})</h4>
                      <p className="form-hint-small">Leads have been auto-imported. Review or adjust selection below:</p>
                      
                      <div style={{ marginBottom: '0.5rem' }}>
                        <label style={{ cursor: 'pointer' }}>
                          <input
                            type="checkbox"
                            checked={selectedContacts.length === discoveryContacts.length && discoveryContacts.length > 0}
                            onChange={toggleAllContacts}
                          />
                          <span style={{ marginLeft: '0.5rem' }}>Select All</span>
                        </label>
                      </div>
                      
                      <div style={{ maxHeight: '350px', overflow: 'auto', border: '1px solid #e5e7eb', borderRadius: '8px' }}>
                        <table style={{ width: '100%', fontSize: '0.875rem', borderCollapse: 'collapse' }}>
                          <thead style={{ background: '#f9fafb', position: 'sticky', top: 0 }}>
                            <tr>
                              <th style={{ padding: '0.75rem', textAlign: 'left' }}>Select</th>
                              <th style={{ padding: '0.75rem', textAlign: 'left' }}>Name</th>
                              <th style={{ padding: '0.75rem', textAlign: 'left' }}>Title</th>
                              <th style={{ padding: '0.75rem', textAlign: 'left' }}>Company</th>
                              <th style={{ padding: '0.75rem', textAlign: 'left' }}>Link</th>
                            </tr>
                          </thead>
                          <tbody>
                            {discoveryContacts.map((contact, idx) => (
                              <tr key={idx} style={{ borderBottom: '1px solid #f3f4f6' }}>
                                <td style={{ padding: '0.75rem' }}>
                                  <input
                                    type="checkbox"
                                    checked={selectedContacts.some(c => c.linkedin_url === contact.linkedin_url)}
                                    onChange={() => toggleContactSelection(contact)}
                                  />
                                </td>
                                <td style={{ padding: '0.75rem' }}>{contact.name || '-'}</td>
                                <td style={{ padding: '0.75rem' }}>{contact.title || '-'}</td>
                                <td style={{ padding: '0.75rem' }}>{contact.discovered_company || contact.company_name || '-'}</td>
                                <td style={{ padding: '0.75rem' }}>
                                  {contact.linkedin_url && (
                                    <a href={contact.linkedin_url} target="_blank" rel="noopener noreferrer">
                                      LinkedIn ↗
                                    </a>
                                  )}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                      
                      <div style={{ display: 'flex', gap: '1rem', marginTop: '1rem' }}>
                        <button className="btn btn-secondary" onClick={() => setDiscoveryStep(1)}>
                          ← New Search
                        </button>
                        <button 
                          className="btn btn-primary" 
                          onClick={() => { fetchLeads(); setShowImportModal(false); }}
                          disabled={discoveryLoading}
                        >
                          ✅ Done - View Leads
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Web Search (Enhanced with Multi-Select Filters) */}
              {importMethod === "web-search" && (
                <div className="import-form">
                  <h3>🔍 Search LinkedIn Profiles</h3>
                  
                  {/* Search Control Panel */}
                  <div style={{
                    marginBottom: "1rem",
                    padding: "0.75rem 1rem",
                    borderRadius: "8px",
                    border: "1px solid " + (searchControl.circuit_breaker_open ? "#fecaca" : searchControl.global_paused ? "#fed7aa" : "#e5e7eb"),
                    backgroundColor: searchControl.circuit_breaker_open ? "#fef2f2" : searchControl.global_paused ? "#fff7ed" : "#f9fafb"
                  }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "0.5rem" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
                        {/* Status indicator */}
                        <div style={{ 
                          width: "10px", 
                          height: "10px", 
                          borderRadius: "50%", 
                          backgroundColor: searchControl.circuit_breaker_open ? "#ef4444" : 
                                           searchControl.global_paused ? "#f59e0b" : "#22c55e"
                        }} />
                        <span style={{ fontWeight: "500", color: "#374151" }}>
                          {searchControl.circuit_breaker_open ? "🔴 Circuit Breaker Open" :
                           searchControl.global_paused ? "⏸️ Search Paused" : "🟢 Search Active"}
                        </span>
                        {searchControl.active_jobs_count > 0 && (
                          <span style={{ 
                            fontSize: "0.75rem", 
                            backgroundColor: "#dbeafe", 
                            color: "#1e40af", 
                            padding: "0.125rem 0.5rem", 
                            borderRadius: "9999px" 
                          }}>
                            {searchControl.active_jobs_count} job{searchControl.active_jobs_count !== 1 ? 's' : ''} active
                          </span>
                        )}
                      </div>
                      
                      <div style={{ display: "flex", gap: "0.5rem" }}>
                        {/* Pause/Resume Toggle */}
                        {searchControl.global_paused || searchControl.circuit_breaker_open ? (
                          <button
                            className="btn btn-sm"
                            style={{ backgroundColor: "#22c55e", color: "white", padding: "0.25rem 0.75rem" }}
                            onClick={handleResumeSearch}
                            disabled={searchControlLoading}
                          >
                            ▶️ Resume
                          </button>
                        ) : (
                          <button
                            className="btn btn-sm"
                            style={{ backgroundColor: "#f59e0b", color: "white", padding: "0.25rem 0.75rem" }}
                            onClick={handlePauseSearch}
                            disabled={searchControlLoading}
                          >
                            ⏸️ Pause
                          </button>
                        )}
                        
                        {/* Emergency Stop */}
                        <button
                          className="btn btn-sm"
                          style={{ backgroundColor: "#dc2626", color: "white", padding: "0.25rem 0.75rem" }}
                          onClick={handleStopAllJobs}
                          disabled={searchControlLoading || searchControl.active_jobs_count === 0}
                          title="Stop all running jobs immediately"
                        >
                          🚨 Stop All
                        </button>
                      </div>
                    </div>
                    
                    {/* Error message if circuit breaker tripped */}
                    {searchControl.circuit_breaker_open && searchControl.last_error && (
                      <div style={{ 
                        marginTop: "0.5rem", 
                        padding: "0.5rem", 
                        backgroundColor: "#fee2e2", 
                        borderRadius: "4px",
                        fontSize: "0.875rem",
                        color: "#991b1b"
                      }}>
                        <strong>Error:</strong> {searchControl.last_error.message || "API errors detected"}
                        <br />
                        <small>After {searchControl.consecutive_errors} consecutive errors, the circuit breaker tripped. Click Resume to reset.</small>
                      </div>
                    )}
                    
                    {/* Paused reason */}
                    {searchControl.global_paused && searchControl.paused_reason && !searchControl.circuit_breaker_open && (
                      <div style={{ 
                        marginTop: "0.5rem", 
                        fontSize: "0.875rem",
                        color: "#92400e"
                      }}>
                        Reason: {searchControl.paused_reason}
                      </div>
                    )}
                  </div>
                  
                  <p className="form-hint">
                    Configure filters to search for LinkedIn profiles. The system will search up to 10,000 leads using multiple query combinations.
                  </p>
                  
                  <div className="form-grid">
                    {/* Designation - Open-ended text input with suggestions */}
                    <div className="form-group" style={{ gridColumn: "1 / -1" }}>
                      <label>Designation / Title (multiple, comma-separated)</label>
                      <input
                        type="text"
                        className="form-input"
                        placeholder="e.g., CEO, VP Sales, Director of Marketing"
                        value={webSearchDesignation}
                        onChange={(e) => setWebSearchDesignation(e.target.value)}
                      />
                      <small className="form-hint-small">Enter job titles separated by commas</small>
                    </div>
                    
                    {/* Country / Region - Multi-select checkboxes */}
                    <div className="form-group">
                      <label>Countries / Regions (select multiple)</label>
                      <div className="multi-select-container">
                        <div className="multi-select-header">
                          <span>{webSearchCountries.length} selected</span>
                          {webSearchCountries.length > 0 && (
                            <button type="button" className="clear-btn" onClick={() => setWebSearchCountries([])}>
                              Clear
                            </button>
                          )}
                        </div>
                        <div className="multi-select-options">
                          {COUNTRY_OPTIONS.map(country => (
                            <label key={country} className="checkbox-option">
                              <input
                                type="checkbox"
                                checked={webSearchCountries.includes(country)}
                                onChange={(e) => {
                                  if (e.target.checked) {
                                    setWebSearchCountries([...webSearchCountries, country]);
                                  } else {
                                    setWebSearchCountries(webSearchCountries.filter(c => c !== country));
                                  }
                                }}
                              />
                              <span>{country}</span>
                            </label>
                          ))}
                        </div>
                      </div>
                    </div>
                    
                    {/* Seniority Level - Multi-select checkboxes */}
                    <div className="form-group">
                      <label>Seniority Levels (select multiple)</label>
                      <div className="multi-select-container">
                        <div className="multi-select-header">
                          <span>{webSearchSeniorities.length} selected</span>
                          {webSearchSeniorities.length > 0 && (
                            <button type="button" className="clear-btn" onClick={() => setWebSearchSeniorities([])}>
                              Clear
                            </button>
                          )}
                        </div>
                        <div className="multi-select-options seniority-options">
                          {SENIORITY_OPTIONS.map(seniority => (
                            <label key={seniority} className="checkbox-option">
                              <input
                                type="checkbox"
                                checked={webSearchSeniorities.includes(seniority)}
                                onChange={(e) => {
                                  if (e.target.checked) {
                                    setWebSearchSeniorities([...webSearchSeniorities, seniority]);
                                  } else {
                                    setWebSearchSeniorities(webSearchSeniorities.filter(s => s !== seniority));
                                  }
                                }}
                              />
                              <span>{seniority}</span>
                            </label>
                          ))}
                        </div>
                      </div>
                    </div>
                    
                    {/* Target count removed - job runs continuously until stopped, controlled by rate limits */}
                  </div>
                  
                  {webSearchProgress && (
                    <div className="progress-bar-container" style={{ 
                      marginTop: "1rem", 
                      padding: "1rem", 
                      backgroundColor: webSearchProgress.status === "running" ? "#f0fdf4" : 
                                       webSearchProgress.status === "quota_exceeded" ? "#fef3c7" :
                                       webSearchProgress.status === "api_error" ? "#fef2f2" :
                                       webSearchProgress.status === "completed" ? "#ecfdf5" : "#f9fafb",
                      borderRadius: "8px",
                      border: "1px solid " + (webSearchProgress.status === "api_error" ? "#fecaca" : "#e5e7eb")
                    }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.5rem" }}>
                        <div className="progress-text" style={{ fontWeight: "600", color: webSearchProgress.status === "api_error" ? "#dc2626" : "#374151" }}>
                          {webSearchProgress.status === "running" && "🔄 "}
                          {webSearchProgress.status === "quota_exceeded" && "⏸️ "}
                          {webSearchProgress.status === "api_error" && "🔴 "}
                          {webSearchProgress.status === "completed" && "✅ "}
                          {webSearchProgress.status === "stopped" && "⏹️ "}
                          {webSearchProgress.status === "api_error" ? "API Error" : 
                           (webSearchProgress.status?.charAt(0).toUpperCase() + webSearchProgress.status?.slice(1) || "Processing...")}
                        </div>
                        {webSearchProgress.job_id && webSearchProgress.status === "running" && (
                          <button
                            className="btn btn-sm"
                            style={{ backgroundColor: "#ef4444", color: "white", padding: "0.25rem 0.75rem" }}
                            onClick={async () => {
                              try {
                                const res = await fetch(
                                  buildApiUrl(`/leads/import/web-search/stop/${webSearchProgress.job_id}`),
                                  { method: "POST", headers: { Authorization: sessionId } }
                                );
                                if (res.ok) {
                                  if (window.webSearchPollInterval) {
                                    clearInterval(window.webSearchPollInterval);
                                  }
                                }
                              } catch (e) {
                                console.error("Failed to stop job:", e);
                              }
                            }}
                          >
                            ⏹️ Stop
                          </button>
                        )}
                      </div>
                      
                      {/* API Error message */}
                      {webSearchProgress.status === "api_error" && (
                        <div style={{ 
                          marginBottom: "0.75rem", 
                          padding: "0.5rem", 
                          backgroundColor: "#fee2e2", 
                          borderRadius: "4px",
                          fontSize: "0.875rem",
                          color: "#991b1b"
                        }}>
                          API key may be invalid or expired. Check Settings → Google CSE configuration.
                          {webSearchProgress.errors && webSearchProgress.errors.length > 0 && (
                            <div style={{ marginTop: "0.25rem", fontSize: "0.8rem" }}>
                              Last error: {webSearchProgress.errors[webSearchProgress.errors.length - 1]}
                            </div>
                          )}
                        </div>
                      )}
                      
                      {/* Progress Bar */}
                      <div style={{ 
                        width: "100%", 
                        height: "8px", 
                        backgroundColor: "#e5e7eb", 
                        borderRadius: "4px", 
                        overflow: "hidden",
                        marginBottom: "0.75rem"
                      }}>
                        <div style={{ 
                          width: `${webSearchProgress.progress_percent || 0}%`, 
                          height: "100%", 
                          backgroundColor: webSearchProgress.status === "running" ? "#22c55e" : 
                                          webSearchProgress.status === "api_error" ? "#ef4444" :
                                          webSearchProgress.status === "quota_exceeded" ? "#f59e0b" : "#3b82f6",
                          transition: "width 0.3s ease"
                        }} />
                      </div>
                      
                      {/* Stats Grid */}
                      <div style={{ 
                        display: "grid", 
                        gridTemplateColumns: "repeat(4, 1fr)", 
                        gap: "0.75rem",
                        fontSize: "0.875rem"
                      }}>
                        <div style={{ textAlign: "center" }}>
                          <div style={{ fontSize: "1.25rem", fontWeight: "700", color: "#059669" }}>
                            {webSearchProgress.imported || 0}
                          </div>
                          <div style={{ color: "#6b7280" }}>Imported</div>
                        </div>
                        <div style={{ textAlign: "center" }}>
                          <div style={{ fontSize: "1.25rem", fontWeight: "700", color: "#3b82f6" }}>
                            {webSearchProgress.classified || 0}
                          </div>
                          <div style={{ color: "#6b7280" }}>Classified</div>
                        </div>
                        <div style={{ textAlign: "center" }}>
                          <div style={{ fontSize: "1.25rem", fontWeight: "700", color: "#8b5cf6" }}>
                            {webSearchProgress.emails_found || 0}
                          </div>
                          <div style={{ color: "#6b7280" }}>Emails</div>
                        </div>
                        <div style={{ textAlign: "center" }}>
                          <div style={{ fontSize: "1.25rem", fontWeight: "700", color: "#6b7280" }}>
                            {webSearchProgress.progress_percent || 0}%
                          </div>
                          <div style={{ color: "#6b7280" }}>Progress</div>
                        </div>
                      </div>
                      
                      {/* Additional Info */}
                      <div style={{ 
                        marginTop: "0.75rem", 
                        paddingTop: "0.75rem", 
                        borderTop: "1px solid #e5e7eb",
                        fontSize: "0.75rem",
                        color: "#6b7280"
                      }}>
                        <div style={{ display: "flex", justifyContent: "space-between" }}>
                          <span>Mode: Continuous (stop manually)</span>
                          <span>Today: {webSearchProgress.leads_today || 0} / {webSearchProgress.daily_limit?.toLocaleString()}</span>
                        </div>
                        {webSearchProgress.current_query && (
                          <div style={{ marginTop: "0.25rem", fontStyle: "italic" }}>
                            Current: {webSearchProgress.current_query}
                          </div>
                        )}
                        {webSearchProgress.status === "quota_exceeded" && (
                          <div style={{ marginTop: "0.5rem", color: "#d97706", fontWeight: "500" }}>
                            ⚠️ Daily API limit reached. Will auto-resume at midnight UTC.
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                  
                  <div className="web-search-info" style={{ marginTop: "1rem", padding: "1rem", backgroundColor: "#f0f9ff", borderRadius: "8px" }}>
                    <p style={{ margin: 0, fontSize: "0.875rem", color: "#0369a1" }}>
                      💡 <strong>Tip:</strong> Configure your Google API key in Settings → Google API Settings.
                      The system will run multiple search queries combining your selections.
                    </p>
                  </div>
                </div>
              )}

              {/* CSV Upload (Enhanced with column mapping) */}
              {importMethod === "csv" && (
                <div className="import-form">
                  {csvImportStep === 1 && (
                    <>
                      <h3>📁 Upload CSV File</h3>
                      <p className="form-hint">
                        Upload a CSV file containing leads data. We'll help you map columns to the correct fields.
                      </p>
                      
                      <div 
                        className="file-upload-dropzone"
                        onClick={() => fileInputRef.current?.click()}
                        onDrop={(e) => { e.preventDefault(); handleCsvFileSelect(e.dataTransfer.files[0]); }}
                        onDragOver={(e) => e.preventDefault()}
                      >
                        <div className="dropzone-icon">📤</div>
                        <p>Drop your CSV file here, or click to browse</p>
                        <span className="dropzone-hint">Supports .csv files</span>
                        <input
                          ref={fileInputRef}
                          type="file"
                          accept=".csv"
                          style={{ display: "none" }}
                          onChange={(e) => handleCsvFileSelect(e.target.files[0])}
                        />
                      </div>
                    </>
                  )}
                  
                  {csvImportStep === 2 && (
                    <>
                      <div className="csv-file-info">
                        <span>📄 {csvFile?.name}</span>
                        <span className="csv-stats">{csvData.length} rows, {csvColumns.length} columns</span>
                        <button 
                          className="btn btn-sm btn-outline"
                          onClick={() => { setCsvFile(null); setCsvData([]); setCsvColumns([]); setCsvImportStep(1); }}
                        >
                          Change File
                        </button>
                      </div>
                      
                      <h3>🔗 Map Columns</h3>
                      <p className="form-hint">
                        Match your CSV columns to lead fields. We auto-matched {getMappedFieldsCount()} fields.
                      </p>
                      
                      <div className="column-mapping-list">
                        {DB_FIELDS.map((field) => (
                          <div key={field.key} className="mapping-row">
                            <label className="mapping-label">
                              {field.label}
                              {field.required && <span className="required">*</span>}
                            </label>
                            <select
                              className={`mapping-select ${columnMapping[field.key] ? "mapped" : ""}`}
                              value={columnMapping[field.key] || ""}
                              onChange={(e) => handleMappingChange(field.key, e.target.value)}
                            >
                              <option value="">-- Select column --</option>
                              {csvColumns.map((col) => (
                                <option key={col} value={col}>{col}</option>
                              ))}
                            </select>
                          </div>
                        ))}
                      </div>
                      
                      <div className="csv-preview-actions">
                        <button 
                          className="btn btn-outline"
                          onClick={() => { setCsvFile(null); setCsvData([]); setCsvColumns([]); setCsvImportStep(1); }}
                        >
                          ◀ Back
                        </button>
                        <button 
                          className="btn btn-primary"
                          onClick={() => setCsvImportStep(3)}
                          disabled={!columnMapping.email}
                        >
                          Preview ▶
                        </button>
                      </div>
                    </>
                  )}
                  
                  {csvImportStep === 3 && (
                    <>
                      <h3>👁️ Preview Import</h3>
                      <p className="form-hint">
                        Review the first 5 rows before importing. {csvData.length} leads will be imported.
                      </p>
                      
                      <div className="preview-table-wrapper">
                        <table className="preview-table">
                          <thead>
                            <tr>
                              {DB_FIELDS.filter((f) => columnMapping[f.key]).map((field) => (
                                <th key={field.key}>{field.label}</th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {csvData.slice(0, 5).map((row, idx) => (
                              <tr key={idx}>
                                {DB_FIELDS.filter((f) => columnMapping[f.key]).map((field) => (
                                  <td key={field.key}>{row[columnMapping[field.key]] || "—"}</td>
                                ))}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                      
                      <div className="csv-preview-actions">
                        <button 
                          className="btn btn-outline"
                          onClick={() => setCsvImportStep(2)}
                        >
                          ◀ Back to Mapping
                        </button>
                      </div>
                    </>
                  )}
                </div>
              )}

              {/* Gmail Import - Extract from MongoDB Emails */}
              {importMethod === "gmail" && (
                <div className="import-form">
                  <h3>📧 Extract Leads from Stored Emails</h3>
                  <p className="form-hint">
                    Emails are already downloaded in the database. Extract contact information and enrich lead data in phases.
                  </p>

                  {/* Gmail Account Selection */}
                  <div className="form-group">
                    <label>Select Email Accounts</label>
                    <div className="multi-select-container">
                      <div className="multi-select-options" style={{ maxHeight: "180px", overflowY: "auto" }}>
                        {gmailAccounts.length === 0 ? (
                          <div style={{ padding: "10px", color: "#888" }}>
                            No email accounts found. Add accounts in Settings.
                          </div>
                        ) : (
                          gmailAccounts.map(account => (
                            <label key={account.email} className="checkbox-option" style={{ 
                              display: "flex", 
                              alignItems: "center", 
                              padding: "8px 12px",
                              borderBottom: "1px solid #eee"
                            }}>
                              <input
                                type="checkbox"
                                checked={selectedGmailAccounts.includes(account.email)}
                                onChange={(e) => {
                                  if (e.target.checked) {
                                    setSelectedGmailAccounts([...selectedGmailAccounts, account.email]);
                                  } else {
                                    setSelectedGmailAccounts(selectedGmailAccounts.filter(a => a !== account.email));
                                  }
                                }}
                              />
                              <span style={{ flex: 1, marginLeft: "8px" }}>
                                <strong>{account.email}</strong>
                                {account.display_name && account.display_name !== account.email.split("@")[0] && (
                                  <span style={{ color: "#666", marginLeft: "8px" }}>({account.display_name})</span>
                                )}
                              </span>
                              {account.email_count && (
                                <span style={{ 
                                  backgroundColor: "#e8f4fd", 
                                  color: "#1976d2", 
                                  padding: "2px 8px", 
                                  borderRadius: "12px", 
                                  fontSize: "12px" 
                                }}>
                                  {account.email_count.toLocaleString()} emails
                                </span>
                              )}
                            </label>
                          ))
                        )}
                      </div>
                    </div>
                  </div>

                  {/* Import Progress */}
                  {gmailImportProgress && (
                    <div style={{ 
                      marginTop: "1rem", 
                      padding: "1rem", 
                      backgroundColor: gmailImportProgress.status === "running" ? "#f0fdf4" : "#f9fafb",
                      borderRadius: "8px",
                      border: "1px solid #e5e7eb"
                    }}>
                      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.5rem" }}>
                        <span style={{ fontWeight: "600" }}>
                          {gmailImportProgress.status === "running" ? "🔄 Processing..." : "✅ Complete"}
                        </span>
                        <span style={{ color: "#6b7280" }}>{gmailImportProgress.progress || 0}%</span>
                      </div>
                      <div style={{ width: "100%", height: "6px", backgroundColor: "#e5e7eb", borderRadius: "3px" }}>
                        <div style={{ 
                          width: `${gmailImportProgress.progress || 0}%`, 
                          height: "100%", 
                          backgroundColor: "#22c55e", 
                          borderRadius: "3px",
                          transition: "width 0.3s"
                        }} />
                      </div>
                      <div style={{ display: "flex", justifyContent: "space-between", marginTop: "0.5rem", fontSize: "0.875rem", color: "#6b7280" }}>
                        <span>Extracted: {gmailImportProgress.extracted || 0}</span>
                        <span>Enriched: {gmailImportProgress.enriched || 0}</span>
                        <span>Duplicates: {gmailImportProgress.duplicates || 0}</span>
                      </div>
                    </div>
                  )}

                  {/* Gmail-specific import button */}
                  <div className="form-group" style={{ marginTop: "20px" }}>
                    <button 
                      className="btn btn-primary" 
                      onClick={handleGmailImport} 
                      disabled={gmailImporting || selectedGmailAccounts.length === 0}
                      style={{ width: "100%", padding: "12px", fontSize: "16px" }}
                    >
                      {gmailImporting ? "⏳ Extracting Leads..." : "📧 Extract Leads from Emails"}
                    </button>
                    {selectedGmailAccounts.length === 0 && !gmailImporting && (
                      <small style={{ color: "#ff6b6b", display: "block", marginTop: "8px", textAlign: "center" }}>
                        ⚠️ Please select at least one email account above
                      </small>
                    )}
                  </div>
                </div>
              )}
            </div>

            <div className="modal-footer">
              <button className="btn btn-outline" onClick={() => resetImportModal()}>
                Cancel
              </button>
              {importMethod !== "gmail" && (
                <button className="btn btn-primary" onClick={handleImport} disabled={importing}>
                  {importing ? "⏳ Importing..." : "📥 Import Leads"}
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default AILeads;
