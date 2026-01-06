"use client"

import { useNavigate } from "react-router-dom"
import "./Templates.css"
import { useState, useEffect, useRef } from "react"
import { API_BASE_URL } from "../../../config"

function Templates() {
  const navigate = useNavigate()
  const [templates, setTemplates] = useState([])
  const [selectedTemplate, setSelectedTemplate] = useState(null)
  const [viewMode, setViewMode] = useState("desktop")
  const [showEditor, setShowEditor] = useState(false)
  const [saving, setSaving] = useState(false)
  const editorRef = useRef(null)

  const [formData, setFormData] = useState({ 
    name: "", 
    category: "Leads", 
    subject: "", 
    htmlContent: "" 
  })

  // Fetch templates from backend
  useEffect(() => {
    const fetchTemplates = async () => {
      const sessionId = localStorage.getItem("session_id")
      if (!sessionId) {
        navigate("/login")
        return
      }

      try {
        const res = await fetch(`${API_BASE_URL}/templates/`, {
          headers: {
            "Content-Type": "application/json",
            "Authorization": sessionId,
          },
        })

        if (res.status === 401) {
          alert("Session expired. Please login again.")
          localStorage.removeItem("session_id")
          navigate("/login")
          return
        }

        if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`)
        const data = await res.json()
        setTemplates(data.templates || [])
        if (data.templates && data.templates.length > 0) {
          setSelectedTemplate(data.templates[0])
        }
      } catch (err) {
        console.error("Failed to fetch templates:", err.message)
      }
    }

    fetchTemplates()
  }, [navigate])

  const handleDeleteTemplate = async (id) => {
    if (!window.confirm("Are you sure you want to delete this template?")) return

    const sessionId = localStorage.getItem("session_id")
    if (!sessionId) {
      navigate("/login")
      return
    }

    try {
      const res = await fetch(`${API_BASE_URL}/templates/${id}`, {
        method: "DELETE",
        headers: {
          "Content-Type": "application/json",
          "Authorization": sessionId,
        },
      })

      if (res.status === 401) {
        alert("Session expired. Please login again.")
        localStorage.removeItem("session_id")
        navigate("/login")
        return
      }

      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || "Failed to delete template")

      alert("Template deleted successfully")
      setTemplates((prev) => prev.filter((t) => t._id !== id))
      if (selectedTemplate?._id === id) {
        setSelectedTemplate(templates.find(t => t._id !== id) || null)
      }
    } catch (err) {
      alert("Error deleting template: " + err.message)
    }
  }

  const handleFormSubmit = async (e) => {
    if (e) e.preventDefault()
    setSaving(true)

    const sessionId = localStorage.getItem("session_id")
    if (!sessionId) {
      navigate("/login")
      return
    }

    try {
      const isEditing = selectedTemplate && showEditor && selectedTemplate._id
      const url = isEditing
        ? `${API_BASE_URL}/templates/${selectedTemplate._id}`
        : `${API_BASE_URL}/templates/`
      const method = isEditing ? "PUT" : "POST"

      const res = await fetch(url, {
        method,
        headers: {
          "Content-Type": "application/json",
          "Authorization": sessionId,
        },
        body: JSON.stringify(formData),
      })

      if (res.status === 401) {
        alert("Session expired. Please login again.")
        localStorage.removeItem("session_id")
        navigate("/login")
        return
      }

      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || "Failed to save template")

      alert(isEditing ? "Template updated!" : "Template created!")
      setShowEditor(false)

      // Refresh list after save
      const newRes = await fetch(`${API_BASE_URL}/templates/`, {
        headers: {
          "Content-Type": "application/json",
          "Authorization": sessionId,
        },
      })
      const newData = await newRes.json()
      setTemplates(newData.templates || [])
      
      if (data.template) {
        setSelectedTemplate(data.template)
      }
    } catch (err) {
      alert("Error: " + err.message)
    } finally {
      setSaving(false)
    }
  }

  const handleEditTemplate = (template) => {
    setFormData({
      name: template.name || "",
      category: template.category || "Leads",
      subject: template.subject || "",
      htmlContent: template.htmlContent || "",
    })
    setSelectedTemplate(template)
    setShowEditor(true)
  }

  const handleCreateNew = () => {
    setFormData({ name: "", category: "Leads", subject: "", htmlContent: "" })
    setSelectedTemplate(null)
    setShowEditor(true)
  }

  const handleUseTemplate = (template) => {
    navigate("/admin/sales/campaign/list", { state: { selectedTemplate: template } })
  }

  // Rich text editor commands
  const execCommand = (command, value = null) => {
    document.execCommand(command, false, value)
    editorRef.current?.focus()
  }

  const insertLink = () => {
    const url = prompt("Enter URL:")
    if (url) {
      execCommand("createLink", url)
    }
  }

  const insertImage = () => {
    const url = prompt("Enter image URL:")
    if (url) {
      execCommand("insertImage", url)
    }
  }

  // Template Editor View
  if (showEditor) {
    return (
      <div className="template-editor-page">
        <div className="editor-header">
          <div className="editor-title">
            <span className="template-name-display">{formData.name || "Untitled Template"}</span>
            <span className="template-category-badge">{formData.category || "Leads"}</span>
          </div>
          <div className="editor-actions">
            <button className="btn btn-attachment">Attachments</button>
            <button className="btn btn-cancel" onClick={() => setShowEditor(false)}>Cancel</button>
            <button className="btn btn-preview-btn" onClick={() => setViewMode(viewMode === "desktop" ? "mobile" : "desktop")}>Preview</button>
            <button className="btn btn-save" onClick={handleFormSubmit} disabled={saving}>
              {saving ? "Saving..." : "Save"}
            </button>
          </div>
        </div>

        <div className="editor-form-bar">
          <input
            type="text"
            className="editor-input template-name-input"
            placeholder="Template Name"
            value={formData.name}
            onChange={(e) => setFormData({ ...formData, name: e.target.value })}
          />
          <input
            type="text"
            className="editor-input subject-input"
            placeholder="Subject Line"
            value={formData.subject}
            onChange={(e) => setFormData({ ...formData, subject: e.target.value })}
          />
        </div>

        <div className="editor-toolbar">
          <select 
            className="toolbar-select font-family"
            onChange={(e) => execCommand("fontName", e.target.value)}
          >
            <option value="Arial">Arial</option>
            <option value="Times New Roman">Times New Roman</option>
            <option value="Georgia">Georgia</option>
            <option value="Verdana">Verdana</option>
            <option value="Courier New">Courier New</option>
          </select>
          <select 
            className="toolbar-select font-size"
            onChange={(e) => execCommand("fontSize", e.target.value)}
            defaultValue="3"
          >
            <option value="1">8</option>
            <option value="2">10</option>
            <option value="3">12</option>
            <option value="4">14</option>
            <option value="5">18</option>
            <option value="6">24</option>
            <option value="7">36</option>
          </select>
          <span className="toolbar-divider"></span>
          <button type="button" className="toolbar-btn" onClick={() => execCommand("bold")} title="Bold"><b>B</b></button>
          <button type="button" className="toolbar-btn" onClick={() => execCommand("italic")} title="Italic"><i>I</i></button>
          <button type="button" className="toolbar-btn" onClick={() => execCommand("underline")} title="Underline"><u>U</u></button>
          <button type="button" className="toolbar-btn" onClick={() => execCommand("strikeThrough")} title="Strikethrough"><s>S</s></button>
          <button type="button" className="toolbar-btn" onClick={() => execCommand("superscript")} title="Superscript">X<sup>2</sup></button>
          <button type="button" className="toolbar-btn" onClick={() => execCommand("subscript")} title="Subscript">X<sub>2</sub></button>
          <span className="toolbar-divider"></span>
          <input 
            type="color" 
            className="toolbar-color" 
            title="Text Color"
            onChange={(e) => execCommand("foreColor", e.target.value)}
          />
          <input 
            type="color" 
            className="toolbar-color" 
            title="Highlight Color"
            defaultValue="#ffff00"
            onChange={(e) => execCommand("hiliteColor", e.target.value)}
          />
          <span className="toolbar-divider"></span>
          <button type="button" className="toolbar-btn" onClick={() => execCommand("justifyLeft")} title="Align Left">⬐</button>
          <button type="button" className="toolbar-btn" onClick={() => execCommand("justifyCenter")} title="Align Center">☰</button>
          <button type="button" className="toolbar-btn" onClick={() => execCommand("justifyRight")} title="Align Right">⬑</button>
          <button type="button" className="toolbar-btn" onClick={() => execCommand("justifyFull")} title="Justify">≡</button>
          <span className="toolbar-divider"></span>
          <button type="button" className="toolbar-btn" onClick={() => execCommand("insertOrderedList")} title="Numbered List">1.</button>
          <button type="button" className="toolbar-btn" onClick={() => execCommand("insertUnorderedList")} title="Bullet List">•</button>
          <button type="button" className="toolbar-btn" onClick={() => execCommand("indent")} title="Increase Indent">⇥</button>
          <button type="button" className="toolbar-btn" onClick={() => execCommand("outdent")} title="Decrease Indent">⇤</button>
          <span className="toolbar-divider"></span>
          <button type="button" className="toolbar-btn" onClick={insertLink} title="Insert Link">🔗</button>
          <button type="button" className="toolbar-btn" onClick={() => execCommand("unlink")} title="Remove Link">✂</button>
          <button type="button" className="toolbar-btn" onClick={insertImage} title="Insert Image">🖼</button>
          <button type="button" className="toolbar-btn" onClick={() => execCommand("insertHorizontalRule")} title="Horizontal Line">―</button>
          <button type="button" className="toolbar-btn" onClick={() => execCommand("formatBlock", "pre")} title="Code Block">&lt;/&gt;</button>
          <button type="button" className="toolbar-btn" onClick={() => execCommand("formatBlock", "blockquote")} title="Quote">"</button>
        </div>

        <div className="editor-hint">
          <span>HINT: To insert a merge field, type <strong>#</strong> and choose one from the list.</span>
          <button type="button" className="hint-link">More</button>
        </div>

        <div className="editor-content-area">
          <div 
            ref={editorRef}
            className="rich-text-editor"
            contentEditable
            dangerouslySetInnerHTML={{ __html: formData.htmlContent }}
            onInput={(e) => setFormData({ ...formData, htmlContent: e.currentTarget.innerHTML })}
          />
        </div>

        <div className="editor-footer">
          <span className="footer-hint">• Plain text</span>
          <span className="footer-hint">| Show Hints</span>
        </div>
      </div>
    )
  }

  // Main Templates List View (Zoho Style - Split View)
  return (
    <div className="templates-zoho-container">
      {/* Header */}
      <div className="templates-zoho-header">
        <div className="header-left">
          <h1 className="page-title">Templates</h1>
          <span className="template-type-badge">✉ Public Email Templates</span>
        </div>
        <div className="header-right">
          <button className="btn btn-close" onClick={() => navigate(-1)}>×</button>
        </div>
      </div>

      <div className="templates-zoho-content">
        {/* Left Panel - Template List */}
        <div className="templates-list-panel">
          <div className="list-header">
            <div className="list-controls">
              <input type="checkbox" className="select-all-checkbox" />
              <span className="column-header">Template Name</span>
            </div>
            <button className="btn btn-create" onClick={handleCreateNew}>
              + Create Template
            </button>
          </div>

          <div className="templates-list">
            {templates.length === 0 ? (
              <div className="empty-list">
                <p>No templates found</p>
                <button className="btn btn-primary" onClick={handleCreateNew}>Create your first template</button>
              </div>
            ) : (
              templates.map((template) => (
                <div 
                  key={template._id} 
                  className={`template-list-item ${selectedTemplate?._id === template._id ? 'selected' : ''}`}
                  onClick={() => setSelectedTemplate(template)}
                >
                  <div className="template-star">☆</div>
                  <div className="template-info">
                    <div className="template-name-row">
                      <span className="template-name">{template.name}</span>
                    </div>
                    <div className="template-meta-row">
                      <span className="template-category-tag">{template.category || "Leads"}</span>
                      <span className="template-separator">·</span>
                      <span className="template-subject">{template.subject || template.name}</span>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Right Panel - Preview */}
        <div className="templates-preview-panel">
          {selectedTemplate ? (
            <>
              <div className="preview-header">
                <h2 className="preview-title">{selectedTemplate.name}</h2>
                <span className="preview-subtitle">{selectedTemplate.subject || selectedTemplate.name}</span>
              </div>

              <div className="preview-tabs">
                <button 
                  className={`preview-tab ${viewMode === 'desktop' ? 'active' : ''}`}
                  onClick={() => setViewMode('desktop')}
                >
                  🖥 Desktop
                </button>
                <button 
                  className={`preview-tab ${viewMode === 'mobile' ? 'active' : ''}`}
                  onClick={() => setViewMode('mobile')}
                >
                  📱 Mobile
                </button>
                <div className="tab-spacer"></div>
                <button className="preview-tab active">Preview</button>
                <button className="preview-tab">Analytics</button>
              </div>

              <div className="preview-actions">
                <button 
                  className="preview-action-btn edit" 
                  onClick={() => handleEditTemplate(selectedTemplate)}
                  title="Edit Template"
                >
                  ✏️
                </button>
                <button 
                  className="preview-action-btn copy" 
                  onClick={() => navigator.clipboard.writeText(selectedTemplate.htmlContent || '')}
                  title="Copy Template"
                >
                  📋
                </button>
              </div>

              <div className={`preview-content ${viewMode}`}>
                <div className="preview-iframe-container">
                  <iframe
                    srcDoc={selectedTemplate.htmlContent || '<p>No content</p>'}
                    title="Template Preview"
                    className="preview-iframe"
                    sandbox="allow-same-origin"
                  />
                </div>
              </div>

              <div className="preview-footer-actions">
                <button 
                  className="btn btn-use-template"
                  onClick={() => handleUseTemplate(selectedTemplate)}
                >
                  Use Template
                </button>
                <button 
                  className="btn btn-edit-template"
                  onClick={() => handleEditTemplate(selectedTemplate)}
                >
                  Edit Template
                </button>
                <button 
                  className="btn btn-delete-template"
                  onClick={() => handleDeleteTemplate(selectedTemplate._id)}
                >
                  Delete
                </button>
              </div>
            </>
          ) : (
            <div className="no-template-selected">
              <p>Select a template to preview</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default Templates
