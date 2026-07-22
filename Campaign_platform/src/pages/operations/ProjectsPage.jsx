"use client";

import { useEffect, useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import {
  Plus, Search, Pencil, Trash2, Eye, ChevronLeft, ChevronRight,
  FolderOpen, Activity, X
} from "lucide-react";
import "./ProjectsPage.css";
import { buildApiUrl } from "../../config";
import { qreApi } from "../../services/qreApi";

function ProjectsPage() {
  const navigate = useNavigate();
  const [projects, setProjects] = useState([]);
  const [vendors, setVendors] = useState([]);
  const [clients, setClients] = useState([]);
  const [rfqs, setRfqs] = useState([]);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [error, setError] = useState(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [recordsPerPage, setRecordsPerPage] = useState(10);
  const [qreStatsMap, setQreStatsMap] = useState({});
  const [qreStudies, setQreStudies] = useState([]);

  const emptyForm = {
    projectName: "",
    surveyNo: "",
    salesPerson: "",
    projectValue: "",
    client: "",
    projectStatus: "live",
    projectLaunchDate: "",
    projectCloseDate: "",
    rfqId: "",
    rfqDetails: "",
    totalCompletesRequired: "",
    loi: "",
    clientIR: "",
    cpi: "",
    totalCompletes: "",
    totalRespondents: "",
    actualCompletes: "",
    actualIR: "",
    entryLink: "",
    liveLink: "",
    completePage: "",
    terminatePage: "",
    quotaFullPage: "",
    countryCode: "",
    vendorName: "",
    vendorId: "",
    vendorCompleteRD: [],
    vendorTerminateRD: [],
    vendorQuotaFullRD: [],
    qreStudyId: "",
  };
  const [formData, setFormData] = useState(emptyForm);

  const toNumber = (value) => {
    if (value === null || value === undefined || value === "") return 0;
    const numeric = Number(String(value).replace(/,/g, "").trim());
    return Number.isFinite(numeric) ? numeric : 0;
  };

  const computeActualIR = (actualCompletes, totalRespondents) => {
    const completes = toNumber(actualCompletes);
    const respondents = toNumber(totalRespondents);
    if (respondents <= 0) return 0;
    return Number(((completes / respondents) * 100).toFixed(2));
  };

  const detectProviderFromLiveLink = (liveLink) => {
    if (!liveLink) return "cpx";
    const link = String(liveLink).trim().toLowerCase();
    try {
      const host = new URL(link).hostname.toLowerCase();
      if (host.includes("samplicio.us") || host.includes("cint") || host.includes("luc.id")) {
        return "cint";
      }
    } catch {
      // Fallback to substring checks for malformed URLs.
    }
    return link.includes("cint") ? "cint" : "cpx";
  };

  const getProjectCallbackBase = () => {
    if (typeof window !== "undefined" && window.location?.origin) {
      return window.location.origin.replace(/\/$/, "");
    }
    return "https://surveyfieldwork.com";
  };

  const getSystemGeneratedPages = (liveLink) => {
    const base = getProjectCallbackBase();
    const provider = detectProviderFromLiveLink(liveLink);

    if (provider === "cint") {
      return {
        completePage: `${base}/cint-response?status=complete&pid=[%PID%]&mid=[%MID%]&revenue=[%REVENUE%]`,
        terminatePage: `${base}/cint-response?status=terminate&pid=[%PID%]&mid=[%MID%]`,
        quotaFullPage: `${base}/cint-response?status=quota_full&pid=[%PID%]&mid=[%MID%]`,
      };
    }

    return {
      completePage: `${base}/surveycomplete?rid={RID}`,
      terminatePage: `${base}/surveyterminate?rid={RID}`,
      quotaFullPage: `${base}/surveyquotafull?rid={RID}`,
    };
  };

  const normalizeList = (value) => {
    if (Array.isArray(value)) return value.filter(Boolean);
    if (!value) return [];
    return [value].filter(Boolean);
  };

  const normalizeEntryUrl = (value) => {
    const raw = String(value || "").trim();
    if (!raw) return "";
    if (/^[a-z][a-z0-9+.-]*:\/\//i.test(raw)) return raw;
    return `https://${raw}`;
  };

  const getEntryLinkTemplate = (form) => {
    const base = getProjectCallbackBase();
    const vid = form?.vendorId || "{VID}";
    const cc = "[%CC%]";
    const panel = "[%PANEL%]";
    // pid must be the surveyNo (what /takesurvey resolves by), not the MongoDB _id
    const pid = form?.surveyNo || "{PID}";
    return `${base}/takesurvey?api=false&vid=${vid}&cc=${cc}&panel=${panel}&pid=${pid}&rid=[%RID%]`;
  };

  const applyDerivedFields = (nextForm) => {
    const liveLink = nextForm.liveLink || "";
    const entryLink = getEntryLinkTemplate(nextForm);
    const actualIR = computeActualIR(nextForm.actualCompletes, nextForm.totalRespondents);
    const generatedPages = getSystemGeneratedPages(liveLink);
    return {
      ...nextForm,
      entryLink,
      actualIR,
      ...generatedPages,
    };
  };

  const deriveCpiFromRfq = (rfq) => {
    const direct = toNumber(rfq?.cpi || rfq?.unit_price);
    if (direct > 0) return direct;

    const sampleSize = toNumber(rfq?.sample_size);
    const value = toNumber(rfq?.final_value || rfq?.manual_value || rfq?.extracted_value || rfq?.budget);
    if (sampleSize > 0 && value > 0) {
      return Number((value / sampleSize).toFixed(2));
    }
    return 0;
  };

  const getRfqSummary = (rfq) => {
    const parts = [
      rfq?.title,
      rfq?.description,
      rfq?.ai_summary,
      rfq?.rfq_id ? `RFQ ID: ${rfq.rfq_id}` : "",
    ]
      .map((item) => (item || "").trim())
      .filter(Boolean);
    return parts.join("\n");
  };

  const formatRfqLabel = (rfq) => {
    const id = rfq?.rfq_id || rfq?._id || "RFQ";
    const title = rfq?.title || "Untitled";
    const status = rfq?.status ? ` (${rfq.status})` : "";
    return `${id} - ${title}${status}`;
  };

  const normalizeProjectForEdit = (project) => {
    // If the saved project is missing vendorId (e.g. created before vid tracking),
    // look it up from the loaded vendors list using the stored vendorName.
    let resolvedVendorId = project.vendorId || "";
    if (!resolvedVendorId && project.vendorName) {
      const matched = vendors.find((v) => v.vendorName === project.vendorName);
      if (matched) resolvedVendorId = matched.vid || "";
    }
    return applyDerivedFields({
      ...emptyForm,
      ...project,
      vendorId: resolvedVendorId,
      vendorCompleteRD: normalizeList(project.vendorCompleteRD),
      vendorTerminateRD: normalizeList(project.vendorTerminateRD),
      vendorQuotaFullRD: normalizeList(project.vendorQuotaFullRD),
      rfqId: project.rfqId || "",
    });
  };

  // 🔹 Fetch Projects + Vendors
  useEffect(() => {
    const sessionId = localStorage.getItem("session_id");
    if (!sessionId) {
      navigate("/login");
      return;
    }

    const fetchProjects = async () => {
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
          navigate("/login");
          return;
        }

        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to load projects");
        setProjects(data.projects || []);
      } catch (err) {
        console.error("❌ Projects fetch failed:", err.message);
      }
    };

    const fetchVendors = async () => {
      try {
        const res = await fetch(buildApiUrl(`/api/vendors/`), {
          headers: {
            "Content-Type": "application/json",
            Authorization: sessionId,
          },
        });

        if (res.status === 401) {
          alert("Session expired. Please login again.");
          localStorage.removeItem("session_id");
          navigate("/login");
          return;
        }

        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to load vendors");
        const vendorList = Array.isArray(data) ? data : (data.vendors || []);
        setVendors(vendorList);
      } catch (err) {
        console.error("❌ Vendors fetch failed:", err.message);
      }
    };

    const fetchClients = async () => {
      try {
        const res = await fetch(buildApiUrl(`/finance/customers/`), {
          headers: {
            "Content-Type": "application/json",
            Authorization: sessionId,
          },
        });

        if (res.status === 401) {
          alert("Session expired. Please login again.");
          localStorage.removeItem("session_id");
          navigate("/login");
          return;
        }

        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to load clients");
        const customerList = Array.isArray(data) ? data : (data.customers || []);
        const activeClients = customerList.filter(
          (c) => !c.status || String(c.status).toLowerCase() === "active"
        );
        setClients(activeClients);
      } catch (err) {
        console.error("❌ Clients fetch failed:", err.message);
      }
    };

    const fetchRfqs = async () => {
      try {
        const res = await fetch(buildApiUrl(`/api/rfq/?page=1&limit=200`), {
          headers: {
            "Content-Type": "application/json",
            Authorization: sessionId,
          },
        });

        if (res.status === 401) {
          alert("Session expired. Please login again.");
          localStorage.removeItem("session_id");
          navigate("/login");
          return;
        }

        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to load RFQs");
        setRfqs(data.rfqs || []);
      } catch (err) {
        console.error("RFQ fetch failed:", err.message);
      }
    };

    fetchProjects();
    fetchVendors();
    fetchClients();
    fetchRfqs();
    qreApi.login("admin", "admin@QRE2026")
      .then(res => { qreApi.setToken(res.token); return qreApi.listStudies(); })
      .then(setQreStudies)
      .catch(() => {});
  }, [navigate]);

  useEffect(() => {
    const studyIds = projects.map(p => p.qreStudyId).filter(Boolean);
    if (!studyIds.length) return;
    const unique = [...new Set(studyIds)];
    Promise.all(unique.map(id => qreApi.getStats(id).then(s => [id, s]).catch(() => null)))
      .then(results => {
        const map = {};
        results.forEach(r => { if (r) map[r[0]] = r[1]; });
        setQreStatsMap(map);
      });
  }, [projects]);

  const handleChange = (e) => {
    const { name, value } = e.target;
    setFormData((prev) => applyDerivedFields({ ...prev, [name]: value }));
  };

  const handleRfqChange = (e) => {
    const rfqId = e.target.value;

    if (!rfqId) {
      setFormData((prev) =>
        applyDerivedFields({
          ...prev,
          rfqId: "",
          rfqDetails: "",
          totalCompletesRequired: "",
          loi: "",
          clientIR: "",
          cpi: "",
          totalCompletes: "",
        })
      );
      return;
    }

    const selected = rfqs.find((item) => item._id === rfqId || item.rfq_id === rfqId);
    if (!selected) {
      setFormData((prev) => applyDerivedFields({ ...prev, rfqId }));
      return;
    }

    const requiredCompletes = toNumber(selected.sample_size);
    const loi = toNumber(selected.loi);
    const clientIR = toNumber(selected.ir);
    const cpi = deriveCpiFromRfq(selected);

    setFormData((prev) =>
      applyDerivedFields({
        ...prev,
        rfqId,
        rfqDetails: getRfqSummary(selected),
        totalCompletesRequired: requiredCompletes > 0 ? requiredCompletes : "",
        loi: loi > 0 ? loi : "",
        clientIR: clientIR > 0 ? clientIR : "",
        cpi: cpi > 0 ? cpi : "",
        totalCompletes: requiredCompletes > 0 ? requiredCompletes : "",
      })
    );
  };

  const handleVendorChange = (e) => {
    const vendorName = e.target.value;
    const vendor = vendors.find((v) => v.vendorName === vendorName);
    if (vendor) {
      setFormData((prev) =>
        applyDerivedFields({
          ...prev,
          vendorName,
          vendorId: vendor.vid || "",
          vendorCompleteRD: normalizeList(vendor.completeRD),
          vendorTerminateRD: normalizeList(vendor.terminateRD),
          vendorQuotaFullRD: normalizeList(vendor.quotaRD || vendor.quotaFullRD),
        })
      );
    } else {
      setFormData((prev) => applyDerivedFields({ ...prev, vendorName, vendorId: "" }));
    }
  };

  // 🔹 Save Project
  const saveProject = async () => {
    const normalizedLiveLink = normalizeEntryUrl(formData.liveLink);

    // Ensure vendorId is populated — if it's missing (e.g. legacy project), derive
    // it from the vendors list using the stored vendorName.
    let vendorId = formData.vendorId || "";
    if (!vendorId && formData.vendorName) {
      const matched = vendors.find((v) => v.vendorName === formData.vendorName);
      if (matched) vendorId = matched.vid || "";
    }

    const preparedForm = applyDerivedFields({
      ...formData,
      liveLink: normalizedLiveLink,
      vendorId,
    });

    const errors = [];
    
    if (!preparedForm.projectName || !preparedForm.projectName.trim()) {
      errors.push("Project Name is required");
    }
    if (!preparedForm.salesPerson || !preparedForm.salesPerson.trim()) {
      errors.push("Sales Person is required");
    }
    if (!preparedForm.client || !preparedForm.client.trim()) {
      errors.push("Client is required");
    }
    if (!preparedForm.projectLaunchDate) {
      errors.push("Project Launch Date is required");
    }
    if (!preparedForm.projectCloseDate) {
      errors.push("Project Close Date is required");
    }
    if (!preparedForm.liveLink || !preparedForm.liveLink.trim()) {
      errors.push("Live Link is required");
    }
    if (!preparedForm.vendorName || !preparedForm.vendorName.trim()) {
      errors.push("Vendor Name is required");
    }
    if (!toNumber(preparedForm.totalCompletesRequired)) {
      errors.push("Total Completes Required is required and must be greater than 0");
    }
    if (!toNumber(preparedForm.loi)) {
      errors.push("LOI (Length of Interview) is required and must be greater than 0");
    }
    if (!toNumber(preparedForm.cpi)) {
      errors.push("CPI (Cost Per Interview) is required and must be greater than 0");
    }
    
    if (errors.length > 0) {
      setError("❌ " + errors.join("\n❌ "));
      return;
    }

    setLoading(true);
    const sessionId = localStorage.getItem("session_id");
    if (!sessionId) {
      navigate("/login");
      return;
    }

    try {
      const payload = {
        ...preparedForm,
        vendorCompleteRD: normalizeList(preparedForm.vendorCompleteRD),
        vendorTerminateRD: normalizeList(preparedForm.vendorTerminateRD),
        vendorQuotaFullRD: normalizeList(preparedForm.vendorQuotaFullRD),
      };

      const url = editingId
        ? buildApiUrl(`/projects/${editingId}`)
        : buildApiUrl(`/projects/`);
      const method = editingId ? "PUT" : "POST";

      const res = await fetch(url, {
        method,
        headers: {
          "Content-Type": "application/json",
          Authorization: sessionId,
        },
        body: JSON.stringify(payload),
      });

      if (res.status === 401) {
        alert("Session expired. Please login again.");
        localStorage.removeItem("session_id");
        navigate("/login");
        return;
      }

      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to save project");

      if (editingId) {
        setProjects((prev) =>
          prev.map((p) =>
            p._id === editingId ? (data.project || { ...p, ...payload }) : p
          )
        );
      } else {
        setProjects((prev) => [...prev, data.project]);
      }

      setShowForm(false);
      setEditingId(null);
      setFormData(emptyForm);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // 🔹 Delete Project
  const deleteProject = async (id) => {
    if (!window.confirm("Delete this project?")) return;

    const sessionId = localStorage.getItem("session_id");
    if (!sessionId) {
      navigate("/login");
      return;
    }

    try {
      const res = await fetch(buildApiUrl(`/projects/${id}`), {
        method: "DELETE",
        headers: {
          "Content-Type": "application/json",
          Authorization: sessionId,
        },
      });

      if (res.status === 401) {
        alert("Session expired. Please login again.");
        localStorage.removeItem("session_id");
        navigate("/login");
        return;
      }

      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "Failed to delete project");

      setProjects((prev) => prev.filter((p) => p._id !== id));
    } catch (err) {
      console.error("❌ Delete failed:", err.message);
    }
  };

  // 🔹 Search filter
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return projects;
    return projects.filter((p) =>
      ["projectName", "client", "salesPerson", "surveyNo", "vendorName"].some(
        (field) => String(p[field] || "").toLowerCase().includes(q)
      )
    );
  }, [projects, search]);

  const totalPages = Math.ceil(filtered.length / recordsPerPage);
  const startIdx = (currentPage - 1) * recordsPerPage;
  const endIdx = startIdx + recordsPerPage;
  const paginatedProjects = filtered.slice(startIdx, endIdx);

  const handleSearch = (value) => {
    setSearch(value);
    setCurrentPage(1);
  };

  const handleRecordsPerPageChange = (value) => {
    setRecordsPerPage(parseInt(value));
    setCurrentPage(1);
  };

  const liveCount = projects.filter(p => p.projectStatus === 'live').length;
  const pausedCount = projects.filter(p => p.projectStatus === 'pause').length;

  return (
    <div className="pp-container">
      {/* Header */}
      <div className="pp-header">
        <div className="pp-header-left">
          <div className="pp-title-row">
            <FolderOpen size={22} className="pp-title-icon" />
            <h2 className="pp-title">Projects</h2>
          </div>
          <div className="pp-stat-pills">
            <span className="pp-pill">{projects.length} Total</span>
            <span className="pp-pill pp-pill-live">{liveCount} Active</span>
            {pausedCount > 0 && <span className="pp-pill pp-pill-pause">{pausedCount} Paused</span>}
          </div>
        </div>
        <button
          className="pp-btn-primary"
          onClick={() => {
            setEditingId(null);
            setError(null);
            setFormData(applyDerivedFields(emptyForm));
            setShowForm(true);
          }}
        >
          <Plus size={16} /> New Project
        </button>
      </div>

      {/* Search Bar */}
      <div className="pp-toolbar">
        <div className="pp-search-wrap">
          <Search size={16} className="pp-search-icon" />
          <input
            className="pp-search"
            value={search}
            onChange={(e) => handleSearch(e.target.value)}
            placeholder="Search projects, clients, vendors..."
          />
        </div>
        <select
          className="pp-per-page"
          value={recordsPerPage}
          onChange={e => handleRecordsPerPageChange(e.target.value)}
        >
          <option value={10}>10 rows</option>
          <option value={20}>20 rows</option>
          <option value={50}>50 rows</option>
          <option value={100}>100 rows</option>
        </select>
      </div>

      {error && <div className="pp-error">{error}</div>}

      {/* Table */}
      <div className="pp-table-wrap">
        <table className="pp-table">
          <thead>
            <tr>
              <th>Project</th>
              <th>Survey #</th>
              <th>Client</th>
              <th>Status</th>
              <th>Launch</th>
              <th>Close</th>
              <th>Vendor</th>
              <th>Completes</th>
              <th>Med. LOI</th>
              <th>IR</th>
              <th className="pp-th-actions">Actions</th>
            </tr>
          </thead>
          <tbody>
            {paginatedProjects.map(p => (
              <tr key={p._id}>
                <td>
                  <span
                    className="pp-project-name"
                    onClick={() => navigate(`/admin/operations/projects/${p._id}`)}
                  >
                    {p.projectName}
                  </span>
                </td>
                <td><code className="pp-survey-no">{p.surveyNo}</code></td>
                <td className="pp-td-client">{p.client}</td>
                <td>
                  <span className={`pp-status pp-status-${p.projectStatus || 'close'}`}>
                    {p.projectStatus}
                  </span>
                </td>
                <td className="pp-td-date">{p.projectLaunchDate || "—"}</td>
                <td className="pp-td-date">{p.projectCloseDate || "—"}</td>
                <td className="pp-td-vendor">{p.vendorName || "—"}</td>
                <td>{p.qreStudyId && qreStatsMap[p.qreStudyId]?.completed != null ? qreStatsMap[p.qreStudyId].completed : (p.totalCompletes || "—")}</td>
                <td>{p.qreStudyId && qreStatsMap[p.qreStudyId]?.median_loi != null ? `${qreStatsMap[p.qreStudyId].median_loi} min` : (p.loi ? `${p.loi} min` : "—")}</td>
                <td>{p.qreStudyId && qreStatsMap[p.qreStudyId]?.incidence_rate != null ? `${qreStatsMap[p.qreStudyId].incidence_rate}%` : (p.actualIR ? `${p.actualIR}%` : "—")}</td>
                <td>
                  <div className="pp-actions">
                    <button
                      className="pp-act-btn pp-act-view"
                      title="View details"
                      onClick={() => navigate(`/admin/operations/projects/${p._id}`)}
                    >
                      <Eye size={14} />
                    </button>
                    <button
                      className="pp-act-btn pp-act-edit"
                      title="Edit project"
                      onClick={() => {
                        setEditingId(p._id);
                        setError(null);
                        setFormData(normalizeProjectForEdit(p));
                        setShowForm(true);
                      }}
                    >
                      <Pencil size={14} />
                    </button>
                    <button
                      className="pp-act-btn pp-act-delete"
                      title="Delete project"
                      onClick={() => deleteProject(p._id)}
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {paginatedProjects.length === 0 && (
              <tr>
                  <td colSpan={11} className="pp-empty">
                  <FolderOpen size={32} />
                  <p>No projects found.</p>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="pp-pagination">
          <button
            className="pp-page-btn"
            onClick={() => setCurrentPage(Math.max(1, currentPage - 1))}
            disabled={currentPage === 1}
          >
            <ChevronLeft size={16} /> Prev
          </button>
          <span className="pp-page-info">
            {currentPage} / {totalPages}
          </span>
          <button
            className="pp-page-btn"
            onClick={() => setCurrentPage(Math.min(totalPages, currentPage + 1))}
            disabled={currentPage === totalPages}
          >
            Next <ChevronRight size={16} />
          </button>
        </div>
      )}

      {/* Modal */}
      {showForm && (
        <div className="pp-overlay" onClick={() => setShowForm(false)}>
          <div className="pp-modal" onClick={(e) => e.stopPropagation()}>
            <div className="pp-modal-header">
              <h3>{editingId ? "Edit Project" : "New Project"}</h3>
              <button className="pp-modal-close" onClick={() => setShowForm(false)}>
                <X size={20} />
              </button>
            </div>

            <div className="pp-modal-body">
              {/* Basic Information */}
              <fieldset className="pp-fieldset">
                <legend>Basic Information</legend>
                <div className="pp-form-row">
                  <div className="pp-field">
                    <label>Project Name <span className="pp-req">*</span></label>
                    <input name="projectName" value={formData.projectName} onChange={handleChange} placeholder="Enter project name" />
                  </div>
                  <div className="pp-field">
                    <label>Survey No.</label>
                    <input name="surveyNo" value={formData.surveyNo} onChange={handleChange} placeholder="Auto-generated" disabled />
                  </div>
                </div>
                <div className="pp-form-row">
                  <div className="pp-field">
                    <label>Sales Person <span className="pp-req">*</span></label>
                    <input name="salesPerson" value={formData.salesPerson} onChange={handleChange} placeholder="Sales person name" />
                  </div>
                  <div className="pp-field">
                    <label>Project Value</label>
                    <input name="projectValue" value={formData.projectValue} onChange={handleChange} placeholder="Value" type="number" />
                  </div>
                </div>
                <div className="pp-form-row">
                  <div className="pp-field">
                    <label>Client <span className="pp-req">*</span></label>
                    <select name="client" value={formData.client} onChange={handleChange}>
                      <option value="">Select Client</option>
                      {clients.map((c) => (
                        <option key={c._id} value={c.company_name || c.name}>
                          {c.company_name || c.name}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="pp-field">
                    <label>Status</label>
                    <select name="projectStatus" value={formData.projectStatus} onChange={handleChange}>
                      <option value="live">Live</option>
                      <option value="pause">Pause</option>
                      <option value="close">Close</option>
                    </select>
                  </div>
                </div>
                <div className="pp-form-row">
                  <div className="pp-field">
                    <label>Launch Date <span className="pp-req">*</span></label>
                    <input type="date" name="projectLaunchDate" value={formData.projectLaunchDate} onChange={handleChange} />
                  </div>
                  <div className="pp-field">
                    <label>Close Date <span className="pp-req">*</span></label>
                    <input type="date" name="projectCloseDate" value={formData.projectCloseDate} onChange={handleChange} />
                  </div>
                </div>
                <div className="pp-form-row">
                  <div className="pp-field">
                    <label>Country Code <span className="pp-req">*</span></label>
                    <input
                      name="countryCode"
                      value={formData.countryCode}
                      onChange={handleChange}
                      placeholder="e.g. IN, US, GB"
                      maxLength={10}
                    />
                    <small className="pp-hint">ISO country code used in the entry link (e.g. IN for India).</small>
                  </div>
                </div>
              </fieldset>

              {/* RFQ */}
              <fieldset className="pp-fieldset">
                <legend>RFQ Details</legend>
                <div className="pp-field">
                  <label>RFQ</label>
                  <select name="rfqId" value={formData.rfqId} onChange={handleRfqChange}>
                    <option value="">Select RFQ (optional)</option>
                    {formData.rfqId && !rfqs.some((item) => (item._id || item.rfq_id) === formData.rfqId) && (
                      <option value={formData.rfqId}>{formData.rfqId}</option>
                    )}
                    {rfqs.map((rfq) => {
                      const value = rfq._id || rfq.rfq_id;
                      return (
                        <option key={value} value={value}>
                          {formatRfqLabel(rfq)}
                        </option>
                      );
                    })}
                  </select>
                </div>
                <div className="pp-field">
                  <label>RFQ Details</label>
                  <textarea name="rfqDetails" value={formData.rfqDetails} onChange={handleChange} placeholder="Enter RFQ details" rows="3" />
                </div>
                <div className="pp-form-row">
                  <div className="pp-field">
                    <label>Total Completes Required</label>
                    <input name="totalCompletesRequired" value={formData.totalCompletesRequired} onChange={handleChange} placeholder="—" type="number" />
                  </div>
                  <div className="pp-field">
                    <label>LOI (minutes)</label>
                    <input name="loi" value={formData.loi} onChange={handleChange} placeholder="—" type="number" />
                  </div>
                </div>
                <div className="pp-form-row">
                  <div className="pp-field">
                    <label>Client IR (%)</label>
                    <input name="clientIR" value={formData.clientIR} onChange={handleChange} placeholder="—" type="number" />
                  </div>
                  <div className="pp-field">
                    <label>CPI</label>
                    <input name="cpi" value={formData.cpi} onChange={handleChange} placeholder="—" type="number" />
                  </div>
                </div>
              </fieldset>

              {/* Survey Metrics */}
              <fieldset className="pp-fieldset">
                <legend>Survey Metrics</legend>
                <div className="pp-form-row">
                  <div className="pp-field">
                    <label>Total Completes</label>
                    <input name="totalCompletes" value={formData.totalCompletes} onChange={handleChange} type="number" />
                  </div>
                  <div className="pp-field">
                    <label>Total Respondents</label>
                    <input name="totalRespondents" value={formData.totalRespondents} onChange={handleChange} placeholder="Survey entrants" type="number" />
                  </div>
                </div>
                <div className="pp-form-row">
                  <div className="pp-field">
                    <label>Actual Completes</label>
                    <input name="actualCompletes" value={formData.actualCompletes} onChange={handleChange} type="number" />
                  </div>
                  <div className="pp-field">
                    <label>Actual IR (%)</label>
                    <input className="pp-readonly" name="actualIR" value={formData.actualIR} readOnly />
                  </div>
                </div>
                <div className="pp-form-row">
                  <div className="pp-field">
                    <label>QRE Study</label>
                    <select name="qreStudyId" value={formData.qreStudyId || ""} onChange={handleChange}>
                      <option value="">— None —</option>
                      {qreStudies.map(s => (
                        <option key={s.id} value={s.id}>{s.name} ({s.client_name})</option>
                      ))}
                    </select>
                    <small className="pp-hint">Links this project to a QRE survey for real-time stats.</small>
                  </div>
                </div>
              </fieldset>

              {/* Survey Links */}
              <fieldset className="pp-fieldset">
                <legend>Survey Links</legend>
                <div className="pp-field">
                  <label>Live Link <span className="pp-req">*</span></label>
                  <input name="liveLink" value={formData.liveLink} onChange={handleChange} placeholder="https://survey.example.com/..." />
                </div>
                <div className="pp-field">
                  <label>Entry Link Template</label>
                  <input className="pp-readonly" name="entryLink" value={formData.entryLink} readOnly />
                  <small className="pp-hint">Vendor-facing URL template with placeholders.</small>
                </div>
                <div className="pp-field">
                  <label>Complete Page URL</label>
                  <input className="pp-readonly" name="completePage" value={formData.completePage} readOnly />
                </div>
                <div className="pp-field">
                  <label>Terminate Page URL</label>
                  <input className="pp-readonly" name="terminatePage" value={formData.terminatePage} readOnly />
                </div>
                <div className="pp-field">
                  <label>Quota Full Page URL</label>
                  <input className="pp-readonly" name="quotaFullPage" value={formData.quotaFullPage} readOnly />
                  <small className="pp-hint">Auto-generated from survey provider format.</small>
                </div>
              </fieldset>

              {/* Vendor */}
              <fieldset className="pp-fieldset">
                <legend>Vendor Assignment</legend>
                <div className="pp-field">
                  <label>Vendor <span className="pp-req">*</span></label>
                  <select name="vendorName" value={formData.vendorName} onChange={handleVendorChange}>
                    <option value="">Select Vendor</option>
                    {vendors.map(v => (
                      <option key={v._id} value={v.vendorName}>{v.vendorName}</option>
                    ))}
                  </select>
                </div>
                {formData.vendorName && (
                  <div className="pp-vendor-urls">
                    <div className="pp-vendor-url-row">
                      <span className="pp-vendor-url-label">Complete RD</span>
                      <span className="pp-vendor-url-val">{formData.vendorCompleteRD?.join(", ") || "N/A"}</span>
                    </div>
                    <div className="pp-vendor-url-row">
                      <span className="pp-vendor-url-label">Terminate RD</span>
                      <span className="pp-vendor-url-val">{formData.vendorTerminateRD?.join(", ") || "N/A"}</span>
                    </div>
                    <div className="pp-vendor-url-row">
                      <span className="pp-vendor-url-label">QuotaFull RD</span>
                      <span className="pp-vendor-url-val">{formData.vendorQuotaFullRD?.join(", ") || "N/A"}</span>
                    </div>
                  </div>
                )}
              </fieldset>
            </div>

            <div className="pp-modal-footer">
              <button className="pp-btn-cancel" onClick={() => setShowForm(false)}>Cancel</button>
              <button className="pp-btn-save" onClick={saveProject} disabled={loading}>
                {loading ? "Saving..." : editingId ? "Update" : "Create"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default ProjectsPage
