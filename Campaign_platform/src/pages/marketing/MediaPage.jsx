"use client"

import { useState, useEffect, useRef } from "react"
import { useParams, Link } from "react-router-dom"
import { API_BASE_URL } from "../../config"
import { 
  Image as ImageIcon, 
  Upload, 
  Trash2, 
  Loader2,
  ArrowLeft,
  ChevronRight,
  Copy,
  Check,
  Film,
  FileText as FileIcon,
  X
} from "lucide-react"
import "./Marketing.css"

function MediaPage() {
  const { websiteId } = useParams()
  const fileInputRef = useRef(null)
  const [website, setWebsite] = useState(null)
  const [media, setMedia] = useState([])
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [typeFilter, setTypeFilter] = useState("all")
  const [selectedMedia, setSelectedMedia] = useState(null)
  const [copiedUrl, setCopiedUrl] = useState(null)

  useEffect(() => {
    if (websiteId) {
      fetchWebsite()
    }
    fetchMedia()
  }, [websiteId, typeFilter])

  const fetchWebsite = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/marketing/websites/${websiteId}`)
      if (response.ok) {
        const data = await response.json()
        setWebsite(data)
      }
    } catch (error) {
      console.error("Error fetching website:", error)
    }
  }

  const fetchMedia = async () => {
    try {
      let url = `${API_BASE_URL}/marketing/media/`
      const params = new URLSearchParams()
      
      if (websiteId) {
        params.append("website_id", websiteId)
      }
      if (typeFilter !== "all") {
        params.append("type", typeFilter)
      }
      
      if (params.toString()) {
        url += `?${params.toString()}`
      }
      
      const response = await fetch(url)
      if (response.ok) {
        const data = await response.json()
        setMedia(data)
      }
    } catch (error) {
      console.error("Error fetching media:", error)
    } finally {
      setLoading(false)
    }
  }

  const handleUpload = async (e) => {
    const files = e.target.files
    if (!files || files.length === 0) return
    
    setUploading(true)
    
    try {
      for (const file of files) {
        const formData = new FormData()
        formData.append("file", file)
        if (websiteId) {
          formData.append("website_id", websiteId)
        }
        
        await fetch(`${API_BASE_URL}/marketing/media/upload`, {
          method: "POST",
          body: formData
        })
      }
      
      fetchMedia()
    } catch (error) {
      console.error("Error uploading file:", error)
      alert("Failed to upload file")
    } finally {
      setUploading(false)
      if (fileInputRef.current) {
        fileInputRef.current.value = ""
      }
    }
  }

  const handleDelete = async (mediaId) => {
    if (!confirm("Are you sure you want to delete this file?")) {
      return
    }

    try {
      const response = await fetch(`${API_BASE_URL}/marketing/media/${mediaId}`, {
        method: "DELETE"
      })

      if (response.ok) {
        fetchMedia()
        if (selectedMedia?.id === mediaId) {
          setSelectedMedia(null)
        }
      } else {
        alert("Failed to delete file")
      }
    } catch (error) {
      console.error("Error deleting file:", error)
      alert("Failed to delete file")
    }
  }

  const copyUrl = (url) => {
    navigator.clipboard.writeText(url)
    setCopiedUrl(url)
    setTimeout(() => setCopiedUrl(null), 2000)
  }

  const getMediaIcon = (type) => {
    switch (type) {
      case "video": return Film
      case "image": return ImageIcon
      case "lottie": return ImageIcon
      default: return FileIcon
    }
  }

  const formatFileSize = (bytes) => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
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
      {websiteId && (
        <div className="flex items-center gap-2 text-sm text-gray-500 mb-4">
          <Link to="/admin/marketing/websites" className="hover:text-gray-700">
            Websites
          </Link>
          <ChevronRight size={16} />
          <span className="text-gray-700">{website?.name}</span>
          <ChevronRight size={16} />
          <span className="text-gray-900 font-medium">Media</span>
        </div>
      )}

      {/* Header */}
      <div className="marketing-header">
        <div className="flex items-center gap-3">
          {websiteId && (
            <Link 
              to="/admin/marketing/websites" 
              className="p-2 hover:bg-gray-100 rounded-lg"
            >
              <ArrowLeft size={20} />
            </Link>
          )}
          <h1>Media Library {website ? `- ${website.name}` : ''}</h1>
        </div>
        <div className="flex items-center gap-3">
          <select
            className="input"
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
            style={{ width: 'auto' }}
          >
            <option value="all">All Types</option>
            <option value="image">Images</option>
            <option value="video">Videos</option>
            <option value="document">Documents</option>
            <option value="lottie">Lottie</option>
          </select>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            onChange={handleUpload}
            className="hidden"
            accept="image/*,video/*,.json,.pdf,.doc,.docx"
          />
          <button 
            className="btn btn-primary flex items-center gap-2"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
          >
            {uploading ? (
              <Loader2 className="animate-spin" size={18} />
            ) : (
              <Upload size={18} />
            )}
            Upload Files
          </button>
        </div>
      </div>

      {/* Media Grid */}
      {media.length === 0 ? (
        <div className="empty-state">
          <ImageIcon size={48} />
          <h3>No media files yet</h3>
          <p>Upload images, videos, or documents to your media library</p>
          <button 
            className="btn btn-primary flex items-center gap-2"
            onClick={() => fileInputRef.current?.click()}
          >
            <Upload size={18} />
            Upload Files
          </button>
        </div>
      ) : (
        <div className="media-grid">
          {media.map((item) => {
            const Icon = getMediaIcon(item.type)
            
            return (
              <div 
                key={item.id} 
                className="media-item"
                onClick={() => setSelectedMedia(item)}
              >
                {item.type === "image" ? (
                  <img src={item.url} alt={item.alt_text || item.original_name} />
                ) : (
                  <div className="flex items-center justify-center h-full bg-gray-100">
                    <Icon size={32} className="text-gray-400" />
                  </div>
                )}
                <div className="media-item-overlay">
                  <button
                    className="p-2 bg-white rounded-lg text-gray-700 hover:bg-gray-100"
                    onClick={(e) => {
                      e.stopPropagation()
                      copyUrl(item.url)
                    }}
                  >
                    {copiedUrl === item.url ? <Check size={18} /> : <Copy size={18} />}
                  </button>
                  <button
                    className="p-2 bg-white rounded-lg text-red-500 hover:bg-red-50"
                    onClick={(e) => {
                      e.stopPropagation()
                      handleDelete(item.id)
                    }}
                  >
                    <Trash2 size={18} />
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Media Detail Modal */}
      {selectedMedia && (
        <div 
          className="modal-overlay" 
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.7)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 50
          }}
          onClick={() => setSelectedMedia(null)}
        >
          <div 
            className="modal-content card" 
            style={{
              width: '100%',
              maxWidth: '800px',
              margin: '1rem'
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="card-header flex justify-between items-center">
              <h2 className="card-title">{selectedMedia.original_name}</h2>
              <button 
                className="p-2 hover:bg-gray-100 rounded-lg"
                onClick={() => setSelectedMedia(null)}
              >
                <X size={20} />
              </button>
            </div>
            
            <div className="p-4">
              {selectedMedia.type === "image" ? (
                <img 
                  src={selectedMedia.url} 
                  alt={selectedMedia.alt_text || selectedMedia.original_name}
                  className="max-w-full max-h-[400px] mx-auto rounded-lg"
                />
              ) : (
                <div className="flex items-center justify-center h-48 bg-gray-100 rounded-lg">
                  {(() => {
                    const Icon = getMediaIcon(selectedMedia.type)
                    return <Icon size={64} className="text-gray-400" />
                  })()}
                </div>
              )}
              
              <div className="mt-4 space-y-3">
                <div>
                  <label className="text-sm font-medium text-gray-500">URL</label>
                  <div className="flex gap-2 mt-1">
                    <input 
                      type="text" 
                      className="input flex-1"
                      value={selectedMedia.url}
                      readOnly
                    />
                    <button 
                      className="btn btn-outline flex items-center gap-2"
                      onClick={() => copyUrl(selectedMedia.url)}
                    >
                      {copiedUrl === selectedMedia.url ? <Check size={16} /> : <Copy size={16} />}
                      Copy
                    </button>
                  </div>
                </div>
                
                <div className="grid grid-cols-3 gap-4 text-sm">
                  <div>
                    <span className="text-gray-500">Type:</span>
                    <span className="ml-2 font-medium">{selectedMedia.type}</span>
                  </div>
                  <div>
                    <span className="text-gray-500">Size:</span>
                    <span className="ml-2 font-medium">{formatFileSize(selectedMedia.size)}</span>
                  </div>
                  <div>
                    <span className="text-gray-500">Uploaded:</span>
                    <span className="ml-2 font-medium">
                      {new Date(selectedMedia.created_at).toLocaleDateString()}
                    </span>
                  </div>
                </div>
              </div>
            </div>
            
            <div className="flex gap-2 justify-end p-4 border-t">
              <button 
                className="btn btn-outline text-red-500 border-red-300 hover:bg-red-50 flex items-center gap-2"
                onClick={() => {
                  handleDelete(selectedMedia.id)
                }}
              >
                <Trash2 size={16} />
                Delete
              </button>
              <button 
                className="btn btn-primary"
                onClick={() => setSelectedMedia(null)}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default MediaPage
