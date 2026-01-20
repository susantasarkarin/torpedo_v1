"use client"

import { Link } from "react-router-dom"
import { 
  Globe, 
  BarChart3, 
  FileText, 
  BookOpen, 
  Image as ImageIcon,
  ArrowRight
} from "lucide-react"

function Marketing() {
  const marketingModules = [
    { 
      title: "Website CMS", 
      description: "Manage your websites, pages, and content",
      icon: Globe,
      link: "/admin/marketing/websites",
      color: "#3b82f6"
    },
    { 
      title: "Blog Management", 
      description: "Create and publish blog posts",
      icon: BookOpen,
      link: "/admin/marketing/websites",
      color: "#10b981"
    },
    { 
      title: "Media Library", 
      description: "Upload and manage images, videos, and documents",
      icon: ImageIcon,
      link: "/admin/marketing/media",
      color: "#8b5cf6"
    },
    { 
      title: "Analytics", 
      description: "Track website performance and visitor insights",
      icon: BarChart3,
      link: "/admin/marketing/websites",
      color: "#f59e0b"
    },
  ]

  return (
    <div>
      <div className="card">
        <div className="card-header">
          <h2 className="card-title">Marketing Dashboard</h2>
          <p className="card-description">
            Manage your websites, content strategy, and brand communications.
          </p>
        </div>

        <div className="grid grid-cols-2 mb-6 gap-4">
          {marketingModules.map((module, index) => {
            const Icon = module.icon
            return (
              <Link 
                key={index} 
                to={module.link}
                className="card hover:shadow-lg transition-shadow cursor-pointer"
                style={{ textDecoration: 'none' }}
              >
                <div className="flex items-start gap-4">
                  <div 
                    className="p-3 rounded-lg"
                    style={{ backgroundColor: `${module.color}15` }}
                  >
                    <Icon size={24} style={{ color: module.color }} />
                  </div>
                  <div className="flex-1">
                    <h3 className="card-title mb-1">{module.title}</h3>
                    <p className="card-description">{module.description}</p>
                  </div>
                  <ArrowRight size={20} className="text-gray-400 mt-1" />
                </div>
              </Link>
            )
          })}
        </div>

        <div className="card bg-gradient-to-r from-blue-50 to-indigo-50 border-blue-200">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="card-title text-blue-900">Get Started with Website CMS</h3>
              <p className="card-description text-blue-700">
                Create and manage your websites directly from the CRM. 
                Control content, track performance, and publish updates.
              </p>
            </div>
            <Link 
              to="/admin/marketing/websites" 
              className="btn btn-primary flex items-center gap-2"
            >
              <Globe size={18} />
              Go to Websites
              <ArrowRight size={18} />
            </Link>
          </div>
        </div>
      </div>
    </div>
  )
}

export default Marketing
