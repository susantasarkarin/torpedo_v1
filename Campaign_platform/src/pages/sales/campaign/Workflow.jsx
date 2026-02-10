"use client"

import { useLocation, useNavigate } from "react-router-dom"
import { useState, useEffect } from "react"
import "./Workflow.css"
import { API_BASE_URL } from "../../../config"
import { buildApiUrl } from "../../../config"
import { Plus, X, Eye, Mail, Linkedin, Trash2, Copy } from "lucide-react"

function Workflow() {
  const location = useLocation()
  const navigate = useNavigate()

  const { selectedTemplate, list, contacts: initialContacts } = location.state || {}
  console.log("🔍 Workflow received:", { selectedTemplate, list, contactsCount: initialContacts?.length || 0, initialContacts })
  const [contacts, setContacts] = useState([])
  const [templates, setTemplates] = useState([])
  const [loading, setLoading] = useState(false)
  const [sending, setSending] = useState(false)

  // Workflow state
  const [workflowSteps, setWorkflowSteps] = useState([
    {
      id: "step1",
      type: "email",
      delay: 0,
      template: "",
      personalization: "Light",
      branches: []
    }
  ])
  const [selectedStep, setSelectedStep] = useState("step1")
  const [showPreview, setShowPreview] = useState(false)
  const [sampleData, setSampleData] = useState(null)

  // 🔹 Helper for authenticated fetch
  async function apiFetch(path, options = {}) {
    const sessionId = localStorage.getItem("session_id")
    if (!sessionId) {
      alert("Session expired. Please login again.")
      navigate("/login")
      throw new Error("No session")
    }

    const res = await fetch(buildApiUrl(`${path}`), {
      ...options,
      headers: {
        "Content-Type": "application/json",
        Authorization: sessionId,
        ...options.headers,
      },
    })

    if (res.status === 401) {
      alert("Session expired. Please login again.")
      localStorage.removeItem("session_id")
      navigate("/login")
      throw new Error("Session expired")
    }

    return res
  }

  // 🔹 Fetch templates and contacts
  useEffect(() => {
    // Fetch templates
    const fetchTemplates = async () => {
      try {
        const res = await apiFetch('/email-campaigns/templates')
        const data = await res.json()
        if (res.ok) {
          setTemplates(data.templates || [])
        }
      } catch (err) {
        console.error("❌ Fetch templates failed:", err)
      }
    }
    fetchTemplates()

    // If contacts passed directly from AI Leads, use them
    if (initialContacts && initialContacts.length > 0) {
      setContacts(initialContacts)
      setSampleData(initialContacts[0])
      return
    }

    // Otherwise fetch from list
    if (!list) return
    const fetchContacts = async () => {
      try {
        setLoading(true)

        let res = await apiFetch(`/contacts/${list._id}`)
        if (!res.ok) {
          res = await apiFetch(`/contacts/${encodeURIComponent(list.name)}`)
        }

        const data = await res.json()
        if (res.ok) {
          setContacts(data.contacts || [])
          if (data.contacts && data.contacts.length > 0) {
            setSampleData(data.contacts[0])
          }
        } else {
          alert("Error fetching contacts: " + data.detail)
        }
      } catch (err) {
        console.error("❌ Fetch contacts failed:", err)
        alert("Error fetching contacts: " + err.message)
      } finally {
        setLoading(false)
      }
    }
    fetchContacts()
  }, [list, initialContacts])

  // Workflow handlers
  const addStep = () => {
    const newId = `step${Date.now()}`
    setWorkflowSteps([
      ...workflowSteps,
      {
        id: newId,
        type: "email",
        delay: 2,
        template: "",
        personalization: "Light",
        branches: []
      }
    ])
    setSelectedStep(newId)
  }

  const addBranch = (stepId) => {
    const branchId = `branch${Date.now()}`
    setWorkflowSteps(
      workflowSteps.map(step =>
        step.id === stepId
          ? {
              ...step,
              branches: [
                ...step.branches,
                {
                  id: branchId,
                  condition: "if_opened",
                  action: "send_email",
                  template: ""
                }
              ]
            }
          : step
      )
    )
  }

  const updateStep = (stepId, updates) => {
    console.log("📝 Updating step:", { stepId, updates })
    setWorkflowSteps(
      workflowSteps.map(step =>
        step.id === stepId ? { ...step, ...updates } : step
      )
    )
  }

  const updateBranch = (stepId, branchId, updates) => {
    setWorkflowSteps(
      workflowSteps.map(step =>
        step.id === stepId
          ? {
              ...step,
              branches: step.branches.map(b =>
                b.id === branchId ? { ...b, ...updates } : b
              )
            }
          : step
      )
    )
  }

  const deleteStep = (stepId) => {
    if (workflowSteps.length === 1) {
      alert("Workflow must have at least one step")
      return
    }
    setWorkflowSteps(workflowSteps.filter(step => step.id !== stepId))
    if (selectedStep === stepId) {
      setSelectedStep(workflowSteps[0].id)
    }
  }

  const deleteBranch = (stepId, branchId) => {
    setWorkflowSteps(
      workflowSteps.map(step =>
        step.id === stepId
          ? {
              ...step,
              branches: step.branches.filter(b => b.id !== branchId)
            }
          : step
      )
    )
  }

  const duplicateStep = (stepId) => {
    const stepToDuplicate = workflowSteps.find(s => s.id === stepId)
    const newId = `step${Date.now()}`
    const newStep = {
      ...stepToDuplicate,
      id: newId,
      branches: stepToDuplicate.branches.map(b => ({
        ...b,
        id: `branch${Date.now()}-${Math.random()}`
      }))
    }
    setWorkflowSteps([...workflowSteps, newStep])
    setSelectedStep(newId)
  }

  // 🔹 Send workflow
  const handleSendWorkflow = async () => {
    console.log("🚀 SENDING WORKFLOW - Current State:", { 
      workflowSteps, 
      firstStepTemplate: workflowSteps[0]?.template,
      contactsCount: contacts.length 
    })
    
    // Check if any step has a template selected
    const hasTemplate = workflowSteps.some(step => step.template && step.template.trim() !== '')
    if (!hasTemplate) {
      alert("Please select a template for at least one step!")
      return
    }
    
    if (contacts.length === 0) {
      alert("No contacts loaded!")
      return
    }

    if (!window.confirm(`Send emails to ${contacts.length} contacts?`)) {
      return
    }

    try {
      setSending(true)
      
      // Get first email step with template
      const firstEmailStep = workflowSteps.find(step => step.type === 'email' && step.template)
      
      // Get lead IDs from contacts
      const leadIds = contacts.map(c => c._id)
      
      console.log("📤 Sending API request:", { 
        leadIds, 
        template_id: firstEmailStep.template,
        url: buildApiUrl('/email-campaigns/send-bulk')
      })
      
      const res = await apiFetch(`/email-campaigns/send-bulk`, {
        method: "POST",
        body: JSON.stringify({
          lead_ids: leadIds,
          template_id: firstEmailStep.template
        }),
      })

      console.log("📥 API Response status:", res.status)
      const data = await res.json()
      console.log("📥 API Response data:", data)
      
      if (res.ok) {
        alert(`✅ ${data.message}\\n\\n${data.sent_count} emails sent successfully!`)
        navigate("/admin/sales/campaign/ai-leads")
      } else {
        alert("❌ Send failed: " + data.detail)
      }
    } catch (err) {
      console.error("❌ Workflow send error:", err)
      alert("Error executing workflow: " + err.message)
    } finally {
      setSending(false)
    }
  }

  const currentStep = workflowSteps.find(s => s.id === selectedStep)

  const branchConditions = [
    { id: "if_opened", label: "If Opened", icon: "👁️" },
    { id: "if_clicked", label: "If Clicked", icon: "🖱️" },
    { id: "if_no_response", label: "If No Response", icon: "⏳" }
  ]

  const branchActions = [
    { id: "send_email", label: "Send Email", icon: "📧" },
    { id: "send_linkedin", label: "Send LinkedIn DM", icon: "💼" },
    { id: "remove", label: "Remove from Workflow", icon: "🚪" }
  ]

  return (
    <div className="workflow-container">
      {/* Header */}
      <div className="workflow-header-v2">
        <div>
          <h1>Workflow Builder</h1>
          <p>Create multi-step, multi-channel sequences with conditional branching</p>
        </div>
      </div>

      {/* Status Info */}
      <div className="workflow-info">
        <div className="info-card">
          <span className="label">Steps</span>
          <span className="value">{workflowSteps.length}</span>
        </div>
        <div className="info-card">
          <span className="label">Recipients</span>
          <span className="value">{contacts.length}</span>
        </div>
        <div className="info-card">
          <span className="label">Total Duration</span>
          <span className="value">{Math.max(...workflowSteps.map(s => s.delay), 0)} days</span>
        </div>
      </div>

      {/* Workflow Editor */}
      <div className="workflow-editor">
        <div className="workflow-canvas">
          {/* Step Cards */}
          <div className="steps-container">
            {workflowSteps.map((step, index) => (
              <div key={step.id} className="step-column">
                {/* Main Step Card */}
                <div
                  className={`step-card ${selectedStep === step.id ? "active" : ""}`}
                  onClick={() => setSelectedStep(step.id)}
                >
                  <div className="step-header">
                    <span className="step-number">Step {index + 1}</span>
                    <div className="step-actions">
                      <button
                        className="step-btn"
                        onClick={(e) => {
                          e.stopPropagation()
                          duplicateStep(step.id)
                        }}
                        title="Duplicate step"
                      >
                        <Copy size={14} />
                      </button>
                      {workflowSteps.length > 1 && (
                        <button
                          className="step-btn danger"
                          onClick={(e) => {
                            e.stopPropagation()
                            deleteStep(step.id)
                          }}
                          title="Delete step"
                        >
                          <Trash2 size={14} />
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Step Type and Delay */}
                  <div className="step-config">
                    <div className="config-row">
                      <label>Type</label>
                      <div className="channel-selector">
                        <button
                          className={`channel-btn ${step.type === "email" ? "active" : ""}`}
                          onClick={() => updateStep(step.id, { type: "email" })}
                        >
                          <Mail size={14} /> Email
                        </button>
                        <button
                          className={`channel-btn ${step.type === "linkedin" ? "active" : ""}`}
                          onClick={() => updateStep(step.id, { type: "linkedin" })}
                        >
                          <Linkedin size={14} /> LinkedIn
                        </button>
                      </div>
                    </div>

                    <div className="config-row">
                      <label>Delay (days)</label>
                      <input
                        type="number"
                        min="0"
                        max="365"
                        value={step.delay}
                        onChange={(e) => updateStep(step.id, { delay: parseInt(e.target.value) })}
                        className="delay-input"
                      />
                    </div>

                    <div className="config-row">
                      <label>Template</label>
                      <select
                        value={step.template}
                        onChange={(e) => updateStep(step.id, { template: e.target.value })}
                        className="template-select"
                      >
                        <option value="">Select template</option>
                        {templates.map(t => (
                          <option key={t._id} value={t._id}>
                            {t.name} - {t.category}
                          </option>
                        ))}
                      </select>
                    </div>

                    <div className="config-row">
                      <label>Personalization Level</label>
                      <select
                        value={step.personalization}
                        onChange={(e) => updateStep(step.id, { personalization: e.target.value })}
                        className="personalization-select"
                      >
                        <option value="Light">Light</option>
                        <option value="Role-Based">Role-Based</option>
                        <option value="Deep">Deep</option>
                      </select>
                    </div>
                  </div>

                  {/* Branches */}
                  <div className="branches-section">
                    <h4>Conditional Paths</h4>
                    {step.branches.length === 0 ? (
                      <p className="no-branches">No branching yet</p>
                    ) : (
                      <div className="branches-list">
                        {step.branches.map(branch => (
                          <div key={branch.id} className="branch-card">
                            <div className="branch-header">
                              <span className="condition-badge">
                                {branchConditions.find(c => c.id === branch.condition)?.label}
                              </span>
                              <button
                                className="delete-branch"
                                onClick={() => deleteBranch(step.id, branch.id)}
                              >
                                <X size={14} />
                              </button>
                            </div>
                            <select
                              value={branch.condition}
                              onChange={(e) => updateBranch(step.id, branch.id, { condition: e.target.value })}
                              className="branch-condition"
                            >
                              {branchConditions.map(cond => (
                                <option key={cond.id} value={cond.id}>
                                  {cond.label}
                                </option>
                              ))}
                            </select>
                            <select
                              value={branch.action}
                              onChange={(e) => updateBranch(step.id, branch.id, { action: e.target.value })}
                              className="branch-action"
                            >
                              {branchActions.map(action => (
                                <option key={action.id} value={action.id}>
                                  {action.label}
                                </option>
                              ))}
                            </select>
                            {(branch.action === "send_email" || branch.action === "send_linkedin") && (
                              <input
                                type="text"
                                placeholder="Template"
                                value={branch.template}
                                onChange={(e) => updateBranch(step.id, branch.id, { template: e.target.value })}
                                className="branch-template"
                              />
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                    <button
                      className="add-branch-btn"
                      onClick={() => addBranch(step.id)}
                    >
                      <Plus size={14} /> Add Condition
                    </button>
                  </div>
                </div>

                {/* Arrow to next step */}
                {index < workflowSteps.length - 1 && (
                  <div className="step-arrow">↓</div>
                )}
              </div>
            ))}

            {/* Add Step Button */}
            <button className="add-step-btn" onClick={addStep}>
              <Plus size={18} /> Add Step
            </button>
          </div>
        </div>

        {/* Right Panel - Preview & Send */}
        <div className="workflow-sidebar">
          {/* Preview Section */}
          <div className="preview-section">
            <button
              className="preview-toggle"
              onClick={() => setShowPreview(!showPreview)}
            >
              <Eye size={16} /> {showPreview ? "Hide" : "Show"} Preview
            </button>

            {showPreview && sampleData && (
              <div className="preview-content">
                <h3>Sample Preview</h3>
                <div className="sample-info">
                  <div className="sample-field">
                    <span className="label">Name:</span>
                    <span>{sampleData.name || "John Doe"}</span>
                  </div>
                  <div className="sample-field">
                    <span className="label">Email:</span>
                    <span>{sampleData.email || "john@example.com"}</span>
                  </div>
                  <div className="sample-field">
                    <span className="label">Company:</span>
                    <span>{sampleData.company || "Acme Corp"}</span>
                  </div>
                  <div className="sample-field">
                    <span className="label">Industry:</span>
                    <span>{sampleData.industry || "Technology"}</span>
                  </div>
                </div>

                {currentStep && (
                  <div className="step-preview">
                    <h4>Step Preview</h4>
                    <div className="preview-box">
                      <strong>Template:</strong> {currentStep.template || "[Select template]"}
                      <br />
                      <strong>Personalization:</strong> {currentStep.personalization}
                      <br />
                      <strong>Delay:</strong> {currentStep.delay} days
                      <br />
                      <strong>Channel:</strong> {currentStep.type === "email" ? "Email" : "LinkedIn"}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Send Section */}
          <div className="send-section">
            <h3>Ready to Launch?</h3>
            <div className="send-info">
              <p>Recipients: <strong>{contacts.length} leads</strong></p>
              <p>Steps: <strong>{workflowSteps.length}</strong></p>
              <p>Duration: <strong>{Math.max(...workflowSteps.map(s => s.delay), 0)} days</strong></p>
            </div>

            <button
              className="btn-send-workflow"
              onClick={handleSendWorkflow}
              disabled={sending || contacts.length === 0}
            >
              {sending ? (
                <>
                  <span className="spinner"></span> Launching...
                </>
              ) : (
                <>
                  <Mail size={18} /> Launch Workflow
                </>
              )}
            </button>

            <div className="workflow-tips">
              <h4>Tips</h4>
              <ul>
                <li>Use 2-3 days between steps</li>
                <li>Add branches for better engagement</li>
                <li>Test personalization levels</li>
                <li>Monitor open/click rates</li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default Workflow
