"use client"

import { useState, useEffect } from "react"
import { useParams, Link, useNavigate } from "react-router-dom"
import { API_BASE_URL } from "../../config"
import { 
import { buildApiUrl } from "../../config"
  BookOpen, 
  Plus, 
  Edit, 
  Trash2, 
  Eye, 
  Check, 
  Loader2,
  ArrowLeft,
  ChevronRight,
  Calendar,
  Tag
} from "lucide-react"
import "./Marketing.css"

function BlogPage() {
  const { websiteId } = useParams()
  const navigate = useNavigate()
  const [website, setWebsite] = useState(null)
  const [posts, setPosts] = useState([])
  const [loading, setLoading] = useState(true)
  const [showModal, setShowModal] = useState(false)
  const [editingPost, setEditingPost] = useState(null)
  const [filter, setFilter] = useState("all")
  const [formData, setFormData] = useState({
    slug: "",
    title: "",
    excerpt: "",
    categories: [],
    tags: [],
    status: "draft"
  })
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    fetchWebsite()
    fetchPosts()
  }, [websiteId, filter])

  const fetchWebsite = async () => {
    try {
      const response = await fetch(buildApiUrl(`/marketing/websites/${websiteId}`))
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

  const fetchPosts = async () => {
    try {
      let url = buildApiUrl(`/marketing/websites/${websiteId}/blog/`)
      if (filter !== "all") {
        url += `?status=${filter}`
      }
      
      const response = await fetch(url)
      if (response.ok) {
        const data = await response.json()
        setPosts(data)
      }
    } catch (error) {
      console.error("Error fetching posts:", error)
    } finally {
      setLoading(false)
    }
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setSubmitting(true)
    
    try {
      const url = editingPost
        ? buildApiUrl(`/marketing/websites/${websiteId}/blog/${editingPost.id}`)
        : buildApiUrl(`/marketing/websites/${websiteId}/blog/`)
      
      const method = editingPost ? "PUT" : "POST"

      // Process categories and tags from comma-separated string
      const payload = {
        ...formData,
        categories: typeof formData.categories === 'string' 
          ? formData.categories.split(',').map(c => c.trim()).filter(Boolean)
          : formData.categories,
        tags: typeof formData.tags === 'string'
          ? formData.tags.split(',').map(t => t.trim()).filter(Boolean)
          : formData.tags,
        content: {}  // Default empty content
      }

      const response = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      })

      if (response.ok) {
        fetchPosts()
        closeModal()
      } else {
        const error = await response.json()
        alert(error.detail || "Failed to save post")
      }
    } catch (error) {
      console.error("Error saving post:", error)
      alert("Failed to save post")
    } finally {
      setSubmitting(false)
    }
  }

  const handleDelete = async (postId, postTitle) => {
    if (!confirm(`Are you sure you want to delete "${postTitle}"?`)) {
      return
    }

    try {
      const response = await fetch(
        buildApiUrl(`/marketing/websites/${websiteId}/blog/${postId}`),
        { method: "DELETE" }
      )

      if (response.ok) {
        fetchPosts()
      } else {
        alert("Failed to delete post")
      }
    } catch (error) {
      console.error("Error deleting post:", error)
      alert("Failed to delete post")
    }
  }

  const handlePublish = async (postId) => {
    try {
      const response = await fetch(
        buildApiUrl(`/marketing/websites/${websiteId}/blog/${postId}/publish`),
        { method: "POST" }
      )

      if (response.ok) {
        fetchPosts()
      } else {
        alert("Failed to publish post")
      }
    } catch (error) {
      console.error("Error publishing post:", error)
    }
  }

  const openEditModal = (post) => {
    setEditingPost(post)
    setFormData({
      slug: post.slug,
      title: post.title,
      excerpt: post.excerpt || "",
      categories: post.categories?.join(", ") || "",
      tags: post.tags?.join(", ") || "",
      status: post.status
    })
    setShowModal(true)
  }

  const closeModal = () => {
    setShowModal(false)
    setEditingPost(null)
    setFormData({ 
      slug: "", 
      title: "", 
      excerpt: "",
      categories: [],
      tags: [],
      status: "draft" 
    })
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
        <span className="text-gray-900 font-medium">Blog</span>
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
          <h1>Blog - {website?.name}</h1>
        </div>
        <div className="flex items-center gap-3">
          <select
            className="input"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            style={{ width: 'auto' }}
          >
            <option value="all">All Posts</option>
            <option value="published">Published</option>
            <option value="draft">Drafts</option>
          </select>
          <button 
            className="btn btn-primary flex items-center gap-2"
            onClick={() => setShowModal(true)}
          >
            <Plus size={18} />
            New Post
          </button>
        </div>
      </div>

      {/* Posts List */}
      {posts.length === 0 ? (
        <div className="empty-state">
          <BookOpen size={48} />
          <h3>No blog posts yet</h3>
          <p>Create your first blog post to start publishing content</p>
          <button 
            className="btn btn-primary flex items-center gap-2"
            onClick={() => setShowModal(true)}
          >
            <Plus size={18} />
            New Post
          </button>
        </div>
      ) : (
        <div className="blog-list">
          {posts.map((post) => (
            <div key={post.id} className="blog-item">
              {post.featured_image ? (
                <img 
                  src={post.featured_image} 
                  alt={post.title} 
                  className="blog-item-thumbnail"
                />
              ) : (
                <div className="blog-item-thumbnail flex items-center justify-center">
                  <BookOpen size={32} className="text-gray-400" />
                </div>
              )}
              
              <div className="blog-item-content">
                <h4>{post.title}</h4>
                <p>{post.excerpt || 'No excerpt'}</p>
                <div className="blog-item-meta">
                  <span className="flex items-center gap-1">
                    <Calendar size={12} />
                    {post.published_at 
                      ? new Date(post.published_at).toLocaleDateString()
                      : 'Not published'
                    }
                  </span>
                  <span className={`website-status ${post.status === 'published' ? 'active' : 'draft'}`}>
                    {post.status}
                  </span>
                  {post.categories?.length > 0 && (
                    <span className="flex items-center gap-1">
                      <Tag size={12} />
                      {post.categories.join(', ')}
                    </span>
                  )}
                </div>
              </div>
              
              <div className="flex items-center gap-2">
                <Link
                  to={`/admin/marketing/websites/${websiteId}/blog/${post.id}/edit`}
                  className="p-2 hover:bg-gray-100 rounded-lg"
                  title="Edit content"
                >
                  <Edit size={18} />
                </Link>
                <a
                  href={`https://${website?.domain}/blog/${post.slug}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="p-2 hover:bg-gray-100 rounded-lg"
                  title="Preview"
                >
                  <Eye size={18} />
                </a>
                {post.status !== 'published' && (
                  <button
                    onClick={() => handlePublish(post.id)}
                    className="p-2 hover:bg-green-100 text-green-600 rounded-lg"
                    title="Publish"
                  >
                    <Check size={18} />
                  </button>
                )}
                <button
                  onClick={() => openEditModal(post)}
                  className="p-2 hover:bg-gray-100 rounded-lg"
                  title="Edit details"
                >
                  <BookOpen size={18} />
                </button>
                <button
                  onClick={() => handleDelete(post.id, post.title)}
                  className="p-2 hover:bg-red-100 text-red-500 rounded-lg"
                  title="Delete"
                >
                  <Trash2 size={18} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Create/Edit Post Modal */}
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
            maxWidth: '560px',
            margin: '1rem',
            maxHeight: '90vh',
            overflow: 'auto'
          }}>
            <div className="card-header">
              <h2 className="card-title">{editingPost ? 'Edit Post' : 'New Blog Post'}</h2>
            </div>
            <form onSubmit={handleSubmit}>
              <div className="mb-4">
                <label className="block text-sm font-medium mb-1">Post Title</label>
                <input
                  type="text"
                  className="input"
                  value={formData.title}
                  onChange={(e) => setFormData({ ...formData, title: e.target.value })}
                  placeholder="e.g., How to Conduct Effective Market Research"
                  required
                />
              </div>
              {!editingPost && (
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
                    placeholder="e.g., effective-market-research"
                    required
                  />
                  <p className="text-xs text-gray-500 mt-1">
                    URL: https://{website?.domain}/blog/{formData.slug || 'post-slug'}
                  </p>
                </div>
              )}
              <div className="mb-4">
                <label className="block text-sm font-medium mb-1">Excerpt</label>
                <textarea
                  className="input"
                  rows={3}
                  value={formData.excerpt}
                  onChange={(e) => setFormData({ ...formData, excerpt: e.target.value })}
                  placeholder="Brief summary of the post..."
                />
              </div>
              <div className="mb-4">
                <label className="block text-sm font-medium mb-1">Categories (comma-separated)</label>
                <input
                  type="text"
                  className="input"
                  value={formData.categories}
                  onChange={(e) => setFormData({ ...formData, categories: e.target.value })}
                  placeholder="e.g., Research, Market Trends"
                />
              </div>
              <div className="mb-4">
                <label className="block text-sm font-medium mb-1">Tags (comma-separated)</label>
                <input
                  type="text"
                  className="input"
                  value={formData.tags}
                  onChange={(e) => setFormData({ ...formData, tags: e.target.value })}
                  placeholder="e.g., surveys, data collection, methodology"
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
                  {editingPost ? 'Update' : 'Create'} Post
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}

export default BlogPage
