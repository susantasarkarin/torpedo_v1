/**
 * AI Lead Database
 * Path: /admin/sales/campaign/ai-leads
 * Light theme matching app styling
 */

import { useState, useEffect, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { API_BASE_URL } from "../../../config";
import Papa from "papaparse";
import "./AILeads.css";

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

  // Web Search Filters (enhanced with multi-select)
  const [webSearchDesignation, setWebSearchDesignation] = useState("");
  const [webSearchCountries, setWebSearchCountries] = useState([]); // Multi-select
  const [webSearchSeniorities, setWebSearchSeniorities] = useState([]); // Multi-select
  const [webSearchTargetCount, setWebSearchTargetCount] = useState(10000); // Default to 10000
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

  const fetchLeads = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (searchQuery) params.append("search", searchQuery);
      if (filters.seniority_level) params.append("seniority_level", filters.seniority_level);
      if (filters.department) params.append("department", filters.department);
      if (filters.persona) params.append("persona", filters.persona);
      if (filters.company_size) params.append("company_size", filters.company_size);
      if (filters.min_confidence) params.append("min_confidence", filters.min_confidence);
      params.append("page", currentPage);
      params.append("limit", 50);

      const res = await fetch(`${API_BASE_URL}/leads?${params.toString()}`, {
        headers: { Authorization: sessionId },
      });

      if (!res.ok) throw new Error("Failed to fetch leads");
      const data = await res.json();
      setLeads(data.leads || []);
      setTotalPages(data.pages || 1);
    } catch (err) {
      console.error("Error fetching leads:", err);
    }
  }, [filters, currentPage, searchQuery, sessionId]);

  const fetchRawLeads = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/leads/raw`, {
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
      const res = await fetch(`${API_BASE_URL}/leads/statistics`, {
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
      const res = await fetch(`${API_BASE_URL}/leads/gmail/accounts`, {
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
      const res = await fetch(`${API_BASE_URL}/leads/gmail/segments`, {
        headers: { Authorization: sessionId },
      });
      if (!res.ok) return;
      const data = await res.json();
      setGmailSegments(data.segments || []);
    } catch (err) {
      console.error("Error fetching Gmail segments:", err);
    }
  }, [sessionId]);

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
    };
    
    loadPhase1();
    loadPhase2();
  }, []);

  // Refetch leads when filters change
  useEffect(() => {
    if (!loading) fetchLeads();
  }, [filters, currentPage, searchQuery]);

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
  const handleCsvFileSelect = (file) => {
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
      complete: (results) => {
        if (results.errors.length > 0) {
          setImportError("Error parsing CSV: " + results.errors[0].message);
          return;
        }
        const columns = results.meta.fields || [];
        setCsvColumns(columns);
        setCsvData(results.data);
        const autoMapping = autoMatchColumns(columns);
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
    
    try {
      let res;
      
      if (importMethod === "json") {
        if (!importData.trim()) {
          setImportError("Please enter JSON data");
          setImporting(false);
          return;
        }
        const leadsToImport = JSON.parse(importData);
        res = await fetch(`${API_BASE_URL}/leads/import`, {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: sessionId },
          body: JSON.stringify({ leads: Array.isArray(leadsToImport) ? leadsToImport : [leadsToImport] }),
        });
      } else if (importMethod === "csv") {
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
        
        res = await fetch(`${API_BASE_URL}/leads/import/csv`, {
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
        
        res = await fetch(`${API_BASE_URL}/leads/import/web-search`, {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: sessionId },
          body: JSON.stringify({
            designation: webSearchDesignation,
            countries: webSearchCountries,
            seniorities: webSearchSeniorities,
            target_count: webSearchTargetCount
          }),
        });
        
        if (!res.ok) {
          const error = await res.json();
          throw new Error(error.detail || "Failed to start search job");
        }
        
        const jobResult = await res.json();
        
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
            progress_percent: 0,
            target_count: webSearchTargetCount
          });
          
          // Start polling interval for status updates
          const pollInterval = setInterval(async () => {
            try {
              const statusRes = await fetch(
                `${API_BASE_URL}/leads/import/web-search/status/${jobResult.job_id}`,
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
                  target_count: status.target_count,
                  current_query: status.current_query,
                  eta_minutes: status.eta_minutes,
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
                if (["completed", "stopped", "failed"].includes(status.status)) {
                  clearInterval(pollInterval);
                  setImporting(false);
                  fetchRawLeads();
                  fetchStatistics();
                  
                  if (status.status === "completed") {
                    alert(`✅ Search completed! Imported ${status.total_imported} leads, found ${status.emails_found} emails.`);
                  } else if (status.status === "stopped") {
                    alert(`⏹️ Search stopped. Imported ${status.total_imported} leads so far.`);
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

      if (!res.ok) {
        const error = await res.json();
        throw new Error(error.detail || "Import failed");
      }

      const result = await res.json();
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
    setWebSearchTargetCount(10000);
    setWebSearchProgress(null);
    setWebSearchJobId(null);
    setImportError("");
    // Reset Gmail state
    setSelectedGmailAccounts([]);
    setSelectedGmailSegments(GMAIL_SEGMENT_OPTIONS.map(s => s.value));
    setGmailMaxEmails(500);
    setGmailImporting(false);
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
      const res = await fetch(`${API_BASE_URL}/leads/all`, {
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

  // Email IMAP import handler
  const handleGmailImport = async () => {
    setGmailImporting(true);
    setImportError("");
    
    try {
      const res = await fetch(`${API_BASE_URL}/leads/gmail/import`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: sessionId },
        body: JSON.stringify({
          account_emails: selectedGmailAccounts.length > 0 ? selectedGmailAccounts : null,
          max_emails: gmailMaxEmails,
          since_days: 30,
          segments: selectedGmailSegments.length > 0 ? selectedGmailSegments : null
        }),
      });
      
      if (!res.ok) {
        const error = await res.json();
        throw new Error(error.detail || "Email import failed");
      }
      
      const result = await res.json();
      let alertMsg = `✅ ${result.message}\n\nEmails processed: ${result.emails_processed}\nLeads imported: ${result.leads_imported}\nDuplicates: ${result.duplicates}`;
      if (result.errors && result.errors.length > 0) {
        alertMsg += `\n\n⚠️ Errors:\n${result.errors.join("\n")}`;
      }
      alert(alertMsg);
      resetImportModal();
      fetchRawLeads();
      fetchLeads();
      fetchStatistics();
    } catch (err) {
      setImportError(err.message);
    } finally {
      setGmailImporting(false);
    }
  };

  // ============== CLASSIFY HANDLER ==============

  const handleClassify = async (leadIds = null) => {
    setClassifying(true);
    try {
      // When leadIds is null, classify ALL pending leads (no batch_size limit)
      const res = await fetch(`${API_BASE_URL}/leads/classify`, {
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

  // ============== GET DISPLAY DATA ==============

  const getDisplayLeads = () => {
    if (activeTab === "pending") {
      return rawLeads.filter(l => l.classification_status === "Pending");
    } else if (activeTab === "classified") {
      return leads;
    }
    return rawLeads;
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
          All Leads ({rawLeads.length})
        </button>
        <button 
          className={`tab-btn ${activeTab === "pending" ? "active" : ""}`}
          onClick={() => setActiveTab("pending")}
        >
          Pending ({rawLeads.filter(l => l.classification_status === "Pending").length})
        </button>
        <button 
          className={`tab-btn ${activeTab === "classified" ? "active" : ""}`}
          onClick={() => setActiveTab("classified")}
        >
          Classified ({leads.length})
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
          <button className="btn btn-sm btn-primary" onClick={() => handleClassify(Array.from(selectedIds))}>
            🤖 Classify Selected
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
        ) : activeTab === "classified" ? (
          /* Classified Leads Table - Full columns */
          <div className="classified-table-container">
            <table className="data-table classified-table">
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
                  <th>First Name</th>
                  <th>Last Name</th>
                  <th>Email</th>
                  <th>Email Status</th>
                  <th>Title</th>
                  <th>LinkedIn</th>
                  <th>Location</th>
                  <th>Added On</th>
                  <th>Seniority Level</th>
                  <th>Buying Role</th>
                  <th>Company Name</th>
                  <th>Company Domain</th>
                  <th>Company Website</th>
                  <th>Employee Count</th>
                  <th>Employee Range</th>
                  <th>Founded</th>
                  <th>Industry</th>
                  <th>Company Type</th>
                  <th>Headquarters</th>
                  <th>Revenue Range</th>
                  <th>Company LinkedIn</th>
                  <th>Source</th>
                  <th>Confidence</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {displayLeads.map((lead) => (
                  <tr key={lead._id} className={selectedIds.has(lead._id) ? "selected" : ""}>
                    <td className="checkbox-col sticky-col">
                      <input
                        type="checkbox"
                        checked={selectedIds.has(lead._id)}
                        onChange={() => toggleSelect(lead._id)}
                      />
                    </td>
                    <td className="name-cell sticky-col-2">
                      <a href={lead.linkedin_url} target="_blank" rel="noopener noreferrer">
                        {lead.name}
                      </a>
                    </td>
                    <td>{lead.first_name || "-"}</td>
                    <td>{lead.last_name || "-"}</td>
                    <td className="email-cell">{lead.email || "-"}</td>
                    <td>
                      <span className={`status-badge ${(lead.email_status || "unknown").toLowerCase().replace(" ", "-")}`}>
                        {lead.email_status || "Unknown"}
                      </span>
                    </td>
                    <td>{lead.title || "-"}</td>
                    <td>
                      <a href={lead.linkedin_url} target="_blank" rel="noopener noreferrer" className="linkedin-link">
                        View ↗
                      </a>
                    </td>
                    <td>{lead.location || "-"}</td>
                    <td>{lead.added_on ? new Date(lead.added_on).toLocaleDateString() : "-"}</td>
                    <td><span className="badge badge-blue">{lead.seniority_level || "Unknown"}</span></td>
                    <td><span className="badge badge-orange">{lead.buying_role || "Unknown"}</span></td>
                    <td>{lead.company_name || "-"}</td>
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
                    <td>{lead.company_industry || "-"}</td>
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
                      <span className={`confidence-pill ${getConfidenceClass(lead.confidence_score)}`}>
                        {Math.round((lead.confidence_score || 0) * 100)}%
                      </span>
                    </td>
                    <td className="actions-cell">
                      <button className="action-btn" onClick={() => handleClassify([lead._id])}>
                        Re-classify
                      </button>
                    </td>
                  </tr>
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
                    <a href={lead.linkedin_url} target="_blank" rel="noopener noreferrer">
                      {lead.name}
                    </a>
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
                    <a href={lead.linkedin_url} target="_blank" rel="noopener noreferrer" className="action-link">
                      View ↗
                    </a>
                    {lead.classification_status === "Pending" && (
                      <button className="action-btn" onClick={() => handleClassify([lead._id])}>
                        Classify
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && activeTab === "classified" && (
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
                  className={`method-tab ${importMethod === "json" ? "active" : ""}`}
                  onClick={() => { setImportMethod("json"); setCsvImportStep(1); }}
                >
                  📋 JSON
                </button>
              </div>

              {/* Error Display */}
              {importError && (
                <div className="error-alert">{importError}</div>
              )}

              {/* Web Search (Enhanced with Multi-Select Filters) */}
              {importMethod === "web-search" && (
                <div className="import-form">
                  <h3>🔍 Search LinkedIn Profiles</h3>
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
                    
                    <div className="form-group">
                      <label>Target Lead Count</label>
                      <input
                        type="number"
                        className="form-input"
                        min="10"
                        max="10000"
                        step="100"
                        value={webSearchTargetCount}
                        onChange={(e) => setWebSearchTargetCount(parseInt(e.target.value) || 10000)}
                      />
                      <span className="form-hint">Default: 10,000 leads (max)</span>
                    </div>
                  </div>
                  
                  {webSearchProgress && (
                    <div className="progress-bar-container" style={{ 
                      marginTop: "1rem", 
                      padding: "1rem", 
                      backgroundColor: webSearchProgress.status === "running" ? "#f0fdf4" : 
                                       webSearchProgress.status === "quota_exceeded" ? "#fef3c7" :
                                       webSearchProgress.status === "completed" ? "#ecfdf5" : "#f9fafb",
                      borderRadius: "8px",
                      border: "1px solid #e5e7eb"
                    }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.5rem" }}>
                        <div className="progress-text" style={{ fontWeight: "600", color: "#374151" }}>
                          {webSearchProgress.status === "running" && "🔄 "}
                          {webSearchProgress.status === "quota_exceeded" && "⏸️ "}
                          {webSearchProgress.status === "completed" && "✅ "}
                          {webSearchProgress.status === "stopped" && "⏹️ "}
                          {webSearchProgress.status?.charAt(0).toUpperCase() + webSearchProgress.status?.slice(1) || "Processing..."}
                        </div>
                        {webSearchProgress.job_id && webSearchProgress.status === "running" && (
                          <button
                            className="btn btn-sm"
                            style={{ backgroundColor: "#ef4444", color: "white", padding: "0.25rem 0.75rem" }}
                            onClick={async () => {
                              try {
                                const res = await fetch(
                                  `${API_BASE_URL}/leads/import/web-search/stop/${webSearchProgress.job_id}`,
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
                          <span>Target: {webSearchProgress.target_count?.toLocaleString()} leads</span>
                          <span>Today: {webSearchProgress.leads_today || 0} / {webSearchProgress.daily_limit?.toLocaleString()}</span>
                          {webSearchProgress.eta_minutes && (
                            <span>ETA: ~{webSearchProgress.eta_minutes} min</span>
                          )}
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

              {/* JSON */}
              {importMethod === "json" && (
                <div className="import-form">
                  <label>Paste JSON Data</label>
                  <textarea
                    className="form-textarea"
                    placeholder='[{"name": "John Smith", "title": "VP Sales", "linkedin_url": "https://linkedin.com/in/...", "snippet": "10+ years experience"}]'
                    value={importData}
                    onChange={(e) => setImportData(e.target.value)}
                  />
                </div>
              )}

              {/* Gmail Import */}
              {importMethod === "gmail" && (
                <div className="import-form">
                  {/* Gmail Account Selection */}
                  <div className="form-group">
                    <label>Select Gmail Accounts</label>
                    <div className="multi-select-container">
                      <div className="multi-select-options" style={{ maxHeight: "150px", overflowY: "auto" }}>
                        {gmailAccounts.length === 0 ? (
                          <div style={{ padding: "10px", color: "#888" }}>
                            No Gmail accounts connected. Add accounts in Settings.
                          </div>
                        ) : (
                          gmailAccounts.map(account => (
                            <label key={account.email} className="checkbox-option">
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
                              <span>{account.email}</span>
                            </label>
                          ))
                        )}
                      </div>
                    </div>
                  </div>

                  {/* Segment Filter */}
                  <div className="form-group">
                    <label>Filter by Email Segments</label>
                    <div className="multi-select-container">
                      <div className="multi-select-header" style={{ marginBottom: "8px" }}>
                        <button 
                          type="button" 
                          className="btn btn-sm"
                          onClick={() => setSelectedGmailSegments(GMAIL_SEGMENT_OPTIONS.map(s => s.value))}
                        >
                          Select All
                        </button>
                        <button 
                          type="button" 
                          className="btn btn-sm"
                          onClick={() => setSelectedGmailSegments([])}
                          style={{ marginLeft: "8px" }}
                        >
                          Clear All
                        </button>
                      </div>
                      <div className="multi-select-options" style={{ maxHeight: "200px", overflowY: "auto" }}>
                        {GMAIL_SEGMENT_OPTIONS.map(segment => (
                          <label key={segment.value} className="checkbox-option">
                            <input
                              type="checkbox"
                              checked={selectedGmailSegments.includes(segment.value)}
                              onChange={(e) => {
                                if (e.target.checked) {
                                  setSelectedGmailSegments([...selectedGmailSegments, segment.value]);
                                } else {
                                  setSelectedGmailSegments(selectedGmailSegments.filter(s => s !== segment.value));
                                }
                              }}
                            />
                            <span>{segment.label}</span>
                          </label>
                        ))}
                      </div>
                    </div>
                  </div>

                  {/* Max Emails */}
                  <div className="form-group">
                    <label>Max Emails to Process</label>
                    <input
                      type="number"
                      className="form-input"
                      value={gmailMaxEmails}
                      onChange={(e) => setGmailMaxEmails(parseInt(e.target.value) || 100)}
                      min={1}
                      max={10000}
                    />
                    <small style={{ color: "#888" }}>Maximum number of emails to scan for leads per account</small>
                  </div>

                  {/* Gmail-specific import button */}
                  <div className="form-group" style={{ marginTop: "20px" }}>
                    <button 
                      className="btn btn-primary" 
                      onClick={handleGmailImport} 
                      disabled={gmailImporting || selectedGmailAccounts.length === 0}
                      style={{ width: "100%" }}
                    >
                      {gmailImporting ? "⏳ Extracting Leads from Gmail..." : "📧 Extract Leads from Gmail"}
                    </button>
                    {selectedGmailAccounts.length === 0 && (
                      <small style={{ color: "#ff6b6b", display: "block", marginTop: "5px" }}>
                        Please select at least one Gmail account
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
