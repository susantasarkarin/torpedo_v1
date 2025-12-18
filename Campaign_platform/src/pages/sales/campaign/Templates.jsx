"use client"

import { useNavigate } from "react-router-dom"
import "./Templates.css"
import { useState, useEffect } from "react"
import { API_BASE_URL } from "../../../config"; // adjust path if needed


function Templates() {
  const navigate = useNavigate()
  const [showPreviewModal, setShowPreviewModal] = useState(false)
  const [previewContent, setPreviewContent] = useState("")
  const [previewTitle, setPreviewTitle] = useState("")
  const [saving, setSaving] = useState(false) // added
  const [showForm, setShowForm] = useState(false) // added
  const [templates, setTemplates] = useState([])

  const [formData, setFormData] = useState({ name: "", category: "", subject: "", htmlContent: "" })
  const [editingTemplate, setEditingTemplate] = useState(null)

  const handleDeleteTemplate = async (id) => {
  if (!window.confirm("Are you sure you want to delete this template?")) return;

  const sessionId = localStorage.getItem("session_id");
  if (!sessionId) {
    navigate("/login");
    return;
  }

  try {
    const res = await fetch(`${API_BASE_URL}/templates/${id}`, {
      method: "DELETE",
      headers: {
        "Content-Type": "application/json",
        "Authorization": sessionId,
      },
    });

    if (res.status === 401) {
      alert("Session expired. Please login again.");
      localStorage.removeItem("session_id");
      navigate("/login");
      return;
    }

    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed to delete template");

    alert("Template deleted successfully");
    setTemplates((prev) => prev.filter((t) => t._id !== id));
  } catch (err) {
    alert("Error deleting template: " + err.message);
  }
};


  const handleFormSubmit = async (e) => {
  e.preventDefault();
  setSaving(true);

  const sessionId = localStorage.getItem("session_id");
  if (!sessionId) {
    navigate("/login");
    return;
  }

  try {
    const url = editingTemplate
      ? `${API_BASE_URL}/templates/${editingTemplate._id}`
      : `${API_BASE_URL}/templates/`;
    const method = editingTemplate ? "PUT" : "POST";

    const res = await fetch(url, {
      method,
      headers: {
        "Content-Type": "application/json",
        "Authorization": sessionId,
      },
      body: JSON.stringify(formData),
    });

    if (res.status === 401) {
      alert("Session expired. Please login again.");
      localStorage.removeItem("session_id");
      navigate("/login");
      return;
    }

    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed to save template");

    alert(editingTemplate ? "Template updated!" : "Template created!");
    setFormData({ name: "", category: "", subject: "", htmlContent: "" });
    setEditingTemplate(null);
    setShowForm(false);

    // refresh list after save
    const newRes = await fetch(`${API_BASE_URL}/templates/`, {
      headers: {
        "Content-Type": "application/json",
        "Authorization": sessionId,
      },
    });
    const newData = await newRes.json();
    setTemplates(newData.templates || []);
  } catch (err) {
    alert("Error: " + err.message);
  } finally {
    setSaving(false);
  }
};


  // fetch templates from backend
 useEffect(() => {
  const fetchTemplates = async () => {
    const sessionId = localStorage.getItem("session_id");
    if (!sessionId) {
      navigate("/login");
      return;
    }

    try {
      const res = await fetch(`${API_BASE_URL}/templates/`, {
        headers: {
          "Content-Type": "application/json",
          "Authorization": sessionId,
        },
      });

      if (res.status === 401) {
        alert("Session expired. Please login again.");
        localStorage.removeItem("session_id");
        navigate("/login");
        return;
      }

      if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      const data = await res.json();
      setTemplates(data.templates || []);
    } catch (err) {
      console.error("❌ Failed to fetch templates:", err.message);
      alert("Error loading templates: " + err.message);
    }
  };

  fetchTemplates();
}, [navigate]);



  const handlePreview = (htmlContent, title) => {
    setPreviewContent(htmlContent)
    setPreviewTitle(title)
    setShowPreviewModal(true)
  }

  const handleUseTemplate = (template) => {
    // ✅ do NOT save to DB again
    navigate("/admin/sales/campaign/list", { state: { selectedTemplate: template } })
  }

  const handleToggleForm = () => {
    setShowForm((prev) => !prev)
    setFormData({ name: "", category: "", subject: "", htmlContent: "" })
    setEditingTemplate(null)
  }

  return (
    <div className="templates-container">
      {/* --- header + form + grid wrapped together --- */}
      <div className="templates-library">
        <div className="templates-library-header">
          <h3 className="card-title">Template Library</h3>
          <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
            <select className="form-input" style={{ width: "auto" }}>
              <option>All Categories</option>
              <option>Onboarding</option>
              <option>Sales</option>
              <option>Marketing</option>
              <option>Nurturing</option>
              <option>E-commerce</option>
              <option>Outreach</option>
              <option>Follow-up</option>
              <option>Re-engagement</option>
            </select>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => {
                setEditingTemplate(null)
                setFormData({ name: "", category: "", subject: "", htmlContent: "" })
                setShowForm(true)
              }}
            >
              Create Template
            </button>
          </div>
        </div>

        {/* Create / Edit form */}
        {(showForm || editingTemplate) && (
          <form className="template-form" onSubmit={handleFormSubmit}>
            <input
              type="text"
              className="form-input"
              placeholder="Template Name"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              required
            />
            <input
              type="text"
              className="form-input"
              placeholder="Category"
              value={formData.category}
              onChange={(e) => setFormData({ ...formData, category: e.target.value })}
            />
            <input
              type="text"
              className="form-input"
              placeholder="Subject"
              value={formData.subject}
              onChange={(e) => setFormData({ ...formData, subject: e.target.value })}
              required
            />
            <textarea
              className="form-input"
              placeholder="HTML Content"
              rows={6}
              value={formData.htmlContent}
              onChange={(e) => setFormData({ ...formData, htmlContent: e.target.value })}
              required
            />
            <div className="form-actions">
              <button type="submit" className="btn btn-save" disabled={saving}>
                {saving ? "Saving..." : editingTemplate ? "Update Template" : "Create Template"}
              </button>
              <button
                type="button"
                className="btn btn-cancel"
                onClick={() => {
                  setEditingTemplate(null)
                  setFormData({ name: "", category: "", subject: "", htmlContent: "" })
                  setShowForm(false)
                }}
                disabled={saving}
              >
                Cancel
              </button>
            </div>
          </form>
        )}

        {/* Template list */}
        <div className="templates-grid">
          {templates.length === 0 && !showForm && (
            <div className="empty-state">
              <h4>No templates, click to create one</h4>
              <p>Create your first template to get started.</p>
              <button type="button" className="btn btn-primary" onClick={() => setShowForm(true)}>
                Create Template
              </button>
            </div>
          )}
          {templates.map((template) => (
            <div key={template._id} className="template-card">
              <div className="template-card-header">
                <div>
                  <h4 className="template-name">{template.name}</h4>
                  <span className="template-category">{template.category}</span>
                </div>
                <div style={{ textAlign: "right" }}>
                  <p className="template-meta">Used {template.usage ?? 0} times</p>
                  <p className="template-meta">Last: {template.lastUsed || "N/A"}</p>
                </div>
              </div>

              <div className="template-actions">
                <button
                  className="btn btn-preview"
                  onClick={() => handlePreview(template.htmlContent, template.name)}
                  type="button"
                >
                  Preview
                </button>

                <button className="btn btn-use" onClick={() => handleUseTemplate(template)} type="button">
                  Use Template
                </button>

                <button
                  className="btn btn-edit"
                  onClick={() => {
                    setEditingTemplate(template)
                    setFormData({
                      name: template.name || "",
                      category: template.category || "",
                      subject: template.subject || "",
                      htmlContent: template.htmlContent || "",
                    })
                    setShowForm(true)
                  }}
                  type="button"
                >
                  Edit
                </button>

                <button className="btn btn-delete" onClick={() => handleDeleteTemplate(template._id)} type="button">
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Preview Modal */}
      {showPreviewModal && (
        <div className="modal-overlay" onClick={() => setShowPreviewModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <button
              className="modal-close-btn"
              type="button"
              onClick={() => setShowPreviewModal(false)}
              aria-label="Close preview"
            >
              &times;
            </button>
            <h2 className="modal-title">Preview: {previewTitle}</h2>
            <iframe 
              srcDoc={previewContent}
              title="Template Preview"
              className="template-preview-iframe"
              sandbox="allow-same-origin"
            />
          </div>
        </div>
      )}
    </div>
  )
}

export default Templates
