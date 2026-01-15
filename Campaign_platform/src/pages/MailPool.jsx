"use client"

import { useState, useEffect, useCallback } from "react"
import { useNavigate } from "react-router-dom"
import { API_BASE_URL } from "../config"
import "./Settings.css"

// Segment colors for labels
const SEGMENT_COLORS = {
  promotional: { bg: "#fef3c7", text: "#92400e", icon: "📢" },
  outreach: { bg: "#dbeafe", text: "#1e40af", icon: "📤" },
  discovery: { bg: "#d1fae5", text: "#065f46", icon: "🔍" },
  presentation: { bg: "#e0e7ff", text: "#3730a3", icon: "📊" },
  rfq_pricing: { bg: "#fce7f3", text: "#9d174d", icon: "💰" },
  negotiation: { bg: "#fed7aa", text: "#9a3412", icon: "🤝" },
  invoice: { bg: "#ccfbf1", text: "#0f766e", icon: "📄" },
  banking: { bg: "#f3e8ff", text: "#6b21a8", icon: "🏦" },
  internal: { bg: "#e0f2fe", text: "#0369a1", icon: "🏠" },
  others: { bg: "#f3f4f6", text: "#374151", icon: "📧" },
}

// AI Category colors (Tier 1)
const AI_CATEGORY_COLORS = {
  client: { bg: "#dcfce7", text: "#166534", icon: "👤" },
  vendor: { bg: "#dbeafe", text: "#1e40af", icon: "🏢" },
  internal: { bg: "#e0f2fe", text: "#0369a1", icon: "🏠" },
  promotional: { bg: "#fef3c7", text: "#92400e", icon: "📢" },
  invoice: { bg: "#ccfbf1", text: "#0f766e", icon: "📄" },
  banking: { bg: "#f3e8ff", text: "#6b21a8", icon: "🏦" },
  automated: { bg: "#e5e7eb", text: "#6b7280", icon: "🤖" },
  spam: { bg: "#fee2e2", text: "#dc2626", icon: "🚫" },
  others: { bg: "#f3f4f6", text: "#374151", icon: "📧" },
}

// AI Urgency colors
const URGENCY_COLORS = {
  critical: { bg: "#fee2e2", text: "#dc2626" },
  high: { bg: "#fed7aa", text: "#c2410c" },
  medium: { bg: "#fef3c7", text: "#92400e" },
  low: { bg: "#e5e7eb", text: "#6b7280" },
  none: { bg: "transparent", text: "#9ca3af" },
}

// Gmail-like folder structure
const FOLDERS = [
  { id: "inbox", name: "Inbox", icon: "📥", direction: "inbox", count: 0 },
  { id: "sent", name: "Sent", icon: "📤", direction: "outbox" },
  { id: "drafts", name: "Drafts", icon: "📝", filter: "drafts" },
  { id: "all", name: "All Mail", icon: "📧", direction: "" },
]

// Helper to strip HTML tags
const stripHtml = (html) => {
  if (!html) return ""
  const doc = new DOMParser().parseFromString(html, 'text/html')
  return doc.body.textContent || ""
}

// Check if content is HTML
const isHtmlContent = (content) => {
  if (!content) return false
  // Check for common HTML tags
  return /<(html|head|body|div|p|span|table|tr|td|br|img|a|ul|ol|li|h[1-6]|strong|em|b|i)[^>]*>/i.test(content)
}

// Format plain text email body to HTML
const formatEmailBody = (body) => {
  if (!body) return ""
  
  // Check if it's already HTML
  if (isHtmlContent(body)) {
    // It's HTML, sanitize scripts/styles and improve styling
    let cleaned = body
      .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '')
      .replace(/<style\b[^<]*(?:(?!<\/style>)<[^<]*)*<\/style>/gi, '')
    
    // Add some base styles for better readability
    return `<div style="font-family: Arial, sans-serif; line-height: 1.6;">${cleaned}</div>`
  }
  
  // It's plain text - need to format properly
  // First, detect if this is an email thread with embedded headers
  const isEmailThread = /From:.*Sent:.*To:.*Subject:/s.test(body) || 
                        /From:.*Date:.*To:.*Subject:/s.test(body) ||
                        /-{3,}Original Message-{3,}/i.test(body)
  
  if (isEmailThread) {
    // Parse email thread and format each message separately
    return formatEmailThread(body)
  }
  
  // Simple plain text formatting
  let lines = body.split(/\r?\n/)
  let formatted = []
  let inQuote = false
  let quoteBuffer = []
  
  const flushQuote = () => {
    if (quoteBuffer.length > 0) {
      formatted.push(`<div style="border-left: 3px solid #dadce0; padding-left: 12px; margin: 12px 0; color: #5f6368; font-size: 0.9em;">${quoteBuffer.join('<br>')}</div>`)
      quoteBuffer = []
    }
    inQuote = false
  }
  
  for (let line of lines) {
    // Check for quoted lines (starting with >)
    const quoteMatch = line.match(/^(>+)\s*(.*)/)
    
    if (quoteMatch) {
      if (!inQuote) {
        inQuote = true
      }
      quoteBuffer.push(quoteMatch[2])
    } else {
      if (inQuote) {
        flushQuote()
      }
      
      // Process regular line
      let processedLine = line
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*([^*]+)\*/g, '<strong>$1</strong>')
        .replace(/^(From:|To:|Cc:|Sent:|Subject:|Date:)\s*/i, '<span style="color: #5f6368; font-size: 0.85em; font-weight: 600;">$1</span> ')
        .replace(/(https?:\/\/[^\s<>]+)/g, '<a href="$1" target="_blank" rel="noopener noreferrer" style="color: #1a73e8;">$1</a>')
        .replace(/([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})/g, '<a href="mailto:$1" style="color: #1a73e8;">$1</a>')
      
      if (processedLine.match(/^(Director|Manager|CEO|MD|Managing Director|President|Regards|Best|Thanks|Sincerely)/i)) {
        processedLine = `<span style="color: #5f6368;">${processedLine}</span>`
      }
      
      if (processedLine.trim() === '') {
        formatted.push('<br>')
      } else {
        formatted.push(`<div style="margin: 4px 0;">${processedLine}</div>`)
      }
    }
  }
  
  if (inQuote) {
    flushQuote()
  }
  
  return `<div style="font-family: Arial, sans-serif; line-height: 1.6;">${formatted.join('')}</div>`
}

// Format email thread with multiple messages
const formatEmailThread = (body) => {
  // Split by common email separators
  const separators = [
    /-{3,}\s*Original Message\s*-{3,}/gi,
    /_{3,}\s*From:/gi,
    /On\s+\w+,\s+\w+\s+\d+,\s+\d+.*wrote:/gi,
    /From:.*Sent:.*To:.*Subject:/gs
  ]
  
  let html = []
  let remaining = body
  let messageIndex = 0
  
  // Find From: ... Subject: blocks and format them as separate messages
  const messagePattern = /(From:\s*[^\n]+(?:\n(?!From:)[^\n]*)*)/gi
  const messages = body.split(/(?=From:\s*[^\n]+.*?(?:Sent|Date):\s*[^\n]+.*?(?:To):\s*[^\n]+.*?Subject:\s*)/si)
  
  if (messages.length > 1) {
    for (let msg of messages) {
      if (msg.trim()) {
        const isQuoted = messageIndex > 0
        const bgColor = isQuoted ? '#f8f9fa' : 'white'
        const borderColor = isQuoted ? '#e8eaed' : '#dadce0'
        
        // Extract header info
        const headerMatch = msg.match(/From:\s*([^\n]+)/i)
        const dateMatch = msg.match(/(?:Sent|Date):\s*([^\n]+)/i)
        const subjectMatch = msg.match(/Subject:\s*([^\n]+)/i)
        
        let formattedMsg = msg
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;')
          .replace(/\n/g, '<br>')
          .replace(/^(From:|To:|Cc:|Sent:|Subject:|Date:)\s*/gim, '<span style="color: #5f6368; font-size: 0.85em; font-weight: 600;">$1</span> ')
          .replace(/(https?:\/\/[^\s<>]+)/g, '<a href="$1" target="_blank" style="color: #1a73e8;">$1</a>')
          .replace(/([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})/g, '<a href="mailto:$1" style="color: #1a73e8;">$1</a>')
        
        html.push(`
          <div style="margin: ${messageIndex > 0 ? '16px 0' : '0'}; padding: 16px; background: ${bgColor}; border: 1px solid ${borderColor}; border-radius: 8px;">
            <div style="font-family: Arial, sans-serif; font-size: 14px; line-height: 1.6; color: ${isQuoted ? '#5f6368' : '#202124'};">
              ${formattedMsg}
            </div>
          </div>
        `)
        messageIndex++
      }
    }
    return html.join('')
  }
  
  // Fallback: simple formatting
  return body
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\n/g, '<br>')
    .replace(/(https?:\/\/[^\s<>]+)/g, '<a href="$1" target="_blank" style="color: #1a73e8;">$1</a>')
    .replace(/([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})/g, '<a href="mailto:$1" style="color: #1a73e8;">$1</a>')
}

// Get initials from name/email
const getInitials = (name, email) => {
  if (name) {
    const parts = name.split(' ')
    if (parts.length >= 2) {
      return (parts[0].charAt(0) + parts[parts.length - 1].charAt(0)).toUpperCase()
    }
    return name.charAt(0).toUpperCase()
  }
  return email ? email.charAt(0).toUpperCase() : "?"
}

// Get avatar color based on name
const getAvatarColor = (name) => {
  const colors = [
    "#1a73e8", "#ea4335", "#34a853", "#fbbc04", "#673ab7",
    "#e91e63", "#00bcd4", "#ff5722", "#795548", "#607d8b"
  ]
  const hash = (name || "").split("").reduce((a, b) => a + b.charCodeAt(0), 0)
  return colors[hash % colors.length]
}

function MailPool() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  
  // Stats & Accounts
  const [stats, setStats] = useState({
    total_emails: 0,
    emails_today: 0,
    segments: {},
    accounts: []
  })
  
  // Emails list
  const [emails, setEmails] = useState([])
  const [pagination, setPagination] = useState({ page: 1, limit: 50, total: 0, total_pages: 0 })
  
  // Filters
  const [filterSegment, setFilterSegment] = useState("")
  const [filterSearch, setFilterSearch] = useState("")
  const [searchInput, setSearchInput] = useState("")
  const [filterDirection, setFilterDirection] = useState("inbox") // Default to inbox
  const [filterAccount, setFilterAccount] = useState("")
  const [filterFolder, setFilterFolder] = useState("inbox")
  
  // Email viewing
  const [selectedEmail, setSelectedEmail] = useState(null)
  const [emailThread, setEmailThread] = useState([])
  const [viewMode, setViewMode] = useState("list") // list, email, compose
  
  // Contact popup
  const [showContactPopup, setShowContactPopup] = useState(false)
  const [contactInfo, setContactInfo] = useState(null)
  
  // Compose
  const [showCompose, setShowCompose] = useState(false)
  const [composeData, setComposeData] = useState({ to: "", subject: "", body: "", replyTo: null })
  const [selectedAlias, setSelectedAlias] = useState("")
  
  // Signatures & Aliases
  const [signatures, setSignatures] = useState({})
  const [aliases, setAliases] = useState([])

  // Fetch stats
  const fetchStats = useCallback(async () => {
    const sessionId = localStorage.getItem("session_id")
    if (!sessionId) {
      navigate("/admin/login")
      return
    }

    try {
      const res = await fetch(`${API_BASE_URL}/gmail/mail-pool/stats`, {
        headers: { Authorization: sessionId },
      })

      if (res.status === 401) {
        navigate("/admin/login")
        return
      }

      const data = await res.json()
      if (data.success) {
        setStats(data.stats)
        // Set aliases from accounts - now aliases are objects with their own signatures
        if (data.stats.accounts) {
          const allAliases = []
          const sigMap = {}
          data.stats.accounts.forEach(acc => {
            // Add primary account
            allAliases.push({ 
              email: acc.email, 
              name: acc.display_name, 
              isPrimary: true,
              signature: acc.signature || ""
            })
            // Store signature for primary account
            sigMap[acc.email] = acc.signature || ""
            
            // Add aliases - they now come as objects with their own signatures
            if (acc.aliases && Array.isArray(acc.aliases)) {
              acc.aliases.forEach(alias => {
                // Handle both old format (string) and new format (object)
                const aliasEmail = typeof alias === 'string' ? alias : alias.email
                const aliasName = typeof alias === 'string' ? acc.display_name : (alias.display_name || acc.display_name)
                const aliasSignature = typeof alias === 'string' ? acc.signature : (alias.signature || acc.signature || "")
                
                allAliases.push({ 
                  email: aliasEmail, 
                  name: aliasName, 
                  isPrimary: false,
                  signature: aliasSignature
                })
                // Store signature for this alias
                sigMap[aliasEmail] = aliasSignature
              })
            }
          })
          setSignatures(sigMap)
          setAliases(allAliases)
          if (allAliases.length > 0) {
            setSelectedAlias(allAliases[0].email)
          }
        }
      }
    } catch (e) {
      console.error("Error fetching stats:", e)
    }
  }, [navigate])

  // Fetch emails
  const fetchEmails = useCallback(async (page = 1) => {
    const sessionId = localStorage.getItem("session_id")
    if (!sessionId) return

    try {
      let url = `${API_BASE_URL}/gmail/mail-pool/emails?page=${page}&limit=${pagination.limit}`
      if (filterSegment) url += `&segment=${filterSegment}`
      if (filterSearch) url += `&search=${encodeURIComponent(filterSearch)}`
      if (filterDirection) url += `&direction=${filterDirection}`
      if (filterAccount) url += `&account=${encodeURIComponent(filterAccount)}`
      if (filterFolder === "drafts") url += `&is_draft=true`
      if (filterFolder === "starred") url += `&is_starred=true`

      const res = await fetch(url, {
        headers: { Authorization: sessionId },
      })

      const data = await res.json()
      if (data.success) {
        setEmails(data.emails)
        setPagination(data.pagination)
      }
    } catch (e) {
      console.error("Error fetching emails:", e)
    }
  }, [filterSegment, filterSearch, filterDirection, filterAccount, filterFolder, pagination.limit])

  // Fetch email thread/detail
  const fetchEmailThread = async (emailId) => {
    const sessionId = localStorage.getItem("session_id")
    try {
      // First get the email to find its thread_id
      const res = await fetch(`${API_BASE_URL}/gmail/mail-pool/emails/${emailId}`, {
        headers: { Authorization: sessionId },
      })
      const data = await res.json()
      if (data.success) {
        setSelectedEmail(data.email)
        
        // If email has a thread_id, fetch all emails in the thread
        if (data.email.thread_id) {
          try {
            const threadRes = await fetch(`${API_BASE_URL}/gmail/mail-pool/thread/${data.email.thread_id}`, {
              headers: { Authorization: sessionId },
            })
            const threadData = await threadRes.json()
            if (threadData.success && threadData.emails?.length > 0) {
              setEmailThread(threadData.emails)
            } else {
              setEmailThread([data.email])
            }
          } catch (threadErr) {
            console.error("Error fetching thread:", threadErr)
            setEmailThread([data.email])
          }
        } else {
          setEmailThread([data.email])
        }
        setViewMode("email")
      }
    } catch (e) {
      console.error("Error fetching email:", e)
    }
  }

  // Fetch contact info
  const fetchContactInfo = async (email, name, company) => {
    const sessionId = localStorage.getItem("session_id")
    try {
      const res = await fetch(`${API_BASE_URL}/gmail/mail-pool/contact?email=${encodeURIComponent(email)}`, {
        headers: { Authorization: sessionId },
      })
      const data = await res.json()
      if (data.success) {
        setContactInfo(data.contact)
        setShowContactPopup(true)
      } else {
        // Fallback to basic info
        setContactInfo({ email, name: name || "", company: company || "" })
        setShowContactPopup(true)
      }
    } catch (e) {
      // Fallback
      setContactInfo({ email, name: name || "", company: company || "" })
      setShowContactPopup(true)
    }
  }

  // Handle folder selection
  const handleFolderSelect = (folder) => {
    setFilterFolder(folder.id)
    if (folder.direction !== undefined) {
      setFilterDirection(folder.direction)
    } else {
      setFilterDirection("")
    }
    setFilterSegment("")
    setViewMode("list")
  }

  // Handle label/segment selection
  const handleLabelSelect = (segment) => {
    setFilterSegment(segment)
    setFilterDirection("")
    setFilterFolder("")
    setViewMode("list")
  }

  // Open compose
  const openCompose = (replyTo = null) => {
    if (replyTo) {
      setComposeData({
        to: replyTo.email,
        subject: `Re: ${stripHtml(replyTo.subject) || ""}`,
        body: "",
        replyTo
      })
    } else {
      setComposeData({ to: "", subject: "", body: "", replyTo: null })
    }
    if (filterAccount) {
      setSelectedAlias(filterAccount)
    } else if (aliases.length > 0) {
      setSelectedAlias(aliases[0].email)
    }
    setShowCompose(true)
  }

  // Send email
  const [sending, setSending] = useState(false)
  const handleSendEmail = async () => {
    if (!composeData.to || !composeData.subject) {
      alert("Please fill in recipient and subject")
      return
    }

    const sessionId = localStorage.getItem("session_id")
    if (!sessionId) {
      navigate("/admin/login")
      return
    }

    setSending(true)
    try {
      const recipients = composeData.to.split(",").map(e => e.trim()).filter(e => e)
      
      // Get signature HTML for selected alias
      const signatureHtml = signatures[selectedAlias] || null
      
      // Use Gmail API endpoint (not IMAP/SMTP)
      const res = await fetch(`${API_BASE_URL}/gmail-ws/send`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: sessionId,
        },
        body: JSON.stringify({
          to: recipients,
          subject: composeData.subject,
          body: composeData.body,
          html_body: composeData.body.replace(/\n/g, "<br>"),
          from_email: selectedAlias || null,
          cc: [],
          bcc: [],
          signature_html: signatureHtml,
          reply_to_message_id: composeData.replyTo?.message_id || null,
          thread_id: composeData.replyTo?.thread_id || null
        }),
      })

      const data = await res.json()
      
      if (data.success) {
        alert("Email sent successfully!")
        setShowCompose(false)
        setComposeData({ to: "", subject: "", body: "", replyTo: null })
        // Refresh emails to show sent email
        fetchEmails(1)
      } else {
        alert(`Failed to send: ${data.detail || data.error || "Unknown error"}`)
      }
    } catch (e) {
      console.error("Error sending email:", e)
      alert(`Error sending email: ${e.message}`)
    } finally {
      setSending(false)
    }
  }

  // Re-categorization state and handler
  const [recategorizing, setRecategorizing] = useState(false)
  const [recategorizeStatus, setRecategorizeStatus] = useState(null)
  
  const handleRecategorizeAll = async (useAi = true) => {
    const sessionId = localStorage.getItem("session_id")
    if (!sessionId) {
      navigate("/admin/login")
      return
    }

    if (!confirm(`This will re-categorize all emails using ${useAi ? 'AI' : 'keyword-based'} classification. Continue?`)) {
      return
    }

    setRecategorizing(true)
    try {
      const res = await fetch(`${API_BASE_URL}/email-sync/recategorize-all`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: sessionId,
        },
        body: JSON.stringify({
          use_ai: useAi,
          mailbox_id: filterAccount || null,
          category: null,
          limit: null
        }),
      })

      const data = await res.json()
      
      if (data.success) {
        setRecategorizeStatus({
          task_id: data.task_id,
          total: data.total_emails,
          status: "running",
          processed: 0
        })
        alert(`Started re-categorization of ${data.total_emails} emails. Check status in the console or refresh page.`)
        // Start polling for status
        pollRecategorizeStatus(data.task_id)
      } else {
        alert(`Failed to start re-categorization: ${data.message || "Unknown error"}`)
      }
    } catch (e) {
      console.error("Error starting re-categorization:", e)
      alert(`Error: ${e.message}`)
    } finally {
      setRecategorizing(false)
    }
  }

  const pollRecategorizeStatus = async (taskId) => {
    const sessionId = localStorage.getItem("session_id")
    try {
      const res = await fetch(`${API_BASE_URL}/email-sync/recategorize-status/${taskId}`, {
        headers: { Authorization: sessionId },
      })
      const data = await res.json()
      setRecategorizeStatus(data)
      
      if (data.status === "running" || data.status === "pending") {
        // Continue polling
        setTimeout(() => pollRecategorizeStatus(taskId), 3000)
      } else if (data.status === "completed") {
        alert(`Re-categorization completed! Processed ${data.processed} emails.`)
        fetchEmails(1)
      }
    } catch (e) {
      console.error("Error polling status:", e)
    }
  }

  // AI Classification state
  const [classifying, setClassifying] = useState(false)
  const [classifyStatus, setClassifyStatus] = useState(null)

  // Start AI classification (Tiered)
  const handleAIClassify = async (runTier2 = true) => {
    const sessionId = localStorage.getItem("session_id")
    if (!sessionId) {
      navigate("/admin/login")
      return
    }

    if (!confirm(`Start AI classification?\n\n• Tier 1: Fast classification of all emails\n• Tier 2: Deep analysis of client/vendor emails${runTier2 ? ' (enabled)' : ' (disabled)'}\n\nContinue?`)) {
      return
    }

    setClassifying(true)
    try {
      const res = await fetch(`${API_BASE_URL}/gmail/mail-pool/classify`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: sessionId,
        },
        body: JSON.stringify({
          limit: 500,
          run_tier2: runTier2,
          category_filter: null
        }),
      })

      const data = await res.json()
      
      if (data.success) {
        if (data.total === 0) {
          alert("All emails are already classified!")
          setClassifying(false)
          return
        }
        setClassifyStatus({
          task_id: data.task_id,
          total: data.total_emails,
          status: "running",
          processed: 0
        })
        alert(`Started AI classification of ${data.total_emails} emails.`)
        pollClassifyStatus(data.task_id)
      } else {
        alert(`Failed: ${data.message || "Unknown error"}`)
        setClassifying(false)
      }
    } catch (e) {
      console.error("Error starting classification:", e)
      alert(`Error: ${e.message}`)
      setClassifying(false)
    }
  }

  const pollClassifyStatus = async (taskId) => {
    const sessionId = localStorage.getItem("session_id")
    try {
      const res = await fetch(`${API_BASE_URL}/gmail/mail-pool/classify/status/${taskId}`, {
        headers: { Authorization: sessionId },
      })
      const data = await res.json()
      setClassifyStatus(data)
      
      if (data.status === "running" || data.status === "pending") {
        setTimeout(() => pollClassifyStatus(taskId), 3000)
      } else if (data.status === "completed") {
        alert(`AI classification completed!\n\n• Processed: ${data.processed}\n• Tier 1 only: ${data.tier1_only || 0}\n• Tier 2 analyzed: ${data.tier2_analyzed || 0}\n• Errors: ${data.errors || 0}`)
        setClassifying(false)
        fetchEmails(1)
      } else if (data.status === "failed") {
        alert(`Classification failed: ${data.error || "Unknown error"}`)
        setClassifying(false)
      }
    } catch (e) {
      console.error("Error polling status:", e)
    }
  }

  // Get AI category badge
  const getAICategoryBadge = (category) => {
    if (!category) return null
    const config = AI_CATEGORY_COLORS[category] || AI_CATEGORY_COLORS.others
    return (
      <span style={{
        backgroundColor: config.bg,
        color: config.text,
        padding: "2px 6px",
        borderRadius: "4px",
        fontSize: "0.65rem",
        fontWeight: "600",
        marginRight: "4px",
        textTransform: "uppercase"
      }}>
        {config.icon} {category}
      </span>
    )
  }

  // Get urgency badge
  const getUrgencyBadge = (urgency) => {
    if (!urgency || urgency === "none") return null
    const config = URGENCY_COLORS[urgency] || URGENCY_COLORS.medium
    return (
      <span style={{
        backgroundColor: config.bg,
        color: config.text,
        padding: "2px 6px",
        borderRadius: "4px",
        fontSize: "0.65rem",
        fontWeight: "600"
      }}>
        {urgency === "critical" ? "🔴" : urgency === "high" ? "🟠" : ""} {urgency.toUpperCase()}
      </span>
    )
  }

  // Download attachment
  const handleDownloadAttachment = (attachment) => {
    if (!attachment.data) {
      alert("Attachment data not available. This may be a large file or from an older sync.")
      return
    }
    
    try {
      // Decode base64 and create blob
      const byteCharacters = atob(attachment.data)
      const byteNumbers = new Array(byteCharacters.length)
      for (let i = 0; i < byteCharacters.length; i++) {
        byteNumbers[i] = byteCharacters.charCodeAt(i)
      }
      const byteArray = new Uint8Array(byteNumbers)
      const blob = new Blob([byteArray], { type: attachment.mime_type || 'application/octet-stream' })
      
      // Create download link
      const url = window.URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = attachment.filename || 'attachment'
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      window.URL.revokeObjectURL(url)
    } catch (e) {
      console.error("Error downloading attachment:", e)
      alert("Failed to download attachment: " + e.message)
    }
  }

  // Per-mailbox recategorize
  const handleRecategorizeMailbox = async (mailboxId, useAi = true) => {
    const sessionId = localStorage.getItem("session_id")
    if (!sessionId) {
      navigate("/admin/login")
      return
    }

    if (!confirm(`Re-categorize all emails for this mailbox using ${useAi ? 'AI' : 'keywords'}?`)) {
      return
    }

    try {
      const res = await fetch(`${API_BASE_URL}/email-sync/recategorize-all`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: sessionId,
        },
        body: JSON.stringify({
          use_ai: useAi,
          mailbox_id: mailboxId,
          category: null,
          limit: null
        }),
      })

      const data = await res.json()
      
      if (data.success) {
        alert(`Started re-categorization of ${data.total_emails} emails for this mailbox.`)
        pollRecategorizeStatus(data.task_id)
      } else {
        alert(`Failed: ${data.message || "Unknown error"}`)
      }
    } catch (e) {
      console.error("Error:", e)
      alert(`Error: ${e.message}`)
    }
  }

  // Initial load
  useEffect(() => {
    const loadData = async () => {
      setLoading(true)
      await Promise.all([fetchStats(), fetchEmails()])
      setLoading(false)
    }
    loadData()
  }, [fetchStats, fetchEmails])

  // Reload emails when filters change
  useEffect(() => {
    fetchEmails(1)
  }, [filterSegment, filterSearch, filterDirection, filterAccount, filterFolder, fetchEmails])

  // Format date like Gmail
  const formatDate = (dateStr) => {
    if (!dateStr) return ""
    try {
      const date = new Date(dateStr)
      const now = new Date()
      const isToday = date.toDateString() === now.toDateString()
      const isThisYear = date.getFullYear() === now.getFullYear()
      
      if (isToday) {
        return date.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", hour12: true })
      } else if (isThisYear) {
        return date.toLocaleDateString("en-US", { month: "short", day: "numeric" })
      } else {
        return date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "2-digit" })
      }
    } catch {
      return dateStr
    }
  }

  // Format full date
  const formatFullDate = (dateStr) => {
    if (!dateStr) return ""
    try {
      const date = new Date(dateStr)
      return date.toLocaleDateString("en-US", { 
        weekday: "short", 
        month: "short", 
        day: "numeric", 
        year: "numeric",
        hour: "numeric",
        minute: "2-digit",
        hour12: true
      })
    } catch {
      return dateStr
    }
  }

  // Get segment badge
  const getSegmentBadge = (segment) => {
    const config = SEGMENT_COLORS[segment] || SEGMENT_COLORS.others
    return (
      <span style={{
        backgroundColor: config.bg,
        color: config.text,
        padding: "2px 8px",
        borderRadius: "4px",
        fontSize: "0.7rem",
        fontWeight: "500",
        marginRight: "4px"
      }}>
        {segment?.replace("_", " ") || "other"}
      </span>
    )
  }

  if (loading) {
    return (
      <div style={styles.loadingContainer}>
        <div style={{ fontSize: "2rem", marginBottom: "1rem" }}>📧</div>
        Loading emails...
      </div>
    )
  }

  return (
    <div style={styles.gmailLayout}>
      {/* Sidebar */}
      <div style={styles.sidebar}>
        {/* Compose Button */}
        <button style={styles.composeBtn} onClick={() => openCompose()}>
          <span style={{ fontSize: "1.2rem" }}>✏️</span>
          <span>Compose</span>
        </button>

        {/* Folders */}
        <div style={styles.sidebarSection}>
          {FOLDERS.map(folder => (
            <div
              key={folder.id}
              style={{
                ...styles.sidebarItem,
                backgroundColor: filterFolder === folder.id ? "#d3e3fd" : "transparent",
                fontWeight: filterFolder === folder.id ? "600" : "400"
              }}
              onClick={() => handleFolderSelect(folder)}
            >
              <span style={styles.sidebarIcon}>{folder.icon}</span>
              <span style={styles.sidebarLabel}>{folder.name}</span>
              {folder.id === "inbox" && stats.inbox_count > 0 && (
                <span style={styles.sidebarBadge}>{stats.inbox_count?.toLocaleString()}</span>
              )}
            </div>
          ))}
        </div>

        {/* Labels */}
        <div style={styles.sidebarDivider}>
          <span style={styles.sidebarTitle}>Labels</span>
        </div>
        <div style={styles.sidebarSection}>
          {Object.entries(SEGMENT_COLORS).slice(0, 8).map(([segment, config]) => {
            const count = stats.segments?.[segment] || 0;
            return (
              <div
                key={segment}
                style={{
                  ...styles.sidebarItem,
                  backgroundColor: filterSegment === segment ? config.bg : "transparent"
                }}
                onClick={() => handleLabelSelect(segment)}
              >
                <span style={{
                  width: "12px",
                  height: "12px",
                  borderRadius: "2px",
                  backgroundColor: config.text,
                  marginRight: "12px"
                }}></span>
                <span style={styles.sidebarLabel}>
                  {segment.replace("_", " ").charAt(0).toUpperCase() + segment.replace("_", " ").slice(1)}
                </span>
                {count > 0 && (
                  <span style={{ marginLeft: "auto", fontSize: "0.75rem", color: "#6b7280" }}>{count}</span>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Main Content */}
      <div style={styles.mainContent}>
        {/* Header with Account Dropdown */}
        <div style={styles.header}>
          <h1 style={styles.headerTitle}>📬 Mail Pool</h1>
          <div style={styles.headerRight}>
            <select
              value={filterAccount}
              onChange={(e) => setFilterAccount(e.target.value)}
              style={styles.accountDropdown}
            >
              <option value="">All Accounts</option>
              {stats.accounts?.map(acc => (
                <option key={acc.email} value={acc.email}>
                  {acc.email}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Search Bar */}
        <div style={styles.searchBar}>
          <span style={styles.searchIcon}>🔍</span>
          <input
            type="text"
            placeholder="Search mail"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && setFilterSearch(searchInput)}
            style={styles.searchInput}
          />
          {filterSearch && (
            <button 
              onClick={() => { setFilterSearch(""); setSearchInput(""); }}
              style={styles.searchClear}
            >✕</button>
          )}
        </div>

        {/* Email List View */}
        {viewMode === "list" && (
          <div style={styles.emailListContainer}>
            {/* Toolbar */}
            <div style={styles.toolbar}>
              <div style={styles.toolbarLeft}>
                <input type="checkbox" style={styles.checkbox} />
                <button style={styles.toolbarBtn} title="Refresh" onClick={() => fetchEmails(pagination.page)}>🔄</button>
                <button 
                  style={{...styles.toolbarBtn, backgroundColor: "#e8f0fe", color: "#1a73e8", fontWeight: "500", padding: "4px 12px", borderRadius: "16px"}}
                  title="AI Classify Emails" 
                  onClick={() => handleAIClassify(true)}
                  disabled={classifying}
                >
                  {classifying ? "⏳ Classifying..." : "✨ AI Classify"}
                </button>
                {classifyStatus && classifyStatus.status === "running" && (
                  <span style={{fontSize: "0.75rem", color: "#6b7280", marginLeft: "8px"}}>
                    Processing {classifyStatus.processed}/{classifyStatus.total}...
                  </span>
                )}
              </div>
              <div style={styles.toolbarRight}>
                <span style={styles.paginationText}>
                  {pagination.total > 0 ? `${((pagination.page - 1) * pagination.limit) + 1}-${Math.min(pagination.page * pagination.limit, pagination.total).toLocaleString()} of ${pagination.total.toLocaleString()}` : "0"}
                </span>
                <button 
                  style={styles.toolbarBtn} 
                  onClick={() => fetchEmails(pagination.page - 1)}
                  disabled={pagination.page <= 1}
                >◀</button>
                <button 
                  style={styles.toolbarBtn}
                  onClick={() => fetchEmails(pagination.page + 1)}
                  disabled={pagination.page >= pagination.total_pages}
                >▶</button>
              </div>
            </div>

            {/* Email Rows */}
            <div style={styles.emailList}>
              {emails.length > 0 ? emails.map((email) => (
                <div 
                  key={email.id}
                  style={{
                    ...styles.emailRow,
                    backgroundColor: email.is_read === false ? "#f2f6fc" : "transparent",
                    fontWeight: email.is_read === false ? "600" : "400"
                  }}
                  onClick={() => fetchEmailThread(email.id)}
                >
                  {/* Checkbox & Star */}
                  <div style={styles.emailRowLeft} onClick={(e) => e.stopPropagation()}>
                    <input type="checkbox" style={styles.checkbox} />
                    <span style={styles.starIcon}>{email.is_starred ? "⭐" : "☆"}</span>
                  </div>
                  
                  {/* Sender Avatar */}
                  <div 
                    style={{
                      ...styles.avatar,
                      backgroundColor: getAvatarColor(email.name || email.email)
                    }}
                    onClick={(e) => {
                      e.stopPropagation()
                      fetchContactInfo(email.email, email.name, email.company)
                    }}
                    title="View contact info"
                  >
                    {getInitials(email.name, email.email)}
                  </div>

                  {/* Sender Name */}
                  <div style={{
                    ...styles.emailSender,
                    fontWeight: email.is_read === false ? "700" : "600"
                  }}>
                    {email.is_read === false && <span style={{color: "#1a73e8", marginRight: "4px"}}>●</span>}
                    {email.name || email.email?.split("@")[0] || "Unknown"}
                    {email.thread_count > 1 && (
                      <span style={styles.threadCount}>{email.thread_count}</span>
                    )}
                  </div>

                  {/* Subject & Snippet */}
                  <div style={styles.emailSubjectLine}>
                    {/* AI Category Badge (Tier 1) */}
                    {email.ai_category && getAICategoryBadge(email.ai_category)}
                    {/* Urgency badge if high/critical */}
                    {(email.ai_urgency === "critical" || email.ai_urgency === "high") && getUrgencyBadge(email.ai_urgency)}
                    {/* Legacy segment badge */}
                    {!email.ai_category && email.segment && email.segment !== "others" && getSegmentBadge(email.segment)}
                    {email.has_rfq && (
                      <span style={styles.rfqTag}>RFQ</span>
                    )}
                    
                    <span style={styles.emailSubject} title={stripHtml(email.subject) || "(no subject)"}>
                      {(stripHtml(email.subject) || "(no subject)").length > 50 
                        ? (stripHtml(email.subject) || "(no subject)").substring(0, 50) + "..." 
                        : (stripHtml(email.subject) || "(no subject)")}
                    </span>
                    <span style={styles.emailSnippetSeparator}> - </span>
                    <span style={styles.emailSnippet}>
                      {stripHtml(email.snippet)?.substring(0, 100) || ""}
                    </span>
                  </div>

                  {/* Attachments indicator */}
                  {email.has_attachments && (
                    <span style={styles.attachmentIcon} title="Has attachments">📎</span>
                  )}

                  {/* Date */}
                  <div style={styles.emailDate}>
                    {formatDate(email.added_on || email.date)}
                  </div>
                </div>
              )) : (
                <div style={styles.emptyState}>
                  <div style={{ fontSize: "3rem", marginBottom: "1rem" }}>📭</div>
                  <p>No emails found</p>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Email Detail View - Gmail Style */}
        {viewMode === "email" && selectedEmail && (
          <div style={styles.emailDetailContainer}>
            {/* Detail Header */}
            <div style={styles.detailHeader}>
              <button style={styles.backBtn} onClick={() => setViewMode("list")}>
                ← Back to {filterFolder || "inbox"}
              </button>
              <div style={styles.detailActions}>
                <button style={styles.toolbarBtn} title="Archive">📥</button>
                <button style={styles.toolbarBtn} title="Report spam">⚠️</button>
                <button style={styles.toolbarBtn} title="Delete">🗑️</button>
                <button style={styles.toolbarBtn} title="Mark unread">✉️</button>
                <button style={styles.toolbarBtn} title="More">⋮</button>
              </div>
            </div>

            {/* Subject Line */}
            <div style={styles.detailSubject}>
              <h2 style={styles.subjectText}>{stripHtml(selectedEmail.subject) || "(no subject)"}</h2>
              <div style={styles.subjectLabels}>
                {/* AI Category Badge */}
                {selectedEmail.ai_category && getAICategoryBadge(selectedEmail.ai_category)}
                {/* Urgency Badge */}
                {selectedEmail.ai_urgency && selectedEmail.ai_urgency !== "none" && getUrgencyBadge(selectedEmail.ai_urgency)}
                {/* Legacy segment */}
                {!selectedEmail.ai_category && selectedEmail.segment && getSegmentBadge(selectedEmail.segment)}
                <span style={styles.inboxLabel}>{filterFolder === "sent" ? "Sent" : "Inbox"} ×</span>
              </div>
            </div>

            {/* AI Insights Section (Tier 2) */}
            {(selectedEmail.ai_intent || selectedEmail.ai_action_items?.length > 0) && (
              <div style={{
                margin: "12px 0",
                padding: "16px",
                backgroundColor: "#f0f7ff",
                borderRadius: "12px",
                border: "1px solid #d0e5ff"
              }}>
                <div style={{ display: "flex", alignItems: "center", marginBottom: "12px" }}>
                  <span style={{ fontSize: "1.2rem", marginRight: "8px" }}>🤖</span>
                  <span style={{ fontWeight: "600", color: "#1a73e8" }}>AI Analysis</span>
                  {selectedEmail.ai_confidence && (
                    <span style={{ marginLeft: "auto", fontSize: "0.75rem", color: "#6b7280" }}>
                      {Math.round(selectedEmail.ai_confidence * 100)}% confident
                    </span>
                  )}
                </div>
                
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "12px" }}>
                  {/* Intent */}
                  {selectedEmail.ai_intent && (
                    <div style={{ padding: "8px 12px", backgroundColor: "white", borderRadius: "8px" }}>
                      <div style={{ fontSize: "0.7rem", color: "#6b7280", marginBottom: "4px" }}>INTENT</div>
                      <div style={{ fontWeight: "500", color: "#374151", textTransform: "capitalize" }}>
                        {selectedEmail.ai_intent.replace(/_/g, " ")}
                      </div>
                    </div>
                  )}
                  
                  {/* Sentiment */}
                  {selectedEmail.ai_sentiment && (
                    <div style={{ padding: "8px 12px", backgroundColor: "white", borderRadius: "8px" }}>
                      <div style={{ fontSize: "0.7rem", color: "#6b7280", marginBottom: "4px" }}>SENTIMENT</div>
                      <div style={{ fontWeight: "500", color: selectedEmail.ai_sentiment === "positive" ? "#059669" : selectedEmail.ai_sentiment === "negative" ? "#dc2626" : "#6b7280", textTransform: "capitalize" }}>
                        {selectedEmail.ai_sentiment === "positive" ? "😊" : selectedEmail.ai_sentiment === "negative" ? "😟" : "😐"} {selectedEmail.ai_sentiment}
                      </div>
                    </div>
                  )}
                  
                  {/* Reply Expected */}
                  {selectedEmail.ai_reply_expected !== undefined && (
                    <div style={{ padding: "8px 12px", backgroundColor: "white", borderRadius: "8px" }}>
                      <div style={{ fontSize: "0.7rem", color: "#6b7280", marginBottom: "4px" }}>REPLY EXPECTED</div>
                      <div style={{ fontWeight: "500", color: selectedEmail.ai_reply_expected ? "#dc2626" : "#059669" }}>
                        {selectedEmail.ai_reply_expected ? "✅ Yes" : "❌ No"}
                      </div>
                    </div>
                  )}
                </div>
                
                {/* Key Points */}
                {selectedEmail.ai_key_points && selectedEmail.ai_key_points.length > 0 && (
                  <div style={{ marginTop: "12px", padding: "8px 12px", backgroundColor: "white", borderRadius: "8px" }}>
                    <div style={{ fontSize: "0.7rem", color: "#6b7280", marginBottom: "6px" }}>KEY POINTS</div>
                    <ul style={{ margin: "0", paddingLeft: "20px", color: "#374151", fontSize: "0.9rem" }}>
                      {selectedEmail.ai_key_points.map((point, i) => (
                        <li key={i} style={{ marginBottom: "4px" }}>{point}</li>
                      ))}
                    </ul>
                  </div>
                )}
                
                {/* Action Items */}
                {selectedEmail.ai_action_items && selectedEmail.ai_action_items.length > 0 && (
                  <div style={{ marginTop: "12px", padding: "8px 12px", backgroundColor: "#fef3c7", borderRadius: "8px", border: "1px solid #fcd34d" }}>
                    <div style={{ fontSize: "0.7rem", color: "#92400e", marginBottom: "6px" }}>⚡ ACTION ITEMS</div>
                    <ul style={{ margin: "0", paddingLeft: "20px", color: "#78350f", fontSize: "0.9rem", fontWeight: "500" }}>
                      {selectedEmail.ai_action_items.map((action, i) => (
                        <li key={i} style={{ marginBottom: "4px" }}>{action}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}

            {/* AI Summary Section */}
            {selectedEmail.ai_summary && (
              <div style={styles.aiSummaryContainer}>
                <div style={styles.aiSummaryHeader}>
                  <span style={styles.aiSummaryIcon}>✨</span>
                  <span style={styles.aiSummaryTitle}>AI Summary</span>
                </div>
                <div style={styles.aiSummaryContent}>
                  {selectedEmail.ai_summary}
                </div>
              </div>
            )}

            {/* Email Thread */}
            <div style={styles.threadContainer}>
              {emailThread.map((email, idx) => (
                <div key={email.id || idx} style={styles.threadMessage}>
                  {/* Message Header */}
                  <div style={styles.messageHeader}>
                    <div 
                      style={{
                        ...styles.avatarLarge,
                        backgroundColor: getAvatarColor(email.name || email.email)
                      }}
                      onClick={() => fetchContactInfo(email.email, email.name, email.company)}
                    >
                      {getInitials(email.name, email.email)}
                    </div>
                    <div style={styles.messageMeta}>
                      <div style={styles.messageSender}>
                        <strong>{email.name || email.email?.split("@")[0]}</strong>
                        {email.company && <span style={styles.senderCompany}> | {stripHtml(email.company)}</span>}
                      </div>
                      <div style={styles.messageRecipients}>
                        to {stripHtml(email.to_email?.split('<')[0]) || filterAccount || "me"}
                        <span style={styles.expandRecipients}>▼</span>
                      </div>
                    </div>
                    <div style={styles.messageDate}>
                      {formatFullDate(email.added_on || email.date)}
                      <span style={{...styles.starIcon, marginLeft: "8px"}}>{email.is_starred ? "⭐" : "☆"}</span>
                      <button style={styles.replyBtn} onClick={() => openCompose(email)}>↩️</button>
                      <button style={styles.toolbarBtn}>⋮</button>
                    </div>
                  </div>

                  {/* Message Body */}
                  <div style={{...styles.messageBody, maxHeight: "none", overflow: "visible"}}>
                    {email.body_html ? (
                      <div dangerouslySetInnerHTML={{ 
                        __html: `<div style="font-family: Arial, sans-serif; line-height: 1.6;">${email.body_html}</div>`
                      }} />
                    ) : email.body ? (
                      <div dangerouslySetInnerHTML={{ 
                        __html: formatEmailBody(email.body)
                      }} />
                    ) : email.snippet ? (
                      <div dangerouslySetInnerHTML={{ 
                        __html: formatEmailBody(email.snippet)
                      }} />
                    ) : (
                      <div style={{ color: "#999" }}>Email body not available</div>
                    )}
                  </div>

                  {/* Attachments */}
                  {email.attachments && email.attachments.length > 0 && (
                    <div style={styles.attachmentsSection}>
                      <div style={styles.attachmentsHeader}>
                        📎 {email.attachments.length} Attachment{email.attachments.length > 1 ? "s" : ""}
                      </div>
                      <div style={styles.attachmentsList}>
                        {email.attachments.map((att, i) => (
                          <div 
                            key={i} 
                            style={{...styles.attachmentItem, cursor: att.data ? 'pointer' : 'default'}}
                            onClick={() => handleDownloadAttachment(att)}
                            title={att.data ? "Click to download" : "Attachment not available for download"}
                          >
                            <span>📄</span>
                            <span style={styles.attachmentName}>{att.filename || att.name}</span>
                            <span style={styles.attachmentSize}>
                              {att.size ? `(${Math.round(att.size / 1024)}KB)` : ""}
                            </span>
                            {att.data && <span style={{marginLeft: '8px', color: '#1a73e8'}}>⬇️</span>}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>

            {/* Reply Section */}
            <div style={styles.replySection}>
              <div 
                style={{
                  ...styles.avatar,
                  backgroundColor: getAvatarColor("me")
                }}
              >
                M
              </div>
              <div style={styles.replyBox} onClick={() => openCompose(selectedEmail)}>
                Click here to Reply
              </div>
              <button style={styles.replyAllBtn} onClick={() => openCompose(selectedEmail)}>
                Reply all
              </button>
              <button style={styles.forwardBtn}>
                Forward
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Contact Popup */}
      {showContactPopup && contactInfo && (
        <div style={styles.popupOverlay} onClick={() => setShowContactPopup(false)}>
          <div style={styles.contactPopup} onClick={(e) => e.stopPropagation()}>
            <div style={styles.contactHeader}>
              <div style={{
                ...styles.contactAvatar,
                backgroundColor: getAvatarColor(contactInfo.name || contactInfo.email)
              }}>
                {getInitials(contactInfo.name, contactInfo.email)}
              </div>
              <button style={styles.popupClose} onClick={() => setShowContactPopup(false)}>✕</button>
            </div>
            <div style={styles.contactBody}>
              <h3 style={styles.contactName}>{contactInfo.name || contactInfo.email?.split("@")[0] || "Unknown"}</h3>
              <div style={styles.contactFields}>
                <div style={styles.contactField}>
                  <label>Email</label>
                  <span>{contactInfo.email}</span>
                </div>
                {contactInfo.first_name && (
                  <div style={styles.contactField}>
                    <label>First Name</label>
                    <span>{contactInfo.first_name}</span>
                  </div>
                )}
                {contactInfo.last_name && (
                  <div style={styles.contactField}>
                    <label>Last Name</label>
                    <span>{contactInfo.last_name}</span>
                  </div>
                )}
                {contactInfo.title && (
                  <div style={styles.contactField}>
                    <label>Title</label>
                    <span>{stripHtml(contactInfo.title)}</span>
                  </div>
                )}
                {contactInfo.linkedin && (
                  <div style={styles.contactField}>
                    <label>LinkedIn</label>
                    <a href={contactInfo.linkedin} target="_blank" rel="noreferrer" style={{ color: "#1a73e8" }}>{contactInfo.linkedin}</a>
                  </div>
                )}
                {contactInfo.location && (
                  <div style={styles.contactField}>
                    <label>Location</label>
                    <span>{contactInfo.location}</span>
                  </div>
                )}
                {contactInfo.company && (
                  <div style={styles.contactField}>
                    <label>Company</label>
                    <span>{stripHtml(contactInfo.company)}</span>
                  </div>
                )}
                {contactInfo.company_website && (
                  <div style={styles.contactField}>
                    <label>Company Website</label>
                    <a href={contactInfo.company_website} target="_blank" rel="noreferrer" style={{ color: "#1a73e8" }}>{contactInfo.company_website}</a>
                  </div>
                )}
                {contactInfo.added_on && (
                  <div style={styles.contactField}>
                    <label>Added On</label>
                    <span>{formatFullDate(contactInfo.added_on)}</span>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Compose Modal */}
      {showCompose && (
        <div style={styles.composeModal}>
          <div style={styles.composeHeader}>
            <span>{composeData.replyTo ? "Reply" : "New Message"}</span>
            <div>
              <button style={styles.composeMinimize}>—</button>
              <button style={styles.composeClose} onClick={() => setShowCompose(false)}>✕</button>
            </div>
          </div>
          <div style={styles.composeBody}>
            {/* From (Alias Selector) */}
            <div style={styles.composeField}>
              <label style={styles.composeLabel}>From:</label>
              <select 
                value={selectedAlias}
                onChange={(e) => setSelectedAlias(e.target.value)}
                style={styles.aliasSelect}
              >
                {aliases.map(alias => (
                  <option key={alias.email} value={alias.email}>
                    {alias.name ? `${alias.name} <${alias.email}>` : alias.email}
                    {alias.isPrimary ? " (Primary)" : " (Alias)"}
                  </option>
                ))}
              </select>
            </div>
            <div style={styles.composeField}>
              <label style={styles.composeLabel}>To:</label>
              <input 
                type="text" 
                value={composeData.to}
                onChange={(e) => setComposeData({...composeData, to: e.target.value})}
                style={styles.composeInput}
              />
            </div>
            <div style={styles.composeField}>
              <label style={styles.composeLabel}>Subject:</label>
              <input 
                type="text" 
                value={composeData.subject}
                onChange={(e) => setComposeData({...composeData, subject: e.target.value})}
                style={styles.composeInput}
              />
            </div>
            <textarea 
              style={styles.composeTextarea}
              value={composeData.body}
              onChange={(e) => setComposeData({...composeData, body: e.target.value})}
              placeholder="Write your message..."
            />
            {/* Signature Preview - shows when alias is selected */}
            {selectedAlias && (
              <div style={styles.signaturePreview}>
                {signatures[selectedAlias] ? (
                  <>
                    <div style={{ fontSize: "0.7rem", color: "#5f6368", marginBottom: "4px", borderTop: "1px solid #e5e7eb", paddingTop: "8px" }}>
                      Signature for {selectedAlias}:
                    </div>
                    <div dangerouslySetInnerHTML={{ __html: signatures[selectedAlias] }} />
                  </>
                ) : (
                  <div style={{ fontSize: "0.75rem", color: "#9ca3af", fontStyle: "italic", borderTop: "1px solid #e5e7eb", paddingTop: "8px" }}>
                    No signature configured for {selectedAlias}
                  </div>
                )}
              </div>
            )}
          </div>
          <div style={styles.composeFooter}>
            <button 
              style={{
                ...styles.sendBtn,
                opacity: sending ? 0.6 : 1,
                cursor: sending ? "not-allowed" : "pointer"
              }} 
              onClick={handleSendEmail}
              disabled={sending}
            >
              {sending ? "Sending..." : "Send"}
            </button>
            <button style={styles.composeToolBtn}>📎</button>
            <button style={styles.composeToolBtn}>🔗</button>
            <button style={styles.composeToolBtn}>😊</button>
            <button style={styles.composeToolBtn}>📷</button>
            <div style={{ flex: 1 }}></div>
            <button style={styles.composeToolBtn} onClick={() => setShowCompose(false)}>🗑️</button>
          </div>
        </div>
      )}
    </div>
  )
}

// Styles
const styles = {
  gmailLayout: {
    display: "flex",
    height: "calc(100vh - 60px)",
    backgroundColor: "#f6f8fc",
    overflow: "hidden"
  },
  loadingContainer: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    height: "100vh",
    backgroundColor: "#f6f8fc"
  },
  sidebar: {
    width: "256px",
    backgroundColor: "#f6f8fc",
    padding: "0.5rem",
    overflowY: "auto",
    flexShrink: 0
  },
  composeBtn: {
    display: "flex",
    alignItems: "center",
    gap: "0.75rem",
    padding: "0.875rem 1.5rem",
    margin: "0.5rem 0.5rem 1rem",
    backgroundColor: "#c2e7ff",
    border: "none",
    borderRadius: "16px",
    fontSize: "0.875rem",
    fontWeight: "500",
    cursor: "pointer",
    boxShadow: "0 1px 3px rgba(0,0,0,0.1)"
  },
  sidebarSection: {
    padding: "0.25rem 0"
  },
  sidebarItem: {
    display: "flex",
    alignItems: "center",
    padding: "0.5rem 1.25rem",
    borderRadius: "0 16px 16px 0",
    cursor: "pointer",
    fontSize: "0.875rem",
    color: "#202124",
    marginRight: "0.5rem",
    transition: "background-color 0.15s"
  },
  sidebarIcon: {
    marginRight: "12px",
    fontSize: "1.1rem"
  },
  sidebarLabel: {
    flex: 1
  },
  sidebarBadge: {
    backgroundColor: "#d93025",
    color: "white",
    fontSize: "0.75rem",
    padding: "2px 8px",
    borderRadius: "10px",
    fontWeight: "600"
  },
  sidebarDivider: {
    padding: "1rem 1.25rem 0.5rem",
    borderTop: "1px solid #e5e7eb",
    marginTop: "0.5rem"
  },
  sidebarTitle: {
    fontSize: "0.7rem",
    fontWeight: "600",
    color: "#5f6368",
    textTransform: "uppercase",
    letterSpacing: "0.5px"
  },
  mailboxItem: {
    padding: "0.5rem 1rem",
    borderBottom: "1px solid #f0f0f0"
  },
  mailboxHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: "0.5rem"
  },
  mailboxEmail: {
    fontSize: "0.8rem",
    fontWeight: "500",
    color: "#202124",
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
    maxWidth: "120px"
  },
  mailboxCount: {
    fontSize: "0.7rem",
    color: "#5f6368",
    backgroundColor: "#f1f3f4",
    padding: "2px 6px",
    borderRadius: "10px"
  },
  mailboxActions: {
    display: "flex",
    gap: "0.25rem"
  },
  mailboxActionBtn: {
    fontSize: "0.65rem",
    padding: "4px 8px",
    border: "1px solid #dadce0",
    borderRadius: "4px",
    backgroundColor: "#fff",
    cursor: "pointer",
    color: "#1a73e8",
    transition: "all 0.2s"
  },
  mainContent: {
    flex: 1,
    display: "flex",
    flexDirection: "column",
    backgroundColor: "white",
    borderRadius: "16px 0 0 0",
    margin: "0.5rem 0 0 0",
    overflow: "hidden"
  },
  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    padding: "0.75rem 1rem",
    borderBottom: "1px solid #e5e7eb"
  },
  headerTitle: {
    fontSize: "1.25rem",
    fontWeight: "400",
    color: "#202124",
    margin: 0
  },
  headerRight: {
    display: "flex",
    alignItems: "center",
    gap: "1rem"
  },
  accountDropdown: {
    padding: "0.5rem 1rem",
    border: "1px solid #dadce0",
    borderRadius: "4px",
    fontSize: "0.875rem",
    backgroundColor: "white",
    cursor: "pointer",
    minWidth: "200px"
  },
  searchBar: {
    display: "flex",
    alignItems: "center",
    margin: "0.5rem 1rem",
    padding: "0.5rem 1rem",
    backgroundColor: "#eaf1fb",
    borderRadius: "24px",
    border: "1px solid transparent"
  },
  searchIcon: {
    color: "#5f6368",
    marginRight: "0.5rem"
  },
  searchInput: {
    flex: 1,
    border: "none",
    backgroundColor: "transparent",
    fontSize: "1rem",
    outline: "none"
  },
  searchClear: {
    background: "none",
    border: "none",
    cursor: "pointer",
    color: "#5f6368",
    fontSize: "1rem"
  },
  emailListContainer: {
    flex: 1,
    display: "flex",
    flexDirection: "column",
    overflow: "hidden"
  },
  toolbar: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    padding: "0.5rem 1rem",
    borderBottom: "1px solid #e5e7eb"
  },
  toolbarLeft: {
    display: "flex",
    alignItems: "center",
    gap: "0.5rem"
  },
  toolbarRight: {
    display: "flex",
    alignItems: "center",
    gap: "0.5rem"
  },
  checkbox: {
    width: "18px",
    height: "18px",
    cursor: "pointer"
  },
  toolbarBtn: {
    background: "none",
    border: "none",
    padding: "0.5rem",
    cursor: "pointer",
    borderRadius: "50%",
    fontSize: "1rem"
  },
  paginationText: {
    fontSize: "0.8rem",
    color: "#5f6368"
  },
  emailList: {
    flex: 1,
    overflowY: "auto"
  },
  emailRow: {
    display: "flex",
    alignItems: "center",
    padding: "0.5rem 1rem",
    borderBottom: "1px solid #f1f3f4",
    cursor: "pointer",
    transition: "box-shadow 0.1s"
  },
  emailRowLeft: {
    display: "flex",
    alignItems: "center",
    gap: "0.5rem",
    marginRight: "0.5rem"
  },
  starIcon: {
    cursor: "pointer",
    fontSize: "1rem",
    color: "#5f6368"
  },
  avatar: {
    width: "32px",
    height: "32px",
    borderRadius: "50%",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    color: "white",
    fontSize: "0.8rem",
    fontWeight: "500",
    marginRight: "0.75rem",
    cursor: "pointer",
    flexShrink: 0
  },
  avatarLarge: {
    width: "40px",
    height: "40px",
    borderRadius: "50%",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    color: "white",
    fontSize: "1rem",
    fontWeight: "500",
    cursor: "pointer",
    flexShrink: 0
  },
  emailSender: {
    width: "180px",
    fontWeight: "600",
    fontSize: "0.875rem",
    color: "#202124",
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
    flexShrink: 0
  },
  threadCount: {
    fontSize: "0.75rem",
    color: "#5f6368",
    marginLeft: "4px"
  },
  emailSubjectLine: {
    flex: 1,
    display: "flex",
    alignItems: "center",
    overflow: "hidden",
    marginRight: "1rem"
  },
  emailSubject: {
    fontWeight: "400",
    color: "#202124",
    whiteSpace: "nowrap",
    overflow: "hidden",
    textOverflow: "ellipsis",
    maxWidth: "250px",
    flexShrink: 1
  },
  emailSnippetSeparator: {
    color: "#5f6368",
    margin: "0 4px"
  },
  emailSnippet: {
    color: "#5f6368",
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap"
  },
  rfqTag: {
    backgroundColor: "#e8f0fe",
    color: "#1a73e8",
    padding: "2px 6px",
    borderRadius: "4px",
    fontSize: "0.7rem",
    fontWeight: "500",
    marginRight: "4px"
  },
  attachmentIcon: {
    marginRight: "0.5rem",
    color: "#5f6368"
  },
  emailDate: {
    fontSize: "0.75rem",
    color: "#5f6368",
    whiteSpace: "nowrap",
    marginLeft: "auto"
  },
  emptyState: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    height: "100%",
    color: "#5f6368"
  },
  // Email Detail View
  emailDetailContainer: {
    flex: 1,
    display: "flex",
    flexDirection: "column",
    overflow: "hidden"
  },
  detailHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    padding: "0.5rem 1rem",
    borderBottom: "1px solid #e5e7eb"
  },
  backBtn: {
    background: "none",
    border: "none",
    cursor: "pointer",
    fontSize: "0.9rem",
    color: "#5f6368",
    padding: "0.5rem"
  },
  detailActions: {
    display: "flex",
    gap: "0.25rem"
  },
  detailSubject: {
    padding: "1rem 1rem 0.5rem",
    display: "flex",
    alignItems: "flex-start",
    gap: "1rem",
    flexWrap: "wrap"
  },
  subjectText: {
    fontSize: "1.375rem",
    fontWeight: "400",
    color: "#202124",
    margin: 0,
    flex: 1,
    minWidth: "200px"
  },
  subjectLabels: {
    display: "flex",
    gap: "0.5rem",
    flexWrap: "wrap"
  },
  inboxLabel: {
    backgroundColor: "#e8e8e8",
    color: "#5f6368",
    padding: "2px 8px",
    borderRadius: "4px",
    fontSize: "0.75rem"
  },
  aiSummaryContainer: {
    margin: "0 1rem 1rem",
    padding: "1rem",
    backgroundColor: "#f0f7ff",
    borderRadius: "8px",
    border: "1px solid #d0e3ff"
  },
  aiSummaryHeader: {
    display: "flex",
    alignItems: "center",
    gap: "0.5rem",
    marginBottom: "0.5rem"
  },
  aiSummaryIcon: {
    fontSize: "1rem"
  },
  aiSummaryTitle: {
    fontSize: "0.8rem",
    fontWeight: "600",
    color: "#1a73e8",
    textTransform: "uppercase",
    letterSpacing: "0.5px"
  },
  aiSummaryContent: {
    fontSize: "0.875rem",
    color: "#3c4043",
    lineHeight: "1.5"
  },
  threadContainer: {
    flex: 1,
    overflowY: "auto",
    padding: "0 1rem"
  },
  threadMessage: {
    marginBottom: "1rem",
    border: "1px solid #e5e7eb",
    borderRadius: "8px",
    overflow: "hidden"
  },
  messageHeader: {
    display: "flex",
    alignItems: "flex-start",
    padding: "1rem",
    gap: "0.75rem",
    backgroundColor: "#fafafa"
  },
  messageMeta: {
    flex: 1
  },
  messageSender: {
    fontSize: "0.875rem",
    color: "#202124"
  },
  senderCompany: {
    color: "#5f6368",
    fontWeight: "400"
  },
  messageRecipients: {
    fontSize: "0.75rem",
    color: "#5f6368"
  },
  expandRecipients: {
    cursor: "pointer",
    marginLeft: "4px"
  },
  messageDate: {
    display: "flex",
    alignItems: "center",
    gap: "0.5rem",
    fontSize: "0.75rem",
    color: "#5f6368",
    flexShrink: 0
  },
  replyBtn: {
    background: "none",
    border: "none",
    cursor: "pointer",
    fontSize: "1rem"
  },
  messageBody: {
    padding: "1rem 1rem 1rem 3.5rem",
    fontSize: "0.9rem",
    lineHeight: "1.6",
    color: "#202124",
    backgroundColor: "white",
    fontFamily: "Arial, sans-serif",
    wordBreak: "break-word",
    overflowWrap: "break-word"
  },
  attachmentsSection: {
    padding: "1rem",
    borderTop: "1px solid #e5e7eb",
    backgroundColor: "#f8f9fa"
  },
  attachmentsHeader: {
    fontSize: "0.875rem",
    color: "#202124",
    marginBottom: "0.5rem"
  },
  attachmentsList: {
    display: "flex",
    flexWrap: "wrap",
    gap: "0.5rem"
  },
  attachmentItem: {
    display: "flex",
    alignItems: "center",
    gap: "0.5rem",
    padding: "0.5rem 1rem",
    backgroundColor: "white",
    border: "1px solid #dadce0",
    borderRadius: "4px",
    cursor: "pointer"
  },
  attachmentName: {
    fontSize: "0.8rem"
  },
  attachmentSize: {
    fontSize: "0.7rem",
    color: "#5f6368"
  },
  replySection: {
    display: "flex",
    alignItems: "center",
    padding: "1rem",
    gap: "0.75rem",
    borderTop: "1px solid #e5e7eb",
    backgroundColor: "#fafafa"
  },
  replyBox: {
    flex: 1,
    padding: "0.75rem 1rem",
    border: "1px solid #dadce0",
    borderRadius: "24px",
    color: "#5f6368",
    cursor: "pointer",
    backgroundColor: "white"
  },
  replyAllBtn: {
    padding: "0.5rem 1rem",
    border: "1px solid #dadce0",
    borderRadius: "4px",
    backgroundColor: "white",
    cursor: "pointer",
    fontSize: "0.875rem"
  },
  forwardBtn: {
    padding: "0.5rem 1rem",
    border: "1px solid #dadce0",
    borderRadius: "4px",
    backgroundColor: "white",
    cursor: "pointer",
    fontSize: "0.875rem"
  },
  // Contact Popup
  popupOverlay: {
    position: "fixed",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: "rgba(0,0,0,0.5)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    zIndex: 1000
  },
  contactPopup: {
    backgroundColor: "white",
    borderRadius: "8px",
    width: "400px",
    maxHeight: "80vh",
    overflow: "auto",
    boxShadow: "0 4px 20px rgba(0,0,0,0.2)"
  },
  contactHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "flex-start",
    padding: "1.5rem",
    backgroundColor: "#f8f9fa"
  },
  contactAvatar: {
    width: "64px",
    height: "64px",
    borderRadius: "50%",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    color: "white",
    fontSize: "1.5rem",
    fontWeight: "500"
  },
  popupClose: {
    background: "none",
    border: "none",
    fontSize: "1.5rem",
    cursor: "pointer",
    color: "#5f6368"
  },
  contactBody: {
    padding: "1rem 1.5rem 1.5rem"
  },
  contactName: {
    margin: "0 0 1rem",
    fontSize: "1.25rem",
    color: "#202124"
  },
  contactFields: {
    display: "flex",
    flexDirection: "column",
    gap: "0.75rem"
  },
  contactField: {
    display: "flex",
    flexDirection: "column",
    gap: "0.25rem"
  },
  // Compose Modal
  composeModal: {
    position: "fixed",
    bottom: "0",
    right: "80px",
    width: "500px",
    backgroundColor: "white",
    borderRadius: "8px 8px 0 0",
    boxShadow: "0 -2px 20px rgba(0,0,0,0.2)",
    zIndex: 1001,
    display: "flex",
    flexDirection: "column",
    maxHeight: "600px"
  },
  composeHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    padding: "0.75rem 1rem",
    backgroundColor: "#404040",
    color: "white",
    borderRadius: "8px 8px 0 0"
  },
  composeMinimize: {
    background: "none",
    border: "none",
    color: "white",
    cursor: "pointer",
    fontSize: "1rem",
    marginRight: "0.5rem"
  },
  composeClose: {
    background: "none",
    border: "none",
    color: "white",
    cursor: "pointer",
    fontSize: "1rem"
  },
  composeBody: {
    padding: "0.5rem 1rem",
    flex: 1,
    overflowY: "auto"
  },
  composeField: {
    display: "flex",
    alignItems: "center",
    padding: "0.5rem 0",
    borderBottom: "1px solid #e5e7eb"
  },
  composeLabel: {
    color: "#5f6368",
    fontSize: "0.875rem",
    minWidth: "60px"
  },
  composeInput: {
    flex: 1,
    border: "none",
    outline: "none",
    fontSize: "0.875rem",
    marginLeft: "0.5rem",
    padding: "0.25rem"
  },
  aliasSelect: {
    flex: 1,
    border: "none",
    outline: "none",
    fontSize: "0.875rem",
    marginLeft: "0.5rem",
    backgroundColor: "transparent",
    cursor: "pointer"
  },
  composeTextarea: {
    width: "100%",
    minHeight: "200px",
    border: "none",
    outline: "none",
    resize: "none",
    fontSize: "0.875rem",
    padding: "0.5rem 0",
    fontFamily: "inherit"
  },
  signaturePreview: {
    borderTop: "1px solid #e5e7eb",
    paddingTop: "0.5rem",
    fontSize: "0.8rem",
    color: "#5f6368"
  },
  composeFooter: {
    display: "flex",
    alignItems: "center",
    padding: "0.75rem 1rem",
    gap: "0.5rem",
    borderTop: "1px solid #e5e7eb"
  },
  sendBtn: {
    backgroundColor: "#0b57d0",
    color: "white",
    border: "none",
    borderRadius: "4px",
    padding: "0.5rem 1.5rem",
    cursor: "pointer",
    fontWeight: "500",
    fontSize: "0.875rem"
  },
  composeToolBtn: {
    background: "none",
    border: "none",
    cursor: "pointer",
    fontSize: "1rem",
    color: "#5f6368",
    padding: "0.5rem"
  }
}

export default MailPool
