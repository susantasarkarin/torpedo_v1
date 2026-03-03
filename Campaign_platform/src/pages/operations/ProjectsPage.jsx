"use client";

import { useEffect, useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import "./ProjectsPage.css";
import { buildApiUrl } from "../../config"

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
    liveLink: "",
    completePage: "",
    terminatePage: "",
    quotaFullPage: "",
    vendorName: "",
    vendorCompleteRD: [],
    vendorTerminateRD: [],
    vendorQuotaFullRD: [],
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
    return "https://torpedo.cogentixresearch.com";
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

  const applyDerivedFields = (nextForm) => {
    const actualIR = computeActualIR(nextForm.actualCompletes, nextForm.totalRespondents);
    const generatedPages = getSystemGeneratedPages(nextForm.liveLink);
    return {
      ...nextForm,
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

  const normalizeProjectForEdit = (project) =>
    applyDerivedFields({
      ...emptyForm,
      ...project,
      vendorCompleteRD: normalizeList(project.vendorCompleteRD),
      vendorTerminateRD: normalizeList(project.vendorTerminateRD),
      vendorQuotaFullRD: normalizeList(project.vendorQuotaFullRD),
      rfqId: project.rfqId || "",
    });

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
        const res = await fetch(buildApiUrl(`/finance/finance/customers/`), {
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
  }, [navigate]);

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
          vendorCompleteRD: normalizeList(vendor.completeRD),
          vendorTerminateRD: normalizeList(vendor.terminateRD),
          vendorQuotaFullRD: normalizeList(vendor.quotaRD || vendor.quotaFullRD),
        })
      );
    } else {
      setFormData((prev) => applyDerivedFields({ ...prev, vendorName }));
    }
  };

  // 🔹 Save Project
  const saveProject = async () => {
    const errors = [];
    
    if (!formData.projectName || !formData.projectName.trim()) {
      errors.push("Project Name is required");
    }
    if (!formData.salesPerson || !formData.salesPerson.trim()) {
      errors.push("Sales Person is required");
    }
    if (!formData.client || !formData.client.trim()) {
      errors.push("Client is required");
    }
    if (!formData.projectLaunchDate) {
      errors.push("Project Launch Date is required");
    }
    if (!formData.projectCloseDate) {
      errors.push("Project Close Date is required");
    }
    if (!formData.liveLink || !formData.liveLink.trim()) {
      errors.push("Live Link is required");
    }
    if (!formData.vendorName || !formData.vendorName.trim()) {
      errors.push("Vendor Name is required");
    }
    if (!toNumber(formData.totalCompletesRequired)) {
      errors.push("Total Completes Required is required and must be greater than 0");
    }
    if (!toNumber(formData.loi)) {
      errors.push("LOI (Length of Interview) is required and must be greater than 0");
    }
    if (!toNumber(formData.cpi)) {
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
      const derivedForm = applyDerivedFields(formData);
      const payload = {
        ...derivedForm,
        vendorCompleteRD: normalizeList(derivedForm.vendorCompleteRD),
        vendorTerminateRD: normalizeList(derivedForm.vendorTerminateRD),
        vendorQuotaFullRD: normalizeList(derivedForm.vendorQuotaFullRD),
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

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <div>
          <h2 style={styles.title}>Projects</h2>
          <p style={styles.subtitle}>Manage your survey projects and vendor assignments</p>
        </div>
        <button
          style={styles.btnPrimary}
          onClick={() => {
            setEditingId(null)
            setError(null)
            setFormData(applyDerivedFields(emptyForm))
            setShowForm(true)
          }}
        >
          + Add New Project
        </button>
      </div>

      <div style={styles.searchSection}>
        <input
          style={styles.searchInput}
          value={search}
          onChange={(e) => handleSearch(e.target.value)}
          placeholder="Search by project, client, survey number, vendor..."
        />
        <select
          style={styles.recordsPerPageSelect}
          value={recordsPerPage}
          onChange={e => handleRecordsPerPageChange(e.target.value)}
        >
          <option value={10}>10 per page</option>
          <option value={20}>20 per page</option>
          <option value={50}>50 per page</option>
          <option value={100}>100 per page</option>
          <option value={200}>200 per page</option>
        </select>
        <div style={styles.stats}>
          <span>Total Projects: <strong>{projects.length}</strong></span>
          <span>Active: <strong>{projects.filter(p => p.projectStatus === 'live').length}</strong></span>
        </div>
      </div>

      {error && <div style={styles.errorBanner}>{error}</div>}

      <div style={styles.tableContainer}>
        <table style={styles.table}>
          <thead style={styles.thead}>
            <tr>
              <th style={styles.th}>Project Name</th>
              <th style={styles.th}>Survey No.</th>
              <th style={styles.th}>Client</th>
              <th style={styles.th}>Status</th>
              <th style={styles.th}>Launch Date</th>
              <th style={styles.th}>Close Date</th>
              <th style={styles.th}>Vendor</th>
              <th style={styles.th}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {paginatedProjects.map(p => (
              <tr key={p._id} style={styles.tr}>
                <td style={styles.td}>
                  <span
                    style={{
                      ...styles.td,
                      cursor: "pointer",
                      color: "#667eea",
                      textDecoration: "underline",
                      fontWeight: "500"
                    }}
                    onClick={() => navigate(`/admin/operations/projects/${p._id}`)}
                  >
                    {p.projectName}
                  </span>
                </td>
                <td style={styles.td}>{p.surveyNo}</td>
                <td style={styles.td}>{p.client}</td>
                <td style={styles.td}>
                  <span style={{
                    ...styles.statusBadge,
                    ...(p.projectStatus === 'live' ? styles.statusLive : 
                        p.projectStatus === 'pause' ? styles.statusPause : 
                        styles.statusClose)
                  }}>
                    {p.projectStatus}
                  </span>
                </td>
                <td style={styles.td}>{p.projectLaunchDate}</td>
                <td style={styles.td}>{p.projectCloseDate}</td>
                <td style={styles.td}>{p.vendorName}</td>
                <td style={styles.td}>
                  <div style={styles.actionButtons}>
                    <button
                      style={styles.btnEdit}
                      onClick={() => {
                        setEditingId(p._id)
                        setError(null)
                        setFormData(normalizeProjectForEdit(p))
                        setShowForm(true)
                      }}
                    >
                      ✏️
                    </button>
                    <button style={styles.btnDelete} onClick={() => deleteProject(p._id)}>🗑️</button>
                  </div>
                </td>
              </tr>
            ))}
            {paginatedProjects.length === 0 && filtered.length === 0 && (
              <tr>
                <td colSpan={8} style={styles.emptyState}>
                  No projects found.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div style={styles.paginationContainer}>
          <button
            style={{...styles.paginationBtn, ...(currentPage === 1 ? styles.paginationBtnDisabled : {})}}
            onClick={() => setCurrentPage(Math.max(1, currentPage - 1))}
            disabled={currentPage === 1}
          >
            ← Previous
          </button>
          <div style={styles.pageInfo}>
            Page <strong>{currentPage}</strong> of <strong>{totalPages}</strong>
          </div>
          <button
            style={{...styles.paginationBtn, ...(currentPage === totalPages ? styles.paginationBtnDisabled : {})}}
            onClick={() => setCurrentPage(Math.min(totalPages, currentPage + 1))}
            disabled={currentPage === totalPages}
          >
            Next →
          </button>
        </div>
      )}

      {showForm && (
        <div style={styles.modal} onClick={() => setShowForm(false)}>
          <div style={styles.modalContent} onClick={(e) => e.stopPropagation()}>
            <div style={styles.modalHeader}>
              <h3 style={styles.modalTitle}>{editingId ? "Edit Project" : "Add New Project"}</h3>
              <button style={styles.closeBtn} onClick={() => setShowForm(false)}>×</button>
            </div>

            <div style={styles.modalBody}>
              <div style={styles.section}>
                <h4 style={styles.sectionTitle}>Basic Information</h4>
                <div style={styles.formRow}>
                  <div style={styles.formGroup}>
                    <label style={styles.label}>Project Name <span style={styles.required}>*</span></label>
                    <input style={styles.input} name="projectName" value={formData.projectName} onChange={handleChange} placeholder="Enter project name" />
                  </div>
                  <div style={styles.formGroup}>
                    <label style={styles.label}>Survey No.</label>
                    <input style={styles.input} name="surveyNo" value={formData.surveyNo} onChange={handleChange} placeholder="System generated" disabled />
                  </div>
                </div>

                <div style={styles.formRow}>
                  <div style={styles.formGroup}>
                    <label style={styles.label}>Sales Person <span style={styles.required}>*</span></label>
                    <input style={styles.input} name="salesPerson" value={formData.salesPerson} onChange={handleChange} placeholder="Sales person name" />
                  </div>
                  <div style={styles.formGroup}>
                    <label style={styles.label}>Project Value</label>
                    <input style={styles.input} name="projectValue" value={formData.projectValue} onChange={handleChange} placeholder="Enter value" type="number" />
                  </div>
                </div>

                <div style={styles.formRow}>
                  <div style={styles.formGroup}>
                    <label style={styles.label}>Client <span style={styles.required}>*</span></label>
                    <select style={styles.select} name="client" value={formData.client} onChange={handleChange} required>
                      <option value="">-- Select Client (Required) --</option>
                      {clients.map((c) => (
                        <option key={c._id} value={c.company_name || c.name}>
                          {c.company_name || c.name}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div style={styles.formGroup}>
                    <label style={styles.label}>Project Status</label>
                    <select style={styles.select} name="projectStatus" value={formData.projectStatus} onChange={handleChange}>
                      <option value="live">Live</option>
                      <option value="pause">Pause</option>
                      <option value="close">Close</option>
                    </select>
                  </div>
                </div>

                <div style={styles.formRow}>
                  <div style={styles.formGroup}>
                    <label style={styles.label}>Project Launch Date <span style={styles.required}>*</span></label>
                    <input style={styles.input} type="date" name="projectLaunchDate" value={formData.projectLaunchDate} onChange={handleChange} />
                  </div>
                  <div style={styles.formGroup}>
                    <label style={styles.label}>Project Close Date <span style={styles.required}>*</span></label>
                    <input style={styles.input} type="date" name="projectCloseDate" value={formData.projectCloseDate} onChange={handleChange} />
                  </div>
                </div>
              </div>

              <div style={styles.section}>
                <h4 style={styles.sectionTitle}>RFQ Details</h4>
                <div style={styles.formGroup}>
                  <label style={styles.label}>RFQ</label>
                  <select style={styles.select} name="rfqId" value={formData.rfqId} onChange={handleRfqChange}>
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
                <div style={styles.formGroup}>
                  <label style={styles.label}>RFQ Details</label>
                  <textarea style={styles.textarea} name="rfqDetails" value={formData.rfqDetails} onChange={handleChange} placeholder="Enter RFQ details" rows="3" />
                </div>

                <div style={styles.formRow}>
                  <div style={styles.formGroup}>
                    <label style={styles.label}>Total Completes Required</label>
                    <input
                      style={styles.input}
                      name="totalCompletesRequired"
                      value={formData.totalCompletesRequired}
                      onChange={handleChange}
                      placeholder="From RFQ field"
                      type="number"
                    />
                  </div>
                  <div style={styles.formGroup}>
                    <label style={styles.label}>LOI (Length of Interview)</label>
                    <input
                      style={styles.input}
                      name="loi"
                      value={formData.loi}
                      onChange={handleChange}
                      placeholder="From RFQ"
                      type="number"
                    />
                  </div>
                </div>

                <div style={styles.formRow}>
                  <div style={styles.formGroup}>
                    <label style={styles.label}>Client IR (%)</label>
                    <input
                      style={styles.input}
                      name="clientIR"
                      value={formData.clientIR}
                      onChange={handleChange}
                      placeholder="From RFQ"
                      type="number"
                    />
                  </div>
                  <div style={styles.formGroup}>
                    <label style={styles.label}>CPI (Currency)</label>
                    <input
                      style={styles.input}
                      name="cpi"
                      value={formData.cpi}
                      onChange={handleChange}
                      placeholder="From RFQ"
                      type="number"
                    />
                  </div>
                </div>
              </div>

              <div style={styles.section}>
                <h4 style={styles.sectionTitle}>Survey Metrics</h4>
                <div style={styles.formRow}>
                  <div style={styles.formGroup}>
                    <label style={styles.label}>Total Completes</label>
                    <input
                      style={styles.input}
                      name="totalCompletes"
                      value={formData.totalCompletes}
                      onChange={handleChange}
                      placeholder="From RFQ"
                      type="number"
                    />
                  </div>
                  <div style={styles.formGroup}>
                    <label style={styles.label}>Total Respondents</label>
                    <input style={styles.input} name="totalRespondents" value={formData.totalRespondents} onChange={handleChange} placeholder="Total survey entrants" type="number" />
                  </div>
                </div>

                <div style={styles.formRow}>
                  <div style={styles.formGroup}>
                    <label style={styles.label}>Actual Completes</label>
                    <input style={styles.input} name="actualCompletes" value={formData.actualCompletes} onChange={handleChange} placeholder="Completes registered in survey" type="number" />
                  </div>
                  <div style={styles.formGroup}>
                    <label style={styles.label}>Actual IR (%)</label>
                    <input
                      style={{ ...styles.input, ...styles.readOnlyField }}
                      name="actualIR"
                      value={formData.actualIR}
                      placeholder="Actual completes/survey respondents"
                      type="number"
                      readOnly
                    />
                  </div>
                </div>
              </div>

              <div style={styles.section}>
                <h4 style={styles.sectionTitle}>Survey Links</h4>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Live Link <span style={styles.required}>*</span></label>
                  <input style={styles.input} name="liveLink" value={formData.liveLink} onChange={handleChange} placeholder="https://www.surveyfieldwork.com/live?rid=XXXX" />
                </div>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Complete Page URL</label>
                  <input
                    style={{ ...styles.input, ...styles.readOnlyField }}
                    name="completePage"
                    value={formData.completePage}
                    placeholder="System generated"
                    readOnly
                  />
                </div>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Terminate Page URL</label>
                  <input
                    style={{ ...styles.input, ...styles.readOnlyField }}
                    name="terminatePage"
                    value={formData.terminatePage}
                    placeholder="System generated"
                    readOnly
                  />
                </div>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Quota Full Page URL</label>
                  <input
                    style={{ ...styles.input, ...styles.readOnlyField }}
                    name="quotaFullPage"
                    value={formData.quotaFullPage}
                    placeholder="System generated"
                    readOnly
                  />
                  <small style={styles.fieldHint}>
                    Generated automatically using CPX/CINT callback format.
                  </small>
                </div>
              </div>

              <div style={styles.section}>
                <h4 style={styles.sectionTitle}>Vendor Assignment</h4>
                <div style={styles.formGroup}>
                  <label style={styles.label}>Vendor Name <span style={styles.required}>*</span></label>
                  <select style={styles.select} name="vendorName" value={formData.vendorName} onChange={handleVendorChange}>
                    <option value="">Select Vendor</option>
                    {vendors.map(v => (
                      <option key={v._id} value={v.vendorName}>{v.vendorName}</option>
                    ))}
                  </select>
                </div>

                {formData.vendorName && (
                  <div style={styles.vendorLinks}>
                    <div style={styles.linkGroup}>
                      <strong style={styles.linkLabel}>Vendor Complete RD:</strong>
                      <span style={styles.linkValue}>{formData.vendorCompleteRD?.join(", ") || "N/A"}</span>
                    </div>
                    <div style={styles.linkGroup}>
                      <strong style={styles.linkLabel}>Vendor Terminate RD:</strong>
                      <span style={styles.linkValue}>{formData.vendorTerminateRD?.join(", ") || "N/A"}</span>
                    </div>
                    <div style={styles.linkGroup}>
                      <strong style={styles.linkLabel}>Vendor QuotaFull RD:</strong>
                      <span style={styles.linkValue}>{formData.vendorQuotaFullRD?.join(", ") || "N/A"}</span>
                    </div>
                  </div>
                )}
              </div>
            </div>

            <div style={styles.modalFooter}>
              <button style={styles.btnCancel} onClick={() => setShowForm(false)}>Cancel</button>
              <button style={styles.btnSave} onClick={saveProject} disabled={loading}>
                {loading ? "Saving..." : editingId ? "Update Project" : "Create Project"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

const styles = {
  container: {
    maxWidth: '1400px',
    margin: '0 auto',
    padding: '2rem',
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
    backgroundColor: '#f8f9fa',
    minHeight: '100vh',
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: '2rem',
  },
  title: {
    fontSize: '2rem',
    fontWeight: '700',
    margin: '0 0 0.5rem 0',
    color: '#1a1a1a',
  },
  subtitle: {
    color: '#6b7280',
    margin: '0',
    fontSize: '0.95rem',
  },
  btnPrimary: {
    padding: '0.75rem 1.5rem',
    backgroundColor: '#0d6efd',
    color: 'white',
    border: 'none',
    borderRadius: '0.5rem',
    fontSize: '0.95rem',
    fontWeight: '500',
    cursor: 'pointer',
    transition: 'all 0.2s',
  },
  searchSection: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: '1.5rem',
    padding: '1.25rem',
    backgroundColor: 'white',
    borderRadius: '0.75rem',
    boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
  },
  searchInput: {
    flex: '1',
    maxWidth: '400px',
    padding: '0.75rem 1rem',
    border: '1px solid #d1d5db',
    borderRadius: '0.5rem',
    fontSize: '0.95rem',
  },
  recordsPerPageSelect: {
    padding: '0.75rem 1rem',
    border: '1px solid #d1d5db',
    borderRadius: '0.5rem',
    fontSize: '0.95rem',
    backgroundColor: 'white',
    cursor: 'pointer',
  },
  stats: {
    display: 'flex',
    gap: '2rem',
    fontSize: '0.9rem',
    color: '#6b7280',
  },
  errorBanner: {
    marginBottom: '1rem',
    padding: '0.85rem 1rem',
    border: '1px solid #fecaca',
    borderRadius: '0.5rem',
    backgroundColor: '#fef2f2',
    color: '#991b1b',
    whiteSpace: 'pre-line',
  },
  tableContainer: {
    backgroundColor: 'white',
    borderRadius: '0.75rem',
    overflow: 'hidden',
    boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
  },
  table: {
    width: '100%',
    borderCollapse: 'collapse',
  },
  thead: {
    backgroundColor: '#f9fafb',
    borderBottom: '2px solid #e5e7eb',
  },
  th: {
    padding: '1rem',
    textAlign: 'left',
    fontSize: '0.75rem',
    fontWeight: '600',
    textTransform: 'uppercase',
    color: '#6b7280',
    letterSpacing: '0.05em',
  },
  tr: {
    borderBottom: '1px solid #e5e7eb',
    transition: 'background-color 0.15s',
  },
  td: {
    padding: '1rem',
    fontSize: '0.9rem',
    color: '#374151',
  },
  statusBadge: {
    display: 'inline-block',
    padding: '0.375rem 0.75rem',
    borderRadius: '0.375rem',
    fontSize: '0.8rem',
    fontWeight: '600',
    textTransform: 'capitalize',
  },
  statusLive: {
    backgroundColor: '#d1fae5',
    color: '#065f46',
  },
  statusPause: {
    backgroundColor: '#fef3c7',
    color: '#92400e',
  },
  statusClose: {
    backgroundColor: '#e5e7eb',
    color: '#6b7280',
  },
  actionButtons: {
    display: 'flex',
    gap: '0.5rem',
  },
  btnEdit: {
    padding: '0.5rem 0.75rem',
    backgroundColor: '#6b7280',
    color: 'white',
    border: 'none',
    borderRadius: '0.375rem',
    cursor: 'pointer',
    fontSize: '1rem',
  },
  btnDelete: {
    padding: '0.5rem 0.75rem',
    backgroundColor: '#ef4444',
    color: 'white',
    border: 'none',
    borderRadius: '0.375rem',
    cursor: 'pointer',
    fontSize: '1rem',
  },
  emptyState: {
    textAlign: 'center',
    padding: '3rem',
    color: '#9ca3af',
  },
  modal: {
    position: 'fixed',
    top: '0',
    left: '0',
    right: '0',
    bottom: '0',
    backgroundColor: 'rgba(0, 0, 0, 0.5)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: '1000',
    padding: '1rem',
  },
  modalContent: {
    backgroundColor: 'white',
    borderRadius: '0.75rem',
    width: '100%',
    maxWidth: '900px',
    maxHeight: '90vh',
    overflow: 'hidden',
    display: 'flex',
    flexDirection: 'column',
    boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.25)',
  },
  modalHeader: {
    padding: '1.5rem',
    borderBottom: '1px solid #e5e7eb',
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    backgroundColor: 'white',
  },
  modalTitle: {
    fontSize: '1.5rem',
    fontWeight: '600',
    color: '#1a1a1a',
    margin: '0',
  },
  closeBtn: {
    background: 'none',
    border: 'none',
    fontSize: '2rem',
    color: '#9ca3af',
    cursor: 'pointer',
    padding: '0',
    width: '2rem',
    height: '2rem',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    lineHeight: '1',
  },
  modalBody: {
    padding: '1.5rem',
    overflowY: 'auto',
    flex: '1',
  },
  section: {
    marginBottom: '2rem',
    paddingBottom: '1.5rem',
    borderBottom: '1px solid #e5e7eb',
  },
  sectionTitle: {
    fontSize: '1.1rem',
    fontWeight: '600',
    color: '#1a1a1a',
    marginBottom: '1rem',
  },
  formRow: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: '1rem',
    marginBottom: '1rem',
  },
  formGroup: {
    display: 'flex',
    flexDirection: 'column',
  },
  label: {
    marginBottom: '0.5rem',
    fontSize: '0.875rem',
    fontWeight: '500',
    color: '#374151',
  },
  required: {
    color: '#ef4444',
  },
  input: {
    padding: '0.75rem',
    border: '1px solid #d1d5db',
    borderRadius: '0.5rem',
    fontSize: '0.95rem',
    transition: 'all 0.2s',
    backgroundColor: 'white',
  },
  select: {
    padding: '0.75rem',
    border: '1px solid #d1d5db',
    borderRadius: '0.5rem',
    fontSize: '0.95rem',
    transition: 'all 0.2s',
    cursor: 'pointer',
    backgroundColor: 'white',
  },
  readOnlyField: {
    backgroundColor: '#f3f4f6',
    color: '#374151',
  },
  textarea: {
    padding: '0.75rem',
    border: '1px solid #d1d5db',
    borderRadius: '0.5rem',
    fontSize: '0.95rem',
    transition: 'all 0.2s',
    fontFamily: 'inherit',
    resize: 'vertical',
  },
  fieldHint: {
    marginTop: '0.35rem',
    color: '#6b7280',
    fontSize: '0.8rem',
  },
  vendorLinks: {
    marginTop: '1rem',
    padding: '1rem',
    backgroundColor: '#f9fafb',
    borderRadius: '0.5rem',
  },
  linkGroup: {
    marginBottom: '0.75rem',
    display: 'flex',
    flexDirection: 'column',
    gap: '0.25rem',
  },
  linkLabel: {
    fontSize: '0.875rem',
    color: '#6b7280',
  },
  linkValue: {
    fontSize: '0.875rem',
    color: '#374151',
    wordBreak: 'break-all',
  },
  modalFooter: {
    padding: '1rem 1.5rem',
    borderTop: '1px solid #e5e7eb',
    display: 'flex',
    justifyContent: 'flex-end',
    gap: '0.75rem',
    backgroundColor: 'white',
  },
  btnCancel: {
    padding: '0.75rem 1.5rem',
    backgroundColor: '#6b7280',
    color: 'white',
    border: 'none',
    borderRadius: '0.5rem',
    fontSize: '0.95rem',
    fontWeight: '500',
    cursor: 'pointer',
  },
  btnSave: {
    padding: '0.75rem 1.5rem',
    backgroundColor: '#0d6efd',
    color: 'white',
    border: 'none',
    borderRadius: '0.5rem',
    fontSize: '0.95rem',
    fontWeight: '500',
    cursor: 'pointer',
  },
  paginationContainer: {
    display: 'flex',
    justifyContent: 'center',
    alignItems: 'center',
    gap: '1rem',
    marginTop: '2rem',
    padding: '1rem',
    backgroundColor: 'white',
    borderRadius: '0.75rem',
    boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
  },
  paginationBtn: {
    padding: '0.5rem 1rem',
    backgroundColor: '#0d6efd',
    color: 'white',
    border: 'none',
    borderRadius: '0.375rem',
    fontSize: '0.9rem',
    fontWeight: '500',
    cursor: 'pointer',
    transition: 'all 0.2s',
  },
  paginationBtnDisabled: {
    backgroundColor: '#d1d5db',
    cursor: 'not-allowed',
    opacity: '0.6',
  },
  pageInfo: {
    fontSize: '0.9rem',
    color: '#6b7280',
    minWidth: '150px',
    textAlign: 'center',
  },
}

export default ProjectsPage
