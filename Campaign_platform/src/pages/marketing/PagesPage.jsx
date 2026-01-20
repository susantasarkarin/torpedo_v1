"use client"

import { useState, useEffect } from "react"
import { useParams, Link, useNavigate } from "react-router-dom"
import { API_BASE_URL } from "../../config"
import { 
  FileText, 
  Plus, 
  Edit, 
  Trash2, 
  Eye, 
  Check, 
  Loader2,
  ArrowLeft,
  ChevronRight
} from "lucide-react"
import "./Marketing.css"

function PagesPage() {
  const { websiteId } = useParams()
  const navigate = useNavigate()
  const [website, setWebsite] = useState(null)
  const [pages, setPages] = useState([])
  const [loading, setLoading] = useState(true)
  const [showModal, setShowModal] = useState(false)
  const [editingPage, setEditingPage] = useState(null)
  const [formData, setFormData] = useState({
    slug: "",
    title: "",
    status: "draft"
  })
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    fetchWebsite()
    fetchPages()
  }, [websiteId])

  const fetchWebsite = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/marketing/websites/${websiteId}`)
      if (response.ok) {
        const data = await response.json()
        setWebsite(data)
      } else {
        navigate("/admin/marketing/websites")
      }
    } catch (error) {
      console.error("Error fetching website:", error)
      navigate("/admin/marketing/websites")
    }
  }

  const fetchPages = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/marketing/websites/${websiteId}/pages/`)
      if (response.ok) {
        const data = await response.json()
        setPages(data)
      }
    } catch (error) {
      console.error("Error fetching pages:", error)
    } finally {
      setLoading(false)
    }
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setSubmitting(true)
    
    try {
      const url = editingPage
        ? `${API_BASE_URL}/marketing/websites/${websiteId}/pages/${editingPage.id}`
        : `${API_BASE_URL}/marketing/websites/${websiteId}/pages/`
      
      const method = editingPage ? "PUT" : "POST"

      const response = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(formData)
      })

      if (response.ok) {
        fetchPages()
        closeModal()
      } else {
        const error = await response.json()
        alert(error.detail || "Failed to save page")
      }
    } catch (error) {
      console.error("Error saving page:", error)
      alert("Failed to save page")
    } finally {
      setSubmitting(false)
    }
  }

  const handleDelete = async (pageId, pageTitle) => {
    if (!confirm(`Are you sure you want to delete "${pageTitle}"?`)) {
      return
    }

    try {
      const response = await fetch(
        `${API_BASE_URL}/marketing/websites/${websiteId}/pages/${pageId}`,
        { method: "DELETE" }
      )

      if (response.ok) {
        fetchPages()
      } else {
        alert("Failed to delete page")
      }
    } catch (error) {
      console.error("Error deleting page:", error)
      alert("Failed to delete page")
    }
  }

  const handlePublish = async (pageId) => {
    try {
      const response = await fetch(
        `${API_BASE_URL}/marketing/websites/${websiteId}/pages/${pageId}/publish`,
        { method: "POST" }
      )

      if (response.ok) {
        fetchPages()
      } else {
        alert("Failed to publish page")
      }
    } catch (error) {
      console.error("Error publishing page:", error)
    }
  }

  const openEditModal = (page) => {
    setEditingPage(page)
    setFormData({
      slug: page.slug,
      title: page.title,
      status: page.status
    })
    setShowModal(true)
  }

  const closeModal = () => {
    setShowModal(false)
    setEditingPage(null)
    setFormData({ slug: "", title: "", status: "draft" })
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
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm text-gray-500 mb-4">
        <Link to="/admin/marketing/websites" className="hover:text-gray-700">
          Websites
        </Link>
        <ChevronRight size={16} />
        <span className="text-gray-700">{website?.name}</span>
        <ChevronRight size={16} />
        <span className="text-gray-900 font-medium">Pages</span>
      </div>

      {/* Header */}
      <div className="marketing-header">
        <div className="flex items-center gap-3">
          <Link 
            to="/admin/marketing/websites" 
            className="p-2 hover:bg-gray-100 rounded-lg"
          >
            <ArrowLeft size={20} />
          </Link>
          <h1>Pages - {website?.name}</h1>
        </div>
        <button 
          className="btn btn-primary flex items-center gap-2"
          onClick={() => setShowModal(true)}
        >
          <Plus size={18} />
          Add Page
        </button>
      </div>

      {/* Pages List */}
      {pages.length === 0 ? (
        <div className="empty-state">
          <FileText size={48} />
          <h3>No pages yet</h3>
          <p>Create your first page to start building your website</p>
          <button 
            className="btn btn-primary flex items-center gap-2"
            onClick={() => setShowModal(true)}
          >
            <Plus size={18} />
            Add Page
          </button>
        </div>
      ) : (
        <div className="card">
          <table className="table w-full">
            <thead>
              <tr>
                <th className="text-left p-3">Title</th>
                <th className="text-left p-3">Slug</th>
                <th className="text-left p-3">Status</th>
                <th className="text-left p-3">Updated</th>
                <th className="text-right p-3">Actions</th>
              </tr>
            </thead>
            <tbody>
              {pages.map((page) => (
                <tr key={page.id} className="border-t">
                  <td className="p-3 font-medium">{page.title}</td>
                  <td className="p-3 text-gray-500">/{page.slug}</td>
                  <td className="p-3">
                    <span className={`website-status ${page.status === 'published' ? 'active' : 'draft'}`}>
                      {page.status}
                    </span>
                  </td>
                  <td className="p-3 text-gray-500 text-sm">
                    {new Date(page.updated_at).toLocaleDateString()}
                  </td>
                  <td className="p-3">
                    <div className="flex gap-2 justify-end">
                      <Link
                        to={`/admin/marketing/websites/${websiteId}/pages/${page.id}/edit`}
                        className="p-2 hover:bg-gray-100 rounded-lg"
                        title="Edit sections"
                      >
                        <Edit size={18} />
                      </Link>
                      <a
                        href={`https://${website?.domain}/${page.slug}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="p-2 hover:bg-gray-100 rounded-lg"
                        title="Preview"
                      >
                        <Eye size={18} />
                      </a>
                      {page.status !== 'published' && (
                        <button
                          onClick={() => handlePublish(page.id)}
                          className="p-2 hover:bg-green-100 text-green-600 rounded-lg"
                          title="Publish"
                        >
                          <Check size={18} />
                        </button>
                      )}
                      <button
                        onClick={() => openEditModal(page)}
                        className="p-2 hover:bg-gray-100 rounded-lg"
                        title="Edit details"
                      >
                        <FileText size={18} />
                      </button>
                      <button
                        onClick={() => handleDelete(page.id, page.title)}
                        className="p-2 hover:bg-red-100 text-red-500 rounded-lg"
                        title="Delete"
                      >
                        <Trash2 size={18} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Create/Edit Page Modal */}
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
              <h2 className="card-title">{editingPage ? 'Edit Page' : 'Add New Page'}</h2>
            </div>
            <form onSubmit={handleSubmit}>
              <div className="mb-4">
                <label className="block text-sm font-medium mb-1">Page Title</label>
                <input
                  type="text"
                  className="input"
                  value={formData.title}
                  onChange={(e) => setFormData({ ...formData, title: e.target.value })}
                  placeholder="e.g., About Us"
                  required
                />
              </div>
              {!editingPage && (
                <div className="mb-4">
                  <label className="block text-sm font-medium mb-1">Slug (URL path)</label>
                  <input
                    type="text"
                    className="input"
                    value={formData.slug}
                    onChange={(e) => setFormData({ 
                      ...formData, 
                      slug: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '-')
                    })}
                    placeholder="e.g., about-us"
                    required
                  />
                  <p className="text-xs text-gray-500 mt-1">
                    URL: https://{website?.domain}/{formData.slug || 'page-slug'}
                  </p>
                </div>
              )}
              <div className="mb-4">
                <label className="block text-sm font-medium mb-1">Status</label>
                <select
                  className="input"
                  value={formData.status}
                  onChange={(e) => setFormData({ ...formData, status: e.target.value })}
                >
                  <option value="draft">Draft</option>
                  <option value="published">Published</option>
                </select>
              </div>
              <div className="flex gap-2 justify-end">
                <button 
                  type="button" 
                  className="btn btn-outline"
                  onClick={closeModal}
                >
                  Cancel
                </button>
                <button 
                  type="submit" 
                  className="btn btn-primary flex items-center gap-2"
                  disabled={submitting}
                >
                  {submitting && <Loader2 className="animate-spin" size={16} />}
                  {editingPage ? 'Update' : 'Create'} Page
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}

export default PagesPage
