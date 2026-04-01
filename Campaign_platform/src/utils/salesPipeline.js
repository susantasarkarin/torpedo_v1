/**
 * Sales Pipeline Configuration
 * 11-Stage Sales Pipeline for managing leads and contacts
 */

export const SALES_STAGES = [
  { id: "lead_generation", label: "Lead Generation", icon: "🎯", color: { bg: "#f0fdf4", text: "#166534" } },
  { id: "outreach", label: "Outreach", icon: "📧", color: { bg: "#ecfeff", text: "#0e7490" } },
  { id: "discovery_call", label: "Discovery Call", icon: "📞", color: { bg: "#fef3c7", text: "#92400e" } },
  { id: "presentation", label: "Presentation", icon: "📊", color: { bg: "#dbeafe", text: "#1e40af" } },
  { id: "rfq_pricing", label: "RFQ & Pricing", icon: "💰", color: { bg: "#e0e7ff", text: "#3730a3" } },
  { id: "negotiation", label: "Negotiation", icon: "🤝", color: { bg: "#fce7f3", text: "#9d174d" } },
  { id: "won", label: "Won", icon: "✅", color: { bg: "#d1fae5", text: "#065f46" } },
  { id: "lost", label: "Lost", icon: "❌", color: { bg: "#fee2e2", text: "#dc2626" } },
  { id: "onboarding", label: "Onboarding", icon: "🚀", color: { bg: "#cffafe", text: "#0f766e" } },
  { id: "project_execution", label: "Project Execution", icon: "⚙️", color: { bg: "#fef9c3", text: "#854d0e" } },
  { id: "payment", label: "Payment", icon: "💳", color: { bg: "#dcfce7", text: "#15803d" } },
  { id: "retention", label: "Retention", icon: "♻️", color: { bg: "#f3e8ff", text: "#7c3aed" } },
]

// Get stage by ID
export const getStageById = (stageId) => {
  return SALES_STAGES.find(s => s.id === stageId) || SALES_STAGES[0]
}

// Get stage label from ID
export const getStageLabel = (stageId) => {
  const stage = getStageById(stageId)
  return stage ? stage.label : stageId
}

// Get stage style for badges
export const getStageStyle = (stageId) => {
  const stage = getStageById(stageId)
  if (!stage) return { bg: "#f3f4f6", color: "#374151" }
  return { bg: stage.color.bg, color: stage.color.text }
}

// Determine if a stage is in the "Leads" phase (early prospecting)
export const isLeadStage = (stageId) => {
  return ["lead_generation", "outreach"].includes(stageId)
}

// Determine if a stage is in the "Contacts" phase (active deals - discovery_call onwards)
export const isContactStage = (stageId) => {
  return ["discovery_call", "presentation", "rfq_pricing", "negotiation", "won", "lost", "onboarding", "project_execution", "payment", "retention"].includes(stageId)
}

// Determine if a stage is in the "Project" phase (won deals)
export const isProjectStage = (stageId) => {
  return ["onboarding", "project_execution", "payment", "retention"].includes(stageId)
}

// Get stages for leads page
export const getLeadStages = () => {
  return SALES_STAGES.filter(s => isLeadStage(s.id))
}

// Get stages for contacts page (show key stages for stats)
export const getContactStages = () => {
  // Show most important stages for contacts stats
  return SALES_STAGES.filter(s => ["discovery_call", "presentation", "negotiation", "won"].includes(s.id))
}

// Get stages for project management
export const getProjectStages = () => {
  return SALES_STAGES.filter(s => isProjectStage(s.id))
}

// Get the next stage in the pipeline
export const getNextStage = (currentStageId) => {
  const currentIndex = SALES_STAGES.findIndex(s => s.id === currentStageId)
  if (currentIndex === -1 || currentIndex >= SALES_STAGES.length - 1) return null
  return SALES_STAGES[currentIndex + 1]
}

// Get the previous stage in the pipeline
export const getPreviousStage = (currentStageId) => {
  const currentIndex = SALES_STAGES.findIndex(s => s.id === currentStageId)
  if (currentIndex <= 0) return null
  return SALES_STAGES[currentIndex - 1]
}

// All stages for dropdown selection
export const getStageOptions = () => {
  return SALES_STAGES.map(s => ({ value: s.id, label: s.label, icon: s.icon }))
}

export default SALES_STAGES
