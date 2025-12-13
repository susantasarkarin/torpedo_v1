// "use client"

// import { useState, useEffect } from "react"
// import "./ContactsStatistics.css"

// function ContactsStatistics({ importedData, onBack }) {
//   const [contacts, setContacts] = useState([])
//   const [statistics, setStatistics] = useState({
//     total: 0,
//     subscribed: 0,
//     unsubscribed: 0,
//     bounced: 0,
//     dateRange: "Aug 1 - Aug 31, 2024",
//   })

//   useEffect(() => {
//     if (importedData) {
//       // Simulate processing imported CSV data
//       const mockContacts = [
//         {
//           id: 1,
//           name: "John Doe",
//           email: "john@example.com",
//           phone: "+1234567890",
//           status: "subscribed",
//           company: "Tech Corp",
//         },
//         {
//           id: 2,
//           name: "Jane Smith",
//           email: "jane@example.com",
//           phone: "+1234567891",
//           status: "subscribed",
//           company: "Design Inc",
//         },
//         {
//           id: 3,
//           name: "Bob Johnson",
//           email: "bob@example.com",
//           phone: "+1234567892",
//           status: "unsubscribed",
//           company: "Marketing Ltd",
//         },
//         {
//           id: 4,
//           name: "Alice Brown",
//           email: "alice@example.com",
//           phone: "+1234567893",
//           status: "subscribed",
//           company: "Sales Co",
//         },
//         {
//           id: 5,
//           name: "Charlie Wilson",
//           email: "charlie@example.com",
//           phone: "+1234567894",
//           status: "subscribed",
//           company: "Dev Studio",
//         },
//       ]

//       setContacts(mockContacts)

//       // Calculate statistics
//       const total = mockContacts.length
//       const subscribed = mockContacts.filter((c) => c.status === "subscribed").length
//       const unsubscribed = mockContacts.filter((c) => c.status === "unsubscribed").length
//       const bounced = 0 // Mock data

//       setStatistics({
//         total,
//         subscribed,
//         unsubscribed,
//         bounced,
//         dateRange: "Aug 1 - Aug 31, 2024",
//       })
//     }
//   }, [importedData])

//   return (
//     <div className="contacts-statistics-container">
//       <div className="page-header">
//         <div className="breadcrumb">
//           <button className="breadcrumb-link" onClick={onBack}>
//             Lists
//           </button>
//           <span className="breadcrumb-separator">/</span>
//           <span className="breadcrumb-current">Imported Contacts</span>
//         </div>
//         <h1 className="page-title">Contact Import Results</h1>
//         <p className="page-description">Review your imported contacts and statistics</p>
//       </div>

//       {/* Statistics Cards */}
//       <div className="statistics-grid">
//         <div className="stat-card total">
//           <div className="stat-number">{statistics.total}</div>
//           <div className="stat-label">Total Contacts</div>
//         </div>
//         <div className="stat-card subscribed">
//           <div className="stat-number">{statistics.subscribed}</div>
//           <div className="stat-label">Subscribed</div>
//         </div>
//         <div className="stat-card unsubscribed">
//           <div className="stat-number">{statistics.unsubscribed}</div>
//           <div className="stat-label">Unsubscribed</div>
//         </div>
//         <div className="stat-card bounced">
//           <div className="stat-number">{statistics.bounced}</div>
//           <div className="stat-label">Bounced</div>
//         </div>
//       </div>

//       {/* Date Range */}
//       <div className="date-range-section">
//         <div className="date-range-label">Date Range:</div>
//         <div className="date-range-value">{statistics.dateRange}</div>
//       </div>

//       {/* Contacts Table */}
//       <div className="contacts-table-container">
//         <div className="table-header">
//           <h3>Imported Contacts</h3>
//           <div className="table-actions">
//             <button className="btn-secondary">Export</button>
//             <button className="btn-secondary">Filter</button>
//           </div>
//         </div>

//         <div className="table-wrapper">
//           <table className="contacts-table">
//             <thead>
//               <tr>
//                 <th>
//                   <input type="checkbox" />
//                 </th>
//                 <th>Name</th>
//                 <th>Email</th>
//                 <th>Phone</th>
//                 <th>Company</th>
//                 <th>Status</th>
//                 <th>Actions</th>
//               </tr>
//             </thead>
//             <tbody>
//               {contacts.map((contact) => (
//                 <tr key={contact.id}>
//                   <td>
//                     <input type="checkbox" />
//                   </td>
//                   <td className="contact-name">{contact.name}</td>
//                   <td className="contact-email">{contact.email}</td>
//                   <td className="contact-phone">{contact.phone}</td>
//                   <td className="contact-company">{contact.company}</td>
//                   <td>
//                     <span className={`status-badge ${contact.status}`}>{contact.status}</span>
//                   </td>
//                   <td>
//                     <div className="action-buttons">
//                       <button className="action-btn edit" title="Edit">
//                         ✏️
//                       </button>
//                       <button className="action-btn delete" title="Delete">
//                         🗑️
//                       </button>
//                     </div>
//                   </td>
//                 </tr>
//               ))}
//             </tbody>
//           </table>
//         </div>
//       </div>

//       {/* Action Buttons */}
//       <div className="bottom-actions">
//         <button className="btn-secondary" onClick={onBack}>
//           Back to Lists
//         </button>
//         <button className="btn-primary">Create Campaign</button>
//       </div>
//     </div>
//   )
// }

// export default ContactsStatistics
