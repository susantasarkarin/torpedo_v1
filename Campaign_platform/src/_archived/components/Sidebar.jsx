// "use client"

// import { Link, useLocation } from "react-router-dom"
// import { useState, useEffect } from "react"

// function Sidebar() {
//   const location = useLocation()
//   const [salesDropdownOpen, setSalesDropdownOpen] = useState(false)
//   const [campaignDropdownOpen, setCampaignDropdownOpen] = useState(false)

//   useEffect(() => {
//     if (!location.pathname.startsWith("/sales")) {
//       setSalesDropdownOpen(false)
//       setCampaignDropdownOpen(false)
//     } else if (!location.pathname.startsWith("/sales/campaign")) {
//       setCampaignDropdownOpen(false)
//     }
//   }, [location.pathname])

//   const isActive = (path) => {
//     return location.pathname === path || location.pathname.startsWith(path)
//   }

//   const showSalesDropdown = location.pathname.startsWith("/sales") || salesDropdownOpen
//   const showCampaignDropdown =
//     (location.pathname.startsWith("/sales/campaign") || campaignDropdownOpen) && showSalesDropdown

//   const handleSalesToggle = (e) => {
//     e.preventDefault()
//     e.stopPropagation()

//     if (salesDropdownOpen) {
//       // Closing sales dropdown
//       setSalesDropdownOpen(false)
//       setCampaignDropdownOpen(false)
//     } else {
//       // Opening sales dropdown
//       setSalesDropdownOpen(true)
//     }
//   }

//   const handleCampaignToggle = (e) => {
//     e.preventDefault()
//     e.stopPropagation()
//     setCampaignDropdownOpen(!campaignDropdownOpen)
//   }

//   return (
//     <aside className="sidebar">
//       <div className="sidebar-brand">
//         <h2>Email Campaigns</h2>
//       </div>

//       <nav className="sidebar-nav">
//         <div className="nav-section">
//           <div className={`nav-item dropdown ${showSalesDropdown ? "open" : ""}`}>
//             <button className="nav-link dropdown-toggle" onClick={handleSalesToggle} type="button">
//               <span className="nav-link-icon">📊</span>
//               <span>Sales</span>
//               <span className={`dropdown-arrow ${showSalesDropdown ? "rotated" : ""}`}>▼</span>
//             </button>
//             <div className="dropdown-menu">
//               <button
//                 className={`dropdown-item ${isActive("/sales/campaign") ? "active" : ""}`}
//                 onClick={handleCampaignToggle}
//                 type="button"
//               >
//                 Campaign
//                 <span className={`dropdown-arrow ${showCampaignDropdown ? "rotated" : ""}`}>▼</span>
//               </button>
//               <Link to="/sales/leads" className={`dropdown-item ${isActive("/sales/leads") ? "active" : ""}`}>
//                 Leads
//               </Link>
//               <Link to="/sales/contacts" className={`dropdown-item ${isActive("/sales/contacts") ? "active" : ""}`}>
//                 Contacts
//               </Link>
//               <Link to="/sales/account" className={`dropdown-item ${isActive("/sales/account") ? "active" : ""}`}>
//                 Account
//               </Link>
//               <Link to="/sales/rfq" className={`dropdown-item ${isActive("/sales/rfq") ? "active" : ""}`}>
//                 RFQ
//               </Link>
//             </div>
//           </div>
//         </div>

//         {showCampaignDropdown && (
//           <div className="nav-section campaign-subsection">
//             <div className="dropdown-menu campaign-submenu">
//               <Link
//                 to="/sales/campaign/list"
//                 className={`dropdown-item ${isActive("/sales/campaign/list") ? "active" : ""}`}
//               >
//                 <span className="nav-link-icon">📋</span>
//                 List
//               </Link>
//               <Link
//                 to="/sales/campaign/templates"
//                 className={`dropdown-item ${isActive("/sales/campaign/templates") ? "active" : ""}`}
//               >
//                 <span className="nav-link-icon">📝</span>
//                 Templates
//               </Link>
//               <Link
//                 to="/sales/campaign/workflow"
//                 className={`dropdown-item ${isActive("/sales/campaign/workflow") ? "active" : ""}`}
//               >
//                 <span className="nav-link-icon">🔄</span>
//                 Workflow
//               </Link>
//               <Link
//                 to="/sales/campaign/reports"
//                 className={`dropdown-item ${isActive("/sales/campaign/reports") ? "active" : ""}`}
//               >
//                 <span className="nav-link-icon">📊</span>
//                 Reports
//               </Link>
//             </div>
//           </div>
//         )}

//         <div className="nav-section">
//           <div className="nav-item">
//             <Link to="/marketing" className={`nav-link ${isActive("/marketing") ? "active" : ""}`}>
//               <span className="nav-link-icon">📈</span>
//               Marketing
//             </Link>
//           </div>
//         </div>

//         <div className="nav-section">
//           <div className="nav-item">
//             <Link to="/finance" className={`nav-link ${isActive("/finance") ? "active" : ""}`}>
//               <span className="nav-link-icon">💰</span>
//               Finance
//             </Link>
//           </div>
//         </div>

//         <div className="nav-section">
//           <div className="nav-item">
//             <Link to="/operations" className={`nav-link ${isActive("/operations") ? "active" : ""}`}>
//               <span className="nav-link-icon">⚙️</span>
//               Operations
//             </Link>
//           </div>
//         </div>

//         <div className="nav-section">
//           <div className="nav-item">
//             <Link to="/hr" className={`nav-link ${isActive("/hr") ? "active" : ""}`}>
//               <span className="nav-link-icon">👥</span>
//               HR
//             </Link>
//           </div>
//         </div>
//       </nav>
//     </aside>
//   )
// }

// export default Sidebar
