 import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { API_BASE_URL } from "../config"

 
 function Dashboard() {

   const navigate = useNavigate()
  const [projects, setProjects] = useState([]) // example for protected API data

  useEffect(() => {
    const sessionId = localStorage.getItem("session_id")

    // ✅ if no valid session, redirect to login
    if (!sessionId) {
      navigate("/login")
      return
    }

    // ✅ fetch protected data (optional)
    const fetchProjects = async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/projects/`, {
          headers: {
            "Content-Type": "application/json",
            "Authorization": sessionId,
          },
        })

        if (res.status === 401) {
          alert("Session expired. Please log in again.")
          localStorage.removeItem("session_id")
          navigate("/login")
          return
        }

        const data = await res.json()
        setProjects(data.projects || [])
      } catch (err) {
        console.error("Error fetching projects:", err)
      }
    }

    fetchProjects()
  }, [navigate])
  return (
    <div>
      <div className="card">
        <div className="card-header">
          <h2 className="card-title">Welcome to Email Campaigns Platform</h2>
          <p className="card-description">
            Manage your automated email campaigns, leads, and customer relationships all in one place.
          </p>
        </div>
        <div className="grid grid-cols-3">
          <div className="card">
            <h3 className="card-title">Active Campaigns</h3>
            <p style={{ fontSize: "2rem", fontWeight: "bold", color: "#3b82f6" }}>12</p>
            <p className="card-description">Currently running</p>
          </div>
          <div className="card">
            <h3 className="card-title">Total Leads</h3>
            <p style={{ fontSize: "2rem", fontWeight: "bold", color: "#10b981" }}>1,247</p>
            <p className="card-description">In your database</p>
          </div>
          <div className="card">
            <h3 className="card-title">Email Templates</h3>
            <p style={{ fontSize: "2rem", fontWeight: "bold", color: "#f59e0b" }}>28</p>
            <p className="card-description">Ready to use</p>
          </div>
        </div>
      </div>
    </div>
  )
}

export default Dashboard
