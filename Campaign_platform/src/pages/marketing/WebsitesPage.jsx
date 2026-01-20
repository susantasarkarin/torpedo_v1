"use client"

import { useState, useEffect } from "react"
import { Link } from "react-router-dom"
import { API_BASE_URL } from "../../config"
import { 
  Globe, 
  Plus, 
  FileText, 
  BookOpen, 
  Image as ImageIcon, 
  Settings, 
  ExternalLink,
  BarChart3,
  Loader2,
  Trash2
} from "lucide-react"
import "./Marketing.css"

function WebsitesPage() {
  const [websites, setWebsites] = useState([])
  const [loading, setLoading] = useState(true)
  const [showModal, setShowModal] = useState(false)
  const [formData, setFormData] = useState({
    name: "",
    domain: "",
    status: "draft"
  })
  const [submitting, setSubmitting] = useState(false)
  const [stats, setStats] = useState({
    total_websites: 0,
    total_pages: 0,
    total_blog_posts: 0,
    published_pages: 0,
    published_posts: 0,
    draft_posts: 0
  })

  useEffect(() => {
    fetchWebsites()
    fetchDashboard()
  }, [])

  const fetchWebsites = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/marketing/websites/`)
      if (response.ok) {
        const data = await response.json()
        setWebsites(data)
      }
    } catch (error) {
      console.error("Error fetching websites:", error)
    } finally {
      setLoading(false)
    }
  }

  const fetchDashboard = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/marketing/dashboard`)
      if (response.ok) {
        const data = await response.json()
        setStats(data)
      }
    } catch (error) {
      console.error("Error fetching dashboard:", error)
    }
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setSubmitting(true)
    
    try {
      const response = await fetch(`${API_BASE_URL}/marketing/websites/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(formData)
      })

      if (response.ok) {
        fetchWebsites()
        setShowModal(false)
        setFormData({ name: "", domain: "", status: "draft" })
      } else {
        const error = await response.json()
        alert(error.detail || "Failed to create website")
      }
    } catch (error) {
      console.error("Error creating website:", error)
      alert("Failed to create website")
    } finally {
      setSubmitting(false)
    }
  }

  const handleDelete = async (websiteId, websiteName) => {
    if (!confirm(`Are you sure you want to delete "${websiteName}"? This will delete all pages, blog posts, and media.`)) {
      return
    }

    try {
      const response = await fetch(`${API_BASE_URL}/marketing/websites/${websiteId}`, {
        method: "DELETE"
      })

      if (response.ok) {
        fetchWebsites()
        fetchDashboard()
      } else {
        alert("Failed to delete website")
      }
    } catch (error) {
      console.error("Error deleting website:", error)
      alert("Failed to delete website")
    }
  }

  const getStatusClass = (status) => {
    switch (status) {
      case "active": return "active"
      case "maintenance": return "maintenance"
      default: return "draft"
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center p-8">
        <Loader2 className="animate-spin" size={32} />
      </div>
    )
  }

  return (
    <div className="marketing-dashboard">
      {/* Header */}
      <div className="marketing-header">
        <h1>Website CMS</h1>
        <button 
          className="btn btn-primary flex items-center gap-2"
          onClick={() => setShowModal(true)}
        >
          <Plus size={18} />
          Add Website
        </button>
      </div>

      {/* Stats */}
      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-card-label">Total Websites</div>
          <div className="stat-card-value">{stats.total_websites}</div>
        </div>
        <div className="stat-card">
          <div className="stat-card-label">Total Pages</div>
          <div className="stat-card-value">{stats.total_pages}</div>
          <div className="stat-card-change positive">{stats.published_pages} published</div>
        </div>
        <div className="stat-card">
          <div className="stat-card-label">Blog Posts</div>
          <div className="stat-card-value">{stats.total_blog_posts}</div>
          <div className="stat-card-change positive">{stats.published_posts} published</div>
        </div>
        <div className="stat-card">
          <div className="stat-card-label">Draft Posts</div>
          <div className="stat-card-value">{stats.draft_posts}</div>
        </div>
      </div>

      {/* Websites List */}
      {websites.length === 0 ? (
        <div className="empty-state">
          <Globe size={48} />
          <h3>No websites yet</h3>
          <p>Create your first website to start managing content</p>
          <button 
            className="btn btn-primary flex items-center gap-2"
            onClick={() => setShowModal(true)}
          >
            <Plus size={18} />
            Add Website
          </button>
        </div>
      ) : (
        <div>
          {websites.map((website) => (
            <div key={website.id} className="website-card">
              <div className="website-card-header">
                <div className="website-info">
                  <h3>{website.name}</h3>
                  <a 
                    href={`https://${website.domain}`} 
                    target="_blank" 
                    rel="noopener noreferrer"
                    className="website-domain flex items-center gap-1"
                  >
                    {website.domain}
                    <ExternalLink size={12} />
                  </a>
                </div>
                <span className={`website-status ${getStatusClass(website.status)}`}>
                  {website.status}
                </span>
              </div>

              <div className="website-actions">
                <Link 
                  to={`/admin/marketing/websites/${website.id}/pages`}
                  className="website-action-btn"
                >
                  <FileText size={16} />
                  Pages
                </Link>
                <Link 
                  to={`/admin/marketing/websites/${website.id}/blog`}
                  className="website-action-btn"
                >
                  <BookOpen size={16} />
                  Blog
                </Link>
                <Link 
                  to={`/admin/marketing/websites/${website.id}/media`}
                  className="website-action-btn"
                >
                  <ImageIcon size={16} />
                  Media
                </Link>
                <Link 
                  to={`/admin/marketing/websites/${website.id}/navigation`}
                  className="website-action-btn"
                >
                  <Settings size={16} />
                  Navigation
                </Link>
                <Link 
                  to={`/admin/marketing/websites/${website.id}/analytics`}
                  className="website-action-btn"
                >
                  <BarChart3 size={16} />
                  Analytics
                </Link>
                <Link 
                  to={`/admin/marketing/websites/${website.id}/settings`}
                  className="website-action-btn primary"
                >
                  <Settings size={16} />
                  Settings
                </Link>
                <button 
                  className="website-action-btn"
                  onClick={() => handleDelete(website.id, website.name)}
                  style={{ color: '#ef4444' }}
                >
                  <Trash2 size={16} />
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Create Website Modal */}
      {showModal && (
        <div className="modal-overlay" style={{
          position: 'fixed',
          inset: 0,
          background: 'rgba(0,0,0,0.5)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 50
        }}>
          <div className="modal-content card" style={{
            width: '100%',
            maxWidth: '480px',
            margin: '1rem'
          }}>
            <div className="card-header">
              <h2 className="card-title">Add New Website</h2>
            </div>
            <form onSubmit={handleSubmit}>
              <div className="mb-4">
                <label className="block text-sm font-medium mb-1">Website Name</label>
                <input
                  type="text"
                  className="input"
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  placeholder="e.g., Survey Fieldwork"
                  required
                />
              </div>
              <div className="mb-4">
                <label className="block text-sm font-medium mb-1">Domain</label>
                <input
                  type="text"
                  className="input"
                  value={formData.domain}
                  onChange={(e) => setFormData({ ...formData, domain: e.target.value })}
                  placeholder="e.g., surveyfieldwork.com"
                  required
                />
              </div>
              <div className="mb-4">
                <label className="block text-sm font-medium mb-1">Status</label>
                <select
                  className="input"
                  value={formData.status}
                  onChange={(e) => setFormData({ ...formData, status: e.target.value })}
                >
                  <option value="draft">Draft</option>
                  <option value="active">Active</option>
                  <option value="maintenance">Maintenance</option>
                </select>
              </div>
              <div className="flex gap-2 justify-end">
                <button 
                  type="button" 
                  className="btn btn-outline"
                  onClick={() => setShowModal(false)}
                >
                  Cancel
                </button>
                <button 
                  type="submit" 
                  className="btn btn-primary flex items-center gap-2"
                  disabled={submitting}
                >
                  {submitting && <Loader2 className="animate-spin" size={16} />}
                  Create Website
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}

export default WebsitesPage
