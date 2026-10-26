"use client"

import { Link } from "react-router-dom"
import { 
  Globe, 
  BarChart3, 
  FileText, 
  BookOpen, 
  Image as ImageIcon,
  Plug,
  Sparkles,
  Inbox,
  ArrowRight
} from "lucide-react"

function Marketing() {
  const marketingModules = [
    { 
      title: "Website CMS", 
      description: "Manage your websites, pages, and content",
      icon: Globe,
      link: "/admin/marketing/websites",
      color: "#a15f06"
    },
    { 
      title: "Content calendar",
      description: "Posts per company and channel, Qwen drafts, claim checks, approval",
      icon: BookOpen,
      link: "/admin/marketing/content",
      color: "#166534"
    },
    { 
      title: "Inbox",
      description: "Forms, social comments and DMs, WhatsApp, lead forms, with reply SLA",
      icon: Inbox,
      link: "/admin/marketing/inbox",
      color: "#b91c1c"
    },
    { 
      title: "Media Library", 
      description: "Upload and manage images, videos, and documents",
      icon: ImageIcon,
      link: "/admin/marketing/media",
      color: "#8b5cf6"
    },
    { 
      title: "Marketing dashboard",
      description: "Leads, RFQs, won ₹, spend, ROAS, SEO, social, inbox SLA, decisions — and the weekly report",
      icon: BarChart3,
      link: "/admin/dashboards/marketing",
      color: "#b45309"
    },
    {
      title: "Decision Engine",
      description: "Recommendations, executed actions with undo, scorecard and autonomy per decision type",
      icon: Sparkles,
      link: "/admin/marketing/decisions",
      color: "#7c3aed"
    },
    {
      title: "Weekly report",
      description: "Monday 09:00 IST: per-company results, top 5 actions, engine results, SEO, content",
      icon: FileText,
      link: "/admin/marketing/report",
      color: "#475569"
    },
    {
      title: "Integrations",
      description: "Connect Google, LinkedIn, Meta, WhatsApp and Quora (tokens stored encrypted)",
      icon: Plug,
      link: "/admin/marketing/integrations",
      color: "#0a66c2"
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

        <div className="card bg-gradient-to-r from-cogentix-orange-50 to-cogentix-orange-50 border-cogentix-orange-200">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="card-title text-cogentix-orange-900">Get Started with Website CMS</h3>
              <p className="card-description text-cogentix-orange-700">
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
